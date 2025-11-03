# src/monitor/uds_monitor.py
import time
import os
import can
import isotp
import yaml
from logger.base_logger import log_event


# 모니터링 설정값

CAN_CHANNEL = "can0"
TARGET_UDS_ID = 0x366
UDS_RESPONSE_OFFSET = 0x6A
PADDING_BYTE = 0xAA

# ISO-TP 기본 설정
isotp_params = {
    "stmin": 0,
    "blocksize": 8,
    "wftmax": 0,
    "tx_data_length": 8,
    "tx_padding": PADDING_BYTE,
    "rx_flowcontrol_timeout": 1000,
    "rx_consecutive_frame_timeout": 1000,
}



# NRC config 로드

def load_nrc_config(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"NRC config not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "nrc_scores" not in data:
        raise ValueError("Invalid NRC config: missing 'nrc_scores'")

    scores = {}
    for k, v in data["nrc_scores"].items():
        try:
            key = int(k, 16) if isinstance(k, str) and k.startswith("0x") else int(k)
            scores[key] = float(v)
        except Exception as e:
            raise ValueError(f"Invalid NRC key/value {k}:{v} ({e})")
    return scores



# UDS 모니터 클래스

class UDSMonitor:
    def __init__(self, nrc_cfg_path: str = "config/nrc_weights.yaml"):
        # NRC 점수 테이블 로드
        self.NRC_CLASS = load_nrc_config(nrc_cfg_path)

        # CAN & ISO-TP 초기화
        self.bus = can.interface.Bus(channel=CAN_CHANNEL, bustype="socketcan")
        addr = isotp.Address(
            isotp.AddressingMode.Normal_11bits,
            txid=TARGET_UDS_ID,
            rxid=TARGET_UDS_ID + UDS_RESPONSE_OFFSET
        )
        self.stack = isotp.CanStack(bus=self.bus, address=addr, params=isotp_params)


    # ISO-TP 송신

    def send_request(self, data):
        
        self.stack.send(bytes(data))
        while self.stack.transmitting():
            self.stack.process()
            time.sleep(0.01)

    # ISO-TP 수신

    def recv_response(self, timeout=1.0):
     
        start = time.time()
        while time.time() - start < timeout:
            self.stack.process()
            if self.stack.available():
                return list(self.stack.recv())
            time.sleep(0.01)
        return None



    def start(self):
        try:
            # 0x10 세션 진입
            if not self._send_once_or_retry([0x10, 0x02], "session_entry"):
                return

            # 0x3E Tester Present
            if not self._send_once_or_retry([0x3E, 0x00], "tester_present"):
                return

            # 0x19 DTC 읽기
            self.send_request([0x19, 0x02])
            total_dtc = self.collect_all_dtc()
            value = total_dtc / 20.0
            log_event("uds", TARGET_UDS_ID, "DTC_total_score", value, "OK")

        except Exception as e:
            log_event("uds", TARGET_UDS_ID, "exception", str(e), "FAIL")

    # 1회 전송 + 1회 재시도

    def _send_once_or_retry(self, data, step_name):
        """요청 보내고 응답 확인, 없으면 한 번만 재시도"""
        # 1차 요청
        self.send_request(data)
        resp = self.recv_response(timeout=1.0)

        if not resp:
            # 응답이 없으면 한 번만 재시도
            self.send_request(data)
            resp = self.recv_response(timeout=1.0)

            if not resp:
                log_event("uds", TARGET_UDS_ID, f"{step_name}_no_response", "high", "FAIL")
                return False

        # NRC 응답
        if resp[0] == 0x7F:
            nrc = resp[2]
            if nrc in self.NRC_CLASS:
                score = self.NRC_CLASS[nrc]
                log_event("uds", TARGET_UDS_ID, f"NRC_{hex(nrc)}", score, "FAIL")
                return False
            else:
                return True

        # 정상 응답
        log_event("uds", TARGET_UDS_ID, step_name, "response_ok", "OK")
        return True

 

    #0x59 0x02 DTC 개수 계산
    def collect_all_dtc(self):
        
        accumulated_data = bytearray()
        start_time = time.time()

        while time.time() - start_time < 2.0:
            resp = self.recv_response(timeout=0.5)
            if not resp:
                break

            # 정상 DTC 응답
            if len(resp) >= 4 and resp[0] == 0x59 and resp[1] == 0x02:
                # status mask(resp[2]) 건너뛰고 resp[3:]부터 누적
                accumulated_data.extend(resp[3:])

            # NRC 응답
            elif resp[0] == 0x7F:
                nrc = resp[2]
                if nrc in self.NRC_CLASS:
                    score = self.NRC_CLASS[nrc]
                    log_event("uds", TARGET_UDS_ID, f"NRC_{hex(nrc)}", score, "FAIL")
                else:
                    log_event("uds", TARGET_UDS_ID, "DTC_NRC_Unknown", nrc, "WARN")
                continue

        total_dtc = len(accumulated_data) // 4  # 3바이트 코드 + 1바이트 상태
        return total_dtc
