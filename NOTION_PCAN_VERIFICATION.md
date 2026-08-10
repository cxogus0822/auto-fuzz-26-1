# Audi A5 J533 Powertrain CAN 검증 기록

## 1. 목적

Audi A5 2020의 J533 Gateway에 연결한 Raspberry Pi `can0`가 실제 Powertrain CAN 물리 버스인지 검증하고, 향후 CAN fuzzing을 위한 송수신 준비 상태를 정리한다.

이번 검증 단계에서는 CAN 프레임을 송신하지 않고 passive monitoring만 수행했다. Injection 관련 내용은 후보 분석과 dry-run 프레임 생성까지만 진행했다.

## 2. 시험 환경

| 항목 | 내용 |
| --- | --- |
| 차량 | Audi A5 2020 |
| Gateway | J533 |
| CAN 인터페이스 | Raspberry Pi `can0` |
| CAN 형식 | Classical CAN (`mtu 16`) |
| Bitrate | 500 kbit/s |
| 캡처 상태 | `UP`, `LOWER_UP`, `ERROR-ACTIVE` |
| DBC | `A5.dbc`, P/B/I-CAN 통합 DBC |

## 3. 물리 핀 확인

`J533 pinout.pdf` 7페이지(No. 11/7)의 Audi 배선도에는 다음과 같이 명시되어 있다.

| J533 커넥터 핀 | 용도 |
| --- | --- |
| `T54/51` | Powertrain CAN High |
| `T54/50` | Powertrain CAN Low |
| `B383` | Powertrain CAN Bus High Connection 1 |
| `B390` | Powertrain CAN Bus Low Connection 1 |

실제 점프선 연결도 J533 검정색 54핀 커넥터의 50번과 51번으로 확인됐다.

## 4. Passive CAN 캡처

점프선 접촉을 다시 확인한 뒤 `candump` 출력을 줄 단위로 flush하도록 설정하여 실제 트래픽을 캡처했다.

| 항목 | 결과 |
| --- | ---: |
| 실제 first-to-last frame 시간 | 64.987895초 |
| 전체 프레임 | 46,314 |
| Unique CAN ID | 121 |
| CAN 오류 | 0 |
| 송신 프레임 | 0 |
| 원본 로그 | `pcan_capture.log` |

초기 캡처 파일이 비었던 원인은 점프선 재연결 이후에도 트래픽이 없어서가 아니라, 파일로 redirect된 `candump` 출력이 `timeout` 종료 전에 flush되지 않은 버퍼링 문제였다. Kernel RX counter 증가를 확인한 뒤 `stdbuf -oL`을 적용하여 정상 로그를 확보했다.

## 5. DBC 비교 결과

| 항목 | 결과 |
| --- | ---: |
| DBC 메시지 | 561 |
| DBC Signal | 4,511 |
| DBC Node | 13 |
| 캡처 ID 중 DBC 매칭 | 84/121 |
| DBC에 매칭된 프레임 | 31,792/46,314 |

주요 Powertrain 관련 메시지:

| CAN ID | Message | 주요 Signal/의미 | 실제 평균 주기 | DBC 주기 |
| --- | --- | --- | ---: | ---: |
| `0xA8` | `Motor_12` | Engine RPM, torque limits | 10.001 ms | 10 ms |
| `0xA7` | `Motor_11` | Requested/actual torque | 100.007 ms | 200 ms |
| `0x154` | `Motor_28` | Engine torque, drivetrain fault, RPM | 200.013 ms | 500 ms |
| `0x3BE` | `Motor_14` | Start/stop, gear position, braking state | 100.006 ms | 100 ms |
| `0x3C7` | `Motor_26` | Cooling and oil-related status | 80.004 ms | 80 ms |
| `0x640` | `Motor_07` | Intake/oil/coolant temperatures | 320.017 ms | 320 ms |
| `0x647` | `Motor_09` | Coolant/SCR/engine status | 320.016 ms | 320 ms |
| `0x670` | `Motor_18` | Engine/start-stop/display status | 500.027 ms | 500 ms |
| `0xB1` | `Getriebe_17` | Transmission program/status/input RPM | 500.035 ms | 500 ms |
| `0x391` | `OBD_01` | Load, coolant, throttle, pedal | 80.004 ms | 500 ms |
| `0xFD` | `ESP_21` | Brake intervention torque, speed, ESP | 20.001 ms | 100 ms |

## 6. 도메인 분류 통계

Frame 기반:

| 분류 | 비율 | 프레임 |
| --- | ---: | ---: |
| Strong/Probable Powertrain | 35.052% | 16,234 |
| Cross-domain | 20.402% | 9,449 |
| Ambiguous | 44.546% | 20,631 |

Unique-ID 기반:

| 분류 | 비율 | ID 수 |
| --- | ---: | ---: |
| Strong/Probable Powertrain | 14.050% | 17 |
| Cross-domain | 39.669% | 48 |
| Ambiguous | 46.281% | 56 |

Door, HVAC, navigation, telephone, audio 등 cross-domain 메시지도 관찰됐다. 이는 J533 Gateway routing으로 설명할 수 있으며, 해당 메시지의 존재만으로 물리 버스를 B-CAN 또는 I-CAN으로 판단하지 않았다.

## 7. 최종 판정

> **HIGHLY LIKELY POWERTRAIN CAN — Confidence 90%**

판단 근거:

1. 실제 연결한 `T54/50`과 `T54/51`이 Audi 배선도에서 Powertrain CAN Low/High로 명시된다.
2. `Motor_12 (0xA8)`의 RPM·토크 메시지가 약 10ms 주기로 지속 관찰됐고 DBC 주기와 일치한다.
3. 다수의 독립적인 Motor, Transmission, ESP, OBD 메시지가 실제 캡처에 존재한다.
4. 여러 메시지의 실제 주기가 DBC와 정확히 또는 거의 일치한다.
5. DBC 송신자가 대부분 `Gateway/Gateway_PAG`이고 cross-domain routing이 관찰되므로 과도한 `CONFIRMED` 판정은 피했다.

## 8. Injection 준비 분석

초기 저영향 후보였던 `0x643 Einheiten_01`은 계기판 단위 설정을 전달하는 cross-domain 메시지이므로 Powertrain 전용 injection 검증에는 적합하지 않다고 판단했다.

Powertrain 전용 dry-run 후보는 다음과 같이 다시 선정했다.

| 항목 | 값 |
| --- | --- |
| CAN ID | `0x670` |
| DBC Message | `Motor_18` |
| Dry-run frame | `670#001010000001007C` |
| DBC 주기 | 500ms |
| 캡처 횟수 | 130 |
| Payload variants | 1 |
| CRC/rolling counter | 없음 |
| DBC round-trip | 동일 payload로 재인코딩 성공 |

선정 이유:

- 명확한 `Motor_*` Powertrain 메시지다.
- 65초 동안 payload가 한 번도 변하지 않았다.
- Torque, live RPM, gear 또는 ESP 제어 명령이 아니다.
- DBC 수신자는 infotainment/display 계열로 정의되어 있다.
- 단일 정상 payload replay 후보로는 다른 Powertrain 메시지보다 상대적으로 영향이 낮다.

실제 송신은 아직 수행하지 않았다. 동일 payload를 one-shot으로 보내더라도 눈에 보이는 변화는 없을 가능성이 높으며, 송신 성공은 TX counter, ACK/error 상태 및 가능하면 두 번째 독립 CAN 인터페이스로 확인해야 한다. 송신 호스트의 `candump`에 나타난 프레임은 local echo일 수 있으므로 그것만으로 ECU 수신을 증명하면 안 된다.

## 9. 안전 제한

- 현재까지 CAN 송신 및 fuzzing 없음
- 실차 주행 중 injection 금지
- Torque, RPM, gear, brake, ESP 메시지는 초기 injection 대상에서 제외
- 실제 one-shot 시험은 차량 정차, P/N, 주차브레이크, 바퀴 고정, 주변 통제 및 즉시 전원 차단 수단을 확보한 뒤 별도로 승인해야 함
- 반복 송신이나 Signal 변조는 one-shot 정상 payload 검증 이후 별도 단계로 분리

## 10. 관련 산출물

- `pcan_verification.md`: 전체 물리 도메인 판정 보고서
- `pcan_analysis.csv`: 121개 CAN ID별 raw/DBC 통계 및 분류
- `pcan_dry_run.md`: `0x670 Motor_18` dry-run 분석
- `A5.dbc`: 분석에 사용한 통합 DBC
- `J533 pinout.pdf`: J533 Powertrain CAN 핀 근거
- `pcan_capture.log`: 원본 캡처. 저장소의 `*.log` ignore 정책으로 Git에는 포함되지 않음
