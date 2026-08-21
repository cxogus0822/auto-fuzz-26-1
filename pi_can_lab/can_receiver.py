#!/usr/bin/env python3
"""Raw CAN recorder with optional DBC decoding and change display."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from can_common import (
    ConfigurationError,
    find_signal_messages,
    hostname,
    json_safe,
    load_dbc,
    load_yaml_config,
    now_fields,
    open_can_bus,
    parse_int,
    resolve_path,
    shutdown_bus,
    write_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="모든 CAN 프레임을 JSONL로 저장하고 선택한 DBC 신호를 표시합니다."
    )
    parser.add_argument("--config", help="receiver YAML 설정 파일")
    parser.add_argument("--bus-name", help="로그에 기록할 논리 버스 이름 (b_can/i_can/c_can)")
    parser.add_argument("--channel", help="SocketCAN 채널 (기본: can0)")
    parser.add_argument("--interface", dest="interface_name", help="python-can interface (기본: socketcan)")
    parser.add_argument("--dbc", help="DBC 파일 경로; 생략하면 raw 기록만 수행")
    parser.add_argument("--output", help="출력 JSONL 경로")
    parser.add_argument("--duration", type=float, help="수신 시간(초); 0이면 Ctrl+C까지 계속")
    parser.add_argument("--watch-id", action="append", default=[], help="표시/해석할 CAN ID; 반복 가능")
    parser.add_argument("--watch-message", action="append", default=[], help="표시/해석할 DBC 메시지 이름")
    parser.add_argument("--watch-signal", action="append", default=[], help="변화를 표시할 DBC 신호 이름")
    parser.add_argument(
        "--print-mode",
        choices=("all", "decoded", "changes", "errors", "none"),
        help="화면 출력 모드",
    )
    parser.add_argument("--watch-only", action="store_true", help="watch 대상 ID만 JSONL에 저장")
    parser.add_argument("--decode-all", action="store_true", help="DBC에 존재하는 모든 ID를 해석")
    return parser


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def choose(cli_value: Any, config_value: Any, default: Any) -> Any:
    return cli_value if cli_value is not None else (config_value if config_value is not None else default)


def resolve_watch(
    database: Any,
    raw_ids: List[Any],
    message_names: List[str],
    signal_names: List[str],
) -> Tuple[Set[int], Set[str]]:
    ids = {parse_int(value, "watch ID") for value in raw_ids}
    signals = set(signal_names)

    if database is None and (message_names or signal_names):
        raise ConfigurationError("watch-message/watch-signal을 사용하려면 DBC가 필요합니다.")
    if database is None:
        return ids, signals

    for name in message_names:
        try:
            ids.add(database.get_message_by_name(name).frame_id)
        except KeyError as exc:
            raise ConfigurationError(f"DBC에 watch 메시지 '{name}'가 없습니다.") from exc

    found = find_signal_messages(database, signals)
    missing = sorted(name for name, messages in found.items() if not messages)
    if missing:
        raise ConfigurationError(f"DBC에 watch 신호가 없습니다: {', '.join(missing)}")
    for messages in found.values():
        ids.update(message.frame_id for message in messages)
    return ids, signals


def frame_record(message: Any, bus_name: str, channel: str) -> Dict[str, Any]:
    record = {
        "record_type": "can_rx",
        **now_fields(),
        "host": hostname(),
        "bus": bus_name,
        "channel": channel,
        "can_timestamp": getattr(message, "timestamp", None),
        "arbitration_id": int(message.arbitration_id),
        "arbitration_id_hex": f"0x{message.arbitration_id:X}",
        "dlc": int(message.dlc),
        "data_hex": bytes(message.data).hex().upper(),
        "is_extended_id": bool(message.is_extended_id),
        "is_remote_frame": bool(message.is_remote_frame),
        "is_error_frame": bool(message.is_error_frame),
        "is_fd": bool(getattr(message, "is_fd", False)),
        "bitrate_switch": bool(getattr(message, "bitrate_switch", False)),
        "error_state_indicator": bool(getattr(message, "error_state_indicator", False)),
    }
    is_rx = getattr(message, "is_rx", None)
    if is_rx is not None:
        record["direction"] = "rx" if is_rx else "tx"
    return record


def display_frame(record: Dict[str, Any], values: Optional[Dict[str, Any]] = None) -> None:
    prefix = f"[{record['wall_time']}] [{record['bus']}] {record['arbitration_id_hex']}"
    raw = f"DLC={record['dlc']} DATA={record['data_hex']}"
    if values is None:
        print(f"{prefix} {raw}")
    else:
        rendered = ", ".join(f"{name}={value}" for name, value in values.items())
        print(f"{prefix} {raw} | {record.get('message_name', '?')} | {rendered}")


def run(args: argparse.Namespace) -> int:
    config, config_path = load_yaml_config(args.config)
    bus_cfg = config.get("bus", {})
    rx_cfg = config.get("receiver", {})
    watch_cfg = rx_cfg.get("watch", {})

    interface_name = choose(args.interface_name, bus_cfg.get("interface"), "socketcan")
    channel = choose(args.channel, bus_cfg.get("channel"), "can0")
    bus_name = choose(args.bus_name, rx_cfg.get("bus_name"), channel)
    duration = float(choose(args.duration, rx_cfg.get("duration_seconds"), 0.0))
    recv_timeout = float(rx_cfg.get("recv_timeout_seconds", 1.0))
    stats_interval = float(rx_cfg.get("stats_interval_seconds", 5.0))
    flush_every = max(1, int(rx_cfg.get("flush_every", 50)))
    print_mode = choose(args.print_mode, rx_cfg.get("print_mode"), "changes")
    decode_all = bool(args.decode_all or rx_cfg.get("decode_all", False))
    log_all = not args.watch_only and bool(rx_cfg.get("log_all", True))

    dbc_path = (
        resolve_path(args.dbc, None)
        if args.dbc is not None
        else resolve_path(rx_cfg.get("dbc"), config_path)
    )
    database = load_dbc(dbc_path) if dbc_path else None

    configured_ids = as_list(watch_cfg.get("ids"))
    configured_messages = as_list(watch_cfg.get("messages"))
    configured_signals = as_list(watch_cfg.get("signals"))
    watch_ids, watch_signals = resolve_watch(
        database,
        configured_ids + args.watch_id,
        configured_messages + args.watch_message,
        configured_signals + args.watch_signal,
    )

    if args.output is not None:
        output_path = resolve_path(args.output, None)
    elif rx_cfg.get("output"):
        output_path = resolve_path(rx_cfg.get("output"), config_path)
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = config_path.parent if config_path else Path.cwd()
        output_path = (base / "logs" / f"{bus_name}_{stamp}.jsonl").resolve()
    assert output_path is not None
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[START] bus={bus_name}, interface={interface_name}, channel={channel}")
    print(f"[LOG]   {output_path}")
    print(f"[DBC]   {dbc_path if dbc_path else '사용 안 함(raw only)'}")
    if watch_ids:
        print("[WATCH] " + ", ".join(f"0x{value:X}" for value in sorted(watch_ids)))
    else:
        print("[WATCH] ID 제한 없음")
    print("[STOP]  Ctrl+C")

    bus = None
    started_mono = time.monotonic()
    last_stats = started_mono
    total = logged = decoded_count = decode_errors = 0
    last_values: Dict[Tuple[int, str], Any] = {}

    try:
        bus = open_can_bus(interface_name, channel, receive_own_messages=False)
        with output_path.open("a", encoding="utf-8") as handle:
            write_jsonl(
                handle,
                {
                    "record_type": "session_start",
                    **now_fields(),
                    "host": hostname(),
                    "bus": bus_name,
                    "channel": channel,
                    "interface": interface_name,
                    "dbc": str(dbc_path) if dbc_path else None,
                    "watch_ids": [f"0x{value:X}" for value in sorted(watch_ids)],
                    "watch_signals": sorted(watch_signals),
                },
            )
            handle.flush()

            while duration <= 0 or (time.monotonic() - started_mono) < duration:
                message = bus.recv(timeout=recv_timeout)
                now_mono = time.monotonic()
                if message is None:
                    if stats_interval > 0 and now_mono - last_stats >= stats_interval:
                        print(f"[STATS] received={total}, logged={logged}, decoded={decoded_count}, errors={decode_errors}")
                        last_stats = now_mono
                    continue

                total += 1
                frame_id = int(message.arbitration_id)
                watched = not watch_ids or frame_id in watch_ids
                record = frame_record(message, bus_name, channel)
                decoded_values: Optional[Dict[str, Any]] = None
                display_values: Optional[Dict[str, Any]] = None

                if database is not None and (decode_all or frame_id in watch_ids):
                    try:
                        definition = database.get_message_by_frame_id(frame_id)
                        decoded_values = definition.decode(
                            bytes(message.data), decode_choices=False, scaling=True
                        )
                        decoded_values = {key: json_safe(value) for key, value in decoded_values.items()}
                        record["message_name"] = definition.name
                        record["signals"] = decoded_values
                        decoded_count += 1
                        if watch_signals:
                            display_values = {
                                key: value for key, value in decoded_values.items() if key in watch_signals
                            }
                        else:
                            display_values = decoded_values
                    except KeyError:
                        record["dbc_status"] = "unknown_id"
                    except Exception as exc:
                        decode_errors += 1
                        record["dbc_status"] = "decode_error"
                        record["decode_error"] = f"{type(exc).__name__}: {exc}"

                if log_all or watched:
                    write_jsonl(handle, record)
                    logged += 1
                    if logged % flush_every == 0:
                        handle.flush()

                if print_mode == "all":
                    display_frame(record, display_values)
                elif print_mode == "decoded" and decoded_values is not None and watched:
                    display_frame(record, display_values)
                elif print_mode == "errors" and record.get("dbc_status") == "decode_error":
                    display_frame(record)
                    print(f"         DECODE ERROR: {record['decode_error']}")
                elif print_mode == "changes" and display_values is not None and watched:
                    changed: Dict[str, Any] = {}
                    for name, value in display_values.items():
                        key = (frame_id, name)
                        if key not in last_values or last_values[key] != value:
                            changed[name] = value
                        last_values[key] = value
                    if changed:
                        display_frame(record, changed)

                if stats_interval > 0 and now_mono - last_stats >= stats_interval:
                    print(f"[STATS] received={total}, logged={logged}, decoded={decoded_count}, errors={decode_errors}")
                    last_stats = now_mono

            write_jsonl(
                handle,
                {
                    "record_type": "session_end",
                    **now_fields(),
                    "host": hostname(),
                    "bus": bus_name,
                    "received": total,
                    "logged": logged,
                    "decoded": decoded_count,
                    "decode_errors": decode_errors,
                    "reason": "duration_complete",
                },
            )
            handle.flush()
    except KeyboardInterrupt:
        print("\n[STOP] 사용자 중지")
        with output_path.open("a", encoding="utf-8") as handle:
            write_jsonl(
                handle,
                {
                    "record_type": "session_end",
                    **now_fields(),
                    "host": hostname(),
                    "bus": bus_name,
                    "received": total,
                    "logged": logged,
                    "decoded": decoded_count,
                    "decode_errors": decode_errors,
                    "reason": "user_interrupt",
                },
            )
            handle.flush()
    finally:
        if bus is not None:
            shutdown_bus(bus)

    print(f"[DONE] received={total}, logged={logged}, decoded={decoded_count}, errors={decode_errors}")
    print(f"[DONE] log={output_path}")
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
