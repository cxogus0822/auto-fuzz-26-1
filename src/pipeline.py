# src/pipeline.py
import random
import time
from seeds.dbc_parser import DbcParser
from seeds.seed_manager import SeedManager, Seed
from seeds.seed_queue import SeedQueue


class AutoFuzzPipeline:
    """전체 퍼저 초기화 및 Seed 관리 파이프라인"""

    # 1️. Seed 등록
    @staticmethod
    def register_seeds(dbc_path: str, db_path: str = "seeds.db") -> int:
        """Parse DBC and register seeds into DB (message-group aware)"""
        parser = DbcParser(dbc_path)
        parsed = parser.parse()

        manager = SeedManager(db_path)
        seed_groups = manager.from_dbc(parsed)      # List[List[Seed]]
        queue = SeedQueue(db_path)

        total_count = 0
        for group in seed_groups:
            queue.push_group(group)
            total_count += len(group)

        queue.close()
        manager.close()
        return total_count

    # 2️. Seed 목록 조회
    @staticmethod
    def list_seeds(db_path: str = "seeds.db"):
        manager = SeedManager(db_path)
        seeds = manager.get_all()
        manager.close()
        return seeds

    # 3️. 퍼징 실행
    def __init__(self, db_path: str = "seeds.db"):
        self.queue = SeedQueue(db_path)
        self.running = False

    def mutate(self, seed: Seed) -> Seed:
        """간단한 변이: factor + offset 기반 랜덤 변형"""
        meta = seed.metadata
        if meta.minimum is not None and meta.maximum is not None:
            val = random.uniform(meta.minimum, meta.maximum)
            meta.offset = round(val * (meta.factor or 1.0), 2)
        else:
            # 최소/최대값이 없을 경우 기본 변형
            meta.offset = round(random.uniform(-10, 10), 2)
        return seed

    def send(self, seed: Seed):
        """CAN 메시지 송신 Stub (향후 python-can 연동 가능)"""
        print(f"[Tx] ID={hex(seed.message_id)} Signal={seed.signal_name:<25} -> val={seed.metadata.offset}")

    def monitor(self) -> float:
        """임시 모니터 점수 (0~1 사이 랜덤값)"""
        return round(random.uniform(0, 1), 3)

    def feedback(self, seed: Seed, score: float):
        """모니터링 피드백 기반으로 우선순위 조정"""
        if score > 0.7:
            self.queue.update_priority(seed.id, +1)
            print(f"  ↑ High score {score} → priority ↑")
        elif score < 0.3:
            self.queue.update_priority(seed.id, -1)
            print(f"  ↓ Low score {score} → priority ↓")
        else:
            print(f"  • Neutral score {score}, no priority change")

    def run(self):
        """퍼징 루프 실행"""
        self.running = True
        print("[+] Auto-Fuzz pipeline started.")

        while self.running:
            seed = self.queue.pop()
            if not seed:
                print("[!] No more seeds in queue. Stopping fuzzing.")
                break

            mutated = self.mutate(seed)
            self.send(mutated)
            score = self.monitor()
            self.feedback(seed, score)

            time.sleep(0.2)     # 전송 주기 (200ms)

        print("[✓] Fuzzing complete.")
        self.queue.close()
