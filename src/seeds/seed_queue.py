# src/seeds/seed_queue.py

import heapq
import itertools
from typing import List, Optional
from ..seeds.seed_manager import Seed, SeedManager


class SeedQueue:
    """
    개선된 우선순위 기반 Seed 큐
    - 우선순위(priority)가 같을 때 Seed 객체끼리 비교하는 문제 해결
    - tiebreaker(counter) 사용하여 Heap 안정성 보장
    """

    def __init__(self, db_path: str = "seeds.db"):
        self.manager = SeedManager(db_path)

        # tiebreaker counter
        self._counter = itertools.count()

        # tuple 구조: ( -priority, tiebreaker, Seed )
        self.queue: List[tuple[int, int, Seed]] = []

        self.load_from_db()


    # Load all seeds from DB into the priority heap
    def load_from_db(self):
        """DB에서 모든 Seed 로드 → 메모리 큐에 적재"""
        for seed in self.manager.get_all():
            tiebreaker = next(self._counter)
            heapq.heappush(self.queue, (-seed.priority, tiebreaker, seed))


    # Push single seed
    def push(self, seed: Seed):
        """단일 Seed 추가"""

        seed_id = self.manager.add_seed(seed)
        seed.id = seed_id

        tiebreaker = next(self._counter)
        heapq.heappush(self.queue, (-seed.priority, tiebreaker, seed))


    # Push group of seeds (message-level)
    def push_group(self, seeds: List[Seed]):
        """메시지 단위 Seed 그룹을 모두 추가"""
        for seed in seeds:
            self.push(seed)


    # Pop highest priority seed
    def pop(self) -> Optional[Seed]:
        """가장 우선순위 높은 Seed 꺼내기"""
        if not self.queue:
            return None

        _, _, seed = heapq.heappop(self.queue)
        return seed


    # Update seed priority and reorder heap
    def update_priority(self, seed_id: int, delta: int):
        """특정 Seed 우선순위 갱신 및 큐 재정렬"""

        updated = False

        for i, (priority, tiebreaker, seed) in enumerate(self.queue):
            if seed.id == seed_id:

                # update priority value
                seed.priority = max(1, min(seed.priority + delta, 10))
                self.manager.update_priority(seed.id, seed.priority)

                # replace heap entry
                self.queue[i] = (-seed.priority, tiebreaker, seed)

                updated = True
                break

        if updated:
            heapq.heapify(self.queue)


    # Return list of seeds sorted by priority
    def list(self) -> List[Seed]:
        """현재 큐 상태 반환 (우선순위 높은 순서)"""
        sorted_list = sorted(self.queue, key=lambda x: (x[0], x[1]))
        return [seed for _, _, seed in sorted_list]


    # Close DB manager
    def close(self):
        self.manager.close()