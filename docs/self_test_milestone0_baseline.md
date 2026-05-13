# Milestone 0 Self-Test Baseline Inventory

## Purpose

This document records the current hardware-in-the-loop self-test behavior before any qualification framework, firmware, protocol, or runner behavior changes. It is the Milestone 0 baseline artifact for the self-test implementation branch.

Documented call path:

`firmware/scripts/run_fw_hil_windows.ps1 -> firmware/hil/flash_and_test.sh -> tools/run_selftest.py -> CMD_SELFTEST_START -> firmware self-test block -> CMD_SELFTEST_RESULT/CMD_SELFTEST_DONE -> JSON report`

Milestone 0 is documentation-only. It does not add manifests, execute tests automatically, change firmware, change normal control protocol behavior, or change hardware motion/pressure/valve timing.

## Latest Known-Good Baseline

| Field | Value |
| --- | --- |
| Report path | `hil_reports/selftest_20260421_090914.json` |
| Run ID | `2966292189` |
| Profile | `FULL` |
| Started | `2026-04-21T16:09:45.437443Z` |
| Finished | `2026-04-21T16:09:53.638906Z` |
| Aborted | `false` |
| Summary | `23 total`, `23 passed`, `0 failed` |

Freshness note: this report is the latest local passing HIL report found during Milestone 0 planning. It should be replaced by a newer FULL report if hardware is available before later qualification milestones depend on these baseline values.

## Current Report Schema Summary

Observed top-level fields:

| Field | Meaning |
| --- | --- |
| `run_id` | Host-selected logical run identifier for the self-test session. |
| `profile` | Requested profile, observed as `FULL` in the baseline report. |
| `started_at` | UTC timestamp when the host runner started the self-test run. |
| `finished_at` | UTC timestamp when the host runner finished and wrote the report. |
| `aborted` | Boolean indicating whether the run ended before normal `CMD_SELFTEST_DONE` completion. |
| `summary` | Aggregate counts: `total`, `passed`, and `failed`. |
| `results` | Ordered firmware-emitted self-test result rows. |
| `host_checks` | Host-side checks and runner watchdog observations. |

Observed `results[]` row fields:

| Field | Meaning |
| --- | --- |
| `test_id` | Stable numeric test identifier emitted by firmware. |
| `name` | Stable test name emitted by firmware; long names may be truncated by current payload limits. |
| `pass` | Firmware-side pass/fail boolean. |
| `metrics` | Compact key/value map of test-specific measurements. |

Observed `host_checks[]` row fields:

| Field | Meaning |
| --- | --- |
| `name` | Host-side check name, such as `hello_ack`, `selftest_start_ack`, or `selftest_progress_watchdog`. |
| `pass` | Host-side pass/fail boolean. |
| `details` | Check-specific transport, timeout, frame-count, or progress-watchdog details. |
| `timestamp` | UTC timestamp for the host check. |

No explicit `schema_version` field was observed in the baseline report.

## Current SAFE Inventory

The following tests are present before the FULL-only hardware-active section and are treated as the current SAFE inventory.

| ID | Name | Baseline result | Key metrics |
| --- | --- | --- | --- |
| `1001` | `comm_crc_known_vector` | pass | `crc` |
| `1002` | `comm_frame_roundtrip` | pass | `frame_len` |
| `1010` | `session_hello_ack` | pass | `ack_cmd`, `seq8_match`, `seq32_match` |
| `1011` | `session_goodbye_ack` | pass | `ack_cmd`, `seq8_match`, `seq32_match` |
| `1012` | `session_goodbye_done` | pass | `done_cmd`, `seq8_match`, `seq32_match` |
| `1003` | `status_frame_shape` | pass | `chunk0_seen`, `chunk1_seen`, `has_seq32`, `tag_count` |
| `1013` | `clear_queue_ack` | pass | `ack_cmd`, `queue_depth_after_clear`, `seq8_match`, `seq32_match` |
| `1020` | `status_chunk_alternation_safe` | pass | `alternation_errors`, `chunk0_seen`, `chunk1_seen` |
| `1021` | `status_cadence_safe` | pass | `period_ms_avg`, `period_ms_max_jitter` |
| `1004` | `uptime_counter_read` | pass | `delta_ms` |
| `1005` | `flash_config_readonly` | pass | flash event counts and pulse width metrics |
| `1007` | `flash_imaging_burst_diag_safe` | pass | cycle counts, flash task deltas, fault latch state |
| `1006` | `fw_build_info` | pass | `build_epoch`, `version_len` |
| `1030` | `uart_recovery_after_noise_safe` | pass | CRC/length rejects and recovered frame count |
| `1040` | `rtos_memory_headroom_safe` | pass | heap, task, stack, and high-water metrics |
| `1041` | `crash_record_retained_safe` | pass | boot/reset/fault/watchdog summary fields |
| `1042` | `watchdog_supervisor_safe` | pass | watchdog enablement, request, recovery, and timeout fields |

Host-side checks in the baseline report:

| Name | Baseline result | Notes |
| --- | --- | --- |
| `hello_ack` | pass | Confirms initial host/device session setup and self-test transport capability. |
| `selftest_start_ack` | pass | Confirms `CMD_SELFTEST_START` was accepted through queue ACK transport. |
| `goodbye_ack` | pass | Confirms session teardown ACK. |
| `goodbye_done` | pass | Confirms session teardown completion. |
| `selftest_progress_watchdog` | pass | Confirms progress frames, activity timeout state, recent frames, and frame counts. |

## Current FULL Inventory

The following tests require the FULL profile and are hardware-active.

| ID | Name observed in report | Baseline result | Key metrics |
| --- | --- | --- | --- |
| `2001` | `motion_home_cycle_full` | pass | `home_success_axes`, `home_time_ms`, `limit_hits` |
| `2002` | `motion_absolute_move_bounds_full` | pass | `bound_violation`, `final_error_steps`, `target_x`, `target_y`, `target_z` |
| `2003` | `pressure_regulator_step_response` | pass | `overshoot`, `settle_time_ms`, `steady_state_error`, `target_pressure` |
| `2004` | `valve_actuation_sequence_full` | pass | `sequence_order_ok`, `valve_open_count`, `valve_close_count` |
| `2005` | `print_refuel_pulse_integrity_ful` | pass | `pulse_count`, `pulse_width_min_ns`, `pulse_width_max_ns` |
| `2006` | `emergency_abort_and_safe_stop_fu` | pass | `abort_latency_ms`, `motors_disabled`, `regulators_stopped`, `valves_safe_state` |

The `2005` and `2006` names are documented as observed. Their likely full names are truncated by the current result payload size.

## Initial Qualification Suite Outline

| Suite | Purpose | Current contents |
| --- | --- | --- |
| SAFE smoke/regression | Verify communication, session handling, status framing, flash read-only diagnostics, memory headroom, crash logging, and watchdog visibility without deliberate motion, valve actuation, or pressure changes. | Current SAFE inventory plus host checks. |
| FULL factory acceptance | Verify the currently available motion, pressure, valve, pulse, and emergency-stop diagnostics on a prepared machine. | Current FULL inventory. |
| Motion fixture-gated | Future suite for repeated motion envelope and homing characterization. | Open; starts from IDs `2001` and `2002`. |
| Pressure fixture-gated | Future suite for leak, hysteresis, and pressure sweep characterization. | Open; starts from ID `2003` and future `2100-2399` ranges. |
| Valve and pulse fixture-gated | Future suite for valve sequencing and pneumatic/electrical pulse repeatability. | Open; starts from IDs `2004` and `2005`. |
| Gripper fixture-gated | Future suite for seal, clamp, blocked-head, or dummy-head fixture tests. | Open; no current gripper HIL result IDs in this baseline report. |
| Imaging and flash fixture-gated | Future suite for flash/camera timing and imaging qualification. | Open; SAFE flash diagnostics currently exist, camera/imaging acceptance remains future work. |

## Fixture Assumptions and Open Questions

Initial fixture list:

| Fixture ID | Status | Notes |
| --- | --- | --- |
| `motion_clear_envelope` | proposed | Required for FULL motion tests; operator must confirm the gantry envelope is clear. |
| `pressure_hold_closed_loop` | proposed | Required for pressure response tests; exact pneumatic setup should be documented before acceptance thresholds harden. |
| `print_valve_pneumatic_drop` | proposed | Required for valve and pulse integrity tests if measuring physical pneumatic behavior. |
| `refuel_valve_pneumatic_drop` | proposed | Paired with print-valve pulse checks where applicable. |
| `blocked_head_seal_test` | proposed | Future gripper/seal fixture; no current baseline result covers it. |

Open items:

- Machine ID convention is not yet confirmed. The roadmap recommendation is a stable local identity such as `LC-0001` plus a generated UUID stored outside tracked repository files.
- The baseline report does not include an explicit fixture ID or machine ID.
- The latest local report is FULL and passing, but a new report should be produced before setting hard factory acceptance thresholds.
- Gripper acceptance metrics are placeholders until a fixture and HIL test IDs are added.

## First-Pass Acceptance Metrics

These metrics are intentionally not hard acceptance thresholds in Milestone 0. They define the first measurements to collect and review.

| Subsystem | Metrics | Initial maturity | Notes |
| --- | --- | --- | --- |
| Motion | `home_success_axes`, `home_time_ms`, `limit_hits`, `final_error_steps`, `bound_violation`, `abort_latency_ms`, `motors_disabled` | candidate | Safety-critical booleans can become acceptance gates once repeated known-good data exists. |
| Pressure | `target_pressure`, `overshoot`, `settle_time_ms`, `steady_state_error`, progress watchdog readiness behavior | candidate | Bounds should be empirical and profile-specific. |
| Valves | `sequence_order_ok`, `valve_open_count`, `valve_close_count`, `valves_safe_state` | candidate | Current metrics confirm sequence shape, not physical output volume. |
| Pulses | `pulse_count`, `pulse_width_min_ns`, `pulse_width_max_ns` | candidate | Width limits should be tied to hardware timing tolerance after repeated runs. |
| Gripper | seal state, clamp state, leak/hold result, fixture-present confirmation | informational | Placeholder only; no current baseline HIL test IDs. |
| Host/session | HELLO/START/GOODBYE checks, progress watchdog, timeout reason, frame counts | candidate | Infrastructure failures should remain distinguishable from firmware diagnostic failures. |

## Validation Notes

Milestone 0 validation is documentation inspection only:

- Confirm this document references `hil_reports/selftest_20260421_090914.json`.
- Confirm the inventory tables match the 23 passing result rows in that report.
- Confirm the schema summary matches the observed top-level fields.

Optional hardware validation, if explicitly authorized:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

If a newer passing FULL report is generated, update this document with the new path and summary before closing Milestone 0.
