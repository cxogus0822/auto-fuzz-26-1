import json
import tempfile
import unittest
from pathlib import Path

from tx_only.fuzzer import (
    DEFAULT_BASE_PAYLOAD,
    HAZARD_CAN_ID,
    generate_mutations,
    mutation_summary,
    parse_payload,
    run_transmission,
)


class TxOnlyFuzzerTests(unittest.TestCase):
    def test_hazard_id_and_payload_parser(self):
        self.assertEqual(HAZARD_CAN_ID, 0x366)
        self.assertEqual(parse_payload("0x00000000200000F0"), DEFAULT_BASE_PAYLOAD)
        self.assertEqual(parse_payload("00 01_02"), bytes.fromhex("000102"))

    def test_mutations_preserve_dlc_by_default(self):
        payloads = generate_mutations(
            base_payload=DEFAULT_BASE_PAYLOAD,
            count=32,
            max_operations=3,
            allow_dlc_change=False,
            include_original=False,
        )
        self.assertTrue(payloads)
        self.assertLessEqual(len(payloads), 32)
        self.assertTrue(all(len(payload) == 8 for payload in payloads))
        self.assertEqual(len(payloads), len(set(payloads)))

    def test_mutation_summary(self):
        summary = mutation_summary(bytes.fromhex("0000"), bytes.fromhex("0103"))
        self.assertEqual(summary["changed_byte_indexes"], [0, 1])
        self.assertEqual(summary["xor_hex"], "0103")
        self.assertEqual(summary["changed_bit_count"], 3)
        self.assertEqual(summary["length_delta"], 0)

    def test_dry_run_writes_manifest_without_sending(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "dry.jsonl"
            calls = []
            sent = run_transmission(
                payloads=[bytes(8), bytes.fromhex("0100000000000000")],
                channel="can0",
                manifest_path=manifest,
                interval_ms=0,
                live=False,
                base_payload=bytes(8),
                allow_dlc_change=False,
                send_payload=calls.append,
            )
            records = [json.loads(line) for line in manifest.read_text().splitlines()]
            self.assertEqual(sent, 0)
            self.assertEqual(calls, [])
            self.assertEqual(records[0]["event"], "run_start")
            self.assertEqual(records[-1]["event"], "run_end")
            self.assertEqual([row["status"] for row in records[1:-1]], ["dry-run", "dry-run"])
            self.assertIn("mutation", records[1])

    def test_injected_sender_records_live_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "live.jsonl"
            calls = []
            payloads = [bytes.fromhex("AA" * 8), bytes.fromhex("55" * 8)]
            sent = run_transmission(
                payloads=payloads,
                channel="can0",
                manifest_path=manifest,
                interval_ms=0,
                live=True,
                base_payload=bytes(8),
                allow_dlc_change=False,
                send_payload=calls.append,
            )
            records = [json.loads(line) for line in manifest.read_text().splitlines()]
            self.assertEqual(sent, 2)
            self.assertEqual(calls, payloads)
            self.assertEqual([row["status"] for row in records[1:-1]], ["sent", "sent"])


if __name__ == "__main__":
    unittest.main()
