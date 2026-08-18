#!/usr/bin/env python3
"""Correlate isolated P-CAN TX timestamps with I-CAN reaction records."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional, Sequence

from powertrain_ican_fuzz.correlation_test.common import CANDIDATES


def load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def correlate(
    tx_records: Sequence[dict[str, object]],
    rx_records: Sequence[dict[str, object]],
    window_seconds: float,
    clock_offset_ms: float = 0.0,
) -> dict[str, object]:
    tx = [record for record in tx_records if record.get("event") == "tx" and record.get("status") == "sent"]
    rx = [record for record in rx_records if record.get("event") == "rx"]
    if not tx:
        raise ValueError("TX manifest contains no status=sent records")
    if not rx_records or rx_records[0].get("event") != "capture_start":
        raise ValueError("RX log has no capture_start record")

    capture_start_ns = int(rx_records[0]["epoch_ns"])
    first_tx_ns = min(int(record.get("send_return_epoch_ns", record["epoch_ns"])) for record in tx)
    adjusted_first_tx_ns = first_tx_ns + int(clock_offset_ms * 1_000_000)
    baseline_seconds = max(0.0, (adjusted_first_tx_ns - capture_start_ns) / 1_000_000_000)

    baseline_counts: Counter[str] = Counter()
    for record in rx:
        if int(record["epoch_ns"]) < adjusted_first_tx_ns:
            baseline_counts[str(record.get("reaction", "unknown"))] += 1

    trials: list[dict[str, object]] = []
    summary: dict[str, dict[str, object]] = defaultdict(
        lambda: {"trials": 0, "trials_with_expected_reaction": 0, "reaction_counts": Counter()},
    )
    window_ns = int(window_seconds * 1_000_000_000)
    for tx_record in tx:
        candidate = str(tx_record.get("candidate", tx_record.get("case", "unknown")))
        if candidate not in CANDIDATES:
            raise ValueError(f"unknown candidate in manifest: {candidate}")
        tx_ns = int(tx_record.get("send_return_epoch_ns", tx_record["epoch_ns"]))
        adjusted_tx_ns = tx_ns + int(clock_offset_ms * 1_000_000)
        matches = []
        for rx_record in rx:
            delta_ns = int(rx_record["epoch_ns"]) - adjusted_tx_ns
            if 0 <= delta_ns <= window_ns:
                matches.append({
                    "delta_ms": round(delta_ns / 1_000_000, 3),
                    "reaction": rx_record.get("reaction"),
                    "can_id": rx_record.get("can_id"),
                    "payload": rx_record.get("payload"),
                })
        expected = set(CANDIDATES[candidate]["expected_reactions"])
        expected_matches = [match for match in matches if match["reaction"] in expected]
        reaction_counts = Counter(str(match["reaction"]) for match in expected_matches)
        candidate_summary = summary[candidate]
        candidate_summary["trials"] = int(candidate_summary["trials"]) + 1
        if expected_matches:
            candidate_summary["trials_with_expected_reaction"] = (
                int(candidate_summary["trials_with_expected_reaction"]) + 1
            )
        counts = candidate_summary["reaction_counts"]
        assert isinstance(counts, Counter)
        counts.update(reaction_counts)
        trials.append({
            "candidate": candidate,
            "trial": tx_record.get("trial", tx_record.get("round")),
            "tx_utc": tx_record.get("utc"),
            "tx_payload": tx_record.get("payload"),
            "expected_reactions": sorted(expected),
            "expected_reaction_found": bool(expected_matches),
            "matches": matches,
        })

    serializable_summary: dict[str, object] = {}
    for candidate, values in summary.items():
        trial_count = int(values["trials"])
        hit_count = int(values["trials_with_expected_reaction"])
        expected = set(CANDIDATES[candidate]["expected_reactions"])
        baseline_expected_count = sum(baseline_counts[name] for name in expected)
        if baseline_expected_count:
            verdict = "baseline_also_active"
        elif hit_count == trial_count and trial_count >= 2:
            verdict = "repeatable_correlation"
        elif hit_count >= 2:
            verdict = "probable_correlation"
        elif hit_count == 1:
            verdict = "weak_single_occurrence"
        else:
            verdict = "not_reproduced"
        serializable_summary[candidate] = {
            "trials": trial_count,
            "trials_with_expected_reaction": hit_count,
            "baseline_expected_event_count": baseline_expected_count,
            "reaction_counts": dict(values["reaction_counts"]),
            "verdict": verdict,
        }

    return {
        "window_seconds": window_seconds,
        "clock_offset_ms": clock_offset_ms,
        "baseline_seconds_before_first_tx": round(baseline_seconds, 6),
        "baseline_reaction_counts": dict(baseline_counts),
        "candidate_summary": serializable_summary,
        "trials": trials,
    }


def print_report(result: dict[str, object]) -> None:
    print(
        f"[correlation] baseline={result['baseline_seconds_before_first_tx']}s, "
        f"window={result['window_seconds']}s, clock_offset={result['clock_offset_ms']}ms"
    )
    summaries = result["candidate_summary"]
    assert isinstance(summaries, dict)
    for candidate, values in summaries.items():
        assert isinstance(values, dict)
        print(
            f"[correlation] {candidate}: "
            f"hits={values['trials_with_expected_reaction']}/{values['trials']}, "
            f"baseline_events={values['baseline_expected_event_count']}, "
            f"verdict={values['verdict']}"
        )
        print(f"[correlation] reactions={values['reaction_counts']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Correlate P-CAN candidate TX with I-CAN reactions")
    parser.add_argument("--tx-manifest", type=Path, required=True)
    parser.add_argument("--rx-log", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=5.0)
    parser.add_argument(
        "--clock-offset-ms", type=float, default=0.0,
        help="add this offset to TX timestamps to align them to the RX computer",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.window_seconds <= 0:
        print("[correlation:error] window must be greater than zero", file=sys.stderr)
        return 2
    output = args.output or args.rx_log.with_suffix(".correlation.json")
    try:
        result = correlate(
            load_jsonl(args.tx_manifest), load_jsonl(args.rx_log),
            args.window_seconds, args.clock_offset_ms,
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print_report(result)
        print(f"[correlation] output: {output.resolve()}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[correlation:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
