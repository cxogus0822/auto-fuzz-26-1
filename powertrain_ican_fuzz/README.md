# P-CAN Motor_18 → I-CAN Routing Fuzz Test

이 디렉터리는 P-CAN에서 `Motor_18 (0x670)`, `Motor_07 (0x640)`, `Motor_26 (0x3C7)`의 allowlist Signal을 mutation하고, 별도 I-CAN 인터페이스에서 해당 프레임이 J533을 통해 전달되는지 passive monitoring하기 위한 도구다.

## 안전 설계

- P-CAN fuzzer는 기본적으로 dry-run이며 `--live`를 명시해야만 송신한다.
- DLC는 항상 8 bytes로 고정한다.
- 임의 byte fuzzing을 하지 않고 allowlist에 포함된 표시용 Signal만 한 번에 하나씩 변경한다.
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

## Mutation 프로필

- `safe`: 기존 3종 Signal, 1라운드 28개 mutation
- `extended`: 표시용 8종 Signal, 1라운드 59개 mutation

`--rounds 10`을 사용하면 extended 프로필 기준 590프레임을 생성한다. 기본은 여전히 1라운드이며 실제 송신에는 `--live`가 필요하다.

`safe`와 `extended` 프로필은 `motor18`에 적용된다. `motor07`과 `motor26`은 `--message`만 지정하면 해당 메시지의 allowlist Signal 전체를 사용한다.

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
- 생성 값: 1000~7000 RPM, 250 RPM 간격
- 목적: 표시용 상한 RPM 값이 I-CAN으로 전달되는지 관찰

### Extended 전용 Signal

| CLI 이름 | DBC Signal | 생성 값 수 |
| --- | --- | ---: |
| `cylinder_text_detail` | `MO_Zylabsch_Texte_02` | 13 |
| `hybrid_startstop_led` | `MO_Hybrid_StartStopp_LED` | 2 |
| `deactivated_cylinder_count` | `MO_Anzahl_Abgesch_Zyl` | 7 |
| `cylinder_text` | `MO_Zylabsch_Texte` | 3 |
| `ethanol_text` | `MO_Ethanol_BS_Texte` | 6 |

각 프레임은 Signal 하나만 변경하고 나머지 bit는 기준 payload와 동일하게 유지한다. 예약값과 브레이크·이모빌라이저·토크·ESP 관련 Signal은 생성하지 않는다.

## 제외한 Signal과 메시지

- `MO_Bremslicht_Reku`: 브레이크등 의미
- `MO1_Sperr_Info_WFS`, `MO1_Freigabe_Info_WFS`: immobilizer 의미
- `MO_EPCL`: powertrain warning 의미
- `Motor_11`, `Motor_12`, `Motor_28`: Torque/RPM 상태
- `Getriebe_17`: 변속기 상태
- ESP 계열: 제동·wheel-speed·stability 의미
- `Motor_Code_01`: CRC와 rolling counter 존재

## 추가 Powertrain 메시지 후보

### `Motor_07 (0x640)`

- 정상 baseline 2종을 보존한다.
- 8종 Signal, 1라운드 54 payload를 생성한다.
- 온도·고도 정보만 변경하고 valve, transmission cooling, heating pump 요청은 제외한다.

| CLI Signal | DBC Signal |
| --- | --- |
| `intake_temp_qbit` | `MO_QBit_Ansaugluft_Temp` |
| `oil_temp_qbit` | `MO_QBit_Oel_Temp` |
| `coolant_temp_qbit` | `MO_QBit_Kuehlmittel_Temp` |
| `intake_temp` | `MO_Ansaugluft_Temp` |
| `oil_temp` | `MO_Oel_Temp` |
| `coolant_temp` | `MO_Kuehlmittel_Temp` |
| `altitude_raw` | `MO_Hoeheninfo` raw value |
| `altitude_qbit` | `MO_QBit_Hoeheninfo` |

### `Motor_26 (0x3C7)`

- fan 1/fan 2 MUX가 교대하는 정상 baseline 2종을 모두 보존한다.
- 12종 Signal, 1라운드 58 payload를 생성한다.
- 경고·텍스트·표시등 Signal만 변경한다.

| CLI Signal | DBC Signal |
| --- | --- |
| `eflex_lamp` | `MO_EFLEX_Lampe` |
| `oil_min_warning` | `WIV_Oelmin_Warn` |
| `oil_system_fault` | `OLEV_Systemstoerung` |
| `oil_max_warning` | `MO_Oelwarnung_max` |
| `motor_start_text` | `MO_Text_Motorstart` |
| `electric_warning` | `MO_E_Warnungen` |
| `system_lamp` | `MO_Systemlampe` |
| `obd2_lamp` | `MO_OBD2_Lampe` |
| `hot_lamp` | `MO_Heissleuchte` |
| `particle_lamp` | `MO_Partikel_Lampe` |
| `oil_overfill_warning` | `WIV_Ueberfuell_Warn` |
| `oil_underfill_warning` | `WIV_Unterfuell_Warn` |

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

기본 safe 프로필 한 라운드의 28개 mutation을 생성하고 `tx_logs/motor18_tx_*.jsonl`에 저장하지만 CAN 프레임은 보내지 않는다.

확장 프로필 59개를 확인하려면:

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --profile extended \
  --rounds 1 \
  --interval-ms 0
```

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

다른 후보 ID를 모니터링하려면:

```bash
./powertrain_ican_fuzz/ican_monitor/run_monitor.sh \
  --channel can0 --message motor07 --duration 120
```

```bash
./powertrain_ican_fuzz/ican_monitor/run_monitor.sh \
  --channel can0 --message motor26 --duration 120
```

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

확장 프로필을 10라운드(총 590프레임) 실행하려면:

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --channel can0 \
  --profile extended \
  --rounds 10 \
  --interval-ms 500 \
  --live
```

`--rounds`를 늘리면 동일 mutation 세트가 반복되므로 최초 검증 전에는 1을 유지한다.

기본적으로 10프레임마다 진행률을 출력한다. 간격을 바꾸려면 `--progress-every 25`처럼 지정한다. `Ctrl+C`로 중단하면 traceback 대신 manifest의 마지막에 `status=interrupted`와 실제 송신 수를 기록한다.

## 모든 후보를 한 명령으로 실행

I-CAN PC에서 세 ID를 동시에 passive monitoring한다.

```bash
./powertrain_ican_fuzz/ican_monitor/run_all_monitor.sh \
  --channel can0 \
  --duration 120
```

P-CAN PC에서 `Motor_18 extended`, `Motor_07`, `Motor_26`을 순차 실행한다. 기본 10라운드는 총 1,710프레임이며 17ms 간격으로 약 30초가 걸린다.

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_all_fuzzer.sh \
  --channel can0 \
  --rounds 10 \
  --interval-ms 17 \
  --live
```

`--live`를 생략하면 세 메시지의 manifest만 생성하고 실제 CAN 송신은 하지 않는다.

### Motor_07 약 30초 fuzzing

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --channel can0 \
  --message motor07 \
  --rounds 10 \
  --interval-ms 55 \
  --live
```

### Motor_26 약 30초 fuzzing

```bash
./powertrain_ican_fuzz/pcan_fuzzer/run_fuzzer.sh \
  --channel can0 \
  --message motor26 \
  --rounds 10 \
  --interval-ms 50 \
  --live
```

## 결과 해석

1. P-CAN TX manifest에서 `status=sent`인지 확인한다.
2. 송신 전후 `can0` TX/error counter를 비교한다.
3. I-CAN JSONL에서 `classification=expected_mutation`을 찾는다.
4. ID, payload, TX/RX epoch timestamp를 비교한다.
5. I-CAN에 mutation이 없으면 J533 routing/filtering, native message overwrite, 연결 domain 또는 capture timing을 조사한다.

송신 PC의 `candump`에서 보이는 프레임은 local echo일 수 있다. ECU 또는 gateway 수신의 근거로는 별도 I-CAN 인터페이스의 관찰 결과를 사용한다.

## 후보 반응 재현 시험

전체 fuzzing 결과에서 다음 두 시점이 특히 가까웠으므로, 다른 mutation을 섞지 않고 각각 한 프레임씩 반복하는 전용 시험을 제공한다.

| P-CAN 후보 | 정확한 송신 프레임 | I-CAN 확인 대상 |
| --- | --- | --- |
| `rpm_limit_4000` | `0x670#0010100000010050` | `0x17FD0200` TesterPresent, `0x17FC0214/0x17FE0214`, Gateway Car_Wakeup |
| `oil_temp_40` | `0x640#809264B67E421104` | `0x17FC0373/0x17FE0373` FoD 요청·응답, FoD Transmission Info 변화 |

이 시험은 **직접 payload 전달**을 찾는 시험이 아니다. P-CAN의 특정 mutation 직후 J533 내부 반응으로 보이는 진단·wake-up 통신이 I-CAN에서 반복되는지 확인한다.

두 PC의 시계를 먼저 NTP로 동기화한다. I-CAN PC에서 아래 명령을 먼저 실행하면 처음 15초는 baseline, 이후 75초는 주입 관찰 구간으로 한 번에 기록된다.

```bash
./powertrain_ican_fuzz/correlation_test/run_ican_reaction_monitor.sh \
  --channel can0 \
  --duration 90 \
  --baseline-seconds 15
```

출력의 안내대로 15초가 지난 다음, P-CAN PC에서는 **후보 하나만** 3회 송신한다. 각 시험 사이에는 10초 간격이 들어가므로 반응 창이 겹치지 않는다.

RPM 후보:

```bash
./powertrain_ican_fuzz/correlation_test/run_pcan_candidate.sh \
  --channel can0 \
  --candidate rpm_limit_4000 \
  --trials 3 \
  --gap-seconds 10 \
  --live
```

Oil temperature 후보는 별도의 새 I-CAN capture를 시작한 뒤 실행한다.

```bash
./powertrain_ican_fuzz/correlation_test/run_pcan_candidate.sh \
  --channel can0 \
  --candidate oil_temp_40 \
  --trials 3 \
  --gap-seconds 10 \
  --live
```

P-CAN에서 생성된 `tx_logs/correlation_*.jsonl`을 I-CAN PC로 복사한 뒤 자동 상관분석을 실행한다.

```bash
./powertrain_ican_fuzz/correlation_test/analyze_result.sh \
  --tx-manifest tx_logs/correlation_rpm_limit_4000_YYYYMMDD_HHMMSS_ffffff.jsonl \
  --rx-log rx_logs/correlation_ican_YYYYMMDD_HHMMSS_ffffff.jsonl \
  --window-seconds 5
```

판정은 다음과 같다.

- `repeatable_correlation`: baseline에는 없고 모든 반복에서 예상 반응 발생
- `probable_correlation`: baseline에는 없고 두 번 이상 발생
- `weak_single_occurrence`: 한 번만 발생
- `not_reproduced`: 재현되지 않음
- `baseline_also_active`: 주입 전에도 같은 이벤트가 있어 fuzzing 고유 반응으로 판단할 수 없음

PC 간 시간 차이가 확인되면 `--clock-offset-ms`에 `I-CAN 시각 - P-CAN 시각`을 밀리초로 지정한다. 분석 결과와 각 trial의 반응 시차는 RX 로그 옆 `*.correlation.json`에 저장된다.

## 테스트

```bash
python3 -m unittest powertrain_ican_fuzz.tests.test_tools
```

테스트는 bit mutation, DLC 유지, dry-run 무송신, manifest matching, 후보 payload 및 상관분석 판정을 검증하며 실제 CAN 인터페이스를 사용하지 않는다.
