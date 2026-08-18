#!/usr/bin/env python3
"""Signal-aware, TX-only fuzzer for Motor_18 (CAN ID 0x670).

The default mode is a dry-run.  Live CAN transmission requires ``--live``.
Only three display/status signals are mutated; unrelated bits remain identical
to the captured baseline payload.
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
DEFAULT_INTERVAL_MS = 500.0
SIGNAL_CASES = {
    "start_stop_popup": [
        ("popup_button_disabled", 1),
        ("popup_button_enabled", 2),
    ],
    "rpm_warning": [("rpm_warning_on", 1)],
    "rpm_limit": [
        ("rpm_limit_3000", 3000),
        ("rpm_limit_4000", 4000),
        ("rpm_limit_5000", 5000),
        ("rpm_limit_6000", 6000),
    ],
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
    raise ValueError(f"unsupported signal: {signal}")


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


def default_manifest_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("tx_logs") / f"motor18_tx_{stamp}.jsonl"


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
            bus.send(can.Message(arbitration_id=CAN_ID, data=payload, is_extended_id=False), timeout=1.0)

    sent = 0
    try:
        with manifest.open("x", encoding="utf-8", buffering=1) as handle:
            def write(record: dict[str, object]) -> None:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()

            write({
                "event": "run_start", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "mode": "live" if live else "dry-run", "channel": channel,
                "can_id": f"0x{CAN_ID:X}", "message": MESSAGE_NAME,
                "base_payload": BASE_PAYLOAD.hex().upper(), "case_count": len(cases),
                "interval_ms": interval_ms,
            })
            for index, case in enumerate(cases):
                payload = case["payload"]
                assert isinstance(payload, bytes)
                record = {key: value for key, value in case.items() if key != "payload"}
                record.update({
                    "event": "tx", "utc": utc_now(), "epoch_ns": time.time_ns(),
                    "can_id": f"0x{CAN_ID:X}", "payload": payload.hex().upper(),
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
                if index + 1 < len(cases) and interval_ms:
                    time.sleep(interval_ms / 1000.0)
            write({
                "event": "run_end", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "status": "completed", "planned": len(cases), "sent": sent,
            })
    finally:
        if bus is not None:
            bus.shutdown()
    return sent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TX-only Motor_18 signal fuzzer; dry-run by default")
    parser.add_argument("--channel", default="can0")
    parser.add_argument(
        "--signals", nargs="+", choices=sorted(SIGNAL_CASES),
        default=["start_stop_popup", "rpm_warning", "rpm_limit"],
    )
    parser.add_argument("--rounds", type=positive_int, default=1)
    parser.add_argument("--interval-ms", type=nonnegative_float, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--live", action="store_true", help="actually transmit; omitted means dry-run")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest or default_manifest_path()
    try:
        cases = generate_cases(args.signals, args.rounds)
        if args.live:
            snapshot = interface_snapshot(args.channel)
            snapshot_path = manifest.with_suffix(".interface.txt")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(snapshot, encoding="utf-8")
        mode = "LIVE" if args.live else "DRY-RUN"
        print(f"[pcan-fuzzer] {mode}: ID=0x{CAN_ID:X}, cases={len(cases)}, channel={args.channel}")
        sent = run(cases, args.channel, manifest, args.interval_ms, args.live)
        print(f"[pcan-fuzzer] completed: planned={len(cases)}, sent={sent}")
        print(f"[pcan-fuzzer] manifest: {manifest.resolve()}")
        return 0
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"[pcan-fuzzer:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
