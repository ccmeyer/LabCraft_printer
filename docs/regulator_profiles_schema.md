# Regulator Profiles Schema And Command Contract

## Purpose

This file completes Stage 1 of the regulator optimization plan. It defines the
v1 profile schema, calibration run metadata, initial safety bounds, and the
future MCU command contract for runtime regulator tuning.

Stage 1 is documentation-only. It does not change firmware, host code, UI, or
the wire protocol.

## Decisions Locked For V1

- Default tracked profile file: `FreeRTOS-interface/Presets/RegulatorProfiles.json`
- Generated run artifacts: `local/regulator_optimization/`
- Initial automatic selection scope: mode-level `droplet` and `stream`
- Head and reagent fields: recorded as metadata only, not used for automatic
  profile selection in v1
- Runtime candidate application: RAM-only
- Tunable fields: recovery, slew, and ready configs only
- PID gains: out of scope for v1
- Stage 2 command IDs: reserve `0x68` through `0x6C`
- Stage 2 command shape: one channel per command, existing `p1/p2/p3` 32-bit
  TLV fields only
- Calibration trace source: use the existing pressure trace export path first;
  add app-owned trace capture only if the existing path cannot support the
  calibration workflow safely

## Profile File: RegulatorProfiles.json

### Top-Level Shape

```json
{
  "schema_version": 1,
  "active_profiles": {
    "droplet": "droplet_default",
    "stream": "stream_default"
  },
  "profiles": {
    "droplet_default": {
      "profile_id": "droplet_default",
      "mode": "droplet",
      "description": "Default droplet-mode regulator profile",
      "source": {
        "kind": "factory_default",
        "run_id": null,
        "promoted_at_utc": null,
        "operator": null,
        "notes": ""
      },
      "conditions": {
        "printer_head_id": null,
        "printer_head_type": null,
        "reagent_id": null,
        "print_pressure_psi": null,
        "print_pulse_width_us": null,
        "refuel_pressure_psi": null,
        "refuel_pulse_width_us": null,
        "frequency_hz": 20
      },
      "print": {
        "recovery": {
          "active_ticks": 2,
          "base_boost_hz": 300,
          "pulse_coeff_hz_per_us": 1,
          "pressure_coeff_hz_per_raw": 0,
          "max_boost_hz": 1500,
          "recovery_floor_hz": 0,
          "recovery_exit_error_raw": 3,
          "max_extend_ticks": 0,
          "allow_extend_while_undershoot": false,
          "boost_only_when_undershoot": true,
          "linear_decay": true
        },
        "slew": {
          "max_hz_delta_up_per_loop": 600,
          "max_hz_delta_down_per_loop": 1200,
          "recovery_bypass_slew_ticks": 0
        },
        "ready": {
          "ready_tol_raw": 4,
          "consecutive_samples": 1
        }
      },
      "refuel": {
        "recovery": {
          "active_ticks": 8,
          "base_boost_hz": 2000,
          "pulse_coeff_hz_per_us": 2,
          "pressure_coeff_hz_per_raw": 1,
          "max_boost_hz": 10000,
          "recovery_floor_hz": 1200,
          "recovery_exit_error_raw": 4,
          "max_extend_ticks": 4,
          "allow_extend_while_undershoot": true,
          "boost_only_when_undershoot": true,
          "linear_decay": true
        },
        "slew": {
          "max_hz_delta_up_per_loop": 1200,
          "max_hz_delta_down_per_loop": 450,
          "recovery_bypass_slew_ticks": 3
        },
        "ready": {
          "ready_tol_raw": 4,
          "consecutive_samples": 1
        }
      }
    }
  }
}
```

### Required Top-Level Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema_version` | integer | yes | Must be `1` for this schema. |
| `active_profiles` | object | yes | Maps mode names to profile IDs or `null`. |
| `profiles` | object | yes | Object keyed by profile ID. |

### Required Profile Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `profile_id` | string | yes | Must match the key in `profiles`. |
| `mode` | string | yes | One of `droplet`, `stream`, `custom`. |
| `description` | string | yes | Human-readable purpose. |
| `source` | object | yes | Promotion/default provenance. |
| `conditions` | object | yes | Calibration context metadata. |
| `print` | object | yes | Print channel regulator settings. |
| `refuel` | object | yes | Refuel channel regulator settings. |

### Source Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `kind` | string | yes | `factory_default`, `calibration_candidate`, `promoted`, or `manual`. |
| `run_id` | string or null | yes | Calibration run that produced the profile, if any. |
| `promoted_at_utc` | string or null | yes | ISO-8601 UTC timestamp for promoted profiles. |
| `operator` | string or null | yes | Operator who promoted or edited the profile. |
| `notes` | string | yes | Free-form notes. |

### Conditions Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `printer_head_id` | string or null | yes | Metadata only in v1. |
| `printer_head_type` | string or null | yes | Metadata only in v1. |
| `reagent_id` | string or null | yes | Metadata only in v1. |
| `print_pressure_psi` | number or null | yes | Calibration condition. |
| `print_pulse_width_us` | integer or null | yes | Calibration condition. |
| `refuel_pressure_psi` | number or null | yes | Calibration condition. |
| `refuel_pulse_width_us` | integer or null | yes | Calibration condition. |
| `frequency_hz` | number or null | yes | Calibration condition. |

### Channel Fields

Each channel object must include:

| Field | Type | Required |
| --- | --- | --- |
| `recovery` | object | yes |
| `slew` | object | yes |
| `ready` | object | yes |

## Calibration Run Metadata

Each calibration run folder must contain `run_meta.json`.

```json
{
  "schema_version": 1,
  "run_id": "regopt_20260529_120000_12345678",
  "session_id": "session_20260529_115900_abcdef12",
  "created_at_utc": "2026-05-29T19:00:00Z",
  "operator": "",
  "mode": "stream",
  "candidate_profile_id": "stream_candidate_001",
  "candidate_profile": {},
  "baseline_profile": {},
  "conditions": {
    "printer_head_id": "",
    "printer_head_type": "",
    "reagent_id": "",
    "print_pressure_psi": 0.8,
    "print_pulse_width_us": 2500,
    "refuel_pressure_psi": 0.8,
    "refuel_pulse_width_us": 6000,
    "frequency_hz": 20,
    "pulse_count": 50,
    "channel": "print"
  },
  "outputs": {
    "trace_files": [],
    "analysis_json": null,
    "summary_csv": null,
    "plots": []
  },
  "outcome": {
    "status": "completed",
    "restored_previous_profile": true,
    "error_message": ""
  }
}
```

Required `outcome.status` values:

- `completed`
- `canceled`
- `failed`
- `restore_failed`

The calibration workflow must set `restored_previous_profile` to `true` only
after the previous profile has been restored or the firmware has confirmed that
no candidate profile was applied.

## Candidate And Promoted Profile Semantics

### Candidate Profile

A candidate profile is temporary. It may be loaded from JSON, edited in the UI,
or generated from analysis, but applying it to the MCU must be RAM-only.

Rules:

- Candidate profiles are never active production profiles by default.
- Candidate application must snapshot the prior MCU regulator settings before
  applying the first candidate in a calibration run.
- Candidate application must restore the prior settings on completion, cancel,
  timeout, serial disconnect, or error.
- Candidate profiles may be saved in calibration run folders as evidence.

### Promoted Profile

A promoted profile is an operator-approved profile that can be referenced by
`active_profiles`.

Rules:

- Promotion must be explicit.
- Promotion must record `source.kind = "promoted"`.
- Promotion must record the source `run_id` when the profile came from a
  calibration run.
- A promoted profile still applies to the MCU in RAM when selected; v1 does not
  persist it to MCU flash.

## Initial Safe Bounds

All Stage 2 command handlers and Python validators must reject values outside
these bounds. Clamping is allowed only if the command response or host result
reports that clamping occurred; rejection is preferred for calibration UI input.

### Recovery Bounds

| JSON field | Firmware field | Type | Min | Max |
| --- | --- | --- | --- | --- |
| `active_ticks` | `activeTicks` | integer | 0 | 20 |
| `base_boost_hz` | `baseBoostHz` | integer | 0 | 6000 |
| `pulse_coeff_hz_per_us` | `pulseCoeffHzPerUs` | integer | 0 | 4 |
| `pressure_coeff_hz_per_raw` | `pressureCoeffHzPerRaw` | integer | 0 | 4 |
| `max_boost_hz` | `maxBoostHz` | integer | 0 | 12000 |
| `recovery_floor_hz` | `recoveryFloorHz` | integer | 0 | 5000 |
| `recovery_exit_error_raw` | `recoveryExitErrorRaw` | integer | 1 | 30 |
| `max_extend_ticks` | `maxExtendTicks` | integer | 0 | 10 |
| `allow_extend_while_undershoot` | `allowExtendWhileUndershoot` | boolean | false | true |
| `boost_only_when_undershoot` | `boostOnlyWhenUndershoot` | boolean | false | true |
| `linear_decay` | `linearDecay` | boolean | false | true |

### Slew Bounds

| JSON field | Firmware field | Type | Min | Max |
| --- | --- | --- | --- | --- |
| `max_hz_delta_up_per_loop` | `maxHzDeltaUpPerLoop` | integer | 1 | 2500 |
| `max_hz_delta_down_per_loop` | `maxHzDeltaDownPerLoop` | integer | 1 | 2500 |
| `recovery_bypass_slew_ticks` | `recoveryBypassSlewTicks` | integer | 0 | 5 |

### Ready Bounds

| JSON field | Firmware field | Type | Min | Max |
| --- | --- | --- | --- | --- |
| `ready_tol_raw` | `readyTolRaw` | integer | 1 | 25 |
| `consecutive_samples` | `consecutiveSamples` | integer | 1 | 5 |

`ready_tol_raw` must never be used to disable the pressure-ready gate. The
maximum of `25` raw counts is intentionally conservative for v1 and can be
expanded only after trace evidence supports it.

## Reserved Stage 2 Command Contract

These command IDs are reserved for Stage 2. Stage 1 does not implement them.

| Command name | ID | Stage 2 requirement |
| --- | --- | --- |
| `CMD_SET_REG_RECOVERY_PROFILE` | `0x68` | Required |
| `CMD_SET_REG_SLEW_PROFILE` | `0x69` | Required |
| `CMD_SET_REG_READY_PROFILE` | `0x6A` | Required |
| `CMD_RESTORE_REG_PROFILE` | `0x6B` | Required |
| `CMD_QUERY_REG_PROFILE` | `0x6C` | Reserved; implement only if response path is safe |

### Shared Channel Codes

| Code | Channel |
| --- | --- |
| `0` | print |
| `1` | refuel |

Any other channel code must be rejected.

### Packed U16 Helper

When two 16-bit values share one command parameter:

```text
packed = (high_u16 << 16) | low_u16
```

### CMD_SET_REG_RECOVERY_PROFILE: 0x68

Recovery config uses three command chunks so the existing `p1/p2/p3` fields can
remain unchanged.

`p1` layout:

```text
bits 0..7:   channel code
bits 8..15:  chunk index
bit 16:      commit flag
bits 17..31: reserved, must be zero
```

Chunk `0`:

| Parameter | Bits | Field |
| --- | --- | --- |
| `p2` | low 16 | `active_ticks` |
| `p2` | high 16 | `base_boost_hz` |
| `p3` | low 16 | `pulse_coeff_hz_per_us` |
| `p3` | high 16 | `pressure_coeff_hz_per_raw` |

Chunk `1`:

| Parameter | Bits | Field |
| --- | --- | --- |
| `p2` | low 16 | `max_boost_hz` |
| `p2` | high 16 | `recovery_floor_hz` |
| `p3` | low 16 | `recovery_exit_error_raw` |
| `p3` | high 16 | `max_extend_ticks` |

Chunk `2`:

| Parameter | Bits | Field |
| --- | --- | --- |
| `p2` | bit 0 | `allow_extend_while_undershoot` |
| `p2` | bit 1 | `boost_only_when_undershoot` |
| `p2` | bit 2 | `linear_decay` |
| `p2` | bits 3..31 | reserved, must be zero |
| `p3` | all | reserved, must be zero |

Stage 2 must stage chunks per channel and apply recovery only when chunk `2`
arrives with the commit flag set. Commit must fail if chunks `0` and `1` have
not been staged for the same channel.

### CMD_SET_REG_SLEW_PROFILE: 0x69

`p1` layout:

```text
bits 0..7:   channel code
bits 8..31:  reserved, must be zero
```

Payload:

| Parameter | Bits | Field |
| --- | --- | --- |
| `p2` | low 16 | `max_hz_delta_up_per_loop` |
| `p2` | high 16 | `max_hz_delta_down_per_loop` |
| `p3` | low 8 | `recovery_bypass_slew_ticks` |
| `p3` | bits 8..31 | reserved, must be zero |

### CMD_SET_REG_READY_PROFILE: 0x6A

`p1` layout:

```text
bits 0..7:   channel code
bits 8..31:  reserved, must be zero
```

Payload:

| Parameter | Bits | Field |
| --- | --- | --- |
| `p2` | low 16 | `ready_tol_raw` |
| `p2` | high 16 | reserved, must be zero |
| `p3` | low 8 | `consecutive_samples` |
| `p3` | bits 8..31 | reserved, must be zero |

### CMD_RESTORE_REG_PROFILE: 0x6B

`p1` channel mask:

| Bit | Meaning |
| --- | --- |
| `0` | restore print channel |
| `1` | restore refuel channel |

`p2` restore source:

| Value | Meaning |
| --- | --- |
| `0` | restore session baseline snapshot |
| `1` | restore firmware defaults |

`p3` is reserved and must be zero.

Stage 2 must snapshot the session baseline before applying the first candidate
profile command after boot or after the previous restore. If no candidate has
been applied, restore must be treated as a safe no-op.

### CMD_QUERY_REG_PROFILE: 0x6C

This ID is reserved for a future query/snapshot command. Stage 2 may leave it
unimplemented if there is no compact, safe response path.

If implemented later:

| Parameter | Meaning |
| --- | --- |
| `p1` | channel code |
| `p2` | component code: `0` recovery, `1` slew, `2` ready, `3` all |
| `p3` | host request ID |

The query response format must be documented before implementation.

## Later Validation Commands

When Stage 2 touches firmware, run:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

When Stage 3 adds Python validators, run targeted profile tests and then the
full Python suite if model/controller integration is touched:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_regulator_profiles.py
.\env\Scripts\python.exe -m pytest -q
```
