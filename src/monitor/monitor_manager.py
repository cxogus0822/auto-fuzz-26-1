# src/monitor/monitor_manager.py
# 각 모니터를 스레드로 실행하고, FAIL 발생 시 리턴값으로 종료 처리

import threading
import time
from typing import Optional, Dict, Any


class MonitorManager:
    """
    여러 모니터(DBC, Timing, UDS)를 개별 스레드로 실행하고,
    각 모니터로부터 실수 점수를 받아 딕셔너리로 반환합니다.
    """

    def __init__(self):
        self.monitors: Dict[str, Any] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.durations: Dict[str, Optional[float]] = {}  # 각 모니터의 실행 시간
        self.results: Dict[str, Optional[float]] = {}  # 각 모니터의 점수 저장
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def register(self, name: str, monitor_instance: Any, duration: Optional[float] = None):
        """
        모니터 인스턴스를 등록합니다.
        
        :param name: 모니터 식별 이름 (예: "dbc", "timing", "uds")
        :param monitor_instance: start() 메서드를 가진 모니터 객체
        :param duration: 해당 모니터의 실행 시간(초). None이면 무제한
        """
        if name in self.monitors:
            raise ValueError(f"Monitor '{name}' is already registered.")
        
        self.monitors[name] = monitor_instance
        self.durations[name] = duration
        self.results[name] = None
        
        duration_str = f"{duration}s" if duration else "unlimited"
        print(f"[MonitorManager] Registered monitor: {name} (duration: {duration_str})")

    def _monitor_wrapper(self, name: str, monitor_instance: Any, duration: Optional[float]):
        """
        각 모니터를 실행하는 래퍼 함수.
        모니터의 start() 메서드로부터 실수 점수를 받아 저장합니다.
        duration이 설정된 경우 해당 시간 후 강제 종료합니다.
        """
        monitor_thread = threading.current_thread()
        timer = None
        
        def timeout_handler():
            print(f"[MonitorManager] Monitor '{name}' reached timeout ({duration}s)")
            # 타임아웃 시 해당 모니터 스레드를 강제 종료하는 대신
            # 결과를 None으로 설정하고 stop_event 설정
            with self.lock:
                if self.results[name] is None:
                    self.results[name] = None
        
        try:
            # duration이 설정된 경우 타이머 시작
            if duration is not None:
                timer = threading.Timer(duration, timeout_handler)
                timer.daemon = True
                timer.start()
            
            print(f"[MonitorManager] Starting monitor: {name}")
            
            # 모니터 실행 - 실수 점수 리턴
            score = monitor_instance.start()
            
            # 정상 완료 시 타이머 취소
            if timer:
                timer.cancel()
            
            with self.lock:
                self.results[name] = float(score)
                print(f"[MonitorManager] Monitor '{name}' returned score: {score}")
                    
        except Exception as e:
            # 예외 발생 시 타이머 취소
            if timer:
                timer.cancel()
            
            with self.lock:
                self.results[name] = None
                print(f"[MonitorManager] Monitor '{name}' raised exception: {e}")
                self.stop_event.set()

    def start_all(self) -> Dict[str, Optional[float]]:
        """
        등록된 모든 모니터를 스레드로 시작합니다.
        각 모니터는 register 시 설정한 duration만큼 실행됩니다.
        
        :return: {monitor_name: score} 딕셔너리
        """
        if not self.monitors:
            print("[MonitorManager] No monitors registered.")
            return {}

        print(f"[MonitorManager] Starting {len(self.monitors)} monitor(s)...")
        
        # 각 모니터를 스레드로 시작
        for name, monitor in self.monitors.items():
            duration = self.durations[name]
            thread = threading.Thread(
                target=self._monitor_wrapper,
                args=(name, monitor, duration),
                daemon=True,
                name=f"Monitor-{name}"
            )
            self.threads[name] = thread
            thread.start()
        
        # 모든 스레드가 종료되거나 예외 발생까지 대기
        while True:
            # 예외 발생 확인
            if self.stop_event.is_set():
                print("[MonitorManager] Stop event detected. Terminating...")
                break
            
            # 모든 스레드 완료 확인
            all_done = all(not t.is_alive() for t in self.threads.values())
            if all_done:
                print("[MonitorManager] All monitors completed.")
                break
            
            time.sleep(0.1)

        # 스레드 종료 대기 (최대 5초)
        for name, thread in self.threads.items():
            if thread.is_alive():
                print(f"[MonitorManager] Waiting for monitor '{name}' to terminate...")
                thread.join(timeout=5.0)
                if thread.is_alive():
                    print(f"[MonitorManager] Warning: Monitor '{name}' did not terminate gracefully.")

        # 결과 딕셔너리 반환
        results = self.get_results()
        print(f"[MonitorManager] Monitoring completed. Results: {results}")
        
        return results

    def get_results(self) -> Dict[str, Optional[float]]:
        """
        각 모니터의 점수를 반환합니다.
        
        :return: {monitor_name: score} 딕셔너리
        """
        with self.lock:
            return self.results.copy()

    def stop_all(self):
        """
        모든 모니터를 강제 종료합니다.
        """
        print("[MonitorManager] Stopping all monitors...")
        self.stop_event.set()
        
        for name, thread in self.threads.items():
            if thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    print(f"[MonitorManager] Warning: Monitor '{name}' did not stop.")


# 사용 예시
if __name__ == "__main__":
    from dbc_monitor import DBCMonitor
    from timing_monitor import TimingMonitor
    from uds_monitor import UDSMonitor

    manager = MonitorManager()

    # 각 모니터 인스턴스 생성 및 등록
    # DBC와 Timing은 duration 설정, UDS는 duration 없음
    
    try:
        dbc_mon = DBCMonitor()
        manager.register("dbc", dbc_mon, duration=30.0)  # 30초 동안 실행
    except Exception as e:
        print(f"[WARN] DBCMonitor 초기화 실패: {e}")

    try:
        timing_mon = TimingMonitor()
        manager.register("timing", timing_mon, duration=30.0)  # 30초 동안 실행
    except Exception as e:
        print(f"[WARN] TimingMonitor 초기화 실패: {e}")

    try:
        uds_mon = UDSMonitor()
        manager.register("uds", uds_mon)  # duration 없음 (완료될 때까지 실행)
    except Exception as e:
        print(f"[WARN] UDSMonitor 초기화 실패: {e}")

    # 모든 모니터 시작
    scores = manager.start_all()

    # 결과 확인
    print("\n=== Monitoring Scores ===")
    for name, score in scores.items():
        print(f"  {name}: {score}")
    
    # 추후 증거결합 모듈에서 이 scores 딕셔너리를 사용