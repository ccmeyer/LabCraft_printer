# LabCraft Printer

This repository contains the LabCraft Printer project.

## Prerequisites

Before you can run the LabCraft Printer project, make sure you have the following software installed:

- [Python](https://www.python.org/downloads/): Python is a programming language used by the LabCraft Printer project.
- [Visual Studio Code (VSCode)](https://code.visualstudio.com/): VSCode is a lightweight code editor that provides a great development environment for Python.
- [PlatformIO](https://platformio.org/): PlatformIO is an open-source ecosystem for IoT development with cross-platform build system, library manager, and full support for Espressif ESP8266/ESP32 development boards. 

## Getting Started - Python

To get started with the LabCraft Printer project, follow these steps:

1. Clone the Git repository to your local machine:

    ```bash
    git clone https://github.com/ccmeyer/LabCraft_printer
    ```

2. Open the project folder in VSCode:

    ```bash
    cd LabCraft_printer
    ```

3. Create a virtual environment for the project:

    ```bash
    python -m venv venv
    ```

4. Activate the virtual environment:

    - On Windows:

      ```bash
      venv\Scripts\activate
      ```

    - On macOS and Linux:

      ```bash
      source venv/bin/activate
      ```

5. Install the project dependencies:

    ```bash
    pip install -r requirements.txt
    ```

## Run Python Tests

On this Windows checkout, use the repo virtual environment directly:

```bash
.\env\Scripts\python.exe -m pytest -q
```

Avoid `py -m pytest -q` here unless the Windows Python launcher has been verified; in some agent shells it fails with `No installed Python found!`.
The full Python suite commonly takes 3-8 minutes on Windows and in agent sandboxes.
Automation should use a process timeout of at least 15 minutes (`900000` ms) to avoid killing a valid run and paying collection/startup cost again.
Pytest is configured in `pytest.ini` to collect from `tests/`, and its optional cache provider is disabled to avoid `.pytest_cache` permission warnings in OneDrive/sandboxed runs. That only disables pytest cache conveniences such as `--last-failed`; it does not affect normal validation.
Slow, insulated offline analysis-pipeline tests are skipped by default. Run them when changing the plate-reader analysis pipeline:

```bash
.\env\Scripts\python.exe -m pytest -q --run-analysis-pipeline tests\test_plate_reader_analysis.py
```

## Safe Application Construction

`ApplicationComposition` exposes one programmatic composition seam for the real `Model`,
`Controller`, and `MainWindow`. Production startup continues through
`FreeRTOS-interface/App.py`; simulation uses the separate interactive and
verification launchers described below.

`ApplicationComposition.production_dependencies()` selects the existing
Machine, serial, camera, log-reader, and legacy balance implementations.
`simulation_dependencies(run_root, machine_factory=...)` instead requires a
caller-supplied safe machine factory and creates `config/`, `experiments/`, and
`calibration-memory/` beneath the supplied run root. It never falls back to
production hardware if construction fails.

Simulation windows show a persistent
`SIMULATION — NO HARDWARE CONNECTED` banner. The production connection,
firmware/DFU, MCU reset, physical camera, machine qualification/calibration,
balance, and application update controls remain visible but disabled. The
dedicated simulator control accepts only `SIMULATED`. The Controller rejects
direct physical calls before port enumeration, worker construction, or
peripheral access.

Prerequisites for offscreen construction tests:

- the repository `env` virtual environment with real PySide6;
- `QT_QPA_PLATFORM=offscreen`;
- a fresh temporary run root;
- an explicit construction-safe machine factory.

Slice 4 provides the repository-owned, protocol-free implementation. It must
still be selected explicitly:

```python
from ApplicationComposition import (
    build_application_components,
    simulation_dependencies,
)
from hardware.profile import CURRENT_PROFILE
from simulation import (
    SIMULATED_PORT,
    SimulationConfig,
    SimulationTimingPolicy,
    make_simulated_machine_factory,
)

config = SimulationConfig(
    timing=SimulationTimingPolicy(speed_multiplier=100.0),
)
dependencies = simulation_dependencies(
    temporary_run_root,
    machine_factory=make_simulated_machine_factory(config),
)
components = build_application_components(CURRENT_PROFILE, dependencies)
components.machine.connect_board(SIMULATED_PORT)
```

Create a `QApplication` before building the components and drive its event loop
until the asynchronous connection and command callbacks complete. The
simulator uses owned single-shot Qt timers: requested waits and calculated
dispense durations advance simulated time, while `speed_multiplier` reduces
their wall-clock delay. Even accelerated commands retain at least one Qt event
loop turn.

The initial simulator supports connection through the literal `SIMULATED`
sentinel, motor and homing state, absolute motion, print/refuel targets and
regulation, axis acceleration/speed, print profile, waits, dispensing,
gripper state, pause/resume, pause-after, clear, disconnect, and deterministic
fault plans. Relative motion, raw protocol frames, serial transports, physical
cameras, calibration imaging, balance, GPIO/DFU, firmware updates, and physical
motion/pressure dynamics are intentionally unsupported and fail visibly.

This is an application-contract simulator. Passing its tests does not verify
firmware behavior, collision safety, physical motion, pressure response,
camera analysis, or droplet quality. Synthetic calibration and physical
response modeling remain outside the Milestone 1 launcher.

Run the focused construction and safety tests:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulated_machine.py `
  tests\test_safe_application_construction.py `
  tests\test_view_window_icon_contract.py `
  tests\test_local_config.py `
  tests\test_mainwindow_closeevent.py
```

Do not use this programmatic seam as a production launcher and do not pass a
factory that can construct real hardware into `simulation_dependencies`.
Application-owned configuration and experiment writes are isolated, but the
API cannot prove that an arbitrary third-party machine factory is safe.

### Interactive hardware-isolated simulator

Milestone 1 adds a dedicated launcher for manually exercising the real
application UI against `SimulatedMachine`:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py
```

The window shows both persistent simulation identity surfaces. Connect only
through the non-closable `SIMULATOR CONTROL` dock. The production connection
widget remains disabled and does not enumerate ports.

The normal UI may then be used to enable/home, regulate pressure, move,
operate the gripper, create or edit experiments, and disconnect. These are
application-contract simulations only; they do not validate collision safety,
pressure response, camera output, firmware, or physical motion.

Fresh sessions use a unique root under:

```text
%LOCALAPPDATA%\LabCraft\SIL\interactive-sessions\
```

A clean fresh session is removed on close. Retain it for inspection:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session
```

Reopen a retained root:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --session-root "C:\path\printed-by-the-previous-run"
```

The session ID is preserved and a new application-session record is added.
Open a retained experiment manually through the normal Experiment Editor.
The launcher does not auto-load or mutate an experiment.

Choose deterministic timing when useful:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --seed 1 `
  --speed-multiplier 2
```

The seed is instance-local and does not change Python's global random state.
The speed multiplier changes only simulator wall-clock acceleration.

Each retained root contains `session.json`, `logs\`, `artifacts\`, `config\`,
`experiments\`, and `calibration-memory\`. Session metadata and launcher logs
remain outside experiment directories. Application roots are passed directly
to the real Model, so normal writers retain production file names and formats.

Milestone 2 adds simulation-owned, read-only state evidence. Use **Show State
Inspector** in `SIMULATOR CONTROL` to open the hidden-by-default
`SIL STATE INSPECTOR - READ ONLY` dock. **Export State Snapshot** records an
explicit cross-layer snapshot without changing application state. Each launch
uses its own contained artifact directory:

```text
artifacts\state\<application_session_id>\
  events.jsonl
  latest_snapshot.json
  terminal_snapshot.json
```

The JSONL remains complete while the live inspector retains a bounded 512-event
tail. Reopening a retained root creates a new application-session directory and
does not modify the prior trace. The schema contract is documented in
`docs/sil_state_trace_schema_v1.md`. If recorder or snapshot persistence fails,
the observer stops, the root is retained and marked failed, and the ambiguous
write is not retried.

Milestone 3 adds a pure deterministic synthetic-calibration developer API in
`tools.sil`. Its provider remains independent of the interactive launcher and
calibration UI. A caller constructs `CalibrationGenerationRequestV1`, selects one of
the eight versioned profiles, and calls
`SyntheticCalibrationProvider.generate(request)`. The returned request and
result fingerprints, virtual timestamp, calibration values, provenance, and
limitations are byte-reproducible for the same request and seed.

Valid results expose existing-compatible summary-row and calibration-step
adapters. Negative profiles remain inspectable, but application validation and
both adapters reject them before injection. The provider never writes files or
uses Qt, Model, Controller, cameras, balances, serial ports, hardware factories,
or process-global random state. It provides no evidence of camera processing,
physical ejection, volume accuracy, pressure response, refuel behavior,
collision safety, firmware, or protocol behavior. The exact schema is
documented in `docs/sil_calibration_schema_v1.md`.

Milestone 4A is complete. It connects the valid `nominal_droplet` profile to the interactive
simulator without enabling the production camera/calibration launcher. After
connecting, homing, regulating print pressure, finalizing an experiment, and
loading its exact virtual droplet head, select **Nominal droplet** and use
**Generate / Open Synthetic Calibration Result** in `SIMULATOR CONTROL`. A
camera-free presentation of the real
calibration dialog shows an amber **Synthetic** row and an explicit no-physical-
evidence banner. Select the row, inspect the normal design-impact preview, and
use the existing Apply control.

The candidate remains in memory only. Apply continues through the real Model
calibration-revision path and normal Controller-driven simulated print
settings. Canonical request/result evidence is retained outside experiment
directories under:

```text
artifacts\synthetic-calibration\<application_session_id>\<result_fingerprint>\
  request.json
  result.json
```

The presentation mode never starts a camera/read stream, runs a physical
calibration process, enables a print profile, or writes a synthetic run into
`calibration.json`. It does not validate camera processing, physical ejection,
volume accuracy, pressure response, collision safety, firmware, or protocol
behavior.

Milestone 4B is complete. Its original simulation-only surface added
**Droplet → stream** and
**Nominal stream** results. The retained schema-v1 droplet-to-stream profile
requires a finalized
single-stock droplet context above 20 nL and below 40 nL; the standard visible
exercise uses 25 nL and deterministically reaches the 40 nL stream boundary.
The presentation shows the requested/applied mode pair and stream evidence
warning, while Apply continues through the real mode-switch confirmation,
execution-plan revision, printer-head mode, and Controller settings paths.

Applying stream calibration leaves the existing manual-refuel preflight in a
required state. After regulating both print and refuel pressure, use the
clearly labeled **Simulated manual-refuel check — no physical evidence** group
to record Passed, Deferred, or Failed. These controls call the existing
Controller/Model recording API with source
`sil_simulated_manual_refuel_check`, a virtual five-droplet trial, and canonical
seed/provider provenance in the existing notes field. Bypass is intentionally
not exposed. Required, deferred, failed, stale, or settings-mismatched evidence
continues to block stream printing; only a matching pass clears that preflight.
The operator manual-refuel dialog is unchanged, and no physical refuel evidence
is claimed.

The visible Windows fresh/reload gate completed on 2026-08-03. It applied a
25 nL droplet-to-stream result, exercised deferred/failed/passed refuel states,
applied a second nominal-stream result that invalidated the prior pass, recorded
a new matching pass, and reloaded the retained authoritative revision through
Experiment Editor without printing.

Milestone 4C is complete. Its consolidated focused automated gate and visible
Windows fresh/reload validation passed. In the canonical simulator, use the
normal application workflow instead of dock workflow buttons:

- the normal connection surface exposes the single read-only `SIMULATED`
  target and its Connect/Disconnect button delegates to `SimulationSession`;
- **Calibrate Printer head** opens the real three-panel calibration dialog in
  an explicitly synthetic, camera-free mode;
- the Droplet and Stream tabs retain their real **Calibrate All**, summary,
  preview, mode-switch confirmation, and Apply behavior;
- applied synthetic rows are reconstructed read-only from matching canonical
  artifacts and `execution_calibrations.json`, including after retained-root
  reload; synthetic evidence is never inserted into physical `calibration.json`;
- finalized experiments preview and Apply against the authoritative execution
  plan rather than requiring the creation-session `plans_per_option` cache;
- all physical acquisition, camera, movement, optics, debug, and individual
  calibration controls remain visible but disabled;
- the normal Manual Refuel Check window runs its existing commands against the
  simulated machine and records the operator's Passed, Failed, or Unclear
  judgment with the actual trial metadata;
- Refuel Only, Print Only, and relative refuel-pressure controls traverse the
  normal Controller and deterministic simulated command queue;
- choosing No in the post-Apply prompt records an explicit zero-trial deferred
  outcome through the same simulation evidence bridge.

The new additive `stream_to_droplet` profile lets the Droplet tab transition a
stream stock back below 40 nL. Existing schema, profile, and provider versions
are unchanged, so all earlier canonical request/result fingerprints remain
stable. `SIMULATOR CONTROL — NO HARDWARE` now contains diagnostics, the state
inspector launcher, and snapshot export only. It contains no connection,
calibration, or refuel workflow buttons.

The completed Milestone 4C low-volume transition correction lets the normal
Stream-tab **Calibrate All** action accept any valid
droplet source volume from 1 nL up to (but not including) 40 nL, including the
normal 9 nL default. An additive schema-v2 request records the authoritative
source volume and an exact 40 nL stream target. Schema v1 remains readable and
byte-stable, and v1/v2 evidence may coexist in retained history. The dialog
shows the directional readiness text before generation; preview, confirmation,
Apply, authoritative persistence, and manual-refuel preflight remain the
existing application paths.

Milestone 4D and its generated-history correction are complete. Focused
automated validation and the visible Windows/retained-root gates passed. New
synthetic application results are pulse-aware:
droplet mode maps 1300–1800 us linearly from 9–18 nL, while stream mode maps
2500–10000 us linearly from 60–250 nL. Pulse widths outside the target mode's
inclusive range cannot generate a result. **Calibrate All** instead opens the
normal settings-check surface, where a compatible configured print profile can
be selected and applied through Controller and the simulated command queue. An
already-valid pulse width is preserved.

The response is deterministic and explicitly non-empirical. Pressure is
retained in provenance but does not change volume. Schema-v3 details are in
`docs/sil_calibration_schema_v3.md`. V1/v2 artifacts remain readable and
fingerprint-stable, but historical pre-v3 synthetic rows are read-only for new
application because they lack pulse-response provenance. Production
calibration preflight remains unchanged.

Each distinct canonical synthetic result now remains in the real calibration
table as `Pending Apply`, `Generated — Not Applied`, or `Applied History`.
Generating another profile does not replace an earlier unapplied result, and
identical deterministic fingerprints occupy one row. Schema-v3 generated rows
rehydrate from their retained canonical request/result pair and may be applied
later only when their exact head, stock, requested mode, and normal idle/queue
guards still match. The execution-calibration sidecar and SIL snapshots
continue to count only authoritative applied records.

The closing retained root and exact artifacts, fingerprints, snapshots, and
limitations are recorded in
`docs/sil_interactive_simulation_milestone_4d_completion_record.md`.

Milestone 5 manual full-lifecycle characterization is complete. Three fresh,
retained Windows journeys used only normal application controls and existing
authoritative writers:

- one 24-well, one-stock droplet execution, including prepared reload,
  `Stop After Well`, process restart from `resume_ready`, nonrepeating resume,
  completion, and terminal reload;
- one 24-well, two-stock droplet execution with a real rack head exchange and
  exact 24 + 24 completion;
- one 24-well mixed droplet/stream execution with 9 nL/1300 us droplet and
  60 nL/2500 us stream calibrations, a real five-droplet manual-refuel trial,
  Passed judgment, and exact 24 + 24 completion.

Every qualifying terminal and retained-root snapshot reconciled with zero
mismatches. Completed reloads preserved plan IDs/revisions, calibration and
refuel records, progress, and clean checkpoints without relying on prior
process memory. The focused defects exposed during characterization were
corrected and separately tested: zero-target fill omission, exact-stock
selection in multi-stock synthetic calibration, and acceptance of the
application's own manual-refuel sidecar write by the active authoritative
runtime. The full suite was intentionally not rerun; Milestone 5 used the
approved focused gates documented in
`docs/sil_interactive_simulation_milestone_5_completion_record.md`.

Milestone 5 qualifies the application-contract simulator for shared automation
harness planning. It does not validate physical fluid behavior, cameras,
balances, collision safety, firmware, protocol, or hardware performance.

Milestone 6 is complete. The deterministic `virtual_print_array_24_v1` smoke
now runs as a short composition over a shared `SimulationSession` harness and
surface-specific QTest drivers. Connection, motor enable/home, experiment
creation/finalization, print settings, rack volume/confirm/load, pressure
regulation, normal synthetic calibration generation/selection/Apply, and
array start all use visible, enabled normal Qt controls. Every action records
its actual `ui`, `controller`, `model`, `simulator`, or `harness` interaction
surface; successful normal-UI coverage fails if a required operator action is
missing or labeled with another surface.

Run the migrated smoke offscreen or visibly:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_24_v1 `
  --output-root verification_reports\milestone6 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_24_v1 `
  --output-root verification_reports\milestone6-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 300
```

The report directory retains `report.json`, summary, JSONL events, screenshots,
separate action/assertion ledgers, and a SHA-256 evidence manifest. The report
also records an exact replay command and links the retained isolated session
root under `%TEMP%\LabCraft\SIL\composed-sessions`. Session roots intentionally
remain outside the repository and production data roots. Unexpected dialogs,
deadlines, unhealthy recorder evidence, incomplete assertions, and ambiguous
cleanup fail closed with retained failure evidence.

Replay compares fixture hash, seed, action order/surfaces, assertion decisions,
calibration values, completion order, and terminal state. UUIDs, timestamps,
durations, generated plan/head/run identities, and their identity-bearing
hashes are expected to differ. Other workflow families retain their legacy
runners until Milestone 7 parity gates; this milestone adds no Pi, protocol,
firmware, hardware, performance, or production fault-injection behavior.

Milestone 7 Slice 1 also migrates
`experiment_editor_create_finalize_v1` to the shared harness. It creates and
finalizes the tracked A1/A2 design through the normal editor controls, validates
the revision-1 prepared bundle, and reopens it through **Experiment Editor →
Load Design…** and Qt's folder dialog. Reload intentionally leaves the plan
`PREPARED`, eligibility `ready_to_start`, the authoritative runtime inactive,
and the resume sidecar absent; it does not use the legacy verification-only
direct Model activation.

Run the composed editor lifecycle offscreen or visibly:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_create_finalize_v1 `
  --output-root verification_reports\milestone7-slice1 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 60

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_create_finalize_v1 `
  --output-root verification_reports\milestone7-slice1-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 120
```

The create/finalize and prepared-load actions must report `ui`; assertions,
screenshots, reporting, and teardown report `harness`. The legacy direct runner
remains temporarily callable as a parity oracle, while prepared
rename/refinalize and post-start lock/copy remain on the legacy editor runner.

Milestone 7 Slice 2 migrates `print_array_multi_stock_24x2_v1` to the same
composed harness. The normal Experiment Editor creates both A1-A24 reagent
rows; normal rack controls set volume, Confirm, Load, and Unload each head;
the normal calibration dialog applies 9 nL at 1300 us and 18 nL at 1800 us;
and the normal array control starts both passes. Only deterministic fixture
head-ID binding is a recorded `model` action, so it is excluded from UI
coverage. The schema-v4 recipe uses 3.0x and 1.5x stocks to retain exactly one
dispense per stock and a 27 nL final reaction volume.

Run the Slice 2 journey offscreen or visibly, then execute the exact
`run.replay_command` retained in `report.json`:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_multi_stock_24x2_v1 `
  --output-root verification_reports\milestone7-slice2 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_multi_stock_24x2_v1 `
  --output-root verification_reports\milestone7-slice2-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 300
```

The first pass must settle `ACTIVE`, idle, drained, and intent-clean before
the first head is returned. The second must settle `COMPLETED` with 48 exact
stock/well intent lifecycles before the final head is returned. Both retained
heads, all three expected dialogs, action/assertion ledgers, observer evidence,
screenshots, hashes, seed, and replay command remain inspectable.
The full Python suite is deferred until the final Milestone 7 validation; each
slice uses its documented targeted gates.

Milestone 7 Slice 2.5 consolidates the three composed runners before another
workflow is migrated. `JourneyDefinition`, `JourneyRuntime`, `SemanticStep`,
and `JourneyExecutor` now own generic identity, execution, failure, restoration,
artifact, report, and teardown behavior. Typed phase specifications own machine
startup, editor preparation, and ordered stock/head passes. Registry dispatch
calls one generic composed runner instead of branching on each scenario ID.

The compatibility runners are now two-line delegates. The smoke, editor, and
multi-stock journey bodies are 35, 50, and 56 lines respectively; changing
validated stock values or stock order produces a new normalized plan without a
new runner. Active parameter matrices and seeded sequence generation remain
future work, but this typed boundary is their intended input rather than
another monolithic workflow function.

Run the Slice 2.5 focused composition and lifecycle gates:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_multi_stock_composed.py
```

On Windows, if pytest's reused default temporary root reports an access error,
select a fresh `--basetemp` below `%TEMP%\LabCraft`; do not place it inside the
repository because `SimulationSession` correctly rejects roots overlapping
repository or production data.

Milestone 7 Slice 3 migrates
`experiment_editor_prestart_rename_refinalize_v1` onto that composition layer.
The journey creates the initial A1/A2 droplet design, then reopens the untouched
prepared design and drives rename, six-well selection, 120 nL volumes, stream
mode, 0.5x/1.0x targets, regeneration, and refinalization through normal Qt
controls. It finally reloads the renamed directory through **Experiment Editor
→ Load Design…** and Qt's folder dialog. It remains disconnected throughout
and does not execute print commands.

`PreparedEditorRevisionSpec` holds the varying names, wells, modes, targets,
and volumes. `ExperimentEditorDriver` reuses the existing bounded modal QTest
mechanics through the harness action runner, while one read-only assertion
family owns the authoritative plan/archive/progress/key/audit checks. The
scenario body is 76 lines and contains no QTest loop, report writer, or cleanup
path. Ordinary prepared-design values therefore do not require another
runner. Active matrices and seeded action-order exploration remain later work.

Run the Slice 3 focused gates:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice3-unit" `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice3-lifecycle" `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_editor_refinalize_composed.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_prestart_rename_refinalize_v1 `
  --output-root verification_reports\milestone7-slice3-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

The emitted replay command must reproduce the fixture hash, seed, 23 ordered
actions and surfaces, ten passing assertions, ten screenshot names, prepared
terminal state, and pass classification. Generated IDs, paths, timestamps,
durations, and identity-bearing hashes are intentionally nondeterministic. The
full Python suite remains deferred until the final Milestone 7 validation.

Milestone 7 Slice 3.5 consolidates the evidence and reporting added by the
editor migrations. `authoritative_evidence.py` captures one immutable,
JSON-safe view of design, plan/history, progress, resume, calibration, runtime
assignments, key files, audit rows, and directory hashes without activating or
repairing execution. The composed editor journeys, legacy authoritative reload
validator, and legacy post-start lock/copy validator use the same readers and
inventory contracts. `editor_reporting.py` supplies the common zero-print
editor payload and leaves each journey adapter at 12 lines.

Action-order assertions validate an explicit complete ledger window, including
interleaved harness milestones, while retaining the existing UI-only evidence
projection. Slice 3.5 adds no workflow, fixture, registry entry, capability
claim, UI action, page-driver operation, or production behavior. Run its
targeted gates with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_editor_reporting.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_editor_refinalize_composed.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py
```

The complete Python suite remains deferred until the final Milestone 7 gate.

Milestone 7 Slice 4 migrates `print_array_soft_stop_resume_24_v1` to the
generic composed runner. The normal editor, machine, rack, calibration, and
array controls create the A1-A24 design, start printing, request `Stop After
Well` at completion 6, prove the paused empty checkpoint and 250 ms
quiescence window, and confirm `Resume Print Array` before completing all 24
wells. `ArrayDriver` owns the bounded QTest start/stop/resume mechanics;
`SoftStopResumeSpec` and the stop-boundary/resume phases are reusable by the
later authoritative-reload journey. The legacy runner remains directly
callable only as a parity oracle and for the still-unmigrated reload workflow.

Run the composed lifecycle offscreen or visibly, then execute the exact replay
command from `report.json`:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_soft_stop_resume_24_v1 `
  --output-root verification_reports\milestone7-slice4 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 60

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_soft_stop_resume_24_v1 `
  --output-root verification_reports\milestone7-slice4-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

The report retains eight screenshots (`editor_opened`, `generated`, `ready`,
`printing`, `stop_requested`, `stopped`, `resumed`, and `completed`), exact UI
action surfaces, paused and terminal oracle evidence, action/assertion
ledgers, hashes, seed, replay command, and clean teardown. A direct run with
`--speed-multiplier 1000` is useful for automation; use a smaller multiplier
when visually inspecting transitions. If several Qt lifecycle tests share one
process and a parity node is transiently incomplete, rerun that exact node in
a fresh process/root before diagnosing the workflow. The full Python suite is
still deferred until the final Milestone 7 validation.

The Slice 4 migration is complete. Its touched runtime growth was net 598
physical lines against the planned 450-line consolidation gate; the variance
was explicitly accepted because most of the added code is reusable
page-driver, phase, observer, and assertion infrastructure.

Milestone 7 Slice 5 migrates `authoritative_reload_resume_24_v1` to generic
composed dispatch. It creates and partially prints A1-A24 through normal UI
controls, proves the soft-stop boundary, cleanly closes the first application
composition, opens a fresh composition on the same retained SIL root, loads
and activates the authoritative execution through Experiment Editor, reuses
the persisted calibration, and resumes without replaying completed work. The
legacy path remains directly callable as the fixed parity oracle.

Run the composed lifecycle offscreen or visibly, then execute the exact replay
command emitted in `report.json`:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario authoritative_reload_resume_24_v1 `
  --output-root verification_reports\milestone7-slice5 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 60

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario authoritative_reload_resume_24_v1 `
  --output-root verification_reports\milestone7-slice5-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

The report retains eight cross-session screenshots, both application-session
recorder roots, exact UI/harness action surfaces, paused/load/activation/
resume/terminal evidence, hashes, seed, and replay command. A visible run and
its exact replay passed on 2026-08-06 with identical stable projections. If a
nested editor or folder dialog is unexpected, mislabeled, or left open, the
journey fails closed and retains its traceback, ledgers, manifest, available
recorders, and failure screenshot. The complete Python suite remains deferred
until the final Milestone 7 validation.

The final retained Windows evidence is:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260805T124515193488Z-ebd5d6342b4d
```

Using normal application controls, it applied an exact 9 nL Droplet to 40 nL
Stream transition, completed a real five-droplet manual-refuel trial while the
post-Apply dialog remained open, recorded Passed, exported a reconciled
snapshot, and closed cleanly. Reopening the root through Experiment Editor
restored stream mode, 40 nL, plan revision 3, the synthetic history row, and
the matching Passed refuel record. Both application sessions completed with
healthy closed recorders and zero terminal reconciliation mismatches.

Retain and reopen the session to inspect the authoritative result:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session --seed 1
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --session-root "C:\absolute\retained\session-root"
```

Load the experiment through the existing Experiment Editor after reopening;
the launcher never auto-loads an experiment.

Run its focused contract tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_synthetic_calibration.py
```

Run the Milestone 4A focused tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_calibration_ui.py `
  tests\test_sil_calibration_dialog_driver.py `
  tests\system\test_sil_synthetic_calibration_lifecycle.py
```

Run the Milestone 4B focused tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_manual_refuel.py `
  tests\test_sil_calibration_ui.py `
  tests\test_sil_calibration_dialog_driver.py `
  tests\test_simulator_control.py `
  tests\system\test_sil_stream_calibration_lifecycle.py
```

Run the Milestone 4C focused tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_connection_widget_disconnect_state.py `
  tests\test_pressure_plotbox_buttons.py `
  tests\test_safe_application_construction.py `
  tests\test_simulation_session.py `
  tests\test_simulator_control.py `
  tests\test_sil_synthetic_calibration.py `
  tests\test_sil_calibration_application.py `
  tests\test_sil_calibration_ui.py `
  tests\test_droplet_imaging_summary_table.py `
  tests\test_manual_refuel_check_dialog.py `
  tests\test_sil_manual_refuel.py `
  tests\test_sil_calibration_dialog_driver.py `
  tests\test_simulated_machine.py `
  tests\test_sil_state_projection.py `
  tests\test_authoritative_execution_load.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py
```

This milestone intentionally uses the focused affected suite rather than the
full pytest suite. If an implementation failure identifies another direct call
path, add only that path's test module to the focused command.

Run the Milestone 4D focused tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_ejection_response.py `
  tests\test_sil_synthetic_calibration.py `
  tests\test_sil_calibration_application.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_sil_calibration_ui.py `
  tests\test_sil_calibration_dialog_driver.py `
  tests\test_droplet_imaging_summary_table.py `
  tests\test_print_profiles.py `
  tests\test_online_stream_ui_integration.py `
  tests\test_simulated_machine.py `
  tests\system\test_sil_stream_calibration_lifecycle.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py
```

Do not use the full Python suite as a Milestone 4D completion gate unless a
focused failure identifies a wider production call path.

Troubleshooting:

- `session is already locked`: close the other simulator using that root.
- `missing a valid session.json marker`: select an empty directory or a root
  previously created by this launcher.
- root-overlap rejection: do not select the repository, production data, the
  user profile, or a drive root.
- checkpoint access denial: the session is retained and fails closed. Inspect
  the printed root and `logs\launcher.log`; do not overwrite production files.
- disabled camera, updater, qualification, regulator-calibration, balance, or
  firmware controls are expected in Milestone 1.

Run the focused launcher/session tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_state_recorder.py `
  tests\test_sil_state_projection.py `
  tests\test_sil_state_observer.py `
  tests\test_sil_state_inspector.py `
  tests\test_simulation_session.py `
  tests\test_simulation_session_owned.py `
  tests\test_simulator_control.py `
  tests\test_simulated_app_launcher.py `
  tests\test_safe_application_construction.py `
  tests\test_mainwindow_closeevent.py
```

## Real-UI Virtual Print-Array Workflow

Slice 5 adds a separate verification CLI that constructs the real Model,
Controller, MainWindow, 16-by-24 well widget tree, and execution persistence
under explicit simulation dependencies. It connects only to the literal
`SIMULATED` port and completes 96 wells (rows A-D) through the UI start button.
No MCU, serial port, camera, GPIO, balance, updater, or manual operator action
is used.

Prerequisites:

- the repository `env` virtual environment with real PySide6;
- a writable output root;
- `QT_QPA_PLATFORM=offscreen` for headless use (set automatically by the CLI
  unless `--visible` is supplied).

### SIL scenario registry and capability manifest

The 24-well smoke, 96-well regression, and 384x10 stress IDs are
registered in
`tools/virtual_workflows/registry.py`. The CLI obtains its `--scenario`
choices from that registry. All three IDs dispatch through generic composed
journeys. The 384x10 legacy `VirtualPrintArrayScenarioConfig` runner remains
directly callable as a parity oracle while Slice 8 terminal validation is
pending.
For compatibility, the CLI default remains `virtual_print_array_96_v1`;
suite selection is not a CLI feature yet.

The tracked current-truth portfolio is
`tools/virtual_workflows/manifests/capability_coverage_v1.json`, with schema
identity `labcraft.sil_capability_coverage` version 1. It records capabilities,
registered scenarios, planned/active suites, intended schedules, embedded
action/assertion IDs, limitations, and freshness policy. Generated reports do
not rewrite it. The `standard` suite is active and selects only
`print_array_smoke_24_v1`. The active `lifecycle` suite contains the three
verified editor scenarios plus the verified 24-well soft-stop/resume
scenario. Candidate gates remain executable directly but do not join the
suite until they pass; suite/capability CLI selection is not available yet.

Validate registry/fixture drift, manifest references, portable paths, test
nodes, Pi safety requirements, and current capability claims with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Validation failures identify the manifest field or stable ID that drifted.
Keep all manifest paths repository-relative with POSIX separators, do not store
credentials or machine-local paths, and do not mark a capability `covered`
without an active assertion-backed scenario. This validation is read-only and
does not launch Qt, a workflow, physical hardware, or a remote Pi operation.

Reusable scenario actions live in `tools/virtual_workflows/actions.py`. The
legacy scenario adapter now composes those actions through one per-run context
and global deadline while preserving the two registered IDs, fixtures, CLI,
report-v1 envelope, and comparison behavior. Each report records ordered
action, milestone, and cleanup evidence beneath
`metrics.workflow.values`. Validate the action contracts without launching a
workflow with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

The reusable layer lazily imports Qt only for UI operations, accepts only the
literal simulated machine path supplied by the existing adapter, and always
attempts the full cleanup sequence even after timeout or failure.

### SIL pytest tiers

The standard Python test selection runs one composed real-UI SIL scenario:
`virtual_print_array_24_v1`, covering A1 through A24 with one virtual stock.
It constructs the real MainWindow, Controller, Model, 16-by-24 plate widget,
authoritative execution files, and simulated machine. It must complete within
30 seconds and retain the normal report-v1 evidence and four named
screenshots.

Run the standard smoke directly with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\system\test_virtual_workflow_smoke.py
```

Longer composed SIL tiers are opt-in:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-regression `
  tests\system\test_virtual_print_array_96_composed.py `
  tests\system\test_virtual_print_array_workflow.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_virtual_print_array_384x10_workflow.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle
```

The lifecycle command runs create/finalize, prepared rename/refinalize,
post-start lock/editable-copy, and the 24-well soft-stop/resume workflow.
Without these flags, tests marked `sil_lifecycle`,
`sil_regression`, or `sil_stress` are collected but skipped; all editor
fixture contracts are still checked.
Fast registry, manifest, report, comparison, and local Pi safety-contract
tests continue to run normally.
The `sil_pi_contract` marker never launches a remote Pi operation; remote Pi
execution remains an explicit, separately authorized command.

Run the editor create/finalize lifecycle directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_create_finalize_v1 `
  --timeout-seconds 60
```

This scenario clicks the real Experiment Editor button, creates a fresh design,
selects A1 and A2 through the Printable Wells dialog, enters one fixed 1x
droplet stock, optimizes and generates, and presses `Finalize Design`. It validates the
prepared execution plan, immutable revision, compact progress, both key CSVs,
and the absence of calibration/printing history. It then reloads the saved
design and activates the authoritative runtime without rebuilding the design.
A passing report retains `editor_opened`, `generated`, `finalized`,
`reloaded`, and `validated` screenshots and reports every declared lifecycle
assertion as `pass`.

Run the prepared rename/refinalize regression directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_prestart_rename_refinalize_v1 `
  --timeout-seconds 60
```

This scenario first creates the minimal A1/A2 prepared experiment, then
reopens the real editor and changes the name, replicate count, selected wells,
printed/final volumes, reagent targets, reagent mode, and fill mode. It
optimizes again and presses `Finalize Design`. Its target contract requires a single
renamed directory, a fresh revision-1 prepared plan for A1-A6, archived
superseded prepared artifacts, zero progress, consistent key files/runtime
assignments, and a `ready_to_start` reload.

An untouched `PREPARED` execution remains editable after disk reload. Both
Save and `Finalize Design` publish material pre-start edits through the same transactional
replacement path. Started, progressed, resumed, calibrated, or invalid
executions remain fail-closed and require the editable-copy workflow instead.

The Experiment Editor exposes four explicit lifecycle actions:

- `Finalize Design` is enabled for a new draft or editable `PREPARED` design.
  A `ready_to_start` eligibility result does not relabel an editable design.
- `Load Execution` is enabled for a locked, inactive saved execution whose
  authoritative runtime can be reconstructed.
- `Execution Loaded` is disabled when that authoritative runtime is already
  active.
- `Execution Locked` is disabled for blocked, terminal, invalid, or otherwise
  non-activatable saved executions.

`Load Execution` only reconstructs the saved runtime. It does not start or
resume printing; the operator must still use the applicable print/start or
resume action. Locked executions show a full-width lifecycle banner while the
lower status line remains available for transient details and errors.

Run the post-start editor boundary directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_post_start_lock_v1 `
  --timeout-seconds 60
```

This scenario creates and activates the minimal experiment, durably advances
its plan to revision 2 with `lock_reason=printing_started`, and opens the real
editor without issuing a print command. It requires every in-place mutation
surface to be read-only, a visible lifecycle banner with explicit copy
guidance, and an enabled
`Create Editable Copy...` path before it attempts the copy. The active source
remains byte-identical, while the copy accepts a tolerance-only edit and
finalizes as a distinct revision-1 `PREPARED` execution that is
`ready_to_start`. `Create Editable Copy...` always uses the currently loaded
`experiment_design.json`, asks only for a new name in a widened dialog, and
publishes the fresh copy beside the source directory; it does not open a
source-folder selector or inherit execution, progress, calibration, or
printing history. The scenario is active in the lifecycle suite.

Milestone 7 Slice 6 routes this scenario through the shared composed journey
runner. The normal editor controls still own source creation, locked-state
inspection, in-place rejection, editable-copy creation, tolerance editing,
finalization, and prepared-copy reload. The deliberate zero-progress
authoritative activation and `printing_started` lock are recorded as `model`
actions and are excluded from UI coverage; no machine is connected and no
print command is issued. Raw QTest/modal handling now has one owner in
`ExperimentEditorDriver`, and the retained direct runner delegates to the
same page driver, authoritative evidence, and assertion policy for parity.

Run the focused composed Slice 6 gate and a visible replayable journey with:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_editor_post_start_composed.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_post_start_lock_v1 `
  --output-root verification_reports\milestone7-slice6-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

Execute the exact `run.replay_command` retained in `report.json`. The stable
fixture hash, action IDs/multiplicity/surfaces, assertion decisions,
screenshots, source immutability, copy freshness, classification, and cleanup
must match; generated identities, paths, timestamps, durations, and
identity-bearing hashes may differ. If a Qt node materially exceeds its
normal bounded runtime, rerun that exact node with a fresh `--basetemp` below
`$env:TEMP\LabCraft`. The complete Python suite remains deferred until the
final Milestone 7 validation.

Milestone 7 Slice 7 migrates the default `virtual_print_array_96_v1`
regression to the same shared one-stock composed journey as the 24-well
smoke. The normal editor selects A1-D24, machine/rack/calibration/array
controls report truthful UI surfaces, and a reusable regression evidence
profile adds the 48-completion midpoint, responsiveness, resources,
persistence I/O, queue-starvation, injected-stall, report-set, comparison,
and paired local Pi-evidence contracts. The 384x10 stress runner remains
unchanged.

The frozen fixture still describes a 5 nL prepared design value and a 10 nL
design target at 1300 us and 1.2 psi. The application-owned pulse-aware SIL
calibration model deterministically measures 9 nL at 1300 us; the normal
calibration dialog therefore applies 9 nL. Slice 7 records and validates the
5-to-9 nL selected/applied result while preserving the fixture bytes and the
10 nL design target. This is synthetic application-path evidence, not a
physical volume-accuracy claim.

Run the composed/direct parity and retained failure gates with:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-regression `
  tests\system\test_virtual_print_array_96_composed.py `
  tests\system\test_virtual_print_array_workflow.py

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root verification_reports\milestone7-slice7-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 90
```

Inspect the six named screenshots (`editor_opened`, `generated`, `ready`,
`printing`, `mid_array`, and `completed`) and execute the exact retained
`run.replay_command`. A calibration-dialog timeout fails closed with retained
evidence; retry that exact run once in a fresh output root. Two consecutive
failures block the migration. The complete Python suite remains deferred to
the final Milestone 7 validation.

Before the first pressure-sweep, stream-volume, droplet `Calibrate All`, or
stream `Calibrate All` start while the authoritative plan is still
`PREPARED`, the UI requires `Start Calibration` confirmation. `Cancel` is the
safe default and occurs before calibration mode preflight, machine-setting
changes, queue creation, or callbacks. The model remains authoritative for the
durable `calibration_started` lock when a volume calibration is applied.

Run the print-array soft-stop/resume lifecycle directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_soft_stop_resume_24_v1 `
  --timeout-seconds 60
```

This scenario starts A1-A24 through the real UI, queues the real
`Stop After Well` click when completion 6 is observed, and requires the
confirmed watermark/clear/park path to reach an empty paused checkpoint with
`ready_to_resume`. It observes 250 ms of stopped quiescence, clicks
`Resume Print` through the real UI, and requires 24 exact terminal
stock/well completions. A passing report contains `ready`, `printing`,
`stop_requested`, `stopped`, `resumed`, and `completed` screenshots and
reconciles every begun, discarded, reissued, and completed intent. This is
functional lifecycle evidence; responsiveness, resources, and performance
are `not_applicable`.

Run the strict authoritative reload scenario directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario authoritative_reload_resume_24_v1 `
  --timeout-seconds 60
```

This scenario uses one `QApplication` but constructs two independent
Model/Controller/MainWindow/simulator sessions over the same isolated
scenario root. The first session reaches a clean paused checkpoint and tears
down. The second opens the real Experiment Editor, selects the persisted
folder, and selects `Load Execution` before a real UI resume.

The scenario is active in the lifecycle suite. The persisted design is loaded
through the real editor without changing its authoritative disk identity,
`Load Execution` reconstructs the exact partial runtime without starting or
resuming printing, and the real
`Resume Print` path completes A1-A24 without replaying any pair completed by
the first session. A passing report contains eight ordered screenshots, both
session cleanup records, disk/model/plan identity evidence, per-session
command-sequence evidence, and exact combined intent reconciliation. This
proves a fresh MVC/simulator composition within one SIL process; it is not an
operating-system restart or physical-hardware resume.

Run the multi-stock virtual-head lifecycle directly with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_multi_stock_24x2_v1 `
  --timeout-seconds 60
```

This composed scenario promotes the former stress-derived reduced test into a
strict tracked A1-A24 by two-stock fixture. It creates the design, stages and
returns both distinct virtual heads, calibrates both heads, and starts each
stock pass through normal Qt controls. It requires an idle, drained simulator
queue before the initial stage, between-pass exchange, and final return.
The first pass must leave the original plan `ACTIVE`; the second must finish
the same plan as `COMPLETED`. A passing report proves the stock/head identity,
effective pulse width and pressure, two durable pass boundaries, and all 48
stock/well pairs exactly once with no discarded or outstanding intents.
It also retains `editor_opened` and `generated`, followed by
`stock_1_ready`, `stock_1_printing`, `stock_1_completed`,
`stock_2_staged`, `stock_2_printing`, and `completed` screenshots.
Responsiveness, resources, and performance are `not_applicable`.

Lifecycle scenarios are single-run functional evidence. They reject Pi
evidence, injected-stall controls, report-set repetition, and baseline
creation. `--visible`, `--qt-platform`, `--output-root`,
`--timeout-seconds`, and `--speed-multiplier` remain accepted; speed changes
only the isolated simulator configuration and is not performance evidence.

Run the normal one-timescale characterization:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --speed-multiplier 1 `
  --timeout-seconds 180
```

Run the accelerated probe self-check, which deliberately blocks the Qt thread
for 300 ms after well 48 and requires both phase attribution and a captured
main-thread stack:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --speed-multiplier 100 `
  --inject-ui-stall-ms 300 `
  --inject-after-completion 48 `
  --timeout-seconds 180
```

Use `--visible` for local visual inspection. If `QT_QPA_PLATFORM=offscreen` is
already set in the shell, remove it before a visible run.

Reports are retained beneath:

```text
verification_reports/virtual_workflows/virtual_print_array_96_v1/<UTC>_<commit>/
```

### Opt-in 384-well by 10-stock stress workflow

`virtual_print_array_384x10_v1` exercises the same real UI, Controller, Model,
simulator, and authoritative persistence path for ten sequential stock passes
over all 384 wells. The fixture contains ten calibrated droplet-mode heads and
3,840 distinct stock/well completions. Between passes, the scenario performs a
virtual operator head exchange through the reusable rack Swap/Load/Unload
driver while the command queue is idle; no physical head, port, camera, or
other hardware dependency is used. The byte-identical fixture retains its
10 nL design target and original head metadata. The composed recipe uses a
fixed 1,355 us synthetic calibration, whose integer pulse-aware model result is
9.99 nL, to preserve one normal-UI dispense per stock/well. This is synthetic
application-path evidence, not a physical calibration claim.

This is an opt-in characterization, not part of routine pytest or the accepted
96-well comparison baseline:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_384x10_v1 `
  --speed-multiplier 100 `
  --timeout-seconds 1800
```

The run requires exactly 3,840 cached progress updates and no full progress
rebuilds or hot-path authoritative reads. It preserves 11,520 resume and 3,840
progress `fsync`/atomic-replace calls. Its 15,380 identity guards comprise four
guards per completion plus a read-only preflight identity guard and a
preparation identity guard for each of the ten stocks. The final checkpoint
must retain zero intents and the terminal authoritative bundle must validate.

The report additionally records ten pass transitions, active pressure-render
intervals, resident-memory growth, bounded event-retention counters, cumulative
serialized progress bytes, and the final file sizes. Cumulative serialized
bytes are write volume over the whole run, not simultaneous disk usage.
Service gaps or active pressure-render intervals above 250 ms produce an
informational stress warning. A maximum above 1000 ms, or scheduling-lateness
p99 above 250 ms, is a functional stress failure. These limits apply only to
this opt-in stress workload and do not change comparison policy v1.

Reports are retained beneath:

```text
verification_reports/virtual_workflows/virtual_print_array_384x10_v1/<UTC>_<commit>/
```

Each successful run contains the validated JSON report, text summary, bounded
event trace, stack diagnostics, retained isolated config/experiment/calibration
roots, and ready/printing/mid-array/completed screenshots. Failed runs retain a
traceback and failure screenshot when possible. Generated reports are ignored
by Git and are machine-specific.

Slice 8 implementation, offscreen terminal validation, visible Windows
qualification, and exact replay validation are complete.
The reusable rack, final-pass deadline, pressure-readiness, and guarded
ACTIVE-plan cache corrections remain in place. The diagnostic closeout adds a
rolling 120-second no-progress watchdog with bounded Controller/simulator/
checkpoint evidence and separates the composed and legacy-direct stress test
nodes. Focused 100x/1,000x simulator and Controller soaks each preserved 4,000
handler-driven lookahead operations, so no scheduler correction was made.

An isolated real 384-completion persistence run completed in 4.009 seconds
with a 12.573 ms maximum per completion, all 1,536 `fsync` and replacement
calls, zero hot-path reads, and zero full progress rebuilds. Two subsequent
composed stress runs each completed all 3,840 operations without failed actions
or queue starvation. The first proved that nine apparent pressure-render gaps
were the nine intentional inactive windows between stock passes. Active render
intervals are now segmented by pass; the corrected run excluded those nine
boundaries and measured a 256.192 ms maximum.

The follow-up revision-history remediation now validates one calibration
successor against the active session's already validated in-memory history.
It preserves the existing atomic writes and pre/post-write file-identity
guards; cold activation, partial-commit recovery, and terminal closeout still
validate the complete immutable chain. Seven injected write failures prove
that partial commits never advance the cache and recover through the existing
full-validation path.

The final composed 384x10 node passed all 3,840 operations in 383.65 seconds
with zero starvation. Maximum event-loop gap was 685.460 ms,
scheduling-lateness p99 was 81.616 ms, and active pressure-render maximum was
252.072 ms. Nine cached calibration commits had a maximum of 181.185 ms and
performed no full bundle refresh; terminal closeout retained one full-chain
validation. The separate direct-parity node also passed.

The retained pre-correction visible run and exact replay failed closed at
1,536 operations on the same fifth-head rack Swap interaction. A focused
real-session test now reaches that UI boundary without printing: it seeds ten
heads, assigns four slots, and cycles the remaining six through the real rack
Swap combobox. Diagnostics showed that Qt highlighted the correct popup row
but suppressed the release inside its post-open double-click guard. The shared
mouse-only driver now waits out that bounded guard before the item click.

Run the fast rack-only gate headlessly or with a real Windows window:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle tests/system/test_virtual_workflow_rack_swap.py
$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe -m pytest -q -s --run-sil-lifecycle tests/system/test_virtual_workflow_rack_swap.py
```

Three fresh visible rack-only processes passed all six swaps in under nine
seconds each. The subsequent full visible workflow and its exact emitted
replay both completed 3,840/3,840 operations with zero failed actions, failed
assertions, or starvation and drained terminal queues. Slice 8 is complete;
the full pytest suite was deferred to final Milestone 7 validation.

### Mid-array disconnect fail-closed workflow

Milestone 7 Slice 9 adds the composed
`print_array_disconnect_mid_array_24_v1` lifecycle. It creates the normal
24-well one-stock experiment, starts through the real array control, and uses
the normal connection button to disconnect after exactly six durable
completions. The canonical simulator confirms that its queue is drained before
the Controller retires the two canceled look-ahead intents. Unconfirmed or
physical-runtime cancellation is never treated as safe to discard.

The passing boundary retains an ACTIVE plan, Controller `resume_ready`,
authoritative `ready_to_resume`, six completed stock/well pairs, a disconnected
and unhomed machine, zero pending intents, and 250 ms of quiescence. It does not
resume or finish the remaining wells; this focused scenario proves the
disconnect boundary independently.

Run it offscreen or through a visible Windows window:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_disconnect_mid_array_24_v1 `
  --seed 19 `
  --speed-multiplier 20 `
  --timeout-seconds 60

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_disconnect_mid_array_24_v1 `
  --seed 19 `
  --speed-multiplier 20 `
  --timeout-seconds 60 `
  --visible
```

Reports retain the action/assertion ledgers, six named screenshots, state
trace, hashes, seed, exact replay command, and cleanup evidence beneath
`verification_reports/virtual_workflows/print_array_disconnect_mid_array_24_v1/`.
If a visible teardown ever opens a command-error dialog, verify that application
component cleanup blocks deferred child-widget signals before hiding and
deleting the window. Slice 9 and the final Milestone 7 Python validation are
complete; seeded exploration and manual suite selection remain Milestone 8
work.

### Mixed droplet/stream composed lifecycle

Milestone 8 Slice 1 registers `print_array_mixed_mode_24x2_v1` in the manual
lifecycle suite. The journey reuses the composed editor, rack, calibration,
stock-pass, persistence, and teardown phases. It drives a 9 nL droplet pass
and a 60 nL stream pass through normal Qt controls, performs two five-droplet
trials in the real `ManualRefuelCheckDialog`, records Stable, and then crosses
the normal stream array-start preflight. This is synthetic application-facing
SIL evidence, not proof of physical printing, flow, pressure, or refueling.

Run it offscreen or visibly, then use the exact replay command emitted in the
report:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_mixed_mode_24x2_v1 `
  --output-root verification_reports\milestone8-slice1 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_mixed_mode_24x2_v1 `
  --output-root verification_reports\milestone8-slice1-visible `
  --seed 1 --speed-multiplier 20 --timeout-seconds 120 --visible
```

Run the focused tests with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_manifest.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\test_manual_refuel_check_dialog.py `
  tests\test_sil_manual_refuel.py `
  tests\system\test_sil_stream_calibration_lifecycle.py `
  tests\system\test_virtual_workflow_mixed_mode_composed.py `
  tests\system\test_virtual_workflow_multi_stock_composed.py `
  tests\system\test_virtual_workflow_smoke.py
```

Reports retain nine screenshots, exact UI/harness action surfaces, the two
calibration records, the passed manual-refuel record and ordering, 48 durable
completion intents, hashes, seed, replay command, and clean teardown. The full
pytest suite remains deferred to the final Milestone 8 validation.

### Manual SIL selection and changed-source recommendations

Milestone 8 Slice 2 adds a read-only planning surface over the validated
capability manifest. Dry runs do not schedule or execute tests. Operators
still decide when to run a journey; Milestone 8 Slice 3 adds explicit host
execution for the same suite and capability selectors.
Listing, recommendations, and dry runs print deterministic JSON to stdout and
return before importing Qt or constructing the application; they do not create
anything beneath `verification_reports/`.

Inspect the catalog or produce plans with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list all

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite standard --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --capability execution.mixed_droplet_stream_lifecycle --dry-run
```

The standard plan is frozen at `print_array_smoke_24_v1`, order 1, seed 1,
and a 60-second timeout. A different explicit seed or timeout fails closed.
Lifecycle plans retain the manifest order and each scenario's declared
timeout. Omitting `--dry-run` now executes the selected Windows plan through
the Slice 3 fresh-process aggregate runner.

Request recommendations for all staged, unstaged, and untracked paths, or
override Git discovery with one or more explicit repository paths:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --recommend-changed

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --recommend-changed `
  --changed-path tools/virtual_workflows/page_drivers.py
```

Recommendations report matching capability status, source-area reasons, and
ordered active scenarios, but never authorize execution. Deferred capability
matches remain visible as gaps and cannot be selected. Pi plans additionally
require `--target-pi`, `--pi-preflight`, and `--pi-hardware-proof`; those files
are validated before a plan is emitted. Direct `--scenario` execution remains
unchanged, and `--dry-run` alone plans the legacy default scenario.

Run the Slice 2 focused gates with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests/test_virtual_workflow_selection.py `
  tests/test_virtual_workflow_manifest.py `
  tests/test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests/system/test_virtual_workflow_smoke.py
```

If selection reports manifest drift, validate the tracked manifest before
running a scenario. If a Pi plan is rejected, regenerate or transfer matching
preflight/hardware-isolation evidence rather than bypassing validation. No
unattended scheduler, suite artifact writer, or cleanup command is introduced
by this slice.

### Isolated host SIL suite execution

Milestone 8 Slice 3 executes `--suite` and `--capability` selections only when
an operator invokes them. Each selected journey runs sequentially in a fresh
Python child process through the unchanged direct `--scenario` CLI. This keeps
Qt and application state out of the parent process and prevents state from one
journey leaking into the next.

Run the standard lane, a capability, or the complete lifecycle portfolio with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite standard --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --capability execution.mixed_droplet_stream_lifecycle `
  --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000
```

Without an explicit output root, aggregates use
`verification_reports/suites`. Each run contains the hashed selection plan,
`aggregate.json`, `summary.txt`, and ordered `children/<order>_<scenario>/`
directories. Child stdout/stderr and the authoritative report-v1 tree remain
separate; the aggregate references and hashes them rather than copying their
evidence.

Every selected child runs even after an earlier failure. A child passes only
when its process result agrees with exactly one valid, identity-matched report.
The aggregate returns 0 for pass or warning, 2 for a completed failing
selection, and 3 for orchestration or aggregate-writing failure. A per-child
watchdog uses the selected scenario timeout plus 60 seconds, then terminates
and, after five seconds, kills a still-running child while retaining logs.

Pi execution, repetition, fault injection, report sets, baselines, comparisons,
and performance-threshold controls remain unavailable for aggregate runs.
Use direct `--scenario` execution for supported single-scenario controls. For
visible qualification, set `QT_QPA_PLATFORM=windows`, add `--visible`, and run
the exact replay command printed by the aggregate summary.

### Capability coverage and source freshness

Milestone 8 Slice 4 adds an offline, operator-invoked join from retained Slice
3 aggregates to the tracked capability manifest. It does not schedule or run a
workflow. Name every input explicitly; the evaluator validates the aggregate,
its selection plan, child reports, and all referenced hashes before assessing
required scenarios, assertions, semantic actions, declared interaction
surfaces, verification layers, and source identity:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --coverage-from verification_reports\suites\capability__execution.mixed_droplet_stream_lifecycle\<run>\aggregate.json `
  --output-root verification_reports\suites
```

Repeat `--coverage-from` to supply an explicit multi-aggregate evidence set.
Coverage mode rejects scenario/suite execution, planning, Pi, visibility,
timing, repetition, fault injection, baseline, and comparison controls. It
never scans for a convenient latest result and never writes generated status
back into the tracked manifest.

Each evaluation creates
`verification_reports/suites/coverage/<timestamp>_<run-id>/coverage.json` and
`summary.txt`. Capabilities are classified as `pass`, `fail`, `incomplete`,
`missing`, or `stale`. A narrower suite cannot claim a whole capability when
other manifest-active scenarios are absent, and an action recorded through a
different interaction surface cannot satisfy a UI claim. Exit code 0 means all
in-scope capabilities passed, 2 means the evaluation completed with at least
one non-pass capability, and 3 means input validation or artifact writing
failed.

Report-v1 source identity now includes a versioned source-tree fingerprint.
It covers Git-tracked and non-ignored execution/verification inputs while
excluding documentation, retained reports, caches, and runtime artifacts.
This makes intentionally uncommitted but byte-matching evidence comparable
without letting a later source change appear current. Legacy reports remain
readable, but without the fingerprint they are `incomplete`; a complete
otherwise-passing report with a different fingerprint is `stale`. Evidence
age is always retained as informational metadata and does not schedule or gate
manual testing.

### Parameterized SIL calibration matrix

Milestone 8 Slice 5 adds the operator-invoked
`mixed_mode_calibration_v1` matrix. Its eight typed cases reuse the existing
mixed-mode journey and tracked reference fixture while varying droplet/stream
pairing, stock order, calibration profile, and manual-refuel outcome. Generated
case data stays in memory; the matrix does not create a fixture or workflow
body for each variation.

Milestone 9 Slices 3-5 add `calibration_requantization_v1`. Its first three
one-stock, 24-well droplet cases freeze exact catalog-owned count oracles for an
idempotent `10 -> 10` calibration, an 8 nL to 9 nL volume increase producing
`10 -> 9`, and a 10 nL to 9 nL volume decrease producing `10 -> 11`. Passing
evidence reconciles the prepared plan, visible preview, calibrated plan,
zero-progress persistence, runtime, durable intents, simulator commands, and
terminal added counts by exact stock and well identity.

Three appended grouped-oracle cases cover mixed `1 -> 1` and `10 -> 9`
multi-target wells with zero fill omitted from dispatch, an executed stream
`40 nL / 4 drops -> 10.8 nL / 15 drops` mode transition with exact completed
bundle reload in a fresh application session, and fill-stock `4 -> 5`
requantization while non-fill remains at 6 drops. Their positive intent counts
are 36, 48, and 48 respectively.

The final two cases complete the eight-case catalog. The missing-fill
safeguard first records a valid 9 nL calibration, then drives a real
`droplet_to_stream` 60 nL Apply whose zero-drop reagent preview would require
an absent fill stock. It passes only when the real `Apply failed` dialog is
shown, the authoritative bundle remains byte-identical, and no array start,
durable intent, or simulator dispense occurs. The two-reagent isolation case
completes reagent 1 at one drop per well before recalibrating reagent 2 from
one to two drops. It requires 48 unique stock/well intents, exactly 72 total
commanded droplets, and unchanged reagent-1 identity, assignments, targets,
calibration linkage, and completed progress.

List the catalog, inspect a deterministic plan, run all cases in isolated
children, or run one replayable case with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list matrices

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix mixed_mode_calibration_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix mixed_mode_calibration_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix mixed_mode_calibration_v1 `
  --case mixed_ba_baseline_unclear `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 20 --timeout-seconds 120 --visible
```

An all-case run writes
`verification_reports/matrices/mixed_mode_calibration_v1/<run>/` with the
hashed `matrix_plan.json`, `aggregate.json`, summary, ordered child logs, and
references to each authoritative report-v1 evidence tree. Children continue
after an earlier failure, but any timeout, launch error, missing or ambiguous
report, identity/hash mismatch, return-code disagreement, or failed case makes
the aggregate fail.

Three negative cases exercise the real “Manual Refuel Check Required” guard.
They accept the initial Start confirmation, select the default-safe Cancel
response, and pass only when the matching non-passed check and calibration
fingerprint persist while completion count, plan state, queue, gripper, and
execution intents prove that printing was not bypassed. Matrix aggregates are
separate evidence and do not satisfy registered capability-manifest coverage.
Pi, scheduling, repetition, fault injection, baseline, comparison, and
performance controls remain unavailable in matrix mode.

Run a selected requantization case offscreen with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --case stream_to_droplet_40_to_10_8 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen
```

Inspect `metrics.persistence.values.dispense_count_evidence` in each retained
report. `oracle_scope` must be
`calibration_requantization_v1_catalog_oracle`, all reconciliation checks must
pass, and the joined command count must match the catalog-owned positive intent
count (24, 36, or 48). For the stream transition, also require
`execution.completed_terminal_reload_exact` and the `terminal_reloaded`
screenshot. Use the retained replay command; do not reconstruct a case from
remembered values.

For `zero_fill_missing_fill_rejected`, inspect
`metrics.persistence.values.calibration_rejection_evidence` and require every
check to pass, zero values for all dispatch counters, and screenshot
`calibration_apply_blocked`. For `two_reagent_second_1_to_2_isolated`, inspect
`metrics.persistence.values.two_reagent_isolation`; the support-stock progress
and linkage checks, primary-only retarget check, exactly-once execution check,
and 72-droplet total must all pass.

Milestone 9 qualification completed against source commit `792a7b0`. The
complete requantization and mixed-mode matrices, their exact aggregate
replays, the eight-scenario lifecycle suite and replay, the 96-well host
regression and replay, and visible `10 -> 9` and `10 -> 11` cases and replays
all passed. The final default Python suite result was `4123 passed, 78 skipped`.
Exact aggregate/report paths and hashes are retained in
`docs/sil_interactive_simulation_milestone_9_slice_6_completion_record.md`.
Use its commands and the current runner-emitted replay rather than treating
these historical paths as a substitute for source-current qualification.

### Experiment-design SIL matrix

Milestone 10 adds the manually invoked `experiment_design_pairwise_v1`
matrix. Its nine literal, independently derived cases cover a single-reagent
control, multiple reagents and seeds, one- and two-stock feasibility, sparse
custom wells and exclusions, exact capacity, capacity rejection, and fixed
stock infeasibility without forming a Cartesian product.

List or inspect the ordered catalog, run every case in a fresh Qt process, or
run one visible representative with:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list matrices

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix experiment_design_pairwise_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix experiment_design_pairwise_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix experiment_design_pairwise_v1 `
  --case custom_wells_with_exclusions `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 20 --timeout-seconds 120 --visible
```

Positive cases manipulate normal experiment-editor controls, finalize the
design, reload the authoritative bundle, and compare the reconstructed stock,
reaction, and well assignment to the catalog oracle. The two-stock case also
proves the rejected one-stock attempt did not mutate authoritative execution
artifacts. Negative cases stop at the real Finalize warning and require the
experiment directory to remain byte-identical with no execution plan,
runtime activation, durable intent, or simulator dispatch.

For visible review, inspect `generated`, `well_picker_configured`,
`finalization_rejected`, and `prepared_reloaded` screenshots when emitted.
Run the exact replay printed by the aggregate or report. Matrix evidence is
outside registered capability-manifest aggregation and does not replace
source-current lifecycle or regression selection.

Milestone 10 qualification completed against source commit `a373433`. The
nine-case matrix and exact replay, five visible case/replay pairs, lifecycle
and host-regression suites/replays, and default Python suite all passed. The
suite result was `4146 passed, 88 skipped`. Exact retained paths, hashes, and
limitations are in
`docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`.

### Bounded seeded editor exploration

Milestone 8 Slice 6 adds the manually invoked `editor_prepared_guard_v1`
campaign. It generates one legal and one intentionally invalid prepared-editor
sequence for each frozen seed `1, 7, 19, 42, 101`. All ten sequences reuse the
tracked prepared-editor fixture and one dynamic journey; no per-seed fixture or
journey body is written.

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list explorations

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration editor_prepared_guard_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration editor_prepared_guard_v1 `
  --output-root verification_reports\exploration `
  --speed-multiplier 1000 --timeout-seconds 60

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration editor_prepared_guard_v1 `
  --sequence seed_101_illegal `
  --output-root verification_reports\exploration `
  --speed-multiplier 20 --timeout-seconds 120 --visible
```

A full campaign runs ten fresh child processes and writes a hashed
`exploration_plan.json`, `aggregate.json`, summary, child logs, and references
to each authoritative report-v1 evidence tree beneath
`verification_reports/exploration/editor_prepared_guard_v1/<run>/`. The full
campaign uses its frozen seed set and rejects an explicit `--seed`; a selected
sequence derives its seed from the sequence ID and rejects a mismatch.

Illegal sequences temporarily set printed volume above final reaction volume,
attempt Finalize through the real Qt control, dismiss the real `Invalid
volumes` warning through QTest, and pass only when plan revision, files, audit
history, directory identity, runtime activation, and modal state remain
unchanged. They then restore valid values, regenerate, refinalize, and reload a
prepared, `ready_to_start`, runtime-inactive design. Legal runs use 18 actions;
the longest illegal run uses 23 of the 25-action limit. Exploration aggregates
remain separate from registered capability coverage and do not schedule tests.
Pi, hardware, protocol, firmware, unbounded random walks, fault injection,
repetition, baselines, and comparisons remain unavailable in exploration mode.

The report's responsiveness phase timings include `ui.pressure_render`, the
count and duration distribution for the real pressure-plot update slot. The
text summary shows its count, p95, and maximum. This diagnostic covers the
synchronous pressure-series/label update, not deferred native paint or
compositor work, and it is not yet a performance gate. Pressure update signals
are coalesced through a 100 ms single-shot timer, so the chart redraws at no
more than approximately 10 Hz while always reading the latest model state.
`pressure_render_assessment` records incoming signals, actual renders,
coalesced updates, their ratio, the interval, excluded inactive pass
boundaries, and timer teardown state.

Individual well-state signals update only the named well label. Experiment
loads, reagent changes, clears, plate changes, unknown well IDs, and explicit
`all` notifications retain the batched full-plate refresh. These optimizations
change only UI work; machine status processing, execution persistence, and
completion ordering remain unchanged.

Active authoritative executions retain their last validated immutable bundle
and resume document in memory. Before every runtime persistence write, the app
checks the expected identities of the design, plan, progress, resume,
calibration/migration files, and immutable revision history. This removes
repeated per-well JSON reload and history-validation work without changing the
durability contract: each well still performs three atomic, fsynced resume
writes and one atomic, fsynced progress write in the original order.

The resume file is now a bounded recovery checkpoint rather than a completed
command history. It contains only unresolved pending intents; after durable
progress proves a completion, the third resume write removes that intent.
With the normal two-well lookahead its size is therefore bounded by in-flight
work instead of total completed wells. Existing schema-v1 files containing
completed intents remain readable. Passive inspection leaves them untouched,
and explicit activation validates them against progress before compacting them
in the activation checkpoint write. No additional history file, journal,
digest, or migration is created.

If an authoritative file changes outside the running app, printing fails
closed with an execution synchronization error instead of overwriting the
change. Reload the experiment, inspect or repair its authoritative bundle, and
explicitly reactivate it before continuing. Ordinary save failures leave the
last coherent in-memory document available for an unambiguous retry.

Real-UI reports expose this evidence beneath
`metrics.persistence.values.authoritative_io`: hot-path read counts, resume
disk loads, full-bundle refreshes, guard/reconciliation counts, and phase-bound
fsync/replace counts. The 96-well scenario requires zero hot-path reads while
retaining 288 resume and 96 progress durable operations. It also requires 384
identity guards: one immediately before each durable write. These fields are
diagnostic additions; comparison policy v1 and existing baseline metric paths
are unchanged.

The reviewed `ea509c7` remediation evidence completed the accelerated Windows
scenario in 6.185 seconds with zero hot-path reads, a 99.812 ms maximum
event-loop gap, and unchanged durability counts. A clean fail-closed Pi 5 set
of one warm-up plus five measured speed-1 runs passed every functional and
relative comparison rule with acceptable noise. Its median duration was
17.286 seconds, scheduling-lateness p95/p99 were 51.057/61.914 ms, and progress
write p95 was 14.303 ms. The candidate remains an informational warning because
one run's 287.122 ms maximum service gap exceeds the 250 ms warning budget.
These values characterize only the recorded hosts and software identities.
All four durable writes per completion remain visible costs; this remediation
does not batch or weaken them.

The bounded-checkpoint implementation was characterized at commit `48f1e0c`.
All three Windows persistence workloads retained at most one sequential
benchmark intent, ended with zero intents, and held the clean resume file at
499 bytes while preserving every expected durable operation. The accelerated
real-UI scenario retained at most the Controller's two-well lookahead, ended
with a clean 499-byte checkpoint, and completed 96/96 wells in 6.002 seconds.
On the Pi the clean checkpoint was 485 bytes; two independent one-warm-up plus
five-measured sets passed all functional, safety, boundedness, durability,
compatibility, and primary responsiveness checks with acceptable noise.

Both Pi sets reported a secondary progress-write warning. Nested evidence
attributed it to the unchanged progress-phase `fsync` (p95 rose from 9.012 ms
in the immediately preceding set to 15.212 ms in the first bounded-checkpoint
set), while atomic replace stayed near 0.070 ms and total scenario duration
improved. The bounded resume change does not alter the progress payload or its
durability call. The warning is retained as storage evidence; it was not
suppressed by batching, skipping, or weakening `fsync`.

Progress reports split the same write into full-rebuild or cached-update
construction, version-specific serialization, atomic-write, serialized
byte-volume, and non-durable timing evidence. The observer is tooling-only,
restores the real instance methods after every run, and leaves the existing
`persistence.write_progress`, `fsync`, and atomic-replace measurements intact.
This instrumentation supports same-host before/after analysis; it does not
create a new acceptance threshold or make copied cross-environment reports
comparable.

For a durable authoritative completion, the Controller now passes the pending
intent ID to progress persistence. The model validates that intent against the
coherent cached payload, frozen target, and live post-command count, then
copy-on-write replaces only the affected well/reagent before performing the
same complete-file serialization, flush, `fsync`, and atomic replace. Missing,
stale, regressing, overflowing, or mismatched state fails closed; it never
falls back to enumerating every well. Argument-free, initialization, reset,
export, and non-authoritative writes retain full reconstruction.

The reviewed Pi before/after sets reduced median cached-construction p50 from
0.7319 ms to 0.0405 ms. Median per-run non-durable progress p95 improved from
4.9003 ms to 4.7272 ms, while all primary and relative comparison rules
passed. The candidate retains the existing informational maximum-service-gap
warning. Because copy-on-write preserves optional validated reagent metadata
that full reconstruction previously omitted, this fixture's median serialized
snapshot increased from 34,368.5 to 54,624.5 bytes. That result motivated the
compact authoritative progress format described below.

New authoritative executions write `progress.json` schema v2. The immutable
execution plan remains the authority for well/reaction identities, stock
metadata, targets, plate metadata, and applicability; progress stores only the
canonical well order and one added-droplet array per stock. An array element is
an integer where the stock applies to that well and `null` where it does not.
The file is deterministic compact UTF-8 JSON. It remains a complete atomic
snapshot: every completion still flushes, `fsync`s, and atomically replaces the
entire file before its intent can retire.

Schema-v1 progress remains readable. Positive v1 files and any v1 execution
with a resume checkpoint stay v1, avoiding a silent format change during an
active or recorded run. A validated zero-progress v1 execution can adopt v2
only when no resume checkpoint exists. Legacy reconstruction, analysis-only
executions, editable copies, administrative reset/export paths, and
non-authoritative progress retain their existing v1 behavior.

Compact files are less convenient to inspect by hand. Use the application’s
status views, or convert a validated experiment before downgrading to an older
application:

```powershell
.\env\Scripts\python.exe tools\convert_execution_progress.py `
  --experiment-dir <path-to-experiment> `
  --to-v1
```

The converter validates the complete authoritative bundle, atomically writes
the derived v1 snapshot, validates it again, and requires the progress
fingerprint to remain unchanged. Back up or close the experiment first; this
is an offline maintenance command and must not race an active print.

Reports expose `progress_format` with the schema version, encoded size,
schema-v1-equivalent size, ratio, and reduction fraction. They also retain
cumulative serialized bytes. Report envelopes and comparison policy v1 paths
are unchanged.

The reviewed full Pi 384×10 characterization completed all 3,840 stock/well
updates with a final 11,082-byte v2 snapshot versus a 590,982-byte equivalent
v1 snapshot (98.12% smaller). Total progress serialization was 42.55 MB rather
than the prior 4.088 GB projection. It retained zero hot-path reads and exact
15,369 guards, 11,520 resume writes, and 3,840 progress writes.

That run still failed the separate stress responsiveness gate: isolated
event-loop and active pressure-render intervals reached 3.65 and 3.82 seconds,
although scheduling-lateness p99 was 186.7 ms. Captured stacks implicate
pass-start execution-plan/history validation and full experiment-guidance UI
rebuilds as remaining contributors. On Windows, both allowed full-stress
attempts instead failed closed on the existing `execution_resume.json` atomic
rename contention. Compact progress therefore solves the serialization-volume
problem but does not claim to eliminate every large-workload UI stall or
Windows rename failure.

Pass startup now reuses the guarded authoritative runtime session for
target-preserving lock and printer-head-binding transitions. Each stock pass
checks cached file identities and the immutable-revision inventory, then
either performs a guarded no-op or validates one successor in memory before
retaining the existing atomic writes. It never silently reloads and overwrites
an externally changed bundle; a mismatch invalidates the session and requires
explicit reload/repair. Explicit activation, target-changing calibration,
recovery, and terminal completion still perform full validation.

On the reviewed Pi 384x10 before/after pair, the ten pass starts fell from a
2.286-second median (2.592-second maximum) to 0.101 seconds (0.120-second
maximum). Pass-window immutable-revision reads fell from 492 to zero and full
bundle refreshes from 21 to zero, while all 11,520 resume and 3,840 progress
durable writes remained. Guidance rebuilds were at most 104 ms. The optimized
run still recorded a separate 3.44-second terminal-completion event-loop gap:
the required terminal recovery/full validation remains synchronous and is a
separate remediation target.

Successful terminal completion now advances the same guarded in-memory
authoritative session. It checks the active checkpoint and file identities,
constructs and incrementally validates one completed successor, retargets the
cached progress and resume documents, and preserves the crash-recoverable
write order: immutable revision, current plan, progress, then resume. It does
not rewrite CSV exports because completion cannot change wells, stocks, or
targets. Only after those writes does it perform one synchronous full
authoritative validation and expose the completed state. Hard abort,
already-terminal retry, missing-session recovery, and partial-commit repair
retain the conservative disk path.

The 384x10 Pi evidence reduced the cached terminal transaction from the prior
multi-second recovery sequence to 549 ms, including a 374 ms full validation,
with four real `fsync`/replace pairs and one read of each revision. It also
identified and removed two measurement-path scaling costs: structural
equality of the full execution plan and copying the observer's complete I/O
history at the transaction boundary. The observer now uses constant-time
cumulative counters for live deltas while retaining raw samples for the final
report. The last Pi report predates that tooling-only observer fix, so its
1.039-second measured event-loop gap and 1.698-second pressure interval remain
conservative diagnostic evidence rather than a closing responsiveness pass.
Windows `execution_resume.json` rename contention remains a separate issue.

If Windows reports `WinError 5` while rapidly replacing an execution file,
retain the failed diagnostics and retry once with a fresh ignored
repository-local output root, for example:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root tmp\virtual_workflows
```

Do not disable atomic replacement or `fsync` to work around host filesystem
contention. Windows offscreen SIL runs use the normal application font,
`Segoe UI` at 9 points, from `%WINDIR%\Fonts`. Font discovery and sample-glyph
rendering are fail-closed: a missing `segoeui.ttf`, an empty or invalid
caller-provided `QT_QPA_FONTDIR`, or an unresolved Qt font stops the run instead
of accepting unreadable screenshots. Visible runs retain Qt's native font, and
non-Windows headless runs retain the font supplied by their native fontconfig
environment.

Exit code `0` means the functional workflow passed, `2` means a workflow,
safety, persistence, timeout, teardown, or required-artifact failure, and `3`
means setup/environment/reporting failed. Responsiveness data is informational
in Slice 5: it is unsuitable for cross-host, cross-Python, or cross-Qt
comparison, and raw latency cannot fail until Slice 6 defines same-host
comparison and acceptance rules.

The scenario validates the application-facing workflow only. It does not prove
firmware protocol behavior, collision safety, physical motion, pressure
response, camera analysis, balance behavior, or droplet quality.

## Virtual Workflow Baselines and Comparison

Slice 6 repeats the real-UI workflow without blending samples across runs,
builds same-host report sets, and compares a candidate against compact tracked
baseline evidence. It retains every canonical Slice 5 report and verifies its
SHA-256 hash before baseline creation or comparison.

Use a stable, non-secret host label. The initial Windows comparison host uses
`windows-sil-primary-v1`. Baseline collection requires a clean worktree, one
warm-up, five measured runs, one source commit, no injected stalls, and
compatible real PySide6/Qt evidence:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --speed-multiplier 1 `
  --warmup-runs 1 `
  --measured-runs 5 `
  --host-label windows-sil-primary-v1 `
  --threshold-maturity candidate `
  --accept-baseline tests\performance\baselines\virtual_print_array_96_v1_windows_sil_primary_v1.json
```

The command prints the generated `report_set.json` path. A repeated candidate
uses the same options without `--accept-baseline`. Compare that report set
without rerunning the scenario:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --compare `
  tests\performance\baselines\virtual_print_array_96_v1_windows_sil_primary_v1.json `
  verification_reports\virtual_workflows\virtual_print_array_96_v1\<run>_report_set\report_set.json
```

The candidate directory receives `comparison.json` and `comparison.md`.
Classification separates workflow correctness, environment compatibility,
measurement noise, and performance. The initial tracked baseline is
`candidate`: relative or absolute performance findings warn but return `0`.
Exit codes are:

- `0` for pass, improvement, or candidate warning;
- `2` for workflow, safety, persistence, timeout, or teardown failure;
- `3` for setup/reporting failure, incompatible identities, missing evidence,
  tampered/missing raw reports, or excessive primary-metric noise; and
- `4` for a performance regression against a baseline explicitly reviewed at
  `acceptance` maturity.

Compatibility is intentionally strict: scenario/workload/timing, host label,
OS, CPU, Python executable/version, PySide/Qt versions, and Qt platform must
match. Git commits may differ. Dirty candidates are labeled and may be used for
review, but a dirty run can never create an accepted baseline. Cross-Windows/Pi
or copied reports from another computer are historical evidence, not valid
comparisons. Repository-local interpreter paths are normalized relative to the
repository so the tracked summary does not expose a workstation user path.

Do not overwrite a baseline as part of ordinary collection. An explicit
reviewed regeneration must repeat the full clean run and pass
`--replace-accepted-baseline`. Raw reports and report sets remain ignored and
must be retained locally so their hashes can be checked; only the compact
summary under `tests/performance/baselines/` is tracked.

The candidate policy uses run-level medians, robust MAD-based noise floors, and
CV/outlier evidence. It is designed to expose host UI/persistence regressions,
not physical printer behavior. It still does not validate firmware, protocol,
motion, pressure, cameras, balance, or droplet quality.

## Raspberry Pi Software-In-The-Loop

The target-Pi SIL lane runs the same real-UI workflow on Raspberry Pi CPU and
storage without exposing printer devices to the process. It does not launch
`FreeRTOS-interface/App.py`. The designated command uses the explicit
in-process simulator and additionally requires:

- 64-bit Raspberry Pi OS on a Raspberry Pi;
- the repository-local `venv`, `.venv`, or `env`;
- real PySide6/Qt and `psutil` from `requirements-pi.lock`;
- `bubblewrap`, `strace`, and `findmnt`; and
- at least 1 GiB free beneath the ignored
  `verification_reports/virtual_workflows/` root.

Install the two SIL-only system tools once:

```bash
sudo apt-get install -y bubblewrap strace
```

The wrapper fails closed if the sandbox cannot start. Bubblewrap presents a
private `/dev`, mounts the repository read-only, makes only the report root and
temporary Qt directories writable, and unshares the network. There is no
unsandboxed Pi option. The output root remains on the Pi's normal filesystem,
so persistence measurements still exercise its real storage.

Run preflight and the traced safety audit locally on the Pi:

```bash
bash scripts/pi/run_virtual_workflow_sil.sh preflight \
  --output-root verification_reports/virtual_workflows/pi-sil \
  --qt-platform offscreen \
  --output verification_reports/virtual_workflows/pi-sil/pi-safety/preflight.json

bash scripts/pi/run_virtual_workflow_sil.sh prove \
  --output-root verification_reports/virtual_workflows/pi-sil \
  --qt-platform offscreen \
  --preflight verification_reports/virtual_workflows/pi-sil/pi-safety/preflight.json \
  --output verification_reports/virtual_workflows/pi-sil/pi-safety/hardware_proof.json
```

The audit runs one accelerated scenario under `strace`. It fails if the
private-device process accesses UART/serial, GPIO, camera/video, I2C, or USB/DFU
paths. Its timings are safety evidence only and are never included in a
performance report set.

### Manual Pi SIL suites

The complete operator decision table, failure triage, source-freshness rules,
Pi authorization boundary, and non-destructive retention policy are maintained
in `docs/sil_virtual_workflow_operator_runbook.md`.

For pytest runs containing SIL session tests, use a unique `--basetemp` beneath
`$env:LOCALAPPDATA\Temp\LabCraft`; an in-repository basetemp is rejected by the
intentional session-root safety boundary.

Milestone 8 Slice 7 routes the registered `pi_primary` and `pi_stress` suites
through the same fresh-process aggregate contract used on Windows. Suite mode
still performs one preflight and one traced 96-well proof before execution; the
aggregate parent and every scenario child then remain inside the same
Bubblewrap private-device and network namespace. Pi capability selectors are
planning-only so they cannot launch the stress workload indirectly.

Preview the bounded primary run and exact replay without contacting a Pi:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_pi_virtual_workflow.ps1 `
  -PiHost pi-test `
  -Suite pi_primary `
  -Seed 1 `
  -SpeedMultiplier 100 `
  -ReplaySuite `
  -DryRun
```

After separately authorizing the target and confirming that its checkout
contains the exact source under test, remove `-DryRun` and use the approved host
and user. `-ReplaySuite` validates and executes the first aggregate's exact
allowlisted command, then retrieves one bundle containing both aggregates and
their shared proof:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <approved-host> `
  -PiUser <approved-user> `
  -Suite pi_primary `
  -Seed 1 `
  -SpeedMultiplier 100 `
  -ReplaySuite
```

Suite timeouts default to the manifest: 180 seconds for `pi_primary` and 1,800
seconds for `pi_stress`. A positive `-TimeoutSeconds` override is recorded in
the exact replay. The 384x10 lane requires the explicit `-Suite pi_stress`; it
is never implied by primary or capability execution.

Suite artifacts use `labcraft.pi_sil_artifact_bundle` v2 and remain beneath the
ignored `verification_reports/virtual_workflows/` tree locally and remotely.
The wrapper verifies the archive sidecar, every member hash and size, both
aggregate trees, all child report hashes, source identity, and proof/trace
linkage before reporting success. Suite mode never invokes cleanup. Retain a
failed run for diagnosis and use the separately bounded manifest cleanup command
only after explicit review.

The authorized Milestone 8 Slice 7 qualification on Raspberry Pi 5 passed the
`pi_primary` suite and its exact replay at seed 1 and 100x simulator speed. Each
fresh child completed 96/96 wells with all required assertions passing, zero
unexpected dialogs, zero queue starvation, and clean teardown. The retained
aggregate SHA-256 values are `25ec6c8389564041...` and `16799d1e19973d6a...`;
the locally validated two-aggregate bundle SHA-256 is `ecb9fccc83017583...`.
The remote evidence was intentionally retained and `pi_stress` was not run.
See
`docs/sil_interactive_simulation_milestone_8_slice_7_completion_record.md`
for exact paths, full hashes, safety identity, and the focused bootstrap fixes.

Milestone 8 final closeout requalified `pi_primary` after the final reusable
Qt-driver corrections. The fresh primary and its exact replay each passed
96/96 from commit `1e7efa86f95461a2865c075c717f06af06ae28cd` in a separate,
clean Pi worktree. Their aggregate SHA-256 values are
`c884a480054f31fff6d435e5cb0aae7efd9223d6525bff342ca9c2af1baa25f8`
and `228fd7aad64d28d03a93511cdd37791825737e70ccfddba11261c7c3293172a6`;
the validated 53-member bundle SHA-256 is
`785bcbbc8e6d6e34eff13c11fd7fcc4f20c1afa54b349d53810e89deae7b8ff0`.
No cleanup or `pi_stress` run occurred. The complete Windows/Pi evidence,
focused and full-suite results, source identities, and retained paths are in
`docs/sil_interactive_simulation_milestone_8_slice_8_completion_record.md`.

If suite selection fails before Qt starts, verify the suite name, evidence file
paths, source-tree identity, and Qt platform in preflight/proof. A completed
failing aggregate returns `2` and is still bundled; orchestration or evidence
validation failures return `3` and leave remote artifacts in place.

From Windows, the operator-light wrapper performs preflight, proof, one warm-up,
five measured runs, bundle retrieval, hash/path validation, and optional
same-Pi comparison:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <pi-host> `
  -HostLabel pi5-sil-primary-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 5 `
  -TimeoutSeconds 600
```

For the opt-in 384-well by 10-stock characterization, collect one measured
accelerated run and emit a standard one-report report set:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -PiUser labcraft `
  -Scenario virtual_print_array_384x10_v1 `
  -HostLabel pi5-sil-384x10-v1 `
  -WarmupRuns 0 `
  -MeasuredRuns 1 `
  -SpeedMultiplier 100 `
  -TimeoutSeconds 1800
```

The safety proof remains the short, fixed 96-well workload. The stress run
uses the same fail-closed Bubblewrap lane and manifest/hash validation, but it
is not eligible to create or compare against the tracked 96-well baseline.
On the reviewed Pi 5, an accelerated run durably completed 3,791 of 3,840
stock/well entries in 20 minutes before an operator-enforced stop, so allow the
full 30-minute scenario timeout and expect roughly 20–25 minutes on comparable
storage. Speed acceleration does not shorten JSON serialization, `fsync`, or
atomic replacement. Always announce and poll this long opt-in command; do not
include it in routine validation.

Use `-PreflightOnly` or `-SafetyProofOnly` for setup diagnosis.
`-KeepRemoteArtifacts` retains the exact remote run directories; otherwise
only manifest-listed run roots are removed after local extraction and
validation. Failures always retain their evidence. The tool never installs
packages, updates the checkout, changes Pi configuration/groups, or starts the
production application.

A reviewed clean-host collection may create the candidate Pi baseline:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <pi-host> `
  -HostLabel pi5-sil-primary-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 5 `
  -TimeoutSeconds 600 `
  -CreateCandidateBaseline `
  -BaselineDestination `
    tests\performance\baselines\virtual_print_array_96_v1_pi5_sil_primary_v1.json
```

The tracked Pi baseline was collected from clean commit `1f09d022b749` on a
Raspberry Pi 5 using NVMe/ext4, CPython 3.11.2, PySide6/Qt 6.7.1, offscreen Qt,
speed 1, and the documented 600-second timeout. It passed functionally with
acceptable primary noise and remains candidate maturity. Independent same-Pi
comparison crossed only absolute responsiveness warning rules; all relative
regression rules passed.

The UI repaint remediation candidate at clean commit `3ee0a1906eb7` passed a
new same-Pi 1+5 collection with acceptable noise. Against that tracked
pre-remediation baseline, median scheduling-lateness p95 improved from 176.665
to 68.824 ms, p99 from 251.777 to 118.722 ms, well-widget update p95 from
50.903 to 0.522 ms, and scenario duration from 28.518 to 18.925 seconds. Every
relative comparison rule passed. The candidate still warns because its
287.254 ms maximum event-loop gap exceeds the candidate policy's informational
250 ms budget; scheduling-lateness p99 now passes the 250 ms absolute rule.

Pi candidates may be compared only with the exact same Pi model, filesystem,
sandbox method, OS/CPU, Python, PySide/Qt, Qt platform, timing policy, timeout,
and host label. A Windows/Pi comparison is intentionally rejected as
incompatible.

Retrieved archives and extracted reports remain ignored. Each archive carries a
versioned manifest with SHA-256 and size evidence for every raw JSON report,
event timeline, screenshot, safety trace, and retained scenario file.

## Execution Persistence Microbenchmark

The Slice 0/2 persistence tool measures the durable execution path that writes
print intent, progress, and resume state and then reloads the authoritative
bundle. It does not launch the UI or construct the Controller, communication
stack, serial port, cameras, GPIO, balance, MCU, or firmware updater.

Prerequisites:

- the repository `env` virtual environment and normal application dependencies;
- real PySide6 is recommended so the report records the representative binding,
  although this Slice 0 workload does not run a Qt event loop;
- no printer or MCU connection is required.

The default remains the original versioned 384-completion workload (96 wells
and four stock-array passes) with one warm-up and five measured runs:

```powershell
.\env\Scripts\python.exe tools\characterize_execution_persistence.py
```

Reports are written beneath:

```text
verification_reports/virtual_workflows/execution_persistence_v1/
```

Each run writes `report.json` and `summary.txt`. Raw reports are local,
machine-specific, and ignored by Git. A passing Slice 0 result means the
workload and durability invariants completed. A warning means provisional
within-run growth was observed, but it is still informational and returns exit
code 0. Neither result is a performance acceptance threshold.

Select one of the three targeted Slice 2 workloads:

```powershell
# 96 wells, one stock, 96 lifecycle completions
.\env\Scripts\python.exe tools\characterize_execution_persistence.py `
  --workload execution_persistence_96_single_v1

# Original default: 96 wells, four stocks, 384 lifecycle completions
.\env\Scripts\python.exe tools\characterize_execution_persistence.py `
  --workload execution_persistence_v1

# Full 384-well plate, one stock, 384 lifecycle completions
.\env\Scripts\python.exe tools\characterize_execution_persistence.py `
  --workload execution_persistence_384_single_v1
```

Each workload has its own directory beneath
`verification_reports/virtual_workflows/`. Reports include per-phase and
per-completion timing, per-run first/last-quartile growth, progress/resume file
growth, real `fsync` and atomic-replace timings, final authoritative validation,
and process CPU time. Candidate growth is reported only when the median
last/first ratio is greater than 1.25 and the median absolute increase is
greater than 10 ms.

Useful options:

```powershell
.\env\Scripts\python.exe tools\characterize_execution_persistence.py `
  --output-root verification_reports\virtual_workflows `
  --warmup-runs 1 `
  --measured-runs 5 `
  --keep-workload-artifacts on-failure
```

Exit codes are `0` for a valid informational run, `2` for a workload,
durability, or safety failure, and `3` for setup/reporting failure. On failure,
inspect `failure_traceback.txt` and the retained workload directory named in
`report.json`. If Qt is reported as `stub` or `missing`, use the repository
virtual environment and verify PySide6 with:

```powershell
.\env\Scripts\python.exe -c "import PySide6; from PySide6.QtCore import qVersion; print(PySide6.__version__, qVersion(), PySide6.__file__)"
```

Generate and compare performance evidence only on the same host and compatible
Python/Qt environment. Raw reports copied from a different computer are
historical evidence, not an accepted baseline.

## Qt Event-Loop Verification Probe

The Slice 1 probe launches a real PySide6 event loop with the offscreen Qt
platform and injects named 50, 100, 250, and 350 ms blocking callbacks. It
measures timer service gaps, scheduling lateness, probe callback overhead,
phase attribution, main-thread stack capture, and optional process resources.
It does not construct the application MVC, communications, MCU, or any physical
interface.

Prerequisites:

- the repository `env` virtual environment;
- a real PySide6 installation (stubs are rejected);
- `psutil` for complete resource metrics; missing or unsupported counters are
  reported without failing the probe;
- no display server, printer, or MCU connection.

Run one warm-up and five measured offscreen iterations:

```powershell
.\env\Scripts\python.exe tools\run_qt_event_loop_probe.py
```

Reports are written beneath:

```text
verification_reports/virtual_workflows/qt_event_loop_probe_v1/
```

Each run writes `report.json`, `summary.txt`, and `stall_stacks.txt`. A passing
result means every deliberate stall was detected and attributed, the expected
long-stall stack was captured, and the timer and observer shut down cleanly.
Latency bands and distributions remain informational; they are not application
acceptance budgets. The offscreen probe measures Python and Qt event-loop
service, not compositor/GPU rendering, and it is separate from the production
freeze watchdog.

Useful options:

```powershell
.\env\Scripts\python.exe tools\run_qt_event_loop_probe.py `
  --output-root verification_reports\virtual_workflows `
  --warmup-runs 1 `
  --measured-runs 5 `
  --inject-stall-ms 50 100 250 350 `
  --heartbeat-ms 10 `
  --stack-capture-ms 250 `
  --observer-ms 5 `
  --resource-ms 100
```

Exit codes are `0` when injected behavior and cleanup are verified, `2` for a
probe correctness or cleanup failure, and `3` for environment or reporting
failure. On failure, inspect `failure_traceback.txt`, `summary.txt`, and
`report.json`. If Qt is reported as `stub` or `missing`, use the repository
virtual environment and run the PySide6 identity command in the preceding
section. If Qt cannot initialize a display plugin, set
`QT_QPA_PLATFORM=offscreen`; the tool selects that value by default.

## Droplet Imager Optics Calibration

The standard optics-calibration workflow uses a guided load/approach wizard, then reuses the imager `Optics` tab for manual focus, image capture, scale-bar analysis, and applying the micrometer-per-pixel and camera motion-conversion factors. The wizard does not require a printer head, print profile, or regulated pressure, and it does not change firmware or the device protocol.

App workflow:

1. Connect the machine, enable motors, and confirm saved `home` and `camera` locations are valid.
2. Open the main-window `Calibrations` tab.
3. Select `Start Guided Optics Calibration` and confirm the imager area is clear.
4. The wizard homes the machine, opens the gripper, prompts for micrometer insertion, closes the gripper, prompts for waste-holder removal, moves to camera X/Y at home Z, and then stops at `camera.Z - 1000`.
5. If the micrometer is not lined up with the imager entry, choose the manual-alignment branch and jog with the dialog controls. The wizard blocks Z jogging below the guarded approach height and never commands final camera Z.
6. When the service-mode imager opens to the `Optics` tab, manually jog/focus as needed.
7. Keep `Division size` at `10.0 um` unless your micrometer differs.
8. Select `Start Session`, use `Capture Frame` for each micrometer image, and use `Reject Last Frame` for bad frames.
9. Select `End Session and Analyze`; the app first computes the micrometer-per-pixel factor, then fits image-center movement against recorded machine `X/Z` positions.
10. Inspect the displayed motion fit metrics and the generated `motion_fit_summary/index.html` report in the session directory.
11. Select `Apply Result` when both quality gates pass. The measurement gate requires at least 5 valid images and CV at most 2%; the motion gate requires at least 20 fit frames, at least 3 repeat-position groups, 2D RMSE at most 15 px, and P95 residual at most 25 px.

`Open Manual Optics Calibration` remains available as an advanced fallback. It opens the same service-mode imager `Optics` tab but performs no automatic homing, gripper, or camera-approach motion.

Accepted calibrations are written to `local/droplet_imager_optics.json`. The top-level `um_per_pixel` value is loaded by droplet and stream volume analysis, and the nested `motion_conversion` value is loaded by droplet-imager stage conversion. Deleting or renaming that file rolls analysis back to the historical fallback of `1.5696 um/pixel` and the preset step-conversion matrix in `FreeRTOS-interface/Presets/step_conv_250813.json`.

The measurement and motion analyzers can be run from the command line:

```bash
py tools/scale_bar_conversion.py path\to\scale_bar_run --division-um 10.0 --output path\to\summary.json
py tools/scale_bar_motion_conversion.py path\to\scale_bar_run --debug --debug-summary-only
```

## Qualification Campaign CLI

The qualification campaign runner executes multiple existing qualification manifests in sequence and writes a parent campaign report while preserving each suite's normal report folder.

Dry-run the default production rigorous campaign:

```bash
python tools/run_qualification_campaign.py --campaign machine_full_qualification_v1 --operator-prompts --dry-run
```

Run the campaign on the Pi serial port:

```bash
python tools/run_qualification_campaign.py --campaign machine_full_qualification_v1 --operator-prompts --port /dev/ttyAMA0
```

Run the dedicated refuel-vacuum pressure-sensor qualification suite:

```bash
python tools/run_qualification.py --manifest refuel_vacuum_v1 --operator-prompts --fixture refuel_vacuum_dry_back_v1 --port /dev/ttyAMA0
```

Outputs:

- Suite reports: `hil_reports/qualification/<machine_id>/<timestamp>/`
- Campaign report: `hil_reports/qualification_campaigns/<machine_id>/<timestamp>/campaign_report.json`
- Campaign CSV: `hil_reports/qualification_campaigns/<machine_id>/<timestamp>/campaign_summary.csv`

## Firmware Local Checks

Prerequisites:

- CMake available on `PATH`
- STM32CubeIDE installed at `C:\ST\STM32CubeIDE_1.18.1\STM32CubeIDE`, or pass `-CubeIde` to `firmware/scripts/build_firmware_headless.ps1`

Run host firmware tests plus a headless CubeIDE build:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

The firmware scripts resolve the project from the repo checkout, so moved workspaces do not need script edits. If the headless build reports that the project cannot be found, verify the checkout path and rerun the build script with an explicit project path:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1 `
  -Config Debug `
  -ProjectDir C:\Users\conar\LabCraft_printer\firmware
```

## Firmware HIL + Camera Benchmark

Run full firmware checks + Pi flash + selftest + optional camera benchmark:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 `
  -PiHost 192.168.0.29 `
  -Profile FULL `
  -CameraBenchmark `
  -CameraBenchmarkCycles 100 `
  -CameraBenchmarkExposureUs 20000 `
  -CameraBenchmarkFlashDelayUs 5000 `
  -CameraBenchmarkFlashWidthUs 1000 `
  -CameraBenchmarkNumDroplets 1 `
  -CameraBenchmarkAttemptTimeoutMs 250 `
  -CameraBenchmarkMaxNewFrames 6
```

Outputs in `hil_reports/`:

- `selftest_<timestamp>.json`
- `selftest_<timestamp>_camera_benchmark.json` (when benchmark enabled)

The camera benchmark supports `flash_only`, `print_then_flash`, and
`coordinated_flash` modes. `flash_only` defaults to one warm-up trigger cycle
before counted qualification cycles. Use
`--camera-benchmark-min-trigger-period-ms N` to enforce a minimum trigger
start-to-start period during rate characterization. `coordinated_flash`
defaults to a 5000 ms gripper refresh period with a 500 ms pump pulse; use
`--camera-benchmark-coordinated-gripper-refresh-ms 10000` for a softer overlap
test. The benchmark artifact includes a `classification` block separating
firmware missed flashes from camera detection misses, and aborts early after 5
consecutive edge timeouts by default. Run the coordinated flash lane directly
on the Pi when you want to exercise flash capture while pressure regulation,
valve actuation, and gripper refresh are active:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --camera-benchmark \
  --camera-benchmark-mode coordinated_flash --camera-benchmark-order post_selftest \
  --camera-benchmark-cycles 20 --camera-benchmark-min-trigger-period-ms 100 \
  --camera-benchmark-coordinated-gripper-refresh-ms 5000 \
  --camera-benchmark-coordinated-gripper-pulse-ms 500 \
  --out hil_reports/camera_capture_coordinated_flash.json
```

## Pull Calibration Records From The Pi

From the Pi touchscreen, users can create an email-ready archive without remote access:

1. Open the droplet imager calibration window.
2. Wait for any active calibration or image capture to finish.
3. Click `Export Calibration Records` in `Run Options`.
4. Email the generated `LabCraft_calibration_records_*.zip` from `~/Downloads`.

The archive contains the current experiment's `calibration_recordings/`, calibration/progress context files when present, a generated `calibration_recordings_summary.csv`, and a `manifest.json`. The export is read-only and does not send commands to the printer.

Use the Windows PowerShell helper to copy calibration artifacts from a Pi experiment into local `tmp/` for replay and analysis:

```powershell
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -Latest
```

Prerequisites:

- Windows OpenSSH client available in `PATH` (`ssh` and `scp`)
- Pi repo available at `/home/labcraft/LabCraft_printer` unless overridden with `-RemoteRepo`

Common examples:

```powershell
# Copy one exact experiment directory
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -ExperimentName Untitled-20260304_111121

# Copy only calibration artifacts for the newest experiment
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -Latest `
  -CopyMode CalibrationOnly

# Copy an experiment, then materialize a filtered local subset of runs
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -ExperimentMatch 20260304 `
  -ProcessName NozzlePositionCalibrationProcess `
  -RunId run_20260304_111716_24e5f347

# Copy a whole stream experiment into the repo Experiments directory
# `-ExperimentMatch` accepts substrings and wildcard patterns such as Stream_100um_*
# Whole-experiment pulls resume by copy unit on rerun and skip droplet_imager_captures by default
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -ExperimentMatch Stream_100um_* `
  -LocalRoot FreeRTOS-interface/Experiments `
  -PreserveExperimentName

# Include droplet_imager_captures if you explicitly need the duplicate image archive
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -ExperimentMatch Stream_100um_* `
  -LocalRoot FreeRTOS-interface/Experiments `
  -PreserveExperimentName `
  -IncludeDropletImagerCaptures

# Preview the resolved remote/local paths without copying
powershell -ExecutionPolicy Bypass -File tools/pull_pi_calibration_records.ps1 `
  -PiHost 192.168.0.29 `
  -Latest `
  -DryRun
```

After a copy, the script writes `pull_summary.json` into the pulled experiment directory, prints a recording inventory, and suggests local replay commands such as:

```powershell
.\env\Scripts\python.exe tools\replay_calibration_run.py --root "tmp\pi_calibration\<timestamp>_<experiment>\calibration_recordings"
```

If you pass `-Replay`, the script will try to run `tools/replay_calibration_run.py` locally after copying. If no preferred local interpreter is found, it will print the replay command instead.

Whole-experiment pulls also write `pull_state.json` into the destination experiment directory. If a large transfer is interrupted, rerun the same command and the script will compare the local contents against the remote manifest, skip completed copy units, and continue with the remaining files/directories.

## Export Calibration Recording Summary CSV

Use the read-only summary exporter to create one scan-friendly row per recorded calibration process run:

```powershell
py tools/export_calibration_recording_summary.py "FreeRTOS-interface\Experiments\EF-Ts_rep1-20260424_223016"
```

By default, the tool writes `calibration_recordings_summary.csv` into the experiment directory. The CSV includes the run ID, process name, recorder outcome, operator/system verdict, review status, review reasons, and extracted error or warning messages.

Common examples:

```powershell
# Choose a custom output path
py tools/export_calibration_recording_summary.py `
  "FreeRTOS-interface\Experiments\EF-Ts_rep1-20260424_223016" `
  --out "tmp\calibration_recordings_summary.csv"

# Scan a standalone copied calibration_recordings directory
py tools/export_calibration_recording_summary.py `
  --recordings-root "tmp\pi_calibration\EF-Ts_rep1-20260424_223016\calibration_recordings"
```

Troubleshooting notes:

- `review_status=needs_review` is expected for runs with `verdict=unknown`, explicit failed verdicts, event errors/warnings, analysis problems, missing files, or malformed JSON/JSONL.
- `tool_error_count` means the exporter could not read one or more expected recorder files cleanly; check `error_messages` for the exact file and line when available.
- The exporter does not replay image analysis or contact hardware. It only reads existing recorder files and writes a CSV.

## Getting Started - PlatformIO

To get started with PlatformIO, follow these steps:

1. Install PlatformIO in VSCode:
    - Open VSCode and go to the Extensions view (Ctrl+Shift+X).
    - Search for "PlatformIO IDE" and click on the "Install" button.
    - Once installed, restart VSCode.

2. Open the PlatformIO project in VSCode:
    - Open the LabCraft Printer project folder in VSCode.
    - Open the "PlatformIO" sidebar (Ctrl+Alt+P).

3. Compile and upload firmware:
    - Click on the "Build" button (Checkmark in the bottom bar, left side) in the PlatformIO sidebar to compile the firmware.
    - Once the compilation is successful, click on the "Upload" button (Arrow in the bottom bar, left side)to upload the firmware to the board.

Note: Make sure you have the necessary drivers installed for your development board.

For more information, refer to the PlatformIO documentation and the documentation provided by the manufacturer of your development board.

## Usage

To launch the user interface manually once the virtual environment is active, use:
```bash
python FreeRTOS-interface/App.py
```
Inside `FreeRTOS-interface/Presets`, JSON files are tracked starter templates. On first launch, machine-specific templates for `Settings.json`, `Plates.json`, `Locations.json`, and `Obstacles.json` are copied into ignored `local/` files, and the app reads/writes those local copies after that. Calibration-memory starter files under `FreeRTOS-interface/CalibrationMemory` are also seeded into ignored `local/CalibrationMemory/` files before runtime writes. This preserves existing machine calibrations and reagent memory while keeping future app updates from editing tracked templates.

## Application updates

Operators can update the Python application from the Firmware tab.

Maintainers preparing release tags, release metadata, update bundles, or stable/RC promotions should follow `docs/release_process.md`.

Expected flow:

- Click `Check for Updates`.
- The online check fetches tags, reads the upstream `releases/latest.json`, and compares the local checkout with the latest stable release tag.
- Leave `Include release candidates` unchecked for normal updates.
- For support-guided testing only, check `Include release candidates` before clicking `Check for Updates`; the app targets the exact `release_candidate` named in `releases/latest.json`, or the newest valid tag in the optional `release_candidate_series`.
- Release candidate updates are still applied by a named release tag, and `Update App` remains disabled until a fresh check succeeds.
- If the app is already current with the selected release, it stays open and reports that no update is available.
- If an update is available, the app shows the target release version, release summary, release notes, rollback version when defined, and pending commit summaries, then enables `Update App`.
- Click `Update App`; the app confirms that application code will update and firmware will not be flashed.
- If the machine is connected, the normal disconnect/close flow runs first.
- A `LabCraft Updater` window appears after the main app closes, resolves the same confirmed release, and applies it with a fast-forward merge of the release tag.
- On success, the updater shows the status, installed release, commit range, installed commit summaries, and log path.
- Close the updater window, then launch LabCraft again using the normal shortcut or launch command.

Release-candidate series discovery is opt-in metadata. A stable release can allow future RC tags in the same line without knowing the final RC number:

```json
{
  "release_candidate": "v1.2.0-rc.6",
  "release_candidate_series": {
    "tag_prefix": "v1.2.0-rc.",
    "minimum": "v1.2.0-rc.6"
  }
}
```

If the update is blocked or fails, the updater window stays open and shows the log path. Support should ask for the path shown in the updater window, usually under:

```text
local/update_logs/
```

For dirty worktrees, network failures, credential failures, or non-fast-forward Git state, the updater does not stash, reset, clean, or overwrite local changes. Use `Reopen Current Version` to relaunch the installed app version and contact support with the updater log.

Offline operator flow:

- Copy the support-provided `LabCraftUpdates` folder to a USB drive.
- Plug the USB drive into the machine.
- Click `Install Offline Bundle`, select the support-provided manifest JSON, and review the displayed release details.
- If the bundle is valid and newer than the installed app, click `Update App` to install it through the same updater window and safe close flow.
- The regular `Check for Updates` flow still tries the normal online check first.
- If the online check cannot contact the remote repository, the app scans removable drives for `LabCraftUpdates/*.json` manifests.
- If a valid fast-forward offline bundle is found automatically, the same `Update App` button updates from that bundle.

### Create offline update bundles (support only)

When a machine cannot reach GitHub, support should package a named release as a portable Git bundle plus manifest. A full release bundle is the safest default:

```powershell
.\env\Scripts\python.exe tools/create_update_bundle.py --release v1.1.2
```

Release-aware bundles include the target release version, release manifest, release notes, and rollback version in the generated manifest so the app can show the operator which release will install.

If support intentionally needs to package the current deployment branch without release metadata, use:

```powershell
.\env\Scripts\python.exe tools/create_update_bundle.py --branch stable
```

For smaller machine-specific bundles, ask the operator for the current commit on the offline machine:

```bash
git rev-parse HEAD
```

Then create an incremental bundle from the support checkout using that commit as the prerequisite base:

```powershell
.\env\Scripts\python.exe tools/create_update_bundle.py --release v1.1.2 --since <offline-head-sha>
```

As a convenience, support can package approximately the latest 20 commits when confident the offline machine already has `stable~20`:

```powershell
.\env\Scripts\python.exe tools/create_update_bundle.py --release v1.1.2 --last 20
```

Incremental bundles are smaller, but they require the target machine to already have the base commit. If that prerequisite is missing, `git bundle verify` and the app updater reject the bundle cleanly. Incremental bundles omit tags by default; add `--include-tags` only when tag refs are needed.

Release-aware incremental bundles include tags by default so the target release tag is available inside the bundle.

The files are written under:

```text
local/LabCraftUpdates/
```

Copy the generated `.bundle` and `.json` files, or the full `LabCraftUpdates` folder, to the USB drive that will be sent to the operator. This workflow packages application code only; it does not flash firmware.

For backend/manual validation on the target checkout, run the updater against the manifest JSON:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --offline-manifest path\to\labcraft-stable-....json --no-relaunch
```

### Controlled release rollback

The Firmware tab includes support-guided rollback controls for restoring a previous application version without allowing arbitrary tag selection. Use rollback only with support guidance after confirming the machine is idle and no print, calibration, capture, or firmware operation is active.

Expected UI flow:

- Click `Check Rollback`.
- If the installed release defines a rollback target, the app shows the exact path such as `v1.2.0 -> v1.1.2`.
- If the online rollback check cannot fetch release tags, the app scans removable drives for `LabCraftUpdates/*.json` release-aware rollback manifests.
- Click `Restore Previous App Version`; the app confirms that application code will move backward and firmware will not be flashed.
- A `LabCraft Rollback` window appears after the main app closes, verifies the same target again, and applies it.
- For explicit support-provided bundles, click `Restore From Offline Rollback Bundle` and select a release-aware manifest directly.

The backend command remains available for support cases where the main app cannot launch.

Online rollback uses the installed `VERSION`, reads that release tag's manifest, and resets to its configured `rollback_version`:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --rollback --no-relaunch --record-result
```

Offline rollback requires a selected release-aware bundle manifest for the target release:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --rollback --offline-manifest path\to\labcraft-stable-....json --no-relaunch --record-result
```

The rollback command checks for a dirty worktree before fetching or resetting, verifies the target release metadata first, then applies the verified target with `git reset --hard`. If validation fails, the checkout is left at the current commit. After rollback, relaunch LabCraft normally and review the startup rollback result message or `local/update_logs/latest_update_result.json`.

## Pi setup status

For a Raspberry Pi 5 running Raspberry Pi OS Bookworm, use the manual procedure below as the source of truth. Do not run the older root-level helper scripts during normal setup if you are following this README.

| File | Current role | Normal Pi 5 setup? |
| --- | --- | --- |
| `README.md` | Source-of-truth setup for system packages, UART, cameras, GPIO, DFU, and the Python environment. | Yes |
| `scripts/pi/install_desktop_launcher.sh` | Optional per-user desktop launcher installer after the app already launches manually. | Optional |
| `setup_pi.sh` | Legacy partial system setup helper. It does not cover the full Bookworm camera flow or all current groups/packages. | No |
| `post_clone.sh` | Legacy virtualenv helper that installs `requirements.txt` into `.venv`, not the Pi lockfile into `venv`. | No |

## Updated Startup Procedure
```bash
### Update base system (safe)
sudo apt-get update
sudo apt-get -y full-upgrade
sudo reboot

# Enable the primary UART and disable the login console on it
# (This keeps the desktop boot intact and gives you /dev/ttyAMA0 for your MCU)
sudo raspi-config
#  → Interface Options → Serial Port:
#     - Login shell over serial?  NO
#     - Enable serial port hardware?  YES
#  → Interface Options → I2C:
#     - Enable I2C?  YES
#  → Finish (raspi-config will offer to reboot) → Reboot now

# Give the GPU a reasonable memory split
echo 'gpu_mem=128' | sudo tee -a /boot/firmware/config.txt
sudo reboot

# Cameras & tools (Bookworm uses rpicam-* commands)
sudo apt-get install -y \
  python3-libcamera python3-picamera2 rpicam-apps

# GPIO (libgpiod + Python binding + CLI tools like gpiofind/gpioinfo)
sudo apt-get install -y python3-libgpiod gpiod

# DFU and udev rule needs
sudo apt-get install -y dfu-util

# Build tools (handy for wheels)
sudo apt-get install -y python3-venv python3-pip

# Target-Pi SIL sandbox and hardware-access trace
sudo apt-get install -y bubblewrap strace

# Numpy dependent libraries
sudo apt-get install -y \
  python3-numpy python3-scipy python3-skimage python3-sklearn python3-opencv

# Serial access & video groups for your user
sudo usermod -aG dialout,video,gpio,render,plugdev $USER
sudo reboot

# ST DFU udev rule (non-root dfu-util):
printf '%s\n' 'SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", GROUP="plugdev", MODE="0664"' \
 | sudo tee /etc/udev/rules.d/45-st-dfu.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo reboot

## Configure camera overlays
# 1) Backup
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak.$(date +%F-%H%M)

# 2) Edit
sudo nano /boot/firmware/config.txt

# --- Camera configuration ---
camera_auto_detect=0

# V2 (IMX219) on CAM0, GS (IMX296) on CAM1:
dtoverlay=imx219,cam0
dtoverlay=imx296,cam1

# press Ctrl+O, Enter to save
# press Ctrl+X to exit

## Checks to make sure that the configurations are correct:
# Serial device present?
ls -l /dev/ttyAMA0

# Camera works?
rpicam-hello -t 2000 --camera 0
rpicam-hello -t 2000 --camera 1


# GPIO tools present?
gpioinfo | head
gpiofind GPIO17 2>/dev/null || true
```

## Python setup sequence
```bash
git clone https://github.com/ccmeyer/LabCraft_printer
cd ~/LabCraft_printer
python3 -m venv --system-site-packages venv
source venv/bin/activate

python -m pip install -U pip wheel
pip install pip-tools
pip-compile --extra-index-url https://www.piwheels.org/simple \
  --generate-hashes --output-file requirements-pi.lock requirements.in

pip-sync requirements-pi.lock

# NumPy and associated libraries are reinstalled during pip-sync and must be removed
# from site-packages so that they rely on the apt-managed dist-packages versions.
SITE_PACKAGES="$(python -c 'import site; print(next(p for p in site.getsitepackages() if p.endswith("site-packages")))')"
rm -rf "$SITE_PACKAGES"/numpy*
rm -rf "$SITE_PACKAGES"/pandas*
rm -rf "$SITE_PACKAGES"/matplotlib*
rm -rf "$SITE_PACKAGES"/scipy*
rm -rf "$SITE_PACKAGES"/sklearn*

# Manual launch
python FreeRTOS-interface/App.py
```

## Optional desktop launcher install

Once the Pi is already working with the manual setup above and the app launches correctly from your existing repo-local virtual environment, you can install a normal Raspberry Pi OS launcher without changing system configuration:

```bash
bash scripts/pi/install_desktop_launcher.sh
```

The launcher installer is intentionally narrow:

- It installs a per-user application entry into `~/.local/share/applications/`
- It uses the existing repo-local `venv`, `.venv`, or legacy `env`
- It does not run `apt`, change groups, touch camera/UART config, recreate the virtual environment, or reinstall dependencies

Launcher diagnostics are written to:

```text
logs/desktop-launch.log
```

To remove the launcher, delete:

```bash
rm -f ~/.local/share/applications/labcraft-printer.desktop
```

