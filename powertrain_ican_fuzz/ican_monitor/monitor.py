#!/usr/bin/env python3
"""Passive I-CAN monitor for Motor_18 baseline and fuzz payloads."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from powertrain_ican_fuzz.pcan_fuzzer.fuzzer import BASE_PAYLOAD, CAN_ID, MESSAGE_SPECS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def default_output_path(message_key: str = "motor18") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("rx_logs") / f"{message_key}_ican_{stamp}.jsonl"


def decode_display_signals(payload: bytes) -> dict[str, int | float]:
    if len(payload) != 8:
        return {}
    packed = int.from_bytes(payload, "little")
    return {
        "MO_StartStopp_PopUp": (packed >> 9) & 0x3,
        "MO_Zylabsch_Texte_02": (packed >> 16) & 0xF,
        "MO_Hybrid_StartStopp_LED": (packed >> 43) & 0x3,
        "MO_Anzahl_Abgesch_Zyl": (packed >> 47) & 0x7,
        "MO_Zylabsch_Texte": (packed >> 50) & 0x3,
        "MO_Ethanol_BS_Texte": (packed >> 52) & 0x7,
        "MO_Drehzahl_Warnung": (packed >> 55) & 0x1,
        "MO_obere_Drehzahlgrenze": ((packed >> 56) & 0xFF) * 50,
    }


def decode_candidate_signals(message_key: str, payload: bytes) -> dict[str, int | float]:
    if len(payload) != 8:
        return {}
    if message_key == "motor18":
        return decode_display_signals(payload)
    packed = int.from_bytes(payload, "little")
    if message_key == "motor07":
        return {
            "MO_QBit_Ansaugluft_Temp": packed & 0x1,
            "MO_QBit_Oel_Temp": (packed >> 1) & 0x1,
            "MO_QBit_Kuehlmittel_Temp": (packed >> 2) & 0x1,
            "MO_Ansaugluft_Temp": (((packed >> 8) & 0xFF) * 0.75) - 48,
            "MO_Oel_Temp": ((packed >> 16) & 0xFF) - 60,
            "MO_Kuehlmittel_Temp": (((packed >> 24) & 0xFF) * 0.75) - 48,
            "MO_Hoeheninfo_raw": (packed >> 32) & 0xFF,
            "MO_QBit_Hoeheninfo": (packed >> 46) & 0x1,
        }
    if message_key == "motor26":
        return {
            "MO_EFLEX_Lampe": (packed >> 8) & 0x3,
            "WIV_Oelmin_Warn": (packed >> 13) & 0x1,
            "OLEV_Systemstoerung": (packed >> 22) & 0x1,
            "MO_Oelwarnung_max": (packed >> 23) & 0x1,
            "MO_E_Warnungen": (packed >> 28) & 0xF,
            "MO_Text_Motorstart": (packed >> 32) & 0xF,
            "MO_Systemlampe": (packed >> 48) & 0x1,
            "MO_OBD2_Lampe": (packed >> 49) & 0x1,
            "MO_Heissleuchte": (packed >> 50) & 0x1,
            "MO_Partikel_Lampe": (packed >> 51) & 0x1,
            "WIV_Ueberfuell_Warn": (packed >> 26) & 0x1,
            "WIV_Unterfuell_Warn": (packed >> 56) & 0x1,
        }
    raise ValueError(f"unsupported message: {message_key}")


def load_expected_payloads(path: Optional[Path]) -> set[str]:
    if path is None:
        return set()
    expected: set[str] = set()
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("event") == "tx" and record.get("payload"):
                expected.add(str(record["payload"]).upper())
    return expected


def classify_payload(
    payload: bytes, expected: set[str], baseline_payloads: Sequence[bytes] = (BASE_PAYLOAD,),
) -> str:
    payload_hex = payload.hex().upper()
    if payload in baseline_payloads:
        return "baseline"
    if payload_hex in expected:
        return "expected_mutation"
    return "other_variant"


def monitor(
    channel: str,
    duration: float,
    output: Path,
    expected_manifest: Optional[Path] = None,
    message_key: str = "motor18",
) -> dict[str, int]:
    try:
        import can  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-can is required") from exc

    expected = load_expected_payloads(expected_manifest)
    spec = MESSAGE_SPECS[message_key]
    can_id = int(spec["can_id"])
    baseline_payloads = spec["base_payloads"]
    assert isinstance(baseline_payloads, tuple)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"total": 0, "baseline": 0, "expected_mutation": 0, "other_variant": 0}
    bus = can.Bus(
        interface="socketcan",
        channel=channel,
        receive_own_messages=False,
        can_filters=[{"can_id": can_id, "can_mask": 0x7FF, "extended": False}],
    )
    deadline = time.monotonic() + duration
    try:
        with output.open("x", encoding="utf-8", buffering=1) as handle:
            handle.write(json.dumps({
                "event": "capture_start", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "channel": channel, "can_id": f"0x{can_id:X}", "message": message_key,
                "duration_seconds": duration,
                "expected_manifest": str(expected_manifest) if expected_manifest else None,
                "expected_payload_count": len(expected),
            }, separators=(",", ":")) + "\n")
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                message = bus.recv(timeout=min(1.0, remaining))
                if message is None or message.arbitration_id != can_id or message.is_extended_id:
                    continue
                payload = bytes(message.data)
                classification = classify_payload(payload, expected, baseline_payloads)
                counts["total"] += 1
                counts[classification] += 1
                record = {
                    "event": "rx", "utc": utc_now(), "epoch_ns": time.time_ns(),
                    "bus_timestamp": message.timestamp, "channel": channel,
                    "can_id": f"0x{can_id:X}", "payload": payload.hex().upper(),
                    "dlc": len(payload), "classification": classification,
                    "signals": decode_candidate_signals(message_key, payload),
                }
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.write(json.dumps({
                "event": "capture_end", "utc": utc_now(), "epoch_ns": time.time_ns(),
                "counts": counts,
            }, separators=(",", ":")) + "\n")
    finally:
        bus.shutdown()
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Passive I-CAN monitor for selected Powertrain candidates")
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--message", choices=sorted(MESSAGE_SPECS), default="motor18")
    parser.add_argument("--duration", type=positive_float, default=120.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--expected-manifest", type=Path, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output or default_output_path(args.message)
    try:
        can_id = int(MESSAGE_SPECS[args.message]["can_id"])
        print(
            f"[ican-monitor] PASSIVE: ID=0x{can_id:X}, message={args.message}, "
            f"channel={args.channel}, duration={args.duration}s"
        )
        counts = monitor(
            args.channel, args.duration, output, args.expected_manifest, args.message,
        )
        print(f"[ican-monitor] completed: {counts}")
        print(f"[ican-monitor] output: {output.resolve()}")
        return 0
    except (FileExistsError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ican-monitor:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
