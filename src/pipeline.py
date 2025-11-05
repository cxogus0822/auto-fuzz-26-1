# src/pipeline.py
import time
from seeds.dbc_parser import DbcParser
from seeds.seed_manager import SeedManager, Seed
from seeds.seed_queue import SeedQueue
from typing import Optional


class AutoFuzzPipeline:
    """Seed DB 기반 CAN 송신 파이프라인"""

    # Seed 등록 및 조회
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


    # 초기화 및 송신
    def __init__(self, db_path: str = "seeds.db", can_iface: Optional[object] = None):
        """
        db_path: Seed DB 경로
        can_iface: CLI에서 전달받은 CANInterface (없으면 stub 모드)
         = CLI에서 --can 옵션을 주지 않는 경우, 터미널 출력만 보이는 stub 모드
        """
        self.queue = SeedQueue(db_path)
        self.can = can_iface
        self.running = False

    def send(self, seed: Seed):
        """Seed를 CAN으로 송신 (seed.message_id 우선, 없으면 fallback)"""
        if not self.can:
            arb = seed.message_id or 0x6A6
            print(f"[Stub:Tx] ID={hex(arb)} | Signal={seed.signal_name:<25}")
            return

        try:
            value = int(seed.metadata.offset or 0)
        except Exception:
            value = 0

        data = value.to_bytes(8, "little", signed=True)
        arb = getattr(seed, "message_id", None) or getattr(self.can, "can_id", 0x6A6)

        try:
            self.can.send_raw(data, arb_id=arb)
        except Exception as e:
            print(f"[!] CAN send error: {e}")


    # 실행 루프
    def run(self):
        """Seed 큐 순회하며 송신"""
        self.running = True
        print("[+] Auto-Fuzz pipeline started (mutation/monitor disabled).")

        if self.can:
            try:
                self.can.start_listener()
            except Exception as e:
                print(f"[!] CAN listener start failed: {e}")

        while self.running:
            seed = self.queue.pop()
            if not seed:
                print("[!] No more seeds. Stopping.")
                break

            self.send(seed)
            time.sleep(0.2)

        if self.can:
            self.can.stop_listener()

        print("[✓] Fuzzing complete.")
        self.queue.close()
