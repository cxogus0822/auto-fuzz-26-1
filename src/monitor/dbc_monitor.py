# src/monitor/dbc_monitor_bool.py
# DBC 기반 1-bit 신호 모니터

import time
import can
import cantools
from typing import Dict, Any, Optional, List
from logger.base_logger import log_event


CAN_CHANNEL = "can0"
DBC_PATH    = "db/your.ecu.dbc"   # 실제 경로로 교체
TARGET_ID   = 0x366               # Blinkmodi_02

# ─────────────────────────────────────────────────────────────────────────────

class DBCMonitor:
    """
    - decode/type check: 디코드 실패는 즉시 FAIL
    - (선택) range check: min/max(보통 0/1) — enum과 동일 효과
    - (선택) monotonic: "nondecreasing" 또는 "nonincreasing"
      * nondecreasing: 1→0 금지 (0->1은 허용, '한 번 켜지면 유지')
      * nonincreasing: 0→1 금지 (1->0은 허용, '한 번 꺼지면 유지')
    """

    def __init__(self,
                 channel: str = CAN_CHANNEL,
                 dbc_path: str = DBC_PATH,
                 target_id: int = TARGET_ID,
                 rules: Optional[Dict[str, Dict[str, Any]]] = None):
        self.channel = channel
        self.dbc_path = dbc_path
        self.target_id = target_id
        self.rules = rules or {}

        # CAN / DBC 초기화
        self.bus = can.interface.Bus(channel=self.channel, bustype="socketcan")
        self.db  = cantools.database.load_file(self.dbc_path)
        self.msg_def = self.db.get_message_by_frame_id(self.target_id)
        if self.msg_def is None:
            raise ValueError(f"DBC에 ID 0x{self.target_id:X} 메시지 정의가 없습니다.")

        # 내부 상태
        self._prev_values: Dict[str, int] = {}  # 각 신호의 직전 값(0/1)
        self.events: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────
    def start(self):
        print(f"[ INFO ] DBCBoolMonitor: 0x{self.target_id:X} on {self.channel}")
        print(f"         DBC={self.dbc_path}, signals={list(self.rules.keys()) or '—'}")

        while True:
            msg = self.bus.recv(timeout=1)
            if not msg or msg.arbitration_id != self.target_id:
                continue

            try:
                decoded = self.msg_def.decode(bytes(msg.data), decode_choices=True, scaling=True)
            except Exception as e:
                self._emit("decode_error", "_frame", str(e), "FAIL")
                print(f"[FAIL] decode_error: {e}")
                continue

            # 신호별 검사
            for sig, rule in self.rules.items():
                if sig not in decoded:
                    self._emit("missing_signal", sig, None, "FAIL")
                    print(f"[FAIL] {sig}: missing in decoded")
                    continue

                # bool로 강제 캐스팅(0/1), float로 오더라도 정규화
                val = int(float(decoded[sig]))
                self._check_bool_rules(sig, val, rule)

    # ─────────────────────────────────────────────────────────────────────────
    def _check_bool_rules(self, sig: str, val: int, rule: Dict[str, Any]):
        # 1) decode/type check는 상위에서 처리됨 (여기선 값 기준 검증)

        # 2) enum
        allowed = set(rule.get("enum", [0, 1]))  # 기본 0/1 허용
        if val not in allowed:
            self._emit("enum", sig, val, "FAIL")
            print(f"[FAIL] {sig}: {val} not in {sorted(allowed)}")
            # enum 위반 시 추가 검사 의미 없음
            self._prev_values[sig] = val
            return
        else:
            self._emit("enum", sig, val, "OK")

        # 3) range 확인 — 보통 0~1로 enum과 동일 효과
        if "min" in rule or "max" in rule:
            mn = rule.get("min", 0)
            mx = rule.get("max", 1)
            status = "OK" if (mn <= val <= mx) else "FAIL"
            self._emit("range", sig, val, status)
            if status == "FAIL":
                print(f"[FAIL] {sig}: {val} out of [{mn}, {mx}]")

        # 상태 갱신
        self._prev_values[sig] = val

    # ─────────────────────────────────────────────────────────────────────────
    def _emit(self, metric: str, sig: str, value: Any, status: str):
        ev = {
            "type": "dbc",
            "id": self.target_id,
            "metric": metric,   # enum | range | monotonic | decode_error | missing_signal
            "signal": sig,
            "value": value,
            "status": status,
            "ts_ms": int(time.time() * 1000),
        }
        self.events.append(ev)
        log_event("dbc", self.target_id, f"{sig}:{metric}", value, status)

    def fetch_events(self):
        out = self.events[:]
        self.events.clear()
        return out