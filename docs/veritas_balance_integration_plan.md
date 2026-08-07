# Experimental Veritas Balance Integration Plan

## Status

- Date: 2026-08-07
- Branch: `feature/balance_integration`
- Status: Slices 0-3 verified; Slice 4 ready
- Scope: implementation plan and slice verification record
- Target hardware: Veritas/BEL HPB balance connected to the Raspberry Pi through a proper RS-232-to-USB adapter
- Target workflow: stream gravimetric data collection only

## Purpose

Add an intentionally activated `BalanceService` that can capture stable starting
and ending masses for the existing stream gravimetric workflow. The service
must remove routine mass transcription without making balance support part of
the normal product workflow.

The current manual mass-entry path remains authoritative and available at all
times. A balance connection failure, parse failure, stability timeout, or
operator decision to stop using the balance must return the open capture to
manual entry without losing the stream run.

This work is Python/application-only. It must not change printer firmware,
printer opcodes, message formats, command timing, pressure behavior, motion
behavior, or existing firmware handlers.

## Goals

- Read the HPB balance through a USB serial device on the Raspberry Pi.
- Parse complete balance records and normalize supported units to milligrams.
- Determine stability from a time-based sample window, with the balance's own
  stability indicator used only after its exact transmitted value is verified
  on the physical unit.
- Capture a stable starting mass before launching the existing stream sequence.
- Capture a stable ending mass after the existing loading-position transition.
- Feed both values through the existing gravimetric calculation and CSV writer.
- Record enough balance provenance and stability evidence to audit each value.
- Keep normal users unaware of the feature unless an explicit experimental
  runtime flag is enabled.
- Require a second explicit action to connect the selected serial port.
- Preserve manual entry as the default and fallback behavior.

## Non-Goals

- Reusing `legacy.mass_calibration.Balance` as the new implementation.
- Enabling the legacy mass-calibration workflow in the current hardware
  profile.
- Automatically discovering and opening a balance port at startup.
- Exposing balance controls to normal users.
- Remotely taring, calibrating, powering off, or changing balance settings in
  the first implementation.
- Closing the loop on printer pressure, pulse width, or other print settings
  from a mass result.
- Blocking hardware cleanup, gripper restoration, camera return, or application
  shutdown because the balance is unavailable.
- Changing the existing stream metadata CSV headers in the first
  implementation.
- Adding firmware or printer-protocol behavior.

## Manual And Hardware Findings

The attached HPB manual specifies:

- RS-232C communication, with 1200, 2400, 4800, or 9600 baud selectable;
- 8 data bits, one stop bit, and no parity;
- continuous output at the display update rate or output initiated by the
  balance's PRINT button;
- a weighing record containing sign, numeric weight, unit, stability field,
  and CR/LF termination; and
- remote key commands, including tare and calibration, which are deliberately
  out of scope for the first implementation.

The manual calls the record 14 characters while enumerating positions 1-15.
The implementation must therefore frame on CR/LF and validate fields instead
of trusting the stated total length. The stability field is identified, but
its stable/unstable character mapping must be confirmed from raw output from
the actual balance before it becomes a required software gate.

The balance interface is RS-232, not Raspberry Pi GPIO-level UART. Use the
manufacturer-compatible serial cable and a proper RS-232-to-USB converter.
Never connect the DB9 RS-232 signals directly to Raspberry Pi GPIO pins.

Recommended balance configuration for characterization is `PC cont`, 9600
baud, 8N1. Continuous mode permits the application to apply its own stability
window without sending remote balance commands.

### Slice 0 Frozen Hardware

- Balance: Veritas HPB-625i.
- Balance interface: DB9 RS-232C, using the HPB manual's serial settings and
  pinout as the characterization reference.
- USB adapter: BENFEI model `000302`, Amazon ASIN `B08B6C1XQN`, six-foot USB-A
  to male DB9 RS-232 cable.
- Adapter chipset: Prolific PL-2303.
- Target host: Raspberry Pi/Linux. The adapter manufacturer lists Linux 2.4.0
  and later compatibility; the actual Pi kernel binding, USB identifiers, and
  `/dev/serial/by-id` availability remain Slice 1 characterization evidence.
- Electrical boundary: the BENFEI cable performs USB-to-RS-232 conversion; no
  DB9 signal is connected directly to Raspberry Pi GPIO.

The operator-confirmation-first ending-mass workflow is accepted for the
initial hardware-capable implementation. Optional session-only auto-save
remains a later slice gated by confirmation-mode hardware evidence.

## Current Call Paths

### Current Stream Gravimetric Start

`CalibrationClasses/View.py::begin_stream_gravimetric_capture`

`-> Controller.start_stream_gravimetric_capture(starting_mass_mg, ...)`

`-> CalibrationManager.start_stream_gravimetric_capture(...)`

`-> gripper refresh/suspend preamble`

`-> existing calibration queue`

`-> Controller/Machine_FreeRTOS existing print, motion, pressure, and camera commands`

`-> existing firmware handlers`

### Current Stream Gravimetric Completion

`CalibrationManager._complete_stream_capture_queue_success()`

`-> pending loading move`

`-> Controller.begin_stream_gravimetric_capture_loading_move()`

`-> existing motion path`

`-> CalibrationManager.mark_stream_gravimetric_capture_loading_reached()`

`-> StreamCaptureMassEntryDialog`

`-> Controller.finalize_stream_gravimetric_capture(ending_mass_mg, ...)`

`-> CalibrationManager._build_stream_capture_metadata_row()`

`-> mass_change = ending_mass - starting_mass`

`-> existing stream metadata CSV and stream-capture JSONL sidecar`

### Current Legacy Balance Path

`ConnectionWidget -> Controller.connect_balance()`

`-> legacy.mass_calibration.Balance`

`-> balance_mass_updated_signal`

`-> legacy MassCalibrationModel.update_mass()`

This path is constructed only for the `legacy` hardware profile. It performs
polling and parsing that are not sufficient for the HPB stream-capture use
case. It should remain unchanged so the experimental implementation cannot
regress legacy behavior.

## Target Call Paths

### Explicit Activation And Connection

`App.py exact experimental environment flag`

`-> ApplicationComposition experimental feature configuration`

`-> construct BalanceService only in production current-profile runtime`

`-> show experimental controls only in the stream-capture UI`

`-> operator selects port and clicks Connect`

`-> Controller.connect_experimental_balance(port)`

`-> BalanceService worker opens serial transport`

The proposed flag is:

`LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE=1`

Only the exact value `1` enables the feature. Absence or any other value keeps
the service unconstructed and the controls absent. The flag should not be
added to the tracked `Settings.json` preset. This keeps activation tied to an
intentional developer/operator launch configuration.

Connection remains manual even when the flag is set. The app may preselect the
locally saved `BALANCE_PORT`, but it must never open it automatically.

### Starting Mass With Balance Opt-In

`Stream capture UI: Use connected balance for this session`

`-> Controller requests balance-backed start`

`-> CalibrationManager records awaiting-starting-mass state and request identity`

`-> Controller requests stable mass from BalanceService`

`-> BalanceService worker -> parser -> stability detector`

`-> typed stable result with matching session/request/phase identity`

`-> Controller -> CalibrationManager accepts starting mass`

`-> existing start_stream_gravimetric_capture continuation`

`-> existing gripper/calibration/machine/firmware path unchanged`

No printer action may be queued before the starting mass has been accepted.
Stale or duplicate balance completions must be ignored by request identity.

### Ending Mass With Balance Opt-In

`existing stream queue completes`

`-> existing loading move completes`

`-> CalibrationManager enters awaiting-ending-balance-mass state`

`-> UI asks operator to place/confirm the sample and request a stable reading`

`-> Controller -> BalanceService stable-mass request`

`-> typed stable result with matching session/request/phase identity`

`-> Controller -> CalibrationManager accepts ending mass`

`-> existing finalize_stream_gravimetric_capture(...)`

`-> existing difference, mass-per-print, CSV, restore, and camera-return path`

The first hardware-capable version should populate the ending mass and show
the calculated change for explicit operator confirmation before saving. An
optional session-only auto-save mode can be added in a later slice after the
capture and fallback behavior pass hardware validation.

### Manual Fallback

`balance timeout/disconnect/parse failure/operator chooses manual`

`-> cancel only the outstanding balance request`

`-> CalibrationManager changes the mass source for that phase to manual`

`-> existing starting-mass spin box or StreamCaptureMassEntryDialog`

`-> existing start/finalize path`

Fallback must not discard the calibration session, repeat the print sequence,
or skip gripper restoration and camera return.

## Activation Contract

The feature has three intentional gates:

1. The application is launched with
   `LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE=1`.
2. The operator selects a serial port and clicks `Connect Balance`.
3. The operator enables `Use connected balance for this stream capture
   session`.

The third choice may remain selected for the lifetime of the open imager or
application session to support repeated data collection. It must reset to off
after an application restart and must not be persisted as a normal machine
setting.

When any gate is absent:

- the current starting-mass field remains editable;
- the current ending-mass dialog remains unchanged;
- no balance serial device is opened;
- no extra workflow state is entered; and
- normal users see no new controls or status text.

## Proposed Architecture

### Pure Protocol And Stability Layer

Add a pure-Python layer with no Qt, serial port, Model, Controller, or hardware
dependencies. It should define:

- `BalanceReading`: timestamp, numeric value, normalized `mass_mg`, reported
  unit, raw stability field, optional verified stable flag, and raw-frame
  diagnostics;
- `StableMassRequest`: request id, stream session id, phase (`starting` or
  `ending`), start time, timeout, and stability policy snapshot;
- `StableMassResult`: outcome, stable mass, sample count, window duration,
  span, standard deviation, fitted slope, stability-field observations, and
  error details;
- a CR/LF stream framer that handles partial and multiple reads;
- an HPB weighing-record parser; and
- a time-based stability detector.

The parser must reject malformed records, unsupported units, non-finite
values, overload/status messages, and frames that do not represent weighing
mode. Supported units should be explicit. At minimum, `g` and `mg` should be
normalized to milligrams.

The stability policy should be time-based, not dependent on an assumed serial
update frequency. Initial values for hardware characterization may be:

- ignore period after request: 1 second;
- minimum valid window: 3 seconds;
- minimum samples: 10;
- maximum window span: 0.03 mg;
- maximum absolute fitted slope: 0.01 mg/s; and
- request timeout: 30 seconds.

These are starting characterization values, not final metrology claims. They
must be constants/configuration captured in every result and tuned from blank,
loaded, disturbed, and drifting traces from the physical balance.

### BalanceService

`BalanceService` should be a narrow QObject facade backed by a dedicated
worker thread or equivalent nonblocking serial worker. The GUI thread must
never call a serial read that can wait on a timeout.

Responsibilities:

- explicit connect and disconnect;
- expose typed connection state and errors;
- accept at most one active stable-mass request;
- frame and parse incoming records;
- run the stability detector;
- emit typed progress and terminal results;
- cancel requests without closing the app or touching printer state;
- close the serial transport and worker deterministically during app shutdown;
- never send remote tare/calibration/power commands in the initial version.

The serial transport must be injectable. Unit tests and simulation tests use
a fake byte-stream transport; simulation must never instantiate or open
`serial.Serial`.

### Composition Boundary

Do not change `CURRENT_PROFILE.has_mass_calibration` to true. That field and
the existing `balance_factory` currently carry legacy meaning.

Prefer an additive experimental composition seam, for example:

- `ExperimentalFeatures(balance_integration=False)` passed to application
  construction;
- `experimental_balance_factory` in `ApplicationDependencies`; and
- optional `balance_service` in `ApplicationComponents` and `Controller`.

Production constructs the service only when all activation conditions are
met. Simulation supplies a blocked factory and remains incapable of physical
serial access. Application teardown closes the optional service before Qt
objects are deleted.

### Controller Boundary

Use explicitly named methods so legacy and experimental balance behavior
cannot be confused:

- `list_experimental_balance_ports()`;
- `connect_experimental_balance(port)`;
- `disconnect_experimental_balance()`;
- `request_stream_capture_stable_mass(session_id, phase, policy)`; and
- `cancel_stream_capture_stable_mass(request_id)`.

The controller should reject:

- feature-disabled calls;
- simulation runtime calls;
- a port currently used by the MCU;
- duplicate connection or measurement requests;
- stale result identities; and
- phases that do not match the CalibrationManager state.

The service must not call Model methods directly. Its signals are adapted by
the Controller into explicit CalibrationManager transitions.

### CalibrationManager State

Keep the stream capture state authoritative. Add only the fields needed to
make balance activity observable and recoverable, such as:

- `mass_source`: `manual` or `veritas_balance`;
- `balance_request_id`;
- `balance_request_phase`;
- `balance_request_status`;
- `balance_status_message`;
- `starting_mass_capture`;
- `ending_mass_capture`; and
- `balance_fallback_reason`.

Add a starting state such as `awaiting_starting_balance_mass`. At completion,
use a distinct `awaiting_ending_balance_mass` state until a stable result is
accepted or the operator chooses manual fallback. Include these states in
busy/open-session guards and update blockers so duplicate calibration or app
update actions cannot start while a request is pending.

The existing `starting_mass_mg`, `ending_mass_mg`, mass difference,
mass-per-print, CSV writer, gripper restore, and camera-return behavior remain
the final source of truth.

### UI Boundary

Experimental controls belong beside the stream gravimetric controls in
`CalibrationClasses/View.py`, not in the normal current-profile connection
widget.

When enabled, show a visually explicit `Experimental Balance` group with:

- serial-port selector and refresh button;
- Connect/Disconnect button;
- connection and last-reading status;
- session-only `Use connected balance` checkbox;
- stable-reading progress, elapsed time, and cancel/retry/manual controls; and
- the accepted mass, calculated change, and measurement source.

The existing manual widgets remain present. They may become read-only while a
balance request is active, but must be restored immediately on fallback.

Do not automatically capture an ending mass merely because the balance has a
stable unloaded value. After the loading move, require an explicit operator
action such as `Sample placed - read stable ending mass`. This prevents an
empty balance plateau from being accepted before the sample is placed.

### Evidence And Persistence

Do not change the established stream metadata CSV headers in the initial
implementation. Continue writing the existing starting mass, ending mass,
mass change, number printed, and mass-per-print fields.

Add balance evidence to the existing stream-capture JSONL sidecar or a
strictly nested/additive sidecar payload:

- source (`manual` or `veritas_balance`);
- request and stream session ids;
- phase;
- accepted mass in mg;
- original unit;
- start/end timestamps;
- policy thresholds;
- sample count, span, standard deviation, and slope;
- stability-field values and whether their mapping was verified;
- connection/device description and serial settings;
- terminal outcome or fallback reason.

Raw serial records may be retained in the experiment's calibration recording
area when record mode is active, but they should not be inserted into the CSV.
Bound raw evidence to the active request window so continuous balance output
cannot create an unbounded log.

## Files Expected Across The Implementation

The planning slice touches only:

- `docs/veritas_balance_integration_plan.md`

Likely implementation files are:

- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/ApplicationComposition.py`
- new `FreeRTOS-interface/BalanceProtocol.py`
- new `FreeRTOS-interface/BalanceService.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- optionally `FreeRTOS-interface/Model.py` only for reuse of the existing
  local `BALANCE_PORT` preference
- new `tools/probe_veritas_balance.py`
- `README.md` or a focused operator document under `docs/`
- new `tests/test_veritas_balance_protocol.py`
- new `tests/test_balance_service.py`
- new `tests/test_stream_gravimetric_balance_integration.py`
- `tests/test_stream_gravimetric_capture.py`
- `tests/test_safe_application_construction.py`
- `tests/test_controller_port_classification.py`
- `tests/test_app_settings_fallback.py` if startup flag parsing is factored
  through the app settings helper

No file under `firmware/` is expected to change.

## Global Implementation Rules

- Before each slice, restate its call path, steps, and exact files to touch.
- Keep each slice independently testable and reversible.
- Preserve all current manual gravimetric behavior until the balance path has
  completed hardware validation.
- Do not modify the legacy balance implementation in the same slice as the
  new service.
- Do not perform serial I/O on the GUI thread.
- Do not accept a stable result without matching request, stream session, and
  phase identities.
- Do not allow a balance error to enqueue or cancel printer commands.
- Do not introduce remote balance commands during these slices.
- Do not add firmware work unless a later, separately approved requirement
  makes it necessary.

## Implementation Slice Summary

| Slice | Scope | Gate Before Next Slice |
| --- | --- | --- |
| 0 | Plan and freeze boundaries (`verified`) | Plan reviewed |
| 1 | Hardware/protocol characterization and golden fixtures (`verified`) | Raw HPB behavior recorded |
| 2 | Pure parser, units, and stability contract (`verified`) | Pure unit tests pass |
| 3 | Nonblocking BalanceService | Service/thread tests pass |
| 4 | Explicit activation, composition, connection UI | Feature-off equivalence and connection tests pass |
| 5 | Starting-mass workflow and fallback | No printer command before accepted mass |
| 6 | Ending-mass workflow, persistence, and confirmation | Existing CSV calculation proven unchanged |
| 7 | Optional session auto-save for high-throughput collection | HIL confirmation-mode gate passes first |
| 8 | Pi deployment, resilience, full validation, and handoff | Full suite and hardware checklist pass |

## Slice 0: Plan And Boundary Freeze

Status: `verified`

Goal:

Approve this document as the implementation reference.

Call path:

`documentation review only`

Files to touch:

- `docs/veritas_balance_integration_plan.md`

Implementation steps:

1. Review the activation, call-path, fallback, evidence, and non-goal
   decisions. Complete.
2. Confirm the actual balance model and RS-232-to-USB adapter to be used.
   Complete: Veritas HPB-625i and BENFEI `000302`/`B08B6C1XQN` with Prolific
   PL-2303.
3. Confirm that explicit operator confirmation is acceptable for the first
   ending-mass implementation. Complete through approval of this plan.
4. Approve Slice 1 hardware characterization. Complete.

Validation:

- Markdown review.
- Confirm no code or firmware files changed.

Completion evidence:

- Plan approved by the operator on 2026-08-06.
- Exact balance and adapter identities supplied by the operator on
  2026-08-06.
- BENFEI's product specification identifies a USB-A to male DB9 RS-232 cable,
  Prolific PL-2303 chipset, and Linux compatibility.
- Repository change remains documentation-only.

Rollback:

- Remove this planning document.

## Slice 1: HPB Hardware And Protocol Characterization

Status: `verified`

Goal:

Capture the real serial behavior before freezing parser and stability
semantics.

Call path:

`Pi USB port -> RS-232-to-USB adapter -> probe tool -> retained raw transcript`

Files implemented:

- `tools/probe_veritas_balance.py`
- `tests/test_probe_veritas_balance.py`
- `tests/fixtures/veritas_balance/hpb625i_serial_samples_v1.json`
- `docs/veritas_balance_probe.md`
- this plan

Implementation steps:

1. Add a read-only probe tool that requires an explicit port and never sends
   balance commands.
2. Record adapter identity, Linux device path, baud, framing, and balance mode.
3. Capture unloaded stable, loaded stable, deliberately disturbed, slow-drift,
   negative/zero, and sample-remove/replace traces.
4. Confirm record boundaries, exact field widths, unit text, decimal
   precision, update cadence, and encoding.
5. Determine the actual stable and unstable status-field values.
6. Capture unplug/replug and partial-read behavior without involving the
   printer application.
7. Convert a small representative transcript into immutable parser fixtures.
8. Record accepted parser and initial stability thresholds in this plan.

Validation:

- Probe tool `--help` and argument tests.
- Bench transcript review against the balance display.
- Confirm the tool does not import Controller, Model, Machine_FreeRTOS, or Qt.

Proceed criteria:

- Stable/unstable field mapping is known or explicitly classified as
  unavailable/advisory.
- Units and precision are confirmed.
- At least one fragmented serial-read fixture is retained.

Rollback:

- Remove the probe tool and fixtures. No application or hardware behavior has
  changed.

Characterization findings (2026-08-07):

- Fourteen captured runs passed byte count, chunk count, and full-stream
  SHA-256 verification. Raw reports remain under the ignored
  `tmp/veritas_balance_capture_20260807_110258` evidence root; the tracked
  fixture contains only small redacted excerpts and their source hashes.
- The BENFEI adapter enumerated as Prolific `067b:23a3` with the Linux
  `pl2303` driver. It changed from `/dev/ttyUSB1` to `/dev/ttyUSB0` after
  reconnect while its `/dev/serial/by-id` path remained stable, confirming
  that production selection must use the persistent path plus VID:PID rather
  than a `ttyUSB` number.
- In `PC cont` at 9600 8N1, output is ASCII with a 13-byte payload followed by
  `CR LF`, for 15 bytes on the wire. This resolves the manual's ambiguous
  record-length description. Captures contain split terminators, three-byte
  reads, a partial initial record, and a partial final record.
- The payload layout is: byte 0 sign (`space` for nonnegative, `-` for
  negative), bytes 1-8 right-aligned magnitude with two decimal places, byte
  9 space, bytes 10-11 `mg`, and byte 12 stability. Only `mg` was physically
  observed; a leading plus sign and other documented units remain unverified.
- Stability byte `S` means stable and space means unstable. The physical
  update cadence is approximately 0.1495 seconds (6.69 Hz), measured from the
  three-byte fragmented-read capture rather than the probe's coarser normal
  read timestamps.
- Operator markers in this campaign are advisory and were not used as exact
  event boundaries. Protocol and stability conclusions were derived from the
  mass/status stream.
- Retain the provisional policy: one-second ignore period, three-second
  minimum window, at least 10 samples, span at most 0.03 mg, absolute fitted
  slope at most 0.01 mg/s, and 30-second timeout. Require every sample in an
  accepted window to carry the verified `S` flag.
- Stable zero, stable loaded, and the 120-second natural-drift trace passed at
  the first eligible window, approximately four seconds after request start.
  Mass statistics rejected a 0.16 mg draft-shield disturbance even though the
  device continued to report `S`. Conversely, the `S` requirement rejected
  quiet removal/replacement intervals that passed the numeric thresholds
  before the balance declared stability. Both gates are therefore required.
- The unplug capture ended with the expected serial exception and retained
  valid data through a complete record boundary. Other captures provide the
  required partial-start and partial-tail fixtures.

Proceed criteria:

- Stable/unstable mapping verified: complete.
- Unit, precision, field layout, encoding, and cadence: complete for the
  observed `mg` configuration.
- Fragmented, malformed-prefix, negative, status-transition, partial-tail,
  and disconnect fixtures: complete.
- Initial combined stability policy accepted for Slice 2 implementation.

## Slice 2: Pure Protocol, Units, And Stability Contract

Status: `verified`

Goal:

Implement and exhaustively test serial framing, strict mg-only HPB parsing,
and stability decisions without opening a serial port.

Call path:

`fixture byte chunks -> CR/LF framer -> HPB parser -> BalanceReading -> stability detector -> StableMassResult`

Files implemented:

- `FreeRTOS-interface/BalanceProtocol.py`
- `tests/test_veritas_balance_protocol.py`
- this plan

Implementation steps:

1. Add immutable request, reading, policy, and result types.
2. Implement bounded CR/LF framing for partial, combined, empty, and oversized
   input.
3. Implement strict mg-only weighing-record parsing; reject all other units
   and leading plus signs.
4. Reject unsupported units, non-finite values, overload/status records, and
   malformed frames with typed reasons.
5. Implement a monotonic-time stability window with sample-count, duration,
   span, standard-deviation, and slope evidence.
6. Apply the device stability flag only according to the Slice 1 verified
   mapping.
7. Test timeout, cancellation, disturbance reset, drift, exact-threshold, and
   false-stable cases.
8. Freeze golden results for the retained HPB transcripts.

Validation:

`.\env\Scripts\python.exe -m pytest -q tests\test_veritas_balance_protocol.py tests\test_probe_veritas_balance.py`

`.\env\Scripts\python.exe -m py_compile FreeRTOS-interface\BalanceProtocol.py tests\test_veritas_balance_protocol.py`

Proceed criteria:

- Every retained valid record parses to the displayed mass in mg.
- Unstable and drifting traces do not produce a stable result.
- Pure tests require no Qt, serial device, camera, machine, or firmware.

Rollback:

- Remove the pure module and its tests.

Implementation findings (2026-08-07):

- Added a 256-byte bounded CR/LF framer with ordered frame/rejection events,
  oversized-frame discard/resynchronization, explicit incomplete-tail flush,
  and no transport dependency.
- Added an exact 13-byte ASCII parser. Only a leading space or minus sign,
  right-aligned two-decimal magnitude, `mg`, and verified `S`/space stability
  fields are accepted. Malformed device data returns typed rejection results
  rather than raising through a future worker.
- Mass values and all stability calculations use `Decimal`. A successful
  window returns its arithmetic mean quantized to 0.01 mg with
  `ROUND_HALF_EVEN` while retaining the unrounded mean, population standard
  deviation, span, and ordinary-least-squares slope as evidence.
- The detector implements the verified combined gate: one-second ignore,
  three-second window, at least 10 samples, span at most 0.03 mg, absolute
  slope at most 0.01 mg/s, and every retained sample marked `S`.
- Timeout is exclusive at 30 seconds. Cancellation, timeout, sample-limit
  error, and stable completion are typed terminal results; later calls return
  the same result and cannot change the outcome.
- All seven physical fixture excerpts replay through the framer/parser,
  including malformed start, split reads/terminators, negative values,
  status changes, partial tail, and disconnect boundary.
- Targeted validation passed: 50 tests. Python compilation passed. The full
  repository suite remains deferred to the final all-slices validation by
  operator direction.

Proceed criteria:

- Every retained valid physical record parses to its expected mg value:
  complete.
- Device-unstable and numerically drifting samples cannot produce success:
  complete.
- Exact threshold, quantized mean, timeout, cancellation, sample bound, and
  terminal-idempotency contracts: complete.
- Pure module import audit confirms no Qt, pyserial, MVC, machine, camera,
  firmware, application composition, or legacy balance dependency: complete.

## Slice 3: Nonblocking BalanceService

Status: `verified`

Goal:

Add explicit connection lifecycle and asynchronous stable-mass requests while
remaining disconnected from the application workflow.

Call path:

`test/future Controller -> BalanceService -> worker -> injected serial transport -> BalanceProtocol -> typed signals`

Files changed:

- new `FreeRTOS-interface/BalanceService.py`
- updated `FreeRTOS-interface/BalanceProtocol.py`
- new `tests/test_balance_service.py`
- updated `tests/test_veritas_balance_protocol.py`
- this plan

`requirements.txt` was not changed; the existing PySide6 and pyserial
dependencies are sufficient.

Implementation steps:

1. Define disconnected, connecting, streaming, and error connection states.
2. Add an injectable serial-transport factory and a production pyserial
   adapter configured for verified HPB framing.
3. Move all blocking reads into a dedicated worker lifecycle.
4. Support one identified stable-mass request with progress, success,
   timeout, cancellation, and error outcomes.
5. Ignore late worker events after cancellation, disconnect, or request
   replacement.
6. Make disconnect and close idempotent and verify the worker exits promptly.
7. Bound receive buffers, per-request samples, diagnostics, and retained raw
   frames.
8. Test repeated connect/request/disconnect/close cycles with fake transports.

Validation:

```text
.\env\Scripts\python.exe -m pytest -q tests\test_balance_service.py tests\test_veritas_balance_protocol.py tests\test_probe_veritas_balance.py
70 passed

.\env\Scripts\python.exe -m pytest -q tests\test_balance_service.py
17 passed

.\env\Scripts\python.exe -m py_compile FreeRTOS-interface\BalanceService.py FreeRTOS-interface\BalanceProtocol.py tests\test_balance_service.py tests\test_veritas_balance_protocol.py
passed
```

Verified findings:

- `BalanceService` is a narrow `QObject` facade with a receive-only worker
  object running in a dedicated `QThread`; serial open, read, and close calls
  execute off the caller/GUI thread.
- The production adapter is fixed at the verified 9600 baud, 8-N-1, 100 ms
  timeout, 64-byte read, no-flow-control configuration and imports pyserial
  only when the worker opens an explicitly supplied port.
- Connection state, command rejection, asynchronous errors, progress,
  readings, diagnostics, and request results use immutable typed payloads.
- Open or read failure leaves the service in `ERROR`; an explicit disconnect
  is required before reconnecting. No automatic reconnect is implemented.
- One active request is enforced. Cancellation completes before replacement,
  recently used identifiers are bounded to 64, and connection/request
  generations reject late worker events.
- Transport and unexpected service failures now produce terminal
  `TRANSPORT_ERROR` or `SERVICE_ERROR` results while preserving detector
  evidence and counts.
- Framing is bounded at 256 bytes, rejection history at 32 entries, worker
  commands at 8, request identifiers at 64, and stability samples at the
  Slice 2 limit of 512.
- The physical `stable_loaded` fixture was replayed through the worker and
  produced `1540.57 mg`; fragmented, malformed, empty, overflow, incomplete,
  disconnect, timeout, and repeated lifecycle cases also passed.
- QThread shutdown uses the bounded serial timeout and stop event. It never
  invokes forced thread termination, and a shutdown deadline failure retains
  the live worker reference and emits a typed error.
- Static import checks confirm the service is not referenced by application
  composition, MVC, machine/printer communication, simulation, firmware,
  camera, or legacy balance code. Slice 3 therefore cannot activate physical
  balance access from the application.

Proceed criteria:

- No serial read executes on the GUI/test caller thread: complete.
- Normal shutdown leaves no live worker or open fake transport: complete.
- Service errors are typed and do not raise through Qt callbacks: complete.
- Full repository pytest remains deferred to the final all-slices validation
  as previously agreed.

Rollback:

- Remove `BalanceService.py` and its tests; the app does not import it yet.

## Slice 4: Explicit Activation, Composition, And Connection UI

Status: `ready`

Goal:

Make the service available only through the three-gate experimental path,
without changing stream-capture behavior yet.

Call path:

`App flag -> ApplicationComposition -> optional BalanceService -> Controller experimental connection facade -> stream UI connection controls`

Files to touch:

- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/ApplicationComposition.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `tests/test_safe_application_construction.py`
- `tests/test_controller_port_classification.py`
- new or existing focused UI test file
- `README.md` or focused operator documentation

Implementation steps:

1. Parse the exact experimental environment flag into an immutable feature
   configuration.
2. Add an experimental balance factory separate from the legacy balance
   factory.
3. Construct and own the service only for enabled production current-profile
   sessions; keep simulation physically blocked.
4. Add explicitly named Controller list/connect/disconnect methods and reject
   the active MCU port.
5. Add hidden-by-default experimental connection controls beside stream
   capture.
6. Require port selection and a Connect click; never auto-open the remembered
   port.
7. Close the optional service deterministically from application component
   teardown.
8. Document the intentional Pi/Windows launch commands and disable command.

Validation:

`.\env\Scripts\python.exe -m pytest -q tests\test_safe_application_construction.py tests\test_controller_port_classification.py tests\test_stream_gravimetric_balance_integration.py`

Proceed criteria:

- With the flag absent, object construction and visible UI match the current
  application.
- With the flag enabled and a fake factory injected, connection controls work
  without opening real hardware.
- Simulation cannot enumerate or connect to the balance.
- Legacy balance construction tests remain unchanged and passing.

Rollback:

- Remove the flag/composition/controller/UI wiring. The isolated service and
  parser can remain unused.

## Slice 5: Balance-Backed Starting Mass And Manual Fallback

Status: `not_started`

Goal:

Capture and accept a stable starting mass before any existing stream sequence
or printer command begins.

Call path:

`stream UI opt-in -> Controller -> CalibrationManager awaiting start state -> Controller -> BalanceService -> Controller -> CalibrationManager -> existing stream start path`

Files to touch:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- new `tests/test_stream_gravimetric_balance_integration.py`
- `tests/test_stream_gravimetric_capture.py`
- relevant app-update/blocker tests if the new state is observable there

Implementation steps:

1. Add balance-source and request fields plus an awaiting-starting-mass state
   to the copied stream-capture state.
2. Split the current start method so validated manual starts preserve exact
   behavior while balance starts pause before session launch.
3. Issue one identified starting-mass request through the Controller.
4. Accept only matching successful results and copy their evidence into the
   stream state.
5. Continue through the existing gripper preamble and calibration queue with
   the accepted `starting_mass_mg`.
6. Add cancel, retry, and explicit `Use Manual Starting Mass` transitions.
7. Include the new pending state in busy/open/update blockers and duplicate
   start guards.
8. Test that timeout, disconnect, stale completion, and manual fallback never
   enqueue printer or motion commands prematurely.

Validation:

`.\env\Scripts\python.exe -m pytest -q tests\test_stream_gravimetric_balance_integration.py tests\test_stream_gravimetric_capture.py tests\test_app_update_request.py`

Manual/HIL check:

- With pressure/motion disabled or the machine disconnected, capture a stable
  starting mass and verify no machine command is sent before the result is
  explicitly accepted.

Rollback:

- Remove the balance-start branch and state fields. Manual start continues to
  call the existing method with the spin-box value.

## Slice 6: Ending Mass, Provenance, And Confirmed Save

Status: `not_started`

Goal:

Capture a stable ending mass after the existing loading move, show the
calculated difference, and save through the existing finalization path after
operator confirmation.

Call path:

`existing queue success -> existing loading move -> awaiting ending balance -> operator sample-ready action -> Controller -> BalanceService -> CalibrationManager -> existing finalize/CSV/restore/camera-return path`

Files to touch:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `tests/test_stream_gravimetric_balance_integration.py`
- `tests/test_stream_gravimetric_capture.py`
- stream metadata/sidecar tests that assert the additive evidence

Implementation steps:

1. Route loading-reached to an awaiting-ending-balance state only for a
   balance-backed session.
2. Require the operator's sample-ready/read action before issuing the request.
3. Accept only a matching ending-phase result and calculate a preview using
   the existing starting mass and printed count.
4. Populate the existing ending-mass control and show source, mass change, and
   stability evidence.
5. On confirmation, call the existing finalizer with the accepted ending mass.
6. Store additive balance evidence in the stream-capture sidecar while
   preserving existing CSV fields and formatting.
7. Add cancel, retry, and `Enter Ending Mass Manually` transitions that keep
   the already-completed print run open.
8. Test disconnect, timeout, negative/implausible delta warning, duplicate
   result, save failure, gripper restore, and camera-return behavior.

Validation:

`.\env\Scripts\python.exe -m pytest -q tests\test_stream_gravimetric_balance_integration.py tests\test_stream_gravimetric_capture.py tests\test_stream_analysis_summary.py`

Proceed criteria:

- The same two masses produce the same CSV row in manual and balance modes.
- Balance failure after printing never forces a repeated print run.
- Manual fallback can save the existing run.
- Restore and camera-return sequencing remains unchanged.

Rollback:

- Route loading-reached directly back to `awaiting_mass_entry` and ignore the
  additive balance evidence fields. Existing manual completion remains valid.

## Slice 7: Optional Session Auto-Save

Status: `not_started`

Goal:

Reduce repeated confirmation clicks for high-volume internal data collection
only after confirmation mode is proven on hardware.

Call path:

`explicit session-only auto-save opt-in -> accepted stable ending result -> preview validation -> existing finalizer`

Files to touch:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `tests/test_stream_gravimetric_balance_integration.py`
- operator documentation

Implementation steps:

1. Add a session-only auto-save checkbox visible only when all three
   experimental gates are active.
2. Default it off at every application startup and do not persist it.
3. Auto-save only a matching verified stable ending result with positive
   printed count and a finite mass change.
4. Require the explicit sample-ready action even in auto-save mode.
5. Refuse auto-save and show the confirmation dialog for negative,
   out-of-policy, warning, or incomplete results.
6. Provide a short visible cancel opportunity before finalization if practical
   without adding timing races.
7. Record that auto-save, rather than operator-confirmed save, was used.
8. Test every refusal and manual fallback branch.

Validation:

- Complete at least 20 confirmation-mode hardware runs first, with no wrong
  plateau, unit, or identity acceptance.
- Then complete at least 20 auto-save runs and compare display, sidecar, and
  CSV results.

Proceed criteria:

- Confirmation-mode evidence demonstrates the sample-ready action and
  stability policy reliably select the intended loaded plateau.

Rollback:

- Hide/remove the auto-save checkbox and always require confirmation. Slices
  1-6 remain usable.

## Slice 8: Pi Deployment, Resilience, And Full Validation

Status: `not_started`

Goal:

Validate the intentionally activated workflow on the Raspberry Pi and finish
operator/developer handoff documentation.

Call path:

`Pi launch flag -> explicit USB serial connection -> repeated starting/ending captures -> existing stream artifacts -> app close/restart/manual fallback`

Files to touch:

- `README.md` or focused balance operator documentation
- tests discovered during resilience validation
- `docs/veritas_balance_integration_plan.md` status/evidence updates

Implementation steps:

1. Document adapter/cable requirements, balance menu settings, Pi permissions,
   flag activation, connection, fallback, and disable procedure.
2. Prefer a stable `/dev/serial/by-id/...` path when the adapter exposes one;
   document a udev rule only if required and reviewed on the target Pi.
3. Verify simultaneous MCU and balance attachment cannot cross-connect ports.
4. Exercise unplug/replug before start, during starting capture, during the
   print sequence, and during ending capture.
5. Exercise application close and restart with connected, disconnected, and
   pending-request states.
6. Compare at least 20 balance-assisted records with the displayed HPB values
   and spot-check manual transcription.
7. Run focused and full Python suites and inspect sidecar/CSV compatibility.
8. Record limitations, accepted stability policy, adapter identity, and
   rollback instructions.

Validation:

Focused:

`.\env\Scripts\python.exe -m pytest -q tests\test_veritas_balance_protocol.py tests\test_balance_service.py tests\test_stream_gravimetric_balance_integration.py tests\test_stream_gravimetric_capture.py tests\test_safe_application_construction.py tests\test_controller_port_classification.py tests\test_app_update_request.py`

Full Python suite:

`.\env\Scripts\python.exe -m pytest -q`

No firmware check is required unless implementation unexpectedly touches
`firmware/`. If that occurs, stop, read `firmware/AGENTS.md`, revise this plan,
and obtain explicit approval for the scope expansion before editing firmware.

Rollback:

- Remove the experimental launch flag from the Pi launcher and restart the
  app. This immediately returns the UI and runtime to manual-only behavior.

## Hardware Validation Matrix

| Scenario | Required result |
| --- | --- |
| Feature flag absent | No service construction, port access, or balance UI |
| Feature flag present, no connection | Experimental controls visible; manual workflow unchanged |
| Wrong/MCU port selected | Connection rejected without disturbing the MCU |
| Valid stable starting load | Accepted once; no printer command precedes acceptance |
| Disturbed or drifting load | Stability wait continues or times out; no false acceptance |
| Disconnect during starting request | Manual start/retry/cancel available; no printer action |
| Disconnect during print sequence | Printing follows existing behavior; ending mass falls back to manual |
| Empty balance stable at ending | Not accepted before explicit sample-ready action |
| Disconnect during ending request | Existing run remains open for manual ending mass |
| Late/stale result | Ignored by request/session/phase identity |
| Manual and balance same masses | Identical CSV mass change and mass-per-print |
| App close with active request | Worker and serial port close cleanly |
| App restart | Feature and use checkbox reset unless flag is deliberately supplied again |

## Risks And Mitigations

### Serial Port Collision

Risk: a generic USB adapter may be mistaken for the MCU or its Linux device
name may change.

Mitigation: explicit selection, reject the active MCU port, show USB metadata,
prefer `/dev/serial/by-id`, never auto-connect, and test both devices attached.

### GUI Freeze Or Shutdown Hang

Risk: serial reads on the Qt thread can block the application.

Mitigation: dedicated worker, bounded timeouts/buffers, idempotent close, and
worker-lifecycle tests. Do not copy the legacy QTimer/readline design.

### Unit Or Format Error

Risk: the balance normally reports grams while the workflow labels and stores
milligrams.

Mitigation: strict unit parsing, explicit conversion, raw/display fixture
comparison, no unitless regex acceptance, and provenance in the sidecar.

### False Stability

Risk: an empty pan, slowly evaporating load, environmental drift, or too-short
window may be accepted.

Mitigation: sample-ready action, ignore interval, minimum time and sample
count, span plus slope checks, verified device flag when available, hardware
traces, and manual confirmation before initial save behavior.

### Stale Or Duplicate Completion

Risk: a late result from a cancelled request could be applied to another phase
or run.

Mitigation: unique request id plus stream session id plus phase identity on
every progress/result event; one active request; reject every mismatch.

### Balance Failure After Printing

Risk: losing the balance could strand the completed stream run or encourage
an accidental repeat.

Mitigation: ending-mass manual fallback operates on the same open session and
continues through the existing restore/return path.

### Regression To Normal Or Legacy Users

Risk: broadening current-profile balance capability could expose or alter
unrelated workflows.

Mitigation: exact environment flag, separate service/factory/controller API,
stream-local UI, feature-off equivalence tests, and no changes to the legacy
balance class.

### Hardware Electrical Risk

Risk: direct RS-232-to-GPIO connection can expose the Pi to incompatible
voltage levels.

Mitigation: require a proper RS-232-to-USB adapter and document that DB9 must
never connect directly to GPIO UART.

## Definition Of Done

- The feature is invisible and inactive without the exact experimental flag.
- No serial balance port is opened without an explicit Connect action.
- Manual entry remains the default, is always reachable, and produces the
  same artifacts as before.
- Valid HPB records are framed, parsed, and converted to mg with golden tests.
- Stability behavior is time-based, evidence-producing, and validated on the
  actual balance.
- Starting mass is accepted before any stream hardware command begins.
- Ending-mass failure can fall back without repeating the print sequence.
- Existing CSV columns and calculations are unchanged.
- Additive sidecar evidence identifies source, request, policy, and quality.
- Simulation cannot access the physical balance.
- The current and legacy profile tests remain passing.
- Focused tests and the full Python suite pass.
- At least 20 repeated hardware runs match the displayed balance values and
  show no wrong-plateau or stale-result acceptance.
- Pi activation, disable, troubleshooting, and rollback instructions are
  documented.
- No firmware or printer-protocol file is changed.

## Global Rollback Plan

Operational rollback is immediate and does not require a code revert:

1. Disconnect the balance in the experimental controls if the app is open.
2. Remove `LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE=1` from the launch environment.
3. Restart the application.
4. Continue using the existing manual starting and ending mass controls.

Code rollback should proceed in reverse slice order. Because the integration
is additive and the existing manual path remains intact, removing composition
and UI wiring is sufficient to make the parser/service inert. No firmware
rollback, printer protocol rollback, machine recalibration, or experiment
schema migration should be required.
