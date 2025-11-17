# src/monitor/dbc_monitor.py
# DBC 기반 신호 모니터 (1-bit + multi-bit, monotonic, raise on errors)

import time
import can
import cantools
from typing import Dict, Any, Optional, List, Union
from logger.base_logger import log_event
from seeds.seed_manager import SeedManager


CAN_CHANNEL = "can0"
DBC_PATH    = "db/your.ecu.dbc"   
TARGET_ID   = 0x6A6               
Number = Union[int, float]

class DBCMonitor:
    # ─────────────────────────────────────────────────────────────────────
    def _infer_rules_from_seeds(self, seeds, target_id): # Seed db에서 규칙 자동생성
        rules: Dict[str, Dict[str, Any]] = {}
        for sd in seeds:
            if sd.message_id != target_id:
                continue

            meta = getattr(sd, "metadata", {}) or {}
            def m(key, default=None): # 메타 접근 헬퍼 함수 : dict/객체 양쪽을 동일하게 다룸
                if isinstance(meta, dict):
                    return meta.get(key, default)
                return getattr(meta, key, default)

            length  = m("length")
            factor  = m("factor")
            minimum = m("minimum")
            maximum = m("maximum")
            enum    = m("enum")
            mono    = m("monotonic")

            if length == 1: # 1-bit 신호 불린 판단
                kind = "bool"; coerce_int = True # 오차 허용 불필요 항상 int 강제
                default_enum = [0, 1]; default_min, default_max = 0, 1 # 기본 불린 규칙 설정
            else:
                if factor not in (None, 0, 1):
                    kind = "float"; coerce_int = False
                else:
                    kind = "int"; coerce_int = True
                default_enum = None
                default_min, default_max = minimum, maximum

            rule = { # 추론된 규칙 생성
                "kind": kind,
                "enum": enum if enum is not None else default_enum,
                "min": default_min,
                "max": default_max,
                "monotonic": mono if mono in ("nondecreasing", "nonincreasing") else None,
                "coerce_int": coerce_int,
            }
            rules[sd.signal_name] = rule # 신호명 규칙 매핑에 추가
        return rules # 규칙 반환

    # ─────────────────────────────────────────────────────────────────────
    def __init__(self,
                 channel: str = CAN_CHANNEL,
                 dbc_path: str = DBC_PATH,
                 target_id: int = TARGET_ID,
                 rules: Optional[Dict[str, Dict[str, Any]]] = None,
                 seed_db_path: str = "db/seeds.sqlite"):
        self.channel = channel
        self.dbc_path = dbc_path
        self.target_id = target_id
        self.rules = rules or {}

        # CAN / DBC 초기화
        self.bus = can.interface.Bus(channel=self.channel, bustype="socketcan")
        self.db  = cantools.database.load_file(self.dbc_path)
        self.msg_def = self.db.get_message_by_frame_id(self.target_id)
        if self.msg_def is None:
            raise ValueError(f"DBC에 ID 0x{self.target_id:X} 메시지 정의가 없습니다.") # 해당 메시지 없을 경우 예외 처리

        # Seed DB에서 규칙 자동 구성
        if not self.rules:
            manager = SeedManager(seed_db_path)
            seeds = manager.get_all()
            self.rules = self._infer_rules_from_seeds(seeds, self.target_id)
            print(f"[INFO] Seed DB로부터 {len(self.rules)}개의 신호 규칙을 불러왔습니다.")
            if not self.rules:
                print("[WARN] Seed DB에서 규칙을 찾지 못했습니다. 검증 없이 모니터링을 진행합니다.")

        # 내부 상태
        self._prev_values: Dict[str, Number] = {}  # 직전값(단조성 검사용)
        self.events: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────
    def start(self):
        print(f"[ INFO ] DBCMonitor: 0x{self.target_id:X} on {self.channel}")
        print(f"         DBC={self.dbc_path}, signals={list(self.rules.keys()) or '—'}")

        while True:
            try:
                msg = self.bus.recv(timeout=1)
                if not msg or msg.arbitration_id != self.target_id:
                    continue

            # 디코드 실패
                try:
                    decoded = self.msg_def.decode(bytes(msg.data), decode_choices=False, scaling=True)
                
                except Exception as e:
                    self._emit("decode_error", "_frame", str(e), "FAIL")
                    continue

            # 신호별 검사
                for sig, rule in self.rules.items():
                    try: 
                        if sig not in decoded:
                            self._emit("missing_signal", sig, None, "FAIL")
                            raise RuntimeError(f"신호 누락: {sig} - DBC에 정의된 신호가 디코딩 결과에 없습니다.")

                        raw = decoded[sig]

                # 타입 정규화 
                        try:
                            val = self._normalize_value(raw, rule)
                        except Exception as e:
                            self._emit("type_cast", sig, raw, "FAIL")
                            raise ValueError(f"type cast 실패: signal={sig}, value={raw!r}") from e

                        try:
                            self._check_rules(sig, val, rule)
                        except Exception as e:
                            raise RuntimeError(f"rule 위반: signal={sig}, value={val}, err={e}"
                        ) from e
                    
                    except Exception as sig_err:
                        continue

            except KeyboardInterrupt:
                print("[ INFO ] KeyboardInterrupt: stopping monitor")
                break

    # ─────────────────────────────────────────────────────────────────────
    def _normalize_value(self, raw: Any, rule: Dict[str, Any]) -> Number: # 규칙에 맞춰 값을 bool/int/float로 정규화
        kind = rule.get("kind", "int")
        if kind == "bool":
            v = int(float(raw))
            return 1 if v != 0 else 0  # 안전한 0/1화
        if kind == "int":
            if rule.get("coerce_int", True):
                return int(float(raw))
            if isinstance(raw, int):
                return raw
            return int(raw) if (isinstance(raw, float) and raw.is_integer()) else raw
        # float
        return float(raw)

    # ─────────────────────────────────────────────────────────────────────
    def _check_rules(self, sig: str, val: Number, rule: Dict[str, Any]):

        #enum 검사
        enum_vals = rule.get("enum")
        if enum_vals is not None:
            if rule.get("kind") == "float":
                enum_ok = any(float(val) == float(a) for a in enum_vals)
            else:
                enum_ok = val in set(int(a) for a in enum_vals)

            self._emit("enum", sig, val, "OK" if enum_ok else "FAIL")

            if not enum_ok:
                raise RuntimeError(f"enum 위반: {sig} value={val}, 허용={enum_vals}")

        # range 검사
        mn, mx = rule.get("min"), rule.get("max")
        range_ok = True

        if mn is not None and float(val) < float(mn):
            range_ok = False
        if mx is not None and float(val) > float(mx):
            range_ok = False

        self._emit("range", sig, val, "OK" if range_ok else "FAIL")

        if not range_ok:
            raise RuntimeError(f"range 위반: {sig} value={val}, min={mn}, max={mx}")

        # 단조성 검사
        mode = rule.get("monotonic")
        if mode:
            prev = self._prev_values.get(sig)
            mono_ok = True
            
            if prev is not None:
                pv = float(prev)
                cv = float(val)

                if mode == "nondecreasing" and cv < pv:
                    mono_ok = False
                if mode == "nonincreasing" and cv > pv:
                    mono_ok = False

            self._emit("monotonic", sig, {"prev": prev, "cur": val, "mode": mode}, "OK" if mono_ok else "FAIL")

            if not mono_ok:
                raise RuntimeError(f"단조성 위반: {sig} {prev} → {val} ({mode})")

        self._prev_values[sig] = val # 정상 통과 시 이전값 갱신

    # ─────────────────────────────────────────────────────────────────────
    def _emit(self, metric: str, sig: str, value: Any, status: str):
        ev = {
            "type": "dbc",
            "id": self.target_id,
            "metric": metric,
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