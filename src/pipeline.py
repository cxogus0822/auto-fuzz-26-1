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

    @staticmethod
    def list_seeds(db_path: str = "seeds.db"):
        manager = SeedManager(db_path)
        seeds = manager.get_all()
        manager.close()
        return seeds


    def __init__(self, db_path: str = "seeds.db", can_iface: Optional[object] = None):
        self.queue = SeedQueue(db_path)
        self.can = can_iface
        self.running = False

        self.monitor_manager = MonitorManager(
            timing_monitor=TimingMonitor(),
            uds_monitor=UDSMonitor(),
            dbc_monitor=DBCMonitor()
        )


    def send_raw_payload(self, data: bytes, arb_id: int):
        """실제 CAN raw 송신 또는 스텁 출력"""
        if not self.can:
            print(f"[Stub:Tx] ID={hex(arb_id)} | Data={data.hex()}")
            return

        try:
            self.can.send_raw(data, arb_id=arb_id)
        except Exception as e:
            print(f"[!] CAN send error: {e}")


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

        arb_id = seed.message_id or 0x6A6

        for payload in mutated_list:
            self.send_raw_payload(payload, arb_id)
            time.sleep(0.01)


    def run(self) -> Dict[str, Any]:
        """
        1. 모니터 시작
        2. Seed pop
        3. Mutator → Tx
        4. 모니터 종료 + 결과 반환
        """
        self.running = True

        # 모니터 시작
        self.monitor_manager.start_monitors(
            timing_timeout=5.0,
            dbc_timeout=5.0
        )

        # CAN listener
        if self.can:
            try:
                self.can.start_listener()
            except Exception as e:
                print(f"[!] CAN listener start failed: {e}")

        # mutator 초기 가중치
        monitor_weights = {}

        # fuzzing
        while self.running:
            seed = self.queue.pop()
            if not seed:
                break

            self.fuzz_seed(seed, monitor_weights)
            time.sleep(0.2)

        if self.can:
            self.can.stop_listener()

        self.monitor_manager.wait_for_completion()

        scores = self.monitor_manager.get_scores()
        completed = self.monitor_manager.get_completion_status()
        status = self.monitor_manager.get_status()      # 상세 상태 추가

        self.queue.close()

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