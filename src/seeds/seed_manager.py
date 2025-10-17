# src/seeds/seed_manager.py
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict


@dataclass
class SignalMeta:
    """Signal 관련 세부 메타데이터 구조"""
    start_bit: Optional[int] = None
    length: Optional[int] = None
    byte_order: Optional[str] = None
    is_signed: Optional[bool] = None
    factor: Optional[float] = None      # scale → factor로 변경
    offset: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class Seed:
    """단일 Signal을 나타내는 Seed"""
    message_id: int
    signal_name: str
    desc: str = ""
    priority: int = 1
    metadata: SignalMeta = field(default_factory=SignalMeta)
    id: Optional[int] = None


class SeedManager:
    """Seed Pool 관리 및 DB 연동 클래스"""

    def __init__(self, db_path: str = "seeds.db"):
        self.conn = sqlite3.connect(db_path)
        self._create_table()

    def _create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS seeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            signal_name TEXT,
            desc TEXT,
            priority INTEGER,
            metadata TEXT
        );
        """
        self.conn.execute(query)
        self.conn.commit()

    def add_seed(self, seed: Seed) -> int:
        """새로운 Seed를 DB에 추가"""
        query = """
        INSERT INTO seeds (message_id, signal_name, desc, priority, metadata)
        VALUES (?, ?, ?, ?, ?);
        """
        cur = self.conn.execute(
            query,
            (
                seed.message_id,
                seed.signal_name,
                seed.desc,
                seed.priority,
                json.dumps(seed.metadata.__dict__),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_all(self) -> List[Seed]:
        """DB에 등록된 모든 Seed 반환 (우선순위 기준 정렬)"""
        rows = self.conn.execute(
            "SELECT id, message_id, signal_name, desc, priority, metadata FROM seeds ORDER BY priority DESC"
        ).fetchall()

        seeds: List[Seed] = []
        for row in rows:
            meta_dict = json.loads(row[5]) if row[5] else {}
            metadata = SignalMeta(**meta_dict)
            seeds.append(
                Seed(
                    id=row[0],
                    message_id=row[1],
                    signal_name=row[2],
                    desc=row[3],
                    priority=row[4],
                    metadata=metadata,
                )
            )
        return seeds

    def update_priority(self, seed_id: int, new_priority: int):
        self.conn.execute(
            "UPDATE seeds SET priority = ? WHERE id = ?", (new_priority, seed_id)
        )
        self.conn.commit()

    def delete_seed(self, seed_id: int):
        self.conn.execute("DELETE FROM seeds WHERE id = ?", (seed_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()

    # 메시지 단위 그룹 반환 (List[List[Seed]])
    @staticmethod
    def from_dbc(parsed_dbc: Dict[str, Any]) -> List[List["Seed"]]:
        """DbcParser.parse() 결과(dict)를 메시지 단위 Seed 그룹으로 변환"""
        grouped_seeds: List[List[Seed]] = []

        for msg in parsed_dbc.get("messages", []):
            message_group: List[Seed] = []

            for sig in msg.get("signals", []):
                meta = SignalMeta(
                    start_bit=sig.get("start_bit"),
                    length=sig.get("length"),
                    byte_order=sig.get("byte_order"),
                    is_signed=sig.get("is_signed"),
                    factor=sig.get("factor"),
                    offset=sig.get("offset"),
                    minimum=sig.get("minimum"),
                    maximum=sig.get("maximum"),
                    unit=sig.get("unit"),
                    comment=sig.get("comment"),
                )
                seed = Seed(
                    message_id=msg["id"],
                    signal_name=sig["name"],
                    desc=f"Signal {sig['name']} in {msg['name']}",
                    priority=1,
                    metadata=meta,
                )
                message_group.append(seed)

            grouped_seeds.append(message_group)

        return grouped_seeds