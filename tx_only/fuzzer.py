#!/usr/bin/env python3
"""Hazard-message mutation and transmission only.

This program deliberately contains no receive loop, monitor, DBC analysis, UDS,
or replay workflow.  It mutates a base payload, optionally transmits the results
on one SocketCAN interface, and writes an application-side TX manifest for the
separate monitoring PC.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from src.mutation.mutator import Mutator


# Integrated DBC: 0x366 Blinkmodi_02, including BM_Warnblinken.
HAZARD_CAN_ID = 0x366
HAZARD_MESSAGE_NAME = "Blinkmodi_02"
DEFAULT_BASE_PAYLOAD = bytes.fromhex("00000000200000F0")
DEFAULT_MUTATION_COUNT = 256
DEFAULT_INTERVAL_MS = 10.0


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def parse_payload(value: str) -> bytes:
    compact = value.replace(" ", "").replace("_", "")
    if compact.lower().startswith("0x"):
        compact = compact[2:]
    if not compact or len(compact) % 2:
        raise argparse.ArgumentTypeError("payload must contain complete hexadecimal bytes")
    try:
        payload = bytes.fromhex(compact)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("payload must be hexadecimal") from exc
    if not 1 <= len(payload) <= 8:
        raise argparse.ArgumentTypeError("Classic CAN payload must contain 1 to 8 bytes")
    return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def default_manifest_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("tx_logs") / f"hazard_tx_{stamp}.jsonl"


def interface_snapshot(channel: str) -> str:
    result = subprocess.run(
        ["ip", "-details", "-statistics", "link", "show", channel],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout or result.stderr
    if result.returncode:
        raise RuntimeError(f"failed to inspect {channel}: {output.strip()}")
    return output


def generate_mutations(
    base_payload: bytes,
    count: int,
    max_operations: int,
    allow_dlc_change: bool,
    include_original: bool,
) -> list[bytes]:
    """Reuse the repository Mutator without monitor-derived weights."""
    weights = {
        "manager.budget": count,
        "manager.max_ops": max_operations,
        "manager.structural": allow_dlc_change,
        "manager.include_original": include_original,
    }
    payloads = Mutator(
        data=base_payload,
        weights=weights,
        min_length=1,
    ).mutate_manager()
    if not allow_dlc_change:
        payloads = [payload for payload in payloads if len(payload) == len(base_payload)]
    return payloads[:count]


def _write_record(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def mutation_summary(base_payload: bytes, payload: bytes) -> dict[str, Any]:
    overlap = min(len(base_payload), len(payload))
    xor_bytes = bytes(
        base_payload[index] ^ payload[index]
        for index in range(overlap)
    )
    changed = [index for index, value in enumerate(xor_bytes) if value]
    changed.extend(range(overlap, max(len(base_payload), len(payload))))
    return {
        "length_delta": len(payload) - len(base_payload),
        "changed_byte_indexes": changed,
        "xor_hex": xor_bytes.hex().upper(),
        "changed_bit_count": sum(value.bit_count() for value in xor_bytes),
    }


def run_transmission(
    payloads: Sequence[bytes],
    channel: str,
    manifest_path: Path,
    interval_ms: float,
    live: bool,
    base_payload: bytes,
    allow_dlc_change: bool,
    send_payload: Optional[Callable[[bytes], None]] = None,
) -> int:
    """Write every attempted mutation to a manifest and optionally transmit it.

    ``send_payload`` is dependency injection for tests.  In normal live mode a
    SocketCAN Bus is opened for transmission only; no receive call is made.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bus = None
    sender = send_payload
    can_module = None

    if live and sender is None:
        try:
            import can  # type: ignore
        except ImportError as exc:
            raise RuntimeError("python-can is required; activate .venv first") from exc
        can_module = can
        bus = can.Bus(
            interface="socketcan",
            channel=channel,
            receive_own_messages=False,
        )

        def socketcan_send(payload: bytes) -> None:
            message = can_module.Message(
                arbitration_id=HAZARD_CAN_ID,
                data=payload,
                is_extended_id=False,
            )
            bus.send(message, timeout=1.0)

        sender = socketcan_send

    sent = 0
    try:
        with manifest_path.open("x", encoding="utf-8", buffering=1) as handle:
            _write_record(handle, {
                "event": "run_start",
                "utc": utc_now(),
                "epoch_ns": time.time_ns(),
                "monotonic_ns": time.monotonic_ns(),
                "mode": "live" if live else "dry-run",
                "channel": channel,
                "can_id": f"0x{HAZARD_CAN_ID:X}",
                "message": HAZARD_MESSAGE_NAME,
                "base_payload": base_payload.hex().upper(),
                "mutation_count": len(payloads),
                "interval_ms": interval_ms,
                "allow_dlc_change": allow_dlc_change,
            })

            for sequence, payload in enumerate(payloads, start=1):
                record = {
                    "event": "tx",
                    "sequence": sequence,
                    "utc": utc_now(),
                    "epoch_ns": time.time_ns(),
                    "monotonic_ns": time.monotonic_ns(),
                    "channel": channel,
                    "can_id": f"0x{HAZARD_CAN_ID:X}",
                    "payload": payload.hex().upper(),
                    "dlc": len(payload),
                    "status": "planned",
                    "mutation": mutation_summary(base_payload, payload),
                }
                try:
                    if live:
                        assert sender is not None
                        sender(payload)
                        sent += 1
                        record["status"] = "sent"
                        record["send_return_epoch_ns"] = time.time_ns()
                    else:
                        record["status"] = "dry-run"
                    _write_record(handle, record)
                except Exception as exc:
                    record["status"] = "send_error"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    _write_record(handle, record)
                    raise

                if sequence != len(payloads) and interval_ms:
                    time.sleep(interval_ms / 1000.0)

            _write_record(handle, {
                "event": "run_end",
                "utc": utc_now(),
                "epoch_ns": time.time_ns(),
                "monotonic_ns": time.monotonic_ns(),
                "status": "completed",
                "planned": len(payloads),
                "sent": sent,
            })
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(error) from exc
    finally:
        if bus is not None:
            bus.shutdown()

    return sent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TX-only hazard CAN fuzzer (fixed ID 0x366; no receive/monitor/UDS)",
    )
    parser.add_argument("--channel", default="can0")
    parser.add_argument(
        "--base-payload",
        type=parse_payload,
        default=DEFAULT_BASE_PAYLOAD,
        metavar="HEX",
        help="mutation base payload (default: 00000000200000F0)",
    )
    parser.add_argument("--count", type=positive_int, default=DEFAULT_MUTATION_COUNT)
    parser.add_argument("--max-operations", type=positive_int, default=3)
    parser.add_argument("--interval-ms", type=nonnegative_float, default=DEFAULT_INTERVAL_MS)
    parser.add_argument(
        "--allow-dlc-change",
        action="store_true",
        help="allow structural mutations; default preserves the 8-byte DLC",
    )
    parser.add_argument("--include-original", action="store_true")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually transmit; without this flag the command is a dry-run",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest or default_manifest_path()

    try:
        payloads = generate_mutations(
            base_payload=args.base_payload,
            count=args.count,
            max_operations=args.max_operations,
            allow_dlc_change=args.allow_dlc_change,
            include_original=args.include_original,
        )
        if not payloads:
            raise RuntimeError("Mutator did not produce any payload")

        if args.live:
            snapshot = interface_snapshot(args.channel)
            snapshot_path = manifest.with_suffix(".interface.txt")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with snapshot_path.open("x", encoding="utf-8") as handle:
                handle.write(snapshot)
            print(
                f"[tx-only] LIVE: {len(payloads)} mutation(s), "
                f"ID=0x{HAZARD_CAN_ID:X}, channel={args.channel}"
            )
        else:
            print(
                f"[tx-only] DRY-RUN: {len(payloads)} mutation(s), "
                f"ID=0x{HAZARD_CAN_ID:X}; no CAN frame will be sent"
            )

        sent = run_transmission(
            payloads=payloads,
            channel=args.channel,
            manifest_path=manifest,
            interval_ms=args.interval_ms,
            live=args.live,
            base_payload=args.base_payload,
            allow_dlc_change=args.allow_dlc_change,
        )
        print(f"[tx-only] completed: planned={len(payloads)}, sent={sent}")
        print(f"[tx-only] manifest: {manifest.resolve()}")
        return 0
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"[tx-only:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
