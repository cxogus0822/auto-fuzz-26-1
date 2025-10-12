# src/seeds/dbc_parser.py
import json
import os
from typing import Dict, Any, List
import cantools


class DbcParser:
    """DBC 파일을 파싱하여 메시지-시그널 구조를 계층적으로 반환하는 클래스"""

    def __init__(self, dbc_file: str):
        self.db = cantools.database.load_file(dbc_file)

    def parse(
        self,
        include_attributes: bool = True,
        normalize_byte_order: bool = True,
    ) -> Dict[str, Any]:
        """DBC 파일을 메시지 단위로 파싱"""
        messages: List[Dict[str, Any]] = []

        for msg in self.db.messages:
            msg_info = {
                "id": msg.frame_id,
                "name": msg.name,
                "dlc": msg.length,
                "is_extended_frame": getattr(msg, "is_extended_frame", False),
                "senders": list(getattr(msg, "senders", []) or []),
                "comment": getattr(msg, "comment", None),
                "cycle_time": getattr(msg, "cycle_time", None),
                "signals": [],
            }

            if include_attributes:
                msg_info["attributes"] = getattr(msg, "attributes", {}) or {}

            # === Signal 단위 파싱 ===
            for sig in msg.signals:
                byte_order = (
                    "big_endian" if sig.byte_order == "big_endian" else "little_endian"
                    if normalize_byte_order
                    else sig.byte_order
                )

                mux, mux_value = None, None
                if getattr(sig, "is_multiplexer", False):
                    mux = "multiplexer"
                elif getattr(sig, "multiplexer_ids", None) is not None:
                    mux = "multiplexed"
                    mux_value = list(sig.multiplexer_ids)

                sig_info = {
                    "name": sig.name,
                    "start_bit": sig.start,
                    "length": sig.length,
                    "byte_order": byte_order,
                    "is_signed": sig.is_signed,
                    "factor": sig.scale,   # ✅ 명확히 factor로 표기
                    "offset": sig.offset,
                    "minimum": sig.minimum,
                    "maximum": sig.maximum,
                    "unit": sig.unit,
                    "comment": getattr(sig, "comment", None),
                    "choices": getattr(sig, "choices", None),
                    "mux": mux,
                    "mux_value": mux_value,
                }

                if include_attributes:
                    sig_info["attributes"] = getattr(sig, "attributes", {}) or {}

                msg_info["signals"].append(sig_info)

            messages.append(msg_info)

        return {
            "messages": messages,
            "version": getattr(self.db, "version", None),
        }

    @staticmethod
    def save(parsed: Dict[str, Any], out_path: str, sort_keys: bool = False) -> None:
        """파싱 결과를 JSON 파일로 저장"""
        parent = os.path.dirname(os.path.abspath(out_path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False, sort_keys=sort_keys)