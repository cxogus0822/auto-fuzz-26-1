import random
from typing import Dict


class Mutator:
    def __init__(self, data: bytes, weights: Dict[str, float]):
        """
        data: 변이 대상 원본 데이터 (bytes)
        weights: monitor로부터 전달받은 가중치 딕셔너리
        """
        self.data = bytearray(data)
        self.weights = weights  # 단순 저장만 수행

    def mutate_manager(self) -> list[bytes]:
        budget        = int(self.weights.get("manager.budget", 256))
        max_ops       = int(self.weights.get("manager.max_ops", 3))
        enable_struct = bool(self.weights.get("manager.structural", True))
        include_orig  = bool(self.weights.get("manager.include_original", False))
        
        rng = random

        out: list[bytes] = []
        seen: set[bytes] = set()

        def add_snapshot_from_current_buf():
            b = bytes(self.data)
            if b not in seen:
                seen.add(b)
                out.append(b)

        base = bytes(self.data)

        if include_orig:
            # 원본을 스냅샷으로 추가
            self.data = bytearray(base)
            add_snapshot_from_current_buf()

        attempt_cap = budget * 20
        attempts = 0
        while len(out) < budget and attempts < attempt_cap:
            attempts += 1

            # 이번 시드용 작업 버퍼 준비
            saved = self.data
            self.data = bytearray(base)
            try:
                k = rng.randint(1, max_ops)

                for _ in range(k):
                    op_kind = rng.choice([
                        "flip_bit",
                        "increment_bit",
                        "decrement_bit",
                        "increment_byte",
                        "decrement_byte",
                        "insert_byte" if enable_struct else "increment_byte",
                        "delete_byte" if enable_struct else "decrement_byte",
                    ])
                    try:
                        # 이름으로 메서드 찾아 호출
                        getattr(self, op_kind)()
                    except Exception:
                        # 실패 연산은 스킵
                        continue

                # 현재 buf(self.data) 스냅샷 등록
                add_snapshot_from_current_buf()
            finally:
                # self.data 복구
                self.data = saved

        self.generated = out
        return out

    # -----------------------------
    # 🔹 Bit-level mutation
    # -----------------------------
    
    
    def flip_bit(self) -> None:
        """랜덤 바이트 내 특정 비트를 flip"""
        byte_idxs = self.select_random_byte()
        # 리스트/정수 모두 처리
        if isinstance(byte_idxs, int):
            byte_idxs = [byte_idxs]
        if not byte_idxs:
            return
        byte_idx = random.choice(byte_idxs)
        if not (0 <= byte_idx < len(self.data)):
            return

        bit_idxs = self.select_random_bit()
        if isinstance(bit_idxs, int):
            bit_idxs = [bit_idxs]
        if not bit_idxs:
            return
        bit_idx = random.choice(bit_idxs)  # 하나만 뽑아 적용
        self.data[byte_idx] ^= (1 << bit_idx)

    def increment_bit(self) -> None:
        """랜덤 비트를 +1"""
        byte_idxs = self.select_random_byte()
        if isinstance(byte_idxs, int):
            byte_idxs = [byte_idxs]
        if not byte_idxs:
            return
        byte_idx = random.choice(byte_idxs)
        if not (0 <= byte_idx < len(self.data)):
            return

        bit_idxs = self.select_random_bit()
        if isinstance(bit_idxs, int):
            bit_idxs = [bit_idxs]
        if not bit_idxs:
            return
        bit_idx = random.choice(bit_idxs)

        mask = (1 << bit_idx)
        if (self.data[byte_idx] & mask) == 0:
            self.data[byte_idx] |= mask

    def decrement_bit(self) -> None:
        """랜덤 비트를 -1"""
        byte_idxs = self.select_random_byte()
        if isinstance(byte_idxs, int):
            byte_idxs = [byte_idxs]
        if not byte_idxs:
            return
        byte_idx = random.choice(byte_idxs)
        if not (0 <= byte_idx < len(self.data)):
            return

        bit_idxs = self.select_random_bit()
        if isinstance(bit_idxs, int):
            bit_idxs = [bit_idxs]
        if not bit_idxs:
            return
        bit_idx = random.choice(bit_idxs)

        mask = (1 << bit_idx)
        if (self.data[byte_idx] & mask) != 0:
            self.data[byte_idx] &= ~mask

    def increment_byte(self) -> None:
        """랜덤 바이트를 +1"""
        byte_idxs = self.select_random_byte()
        if isinstance(byte_idxs, int):
            byte_idxs = [byte_idxs]
        if not byte_idxs:
            return
        byte_idx = random.choice(byte_idxs)
        if 0 <= byte_idx < len(self.data):
            self.data[byte_idx] = (self.data[byte_idx] + 1) & 0xFF

    def decrement_byte(self) -> None:
        """랜덤 바이트를 -1"""
        byte_idxs = self.select_random_byte()
        if isinstance(byte_idxs, int):
            byte_idxs = [byte_idxs]
        if not byte_idxs:
            return
        byte_idx = random.choice(byte_idxs)
        if 0 <= byte_idx < len(self.data):
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
        del_idxs = self.select_random_byte()
        if isinstance(del_idxs, int):
            del_idxs = [del_idxs]
        if not del_idxs:
            return
        del_pos = random.choice(del_idxs)
        if 0 <= del_pos < len(self.data):
            del self.data[del_pos]

    # -----------------------------
    # 🔹 Utility selectors
    # -----------------------------
    def select_random_byte(self) -> list[int]:
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

    def select_random_bit(self) -> list[int]:
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