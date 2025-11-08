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
        n = len(self.data)
        if n == 0:
            raise ValueError("빈 데이터에서는 바이트를 선택할 수 없습니다.")

        p = float(self.weights.get("byte_k_p", 0.3))
        k = 1
        while random.random() > p and k < n:
            k += 1
        k = min(k, max(1, n // 3))  # 상한: 전체의 1/3

        ws = [float(self.weights.get(f"byte:{i}", 1.0)) for i in range(n)] # 기본 가중치

        edge = float(self.weights.get("edge_bias", 0.0))
        if edge > 0 and n >= 2:
            ws[0] += edge
            ws[-1] += edge

        total = sum(ws)
        if total <= 0:
            return random.sample(range(n), k)
        choices = random.choices(range(n), weights=ws, k=k)

        return list(sorted(set(choices))) # 중복 방지: set으로 정리

    def select_random_bit(self) -> int:
        """선택된 바이트 내 mutation 대상 비트 인덱스 선택"""
        p = float(self.weights.get("bit_k_p", 0.4))
        k = 1
        while random.random() > p and k < 8:
            k += 1
        k = min(k, 8)

        # 2️⃣ 기본 가중치
        w = [float(self.weights.get(f"bit:{b}", 1.0)) for b in range(8)]

        # 3️⃣ MSB/LSB 바이어스
        msb = float(self.weights.get("msb_bias", 0.0))
        lsb = float(self.weights.get("lsb_bias", 0.0))
        if msb > 0:
            w = [wb + msb * (b / 7.0) for b, wb in enumerate(w)]
        if lsb > 0:
            w = [wb + lsb * ((7 - b) / 7.0) for b, wb in enumerate(w)]

        total = sum(w)
        if total <= 0:
            return random.sample(range(8), k)
        choices = random.choices(range(8), weights=w, k=k)
        return list(sorted(set(choices)))
 
    
