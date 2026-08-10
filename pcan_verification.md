# Powertrain CAN Physical Domain Verification

Capture interface: `can0`

Capture duration: 64.987895 seconds

Total frames: 46,314

Unique CAN IDs: 121

DBC: `A5.dbc` (561 messages, 4,511 signals, 13 nodes)

DBC match: 84/121 IDs and 31,792/46,314 frames

Physical connection reported by operator: J533 black 54-pin connector `T54`, pins 50 and 51.

Wiring-diagram evidence: `J533 pinout.pdf`, page 7 (No. 11/7), identifies `T54/51` as Powertrain CAN High and `T54/50` as Powertrain CAN Low. The diagram labels the corresponding harness connections `B383` (Powertrain CAN Bus High) and `B390` (Powertrain CAN Bus Low).

## Capture conditions

- `can0`: `UP`, `LOWER_UP`, `ERROR-ACTIVE`
- Classical CAN (`mtu 16`), 500,000 bit/s
- CAN error counters: 0
- TX frames: 0
- Passive `candump` only; no transmission or fuzzing

## Strong P-CAN Evidence

No ID is placed in the strict Strong group. Although strongly powertrain-specific messages were observed, `A5.dbc` identifies their transmitters as `Gateway`/`Gateway_PAG`, not a distinct ECM/TCU. Under the requested definition, gateway-originated/routed frames cannot alone prove the physical P-CAN segment.

| CAN ID | Message | Transmitter | Important Signals | Actual cycle | Evidence |
| --- | --- | --- | --- | ---: | --- |
| — | — | — | — | — | No non-gateway Powertrain ECU transmitter established |

## Possible P-CAN

| CAN ID | Message | Important evidence | Actual / DBC cycle |
| --- | --- | --- | ---: |
| `0xA8` | `Motor_12` | Engine RPM (`MO_Drehzahl_01`), torque limits/integral | 10.001 / 10 ms |
| `0xA7` | `Motor_11` | Requested and actual engine torque, normal-operation status | 100.007 / 200 ms |
| `0x154` | `Motor_28` | Combustion-engine torque, drivetrain fault, engine speed | 200.013 / 500 ms |
| `0x3BE` | `Motor_14` | Start/stop, gear position, driver braking, hybrid ready state | 100.006 / 100 ms |
| `0x3C7` | `Motor_26` | Engine cooling, oil level/warnings | 80.004 / 80 ms |
| `0x640` | `Motor_07` | Intake, oil and coolant temperatures | 320.017 / 320 ms |
| `0x647` | `Motor_09` | Coolant/SCR/engine-related status | 320.016 / 320 ms |
| `0x670` | `Motor_18` | Boost, regenerative brake light, start/stop | 500.027 / 500 ms |
| `0x641` | `Motor_Code_01` | Engine, transmission and start/stop coding | 960.051 / 960 ms |
| `0xB1` | `Getriebe_17` | Transmission program/status/input speed | 500.035 / 500 ms |
| `0xFD` | `ESP_21` | Brake intervention torque, vehicle-speed signal, ESP status | 20.001 / 100 ms |
| `0x116` | `ESP_10` | Four-wheel pulse signals | 100.007 / 50 ms |
| `0x1A2` | `ESP_15` | ESP/hold coordination states | 200.014 / 1000 ms |
| `0x392` | `ESP_07` | AWD and wheel-sensor status | 80.004 / 1000 ms |
| `0x65D` | `ESP_20` | Brake-system and ESP status | 1000.069 / 160 ms |
| `0x391` | `OBD_01` | Engine load/coolant/throttle/accelerator-pedal signals | 80.004 / 500 ms |
| `0x503` | `HVK_01` | HV/engine/BMS/DC-DC requested modes | 100.006 / 100 ms |

All listed messages use `Gateway`/`Gateway_PAG` as their DBC transmitter, so they remain Possible rather than Strong evidence. Exact or near-exact cycle agreement for several messages (`Motor_12`, `Motor_14`, `Motor_26`, `Motor_07`, `Motor_09`, `Motor_Code_01`, `Getriebe_17`, `Motor_18`, `HVK_01`) supports that the DBC mappings are meaningful. Other cycle mismatches limit confidence and may reflect event-driven transmission, gateway routing, or DBC limitations.

## Cross-Domain / Gateway Candidates

48 IDs are classified here. Representative examples:

| CAN ID | DBC classification | Evidence | Possible explanation |
| --- | --- | --- | --- |
| `0x3CE` | `TSG_HFS_01` | Door open/lock signals | Gateway routing or body-domain sharing |
| `0x3CF` | `TSG_HBFS_01` | Door open/lock signals | Gateway routing or body-domain sharing |
| `0x3D0` | `TSG_FT_01` | Driver-door lock/switch signals | Gateway routing or body-domain sharing |
| `0x3D1` | `TSG_BT_01` | Passenger-door lock/switch signals | Gateway routing or body-domain sharing |
| `0x3B5` | `Klima_11` | HVAC/compressor signals | Gateway routing or body-domain sharing |
| `0x668` | `Klima_12` | Climate and seat-heating requests | Gateway routing or body-domain sharing |
| `0x5F0` | `Dimmung_01` | Display/illumination dimming | Gateway routing or body-domain sharing |
| `0x484`–`0x486` | Navigation data/position | Navigation position and satellite data | Infotainment-domain traffic or routing |
| `0x17332810`/`11` | BAP telephone | Telephone BAP traffic | Infotainment traffic |
| `0x17333110`/`11` | BAP audio | Audio BAP traffic | Infotainment traffic |
| `0x17333210`/`11` | BAP navigation | Navigation BAP traffic | Infotainment traffic |

Complete ID list: `0x184`, `0x1F1`, `0x2A0`, `0x2C7`, `0x3B5`, `0x3CE`, `0x3CF`, `0x3D0`, `0x3D1`, `0x3F8`, `0x484`, `0x485`, `0x486`, `0x497`, `0x49A`, `0x54B`, `0x583`, `0x588`, `0x590`, `0x5A1`, `0x5BB`, `0x5E0`, `0x5E1`, `0x5F0`, `0x648`, `0x64F`, `0x650`, `0x65A`, `0x668`, `0x66E`, `0x67F`, `0x6A6`, `0x6B0`, `0x16A95418`, `0x17330110`, `0x17330810`, `0x17330D10`, `0x17330F10`, `0x17331110`, `0x17331310`, `0x17332810`, `0x17332811`, `0x17333110`, `0x17333111`, `0x17333210`, `0x17333211`, `0x1A5554A8`, `0x1A555525`.

## Ambiguous

56 IDs remain ambiguous because they are unmatched, generic, gateway/network-management related, safety/body messages without a direct physical-domain implication, or contain mixed-domain signals.

Complete ID list: `0x40`, `0xA0`, `0x153`, `0x179`, `0x18A`, `0x1F3`, `0x1F8`, `0x20F`, `0x30B`, `0x32C`, `0x365`, `0x36A`, `0x385`, `0x386`, `0x3A3`, `0x3C0`, `0x3FE`, `0x466`, `0x504`, `0x50F`, `0x520`, `0x552`, `0x556`, `0x585`, `0x58F`, `0x5A0`, `0x5AC`, `0x5E9`, `0x5F5`, `0x5F7`, `0x643`, `0x663`, `0x66F`, `0x671`, `0x6B2`, `0x6B4`, `0x6B5`, `0x6B6`, `0x6B7`, `0x6B8`, `0x12DD54A8`, `0x16A9540A`, `0x16A95414`, `0x16A95415`, `0x16A9545D`, `0x17F00010`, `0x17F00046`, `0x17F000AE`, `0x1A555480`, `0x1A55548D`, `0x1A555492`, `0x1A555548`, `0x1A5555AD`, `0x1B000010`, `0x1B000046`, `0x1B0000AE`.

Per-ID DLC, counts, rates, periods, representative payloads, payload changes, DBC message, transmitter, receivers, complete signal list, DBC cycle, classification and evidence are recorded in `pcan_analysis.csv`.

## Statistics

Frame-based:

- Strong/Probable Powertrain: **35.052%** (16,234/46,314; all currently Possible)
- Cross-domain: **20.402%** (9,449/46,314)
- Ambiguous: **44.546%** (20,631/46,314)

Unique-ID-based:

- Strong/Probable Powertrain: **14.050%** (17/121; all currently Possible)
- Cross-domain: **39.669%** (48/121)
- Ambiguous: **46.281%** (56/121)

## Final Verdict

**HIGHLY LIKELY POWERTRAIN CAN**

Confidence: **90%**

## Strongest decision grounds

1. The operator confirmed connection to J533 `T54/50` and `T54/51`; the Audi wiring diagram explicitly identifies these as Powertrain CAN Low and High respectively.
2. `Motor_12 (0xA8)` is continuously observed at approximately 10 ms and contains engine RPM and torque-related signals; its measured cycle matches the DBC.
3. Multiple independent engine messages (`Motor_11/14/26/28/07/09/18`) and `Getriebe_17` are present, with several measured cycles matching the DBC.
4. OBD throttle, accelerator-pedal, engine load/coolant, ESP speed/braking and gear-position semantics are present in the actual captured IDs.
5. Cross-domain traffic is still expected to some degree because J533 performs gateway routing; its presence does not override the explicit physical pin designation.

The independent physical pinout and captured Powertrain semantics agree, justifying `HIGHLY LIKELY`. The report remains short of `CONFIRMED` because the connector/pin placement is operator-reported rather than independently instrumented, the DBC assigns relevant messages to `Gateway`/`Gateway_PAG`, and cross-domain routing is visible. Photographic pin verification or continuity testing against the documented `T54/50` and `T54/51` terminals would support a final `CONFIRMED` verdict.
