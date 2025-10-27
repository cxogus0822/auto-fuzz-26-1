# src/logger/base_logger.py

import json
import os
from datetime import datetime

LOG_DIR = "logs"

def log_event(source, msg_id, metric, value, status):
    """모니터 결과를 공통 포맷으로 저장"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{source}.jsonl")

    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": source,           # timing / dbc / uds
        "msg_id": hex(msg_id),
        "metric": metric,           # e.g., "cycle_time", "signal_range", "nrc_response"
        "value": round(value, 2) if isinstance(value, (int, float)) else value,
        "status": status,           # OK / FAIL / WARN
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")
