#!/usr/bin/env python3
"""Bounded CAN transmitter supporting raw frames and DBC signal patching."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from can_common import (
    ConfigurationError,
    hostname,
    load_dbc,
    load_yaml_config,
    now_fields,
    open_can_bus,
    parse_assignment,
    parse_can_data,
    parse_int,
    protected_signal_names,
    require_module,
    resolve_message,
    resolve_path,
    shutdown_bus,
    signal_defaults,
    validate_frame_id,
    write_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="B-CAN에 제한된 횟수로 raw 또는 DBC 기반 CAN 프레임을 송신합니다."
    )
    parser.add_argument("--config", help="sender YAML 설정 파일")
    parser.add_argument("--channel", help="SocketCAN 채널 (기본: can0)")
    parser.add_argument("--interface", dest="interface_name", help="python-can interface (기본: socketcan)")
    parser.add_argument("--dbc", help="DBC 파일 경로")
    parser.add_argument("--id", dest="frame_id", help="CAN ID (예: 0x65A)")
    parser.add_argument("--message", help="DBC 메시지 이름 (예: BCM_01)")
    parser.add_argument("--data", help="raw 송신 payload (예: '00 01 02 03 04 05 06 07')")
    parser.add_argument("--set", dest="assignments", action="append", default=[], help="DBC 신호 설정 SIGNAL=VALUE")
    parser.add_argument("--base", choices=("live", "zero", "data"), help="DBC patch의 기준 payload")
    parser.add_argument("--base-data", help="--base data일 때 기준 payload")
    parser.add_argument("--base-timeout", type=float, help="live 기준 프레임 대기 시간(초)")
    parser.add_argument("--count", type=int, help="송신 횟수")
    parser.add_argument("--interval-ms", type=float, help="송신 간격(ms)")
    parser.add_argument("--output", help="송신 기록 JSONL 경로")
    parser.add_argument("--extended", action="store_true", help="raw ID를 29-bit extended로 송신")
    parser.add_argument("--fd", action="store_true", help="raw payload를 CAN FD 프레임으로 송신")
    parser.add_argument("--no-restore", action="store_true", help="DBC patch 후 원본 payload 복원 송신 안 함")
    parser.add_argument("--allow-protected", action="store_true", help="CRC/counter 추정 신호가 있는 DBC 메시지 patch 허용")
    parser.add_argument("--execute", action="store_true", help="실제로 CAN 버스에 송신 (없으면 preview만 수행)")
    return parser


def choose(cli_value: Any, config_value: Any, default: Any) -> Any:
    return cli_value if cli_value is not None else (config_value if config_value is not None else default)


def capture_live_payload(bus: Any, frame_id: int, is_extended: bool, timeout: float) -> bytes:
    print(f"[BASE] 0x{frame_id:X} 원본 프레임을 최대 {timeout:.1f}초 기다립니다...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = bus.recv(timeout=min(0.5, max(0.0, deadline - time.monotonic())))
        if message is None:
            continue
        if int(message.arbitration_id) == frame_id and bool(message.is_extended_id) == is_extended:
            payload = bytes(message.data)
            print(f"[BASE] 수신 완료: {payload.hex().upper()}")
            return payload
    raise RuntimeError(
        f"{timeout:.1f}초 동안 CAN ID 0x{frame_id:X}를 수신하지 못했습니다. "
        "버스/bitrate/DBC가 맞는지 확인하세요."
    )


def validate_length(payload: bytes, is_fd: bool, expected: Optional[int] = None) -> None:
    maximum = 64 if is_fd else 8
    if len(payload) > maximum:
        raise ConfigurationError(
            f"payload 길이 {len(payload)}는 {'CAN FD' if is_fd else 'Classic CAN'} 최대 {maximum}바이트를 초과합니다."
        )
    if expected is not None and len(payload) != expected:
        raise ConfigurationError(f"DBC 메시지는 {expected}바이트지만 payload는 {len(payload)}바이트입니다.")


def load_assignments(configured: Any, command_line: List[str]) -> Dict[str, Any]:
    if configured is None:
        result: Dict[str, Any] = {}
    elif isinstance(configured, dict):
        result = dict(configured)
    else:
        raise ConfigurationError("sender.set은 SIGNAL: VALUE mapping이어야 합니다.")
    for raw in command_line:
        name, value = parse_assignment(raw)
        result[name] = value
    return result


def create_message(
    frame_id: int,
    payload: bytes,
    is_extended: bool,
    is_fd: bool,
    bitrate_switch: bool,
) -> Any:
    can = require_module("can", "python-can")
    return can.Message(
        arbitration_id=frame_id,
        data=payload,
        is_extended_id=is_extended,
        is_fd=is_fd,
        bitrate_switch=bitrate_switch if is_fd else False,
    )


def tx_record(
    bus_name: str,
    channel: str,
    frame_id: int,
    payload: bytes,
    is_extended: bool,
    is_fd: bool,
    status: str,
    sequence: int,
    message_name: Optional[str] = None,
    signals: Optional[Dict[str, Any]] = None,
    kind: str = "inject",
) -> Dict[str, Any]:
    return {
        "record_type": "can_tx",
        **now_fields(),
        "host": hostname(),
        "bus": bus_name,
        "channel": channel,
        "kind": kind,
        "status": status,
        "sequence": sequence,
        "arbitration_id": frame_id,
        "arbitration_id_hex": f"0x{frame_id:X}",
        "dlc": len(payload),
        "data_hex": payload.hex().upper(),
        "is_extended_id": is_extended,
        "is_fd": is_fd,
        "message_name": message_name,
        "signals": signals,
    }


def run(args: argparse.Namespace) -> int:
    config, config_path = load_yaml_config(args.config)
    bus_cfg = config.get("bus", {})
    tx_cfg = config.get("sender", {})
    base_cfg = tx_cfg.get("base", {})
    transmit_cfg = tx_cfg.get("transmit", {})
    safety_cfg = tx_cfg.get("safety", {})

    interface_name = choose(args.interface_name, bus_cfg.get("interface"), "socketcan")
    channel = choose(args.channel, bus_cfg.get("channel"), "can0")
    bus_name = str(tx_cfg.get("bus_name", "b_can"))
    count = int(choose(args.count, transmit_cfg.get("count"), 1))
    interval_ms = float(choose(args.interval_ms, transmit_cfg.get("interval_ms"), 100.0))
    send_timeout = float(transmit_cfg.get("send_timeout_seconds", 1.0))
    max_count = int(safety_cfg.get("max_count", 100))
    min_interval_ms = float(safety_cfg.get("min_interval_ms", 10.0))
    allow_protected = bool(args.allow_protected or safety_cfg.get("allow_protected_dbc_patch", False))

    if count < 1 or count > max_count:
        raise ConfigurationError(f"count는 1~{max_count} 범위여야 합니다.")
    if count > 1 and interval_ms < min_interval_ms:
        raise ConfigurationError(
            f"반복 송신 interval_ms는 안전 제한 {min_interval_ms:g}ms 이상이어야 합니다."
        )

    configured_id = tx_cfg.get("id")
    frame_id = parse_int(args.frame_id if args.frame_id is not None else configured_id, "CAN ID") \
        if (args.frame_id is not None or configured_id is not None) else None
    message_name_arg = args.message if args.message is not None else tx_cfg.get("message")
    assignments = load_assignments(tx_cfg.get("set"), args.assignments)
    raw_data_value = args.data if args.data is not None else tx_cfg.get("data")
    dbc_path = (
        resolve_path(args.dbc, None)
        if args.dbc is not None
        else resolve_path(tx_cfg.get("dbc"), config_path)
    )

    raw_mode = raw_data_value is not None
    if raw_mode and assignments:
        raise ConfigurationError("raw data 송신과 DBC signal set은 동시에 사용할 수 없습니다.")
    if not raw_mode and not assignments:
        raise ConfigurationError("--data 또는 하나 이상의 --set SIGNAL=VALUE가 필요합니다.")

    bus = None
    definition = None
    base_payload: Optional[bytes] = None
    patched_values: Optional[Dict[str, Any]] = None
    protected: List[str] = []

    if raw_mode:
        if frame_id is None:
            raise ConfigurationError("raw 송신에는 CAN ID가 필요합니다.")
        is_extended = bool(args.extended or tx_cfg.get("extended", frame_id > 0x7FF))
        is_fd = bool(args.fd or tx_cfg.get("fd", False))
        bitrate_switch = bool(tx_cfg.get("bitrate_switch", False))
        payload = parse_can_data(raw_data_value)
        validate_frame_id(frame_id, is_extended)
        validate_length(payload, is_fd)
    else:
        if dbc_path is None:
            raise ConfigurationError("DBC 신호 송신에는 dbc 경로가 필요합니다.")
        database = load_dbc(dbc_path)
        definition = resolve_message(database, frame_id, message_name_arg)
        frame_id = int(definition.frame_id)
        message_name_arg = definition.name
        is_extended = bool(definition.is_extended_frame)
        is_fd = bool(getattr(definition, "is_fd", False))
        bitrate_switch = bool(tx_cfg.get("bitrate_switch", False))
        validate_frame_id(frame_id, is_extended)

        signal_names = {signal.name for signal in definition.signals}
        unknown = sorted(set(assignments) - signal_names)
        if unknown:
            raise ConfigurationError(
                f"{definition.name}에 없는 신호입니다: {', '.join(unknown)}"
            )
        protected = protected_signal_names(definition)
        if protected and not allow_protected:
            raise ConfigurationError(
                "이 메시지에는 CRC/counter로 추정되는 신호가 있어 단순 patch 시 거부될 수 있습니다: "
                + ", ".join(protected)
                + ". 의도한 실험이면 --allow-protected를 명시하세요."
            )

        base_mode = choose(args.base, base_cfg.get("mode"), "live")
        base_timeout = float(choose(args.base_timeout, base_cfg.get("timeout_seconds"), 5.0))
        base_data_value = args.base_data if args.base_data is not None else base_cfg.get("data")

        if base_mode == "live":
            bus = open_can_bus(interface_name, channel, receive_own_messages=False)
            base_payload = capture_live_payload(bus, frame_id, is_extended, base_timeout)
        elif base_mode == "data":
            if base_data_value is None:
                raise ConfigurationError("base mode가 data이면 base-data가 필요합니다.")
            base_payload = parse_can_data(base_data_value)
        elif base_mode == "zero":
            defaults = signal_defaults(definition)
            try:
                base_payload = bytes(definition.encode(defaults, scaling=True, padding=False, strict=True))
            except Exception as exc:
                raise RuntimeError(f"DBC 기본 payload 생성 실패: {type(exc).__name__}: {exc}") from exc
        else:
            raise ConfigurationError(f"지원하지 않는 base mode입니다: {base_mode}")

        validate_length(base_payload, is_fd, int(definition.length))
        try:
            base_values = definition.decode(base_payload, decode_choices=False, scaling=True)
            patched_values = dict(base_values)
            patched_values.update(assignments)
            payload = bytes(definition.encode(patched_values, scaling=True, padding=False, strict=True))
        except Exception as exc:
            raise RuntimeError(f"DBC payload patch 실패: {type(exc).__name__}: {exc}") from exc

    assert frame_id is not None
    if args.output is not None:
        output_path = resolve_path(args.output, None)
    elif tx_cfg.get("output"):
        output_path = resolve_path(tx_cfg.get("output"), config_path)
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base_dir = config_path.parent if config_path else Path.cwd()
        output_path = (base_dir / "logs" / f"{bus_name}_tx_{stamp}.jsonl").resolve()
    assert output_path is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)

    restore = bool(transmit_cfg.get("restore_original", True)) and not args.no_restore
    restore_count = max(1, int(transmit_cfg.get("restore_count", 1)))
    restore_delay_ms = max(0.0, float(transmit_cfg.get("restore_delay_ms", interval_ms)))
    execute = bool(args.execute)

    print(f"[MODE]  {'RAW' if raw_mode else 'DBC PATCH'} / {'EXECUTE' if execute else 'PREVIEW'}")
    print(f"[BUS]   {interface_name}:{channel} ({bus_name})")
    print(f"[FRAME] ID=0x{frame_id:X}, DLC={len(payload)}, DATA={payload.hex().upper()}")
    if definition is not None:
        print(f"[DBC]   {definition.name} / set={assignments}")
        print(f"[BASE]  {base_payload.hex().upper() if base_payload is not None else '-'}")
    print(f"[TX]    count={count}, interval={interval_ms:g}ms, restore={bool(restore and base_payload is not None)}")
    print(f"[LOG]   {output_path}")
    if not execute:
        print("[SAFE]  PREVIEW이므로 송신하지 않습니다. 확인 후 --execute를 추가하세요.")

    try:
        if execute and bus is None:
            bus = open_can_bus(interface_name, channel, receive_own_messages=False)

        with output_path.open("a", encoding="utf-8") as handle:
            write_jsonl(
                handle,
                {
                    "record_type": "tx_session_start",
                    **now_fields(),
                    "host": hostname(),
                    "bus": bus_name,
                    "interface": interface_name,
                    "channel": channel,
                    "execute": execute,
                    "dbc": str(dbc_path) if dbc_path else None,
                    "protected_signals": protected,
                },
            )
            for sequence in range(1, count + 1):
                if execute:
                    message = create_message(frame_id, payload, is_extended, is_fd, bitrate_switch)
                    bus.send(message, timeout=send_timeout)
                    status = "sent"
                else:
                    status = "preview"
                write_jsonl(
                    handle,
                    tx_record(
                        bus_name,
                        channel,
                        frame_id,
                        payload,
                        is_extended,
                        is_fd,
                        status,
                        sequence,
                        message_name_arg,
                        assignments if assignments else None,
                    ),
                )
                print(f"[TX {sequence:03}/{count:03}] {status.upper()} 0x{frame_id:X}#{payload.hex().upper()}")
                if sequence < count:
                    time.sleep(interval_ms / 1000.0)

            if restore and base_payload is not None:
                if restore_delay_ms:
                    time.sleep(restore_delay_ms / 1000.0)
                for sequence in range(1, restore_count + 1):
                    if execute:
                        message = create_message(
                            frame_id, base_payload, is_extended, is_fd, bitrate_switch
                        )
                        bus.send(message, timeout=send_timeout)
                        status = "sent"
                    else:
                        status = "preview"
                    write_jsonl(
                        handle,
                        tx_record(
                            bus_name,
                            channel,
                            frame_id,
                            base_payload,
                            is_extended,
                            is_fd,
                            status,
                            sequence,
                            message_name_arg,
                            kind="restore",
                        ),
                    )
                    print(
                        f"[RESTORE {sequence:03}/{restore_count:03}] "
                        f"{status.upper()} 0x{frame_id:X}#{base_payload.hex().upper()}"
                    )
                    if sequence < restore_count:
                        time.sleep(interval_ms / 1000.0)
            handle.flush()
    finally:
        if bus is not None:
            shutdown_bus(bus)

    print("[DONE] 송신 작업 완료")
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
