# SIL State Trace Schema Version 1

Date: 2026-07-31

This document defines the simulation-only state evidence written by the
interactive hardware-isolated simulator. It does not change an experiment,
device protocol, firmware, or production report schema.

## Artifact Layout

Each application launch beneath one retained simulation root owns a unique
directory:

```text
artifacts/state/<application_session_id>/
  events.jsonl
  latest_snapshot.json
  terminal_snapshot.json
```

`events.jsonl` is the complete append-only trace for that application session.
`latest_snapshot.json` is replaced once per explicit persisted snapshot.
`terminal_snapshot.json` is written once during normal cleanup. Paths recorded
in `session.json` are relative to the simulation root.

## Event Document

Schema identity: `labcraft.sil_state_event`, version `1`.

Every non-empty JSONL line is one complete UTF-8 JSON object with these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_id` | string | Always `labcraft.sil_state_event` |
| `schema_version` | integer | Always `1` |
| `event_sequence` | integer | Strictly increasing from 1 within one application session |
| `captured_at_utc` | string | UTC ISO-8601 capture time |
| `monotonic_ns` | integer | Process-monotonic ordering value |
| `session_id` | string | Stable retained-root session identity |
| `application_session_id` | string | Identity unique to this launch |
| `event_kind` | string | Canonical event vocabulary below |
| `source_layer` | string | Layer that produced the observation |
| `simulated_elapsed_ms` | integer or null | Simulator time when available |
| `correlation` | object | Optional `action_id`, `command_id`, and/or `snapshot_id` |
| `before` | object or null | Bounded changed fields before a transition |
| `after` | object or null | Bounded changed fields after a transition |
| `payload` | any JSON value | Bounded event-specific evidence |
| `truncation` | object | Exact normalization/truncation counters |

Canonical v1 event kinds are:

- `recorder_started` and `recorder_stopped`;
- `action_started` and `action_completed`;
- `simulator_connection_changed`, `simulator_command_lifecycle`,
  `simulator_state_changed`, and `simulator_fault`;
- `controller_array_state_changed`, `controller_error`, and
  `controller_transport_fault`;
- `model_machine_state_changed`, `model_experiment_loaded`, and
  `rack_state_changed`;
- `calibration_state_changed` and `refuel_check_changed`;
- `projection_reconciled` and `snapshot_exported`;
- `teardown_started`; and
- `cleanup_completed` or `cleanup_failed`.

Connect, disconnect, and explicit-export actions use recorder-generated IDs of
the form `action-000001`. Simulator command IDs combine the application-session
identity and command number. Snapshot IDs use `snapshot-000001`. Correlation is
assigned from explicit ownership, never inferred from wall-clock proximity.

## Snapshot Document

Schema identity: `labcraft.sil_state_snapshot`, version `1`.

A snapshot contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_id`, `schema_version` | string, integer | Snapshot schema identity |
| `snapshot_id` | string | Application-session-local snapshot identity |
| `event_sequence` | integer | Sequence of the corresponding JSONL event |
| `captured_at_utc`, `monotonic_ns` | string, integer | Capture ordering |
| `session_id`, `application_session_id` | string, string | Root and launch identity |
| `reason` | string | Capture trigger |
| `correlation` | object | Includes `snapshot_id`; may include action/command identity |
| `projection` | object | Bounded cross-layer projection |
| `truncation` | object | Projection normalization counters |

The projection contains `reason`, `layers`, and `reconciliation`. Required
layers are `session`, `simulator`, `controller`, `model_machine`, `rack_head`,
`experiment`, `calibration`, `refuel_check`, `ui`, and `persistence`. Every
layer has:

```json
{
  "available": true,
  "state": {},
  "error": null
}
```

An observation failure sets `available` to `false`, preserves an empty state,
and records the error. It does not manufacture state or repair the application.

`reconciliation.status` is `ok`, `mismatch`, or `unavailable`.
`compared_fields` is the exact comparison count, `domains` reports counts by
comparison domain, and `mismatches` contains bounded structured differences.
Version 1 compares settled simulator/Model machine state, Controller array/UI
state, confirmed rack/head identity, in-memory plan identity versus persisted
plan/progress identity, and applied calibration/refuel counts versus the
execution-calibration sidecar when those sources are available.

Simulator pressure is projected in both protocol raw units and Model PSI.
Pressure and gripper-active values are reconciled only while both simulator and
Model report a live connection because the Model intentionally does not consume
or reset those values in the same way while disconnected.

## Bounds And Durability

Default bounds are 512 retained in-memory events, 64 changed fields, 2,048
characters per string, 100 collection entries, and depth 8. The full JSONL is
not evicted. Every event is flushed by default. Health output records exact
event, eviction, and truncation counts.

Snapshot files use one same-directory temporary write, flush, `fsync`, and
replace attempt. A failed or ambiguous append/replace is not retried. The
recorder is marked failed, its observer is removed, and the simulation session
is retained and failed while normal application teardown continues.

## Compatibility

New event kinds that preserve the envelope may be documented without changing
the schema version. Removing or changing required fields, identity semantics,
ordering semantics, or projection layer contracts requires a new schema
version. Older Milestone 1 `session.json` files remain valid; reopening them
adds a new application-session trace without modifying prior traces.
