import json
import tempfile
import unittest
from pathlib import Path

from powertrain_ican_fuzz.ican_monitor.monitor import (
    classify_payload,
    decode_display_signals,
    load_expected_payloads,
)
from powertrain_ican_fuzz.pcan_fuzzer.fuzzer import (
    BASE_PAYLOAD,
    CAN_ID,
    generate_cases,
    mutate_signal,
    run,
)


class Motor18FuzzerTests(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(CAN_ID, 0x670)
        self.assertEqual(BASE_PAYLOAD.hex().upper(), "001010000001007C")

    def test_signal_mutations_only_touch_expected_fields(self):
        popup = mutate_signal(BASE_PAYLOAD, "start_stop_popup", 1)
        warning = mutate_signal(BASE_PAYLOAD, "rpm_warning", 1)
        limit = mutate_signal(BASE_PAYLOAD, "rpm_limit", 4000)
        self.assertEqual(decode_display_signals(popup)["MO_StartStopp_PopUp"], 1)
        self.assertEqual(decode_display_signals(warning)["MO_Drehzahl_Warnung"], 1)
        self.assertEqual(decode_display_signals(limit)["MO_obere_Drehzahlgrenze"], 4000)
        self.assertEqual(popup[2:], BASE_PAYLOAD[2:])
        self.assertEqual(warning[:6], BASE_PAYLOAD[:6])
        self.assertEqual(limit[:7], BASE_PAYLOAD[:7])

    def test_generate_cases(self):
        cases = generate_cases(["start_stop_popup", "rpm_warning", "rpm_limit"], 1)
        self.assertEqual(len(cases), 7)
        self.assertTrue(all(len(case["payload"]) == 8 for case in cases))

    def test_dry_run_never_calls_sender(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            manifest = Path(directory) / "dry.jsonl"
            cases = generate_cases(["rpm_warning"], 1)
            sent = run(cases, "can0", manifest, 0, False, calls.append)
            records = [json.loads(line) for line in manifest.read_text().splitlines()]
            self.assertEqual(sent, 0)
            self.assertEqual(calls, [])
            self.assertEqual(records[1]["status"], "dry-run")

    def test_monitor_manifest_matching(self):
        mutation = mutate_signal(BASE_PAYLOAD, "rpm_warning", 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tx.jsonl"
            path.write_text(json.dumps({"event": "tx", "payload": mutation.hex()}) + "\n")
            expected = load_expected_payloads(path)
            self.assertEqual(classify_payload(BASE_PAYLOAD, expected), "baseline")
            self.assertEqual(classify_payload(mutation, expected), "expected_mutation")


if __name__ == "__main__":
    unittest.main()
