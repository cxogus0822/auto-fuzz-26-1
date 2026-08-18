import json
import tempfile
import unittest
from pathlib import Path

from powertrain_ican_fuzz.correlation_test.analyze import correlate
from powertrain_ican_fuzz.correlation_test.common import candidate_payload
from powertrain_ican_fuzz.correlation_test.monitor import decode_reaction
from powertrain_ican_fuzz.correlation_test.sender import generate_trials
from powertrain_ican_fuzz.ican_monitor.monitor import (
    classify_payload,
    decode_candidate_signals,
    decode_display_signals,
    load_expected_payloads,
)
from powertrain_ican_fuzz.pcan_fuzzer.fuzzer import (
    BASE_PAYLOAD,
    CAN_ID,
    generate_cases,
    generate_message_cases,
    mutate_message_signal,
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
        self.assertEqual(len(cases), 28)
        self.assertTrue(all(len(case["payload"]) == 8 for case in cases))

    def test_extended_signal_mutations(self):
        expected = {
            "cylinder_text_detail": (6, "MO_Zylabsch_Texte_02"),
            "hybrid_startstop_led": (2, "MO_Hybrid_StartStopp_LED"),
            "deactivated_cylinder_count": (5, "MO_Anzahl_Abgesch_Zyl"),
            "cylinder_text": (3, "MO_Zylabsch_Texte"),
            "ethanol_text": (4, "MO_Ethanol_BS_Texte"),
        }
        for signal, (value, decoded_name) in expected.items():
            payload = mutate_signal(BASE_PAYLOAD, signal, value)
            self.assertEqual(decode_display_signals(payload)[decoded_name], value)

    def test_extended_profile_case_count(self):
        signals = [
            "start_stop_popup", "rpm_warning", "rpm_limit",
            "cylinder_text_detail", "hybrid_startstop_led",
            "deactivated_cylinder_count", "cylinder_text", "ethanol_text",
        ]
        self.assertEqual(len(generate_cases(signals, 1)), 59)
        self.assertEqual(len(generate_cases(signals, 10)), 590)

    def test_motor07_has_eight_signal_candidates(self):
        signals = [
            "intake_temp_qbit", "oil_temp_qbit", "coolant_temp_qbit",
            "intake_temp", "oil_temp", "coolant_temp", "altitude_raw",
            "altitude_qbit",
        ]
        cases = generate_message_cases("motor07", signals, 1)
        self.assertEqual(len(cases), 54)
        payload = mutate_message_signal(
            "motor07", bytes.fromhex("80928BB67E421104"), "coolant_temp", 90,
        )
        self.assertEqual(decode_candidate_signals("motor07", payload)["MO_Kuehlmittel_Temp"], 90)

    def test_motor26_has_twelve_signal_candidates_and_preserves_mux_bases(self):
        signals = [
            "eflex_lamp", "oil_min_warning", "oil_system_fault",
            "oil_max_warning", "motor_start_text", "electric_warning",
            "system_lamp", "obd2_lamp", "hot_lamp", "particle_lamp",
            "oil_overfill_warning", "oil_underfill_warning",
        ]
        cases = generate_message_cases("motor26", signals, 1)
        self.assertEqual(len(cases), 58)
        self.assertEqual({case["base_index"] for case in cases}, {0, 1})
        payload = mutate_message_signal(
            "motor26", bytes.fromhex("0110080100418200"), "obd2_lamp", 1,
        )
        self.assertEqual(decode_candidate_signals("motor26", payload)["MO_OBD2_Lampe"], 1)

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

    def test_interrupted_run_records_partial_result(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "interrupt.jsonl"
            cases = generate_cases(["rpm_warning"], 2)
            calls = []

            def interrupt_after_first(payload):
                calls.append(payload)
                if len(calls) == 2:
                    raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                run(cases, "can0", manifest, 0, True, interrupt_after_first)
            records = [json.loads(line) for line in manifest.read_text().splitlines()]
            self.assertEqual(records[-1]["status"], "interrupted")
            self.assertEqual(records[-1]["sent"], 1)

    def test_monitor_manifest_matching(self):
        mutation = mutate_signal(BASE_PAYLOAD, "rpm_warning", 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tx.jsonl"
            path.write_text(json.dumps({"event": "tx", "payload": mutation.hex()}) + "\n")
            expected = load_expected_payloads(path)
            self.assertEqual(classify_payload(BASE_PAYLOAD, expected), "baseline")
            self.assertEqual(classify_payload(mutation, expected), "expected_mutation")

    def test_isolated_candidate_payloads(self):
        self.assertEqual(
            candidate_payload("rpm_limit_4000").hex().upper(),
            "0010100000010050",
        )
        self.assertEqual(
            candidate_payload("oil_temp_40").hex().upper(),
            "809264B67E421104",
        )
        trials = generate_trials("rpm_limit_4000", 3)
        self.assertEqual(len(trials), 3)
        self.assertEqual([case["trial"] for case in trials], [1, 2, 3])

    def test_reaction_decoding(self):
        reaction, fields = decode_reaction(
            0x17FD0200, bytes.fromhex("023E80AAAAAAAAAA"),
        )
        self.assertEqual(reaction, "tester_present")
        self.assertEqual(fields["uds_service"], "TesterPresent")
        reaction, fields = decode_reaction(0x1B000010, bytes.fromhex("0000400000000000"))
        self.assertEqual(reaction, "gateway_nm")
        self.assertEqual(fields["car_wakeup"], 1)

    def test_correlation_report_marks_repeatable_candidate(self):
        capture_start = {"event": "capture_start", "epoch_ns": 1_000_000_000}
        tx_records = []
        rx_records = [capture_start]
        for trial, second in enumerate((3, 13, 23), 1):
            tx_records.append({
                "event": "tx", "status": "sent", "candidate": "rpm_limit_4000",
                "trial": trial, "epoch_ns": second * 1_000_000_000,
                "send_return_epoch_ns": second * 1_000_000_000,
                "utc": "test", "payload": "0010100000010050",
            })
            rx_records.append({
                "event": "rx", "epoch_ns": second * 1_000_000_000 + 4_000_000,
                "reaction": "tester_present", "can_id": "0x17FD0200",
                "payload": "023E80AAAAAAAAAA",
            })
        result = correlate(tx_records, rx_records, 5.0)
        summary = result["candidate_summary"]["rpm_limit_4000"]
        self.assertEqual(summary["trials_with_expected_reaction"], 3)
        self.assertEqual(summary["verdict"], "repeatable_correlation")


if __name__ == "__main__":
    unittest.main()
