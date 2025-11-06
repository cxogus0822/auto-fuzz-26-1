# ======================================
# 🧬 Mutator Skeleton (CLI 환경용)
# ======================================

import random
from typing import Dict, Tuple, Any


class Mutator:
    def __init__(self, data: bytes, weights: Dict[str, float]):
        """
        data: 변이 대상 원본 데이터 (bytes)
        weights: monitor로부터 전달받은 가중치 딕셔너리
        """
        self.data = bytearray(data)
        self.weights = weights  # 단순 저장만 수행

    def mutate_manager(self) -> None:
        """전체 mutation 관리"""

        pass

    # -----------------------------
    # 🔹 Bit-level mutation
    # -----------------------------
    
    
    def flip_bit(self) -> None:
        """랜덤 바이트 내 특정 비트를 flip"""
        byte_idx = self.select_random_byte()                    # ① 바이트 선택
        bit_idx = self.select_random_bit(self.data[byte_idx])   # ② 비트 선택
        self.data[byte_idx] ^= (1 << bit_idx)                   # ③ 선택된 비트 flip

    def increment_bit(self) -> None:
        """랜덤 비트를 +1"""
        byte_idx = self.select_random_byte()
        bit_idx = self.select_random_bit(self.data[byte_idx])
        mask = (1 << bit_idx)
        if (self.data[byte_idx] & mask) == 0:  # 비트가 0이면 1로
            self.data[byte_idx] |= mask

    def decrement_bit(self) -> None:
        """랜덤 비트를 -1"""
        byte_idx = self.select_random_byte()
        bit_idx = self.select_random_bit(self.data[byte_idx])
        mask = (1 << bit_idx)
        if (self.data[byte_idx] & mask) != 0:  # 비트가 1이면 0으로
            self.data[byte_idx] &= ~mask

    # -----------------------------
    # 🔹 Byte-level mutation
    # -----------------------------
    def increment_byte(self) -> None:
        """랜덤 바이트를 +1"""
        byte_idx = self.select_random_byte()
        self.data[byte_idx] = (self.data[byte_idx] + 1) & 0xFF

    def decrement_byte(self) -> None:
        """랜덤 바이트를 -1"""
        byte_idx = self.select_random_byte()
        self.data[byte_idx] = (self.data[byte_idx] - 1) & 0xFF

    def insert_byte(self) -> None:
        """랜덤 위치에 새로운 바이트 삽입"""
        insert_pos = random.randint(0, len(self.data))
        new_val = random.randint(0, 255)
        self.data.insert(insert_pos, new_val)

    def delete_byte(self) -> None:
        """랜덤 위치의 바이트 삭제"""
        if not self.data:
            return
        del_pos = self.select_random_byte()
        del self.data[del_pos]

    # -----------------------------
    # 🔹 Utility selectors
    # -----------------------------
    def select_random_byte(self) -> int:
        """mutation 대상 바이트 인덱스 선택"""
        pass

    def select_random_bit(self, byte_value: int) -> int:
        """선택된 바이트 내 mutation 대상 비트 인덱스 선택"""
        pass

 
    
