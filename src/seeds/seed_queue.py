# src/seeds/seed_queue.py
import heapq
from typing import List, Optional
from .seed_manager import Seed, SeedManager


class SeedQueue:
    """우선순위 기반 Seed 큐 (메모리 + DB 연동)"""

    def __init__(self, db_path: str = "seeds.db"):
        self.manager = SeedManager(db_path)
        self.queue: List[tuple[int, Seed]] = []
        self.load_from_db()

    def load_from_db(self):
        """DB에서 모든 Seed 로드 → 메모리 큐에 적재"""
        for seed in self.manager.get_all():
            heapq.heappush(self.queue, (-seed.priority, seed))

    def push(self, seed: Seed):
        """단일 Seed 추가"""
        seed_id = self.manager.add_seed(seed)
        seed.id = seed_id
        heapq.heappush(self.queue, (-seed.priority, seed))

    # 메시지 단위 그룹 push
    def push_group(self, seeds: List[Seed]):
        """메시지 단위 Seed 그룹을 모두 추가"""
        for seed in seeds:
            self.push(seed)

    def pop(self) -> Optional[Seed]:
        """가장 우선순위 높은 Seed 꺼내기"""
        if not self.queue:
            return None
        _, seed = heapq.heappop(self.queue)
        return seed

    def update_priority(self, seed_id: int, delta: int):
        """특정 Seed 우선순위 갱신 및 큐 재정렬"""
        updated = False
        for i, (priority, seed) in enumerate(self.queue):
            if seed.id == seed_id:
                seed.priority = max(1, min(seed.priority + delta, 10))
                self.manager.update_priority(seed.id, seed.priority)
                self.queue[i] = (-seed.priority, seed)
                updated = True
                break
        if updated:
            heapq.heapify(self.queue)

    def list(self) -> List[Seed]:
        """현재 큐 상태 반환"""
        return [seed for _, seed in sorted(self.queue, key=lambda x: -x[0])]

    def close(self):
        self.manager.close()