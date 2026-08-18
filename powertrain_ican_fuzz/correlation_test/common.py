"""Shared definitions for the isolated correlation experiment."""

from __future__ import annotations

from powertrain_ican_fuzz.pcan_fuzzer.fuzzer import (
    BASE_PAYLOAD,
    MOTOR07_BASE_PAYLOADS,
    mutate_message_signal,
)


CANDIDATES = {
    "rpm_limit_4000": {
        "message_key": "motor18",
        "message_name": "Motor_18",
        "can_id": 0x670,
        "signal": "rpm_limit",
        "physical_value": 4000,
        "base_payload": BASE_PAYLOAD,
        "expected_reactions": {
            "tester_present",
            "obdc_zr_request",
            "obdc_zr_response",
            "gateway_wakeup_transition",
        },
    },
    "oil_temp_40": {
        "message_key": "motor07",
        "message_name": "Motor_07",
        "can_id": 0x640,
        "signal": "oil_temp",
        "physical_value": 40,
        # This is the exact baseline variant temporally closest to the
        # previously observed FoD request/response event.
        "base_payload": MOTOR07_BASE_PAYLOADS[0],
        "expected_reactions": {
            "fod_request",
            "fod_response",
            "fod_transmission_change",
        },
    },
}


def candidate_payload(name: str) -> bytes:
    spec = CANDIDATES[name]
    base = spec["base_payload"]
    assert isinstance(base, bytes)
    return mutate_message_signal(
        str(spec["message_key"]),
        base,
        str(spec["signal"]),
        int(spec["physical_value"]),
    )
