from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from analyze_fuzz_response import analyse_bus, build_parser as build_analysis_parser, run as run_analysis
from can_common import ConfigurationError
from can_receiver import build_parser as build_receiver_parser, run as run_receiver, validate_runtime_number
from can_sender import capture_live_payload, generate_mutations, mutation_summary


class MutationTests(unittest.TestCase):
    BASE = bytes.fromhex("00001000200000F0")

    def test_repository_mutations_are_deterministic_and_fixed_dlc(self) -> None:
        first = generate_mutations(self.BASE, 32, 3, False, True, 366)
        second = generate_mutations(self.BASE, 32, 3, False, True, 366)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertEqual(first[0], self.BASE)
        self.assertEqual(len(set(first)), 32)
        self.assertTrue(all(len(payload) == 8 for payload in first))

    def test_original_is_removed_when_not_requested(self) -> None:
        payloads = generate_mutations(self.BASE, 32, 3, False, False, 366)
        self.assertEqual(len(payloads), 32)
        self.assertNotIn(self.BASE, payloads)

    def test_mutation_summary(self) -> None:
        payload = bytes.fromhex("00000000200000F0")
        summary = mutation_summary(self.BASE, payload)
        self.assertEqual(summary["changed_byte_indexes"], [2])
        self.assertEqual(summary["xor_hex"], "0000100000000000")
        self.assertEqual(summary["changed_bit_count"], 1)

    def test_live_baseline_requires_configured_stability(self) -> None:
        class FakeBus:
            def __init__(self, payloads: list[bytes]) -> None:
                self.payloads = list(payloads)

            def recv(self, timeout: float):
                del timeout
                payload = self.payloads.pop(0)
                return SimpleNamespace(
                    arbitration_id=0x366,
                    is_extended_id=False,
                    data=payload,
                )

        stable = bytes.fromhex("00000000200000F0")
        selected = capture_live_payload(
            FakeBus([stable, stable, stable]), 0x366, False, 1.0, 3, 1.0
        )
        self.assertEqual(selected, stable)
        with self.assertRaisesRegex(RuntimeError, "baseline이 불안정"):
            capture_live_payload(
                FakeBus([stable, bytes(8), stable]), 0x366, False, 1.0, 3, 1.0
            )


class ReceiverValidationTests(unittest.TestCase):
    def test_non_finite_timing_is_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ConfigurationError):
                validate_runtime_number(value, "test")

    def test_receiver_records_raw_frame_and_session_id(self) -> None:
        class FakeBus:
            def __init__(self) -> None:
                self.sent_frame = False
                self.closed = False

            def recv(self, timeout: float):
                del timeout
                if self.sent_frame:
                    return None
                self.sent_frame = True
                return SimpleNamespace(
                    timestamp=1.0,
                    arbitration_id=0x366,
                    dlc=8,
                    data=bytes.fromhex("00000000200000F0"),
                    is_extended_id=False,
                    is_remote_frame=False,
                    is_error_frame=False,
                    is_fd=False,
                    bitrate_switch=False,
                    error_state_indicator=False,
                    is_rx=True,
                )

            def shutdown(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rx.jsonl"
            args = build_receiver_parser().parse_args([
                "--bus-name", "i_can",
                "--interface", "virtual",
                "--channel", "test",
                "--duration", "0.01",
                "--output", str(output),
                "--print-mode", "none",
            ])
            bus = FakeBus()
            with patch("can_receiver.open_can_bus", return_value=bus):
                self.assertEqual(run_receiver(args), 0)
            records = [json.loads(line) for line in output.read_text().splitlines()]
            frame = next(item for item in records if item["record_type"] == "can_rx")
            self.assertEqual(frame["data_hex"], "00000000200000F0")
            self.assertTrue(frame["session_id"])
            self.assertEqual(records[0]["session_id"], frame["session_id"])
            self.assertTrue(bus.closed)


class ResponseAnalysisTests(unittest.TestCase):
    def test_direct_route_and_stable_reaction_are_ranked(self) -> None:
        second = 1_000_000_000
        tx = [{
            "time_ns": 20 * second,
            "sequence": 1,
            "arbitration_id": 0x366,
            "is_extended_id": False,
            "payload": bytes.fromhex("00001000200000F0"),
        }]
        rx = [
            {
                "time_ns": 12 * second,
                "arbitration_id": 0x366,
                "is_extended_id": False,
                "payload": bytes.fromhex("00000000200000F0"),
            },
            {
                "time_ns": 13 * second,
                "arbitration_id": 0x123,
                "is_extended_id": False,
                "payload": bytes.fromhex("00"),
            },
            {
                "time_ns": 20 * second + 5_000_000,
                "arbitration_id": 0x366,
                "is_extended_id": False,
                "payload": bytes.fromhex("00001000200000F0"),
            },
            {
                "time_ns": 20 * second + 10_000_000,
                "arbitration_id": 0x123,
                "is_extended_id": False,
                "payload": bytes.fromhex("01"),
            },
            {
                "time_ns": 24 * second,
                "arbitration_id": 0x123,
                "is_extended_id": False,
                "payload": bytes.fromhex("00"),
            },
        ]
        result = analyse_bus(
            "i_can",
            rx,
            tx,
            None,
            10 * second,
            20 * second,
            22 * second,
            30 * second,
            250_000_000,
        )
        direct = result["direct_correlation"]
        self.assertEqual(direct["matched_tx_count"], 1)
        self.assertEqual(direct["novel_matched_tx_count"], 1)
        candidates = {item["can_id"]: item for item in result["candidates"]}
        self.assertIn("0x366", candidates)
        self.assertIn("0x123", candidates)
        self.assertIn("stable baseline payload changed", candidates["0x123"]["reasons"])
        self.assertEqual(candidates["0x123"]["recovery_baseline_payload_ratio"], 1.0)

    def test_end_to_end_analysis_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tx_path = root / "tx.jsonl"
            rx_path = root / "rx.jsonl"
            output = root / "result.json"
            tx_records = [
                {"record_type": "tx_session_start", "wall_time_ns": 19_000_000_000},
                {
                    "record_type": "can_tx",
                    "status": "sent",
                    "sequence": 1,
                    "send_attempt_wall_time_ns": 20_000_000_000,
                    "arbitration_id": 0x366,
                    "is_extended_id": False,
                    "data_hex": "00001000200000F0",
                },
            ]
            rx_records = [
                {
                    "record_type": "can_rx",
                    "wall_time_ns": 15_000_000_000,
                    "arbitration_id": 0x366,
                    "is_extended_id": False,
                    "data_hex": "00000000200000F0",
                },
                {
                    "record_type": "can_rx",
                    "wall_time_ns": 20_005_000_000,
                    "arbitration_id": 0x366,
                    "is_extended_id": False,
                    "data_hex": "00001000200000F0",
                },
            ]
            tx_path.write_text(
                "".join(json.dumps(item) + "\n" for item in tx_records),
                encoding="utf-8",
            )
            rx_path.write_text(
                "".join(json.dumps(item) + "\n" for item in rx_records),
                encoding="utf-8",
            )
            args = build_analysis_parser().parse_args([
                "--tx", str(tx_path),
                "--rx", f"i_can={rx_path}",
                "--baseline-seconds", "10",
                "--response-seconds", "2",
                "--recovery-seconds", "10",
                "--output", str(output),
            ])
            self.assertEqual(run_analysis(args), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                result["buses"][0]["direct_correlation"]["novel_matched_tx_count"],
                1,
            )
            self.assertTrue(output.with_suffix(".md").is_file())


if __name__ == "__main__":
    unittest.main()
