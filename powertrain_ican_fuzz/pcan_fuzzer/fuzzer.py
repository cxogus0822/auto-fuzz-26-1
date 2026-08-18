#!/usr/bin/env python3
"""Signal-aware, TX-only fuzzer for Motor_18 (CAN ID 0x670).

The default mode is a dry-run.  Live CAN transmission requires ``--live``.
Only allowlisted display/status signals are mutated; unrelated bits remain
identical to the captured baseline payload.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence


CAN_ID = 0x670
MESSAGE_NAME = "Motor_18"
BASE_PAYLOAD = bytes.fromhex("001010000001007C")
MOTOR07_BASE_PAYLOADS = (
    bytes.fromhex("80928BB67E421104"),
    bytes.fromhex("80928BB77E421104"),
)
MOTOR26_BASE_PAYLOADS = (
    bytes.fromhex("0110080100418200"),
    bytes.fromhex("AE10080100418200"),
)
DEFAULT_INTERVAL_MS = 500.0
SIGNAL_CASES = {
    "start_stop_popup": [
        ("popup_button_disabled", 1),
        ("popup_button_enabled", 2),
    ],
    "rpm_warning": [("rpm_warning_on", 1)],
    "rpm_limit": [
        (f"rpm_limit_{rpm}", rpm) for rpm in range(1000, 7001, 250)
    ],
    "cylinder_text_detail": [
        (f"cylinder_text_detail_{value}", value)
        for value in (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15)
    ],
    "hybrid_startstop_led": [
        ("hybrid_startstop_led_on", 1),
        ("hybrid_startstop_led_blink", 2),
    ],
    "deactivated_cylinder_count": [
        (f"deactivated_cylinder_count_{value}", value) for value in range(1, 8)
    ],
    "cylinder_text": [
        ("cylinder_text_disable", 1),
        ("cylinder_text_enable", 2),
        ("cylinder_text_rough", 3),
    ],
    "ethanol_text": [
        (f"ethanol_text_{value}", value) for value in range(1, 7)
    ],
}

PROFILES = {
    "safe": ["start_stop_popup", "rpm_warning", "rpm_limit"],
    "extended": [
        "start_stop_popup",
        "rpm_warning",
        "rpm_limit",
        "cylinder_text_detail",
        "hybrid_startstop_led",
        "deactivated_cylinder_count",
        "cylinder_text",
        "ethanol_text",
    ],
}

MOTOR07_CASES = {
    "intake_temp_qbit": [("intake_temp_qbit_error", 1)],
    "oil_temp_qbit": [("oil_temp_qbit_error", 1)],
    "coolant_temp_qbit": [("coolant_temp_qbit_error", 1)],
    "intake_temp": [(f"intake_temp_{value}", value) for value in (-18, 0, 30, 60, 90, 120)],
    "oil_temp": [(f"oil_temp_{value}", value) for value in (-20, 0, 40, 80, 120, 160)],
    "coolant_temp": [(f"coolant_temp_{value}", value) for value in (-18, 0, 30, 60, 90, 120)],
    "altitude_raw": [(f"altitude_raw_{value}", value) for value in (0, 64, 128, 192, 254)],
    "altitude_qbit": [("altitude_qbit_error", 1)],
}

MOTOR26_CASES = {
    "eflex_lamp": [(f"eflex_lamp_{value}", value) for value in (1, 2, 3)],
    "oil_min_warning": [("oil_min_warning_on", 1)],
    "oil_system_fault": [("oil_system_fault_on", 1)],
    "oil_max_warning": [("oil_max_warning_on", 1)],
    "motor_start_text": [
        (f"motor_start_text_{value}", value)
        for value in (1, 3, 4, 5, 6, 9, 10, 13, 14, 15)
    ],
    "electric_warning": [(f"electric_warning_{value}", value) for value in range(1, 8)],
    "system_lamp": [("system_lamp_on", 1)],
    "obd2_lamp": [("obd2_lamp_on", 1)],
    "hot_lamp": [("hot_lamp_on", 1)],
    "particle_lamp": [("particle_lamp_on", 1)],
    "oil_overfill_warning": [("oil_overfill_warning_on", 1)],
    "oil_underfill_warning": [("oil_underfill_warning_on", 1)],
}

MESSAGE_SPECS = {
    "motor18": {
        "can_id": CAN_ID,
        "message_name": MESSAGE_NAME,
        "base_payloads": (BASE_PAYLOAD,),
        "cases": SIGNAL_CASES,
    },
    "motor07": {
        "can_id": 0x640,
        "message_name": "Motor_07",
        "base_payloads": MOTOR07_BASE_PAYLOADS,
        "cases": MOTOR07_CASES,
    },
    "motor26": {
        "can_id": 0x3C7,
        "message_name": "Motor_26",
        "base_payloads": MOTOR26_BASE_PAYLOADS,
        "cases": MOTOR26_CASES,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def set_little_endian_bits(payload: bytes, start: int, length: int, raw_value: int) -> bytes:
    if raw_value < 0 or raw_value >= (1 << length):
        raise ValueError(f"raw value {raw_value} does not fit in {length} bits")
    packed = int.from_bytes(payload, "little")
    mask = ((1 << length) - 1) << start
    packed = (packed & ~mask) | (raw_value << start)
    return packed.to_bytes(len(payload), "little")


def mutate_signal(base: bytes, signal: str, physical_value: int) -> bytes:
    if len(base) != 8:
        raise ValueError("Motor_18 requires an 8-byte payload")
    if signal == "start_stop_popup":
        return set_little_endian_bits(base, 9, 2, physical_value)
    if signal == "rpm_warning":
        return set_little_endian_bits(base, 55, 1, physical_value)
    if signal == "rpm_limit":
        if physical_value % 50:
            raise ValueError("rpm_limit must be divisible by 50")
        return set_little_endian_bits(base, 56, 8, physical_value // 50)
    if signal == "cylinder_text_detail":
        return set_little_endian_bits(base, 16, 4, physical_value)
    if signal == "hybrid_startstop_led":
        return set_little_endian_bits(base, 43, 2, physical_value)
    if signal == "deactivated_cylinder_count":
        return set_little_endian_bits(base, 47, 3, physical_value)
    if signal == "cylinder_text":
        return set_little_endian_bits(base, 50, 2, physical_value)
    if signal == "ethanol_text":
        return set_little_endian_bits(base, 52, 3, physical_value)
    raise ValueError(f"unsupported signal: {signal}")


def _scaled_raw(physical_value: int, scale: float, offset: float) -> int:
    raw = round((physical_value - offset) / scale)
    if abs((raw * scale + offset) - physical_value) > 1e-6:
        raise ValueError(f"physical value {physical_value} is not exactly encodable")
    return raw


def mutate_message_signal(
    message_key: str, base: bytes, signal: str, physical_value: int,
) -> bytes:
    if message_key == "motor18":
        return mutate_signal(base, signal, physical_value)
    if message_key == "motor07":
        if signal == "intake_temp":
            layout = (8, 8, _scaled_raw(physical_value, 0.75, -48))
        elif signal == "oil_temp":
            layout = (16, 8, _scaled_raw(physical_value, 1.0, -60))
        elif signal == "coolant_temp":
            layout = (24, 8, _scaled_raw(physical_value, 0.75, -48))
        else:
            layouts = {
                "intake_temp_qbit": (0, 1, physical_value),
                "oil_temp_qbit": (1, 1, physical_value),
                "coolant_temp_qbit": (2, 1, physical_value),
                "altitude_raw": (32, 8, physical_value),
                "altitude_qbit": (46, 1, physical_value),
            }
            try:
                layout = layouts[signal]
            except KeyError as exc:
                raise ValueError(f"unsupported signal for {message_key}: {signal}") from exc
    elif message_key == "motor26":
        layouts = {
            "eflex_lamp": (8, 2, physical_value),
            "oil_min_warning": (13, 1, physical_value),
            "oil_system_fault": (22, 1, physical_value),
            "oil_max_warning": (23, 1, physical_value),
            "motor_start_text": (32, 4, physical_value),
            "electric_warning": (28, 4, physical_value),
            "system_lamp": (48, 1, physical_value),
            "obd2_lamp": (49, 1, physical_value),
            "hot_lamp": (50, 1, physical_value),
            "particle_lamp": (51, 1, physical_value),
            "oil_overfill_warning": (26, 1, physical_value),
            "oil_underfill_warning": (56, 1, physical_value),
        }
        try:
            layout = layouts[signal]
        except KeyError as exc:
            raise ValueError(f"unsupported signal for {message_key}: {signal}") from exc
    else:
        raise ValueError(f"unsupported message: {message_key}")
    start, length, raw_value = layout
    return set_little_endian_bits(base, start, length, raw_value)


def generate_message_cases(
    message_key: str, signals: Sequence[str], rounds: int,
) -> list[dict[str, object]]:
    spec = MESSAGE_SPECS[message_key]
    signal_cases = spec["cases"]
    base_payloads = spec["base_payloads"]
    assert isinstance(signal_cases, dict)
    assert isinstance(base_payloads, tuple)
    cases: list[dict[str, object]] = []
    sequence = 0
    for round_number in range(1, rounds + 1):
        for signal in signals:
            if signal not in signal_cases:
                raise ValueError(f"signal {signal!r} is not valid for {message_key}")
            for label, value in signal_cases[signal]:
                for base_index, base in enumerate(base_payloads):
                    sequence += 1
                    cases.append({
                        "sequence": sequence,
                        "round": round_number,
                        "base_index": base_index,
                        "signal": signal,
                        "case": label,
                        "physical_value": value,
                        "payload": mutate_message_signal(message_key, base, signal, value),
                    })
    return cases


def generate_cases(signals: Sequence[str], rounds: int) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    sequence = 0
    for round_number in range(1, rounds + 1):
        for signal in signals:
            for label, value in SIGNAL_CASES[signal]:
                sequence += 1
                payload = mutate_signal(BASE_PAYLOAD, signal, value)
                cases.append({
                    "sequence": sequence,
                    "round": round_number,
                    "signal": signal,
                    "case": label,
                    "physical_value": value,
                    "payload": payload,
                })
    return cases


def default_manifest_path(message_key: str = "motor18") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("tx_logs") / f"{message_key}_tx_{stamp}.jsonl"


def interface_snapshot(channel: str) -> str:
    result = subprocess.run(
        ["ip", "-details", "-statistics", "link", "show", channel],
        capture_output=True, text=True, check=False,
    )
    output = result.stdout or result.stderr
    if result.returncode:
        raise RuntimeError(f"failed to inspect {channel}: {output.strip()}")
    return output


def run(
    cases: Sequence[dict[str, object]],
    channel: str,
    manifest: Path,
    interval_ms: float,
    live: bool,
    sender: Optional[Callable[[bytes], None]] = None,
    progress_every: int = 0,
    can_id: int = CAN_ID,
    message_name: str = MESSAGE_NAME,
    base_payloads: Sequence[bytes] = (BASE_PAYLOAD,),
) -> int:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    bus = None
    if live and sender is None:
        try:
            import can  # type: ignore
        except ImportError as exc:
            raise RuntimeError("python-can is required") from exc
        bus = can.Bus(interface="socketcan", channel=channel, receive_own_messages=False)

        def sender(payload: bytes) -> None:
            bus.send(can.Message(arbitration_id=can_id, data=payload, is_extended_id=False), timeout=1.0)

    sent = 0
    try:
        with manifest.open("x", encoding="utf-8", buffering=1) as handle:
            def write(record: dict[str, object]) -> None:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()

            write({
                "event": "run_start", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "mode": "live" if live else "dry-run", "channel": channel,
                "can_id": f"0x{can_id:X}", "message": message_name,
                "base_payloads": [payload.hex().upper() for payload in base_payloads],
                "case_count": len(cases),
                "interval_ms": interval_ms,
            })
            try:
                for index, case in enumerate(cases):
                    payload = case["payload"]
                    assert isinstance(payload, bytes)
                    record = {key: value for key, value in case.items() if key != "payload"}
                    record.update({
                        "event": "tx", "utc": utc_now(), "epoch_ns": time.time_ns(),
                        "can_id": f"0x{can_id:X}", "payload": payload.hex().upper(),
                        "dlc": len(payload), "status": "planned",
                    })
                    try:
                        if live:
                            assert sender is not None
                            sender(payload)
                            sent += 1
                            record["status"] = "sent"
                            record["send_return_epoch_ns"] = time.time_ns()
                        else:
                            record["status"] = "dry-run"
                        write(record)
                    except Exception as exc:
                        record["status"] = "send_error"
                        record["error"] = f"{type(exc).__name__}: {exc}"
                        write(record)
                        raise
                    completed = index + 1
                    if progress_every and (completed % progress_every == 0 or completed == len(cases)):
                        print(
                            f"[pcan-fuzzer] progress: {completed}/{len(cases)}, sent={sent}",
                            flush=True,
                        )
                    if completed < len(cases) and interval_ms:
                        time.sleep(interval_ms / 1000.0)
            except KeyboardInterrupt:
                write({
                    "event": "run_end", "utc": utc_now(), "epoch_ns": time.time_ns(),
                    "status": "interrupted", "planned": len(cases), "sent": sent,
                })
                raise
            write({
                "event": "run_end", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "status": "completed", "planned": len(cases), "sent": sent,
            })
    finally:
        if bus is not None:
            bus.shutdown()
    return sent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TX-only Powertrain signal fuzzer; dry-run by default")
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--message", choices=sorted(MESSAGE_SPECS), default="motor18")
    parser.add_argument(
        "--profile", choices=sorted(PROFILES), default="safe",
        help="safe=28 cases/round, extended=59 cases/round; ignored when --signals is given",
    )
    parser.add_argument(
        "--signals", nargs="+",
        default=None,
    )
    parser.add_argument("--rounds", type=positive_int, default=1)
    parser.add_argument("--interval-ms", type=nonnegative_float, default=DEFAULT_INTERVAL_MS)
    parser.add_argument(
        "--progress-every", type=positive_int, default=10,
        help="print progress every N planned frames (default: 10)",
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--live", action="store_true", help="actually transmit; omitted means dry-run")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest or default_manifest_path(args.message)
    try:
        spec = MESSAGE_SPECS[args.message]
        signal_cases = spec["cases"]
        assert isinstance(signal_cases, dict)
        if args.signals is not None:
            signals = args.signals
        elif args.message == "motor18":
            signals = PROFILES[args.profile]
        else:
            signals = list(signal_cases)
        cases = generate_message_cases(args.message, signals, args.rounds)
        can_id = int(spec["can_id"])
        message_name = str(spec["message_name"])
        base_payloads = spec["base_payloads"]
        assert isinstance(base_payloads, tuple)
        if args.live:
            snapshot = interface_snapshot(args.channel)
            snapshot_path = manifest.with_suffix(".interface.txt")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(snapshot, encoding="utf-8")
        mode = "LIVE" if args.live else "DRY-RUN"
        print(
            f"[pcan-fuzzer] {mode}: ID=0x{can_id:X}, message={message_name}, "
            f"cases={len(cases)}, channel={args.channel}"
        )
        sent = run(
            cases, args.channel, manifest, args.interval_ms, args.live,
            progress_every=args.progress_every,
            can_id=can_id,
            message_name=message_name,
            base_payloads=base_payloads,
        )
        print(f"[pcan-fuzzer] completed: planned={len(cases)}, sent={sent}")
        print(f"[pcan-fuzzer] manifest: {manifest.resolve()}")
        return 0
    except KeyboardInterrupt:
        print("\n[pcan-fuzzer] interrupted by user; partial manifest was saved", file=sys.stderr)
        return 130
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"[pcan-fuzzer:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
