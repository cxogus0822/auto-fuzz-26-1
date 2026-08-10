# P-CAN Injection Dry Run

Status: **NOT TRANSMITTED**

## Selected Powertrain candidate

- CAN ID: `0x670` (11-bit standard frame)
- DBC message: `Motor_18`
- DLC: 8
- DBC transmitter: `Gateway`, `Gateway_PAG`
- DBC receivers: `ZR_High`, `ZR_LIMU`, `ZR_MIB_TOP_ab_Gen3`, `ZR_Standard`
- DBC cycle: 500 ms
- Observed count: 130 frames in 64.987895 seconds
- Observed payload variants: 1
- Captured payload: `001010000001007C`
- Dry-run frame: `670#001010000001007C`
- DBC round-trip: exact match

## Selection grounds

- `Motor_18` is explicitly Powertrain/engine-related, unlike the previous `Einheiten_01` candidate.
- All 130 captured instances used the identical payload.
- No CRC, rolling counter, or multiplexed payload rotation is defined.
- Signals are predominantly status/display information rather than torque, RPM, gear, throttle, or brake actuation commands.
- DBC receivers are infotainment/display nodes, not engine, transmission, or brake control modules.
- A single unchanged replay is lower risk than changing any signal, but it is not risk-free on a live vehicle.

## Decoded payload highlights

| Signal | Value | Meaning |
| --- | ---: | --- |
| `MO_Bremslicht_Reku` | 0 | Regenerative brake light off |
| `MO_StartStopp_PopUp` | 0 | Initial/no-button status change |
| `MO1_Sperr_Info_WFS` | 0 | Not immobilizer-locked |
| `MO1_Freigabe_Info_WFS` | 1 | Immobilizer release information valid |
| `MO_EPCL` | 0 | No EPCL warning text |
| `MO_Fahrzeugtyp` | 1 | Hybrid |
| `MO_Abstellzeit_Status` | 1 | Shutdown time calculated |
| `MO_Fehler_Zylabsch` | 0 | No cylinder-deactivation fault |
| `MO_Anzahl_Abgesch_Zyl` | 0 | Full-engine operation |
| `MO_Drehzahl_Warnung` | 0 | No RPM warning |
| `MO_obere_Drehzahlgrenze` | 6200 | Upper RPM limit 6200 |

## Rejected Powertrain candidates

- `0x641 Motor_Code_01`: CRC and rolling counter; 16 payload variants.
- `0x3C7 Motor_26`: multiplexes fan 1/fan 2 and alternates payload every frame.
- `0x647 Motor_09`: multiplexed engine-code field rotates through four payloads.
- `0x640 Motor_07`: contains valve, transmission-cooling and heating-pump requests.
- `0xA7`, `0xA8`, `0x154`: live torque/RPM values.
- `0xB1`: transmission state.
- ESP messages: braking, wheel-speed or stability semantics.

## Verification scope

An unchanged one-shot frame can test whether `can0` transmits electrically when combined with TX/error counters and preferably a second independent CAN receiver. It cannot prove that a specific ECU applied the signals. Seeing the frame in the transmitting host's `candump` may only be local echo.

No `cansend`, replay, cyclic transmission, or fuzzing was executed while producing this artifact.
