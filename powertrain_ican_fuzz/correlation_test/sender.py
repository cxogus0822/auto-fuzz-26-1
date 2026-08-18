#!/usr/bin/env python3
"""Transmit one isolated candidate at a time and timestamp every trial."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from powertrain_ican_fuzz.correlation_test.common import CANDIDATES, candidate_payload
from powertrain_ican_fuzz.pcan_fuzzer.fuzzer import (
    interface_snapshot,
    nonnegative_float,
    positive_int,
    run,
)


def default_manifest_path(candidate: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path("tx_logs") / f"correlation_{candidate}_{stamp}.jsonl"


def generate_trials(candidate: str, trials: int) -> list[dict[str, object]]:
    spec = CANDIDATES[candidate]
    payload = candidate_payload(candidate)
    return [
        {
            "sequence": trial,
            "round": trial,
            "trial": trial,
            "candidate": candidate,
            "signal": spec["signal"],
            "case": candidate,
            "physical_value": spec["physical_value"],
            "payload": payload,
        }
        for trial in range(1, trials + 1)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated P-CAN candidate sender; dry-run by default",
    )
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--trials", type=positive_int, default=3)
    parser.add_argument(
        "--gap-seconds", type=nonnegative_float, default=10.0,
        help="delay between single-frame trials (default: 10)",
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    spec = CANDIDATES[args.candidate]
    payload = candidate_payload(args.candidate)
    manifest = args.manifest or default_manifest_path(args.candidate)
    cases = generate_trials(args.candidate, args.trials)
    try:
        if args.live:
            snapshot = interface_snapshot(args.channel)
            snapshot_path = manifest.with_suffix(".interface.txt")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(snapshot, encoding="utf-8")
        mode = "LIVE" if args.live else "DRY-RUN"
        print(
            f"[correlation-sender] {mode}: candidate={args.candidate}, "
            f"ID=0x{int(spec['can_id']):X}, payload={payload.hex().upper()}, "
            f"trials={args.trials}, gap={args.gap_seconds}s",
            flush=True,
        )
        sent = run(
            cases=cases,
            channel=args.channel,
            manifest=manifest,
            interval_ms=(args.gap_seconds * 1000.0) if args.live else 0,
            live=args.live,
            progress_every=1,
            can_id=int(spec["can_id"]),
            message_name=str(spec["message_name"]),
            base_payloads=(spec["base_payload"],),
        )
        print(f"[correlation-sender] completed: sent={sent}")
        print(f"[correlation-sender] manifest: {manifest.resolve()}")
        return 0
    except KeyboardInterrupt:
        print("\n[correlation-sender] interrupted; partial manifest saved", file=sys.stderr)
        return 130
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"[correlation-sender:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
