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
        pass

    def increment_bit(self) -> None:
        """랜덤 비트를 +1"""
        pass

    def decrement_bit(self) -> None:
        """랜덤 비트를 -1"""
        pass

    # -----------------------------
    # 🔹 Byte-level mutation
    # -----------------------------
    def increment_byte(self) -> None:
        """랜덤 바이트를 +1"""
        pass

    def decrement_byte(self) -> None:
        """랜덤 바이트를 -1"""
        pass

    def insert_byte(self) -> None:
        """랜덤 위치에 새로운 바이트 삽입"""
        pass

    def delete_byte(self) -> None:
        """랜덤 위치의 바이트 삭제"""
        pass

    # -----------------------------
    # 🔹 Utility selectors
    # -----------------------------
    def select_random_byte(self) -> int:
        """mutation 대상 바이트 인덱스 선택"""
        pass

    def select_random_bit(self, byte_value: int) -> int:
        """선택된 바이트 내 mutation 대상 비트 인덱스 선택"""
        pass

    # -----------------------------
    # 🔹 Dispatcher
    # -----------------------------
    def apply_mutation(self) -> Tuple[bytes, str]:
        """
        가중치나 랜덤에 따라 mutation 종류를 선택하고 수행
        결과: (mutated_data, operation_name)
        """
        pass
