#!/usr/bin/env python3
"""Capture only the I-CAN reactions relevant to the two candidate trials."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


TARGET_IDS = {
    0x17FD0200: "OBDC_Funktionaler_Req_All",
    0x17FC0214: "OBDC_ZR_Req",
    0x17FE0214: "OBDC_ZR_Resp",
    0x17FC0373: "FoD_ZR_Req",
    0x17FE0373: "FoD_ZR_Resp",
    0x1B000010: "NMH_Gateway",
    0x1A555564: "FoD_01",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path("rx_logs") / f"correlation_ican_{stamp}.jsonl"


def decode_reaction(can_id: int, payload: bytes) -> tuple[str, dict[str, object]]:
    if can_id == 0x17FD0200:
        if len(payload) >= 3 and payload[:3] == bytes.fromhex("023E80"):
            return "tester_present", {"uds_service": "TesterPresent", "suppress_response": True}
        return "obdc_functional_request", {}
    if can_id == 0x17FC0214:
        return "obdc_zr_request", {}
    if can_id == 0x17FE0214:
        return "obdc_zr_response", {}
    if can_id == 0x17FC0373:
        return "fod_request", {}
    if can_id == 0x17FE0373:
        return "fod_response", {}
    packed = int.from_bytes(payload, "little")
    if can_id == 0x1B000010:
        return "gateway_nm", {"car_wakeup": (packed >> 22) & 0x1}
    if can_id == 0x1A555564:
        return "fod_transmission", {"transmission_info": (packed >> 60) & 0x3}
    return "unknown", {}


def monitor(channel: str, duration: float, baseline_seconds: float, output: Path) -> Counter[str]:
    try:
        import can  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-can is required") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    filters = [
        {"can_id": can_id, "can_mask": 0x1FFFFFFF, "extended": True}
        for can_id in TARGET_IDS
    ]
    bus = can.Bus(
        interface="socketcan", channel=channel, receive_own_messages=False,
        can_filters=filters,
    )
    counts: Counter[str] = Counter()
    previous_values: dict[tuple[int, str], object] = {}
    started_monotonic = time.monotonic()
    deadline = started_monotonic + duration
    try:
        with output.open("x", encoding="utf-8", buffering=1) as handle:
            def write(record: dict[str, object]) -> None:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

            write({
                "event": "capture_start", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "channel": channel, "duration_seconds": duration,
                "baseline_seconds": baseline_seconds,
                "target_ids": {f"0x{key:X}": value for key, value in TARGET_IDS.items()},
            })
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                message = bus.recv(timeout=min(1.0, remaining))
                if message is None or not message.is_extended_id:
                    continue
                can_id = message.arbitration_id
                if can_id not in TARGET_IDS:
                    continue
                elapsed_ms = (time.monotonic() - started_monotonic) * 1000.0
                payload = bytes(message.data)
                reaction, fields = decode_reaction(can_id, payload)
                record: dict[str, object] = {
                    "event": "rx", "utc": utc_now(), "epoch_ns": time.time_ns(),
                    "bus_timestamp": message.timestamp,
                    "capture_elapsed_ms": round(elapsed_ms, 3),
                    "phase": "baseline" if elapsed_ms < baseline_seconds * 1000.0 else "observation",
                    "channel": channel, "can_id": f"0x{can_id:X}",
                    "message": TARGET_IDS[can_id], "payload": payload.hex().upper(),
                    "dlc": len(payload), "reaction": reaction,
                }
                record.update(fields)
                for field_name, value in fields.items():
                    key = (can_id, field_name)
                    previous = previous_values.get(key)
                    record[f"previous_{field_name}"] = previous
                    record[f"{field_name}_changed"] = previous is not None and previous != value
                    previous_values[key] = value
                    if field_name == "car_wakeup" and value == 1 and previous == 0:
                        record["reaction"] = "gateway_wakeup_transition"
                    elif field_name == "transmission_info" and previous is not None and previous != value:
                        record["reaction"] = "fod_transmission_change"
                counts[str(record["reaction"])] += 1
                write(record)
            write({
                "event": "capture_end", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "counts": dict(counts),
            })
    finally:
        bus.shutdown()
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Passive I-CAN reaction monitor")
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--duration", type=positive_float, default=90.0)
    parser.add_argument(
        "--baseline-seconds", type=positive_float, default=15.0,
        help="initial capture interval labelled baseline (default: 15)",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baseline_seconds >= args.duration:
        print("[reaction-monitor:error] baseline must be shorter than duration", file=sys.stderr)
        return 2
    output = args.output or default_output_path()
    try:
        print(
            f"[reaction-monitor] PASSIVE: channel={args.channel}, duration={args.duration}s, "
            f"baseline={args.baseline_seconds}s",
            flush=True,
        )
        print(
            f"[reaction-monitor] Start P-CAN candidate after {args.baseline_seconds}s",
            flush=True,
        )
        counts = monitor(args.channel, args.duration, args.baseline_seconds, output)
        print(f"[reaction-monitor] completed: {dict(counts)}")
        print(f"[reaction-monitor] output: {output.resolve()}")
        return 0
    except KeyboardInterrupt:
        print("\n[reaction-monitor] interrupted", file=sys.stderr)
        return 130
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"[reaction-monitor:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
