#!/usr/bin/env python3
"""Correlate a TX manifest with passive I/P-CAN receiver JSONL logs."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from can_common import ConfigurationError, json_safe, load_dbc


FrameKey = Tuple[int, bool]


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"숫자가 아닙니다: {value}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 유한한 숫자여야 합니다.")
    return parsed


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise ConfigurationError(f"JSONL 파일을 찾을 수 없습니다: {path}")
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigurationError(
                    f"{path}:{line_number} JSON 해석 실패: {exc}"
                ) from exc
            if isinstance(item, dict):
                records.append(item)
    return records


def parse_can_id(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ConfigurationError(f"CAN ID를 해석할 수 없습니다: {value!r}")


def parse_data(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ConfigurationError(f"payload를 해석할 수 없습니다: {value!r}")
    return bytes.fromhex(value)


def last_tx_session(records: Sequence[Dict[str, Any]]) -> Sequence[Dict[str, Any]]:
    starts = [
        index
        for index, record in enumerate(records)
        if record.get("record_type") == "tx_session_start"
        or record.get("event") == "run_start"
    ]
    return records[starts[-1]:] if starts else records


def load_tx_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for record in last_tx_session(load_jsonl(path)):
        is_pi_sender = record.get("record_type") == "can_tx"
        is_tx_only = record.get("event") == "tx"
        if not (is_pi_sender or is_tx_only) or record.get("status") != "sent":
            continue
        timestamp = (
            record.get("send_attempt_wall_time_ns")
            or record.get("epoch_ns")
            or record.get("wall_time_ns")
        )
        if timestamp is None:
            continue
        events.append({
            "time_ns": int(timestamp),
            "sequence": int(record.get("sequence", len(events) + 1)),
            "arbitration_id": parse_can_id(
                record.get("arbitration_id", record.get("can_id"))
            ),
            "is_extended_id": bool(record.get("is_extended_id", False)),
            "payload": parse_data(record.get("data_hex", record.get("payload"))),
            "kind": record.get("kind", "mutation"),
            "mutation": record.get("mutation"),
        })
    if not events:
        raise ConfigurationError(f"마지막 TX session에 status=sent 기록이 없습니다: {path}")
    return sorted(events, key=lambda event: event["time_ns"])


def load_rx_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for record in load_jsonl(path):
        is_pi_receiver = record.get("record_type") == "can_rx"
        is_monitor = record.get("event") == "rx"
        if not (is_pi_receiver or is_monitor):
            continue
        if record.get("is_error_frame") or record.get("is_remote_frame"):
            continue
        timestamp = record.get("wall_time_ns", record.get("epoch_ns"))
        if timestamp is None:
            continue
        try:
            event = {
                "time_ns": int(timestamp),
                "arbitration_id": parse_can_id(
                    record.get("arbitration_id", record.get("can_id"))
                ),
                "is_extended_id": bool(record.get("is_extended_id", False)),
                "payload": parse_data(record.get("data_hex", record.get("payload"))),
            }
        except (TypeError, ValueError, ConfigurationError):
            continue
        events.append(event)
    return sorted(events, key=lambda event: event["time_ns"])


def parse_rx_spec(value: str) -> Tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--rx는 BUS=JSONL 형식이어야 합니다.")
    bus, raw_path = value.split("=", 1)
    bus = bus.strip()
    if not bus or not raw_path.strip():
        raise argparse.ArgumentTypeError("--rx는 BUS=JSONL 형식이어야 합니다.")
    return bus, Path(raw_path).expanduser().resolve()


def phase_events(
    events: Iterable[Dict[str, Any]],
    start_ns: int,
    end_ns: int,
) -> List[Dict[str, Any]]:
    return [event for event in events if start_ns <= event["time_ns"] < end_ns]


def profiles(events: Iterable[Dict[str, Any]]) -> Dict[FrameKey, Counter[bytes]]:
    result: Dict[FrameKey, Counter[bytes]] = defaultdict(Counter)
    for event in events:
        key = (event["arbitration_id"], event["is_extended_id"])
        result[key][event["payload"]] += 1
    return dict(result)


def format_can_id(key: FrameKey) -> str:
    arbitration_id, is_extended = key
    width = 8 if is_extended else 3
    return f"0x{arbitration_id:0{width}X}"


def changed_bytes(reference: bytes, payload: bytes) -> List[Dict[str, Any]]:
    changes = [
        {
            "index": index,
            "baseline": f"{before:02X}",
            "observed": f"{after:02X}",
            "xor": f"{before ^ after:02X}",
        }
        for index, (before, after) in enumerate(zip(reference, payload))
        if before != after
    ]
    if len(reference) != len(payload):
        changes.append({
            "index": "length",
            "baseline": len(reference),
            "observed": len(payload),
            "xor": None,
        })
    return changes


def decoded_changes(
    database: Any,
    key: FrameKey,
    reference: bytes,
    payload: bytes,
) -> List[Dict[str, Any]]:
    if database is None:
        return []
    try:
        message = database.get_message_by_frame_id(key[0])
        before = message.decode(reference, decode_choices=False, scaling=True)
        after = message.decode(payload, decode_choices=False, scaling=True)
    except Exception:
        return []
    return [
        {"signal": name, "baseline": json_safe(value), "observed": json_safe(after[name])}
        for name, value in before.items()
        if name in after and after[name] != value
    ]


def direct_correlations(
    tx_events: Sequence[Dict[str, Any]],
    rx_events: Sequence[Dict[str, Any]],
    baseline: Mapping[FrameKey, Counter[bytes]],
    window_ns: int,
) -> Dict[str, Any]:
    by_frame: Dict[Tuple[int, bool, bytes], List[int]] = defaultdict(list)
    for event in rx_events:
        frame = (
            event["arbitration_id"],
            event["is_extended_id"],
            event["payload"],
        )
        by_frame[frame].append(event["time_ns"])

    matches: List[Dict[str, Any]] = []
    for tx in tx_events:
        frame = (tx["arbitration_id"], tx["is_extended_id"], tx["payload"])
        timestamps = by_frame.get(frame, [])
        left = bisect.bisect_left(timestamps, tx["time_ns"] - window_ns)
        right = bisect.bisect_right(timestamps, tx["time_ns"] + window_ns)
        if left == right:
            continue
        rx_time = min(timestamps[left:right], key=lambda item: abs(item - tx["time_ns"]))
        key = (tx["arbitration_id"], tx["is_extended_id"])
        baseline_seen = tx["payload"] in baseline.get(key, Counter())
        matches.append({
            "sequence": tx["sequence"],
            "can_id": format_can_id(key),
            "payload": tx["payload"].hex().upper(),
            "latency_ms": (rx_time - tx["time_ns"]) / 1_000_000.0,
            "baseline_seen_payload": baseline_seen,
        })
    return {
        "matched_tx_count": len(matches),
        "novel_matched_tx_count": sum(not item["baseline_seen_payload"] for item in matches),
        "matches": matches,
    }


def analyse_bus(
    bus_name: str,
    rx_events: Sequence[Dict[str, Any]],
    tx_events: Sequence[Dict[str, Any]],
    database: Any,
    baseline_start_ns: int,
    tx_start_ns: int,
    stimulus_end_ns: int,
    recovery_end_ns: int,
    correlation_window_ns: int,
) -> Dict[str, Any]:
    baseline_events = phase_events(rx_events, baseline_start_ns, tx_start_ns)
    stimulus_events = phase_events(rx_events, tx_start_ns, stimulus_end_ns)
    recovery_events = phase_events(rx_events, stimulus_end_ns, recovery_end_ns)
    baseline = profiles(baseline_events)
    stimulus = profiles(stimulus_events)
    recovery = profiles(recovery_events)
    direct = direct_correlations(
        tx_events,
        phase_events(rx_events, tx_start_ns - correlation_window_ns, stimulus_end_ns),
        baseline,
        correlation_window_ns,
    )

    baseline_seconds = (tx_start_ns - baseline_start_ns) / 1_000_000_000.0
    stimulus_seconds = (stimulus_end_ns - tx_start_ns) / 1_000_000_000.0
    recovery_seconds = (recovery_end_ns - stimulus_end_ns) / 1_000_000_000.0
    keys = set(baseline) | set(stimulus) | set(recovery)
    candidates: List[Dict[str, Any]] = []

    direct_by_id = Counter(item["can_id"] for item in direct["matches"])
    novel_direct_by_id = Counter(
        item["can_id"] for item in direct["matches"]
        if not item["baseline_seen_payload"]
    )
    for key in keys:
        base_counts = baseline.get(key, Counter())
        stimulus_counts = stimulus.get(key, Counter())
        recovery_counts = recovery.get(key, Counter())
        if not stimulus_counts:
            continue
        novel = [payload for payload in stimulus_counts if payload not in base_counts]
        baseline_rate = sum(base_counts.values()) / baseline_seconds
        stimulus_rate = sum(stimulus_counts.values()) / stimulus_seconds
        recovery_rate = sum(recovery_counts.values()) / recovery_seconds
        rate_ratio = stimulus_rate / baseline_rate if baseline_rate > 0 else None
        can_id = format_can_id(key)

        reasons: List[str] = []
        score = 0
        if novel_direct_by_id[can_id]:
            reasons.append("novel direct TX payload observed")
            score += 100 + min(novel_direct_by_id[can_id], 20)
        elif direct_by_id[can_id]:
            reasons.append("TX payload observed")
            score += 70
        if not base_counts:
            reasons.append("new ID during stimulus")
            score += 40
        elif len(base_counts) == 1 and novel:
            reasons.append("stable baseline payload changed")
            score += 30
        elif novel:
            reasons.append("new payload during stimulus")
            score += 15
        if rate_ratio is not None and (rate_ratio >= 2.0 or rate_ratio <= 0.5):
            reasons.append("frame rate changed")
            score += 10
        if not reasons:
            continue

        reference = base_counts.most_common(1)[0][0] if base_counts else None
        samples = [payload for payload, _ in stimulus_counts.most_common(5) if payload in novel]
        sample_details: List[Dict[str, Any]] = []
        for payload in samples:
            detail: Dict[str, Any] = {
                "payload": payload.hex().upper(),
                "count": stimulus_counts[payload],
            }
            if reference is not None:
                detail["changed_bytes"] = changed_bytes(reference, payload)
                signal_changes = decoded_changes(database, key, reference, payload)
                if signal_changes:
                    detail["changed_signals"] = signal_changes
            sample_details.append(detail)

        recovery_baseline_frames = sum(
            count for payload, count in recovery_counts.items() if payload in base_counts
        )
        recovery_total = sum(recovery_counts.values())
        candidates.append({
            "can_id": can_id,
            "score": score,
            "reasons": reasons,
            "baseline_frames": sum(base_counts.values()),
            "baseline_unique_payloads": len(base_counts),
            "stimulus_frames": sum(stimulus_counts.values()),
            "stimulus_unique_payloads": len(stimulus_counts),
            "novel_payload_count": len(novel),
            "baseline_rate_hz": baseline_rate,
            "stimulus_rate_hz": stimulus_rate,
            "stimulus_to_baseline_rate_ratio": rate_ratio,
            "recovery_rate_hz": recovery_rate,
            "recovery_baseline_payload_ratio": (
                recovery_baseline_frames / recovery_total if recovery_total else None
            ),
            "direct_tx_matches": direct_by_id[can_id],
            "novel_direct_tx_matches": novel_direct_by_id[can_id],
            "baseline_mode_payload": reference.hex().upper() if reference else None,
            "novel_payload_samples": sample_details,
        })

    candidates.sort(key=lambda item: (-item["score"], item["can_id"]))
    return {
        "bus": bus_name,
        "rx_frame_count": len(rx_events),
        "phase_counts": {
            "baseline": len(baseline_events),
            "stimulus": len(stimulus_events),
            "recovery": len(recovery_events),
        },
        "direct_correlation": direct,
        "candidates": candidates,
    }


def markdown_report(result: Mapping[str, Any]) -> str:
    lines = [
        "# CAN Fuzzer Response Correlation",
        "",
        f"- TX frames: {result['tx']['frame_count']}",
        f"- TX ID: {result['tx']['can_id']}",
        f"- TX duration: {result['tx']['duration_ms']:.3f} ms",
        f"- Clock correlation window: ±{result['settings']['correlation_window_ms']:.1f} ms",
        "",
    ]
    for bus in result["buses"]:
        direct = bus["direct_correlation"]
        lines.extend([
            f"## {bus['bus']}",
            "",
            (
                f"Frames: baseline {bus['phase_counts']['baseline']}, "
                f"stimulus {bus['phase_counts']['stimulus']}, "
                f"recovery {bus['phase_counts']['recovery']}. "
                f"Direct matches {direct['matched_tx_count']} "
                f"(novel {direct['novel_matched_tx_count']})."
            ),
            "",
            "| Score | CAN ID | Reasons | Direct | Novel payloads | Rate ratio | Recovery baseline |",
            "|---:|---|---|---:|---:|---:|---:|",
        ])
        for candidate in bus["candidates"][:30]:
            ratio = candidate["stimulus_to_baseline_rate_ratio"]
            recovery = candidate["recovery_baseline_payload_ratio"]
            ratio_text = f"{ratio:.2f}" if ratio is not None else "-"
            recovery_text = f"{recovery:.1%}" if recovery is not None else "-"
            lines.append(
                f"| {candidate['score']} | `{candidate['can_id']}` | "
                f"{'; '.join(candidate['reasons'])} | {candidate['direct_tx_matches']} | "
                f"{candidate['novel_payload_count']} | {ratio_text} | {recovery_text} |"
            )
        if not bus["candidates"]:
            lines.append("| - | - | No ranked candidate | - | - | - | - |")
        lines.append("")
    lines.extend([
        "## Interpretation",
        "",
        "- Novel direct matches are the strongest evidence that the injected frame crossed buses.",
        "- New IDs, payloads, and rate changes are reaction candidates, not proof of causation.",
        "- Negative latency within the configured window usually indicates host clock offset; synchronize all hosts with NTP/chrony.",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TX manifest와 I/P-CAN raw JSONL을 baseline/stimulus/recovery로 비교합니다."
    )
    parser.add_argument("--tx", type=Path, required=True, help="can_sender 또는 tx_only TX JSONL")
    parser.add_argument(
        "--rx", action="append", type=parse_rx_spec, required=True,
        metavar="BUS=JSONL", help="예: i_can=logs/i_can.jsonl; 반복 가능",
    )
    parser.add_argument("--dbc", type=Path, default=None, help="변경 신호 해석용 DBC")
    parser.add_argument("--baseline-seconds", type=positive_float, default=10.0)
    parser.add_argument("--response-seconds", type=positive_float, default=2.0)
    parser.add_argument("--recovery-seconds", type=positive_float, default=10.0)
    parser.add_argument("--correlation-window-ms", type=positive_float, default=250.0)
    parser.add_argument("--output", type=Path, default=None, help="JSON 결과 경로")
    return parser


def run(args: argparse.Namespace) -> int:
    tx_path = args.tx.expanduser().resolve()
    tx_events = load_tx_events(tx_path)
    database = load_dbc(args.dbc.expanduser().resolve()) if args.dbc else None
    first_tx_ns = tx_events[0]["time_ns"]
    last_tx_ns = tx_events[-1]["time_ns"]
    baseline_start_ns = first_tx_ns - int(args.baseline_seconds * 1_000_000_000)
    stimulus_end_ns = last_tx_ns + int(args.response_seconds * 1_000_000_000)
    recovery_end_ns = stimulus_end_ns + int(args.recovery_seconds * 1_000_000_000)
    correlation_window_ns = int(args.correlation_window_ms * 1_000_000)

    buses = []
    for bus_name, rx_path in args.rx:
        buses.append(analyse_bus(
            bus_name,
            load_rx_events(rx_path),
            tx_events,
            database,
            baseline_start_ns,
            first_tx_ns,
            stimulus_end_ns,
            recovery_end_ns,
            correlation_window_ns,
        ))

    key = (tx_events[0]["arbitration_id"], tx_events[0]["is_extended_id"])
    result = {
        "record_type": "fuzz_response_analysis",
        "generated_wall_time_ns": time.time_ns(),
        "tx": {
            "path": str(tx_path),
            "frame_count": len(tx_events),
            "can_id": format_can_id(key),
            "first_tx_ns": first_tx_ns,
            "last_tx_ns": last_tx_ns,
            "duration_ms": (last_tx_ns - first_tx_ns) / 1_000_000.0,
        },
        "settings": {
            "baseline_seconds": args.baseline_seconds,
            "response_seconds": args.response_seconds,
            "recovery_seconds": args.recovery_seconds,
            "correlation_window_ms": args.correlation_window_ms,
            "dbc": str(args.dbc.expanduser().resolve()) if args.dbc else None,
        },
        "buses": buses,
    }

    if args.output:
        output = args.output.expanduser().resolve()
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output = (Path.cwd() / "logs" / f"fuzz_response_{stamp}.json").resolve()
    report_path = output.with_suffix(".md")
    for path in (output, report_path):
        if path.exists():
            raise FileExistsError(f"출력 파일이 이미 존재합니다: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(json_safe(result), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(markdown_report(result))

    print(f"[DONE] TX={len(tx_events)} frames, buses={len(buses)}")
    for bus in buses:
        direct = bus["direct_correlation"]
        print(
            f"[{bus['bus']}] candidates={len(bus['candidates'])}, "
            f"direct={direct['matched_tx_count']}, novel_direct={direct['novel_matched_tx_count']}"
        )
    print(f"[JSON] {output}")
    print(f"[REPORT] {report_path}")
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
