# Hazard TX-only Fuzzer

`tx_only` 패키지는 송신 PC에서 다음 작업만 수행한다.

- 기본 payload mutation
- B-CAN의 SocketCAN 인터페이스로 송신
- 수신 PC와 대조할 application-side TX manifest 저장

수신, Timing/DBC/UDS 모니터, 분석 및 재현 기능은 포함하지 않는다.

## 고정 대상

- CAN ID: `0x366`
- DBC Message: `Blinkmodi_02`
- Hazard 관련 Signal: `BM_Warnblinken`
- DLC: 8 bytes
- 기본 payload: `00000000200000F0`

통합 DBC에서 `0x366`의 송신자는 Gateway로 정의되어 있다. 따라서 B-CAN에서
이 ID를 송신해도 J533이 I-CAN으로 그대로 전달한다는 보장은 없으며, 수신
PC에서 실제 결과를 확인해야 한다.

## 준비

```bash
source .venv/bin/activate
ip -details -statistics link show can0
```

프로그램은 `can0`의 bitrate나 상태를 변경하지 않는다.

## 송신 없는 확인

`--live`가 없으면 CAN 프레임을 전혀 송신하지 않고 mutation과 manifest만
생성한다.

```bash
python -m tx_only \
  --count 256 \
  --interval-ms 10 \
  --manifest tx_logs/hazard_dry.jsonl
```

## 실제 송신

I-CAN 수신 PC의 캡처를 먼저 시작한 다음 송신 PC에서 실행한다.

```bash
python -m tx_only \
  --channel can0 \
  --count 256 \
  --interval-ms 10 \
  --manifest tx_logs/hazard_live.jsonl \
  --live
```

기본값은 DLC를 8 bytes로 유지한다. 길이 mutation까지 허용하려면 명시적으로
`--allow-dlc-change`를 추가한다.

다른 기준 payload를 사용하려면 다음처럼 지정한다.

```bash
python -m tx_only \
  --base-payload 00001000200000F0 \
  --count 64 \
  --interval-ms 20 \
  --manifest tx_logs/hazard_custom.jsonl \
  --live
```

## 두 PC 실행 순서

1. 두 PC의 시간을 NTP/chrony로 동기화한다.
2. I-CAN PC에서 `monitor_only.py capture`를 먼저 시작한다.
3. 10~30초 baseline을 확보한다.
4. B-CAN PC에서 `python -m tx_only --live`를 실행한다.
5. 송신 종료 후에도 I-CAN을 30~60초 더 캡처한다.
6. TX manifest의 `epoch_ns`, ID, payload, 변경 바이트를 수신 결과와 대조한다.

TX manifest 시간은 애플리케이션의 `send()` 호출 시각이다. 정밀한 gateway
latency 측정용 실제 on-bus hardware timestamp는 아니다.

## Manifest

JSONL에는 다음 정보가 저장된다.

- 실행 시작/종료 UTC 및 epoch timestamp
- sequence 번호
- CAN ID, payload, DLC
- 원본 대비 바뀐 byte index, XOR 및 bit 개수
- `dry-run`, `sent`, `send_error` 상태

실제 송신 모드에서는 같은 이름의 `.interface.txt` 파일에 송신 전 인터페이스
상태도 저장한다.
