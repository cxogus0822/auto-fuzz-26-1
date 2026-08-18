# P-CAN Motor_18 → I-CAN Routing Fuzz Test

이 디렉터리는 P-CAN에서 `Motor_18 (0x670)`의 표시용 Signal을 제한적으로 mutation하고, 별도 I-CAN 인터페이스에서 해당 프레임이 J533을 통해 전달되는지 passive monitoring하기 위한 도구다.

## 안전 설계

- P-CAN fuzzer는 기본적으로 dry-run이며 `--live`를 명시해야만 송신한다.
- DLC는 항상 8 bytes로 고정한다.
- 임의 byte fuzzing을 하지 않고 허용된 세 Signal만 한 번에 하나씩 변경한다.
- Torque, live RPM, gear, throttle, brake, ESP 및 immobilizer Signal은 변경하지 않는다.
- I-CAN monitor는 수신만 수행하고 송신 코드를 포함하지 않는다.
- 실차에서는 정차, P/N, 주차브레이크, 바퀴 고정, 주변 통제 및 즉시 전원 차단 수단을 확보해야 한다.

리프트에 올려둔 것만으로 모든 위험이 제거되지는 않는다. 최초 시험은 엔진 OFF, ignition ON에서 수행하고, 이상 경고·CAN 오류·bus-off가 발생하면 즉시 중단한다.

## 대상 메시지

| 항목 | 값 |
| --- | --- |
| CAN ID | `0x670` |
| DBC Message | `Motor_18` |
| 기준 payload | `001010000001007C` |
| DBC cycle | 500 ms |
| 캡처 결과 | 130개 모두 동일 payload |
| CRC/rolling counter | 없음 |
| DBC transmitter | `Gateway`, `Gateway_PAG` |
| DBC receivers | `ZR_High`, `ZR_LIMU`, `ZR_MIB_TOP_ab_Gen3`, `ZR_Standard` |

`A5.dbc`와 별도 I-CAN DBC 양쪽에서 동일한 ID와 수신자 정의를 확인했다. 따라서 P-CAN에서 생성한 변형이 I-CAN에 나타나는지 확인하는 gateway-routing 시험 후보로 선정했다.

## Mutation Signal

### `MO_StartStopp_PopUp`

- Start bit: 9
- Length: 2 bits
- 생성 값: 1, 2
- 목적: Start/Stop 안내 표시 상태 변화 관찰

예약값 3은 생성하지 않는다.

### `MO_Drehzahl_Warnung`

- Start bit: 55
- Length: 1 bit
- 생성 값: 1
- 목적: RPM warning 표시 요청의 I-CAN 전달 여부 관찰

### `MO_obere_Drehzahlgrenze`

- Start bit: 56
- Length: 8 bits
- Scale: 50 RPM/bit
- 생성 값: 3000, 4000, 5000, 6000 RPM
- 목적: 표시용 상한 RPM 값이 I-CAN으로 전달되는지 관찰

각 프레임은 위 Signal 하나만 변경하고 나머지 bit는 기준 payload와 동일하게 유지한다. 기본 한 라운드는 총 7개 mutation이다.

## 제외한 Signal과 메시지

- `MO_Bremslicht_Reku`: 브레이크등 의미
- `MO1_Sperr_Info_WFS`, `MO1_Freigabe_Info_WFS`: immobilizer 의미
- `MO_EPCL`: powertrain warning 의미
- `Motor_11`, `Motor_12`, `Motor_28`: Torque/RPM 상태
- `Getriebe_17`: 변속기 상태
- ESP 계열: 제동·wheel-speed·stability 의미
- `Motor_Code_01`: CRC와 rolling counter 존재

## 디렉터리 구조

```text
powertrain_ican_fuzz/
├── README.md
├── pcan_fuzzer/
│   ├── fuzzer.py
│   └── run_fuzzer.sh
├── ican_monitor/
│   ├── monitor.py
│   └── run_monitor.sh
└── tests/
    └── test_tools.py
```

## 1. 송신 없는 dry-run

프로젝트 루트에서 실행한다.

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh
```

기본 한 라운드의 7개 mutation을 생성하고 `tx_logs/motor18_tx_*.jsonl`에 저장하지만 CAN 프레임은 보내지 않는다.

특정 Signal만 생성할 수도 있다.

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --signals rpm_warning rpm_limit \
  --rounds 1 \
  --interval-ms 500
```

## 2. I-CAN passive monitor 실행

I-CAN에 연결된 PC에서 먼저 실행한다.

```bash
./powertrain_ican_fuzz/ican_monitor/run_monitor.sh \
  --channel can0 \
  --duration 120
```

결과는 `rx_logs/motor18_ican_*.jsonl`에 저장된다. `0x670`만 수신하며 다음으로 분류한다.

- `baseline`: 정상 기준 payload
- `expected_mutation`: 지정한 TX manifest에 포함된 mutation
- `other_variant`: 그 외 payload

TX manifest와 직접 대조하려면 다음과 같이 실행한다.

```bash
./powertrain_ican_fuzz/ican_monitor/run_monitor.sh \
  --channel can0 \
  --duration 120 \
  --expected-manifest tx_logs/motor18_tx_YYYYMMDD_HHMMSS.jsonl
```

두 PC를 사용하는 경우 TX manifest를 I-CAN PC로 복사하거나 공유 경로를 사용한다.

## 3. 실제 one-shot/제한 송신

I-CAN monitor를 먼저 시작하고 10~30초 baseline을 확보한 다음 P-CAN PC에서 실행한다.

최초 live 시험은 가장 작은 범위로 `rpm_warning` 한 건만 생성한다.

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --channel can0 \
  --signals rpm_warning \
  --rounds 1 \
  --interval-ms 500 \
  --live
```

모든 표시용 후보를 한 라운드 실행하려면:

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --channel can0 \
  --rounds 1 \
  --interval-ms 500 \
  --live
```

`--rounds`를 늘리면 동일 mutation 세트가 반복되므로 최초 검증 전에는 1을 유지한다.

## 결과 해석

1. P-CAN TX manifest에서 `status=sent`인지 확인한다.
2. 송신 전후 `can0` TX/error counter를 비교한다.
3. I-CAN JSONL에서 `classification=expected_mutation`을 찾는다.
4. ID, payload, TX/RX epoch timestamp를 비교한다.
5. I-CAN에 mutation이 없으면 J533 routing/filtering, native message overwrite, 연결 domain 또는 capture timing을 조사한다.

송신 PC의 `candump`에서 보이는 프레임은 local echo일 수 있다. ECU 또는 gateway 수신의 근거로는 별도 I-CAN 인터페이스의 관찰 결과를 사용한다.

## 테스트

```bash
python3 -m unittest powertrain_ican_fuzz.tests.test_tools
```

테스트는 bit mutation, DLC 유지, dry-run 무송신, manifest matching을 검증하며 실제 CAN 인터페이스를 사용하지 않는다.
