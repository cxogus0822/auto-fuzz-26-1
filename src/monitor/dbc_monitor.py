# src/monitor/dbc_monitor.py
# DBC 기반 1-bit 신호 모니터

import time
import can
import cantools
from typing import Dict, Any, Optional, List
from logger.base_logger import log_event
from seeds.seed_manager import SeedManager


CAN_CHANNEL = "can0"
DBC_PATH    = "db/your.ecu.dbc"   # 실제 경로로 교체
TARGET_ID   = 0x366               # Blinkmodi_02

# ─────────────────────────────────────────────────────────────────────────────

class DBCMonitor:
    def _infer_rules_from_seeds(self, seeds, target_id):
        rules = {}
        for sd in seeds:
            if sd.message_id != target_id:
                continue
            meta = sd.metadata or {}
            length = getattr(meta, "length", None) or (meta.get("length") if isinstance(meta, dict) else None)
            if length != 1:
                continue

            mn = (meta.minimum if hasattr(meta, "minimum") else meta.get("minimum", 0))
            mx = (meta.maximum if hasattr(meta, "maximum") else meta.get("maximum", 1))
            enum_vals = meta.get("enum", [0, 1])  # 메타에 enum이 있으면 그대로 사용

            rule = {"enum": enum_vals, "min": mn, "max": mx}

            rules[sd.signal_name] = rule
        return rules
    
    def __init__(self,
                 channel: str = CAN_CHANNEL,
                 dbc_path: str = DBC_PATH,
                 target_id: int = TARGET_ID,
                 rules: Optional[Dict[str, Dict[str, Any]]] = None,
                 seed_db_path: str = "db/seeds.sqlite" 
                 ):
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
        
        # Seed DB에서 규칙 자동 구성
        if not self.rules:
            manager = SeedManager(seed_db_path)
            seeds = manager.get_all()
            self.rules = self._infer_rules_from_seeds(seeds, self.target_id)
            print(f"[INFO] Seed DB로부터 {len(self.rules)}개의 신호 규칙을 불러왔습니다.")
            if not self.rules:
                print("[WARN] Seed DB에서 규칙을 찾지 못했습니다. 검증 없이 모니터링을 진행합니다.")

        # 내부 상태
        self._prev_values: Dict[str, int] = {}  # 각 신호의 직전 값(0/1)
        self.events: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────
    def start(self):
        print(f"[ INFO ] DBCMonitor: 0x{self.target_id:X} on {self.channel}")
        print(f"         DBC={self.dbc_path}, signals={list(self.rules.keys()) or '—'}")

        while True:
            msg = self.bus.recv(timeout=1)
            if not msg or msg.arbitration_id != self.target_id:
                continue

            try:
                # choices를 숫자로 받기 위해 False 권장
                decoded = self.msg_def.decode(bytes(msg.data), decode_choices=False, scaling=True)
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

                # bool로 강제 캐스팅(0/1), float로 오더라도 정규화, 타입 일관성 보장
                try:
                    val = int(float(decoded[sig]))
                except Exception:
                    # 혹시라도 문자열/예외가 들어오면 방어
                    self._emit("type_cast", sig, decoded[sig], "FAIL")
                    print(f"[FAIL] {sig}: cannot cast value={decoded[sig]!r} to int")
                    continue

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
            "metric": metric,   # enum | range 
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