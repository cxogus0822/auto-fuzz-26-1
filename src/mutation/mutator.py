import random
from typing import Dict, List
from ..logger.base_logger import log_event  

DEFAULT_BYTE_K_PROB = 0.3  
DEFAULT_BYTE_WEIGHT = 1.0  
DEFAULT_EDGE_BIAS   = 0.0  

DEFAULT_BIT_K_PROB  = 0.4  
DEFAULT_BIT_WEIGHT  = 1.0  
DEFAULT_MSB_BIAS    = 0.0  
DEFAULT_LSB_BIAS    = 0.0  
DEFAULT_BUDGET      = 256
DEFAULT_MAX_OPS     = 3

MAX_CAN_DLC = 8


class Mutator:
    def __init__(self, data: bytes, weights: Dict[str, float], min_length: int = 1):
        self.data = bytearray(data)
        self.weights = weights
        self.min_length = min_length

    ...
    # Manager
    def mutate_manager(self) -> list[bytes]:
        budget        = int(self.weights.get("manager.budget", 256))
        max_ops       = int(self.weights.get("manager.max_ops", 3))
        enable_struct = bool(self.weights.get("manager.structural", True))
        include_orig  = bool(self.weights.get("manager.include_original", False))

        out: list[bytes] = []
        seen: set[bytes] = set()
        base = bytes(self.data)

        def push():
            b = bytes(self.data)

            if len(b) > MAX_CAN_DLC:
                return
            if len(b) < self.min_length:
                return

            if b not in seen:
                seen.add(b)
                out.append(b)

        if include_orig:
            self.data = bytearray(base)
            push()

        attempt_cap = budget * 20
        attempts = 0

        while len(out) < budget and attempts < attempt_cap:
            attempts += 1
            saved = self.data
            self.data = bytearray(base)

            try:
                k = random.randint(1, max_ops)
                for _ in range(k):
                    op = random.choice([
                        "flip_bit",
                        "increment_bit",
                        "decrement_bit",
                        "increment_byte",
                        "decrement_byte",
                        "insert_byte" if enable_struct else "increment_byte",
                        "delete_byte" if enable_struct else "decrement_byte",
                    ])
                    try:
                        getattr(self, op)()
                    except Exception as e:
                        self._log_fail(op, e)

                push()
            except Exception as e:
                self._log_fail("mutate_manager", e)
            finally:
                self.data = saved

        self.generated = out
        return out

    # Byte Ops
    def insert_byte(self):
        try:
            if len(self.data) >= MAX_CAN_DLC:
                return

            pos = random.randint(0, len(self.data))
            val = random.randint(0, 255)
            self.data.insert(pos, val)
        except Exception as e:
            self._log_fail("insert_byte", e)
