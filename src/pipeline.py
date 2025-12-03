# src/pipeline.py

import time
import json
from typing import Optional, Dict, Any

from .seeds.dbc_parser import DbcParser
from .seeds.seed_manager import SeedManager, Seed
from .seeds.seed_queue import SeedQueue

from .monitor.monitor_manager import MonitorManager
from .monitor.timing_monitor import TimingMonitor
from .monitor.uds_monitor import UDSMonitor
from .monitor.dbc_monitor import DBCMonitor

from .mutation.mutator import Mutator


class AutoFuzzPipeline:
    
    # 시드 등록
    @staticmethod
    def register_seeds(dbc_path: str, db_path: str = "seeds.db") -> int:
        parser = DbcParser(dbc_path)
        parsed = parser.parse()

        manager = SeedManager(db_path)
        seed_groups = manager.from_dbc(parsed)
        queue = SeedQueue(db_path)

        total = 0
        for group in seed_groups:
            queue.push_group(group)
            total += len(group)

        queue.close()
        manager.close()
        return total

    
    # 시드 목록
    @staticmethod
    def list_seeds(db_path: str = "seeds.db"):
        manager = SeedManager(db_path)
        seeds = manager.get_all()
        manager.close()
        return seeds


    # config
    def __init__(self, cfg: Dict[str, Any], can_iface: Optional[object] = None):
        """
        cfg: config dict (default.yaml 또는 사용자 config)
        """

        self.cfg = cfg
        self.can = can_iface
        self.running = False

        # 시드 큐 초기화
        seed_db_path = cfg["paths"]["seed_db"]
        self.queue = SeedQueue(seed_db_path)

        # 모니터 매니저
        self.monitor_manager = MonitorManager(
            timing_monitor=TimingMonitor(),
            uds_monitor=UDSMonitor(),
            dbc_monitor=DBCMonitor(
                channel=cfg["can"]["channel"],
                dbc_path=cfg["paths"]["dbc"],
                target_id=int(cfg["can"]["default_id"], 16),
                seed_db_path=cfg["paths"]["seed_db"]
            )
        )


    # CAN 송신
    def send_raw_payload(self, data: bytes, arb_id: int):
        """실제 CAN raw 송신 또는 스텁 출력"""
        if not self.can:
            print(f"[Stub:Tx] ID={hex(arb_id)} | Data={data.hex()}")
            return

        try:
            self.can.send_raw(data, arb_id=arb_id)
        except Exception as e:
            print(f"[!] CAN send error: {e}")

    
    # 시드
    def fuzz_seed(self, seed: Seed, monitor_weights: Dict[str, float]):
        """
        1. seed → base bytes 생성
        2. Mutator 생성 & mutate_manager 실행
        3. Mutated payload 각각 CAN 송신
        """

        try:
            value = int(seed.metadata.offset or 0)
            base_data = value.to_bytes(8, "little", signed=True)
        except Exception:
            base_data = (0).to_bytes(8, "little")

        mut = Mutator(
            data=base_data,
            weights=monitor_weights,
            min_length=1
        )

        mutated_list = mut.mutate_manager()

        if self.cfg["can"].get("force_default_id", False):
            arb_id = int(self.cfg["can"]["default_id"], 16)
        else:
            arb_id = seed.message_id or int(self.cfg["can"]["default_id"], 16)

        for payload in mutated_list:
            self.send_raw_payload(payload, arb_id)
            time.sleep(0.01)


    # 실행
    def run(self) -> Dict[str, Any]:
        """
        0. config 기반 timeout 읽기
        1. 모니터 시작
        2. Seed pop → fuzz → Tx
        3. 모니터 종료
        4. 점수/상태 반환
        """

        self.running = True

        timing_timeout = float(self.cfg["fuzz"]["timing_timeout"])
        dbc_timeout = float(self.cfg["fuzz"]["dbc_timeout"])

        # 1. 모니터 시작
        self.monitor_manager.start_monitors(
            timing_timeout=timing_timeout,
            dbc_timeout=dbc_timeout
        )

        # 2. CAN Listener 시작
        if self.can:
            try:
                self.can.start_listener()
            except Exception as e:
                print(f"[!] CAN listener start failed: {e}")

        monitor_weights = {}  # Mutator 가중치 (추후 확장)

        # 3. fuzz loop
        while self.running:
            seed = self.queue.pop()
            if not seed:
                break

            self.fuzz_seed(seed, monitor_weights)
            time.sleep(0.2)

        # 4. CAN listener 종료
        if self.can:
            self.can.stop_listener()

        # 5. monitor 종료 대기
        self.monitor_manager.wait_for_completion()

        scores = self.monitor_manager.get_scores()
        completed = self.monitor_manager.get_completion_status()
        status = self.monitor_manager.get_status()

        self.queue.close()

        # 6. 결과 리턴
        return {
            "timing": {
                "score": scores["timing"],
                "completed": completed["timing"],
                "status": status["timing"],
            },
            "uds": {
                "score": scores["uds"],
                "completed": completed["uds"],
                "status": status["uds"],
            },
            "dbc": {
                "score": scores["dbc"],
                "completed": completed["dbc"],
                "status": status["dbc"],
            },
        }