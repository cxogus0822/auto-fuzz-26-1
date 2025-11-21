# src/monitor/dbc_monitor.py
# DBC 기반 신호 모니터 (1-bit + multi-bit, monotonic, raise on errors)

import time
import can
import cantools
from typing import Dict, Any, Optional, List, Union
from ..logger.base_logger import log_event
from ..seeds.seed_manager import SeedManager


CAN_CHANNEL = "can0"
DBC_PATH    = "db/your.ecu.dbc"   
TARGET_ID   = 0x6A6               
Number = Union[int, float]


class DBCMonitor:
    def _infer_rules_from_seeds(self, seeds, target_id):
        rules: Dict[str, Dict[str, Any]] = {}
        for sd in seeds:
            if sd.message_id != target_id:
                continue

            meta = getattr(sd, "metadata", {}) or {}

            def m(key, default=None):
                if isinstance(meta, dict):
                    return meta.get(key, default)
                return getattr(meta, key, default)

            length  = m("length")
            factor  = m("factor")
            minimum = m("minimum")
            maximum = m("maximum")
            enum    = m("enum")
            mono    = m("monotonic")

            if length == 1:
                kind = "bool"
                coerce_int = True
                default_enum = [0, 1]
                default_min, default_max = 0, 1
            else:
                if factor not in (None, 0, 1):
                    kind = "float"
                    coerce_int = False
                else:
                    kind = "int"
                    coerce_int = True
                default_enum = None
                default_min, default_max = minimum, maximum

            rule = {
                "kind": kind,
                "enum": enum if enum is not None else default_enum,
                "min": default_min,
                "max": default_max,
                "monotonic": mono if mono in ("nondecreasing", "nonincreasing") else None,
                "coerce_int": coerce_int,
            }
            rules[sd.signal_name] = rule

        return rules


    def __init__(
        self,
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

        # Seed DB 기반 규칙 생성
        if not self.rules:
            manager = SeedManager(seed_db_path)
            seeds = manager.get_all()
            self.rules = self._infer_rules_from_seeds(seeds, self.target_id)
            print(f"[INFO] Seed DB로부터 {len(self.rules)}개의 신호 규칙을 불러왔습니다.")
            if not self.rules:
                print("[WARN] Seed DB에서 규칙을 찾지 못했습니다. 검증 없이 모니터링을 진행합니다.")

        # 내부 상태
        self._prev_values: Dict[str, Number] = {}
        self.events: List[Dict[str, Any]] = []
        self._fail_score = 0.0
        self._fail_count = 0
        self._total_checks = 0


    def start(self, timeout: Optional[float] = None) -> float:
        """
        DBC 모니터링 시작
        예외 발생 시 즉시 종료하고 FAIL 스코어 반환
        timeout이 설정되면 해당 시간 동안만 실행 후 종료

        :param timeout: 최대 실행 시간(초). None이면 무제한
        :return: 최종 FAIL 스코어 (0.0 ~ 1.0)
        """

        print(f"[ INFO ] DBCMonitor: 0x{self.target_id:X} on {self.channel}")
        print(f"         DBC={self.dbc_path}, signals={list(self.rules.keys()) or '—'}")

        self._fail_score = 0.0
        self._fail_count = 0
        self._total_checks = 0

        start_time = time.time()

        try:
            while True:

                # Timeout 체크
                if timeout is not None:
                    if (time.time() - start_time) >= timeout:
                        print(f"[INFO] DBC Monitor timeout reached ({timeout}s)")
                        break

                msg = self.bus.recv(timeout=1)
                if not msg or msg.arbitration_id != self.target_id:
                    continue

                # 디코드
                try:
                    decoded = self.msg_def.decode(
                        bytes(msg.data),
                        decode_choices=False,
                        scaling=True
                    )
                except Exception as e:
                    self._emit("decode_error", "_frame", str(e), "FAIL")
                    self._fail_score = 1.0
                    raise RuntimeError(f"DBC decode 실패: {e}") from e

                # 규칙 검사
                for sig, rule in self.rules.items():
                    if sig not in decoded:
                        self._emit("missing_signal", sig, None, "FAIL")
                        self._fail_score = 1.0
                        raise RuntimeError(f"신호 누락: {sig}")

                    raw = decoded[sig]

                    try:
                        val = self._normalize_value(raw, rule)
                    except Exception as e:
                        self._emit("type_cast", sig, raw, "FAIL")
                        self._fail_score = 1.0
                        raise ValueError(
                            f"type cast 실패: signal={sig}, value={raw!r}"
                        ) from e

                    self._check_rules(sig, val, rule)

        except (RuntimeError, ValueError) as e:
            print(f"[INFO] DBC Monitor stopped due to error: {e}")
            print(f"[INFO] DBC Monitor finished - FAIL score: {self._fail_score:.3f}")
            return self._fail_score

        print(f"[INFO] DBC Monitor finished - FAIL score: {self._fail_score:.3f}")
        return self._fail_score


    def _normalize_value(self, raw: Any, rule: Dict[str, Any]) -> Number:
        kind = rule.get("kind", "int")

        if kind == "bool":
            v = int(float(raw))
            return 1 if v != 0 else 0

        if kind == "int":
            if rule.get("coerce_int", True):
                return int(float(raw))
            if isinstance(raw, int):
                return raw
            return int(raw) if (isinstance(raw, float) and raw.is_integer()) else raw

        return float(raw)


    def _check_rules(self, sig: str, val: Number, rule: Dict[str, Any]):
        # enum 검사
        enum_vals = rule.get("enum")
        if enum_vals is not None:
            self._total_checks += 1
            if rule.get("kind") == "float":
                enum_ok = any(float(val) == float(a) for a in enum_vals)
            else:
                enum_ok = val in set(int(a) for a in enum_vals)

            self._emit("enum", sig, val, "OK" if enum_ok else "FAIL")
            if not enum_ok:
                self._fail_count += 1
                self._update_fail_score()
                raise RuntimeError(f"enum 위반: {sig} value={val}, 허용={enum_vals}")

        # range 검사
        mn, mx = rule.get("min"), rule.get("max")

        if mn is not None:
            self._total_checks += 1
            if float(val) < float(mn):
                self._fail_count += 1
                self._emit("range", sig, val, "FAIL")
                self._update_fail_score()
                raise RuntimeError(f"range 하한 위반: {sig} value={val}, min={mn}")

        if mx is not None:
            self._total_checks += 1
            if float(val) > float(mx):
                self._fail_count += 1
                self._emit("range", sig, val, "FAIL")
                self._update_fail_score()
                raise RuntimeError(f"range 상한 위반: {sig} value={val}, max={mx}")

        if mn is not None or mx is not None:
            self._emit("range", sig, val, "OK")

        # 단조성 검사
        mode = rule.get("monotonic")
        if mode:
            prev = self._prev_values.get(sig)
            
            if prev is not None:
                self._total_checks += 1
                pv = float(prev)
                cv = float(val)

                if mode == "nondecreasing" and cv < pv:
                    self._fail_count += 1
                    self._emit("monotonic", sig, {"prev": prev, "cur": val, "mode": mode}, "FAIL")
                    self._update_fail_score()
                    raise RuntimeError(
                        f"단조성 위반: {sig} {prev} → {val} (nondecreasing)"
                    )

                if mode == "nonincreasing" and cv > pv:
                    self._fail_count += 1
                    self._emit("monotonic", sig, {"prev": prev, "cur": val, "mode": mode}, "FAIL")
                    self._update_fail_score()
                    raise RuntimeError(
                        f"단조성 위반: {sig} {prev} → {val} (nonincreasing)"
                    )

            self._emit("monotonic", sig, {"prev": prev, "cur": val, "mode": mode}, "OK")

        self._prev_values[sig] = val

    def _update_fail_score(self):
        if self._total_checks > 0:
            self._fail_score = 1.0 if self._fail_count > 0 else 0.0

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

    def get_fail_score(self) -> float:
        return self._fail_score
