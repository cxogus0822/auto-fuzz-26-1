# src/monitor/monitor_manager.py

import threading
import time
from typing import Dict, Optional
from monitor.timing_monitor import TimingMonitor
from monitor.uds_monitor import UDSMonitor
from monitor.dbc_monitor import DBCMonitor


class MonitorManager:

    def __init__(
        self,
        timing_monitor: Optional[TimingMonitor] = None,
        uds_monitor: Optional[UDSMonitor] = None,
        dbc_monitor: Optional[DBCMonitor] = None
    ):
        self.timing_monitor = timing_monitor
        self.uds_monitor = uds_monitor
        self.dbc_monitor = dbc_monitor

        self.threads: Dict[str, threading.Thread] = {}

        self.scores: Dict[str, float] = {
            "timing": 0.0,
            "uds": 0.0,
            "dbc": 0.0
        }
        self.scores_lock = threading.Lock()

        self.completed: Dict[str, bool] = {
            "timing": False,
            "uds": False,
            "dbc": False
        }

        self.running = False

    def start_monitors(
        self,
        timing_timeout: Optional[float] = 5.0,
        dbc_timeout: Optional[float] = 5.0
    ):
        """
        각 모니터를 별도 스레드로 시작
        """
        if self.running:
            print("[WARN] Monitors are already running")
            return

        self.running = True
        print("[INFO] Starting monitors...")

        # 초기화
        with self.scores_lock:
            self.scores = {"timing": 0.0, "uds": 0.0, "dbc": 0.0}
            self.completed = {"timing": False, "uds": False, "dbc": False}

        # Timing Monitor
        if self.timing_monitor:
            thread = threading.Thread(
                target=self._run_timing_monitor,
                args=(timing_timeout,),
                daemon=True,
                name="TimingMonitor"
            )
            self.threads["timing"] = thread
            thread.start()
            print("[INFO] ✓ Timing Monitor started")
        else:
            self.completed["timing"] = True

        # UDS Monitor
        if self.uds_monitor:
            thread = threading.Thread(
                target=self._run_uds_monitor,
                daemon=True,
                name="UDSMonitor"
            )
            self.threads["uds"] = thread
            thread.start()
            print("[INFO] ✓ UDS Monitor started")
        else:
            self.completed["uds"] = True

        # DBC Monitor
        if self.dbc_monitor:
            thread = threading.Thread(
                target=self._run_dbc_monitor,
                args=(dbc_timeout,),
                daemon=True,
                name="DBCMonitor"
            )
            self.threads["dbc"] = thread
            thread.start()
            print("[INFO] ✓ DBC Monitor started")
        else:
            self.completed["dbc"] = True

        print(f"[INFO] Total {len(self.threads)} monitor(s) running")


    def _run_timing_monitor(self, timeout: Optional[float]):
        try:
            fail_score = self.timing_monitor.start(timeout=timeout)

            with self.scores_lock:
                self.scores["timing"] = fail_score
                self.completed["timing"] = True

            print(f"[INFO] Timing Monitor completed - Score: {fail_score}")

        except Exception as e:
            print(f"[ERROR] Timing Monitor crashed: {e}")
            with self.scores_lock:
                self.completed["timing"] = True


    def _run_uds_monitor(self):
        try:
            fail_score = self.uds_monitor.start()

            with self.scores_lock:
                self.scores["uds"] = fail_score
                self.completed["uds"] = True

            print(f"[INFO] UDS Monitor completed - Score: {fail_score}")

        except Exception as e:
            print(f"[ERROR] UDS Monitor crashed: {e}")
            with self.scores_lock:
                self.completed["uds"] = True


    def _run_dbc_monitor(self, timeout: Optional[float]):
        try:
            fail_score = self.dbc_monitor.start(timeout=timeout)

            with self.scores_lock:
                self.scores["dbc"] = fail_score
                self.completed["dbc"] = True

            print(f"[INFO] DBC Monitor completed - Score: {fail_score}")

        except Exception as e:
            print(f"[ERROR] DBC Monitor crashed: {e}")
            with self.scores_lock:
                self.completed["dbc"] = True


    def wait_for_completion(self, timeout: Optional[float] = None):
        for name, thread in self.threads.items():
            thread.join(timeout=timeout)
            if thread.is_alive():
                print(f"[WARN] {name} thread is still running")

        self.running = False
        print("[INFO] All monitors completed")


    def is_all_completed(self) -> bool:
        with self.scores_lock:
            return all(self.completed.values())

    def get_completion_status(self) -> Dict[str, bool]:
        with self.scores_lock:
            return self.completed.copy()

    def get_scores(self) -> Dict[str, float]:
        with self.scores_lock:
            return self.scores.copy()

    def is_running(self) -> bool:
        return self.running