# src/monitor/timing_monitor.py

import can
import time
from ..logger.base_logger import log_event
from typing import Optional


# 모니터링 설정값 
CAN_CHANNEL = "can0"           # 사용할 CAN 인터페이스 
TARGET_ID = 0x6A6
EXPECTED_CYCLE_MS = 500        # 기대 주기 
TOLERANCE_MS = 50              # 허용 오차
LOG_INTERVAL = 10              # 평균 주기 출력 주기 (10프레임마다 평균 계산)
MAX_TIMEOUT = 5.0              # 최대 timeout (초)


class TimingMonitor:
    def __init__(self,
                 channel: str = CAN_CHANNEL,
                 target_id: int = TARGET_ID,
                 expected_cycle: int = EXPECTED_CYCLE_MS,
                 tolerance: int = TOLERANCE_MS):
        """
        :param channel: CAN 인터페이스 이름
        :param target_id: 모니터링 대상 CAN ID
        :param expected_cycle: 기대 주기(ms)
        :param tolerance: 허용 오차(ms)
        """
        self.channel = channel
        self.target_id = target_id
        self.expected = expected_cycle
        self.tolerance = tolerance

        # pycan 인터페이스 초기화
        self.bus = can.interface.Bus(channel=self.channel, bustype="socketcan")

        # 내부 상태 관리
        self.prev_time = None     # 이전 메시지 수신 시각
        self.events = []          # 발생한 이벤트 버퍼
        self._frame_counter = 0   # 평균 주기 계산용 카운터
        self._cycle_list = []     # 최근 N개의 주기 기록
        self._fail_score = 0.0    # FAIL 스코어 누적
        self._total_frames = 0    # FAIL 포함 총 프레임 수


    def start(self, timeout: Optional[float] = None) -> float:
        """
        모니터링 루프 시작.
        지정된 CAN ID의 메시지를 수신하며, 주기 위배 여부를 검사한다.
        
        :param timeout: 모니터링 시간 제한(초). None이면 무제한
        :return: 정규화된 FAIL 스코어 (0~1)
        """
        print(f"[ INFO ] Monitoring 0x{self.target_id:X} "
              f"(Cycle={self.expected}ms ±{self.tolerance}ms) on {self.channel}")
        
        if timeout:
            print(f"[ INFO ] Timeout set to {timeout} seconds")
        
        start_time = time.time()
        self._fail_score = 0.0  # 스코어 초기화
        self._total_frames = 0

        while True:
            # timeout 체크
            if timeout and (time.time() - start_time) >= timeout:
                print(f"[ INFO ] Timing Monitor timeout reached ({timeout}s)")
                break
            
            msg = self.bus.recv(timeout=1)
            if not msg:
                continue

            # 지정한 CAN ID만 필터링
            if msg.arbitration_id != self.target_id:
                continue

            now = time.time() * 1000  # 현재 시각(ms)
            if self.prev_time:
                cycle = now - self.prev_time
                status = "OK" if (self.expected - self.tolerance <= cycle <= self.expected + self.tolerance) else "FAIL"

                # FAIL인 경우 스코어 누적 (오차의 절댓값)
                if status == "FAIL":
                    if cycle < self.expected - self.tolerance:
                        # 너무 빠름
                        error = (self.expected - self.tolerance) - cycle
                    else:
                        # 너무 느림
                        error = cycle - (self.expected + self.tolerance)
                    self._fail_score += error

                self._total_frames += 1

                # 이벤트 생성 및 저장
                event = {
                    "type": "timing",
                    "id": self.target_id,
                    "metric": "cycle_time",
                    "value": round(cycle, 2),
                    "status": status
                }
                self.events.append(event)

                # 공통 로거에 기록
                log_event("timing", self.target_id, "cycle_time", cycle, status)

                # CLI 출력
                print(f"[{status}] Cycle: {cycle:.2f} ms")

                # 평균 주기 계산 (optional)
                self._frame_counter += 1
                self._cycle_list.append(cycle)
                if self._frame_counter % LOG_INTERVAL == 0:
                    avg_cycle = sum(self._cycle_list[-LOG_INTERVAL:]) / LOG_INTERVAL
                    print(f"    └ Average cycle (last {LOG_INTERVAL}): {avg_cycle:.2f} ms")

            self.prev_time = now
        
        # 정규화된 스코어 계산
        normalized_score = self._normalize_fail_score(timeout or MAX_TIMEOUT)
        print(f"[ INFO ] Timing Monitor finished")
        print(f"    └ Total FAIL score: {self._fail_score:.2f} ms")
        print(f"    └ Total frames: {self._total_frames}")
        print(f"    └ Normalized score (0~1): {normalized_score:.4f}")
        
        return normalized_score


    def _normalize_fail_score(self, timeout: float) -> float:
        """
        FAIL 스코어를 0~1 범위로 정규화
        
        :param timeout: 모니터링 시간 (초)
        :return: 0~1 사이의 정규화된 스코어
        """
        if self._total_frames == 0:
            return 0.0
        
        # 최대 프레임 수 계산
        max_possible_frames = (timeout * 500) / self.expected
        

        worst_case_score = max_possible_frames * self.tolerance
        
        # 정규화: 현재 스코어 / 최악의 경우 스코어
        normalized = min(self._fail_score / worst_case_score, 1.0)
        
        return normalized


    def get_fail_score(self) -> float:
        """
        현재까지 누적된 정규화된 FAIL 스코어 반환 (0~1)
        
        :return: 정규화된 FAIL 스코어
        """
        
        return self._normalize_fail_score(MAX_TIMEOUT)


    def get_raw_fail_score(self) -> float:
        """
        정규화되지 않은 원본 FAIL 스코어 반환 (ms 단위)
        
        :return: FAIL 스코어 (허용 범위를 벗어난 오차의 누적합)
        """
        return self._fail_score


    def fetch_events(self):
        """
        Manager 또는 Pipeline에서 호출하여, 새로 수집된 이벤트를 반환한다.
        반환 후 내부 버퍼(self.events)는 초기화된다.
        """
        events_copy = self.events[:]
        self.events.clear()
        return events_copy