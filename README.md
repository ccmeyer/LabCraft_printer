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

## Print-Array Pause and Queue-Clear Safety

The full-height `Pause` button in the Connection group pauses command transport
immediately and opens explicit actions. During an active print array, prefer
`Finish Current Well and Stop`;
it resumes only through the frozen current-well boundary, clears confirmed
look-ahead work, parks, and leaves the experiment resumable. `Keep Paused` is
the safe default.

When Resume finds an interrupted coordinated XY command already terminal at
its exact retained endpoint, firmware retires that command without waiting for
one-shot completion bits that may have been consumed during Pause. During an
immediate-pause safe stop, the Controller also watches only the narrower case
where fresh post-Resume X/Y telemetry proves the active XY command is at its
endpoint but its retirement frontier remains stalled for four seconds. That
guard reasserts Pause and requires Retry Safe Stop or confirmed abort; it never
clears the queue, parks, homes, or times ordinary motion and dispensing.

`Abort Array and Clear Queue` requires a second confirmation. It permanently
aborts the active experiment and the interrupted well may be uncertain. Every
application queue clear is classified and guarded by the Controller. An
automatic calibration cleanup cannot clear an active or uncertain experiment.
After a confirmed abort, the print-array control changes to disabled
`Experiment Aborted`; the terminal experiment cannot be resumed even when its
loaded reagent still has partial progress. Create or load a new experiment
before printing again. A completed terminal experiment is likewise
non-resumable and remains represented by a disabled completion control.

While a queue clear is pending or could not be confirmed, new print arrays and
printer-head transfers remain blocked. Keep the machine clear and use the
supported confirmed Clear Queue retry or motion-recovery workflow. If recovery
requires an MCU reset, follow the normal reset, inspection, dock-check, and
homing procedure before further motion.

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

## Development App Against Machine Data

The Windows-to-Pi development workflow is implemented incrementally under the
live [Pi development workflow plan](docs/pi_development_workflow_plan.md).
Its first read-only status/preflight action inventories both checkouts, the
shared interpreter, running processes, and development-store evidence without
creating or switching a worktree:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Status `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519
```

Use `-Action Preflight` when a nonzero exit is required for policy blockers.
`Status` still records blockers but exits zero after a complete collection.
Use `-DryRun` to display the intended target and paths without SSH or report
creation. JSON evidence is written beneath the ignored
`verification_reports/development-workflow/status/` root.

After committing and pushing a development branch, create or update only the
dedicated Pi development worktree at the exact Windows commit:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Sync `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -DevelopmentMachineDataRoot "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development/main-65ba38df-machine-data"
```

`Sync` requires a clean, pushed Windows HEAD and clean Pi state. It fetches the
configured upstream ref, selects the exact commit in detached mode under
`/home/labcraft/LabCraft_printer-dev`, and proves that the protected checkout,
retained worktrees, shared interpreter, running processes, and development
machine-data evidence did not change. It never resets, cleans, deletes, or
switches the protected production worktree.

After the first successful `Sync`, bind the shared interpreter and the intended
development store explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Configure `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -DevelopmentMachineDataRoot "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development/main-65ba38df-machine-data" `
  -Operator "Operator Name"
```

`Configure` requires the Pi development worktree to be clean, detached, and at
the exact pushed Windows commit. It confirms that the tracked root dependency
files are byte-identical in the production and development commits, runs the
production interpreter's version check, `pip check`, and bounded imports, and
fingerprints the installed distributions before and after. It never invokes a
package installer. It also revalidates the development-store marker, authorized
active pointer, and matching machine identity before atomically creating:

```text
/home/labcraft/.config/LabCraft/development_workflow.json
```

The external file contains only explicit paths, machine/store identifiers,
dependency evidence, and configuration provenance. It is outside every Git
worktree, so a branch or checkout change cannot redirect the development app to
another store. An existing different or invalid file is never overwritten.

On later sessions, validate and reuse that binding without repeating or guessing
the machine-data path:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Validate `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Operator "Operator Name"
```

If validation reports a dependency mismatch, do not install packages into the
shared production environment. Either restore matching dependency declarations
for this workflow or use a later, separately approved isolated-environment
workflow. If configuration or store evidence is invalid, preserve the JSON
report under `verification_reports/development-workflow/status/` and investigate
the named mismatch; the tool does not repair, replace, or fall back to another
store.

Once `Sync` and `Configure` have succeeded for the current pushed commit, launch
the Pi application in normal visible no-hardware development mode:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Launch `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -LaunchMode Visible `
  -Operator "Operator Name" `
  -LaunchTimeoutSeconds 1800
```

Close the main window normally when testing is complete. `Launch` first repeats
the path-free Slice 3 validation, requires the Pi development worktree to be
clean and detached at the exact pushed Windows commit, and uses only the
persisted development-store binding. It does not accept a machine-data path or
expose a hardware-enable switch. The main window identifies itself as a
development/no-hardware runtime, uses `SimulatedMachine`, blocks every physical
peripheral factory, and disables updater access.

For an unattended smoke qualification, use the offscreen lane with a short
automatic close:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Launch `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -LaunchMode Offscreen `
  -AutoCloseSeconds 5 `
  -LaunchTimeoutSeconds 120 `
  -Operator "Operator Name"
```

The offscreen lane uses Bubblewrap with a read-only host root, private `/dev`,
and no network namespace, while `strace` checks for serial, GPIO, camera, I2C,
USB/DFU, and updater-tool access. Both lanes write logs and launch evidence
beneath the external Pi directory:

```text
/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/sessions
```

The Windows status report records the corresponding Pi report path and hash.
Only `development_sessions/` and `development_runtime/` writes are permitted in
the development store. Production code/data, the shared Python packages, Git
worktrees, and relevant process state must be identical before and after. If a
launch times out, the supervisor signals only its own process group and records
the cleanup actions; do not kill unrelated Pi processes or bypass a failed
postflight. Install `bubblewrap` and `strace` through the documented Pi setup if
the offscreen lane reports either prerequisite missing.

### SAFE development-firmware round trip

After the exact feature commit has been built, committed, pushed, and synced to
the clean detached Pi development worktree, use the dedicated firmware wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development_firmware.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -ReleasedTag v1.3.0-rc.7 `
  -Operator "Operator Name"
```

This command has no FULL, selector, camera, or benchmark option. Before touching
the MCU it requires clean/pushed Windows state, a clean detached Pi development
worktree at the same commit, byte-identical tracked development firmware, a
release manifest/tag/protected-checkout recovery artifact with identical
SHA-256, a valid persisted development-store binding, the shared interpreter,
`dfu-util`, the serial port, and no conflicting process. Reports and logs are
written only beneath the external `development-workflow/firmware-sessions`
directory on the Pi and `verification_reports/development-workflow/firmware/`
on Windows.

The fixed sequence is development flash, plain SAFE, released-artifact flash,
and a second plain SAFE. The strict validator requires the exact 30-result SAFE
inventory, verifies that all eleven FULL actuation rows were skipped with zero
actuation metrics, and proves the flash session/output remained disarmed. Once
the development flash begins, released restoration is attempted even if its
SAFE run fails. Success means both SAFE stages passed, protected invariants are
unchanged, and the final role is released. A restore failure is
`recovery-required`; preserve its evidence and do not launch either app.

Preview the fixed path without SSH or flashing:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development_firmware.ps1 `
  -PiHost 192.168.0.33 `
  -Operator "Operator Name" `
  -DryRun
```

The older general-purpose `firmware/scripts/run_fw_hil_windows.ps1` now defaults
to SAFE, but it is not the isolated development workflow: it can upload into
the selected repository and still exposes FULL/actuating options. Do not use it
for autonomous development qualification.

### Attended hardware-development preflight

The hardware-development supervisor is separate from both no-hardware launch
and firmware flashing. Its normal first step is read-only policy preflight:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development_hardware.ps1 `
  -Action Preflight `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Operator "Operator Name"
```

It requires the exact clean/pushed Windows commit, matching clean detached Pi
worktree, persisted development-store identity, external firmware-state file,
matching firmware role/commit/artifact/SAFE evidence, and no app/updater/DFU/HIL
process. When development and released firmware differ, released, stale,
unknown, or recovery-required state cannot authorize the hardware app.

`Cancel` records an external canceled receipt without reading hardware or
starting the app. The successful `Launch` action is deliberately harder: it
requires `-Execute` and the exact attended text printed by the live workflow
plan. It creates a five-minute external authorization bound to operator,
commit, development store, and the current firmware-state bytes. Both the
launcher and App bootstrap revalidate that receipt and the two confirmations.
Updater, rollback, in-app DFU, and the production machine-data store remain
blocked. The supervisor owns only the process group it starts and records
normal exit or bounded cleanup plus protected postflight.

Do not use `Launch` unattended. Slice 6 automated/Pi qualification exercises
only dry-run, preflight, cancellation, and fail-closed paths. The first
successful hardware-enabled window is part of the final attended campaign.

### Durable firmware state and exact restoration

Firmware state is recorded outside every worktree at:

```text
/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/firmware-state.json
```

Every flash first atomically records `recovery-required`. Only an exit-zero
flash plus a strict plain-SAFE report can transition it to `development` or
`released`. Each transition increments a revision and writes an external
receipt containing the state hash. State binds machine, role, exact source
commit, artifact path/SHA-256, flash transaction/operator/timestamps,
flash/SAFE evidence, and the previous known-good released artifact. A checkout
alone never changes or proves installed firmware.

The normal autonomous qualification remains:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development_firmware.ps1 `
  -Action Roundtrip `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Operator "Operator Name"
```

It records recovery-required, flashes/SAFE-verifies development, records
development, then always records recovery-required and restores/SAFE-verifies
the released artifact before recording released. Exact released recovery can
also be requested idempotently with `-Action Restore-Released`.

`-Action Activate-Development` intentionally leaves development firmware
installed and is available only inside the final attended campaign. It requires
`-Execute` and the exact physical confirmation. Never run it as an unattended
test. Hardware-development preflight remains blocked until its resulting
development state exactly matches the current development commit/artifact; the
attended campaign must restore released firmware immediately afterward.

Any absent, corrupt, development, unknown, or recovery-required state makes
production readiness false. If restoration cannot reach released plus strict
SAFE, preserve all evidence, do not launch either app, and request attended
recovery rather than editing the JSON.

Do not switch a deployed production checkout to an arbitrary development commit
and launch it against the production machine-data root. Production stores are
bound to the exact commit authorized by the protected updater.

Create a separate external development clone while the production app is
closed. The target must not already exist; the command never overlays it:

```powershell
.\env\Scripts\python.exe tools\prepare_development_machine_data.py `
  --source-root "C:\absolute\production\machine-data" `
  --development-root "C:\absolute\development\machine-data" `
  --operator "Operator Name"
```

On the Pi, use the same tool with absolute Linux paths:

```bash
./env/bin/python tools/prepare_development_machine_data.py \
  --source-root "/home/labcraft/.local/share/LabCraft/LabCraft Printer/machine-data" \
  --development-root "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development/main-machine-data" \
  --operator "Operator Name"
```

The default development launch uses the cloned configuration and calibration
data but a simulated machine. Serial, cameras, GPIO, firmware/DFU, and app
updates are blocked, and the window displays a persistent development banner:

```powershell
.\env\Scripts\python.exe tools\run_development_app.py `
  --machine-data-root "C:\absolute\development\machine-data" `
  --operator "Operator Name"
```

Each launch writes an external `development_sessions/<uuid>.json` record bound
to the exact Git commit, active pointer, store marker, operator, and hardware
mode. Real-hardware development is an attended exception and requires both
`--enable-hardware` and this exact confirmation:

```text
I UNDERSTAND THIS DEVELOPMENT BUILD CAN CONTROL HARDWARE
```

Even in attended development mode, application updates and firmware/DFU remain
blocked. Use a protected tagged release to change the production deployment.
To refresh a development store, choose a new empty target directory; retain or
archive the old directory rather than deleting or overlaying it during a test.

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

The `legacy_experiment_read_only_v1` scenario materializes a deterministic
older experiment with one complete well and one partial well. It uses the real
Experiment Editor to select **View Older Experiment**, verifies the exact saved
targets and progress in the main window, validates the prefilled plate-reader
analysis preview, then opens the read-only editor directly and creates a fresh
editable copy with its **Create Editable Copy...** button. The report records
source hashes, disabled hardware controls, and zero machine/simulator dispatch.

Run it offscreen or visibly:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario legacy_experiment_read_only_v1 `
  --output-root verification_reports\legacy_read_only

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario legacy_experiment_read_only_v1 `
  --visible `
  --output-root verification_reports\legacy_read_only_visible
```

The lifecycle pytest entry point is:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_legacy_read_only.py
```

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
`print_array_smoke_24_v1`. The active `lifecycle` suite includes the verified
editor, older-experiment read-only, and 24-well soft-stop/resume scenarios.
Candidate gates remain executable directly but do not join the suite until
they pass; suite/capability CLI selection is not available yet.

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
60 seconds and retain the normal report-v1 evidence and five named
screenshots. After the final well completes, the same live session reopens the
printer-head calibration dialog and generates a synthetic diagnostic result.
The report proves the preview and diagnostic controls remain available while
Apply is unavailable and authoritative execution artifacts remain unchanged.
It then returns the final printer head through the normal rack UI, opens the
editor directly in read-only mode, and activates **View Completed Experiment**.
Any saved-progress choice popup is treated as a workflow failure.
The `execution.same_session_completed_projection_exact` assertion proves the
displayed assignments, targets, and completed progress match the authoritative
plan while the Controller stays idle, no machine/simulator command is
dispatched, and all experiment-directory files remain byte-identical. Its
evidence is stored at
`metrics.persistence.values.same_session_completed_projection`.

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

To exercise the completed-execution fresh-session boundary directly, run:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py
```

This reload check requires the printer-head diagnostic launcher to be disabled
with historical-analysis guidance and verifies that activation causes no
machine or simulator dispatch. If either boundary fails, retain the generated
report and inspect the `execution.completed_terminal_reload_exact` or
`calibration.post_completion_diagnostics_available` assertion evidence. For
the same-session completed-display boundary, inspect
`execution.same_session_completed_projection_exact` under
`metrics.persistence.values.same_session_completed_projection`.

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
droplet stock, updates reactions and stock solutions, and presses `Finalize Experiment`. It validates the
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
updates again and presses `Finalize Experiment`. Its target contract requires a single
renamed directory, a fresh revision-1 prepared plan for A1-A6, archived
superseded prepared artifacts, zero progress, consistent key files/runtime
assignments, and a `ready_to_start` reload.

An untouched `PREPARED` execution remains editable after disk reload. Both
Save and `Finalize Experiment` publish material pre-start edits through the same transactional
replacement path. Started, progressed, resumed, calibrated, or invalid
executions remain fail-closed and require the editable-copy workflow instead.

The Experiment Editor exposes five explicit lifecycle actions:

- `Finalize Experiment` is enabled for a new draft or editable `PREPARED` design.
  A `ready_to_start` eligibility result does not relabel an editable design.
- `Load Experiment` is enabled for a locked, inactive saved experiment whose
  authoritative runtime can be reconstructed.
- `View Completed Experiment` is enabled only for a valid authoritative
  `COMPLETED` execution. It closes the editor and populates the main plate,
  stock, reaction, well-assignment, target, and final-progress display from
  the saved plan and progress. Every assigned well is shown complete and the
  Experiment Guide reports `Next: Experiment complete`.
- `Experiment Loaded` is disabled when that saved experiment is already
  active.
- `Experiment Locked` is disabled for blocked, stopped, invalid, ambiguous, or
  otherwise non-activatable saved executions.

`Load Experiment` only restores the saved experiment setup and progress. It does not start or
resume printing; the operator must still use the applicable print/start or
resume action. Locked executions show a full-width lifecycle banner while the
lower status line remains available for transient details and errors.

`View Completed Experiment` is display-only. It does not activate the
authoritative runtime, create or repair a resume checkpoint, rewrite exports
or audit files, assign saved reagent heads to physical rack slots, change the
Controller out of `idle`, or send machine/simulator commands. Start Array,
plate calibration, and stock-preparation controls remain disabled while this
completed projection is displayed. Use `Create Editable Copy...` for any
change; the completed source remains byte-identical.

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
durable `calibration_started` lock when a result-producing calibration starts
against a prepared or active authoritative execution. A completed or aborted
execution in the same live session can still run and record pressure-sweep,
stream-volume, and recheck diagnostics without relocking or revising the
terminal plan; **Apply** remains unavailable. Reopened historical executions
remain analysis-only and cannot launch calibration processes.

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
folder, and selects `Load Experiment` before a real UI resume.

The scenario is active in the lifecycle suite. The persisted design is loaded
through the real editor without changing its authoritative disk identity,
`Load Experiment` restores the exact partial progress without starting or
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

### Milestone 12 safeguard matrices

Milestone 12 adds three Windows host-SIL matrices. They exercise real Qt
operator actions and pass only when the exact typed/UI outcome and the shared
no-mutation/no-dispatch oracle agree:

- `editor_safeguards_v1` (8 compact Finalize/Upload Design boundaries);
- `execution_preflight_safeguards_v1` (17 calibration, durable-identity, and
  lifecycle boundaries, including one reordered-row positive identity case);
- `authoritative_persistence_safeguards_v1` (9 isolated one-fault reload
  classifications).

Use the repository virtual environment on Windows. List or dry-run first, then
run a complete catalog or one visible case:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list matrices

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix editor_safeguards_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix execution_preflight_safeguards_v1 `
  --output-root verification_reports\milestone_12 `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 180

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix authoritative_persistence_safeguards_v1 `
  --case unreflected_pending_intent_blocked `
  --output-root verification_reports\milestone_12_visible `
  --seed 1 --speed-multiplier 20 --timeout-seconds 240 --visible
```

Run the exact replay command printed by each report or matrix aggregate; do
not reconstruct a negative fixture from memory. A complete matrix writes a
plan, aggregate, child logs, report-v1 trees, catalog/manifest hashes, and the
tracked matrix-registration row. Persistence faults are created before launch
only in test-owned copies beneath the current SIL scenario root. Never point a
fault case at a user experiment.

For a rejection report, inspect
`metrics.persistence.values.safeguard_boundary`: `failed_checks` must be empty,
all checks must be true, the observed typed/UI record must equal the literal
expected record, and dispatch counters must remain unchanged. Persistence
reports additionally retain `prelaunch_fault`, source/faulted inventories, and
the one-path fault manifest. Visible reports retain the rejection dialog or
locked-state screenshot; a missing-file screenshot naturally differs across
replay because it shows the new isolated absolute path.

The immutable Milestone 11A
`optimizer_360_calibration_reload_execution_v1` scenario remains the complex
positive control and is not a negative-case fixture. The preexisting
`print_array_stress_384x10_v1` pulse-width fixture/staging mismatch is also not
a Milestone 12 product failure. Use direct Milestone 12 matrices, the selected
optimizer-360 compatibility run, `lifecycle`, and `host_regression` as the
Milestone 12 gates; do not require or weaken evidence to make the entire
`host_stress` aggregate green.

If pytest cannot access its shared `%TEMP%\pytest-of-<user>` root in a sandbox,
give focused runs a unique repository-contained `--basetemp` beneath
`verification_reports`. The required final suite remains:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Allow at least 900000 ms when an external runner supplies a timeout.

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

### Bounded design/calibration lifecycle exploration

Milestone 13 adds the separately versioned
`design_calibration_lifecycle_v1` campaign without changing the Milestone 8
campaign or its schema-v1 replay contract. Its six release-blocking frozen
sequences use seeds `13, 29, 47, 83, 131, 197`; explicitly selected diagnostic
seeds are retained but never alter the frozen gate unless deliberately reviewed
and promoted.

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration design_calibration_lifecycle_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration design_calibration_lifecycle_v1 `
  --output-root verification_reports\exploration `
  --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration design_calibration_lifecycle_v1 `
  --sequence seed_47_illegal_editor_recovery_terminal `
  --output-root verification_reports\exploration `
  --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration design_calibration_lifecycle_v1 `
  --seed-tier diagnostic --diagnostic-seed 1 `
  --output-root verification_reports\exploration `
  --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
```

Always run the emitted `run.replay_command` verbatim. Frozen replay consumes
the retained normalized sequence or campaign plan and verifies its SHA-256; it
does not regenerate authoritative failure evidence from a seed. The aggregate
must report complete semantic coverage for all 12 states, 34 declared
transitions, 26 admitted operations, and eight rejection classes. Seed count
and action count are not coverage.

Each sequence fails closed above 18 semantic operations, 80 action rows, three
sessions/two rotations, four screenshots, 256 retained files/48 MiB, a
270-second scenario deadline, or a 300-second child watchdog. The six-sequence
campaign caps those values at 108/480, 18/12, 24, 1,600 files/320 MiB, and
1,800 seconds. Normal fixtures stay compact at four reactions, two stocks,
eight intents, and 44 droplets per sequence. The immutable
`optimizer_360_calibration_reload_execution_v1` case remains a separate stress
oracle; do not substitute it into every generated sequence.

Illegal/recovery sequences drive the real Qt rejection, require the exact
typed operator evidence, immediately reuse the Milestone 12 no-mutation/no-
dispatch oracle, and recover through valid actions on the same authoritative
lineage. Original failing normalized sequences are immutable evidence. The v1
campaign deliberately has no reducer; any future reduction must be separately
labeled diagnostic evidence and may never replace the original. Exploration
remains supplemental to deterministic Milestones 9-12 evidence and is not a
registered capability-coverage aggregate.

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

### Calibration storage-contract SIL

Milestone 1 adds two current-writer scenarios without changing production
calibration behavior or persisted schemas:

- `calibration_storage_contract_v1` runs the seven reviewed fixture families
  through the real `CalibrationManager` writers, then closes and reopens the
  MVC composition and selects/applies a persisted row through the real UI.
- `calibration_storage_legacy_baseline_8x25_v1` freezes eight synthetic heads
  with 25 process runs per head: 200 process recordings and 232 structured
  updates. Workload captures are disabled; a separate two-frame probe proves
  recorder drain behavior.

Run the focused host coverage with unique temporary roots outside the
repository when the default pytest root has stale Windows permissions:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_storage_contract_fixtures.py `
  tests\test_calibration_storage_fixture_sanitizer.py `
  tests\test_calibration_storage_scripted_process.py `
  tests\test_calibration_storage_baseline.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_calibration_storage_contract_performance.py
```

The developer-only sanitizer reads one explicitly selected legacy run/phase,
verifies that the source hash does not change, removes identities and paths,
and refuses to overwrite its reviewed output. Tests never invoke it and never
read `FreeRTOS-interface/Experiments`:

```powershell
.\env\Scripts\python.exe -m tools.sil.calibration_storage_sanitizer `
  --source <explicit-calibration.json> `
  --output <new-reviewed-fixture.json> `
  --fixture-id <fixture-id-v1> `
  --process-id <synthetic-process-id> `
  --run-index 0 `
  --phase <phase-key> `
  --step-index 0
```

Use repeated `--step-index` arguments to retain ordered multi-update shapes.
Review every generated fixture before adding it to the catalog.

The qualified Pi collection is explicit and uses the existing Bubblewrap
private-device lane:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <qualified-pi-host> `
  -Scenario calibration_storage_legacy_baseline_8x25_v1 `
  -HostLabel pi5-calibration-storage-legacy-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 3 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 1800
```

After the wrapper retrieves and validates the report set, freeze the
storage-specific candidate baseline. The command refuses to overwrite an
existing baseline and requires one clean warm-up plus exactly three clean,
passing measured Pi reports:

```powershell
.\env\Scripts\python.exe -m tools.sil.calibration_storage_baseline `
  --report-set <retrieved-report_set.json> `
  --output tests\performance\baselines\calibration_storage_legacy_pi5_v1.json
```

The baseline preserves the source/Pi/storage/Python/Qt identity, fixture and
workload hashes, exact counts, rewrite/append and first/last-quartile latency,
reload/history latency, RSS, and artifact growth. Result-finalize and index
latency remain `not_available_until_m2` because those artifacts do not exist
in the current writer.

The Milestone 1 candidate is tracked at
`tests/performance/baselines/calibration_storage_legacy_pi5_v1.json`. It was
qualified on a Raspberry Pi 5 with NVMe/ext4, Python 3.11.2, and PySide/Qt
6.7.1 from clean source commit
`ddea246c2aa89f492abf9cc8d4755e92af92d9f0`. It is valid only for the exact
environment, fixture, and workload identities embedded in the baseline.

If Qt session creation reports `WinError 5`, choose a new `--basetemp` under
`$env:LOCALAPPDATA\Temp\LabCraft`; do not place a SIL session root inside the
repository. If the baseline tool rejects evidence, retain the report set and
raw reports: count, hash, clean-source, Pi identity, safety-proof, and
environment mismatches are intentionally fail-closed.

This coverage proves only structured current-writer storage, recording,
summary isolation, reload, UI application, and deterministic capture-policy
proxies. It does not prove camera acquisition, image analysis, physical
calibration quality, firmware, serial/GPIO, motion, dispense, balance, or
pressure response.

Milestone 2 adds a non-authoritative canonical shadow store alongside those
unchanged writers and readers. Every calibration process now attempts to write
`calibration_recordings/<process>/<run>/updates.jsonl`, `result.json`, and
schema-v2 `run_meta.json`, followed by one rebuildable
`calibration_index.jsonl` event. The operator recorder toggle still controls
diagnostic events, analysis, verdicts, and captures; it does not disable the
structured shadow attempt. Existing `calibration.json` history and all current
application/UI readers remain authoritative.

The shadow path reports failures and continues through the legacy completion
path. For emergency developer rollback, set
`LABCRAFT_CALIBRATION_STORE_SHADOW=0` before launching the application. This is
not an operator data-retention control and must not be treated as the Milestone
3 capture-policy UI.

Run the Milestone 2 contract and composed SIL coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_recording_store.py `
  tests\test_calibration_recording_store_failures.py `
  tests\test_calibration_storage_scripted_process.py `
  tests\test_calibration_storage_shadow_baseline.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_shadow_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_calibration_storage_shadow_performance.py
```

The explicit qualified-Pi comparison uses the frozen Milestone 1 workload:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <qualified-pi-host> `
  -SshIdentityFile <optional-private-key-path> `
  -Scenario calibration_storage_shadow_8x25_v1 `
  -HostLabel pi5-calibration-storage-shadow-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 3 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 1800

.\env\Scripts\python.exe -m tools.sil.calibration_storage_shadow_baseline `
  --report-set <retrieved-report_set.json> `
  --legacy-baseline tests\performance\baselines\calibration_storage_legacy_pi5_v1.json `
  --output tests\performance\baselines\calibration_storage_shadow_pi5_v1.json
```

The shadow baseline requires a clean one-warmup/three-measured report set,
exact 200-process/232-update/200-result/200-index counts, matching Pi/storage
and fixture identities, and no material regression against the Milestone 1
candidate limits. It freezes separate candidate limits for canonical append,
result-finalize, and index latency. No camera, image-analysis, firmware,
protocol, motion, dispense, balance, or physical calibration claim is made.

The tracked Milestone 2 candidate is
`tests/performance/baselines/calibration_storage_shadow_pi5_v1.json`. It was
qualified from clean commit `0f93e037c26c8fa8d165e433a129f918b671643e`
on the same Raspberry Pi 5 NVMe/ext4, Python 3.11.2, and PySide/Qt 6.7.1
identity as the Milestone 1 baseline. All common timing/RSS comparisons pass.
The candidate upper limits are 17.514 ms for canonical update-append p95,
1.276 ms for result-finalize p95, and 4.416 ms for index-append p95. See
`docs/calibration_recording_store_milestone_2_completion.md` for the report
hashes, exact measurements, limitations, and rollback.

Milestone 3 makes the canonical store authoritative for every new calibration
process while retaining the legacy `calibration.json` dual-write and all
legacy readers. Each application session starts with `Key evidence` capture
retention. The calibration dialog now offers `Structured only`, `Key
evidence`, and `Full`; this choice is session-scoped and cannot change while a
process or capture-owned queue is active. `Structured only` still writes
canonical updates, terminal results, index events, diagnostic events, and
explicit capture-omission records—it only omits pixels. Dataset processes and
stream-gravimetric/refuel dataset acquisition require `Full` and reject lower
policies with operator guidance.

Canonical run creation and update fsync occur before the process starts and
before each legacy step is exposed. Completion is emitted only after capture
drain, minimum-evidence enforcement, result commit, index fsync, and final
metadata. New authority-marked legacy rows are applicable only when their
canonical reference, update hash chain, parity state, completed application
result, and committed index event validate. Historical legacy-only rows remain
available.

Run the Milestone 3 host coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_recording_store.py `
  tests\test_calibration_recording_store_failures.py `
  tests\test_calibration_storage_terminal_adapters.py `
  tests\test_calibration_capture_retention_policy.py `
  tests\test_calibration_storage_scripted_process.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_authoritative_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_calibration_storage_authoritative_performance.py
```

Run and freeze the qualified Pi candidate with:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_authoritative_8x25_v1 `
  -HostLabel pi5-calibration-storage-authoritative-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 3 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 1800

.\env\Scripts\python.exe -m tools.sil.calibration_storage_authoritative_baseline `
  --report-set <retrieved-report_set.json> `
  --shadow-baseline tests\performance\baselines\calibration_storage_shadow_pi5_v1.json `
  --output tests\performance\baselines\calibration_storage_authoritative_pi5_v1.json
```

The tracked Milestone 3 candidate is
`tests/performance/baselines/calibration_storage_authoritative_pi5_v1.json`.
It was qualified from clean commit
`430123e0312d308a5ee8fb4be87b869d9aad6f27` on the same Raspberry Pi 5
NVMe/ext4, Python 3.11.2, and PySide/Qt 6.7.1 identity as Milestone 2. All
200-run/232-update/result/index counts are exact, integrity failures are zero,
and every Milestone 2 timing/RSS comparison passes. See
`docs/calibration_recording_store_milestone_3_completion.md` for raw report
hashes, measured distributions, candidate limits, artifact growth, and the
qualification boundary.

Set `LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0` and restart the application
for operational rollback to the Milestone 2 legacy-authoritative checkbox and
recorder-toggle behavior. This leaves additive canonical artifacts intact.
Image analysis, physical camera behavior, firmware, protocols, motion,
pressure, and dispense remain outside this storage qualification.

Milestone 4A makes the canonical compact index the default source for
calibration prerequisites, characterization history, persisted selection,
preview/load, recheck context, and application. History reads only
`calibration_index.jsonl` plus the legacy compatibility document; result and
update bundles are opened only after a row is selected. New terminal results
carry `labcraft.calibration_recording.summary_projection` v1 rows, and applied
execution-calibration records use schema v2 with nullable result, process-run,
and update identities. Existing schema-v1 application records remain readable.

The canonical reader is mandatory as of Milestone 7. Set
`LABCRAFT_CALIBRATION_LEGACY_FALLBACK=0` to reject historical unmarked legacy
fallback. Authority-marked incomplete/corrupt data and canonical/legacy parity
conflicts are always blocked. Obsolete writer/reader rollback environment values
block new calibration startup with a diagnostic instead of silently selecting a
retired persistence path.

Index repair is never automatic. Preview an offline rebuild first, using the
exact experiment directory, then repeat with `--apply` only after reviewing the
reported bundle counts and errors:

```powershell
.\env\Scripts\python.exe -m tools.calibration_index_repair `
  --experiment-dir <experiment-directory>

.\env\Scripts\python.exe -m tools.calibration_index_repair `
  --experiment-dir <experiment-directory> `
  --apply
```

Apply refuses any invalid canonical bundle, atomically replaces the index, and
retains a content-hash-named backup of an existing index. It does not modify
run bundles or `calibration.json`.

Run the Milestone 4A host coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_recording_reader.py `
  tests\test_calibration_primary_reader.py `
  tests\test_calibration_index_repair.py `
  tests\test_execution_calibration_store.py `
  tests\test_calibration_storage_primary_reader_baseline.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_primary_reader_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_calibration_storage_primary_reader_performance.py
```

Run and freeze the qualified Pi candidate with:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_primary_reader_8x25_v1 `
  -HostLabel pi5-calibration-storage-primary-reader-v1 `
  -WarmupRuns 1 `
  -MeasuredRuns 3 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 1800

.\env\Scripts\python.exe -m tools.sil.calibration_storage_primary_reader_baseline `
  --report-set <retrieved-report_set.json> `
  --milestone3-baseline tests\performance\baselines\calibration_storage_authoritative_pi5_v1.json `
  --output tests\performance\baselines\calibration_storage_primary_reader_pi5_v1.json
```

This qualification covers structured persistence and reader integrity only. It
does not exercise camera acquisition, image analysis, physical motion,
pressure response, dispense behavior, firmware, or device protocols.

Milestone 4A was qualified on 2026-08-15 from clean commit `62d0e74e` on the
Raspberry Pi 5 NVMe/ext4 lane. The tracked candidate baseline is
`tests/performance/baselines/calibration_storage_primary_reader_pi5_v1.json`;
it passes every inherited Milestone 3 timing/RSS limit and records zero reader
integrity, fallback, or conflict events. Exact report hashes, reader limits,
host-test results, synchronization evidence, and rollback details are in
`docs/calibration_recording_store_milestone_4a_completion.md`.

### Calibration recording store Milestone 4B

Milestone 4B moves calibration memory, experiment audit references, record
export, recording-summary CSVs, pressure-sweep replay, and online-stream
emergence lookup to canonical recording identities. New calibration-memory
summaries use schema v2 and resolve their exact canonical session without
requiring `calibration.json`. Legacy files and diagnostic `analysis.jsonl`
remain readable and are retained in exports when present.

The secondary-consumer reader defaults to canonical. To roll back only this
slice for one application process, set this value and restart:

```powershell
$env:LABCRAFT_CALIBRATION_SECONDARY_READER = "legacy"
```

Run the focused and registered SIL coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_recording_reader.py `
  tests\test_calibration_recording_updates.py `
  tests\test_calibration_memory_store.py `
  tests\test_calibration_memory_aggregator.py `
  tests\test_calibration_record_export.py `
  tests\test_calibration_recording_summary_tool.py `
  tests\test_calibration_secondary_consumer_inventory.py `
  tests\test_calibration_storage_secondary_reader_baseline.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_calibration_storage_secondary_reader_contract_lifecycle.py

.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  tests\system\test_calibration_storage_secondary_reader_performance.py
```

The storage journeys emit one-line `SIL_PROGRESS` JSON at phase boundaries
and every 25 processes in the 200-process workload. The Pi wrapper streams
remote SSH output immediately, so a terminal advances through 0, 25, 50, ...,
200, then `fresh_reload`, `secondary_memory`, `secondary_summary`, and
`secondary_export`. Long gaps can still be normal because the retained legacy
writer rewrites its growing whole-file document.

Pi qualification and baseline freezing use:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_secondary_reader_8x25_v1 `
  -HostLabel pi5-calibration-storage-secondary-reader-v1 `
  -WarmupRuns 0 -MeasuredRuns 1 `
  -SpeedMultiplier 1000 -TimeoutSeconds 3600

.\env\Scripts\python.exe -m tools.sil.calibration_storage_secondary_reader_baseline `
  --report-set <retrieved-report-set.json> `
  --milestone4a-baseline tests\performance\baselines\calibration_storage_primary_reader_pi5_v1.json `
  --output tests\performance\baselines\calibration_storage_secondary_reader_pi5_v1.json
```

Milestone 4B uses no warm-up and one measured Pi pass. The resulting
baseline is candidate, single-sample evidence; it detects large regressions
but does not claim multi-run statistical stability. Use the 3,600-second
scenario budget on the qualified Pi. The retained
whole-file legacy writer made the frozen 200-process workload take about 37
minutes during qualification; 1,800 seconds can therefore expire after the
workload succeeds but before final artifact inspection.

The complete consumer inventory is tracked at
`tools/virtual_workflows/fixtures/calibration_storage_secondary_consumers_v1.json`.
Image-analysis SIL, historical conversion, stopping legacy writes, firmware,
and physical-device behavior remain outside this milestone.

### Calibration recording store Milestone 5

Milestone 5 provides an explicit offline converter for historical
`calibration.json` records. It creates additive canonical run bundles, index
events, and `calibration_history_migration.json`; it never rewrites the source
`calibration.json` or matching diagnostic recordings. Ambiguous diagnostic
links and unsupported shapes are reported and skipped instead of guessed.

Always begin with a dry run against one exact experiment directory:

```powershell
.\env\Scripts\python.exe tools\convert_calibration_history.py `
  --experiment-dir <exact-experiment-directory>

.\env\Scripts\python.exe tools\convert_calibration_history.py `
  --experiment-dir <exact-experiment-directory> --apply

.\env\Scripts\python.exe tools\convert_calibration_history.py `
  --experiment-dir <exact-experiment-directory> --resume

.\env\Scripts\python.exe tools\convert_calibration_history.py `
  --experiment-dir <exact-experiment-directory> --validate
```

The default text progress is flushed immediately. Use `--progress json` for
machine-readable `CALIBRATION_MIGRATION_PROGRESS` lines or `--progress none`
for quiet operation. A completed conversion is idempotent; interrupted work
must be continued explicitly with `--resume`. The CLI refuses the repository,
the complete `Experiments` directory, the user's home directory, and a
filesystem root as conversion targets.

To create a review fixture from selected historical shapes, use the separate
sanitizer with explicit `RUN_INDEX:PHASE:STEP_INDEX` selectors and a new output
path. It hashes every selected source before and after, refuses to overwrite,
redacts identities/timestamps/paths/notes, and never copies pixels:

```powershell
.\env\Scripts\python.exe -m tools.sil.calibration_history_conversion_sanitizer `
  --source <experiment>\calibration.json `
  --fixture-id <review-fixture-id> `
  --select 0:pressure_sweep_characterization:0 `
  --output <new-fixture-path>.json
```

Generated migration results are included by default after their completed
manifest validates. To hide all generated conversion results without deleting
anything, set the following value and restart the application:

```powershell
$env:LABCRAFT_CALIBRATION_MIGRATED_RESULTS = "0"
```

Run the focused and compact lifecycle coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_history_conversion_fixtures.py `
  tests\test_calibration_history_conversion.py `
  tests\test_calibration_history_conversion_failures.py `
  tests\test_calibration_history_conversion_cli.py

.\env\Scripts\python.exe -m pytest -q -s --run-sil-lifecycle `
  tests\system\test_calibration_history_conversion_contract_lifecycle.py
```

The lifecycle converts a reviewed 12-step fixture into nine canonical bundles,
retains one already-canonical record, reports two explicit skips, fresh-loads
the real MVC composition, applies one migrated calibration through the
simulator, and validates export and idempotence. It normally completes in a
few seconds and prints MVC, planning, bundle, index, validation, reload, and
export checkpoints. Milestone 5 intentionally does not rerun the earlier
200-process/232-update performance workload; the converter does not change the
online writer path. The Pi gate is likewise one compact run:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_historical_conversion_contract_v1 `
  -HostLabel pi5-calibration-storage-migration-v1 `
  -WarmupRuns 0 -MeasuredRuns 1 `
  -SpeedMultiplier 1000 -TimeoutSeconds 120
```

This coverage claims structured storage conversion, canonical-reader use, and
source immutability only. It does not claim camera/image-analysis correctness,
physical calibration quality, firmware, motion, pressure response, or dispense
behavior.

### Calibration recording store Milestone 6

New experiment designs now persist this explicit storage policy and use the
canonical recording store without creating or rewriting `calibration.json`:

```json
{
  "calibration_storage": {
    "schema_name": "labcraft.calibration_storage.policy",
    "schema_version": 1,
    "legacy_writer_mode": "canonical_only"
  }
}
```

Designs created before this field existed remain `legacy_compatible`, so their
existing `calibration.json` remains readable but is never rewritten. A design-only duplicate is
a new design and therefore starts canonical-only with no copied calibration
history. Structured persistence remains mandatory and capture retention remains
independent.

Milestone 7 retired the emergency writer and legacy-primary-reader switches.
`LABCRAFT_CALIBRATION_LEGACY_WRITER=1`,
`LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0`, or a legacy primary/secondary
reader selection now blocks new calibration startup until the value is removed
and the application is restarted. Historical files remain readable.

Run the focused and compact lifecycle coverage with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_legacy_writer_policy.py `
  tests\test_calibration_storage_scripted_process.py `
  tests\test_experiment_duplicate_design.py

.\env\Scripts\python.exe -m pytest -q -s --run-sil-lifecycle `
  tests\system\test_calibration_storage_new_store_only_contract_lifecycle.py
```

The lifecycle emits flushed `SIL_PROGRESS` checkpoints for setup, all 16
fixture processes, secondary consumers, and fresh application. It proves the
main experiment performs zero legacy writes while one historical canary remains
byte-identical as canonical data is added beside it. It normally completes in about
15 seconds on the Windows host. Milestone 6 does not rerun the retired
200-process/232-update workload; the Pi gate is one compact measured pass:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_new_store_only_contract_v1 `
  -HostLabel pi5-calibration-storage-new-store-only-v1 `
  -WarmupRuns 0 -MeasuredRuns 1 `
  -SpeedMultiplier 1000 -TimeoutSeconds 180
```

This coverage claims canonical structured persistence, canonical readers, and
legacy-reader compatibility only. It does not claim camera/image-analysis
correctness, physical calibration quality, firmware, motion, pressure response,
or dispense behavior.

### Calibration recording store Milestone 7 proving period

The legacy calibration writer has been removed from the production path.
`calibration.json` is a read-only typed-fallback source; new updates, terminal
results, and index events are committed only through `calibration_recordings`
and `calibration_index.jsonl`. The Capture retention selector controls pixels,
not structured persistence. Each application session defaults to `Full` so
every recorder-requested image is available for offline calibration diagnosis;
operators may select a lower-retention policy for future runs.

The proving tool scans only explicitly named experiment directories, validates
indexed terminal bundles, hashes every source file before and after collection,
redacts head/stock identities, refuses to overwrite reports, and prints flushed
`CALIBRATION_STORAGE_PROVING_PROGRESS` lines:

```powershell
.\env\Scripts\python.exe -m tools.calibration_storage_proving init `
  --campaign-id calibration-store-m7 `
  --source-commit <deployed-commit> `
  --output verification_reports\calibration-proving\campaign.json

.\env\Scripts\python.exe -m tools.calibration_storage_proving collect `
  --campaign verification_reports\calibration-proving\campaign.json `
  --experiment-dir <explicit-experiment-directory> `
  --output verification_reports\calibration-proving\snapshot-YYYYMMDD.json

.\env\Scripts\python.exe -m tools.calibration_storage_proving evaluate `
  --campaign verification_reports\calibration-proving\campaign.json `
  --snapshot <snapshot-1.json> --snapshot <snapshot-2.json> `
  --issue-ledger docs\calibration_storage_proving_issue_ledger_template.json `
  --pi-report-set <pi-report-set-1.json> --pi-report-set <pi-report-set-2.json> `
  --output verification_reports\calibration-proving\assessment.json
```

The gate requires at least 14 days, 20 completed calibrations across three
printer heads, two passing compact Pi report sets, unchanged sources, and no
open storage/integrity issues. Copy the issue-ledger template and set its
campaign ID before use. The compact SIL remains the 16-process
`calibration_storage_new_store_only_contract_v1` scenario (normally about 15
seconds); the retired 200-process workload is not part of Milestone 7.

Milestone 7 does not create release candidates, tags, or offline bundles.

### Calibration dialog application-lifetime lifecycle

The application constructs one calibration manager and one pair of calibration
camera models at startup. The primary Droplet Imager window is constructed on
first use and then reused. Closing it stops cameras and timers, disconnects its
session-only callbacks, and releases the calibration pressure profile, while
retaining completed prerequisites and the selected capture-retention policy.
Changing experiments resets experiment-scoped calibration state on the same
manager. Application shutdown performs the final writer and model cleanup.

Run the focused lifecycle coverage and the short eight-reopen SIL scenario with:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_calibration_subsystem_lifecycle.py `
  tests\test_pressure_plotbox_buttons.py `
  tests\test_controller_signal_scoping.py `
  tests\test_safe_application_construction.py `
  tests\test_droplet_imaging_refuel_panel.py

.\env\Scripts\python.exe -m pytest -q -s --run-sil-lifecycle `
  tests\system\test_calibration_dialog_reopen_lifecycle.py
```

The SIL scenario prints one `SIL_PROGRESS` JSON record containing stable object
identities, callback and camera start/stop counts, hidden receiver counts,
timer/thread observations, and capture latency. It uses simulated controllers
and does not access camera, serial, GPIO, firmware, or other physical devices.

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
private `/dev`, mounts the repository read-only after creating its private
`/tmp`, makes only the report root and temporary Qt directories writable, and
unshares the network. Rebinding the repository after the private `/tmp` mount
allows a disposable checkout below `/tmp` to remain visible without making it
writable. There is no unsandboxed Pi option. The output root remains on the
Pi's normal filesystem, so persistence measurements still exercise its real
storage.

If Bubblewrap reports that a repository or its Python launcher below `/tmp`
does not exist, confirm the checkout contains this read-only repository
rebind, the configured `RemoteRepo` is the intended disposable checkout, and
the repository-local `venv`, `.venv`, or `env` launcher works before starting
collection. Do not move the qualification checkout outside its approved
temporary root to bypass the failure.

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

After the attending operator has given fresh authorization for the exact
campaign, known confirmation-only gates can be consumed without pausing for
another terminal response:

```bash
python tools/run_qualification_campaign.py --campaign machine_full_qualification_v1 --operator-prompts --preauthorize-confirmation-prompts --port /dev/ttyAMA0
python tools/run_qualification.py --manifest coordinated_xy_production_mres3_v7 --operator-prompts --preauthorize-confirmation-prompts --fixture coordinated_xy_production_mres3_envelope_clear --port /dev/ttyAMA0
```

`--preauthorize-confirmation-prompts` is opt-in and requires
`--operator-prompts`. It auto-resumes only the runner's explicit allowlist of
confirmation-only stages, including the coordinated XY envelope and bounded
crossing readiness gates. Every automatic response is retained in the raw and
normalized reports with `mode=preauthorized`. Prompts that require a physical
action remain interactive; these include evaporation-plate placement, manual
X/Y switch press/release, and gripper load/support/removal. An unrecognized
future operator gate is never automatically resumed and therefore fails closed
if the host has not been updated to classify it.
The option is not unattended authority and does not replace the fresh attended
confirmation, FULL-profile authorization, fixture checks, emergency-stop
access, or final firmware restoration required by the development workflow.

The raw self-test and legacy HIL pass-throughs use the same explicit option:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --preauthorize-confirmation-prompts --out hil_reports/selftest.json
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29 -Profile FULL -PreauthorizeConfirmationPrompts
```

Interactive prompt time is excluded from the self-test hard deadline, and the
progress/activity watchdog timestamps are rebased when an operator responds so
a valid long pause cannot cause an immediate stale-progress failure.

Run the dedicated refuel-vacuum pressure-sensor qualification suite:

```bash
python tools/run_qualification.py --manifest refuel_vacuum_v1 --operator-prompts --fixture refuel_vacuum_dry_back_v1 --port /dev/ttyAMA0
```

Run the Milestone 1 legacy X/Y ISR timing suite only after confirming the full
gantry envelope is clear. It homes Z and XY, requires a passing 6 kHz safety
probe, and then executes the five 40 kHz measurement vectors:

```bash
python tools/run_qualification.py --manifest motion_timing_v1 --operator-prompts --fixture motion_clear_envelope_v1 --port /dev/ttyAMA0
```

Run the Milestone 2 normalized-cosine benchmark independently of motion with:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --profile-lut-benchmark --out hil_reports/profile_lut_benchmark.json
python3 tools/run_qualification.py --manifest profile_lut_benchmark_v1 --machine-id LC-001 --raw-report hil_reports/profile_lut_benchmark.json
```

`--profile-lut-benchmark` explicitly selects P3 value `2039` and returns only
SAFE performance result `2030 profile_lut_cycle_benchmark_safe`. It is not
part of ordinary SAFE. The diagnostic performs no Stepper, Gantry, GPIO,
pressure, valve, or homing operation. It reports LUT and legacy cycle maxima
and means, speedup, short/long preparation cost, ARR error, interrupt-state
restoration, and a deterministic checksum. The manifest enforces the 180 MHz,
225-cycle maximum, 4x speedup, 1,800-cycle preparation, two-tick error, and
interrupt-restoration gates.

### Coordinated XY production closeout

Milestone 7 makes one coordinated-XY implementation permanent. Normal
`ABSOLUTE_XY` commands use the fixed-point TIM2 executor with MRES=3,
DEDGE enabled, multistep filtering disabled, one interrupt per active STEP
transition, and the 1,125-tick conditional late-rearm guard. Because DEDGE
makes both rising and falling transitions advance the driver, each transition
is one historical logical coordinate unit. `MotionUnitScale`
keeps application commands, stored positions, status, home distances, rates,
and acceleration in the historical MRES=2 logical units. The coordinated
planner therefore consumes logical active-edge counts and the unchanged
40 kHz / 140 kHz/s limits directly; no native complete-cycle conversion is
applied to this path. Ordinary cosine
profile X/Y/Z moves use the normalized LUT; homes, limit soft stops, P/R, and
alternate direct profiles retain their specialized paths.

The former complete-pulse scheduler placed a minor-axis rise/fall pair close
together and then left a long inactive gap. That shape was most visible on
the incident shallow vectors `(17100,4470)`, `(17100,2054)`, and
`(100,19574)`. The active-edge DDA now distributes every selected transition
over the master timeline: minor-axis gaps are respectively 3-4, 8-9, and
195-196 callbacks, including signed and axis-swapped forms, with no more than
one edge of cross-track error. At 40 kHz with the 90 MHz timer clock, ARR
remains 2249; callback load and nominal move duration do not increase.

X and Y retain independent STEP phases initialized from the output GPIOs.
Pause stops immediately when both STEP pins are low. If either pin is high,
the next valid timer interval emits and accounts the required cleanup falling
edge before entering the paused state, so no STEP output is held high during a
pause. Resume discards the old profile cursor and plans only the remaining
distance to the retained endpoint, starting at no more than 3 kHz and
accelerating under the original move's cruise and acceleration limits. Direct
X/Y/Z resume uses the same remaining-endpoint rule. Ordinary unpaused starts
retain their existing profile. Cancel, confirmed limits, and post-edge
scheduling faults continue to use the bounded STEP-low terminal path.

X and Y use an edge-aware, hardware-timed 15 ms confirmation path. Both edges
on PG6/PG9 feed EXTI; the first asserted edge masks only that line and arms its
independent TIM5 compare channel on the continuously running 1 MHz counter.
Any intervening edge is retained in hardware/software evidence and rejects the
old window. An input that ends high must then serve a complete new 15 ms
window; an input that ends low is safely unmasked. TIM5 publishes only a
confirmed axis, and the next direct-axis or coordinated motion interrupt uses
the existing STEP-low abort path. Motion-timer level samples cannot create or
advance an X/Y assertion candidate. If TIM5 initialization or arming is not
valid, an asserted candidate confirms immediately as the fail-safe behavior.
TIM5 channel 3 is reserved for the non-actuating 15,000-16,000 us diagnostic
timing check. Z/P/R retain their existing EXTI/software-timer and direct-step
sampling path, including Z's active-high/no-pull electrical configuration.
The pressure-regulator PG13/PG14 inner switches retain their independent 15 ms
deferred notification.

The production timing contract uses a 2,600-core-cycle active-handler
regression budget and a 3,500-cycle post-motion terminal-handler budget. The
active budget is the 2,134-cycle worst case measured after the active-edge
migration plus approximately 20% margin, rounded up. It is not the physical
40 kHz deadline: a 25 us active-edge interval is 4,500 core cycles at 180 MHz,
so the regression budget retains 1,900 core cycles of raw interval margin.
Zero deadline misses, at least 450 timer ticks of measured slack, the
1,125-tick conditional-rearm guard, and zero pending-at-rearm observations
remain the scheduling-safety gates. Terminal work occurs once after the final
STEP edge while TIM2 is stopping. Pre-handler and full-IRQ timing remain
diagnostic evidence rather than independent acceptance limits.

The supported coordinated-motion selectors are now:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-production-mres3-suite --timeout-ms 300000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_production_mres3_v7.json
python3 tools/run_qualification.py --manifest coordinated_xy_production_mres3_v7 --operator-prompts --fixture coordinated_xy_production_mres3_envelope_clear --fixture coordinated_xy_production_mres3_limit_crossings_ready --machine-id LC-001 --raw-report hil_reports/coordinated_xy_production_mres3_v7.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --motion-pause-resume-suite --timeout-ms 180000 --status-only-timeout-ms 120000 --out hil_reports/motion_pause_resume_v1.json
python3 tools/run_qualification.py --manifest motion_pause_resume_v1 --operator-prompts --fixture motion_pause_resume_envelope_clear --machine-id LC-001 --raw-report hil_reports/motion_pause_resume_v1.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-shallow-edge-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_shallow_edge_v4.json
python3 tools/run_qualification.py --manifest coordinated_xy_shallow_edge_v4 --operator-prompts --fixture coordinated_xy_shallow_edge_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_shallow_edge_v4.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --direct-xyz-lut-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/direct_xyz_lut.json
python3 tools/run_qualification.py --manifest direct_xyz_lut_v1 --operator-prompts --fixture direct_xyz_lut_envelope_clear --machine-id LC-001 --raw-report hil_reports/direct_xyz_lut.json

python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-camera-transition-suite --timeout-ms 180000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_camera_transition_v4.json
python3 tools/run_qualification.py --manifest coordinated_xy_camera_transition_v4 --operator-prompts --fixture coordinated_xy_camera_transition_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_camera_transition_v4.json
```

Production selector `2097` now emits results
`[2087,2088,2089,2090,2098,2106,2107,2105]`. Result `2098` proves TIM5 is running at
1 MHz, channel 3 services a 15 ms deadline within 15,000-16,000 us, the timing
infrastructure has no failures, and ten clean production moves produce no X/Y
confirmations. Results `2106` and `2107` run six two-second pause/resume cases
each at the application maxima (40 kHz coordinated XY and 30 kHz direct Z),
require STEP-low stable holds, exact 3 kHz fresh-plan starts, endpoints, enabled
outputs, exactly one bounded TMC ENN rearm plus a 130 ms powered settle per
resume, and at most 25 logical units of post-run home drift. Each axis first
performs an unmeasured settling home so the measured
reference and post-run homes share the same calibrated coordinate frame.
Status telemetry is enabled only across the XY and Z motion windows so the
focused run also provides a real cadence gate. Operator-gated result `2105`
then performs one bounded physical
crossing per axis at 3 kHz. Each axis starts at the normal 100-step home
backoff, receives only a 200-step command toward the optical trigger, must
report the correct terminal axis with both STEP outputs low and no more than
50 post-edge steps, and must release/home successfully before the next axis.

The completed Z speed-ladder experiment selected the existing 30 kHz logical
rate and 140,000 logical steps/s^2 acceleration for production. Its firmware
selector (`2199`), TIM10 diagnostic hooks, and report code have been removed.
Manifests `z_speed_ladder_v1` through `v3` and catalog rows `2190` through
`2197` remain archived for raw normalization of retained historical reports;
they cannot launch hardware and consume no MCU flash.

Only the normal `Debug` firmware image is built and versioned. The former
`MRES3_Diagnostic` configuration and its separate binary were removed. The
headless build script exits before copying an artifact when compilation fails,
so `firmware/artifacts/LabCraft_firmware.bin` cannot be silently replaced by a
stale failed-build output.

Before loaded-rack use, run the shallow-edge suite with non-dispensing test
heads and a clear envelope. Then perform 20 attended rack operations: five
pause-to-Slot-1 unloads, five pause-to-Slot-2 unloads, five Slot-1-retreat to
Slot-4-approach transfers, and five reverse Slot-4-to-Slot-1 transfers. Home
XY after each five-operation block and require no more than 25 logical units
of drift on either axis. Finally run one attended four-head experiment and
apply the same drift gate. Stop immediately for collision, loss of holding
torque, abnormal sound, or visible gantry skew; do not return the printer to
unattended operation until all automated and physical gates pass.

Result `2099` includes `mf`, the bitwise OR of the exact per-move failure
masks, plus `am`, `tm`, `de`, `sg`, and `wd` timing/status maxima. A passing
run requires `mf=0`. The Windows HIL wrapper downloads and summarizes the JSON
report even when the remote self-test exits nonzero, so first-failure evidence
is retained locally instead of remaining only on the Pi.

Camera-transition result `2071` retains `fs` as its overall stage code and now
adds `mf`, the exact OR of measured coordinated-move failure bits, `ab=2600`,
and the observed active/terminal handler maxima `am`/`tm`. Thus a positioning
or home failure can report a nonzero `fs` with `mf=0`, while an active-handler
overrun reports bit 18 (`mf=262144`) without hiding the safe STEP/ownership or
home evidence. These fields are emitted by a bounded, host-tested formatter
and fit the existing result frame; result ID, name, and protocol layout do not
change.

Shallow-edge manifest v4 also expects result `2100`,
`coord_xy_terminal_timing`. Terminal-budget-only failures remain acceptance
failures but may continue because they occur after the final accounted edge
while TIM2 is stopping; every other failure remains fail-fast. The suite thus
collects 12 terminal samples at 10 kHz and 12 at 40 kHz whenever bit 19 is the
only anomaly. Metrics `tl*`, `ta*`, `tm*`, and `ob*` are the per-tier minimum,
integer mean, maximum, and over-budget count. For the same worst handler
sample, `cm`, `sm`, and `im` split common edge/schedule work,
timer/axis/event shutdown, and instrumentation; `pm` and `fm` report
pre-handler and full-IRQ time. `av` must remain zero so the three handler
stages exactly account for the terminal total. High `cm`, `sm`, or `im`
localizes handler work, while normal handler stages with high `pm`/`fm`
indicates IRQ/HAL or preemption latency. Manifest v1 remains archived.

The 40 kHz shallow tier is a requested active-edge cap, not a promise that a
finite move reaches that rate. With the production acceleration, the 17,100
master-edge vectors use a 36,986 Hz triangular peak (`ARR=2432`, start
`ARR=12160`) and the 19,574-edge vectors use 39,571 Hz (`ARR=2273`, start
`ARR=11365`). At 10 kHz both lengths reach the cap (`ARR=8999`, start
`ARR=44995`). These fixed expectations are independent of sign and axis swap;
an unknown tier/vector combination fails closed before its measured move.
Manifests v1 through v3 remain archived for historical normalization.

With `-CoordinatedXyShallowEdgeSuite`, the Windows wrapper defaults to a
240,000 ms self-test timeout and a 120,000 ms status-only timeout. Explicit
timeout parameters still override those suite defaults.

The recorded rollback baseline is source commit
`00be6ddf633e01f4d757725844af57ee8aa1eb3e` with firmware SHA-256
`02D74A4B24FFC40DEC07A4932B9A2B34D037B518DABFE2DBDB9FC4ABE68613D9`.
If any gate fails, stop rack testing and restore that source and its matching
binary together. Never combine firmware built from one revision with source
from another.

The active-handler rebaseline used shallow-edge maximum 1,964 cycles and two
production observations of 2,134 and 2,122 cycles. The retained production
rerun recorded zero deadline misses and 692 timer ticks of minimum slack in
`coordinated_xy_production_mres3_v4_20260817_145357.json`, SHA-256
`8DE50A087AC493E784607D835D8586FDD919B001BBD95068065B6615A4BD17A3`.
Its immediate rollback artifact is 332,760 bytes with SHA-256
`9A6A8A712AE6732D02D8F29BB172C10327474E4BC053C9F874F5C2F998A06127`;
the matching pre-rebaseline dirty source state is identified by binary-diff
fingerprint `824956a4cbfa79af0e80a5553d1303f9eb9108c8` over commit
`00be6ddf633e01f4d757725844af57ee8aa1eb3e`.

Superseded coordinated-XY manifests are marked `archived`. They remain usable
with `--raw-report` to normalize retained evidence, but are hidden from the
qualification UI, rejected by campaigns, and cannot launch hardware. Their
old self-test selector flags are no longer accepted. The command `feedHz`
parameter remains intentionally ignored by the current normal XY route; making
it authoritative is a separate follow-up because it changes motion behavior.

### Archived coordinated-XY development record

The Milestone 4 through Milestone 6 material below is retained as the design
and HIL history. Its diagnostic build commands and retired selector commands
describe historical artifacts and must not be used to launch current firmware.

The Milestone 4 gated coordinated-executor suite completed its corrected 3 kHz
qualification. It remains an explicit regression suite and still requires a
clear motion envelope plus manual verification of both limit inputs:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-executor-suite --out hil_reports/coordinated_xy_executor.json
python3 tools/run_qualification.py --manifest coordinated_xy_executor_v1 --operator-prompts --fixture motion_clear_envelope_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_executor.json
```

`--coordinated-xy-executor-suite` explicitly selects P3 value `2049`. Before
any motion, it disables both XY motors and requires manual press/release
verification of each physical limit input. A failed input check aborts the
suite. After hands are removed, it homes Z and homes X/Y sequentially at a
reduced 3 kHz/1 kHz rate, moves to `(5000,5000)`, and runs short X-only,
Y-only, equal, asymmetric, pause/resume, cancel, and injected-limit cases at
3 kHz. The operator must keep the entire motion envelope clear, stop
immediately on unexpected contact, and report whether the equal and asymmetric
ramping paths appear straight.

The Milestone 5 candidate enables normal `ABSOLUTE_XY` routing through the
coordinated TIM2 executor while retaining the compile-time legacy override.
It is a 3 kHz integration candidate only; do not use it for production-speed
motion before Milestone 6. Run the operator-gated normal-route suite with:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --normal-xy-route-suite --out hil_reports/normal_xy_route.json
python3 tools/run_qualification.py --manifest normal_xy_route_v1 --operator-prompts --fixture coordinated_xy_physical_limit_v1 --machine-id LC-001 --raw-report hil_reports/normal_xy_route.json
```

`--normal-xy-route-suite` selects P3 value `2059` and emits results `2050`-
`2057`. The suite disables XY before manual X/Y pressed/released checks, homes
Z and then X/Y at reduced rates, temporarily caps normal XY motion at 3 kHz,
and exercises normal-route completion, status cadence, pause/cancel recovery,
legacy direct-axis paths, and bounded physical X/Y limit crossings. Each
physical-limit move starts at `+100` and cannot command past `-100`. Stop the
suite immediately for aggressive contact, travel beyond that 200-step window,
abnormal sound, or reset.

Pressure is qualified separately after removing the motion fixture and
installing the approved closed-loop fixture:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-regulator-suite --timeout-ms 240000 --out hil_reports/pressure_regulator.json
python3 tools/run_qualification.py --manifest pressure_regulator_v1 --operator-prompts --fixture pressure_closed_loop_v1 --machine-id LC-001 --raw-report hil_reports/pressure_regulator.json
```

The ten-test pressure suite takes longer than the generic 90-second FULL
window; retain the explicit 240-second host timeout so settling progress is not
mistaken for a stalled diagnostic.

Milestone 6 qualifies the normal coordinated route at production speed while
the approved closed-loop pressure fixture is installed. The suite uses P3
selector `2069`, emits results `2060`-`2068` plus focused investigation result
`2070`, stops before every later row after
the first failure, and retains the configured 40 kHz X/Y cap:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-performance-suite --timeout-ms 900000 --out hil_reports/coordinated_xy_performance.json
python3 tools/run_qualification.py --manifest coordinated_xy_performance_v1 --operator-prompts --fixture pressure_closed_loop_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_performance.json
```

After a failed post-40 kHz home reference, run the focused direction-isolation
gate before rerunning the full suite:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-x-direction-suite --timeout-ms 300000 --out hil_reports/coordinated_xy_x_direction.json
python3 tools/run_qualification.py --manifest coordinated_xy_x_direction_v1 --operator-prompts --fixture pressure_closed_loop_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_x_direction.json
```

This selector emits only result `2070`; it cannot continue into the ordinary
40 kHz geometry, raster, camera-repeat, or pressure-stress rows.

To distinguish a cold camera-vector/ownership transition from cumulative
driver loading, run the shorter camera/home transition selector:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-camera-transition-suite --timeout-ms 180000 --out hil_reports/coordinated_xy_camera_transition.json
python3 tools/run_qualification.py --manifest coordinated_xy_camera_transition_v1 --operator-prompts --fixture motion_clear_envelope_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_camera_transition.json
```

Selector `2078` emits only result `2071`. It homes Z and then X/Y, uses the
qualified 5 kHz route to position at `(8916,30500)`, executes exactly one
40 kHz camera-ratio round trip through `(500,500)`, and immediately starts the
bounded legacy X home. The result records exact coordinated pulse/callback
totals, both X enable-output states, STEP-low/ownership state, the raw X limit
state, bounded-home phase/outcome/accounting, and final legacy TIM2 evidence.
It does not actuate pressure or continue into any other Milestone 6 row.

To isolate the complete 40 kHz geometry row from all preceding speed tiers and
the focused X-direction workload, run:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-40khz-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_entry_lateness.json
python3 tools/run_qualification.py --manifest coordinated_xy_40khz_v1 --operator-prompts --fixture motion_clear_envelope_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_entry_lateness.json
```

Selector `2077` emits the existing result `2064` plus timing-evidence results
`2072` and `2073`. It performs the normal
Z and sequential X/Y reference homes, runs the exact ten-move 40 kHz geometry
row, performs the existing bounded post-row X/Y homes, restores the production
rate caps, and exits. It does not run the 5-30 kHz tiers, result `2070`, raster,
camera-repeat, or pressure cases. Result `2072` correlates each TIM2 callback's
earliest user-code IRQ timestamp, Gantry-handler entry, pending-update state,
and the timestamp immediately after `HAL_TIM_IRQHandler()` returns. Metrics
include callback/sample counts (`i2`/`s`), missing correlations (`mi`),
pre-handler maximum/mean (`ph`/`pa`), full software IRQ maximum/mean
(`fm`/`fa`), non-terminal full-path maximum (`ax`), terminal full-path maximum
(`tf`), pending-correlated pre/full maxima (`pp`/`pf`), pending count/streak
(`pu`/`ps`), and saturation (`sf`).
This timing begins at the first TIM2 user-code instruction; it does not include
hardware exception-entry latency before the C handler starts or exception
return after the final timestamp.

The coordinated profile applies its cosine to velocity squared and transforms
the result into the fixed-point timer-period LUT. With the default 140,000
steps/s2 setting, the 40 kHz ramp is 10,000 master steps and its calculated
smooth-envelope peak is approximately 131,100 steps/s2. Each 20,000-step
selector-2077 leg still reaches the exact 40 kHz target at the phase join; this
corrects the former ARR-cosine profile's approximately 443,900 steps/s2 peak
without silently lowering the focused test rate.

Result `2073` captures TIM2 `CNT` and `ARR` beside that first DWT timestamp,
before HAL dispatch and without calling HAL or FreeRTOS. It reports callbacks
(`i2`), valid/missing entry samples (`s`/`mi`), maximum/mean entry counter
(`cm`/`ca`, in 90 MHz timer ticks), pending-correlated maximum (`pm`), entries
at or above the diagnostic 128-tick threshold (`lc`), maximum positive
inter-entry schedule overrun (`dm`, in 180 MHz core cycles), status
synchronization mode (`sm=0` for the production critical section), saturation
(`sf`), status-synchronization lock failures (`lf`), and timeout (`to`). It also
retains the first failed movement leg as failure-valid (`fv`), terminal reason
(`tr`: 0 none, 1 completed, 2 canceled, 3 X limit, 4 Y limit, 5 planner fault),
coordinated limit-abort request count (`la`), and raw limit observation count
(`ra`). Successful rows report all four failure fields as zero. The evidence
result passes when coverage is complete and unsaturated; it does not weaken
result `2064`'s zero-pending gate.

Selector `2076` provides the diagnostic-only status-synchronization arm:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-status-sync-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_status_sync.json
python3 tools/run_qualification.py --manifest coordinated_xy_status_sync_v1 --operator-prompts --fixture motion_clear_envelope_v1 --machine-id LC-001 --raw-report hil_reports/coordinated_xy_status_sync.json
```

It runs the exact selector-`2077` geometry and homes but protects only the
status-metric reset/update/snapshot body with a dedicated statically allocated
FreeRTOS task mutex. Interrupts remain enabled during those calculations; the
mutex wait is bounded to 5 ms and any lock failure fails closed through `lf`.
Boot, selector `2077`, and all normal operation remain on the existing critical
section. An exit guard restores critical-section mode on every selector-`2076`
return path. This is an A/B diagnostic, not approval to make the mutex the
production default.

Selector `2075` is now retired and fails closed with
`gate=single_irq_superseded` before the fixture prompt or motion. The
one-interrupt software pulse combined DEDGE's two physical edges into one
planner event, so it was not a sound basis for validating TMC2208 operation.

The replacement diagnostic keeps the production two-edge executor and tests
the driver-supported reduction in microstep resolution. Build the distinct
MRES=3 image without overwriting the production artifact:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1 -Config MRES3_Diagnostic -ArtifactFileName LabCraft_firmware_mres3_diagnostic.bin
```

After flashing exactly
`firmware/artifacts/LabCraft_firmware_mres3_diagnostic.bin`, run only selector
`2085` while an operator watches the clear gantry:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-mres3-20khz-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_mres3_20khz.json
python3 tools/run_qualification.py --manifest coordinated_xy_mres3_20khz_v2 --operator-prompts --fixture coordinated_xy_mres3_20khz_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_mres3_20khz.json
```

MRES=3 selects 1/32 microsteps instead of 1/64. Commands, configuration, and
status remain in the original MRES=2 logical units. The firmware converts at
the motor boundary: one complete high/low DEDGE cycle represents two logical
units, so native pulse-cycle count, rate, and acceleration are divided by two.
An odd signed displacement is truncated toward zero to the nearest reachable
coordinate; status reports that actual logical coordinate rather than the
unreachable request. The original ten-move coordinates, 40 kHz logical rate,
and 140,000 logical-units/s2 therefore preserve physical travel, speed, and
acceleration while producing 110,000 native cycles and 220,000 rise/fall TIM2
callbacks. Results `2080`-`2083` verify exact motion, complete IRQ/entry
coverage, 219,990 nonterminal deadline samples, and the intended TMC
configuration (`MRES=3`, `DEDGE=1`, `multistep_filt=0`). P/R positions must not
change.

The MRES=3 diagnostic image still rejects ordinary queued commands with all
motors disabled, rejects ordinary FULL requests before motion, and accepts
only SAFE plus selectors `2085`, `2084`, and `2086`. Its boot schedule remains
`FreeRunning`; selector guards restore the prior mode on every exit.

Selector `2084` runs the same scaled MRES=3 row but temporarily changes TIM2
from free-running scheduling to rearm-from-actual-edge scheduling:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-mres3-rearm-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_mres3_rearm.json
python3 tools/run_qualification.py --manifest coordinated_xy_mres3_rearm_v1 --operator-prompts --fixture coordinated_xy_mres3_rearm_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_mres3_rearm.json
```

For each nonterminal rise or fall, it installs the following ARR, emits the
STEP edge, stops TIM2, records any already-pending update, resets `CNT`, clears
the peripheral and NVIC pending state, and restarts the timer. This stretches a
late interval instead of compressing the next one. Result `2082` adds `rm`
(mode), `rc` (rearm count), `rp` (pending at rearm), and `rd` (maximum
edge-to-restart core cycles). Acceptance requires `rm=1`, `rc=219990`, `rp=0`,
complete deadline coverage, no missed deadline, and at least 450 timer ticks
of post-handler slack. Entry lateness (`cm`, `lc`, and `dm`) remains visible but
is diagnostic rather than a failure: rearming is intended to tolerate it.
Selector `2085` and diagnostic boot remain free-running.

Selector `2086` is the conditional late-only rearm diagnostic. It runs the same
MRES=3 ten-move row and leaves TIM2 free-running whenever a nonterminal physical
edge has more than 1,125 timer ticks (12.5 us) before the next update. If the
remaining margin is 1,125 ticks or less, UIF is already set, or CNT exceeds ARR,
it rebases the timer from the actual edge. Each measured move injects one bounded
late rising edge at a target 900 ticks of slack: the first cruise rise when a
cruise plateau exists, or the first deceleration rise at the peak when cruise
length is zero. This exercises the recovery branch ten times without altering
unmeasured positioning or homes. Result `2086`
reports decision, rearm, injection, slack, wait, timeout, and saturation evidence.
The intentional wait remains in raw IRQ and wall-duration telemetry but is
excluded only from the executor-body phase-cost gate.

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-mres3-conditional-rearm-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_mres3_conditional_rearm.json
python3 tools/run_qualification.py --manifest coordinated_xy_mres3_conditional_rearm_v3 --operator-prompts --fixture coordinated_xy_mres3_conditional_rearm_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_mres3_conditional_rearm.json
```

This selector is diagnostic-only. It restores the diagnostic image's
`FreeRunning` mode on every exit.

The v3 conditional manifest adds the zero-cruise peak fallback while preserving
the v2 result schema and strict gates. The v2 MRES3 manifests correspond to the
first isolated diagnostic implementation.
TIM2 modes 0/1 use a nonconditional ISR specialization with no mode-2 timer
sample, injection, decision, or intentional-wait bookkeeping. Mode 2 retains
all of those diagnostics. Selectors `2085` and `2086` continue through the
reverse leg and remaining pairs after a completed, internally consistent move
that fails only a timing/qualification gate. The result still fails strictly:
`2080` reports the failing-move count/mask as `qf`/`qm`, and `2082` reports the
first hard-stop mask as `hm` alongside `fv/tr/la/ra`. Timeouts, cancellation,
limit/planner termination, count/endpoint/checksum/state mismatches, incomplete
coverage, saturation, watchdog evidence, and communication/operator aborts
still stop immediately. Selector `2084` retains its original fail-stop policy.
The v1 and v2 conditional manifests remain available to normalize earlier
reports.

The production migration candidate uses the same logical-unit conversion,
programs all shared-UART TMC2208 drivers as MRES=3/DEDGE=1/multistep_filt=0,
and boots coordinated XY in `ConditionalLateRearm`. Synthetic late-edge
injection and its intentional-wait path are compiled only into the diagnostic
image. Selector `2097` exercises the production path without injection and
emits `[2087,2088,2089,2090]`:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --coordinated-xy-production-mres3-suite --timeout-ms 240000 --status-only-timeout-ms 120000 --out hil_reports/coordinated_xy_production_mres3.json
python3 tools/run_qualification.py --manifest coordinated_xy_production_mres3_v1 --operator-prompts --fixture coordinated_xy_production_mres3_envelope_clear --machine-id LC-001 --raw-report hil_reports/coordinated_xy_production_mres3.json
```

Production acceptance requires exact native totals and callback coverage, zero
pending/deadline/reset/watchdog evidence, at least 450 timer ticks of deadline
slack, consistent conditional decisions, successful bounded homes, and normal
operator observation. Conditional rearm need not occur in a clean row; if it
does occur, pending-at-rearm must remain zero. Because synthetic injection is
compiled out, selector `2097` requires all injection counters to remain zero.
The terminal cleanup callback runs after the final physical STEP edge, so its
cycle cost is retained as candidate telemetry rather than a blocking
production gate; active callbacks and every real edge deadline remain strict.
The corrected production artifact is 351,856 bytes with SHA-256
`7EB588C49258F215046BB77C5E5A5518D4BCAAB550F1AFA32CB62E45E2A1A2C6`;
the matching diagnostic artifact is 354,272 bytes with SHA-256
`FBF650E6C6B309885FD4205C79C0613C2F129F822A6222ED7C12A418AD47B15B`.

Rollback before production HIL is the commit-`8a1cd3c4` production artifact:
351,832 bytes, SHA-256
`A0D40FD82EED36B8CECFF2A2B5E56499C95CF9B962029CB8D2A52F618F165A12`.
The production MRES=3/conditional-rearm checkpoint passed watched
SAFE/`2097`/SAFE with exact counts, zero X/Y drift, one clean natural rearm,
unchanged reset/watchdog counters, and a warning-free normalized report. The
single-axis X/Y/Z LUT migration is therefore authorized as a separate commit,
artifact, rollback point, and watched HIL checkpoint.

Checkpoint B now routes ordinary direct X/Y/Z moves using the cosine profile
through the same fixed-point normalized LUT as coordinated XY. The boundary is
deliberately narrow: direct homing and limit soft-stop moves, P/R motion,
coordinated XY, and the linear/min-jerk profile choices retain their existing
paths. App commands, opcodes, positions, targets, speeds, and acceleration stay
in legacy logical units. Invalid cursor preparation fails before motor enable;
an inconsistent runtime cursor stops the affected direct move without emitting
another untrusted edge.

Production selector `2096` provides the independent Checkpoint B HIL gate:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL \
  --direct-xyz-lut-suite --timeout-ms 240000 \
  --status-only-timeout-ms 120000 \
  --out hil_reports/direct_xyz_lut.json
python3 tools/run_qualification.py --manifest direct_xyz_lut_v1 \
  --operator-prompts --fixture direct_xyz_lut_envelope_clear \
  --machine-id LC-001 --raw-report hil_reports/direct_xyz_lut.json
```

The selector homes Z and XY, runs a 14,000-logical-unit cruise-capable move on
X and Y at 40 kHz and Z at 30 kHz, plus a 2,000-unit triangular X move at 40 kHz,
then homes again. Results `2091`-`2094` require exact MRES=3 native pulse and
LUT cursor coverage; `2095` requires both home sets to remain on the legacy
path, no P/R displacement, and the production MRES=3/DEDGE/filter settings.
This is a watched FULL motion selector and requires both switches released and
the complete direct X/Y/Z envelope clear.

The pre-HIL Checkpoint B production candidate is 356,824 bytes with SHA-256
`954B39FC4F0F01A0A3FFAB7E639EE48127FFC2034E1C946F732AB9B7E38ABC44`;
the matching diagnostic artifact is 359,224 bytes with SHA-256
`7D61C356EAC3A73EA369A2C1CAF5923D2F6A3184FC43C956BCC3466C5C5007B4`.
Targeted qualification tests pass 160/160 and the complete firmware gate passes
425/425 host tests plus both linked builds. Generated stack-use evidence reports
128 bytes for `Stepper::_stepTick()` and 24 bytes for the fixed-point sample
helper, within the existing 1,024-byte interrupt-stack reservation.

The first watched `2096` row on commit `c96338fd` completed 5/5 firmware
results with exact endpoints, pulses, cursor coverage, zero pending updates,
and normal operator-observed moves and homes. Its host cadence check failed
because the selector reset and paused status metrics around each sub-second
move; no individual window happened to contain a status frame. One aggregate
RAII-guarded window removed those per-move resets, but a second row showed that
the shared self-test result/progress emitter also reasserted the status pause
after every frame. The final selector-scoped correction resumes status after
each such emission only while the `2096` evidence window is active. Aggregate
result `2095` gates cadence and the host requires both progress-watchdog and
status-cadence checks. Its status-period limit is 125 ms because the nominal
50 ms status task can legitimately miss one slot while a measured result frame
holds the UART for up to 26 ms; watchdog age remains limited to 100 ms. These
were evidence-path defects; no motion code,
geometry, rate, or acceleration changed. The final production candidate is
357,224 bytes with SHA-256
`09A00B221816B73390666BB1A084EE7009DF9555072965E1F7C659B9683DF2FB`;
the matching diagnostic image is 359,640 bytes with SHA-256
`71CF16AF562D80C1B7E0801B33A80DFBF6A6BBCEF414F292704A6A80CDB4CE57`.

Checkpoint B is accepted on commit `5750b3ca`. Its final watched
SAFE/`2096`/SAFE bracket passed both SAFE inventories 30/30 and the focused
row 5/5. The row recorded exact endpoints, native pulses, and normalized cursor
coverage; zero pending, runtime/profile, abort, saturation, timeout, reset, or
new watchdog evidence; 82 status frames; a 114 ms maximum status period; and a
36 ms maximum status-watchdog age. Boot/fault/watchdog counters remained
`162/4/6`, P/R positions were unchanged, and the operator confirmed that every
move and home looked and sounded normal. `direct_xyz_lut_v1` normalized the
report as PASS with zero warnings or blockers. The normalized evidence is
`hil_reports/qualification/LC-001/20260813T200635Z/report.json`, SHA-256
`F5366BE042C76AA3EAAC6F73B76DDF8D7A29B43BDF185F88979D9DD04808AA34`.

The production MRES=3, conditional late-rearm, and direct X/Y/Z LUT migration
is complete. The remaining coordinated-motion work is the separately scoped
Milestone 7 cleanup and full regression/closeout—not another migration change.

The approved comparison is three SAFE-bracketed pairs in order `A-B`, `B-A`,
`A-B`, where A is selector `2077`/manifest `coordinated_xy_40khz_v1` and B is
selector `2076`/manifest `coordinated_xy_status_sync_v1`. Every B run requires
`sm=1`, `lf=0`, `pu=ps=0`, complete 440,000-callback coverage, `lc=0`,
`cm<128`, `dm<256`, and `fv=tr=la=ra=0`, plus clean cadence, watchdog, reset,
and home evidence.

First confirm that the `pressure_closed_loop_v1` fixture is installed and safe
at 1-2 psi and that the complete XY/Z envelope is clear. Both performance
selectors have exactly this one live confirmation. The manual X/Y switch
preflight and low-rate homing regression already passed after the bounded-home
diagnostic change, and no subsequent code affects switch reading or homing.
It automatically homes Z, then homes X and Y sequentially at 3 kHz/1 kHz before
the 5, 10, 20, 30, and 40 kHz ladder. Before the ordinary 40 kHz row, result
`2070` independently qualifies positive and negative X motion at 30/35/40 kHz,
including a 24,000-step reduced-acceleration 40 kHz case long enough to reach a
real cruise plateau, with bounded home-reference checks after every measured
leg. The other direction-isolation legs remain 20,000 steps.
It also covers the Milestone 1 vectors, the Z-up 16x24 raster, repeated
camera/home-ratio moves, and a final 40 kHz move while both pressure regulators
are active. Stop immediately for unexpected contact, abnormal sound, pressure
leakage, reset, or motion outside the documented envelope.

Outputs:

- Suite reports: `hil_reports/qualification/<machine_id>/<timestamp>/`
- Campaign report: `hil_reports/qualification_campaigns/<machine_id>/<timestamp>/campaign_report.json`
- Campaign CSV: `hil_reports/qualification_campaigns/<machine_id>/<timestamp>/campaign_summary.csv`

## Firmware Local Checks

### Watchdog evidence and no-motion soak

The production firmware creates the watchdog supervisor during startup but
arms IWDG only after the first accepted `HELLO`. The timeout remains 4 seconds,
the supervisor period 100 ms, and healthy recovery requires 10 continuous
seconds. A healthy recovery clears only `pending`; SAFE result `1041` can pass
with `pending=0` while still reporting the last historical fault and late task.

`tools/run_selftest.py` writes two separate nullable fields. A reset report
that matches the HELLO sequence and run ID is stored in
`startup_reset_report` and does not abort SAFE. `reset_report` remains the
fail-closed evidence field for a non-startup report observed during execution.
Firmware sends the startup report at most once per MCU boot, so its absence on
a second SAFE run without an MCU reset is expected.

For the watchdog evidence milestone, do not move any axis or actuate pressure.
After flashing the matching binary, wait at least 15 seconds before the first
HELLO, then run:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --out hil_reports/watchdog_soak_initial.json
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --out hil_reports/watchdog_soak_same_boot.json
```

After GOODBYE, leave the MCU powered and idle for 30 minutes, then repeat SAFE
to a new report; perform three intervals total. Compare result `1041` metrics
`boot`, `fault_ct`, and `wdg_ct`, and require result `1042` to remain armed with
all required participants live. If a reset reproduces, retain the first
post-reset report before waiting at least 12 seconds and running SAFE again;
the later run must show `pending=0` while preserving the same historical
`fault=wdt` and `wdg_late` evidence. Stop for a reset loop, missing HELLO,
corrupt evidence, or unexplained counter changes.

### Self-test scheduler and pressure-watchdog A/B diagnostic

For cooperative self-tests, each synchronous result/progress transmission and
its one-tick delay execute under a scoped pressure-priority guard. Tick-level
time slicing lets the pressure task interrupt polling UART transmission and
finish an in-progress I2C transaction or recovery without time-slicing the
emitter against the idle task. The orchestrator's original priority is restored
after every frame. Cooperative self-test frames use a local 50 ms UART timeout
to cover that intentional time slicing; normal communication and the no-yield
control retain 25 ms. A failed result transmission latches incomplete evidence.
This is the default for SAFE, FULL, and focused diagnostics;
selector `1039` retains the original high-priority/no-yield behavior, and
ordinary command/status traffic is unchanged.
SAFE adds result `1044 pressure_wdg_context_safe` and final result
`1043 selftest_scheduler_safe`, so an ordinary SAFE run now reports 30 rows.
Result `1043` records result-frame/yield counts, UART blocking time, live
pressure-task gap/age/phase, I2C failure/recovery deltas, and stack headroom.
Result `1044` exposes the checksummed `.noinit` pressure context retained when
the watchdog identifies the pressure task as late. A context is required only
for a still-pending pressure watchdog fault under the same firmware image;
power cycles and flashing a different image may invalidate `.noinit`.

Both rows also report lightweight I2C failure detail as `h`, `r`, `x`, and `e`:
`h=0` means no failed read in the current diagnostic window, while `1`, `2`,
and `3` are the STM32 HAL `ERROR`, `BUSY`, and `TIMEOUT` results; `r` is the
failed receive call's elapsed milliseconds; and `x` is the active or most
recent read-recovery wall time. `e` is the failure-only result of
`HAL_I2C_GetError()`: timeout is 32, acknowledge failure 4, bus error 1, and
arbitration loss 2; combined errors are bitwise sums. The recovery sequence intentionally requests
20 one-tick delays, so `max(0, x-20)` includes scheduling stretch plus its
small GPIO and HAL reinitialization cost. This is not continuous task tracing.
The successful read path adds only two `HAL_GetTick()` reads and a subtraction;
the error-mask read and detail-state writes occur only after an I2C read
failure. Durations saturate and fail evidence closed above 999 ms. No UART logging,
mutex, allocation, new delay, or stack scan was added to the pressure loop.
The global `INCLUDE_uxTaskGetStackHighWaterMark` setting remains disabled.

Selectors `1039` and `1038` run the identical non-destructive SAFE inventory
with no-yield and cooperative scheduling respectively. They do not move axes,
change pressure targets, or actuate valves:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --selftest-scheduler-no-yield-suite --timeout-ms 240000 --out hil_reports/selftest_scheduler_a1.json
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --selftest-scheduler-cooperative-suite --timeout-ms 240000 --out hil_reports/selftest_scheduler_b1.json
```

Run six arms in `A-B, B-A, A-B` order, waiting at least six seconds after each
arm. Normalize A with `selftest_scheduler_no_yield_v1` and B with
`selftest_scheduler_cooperative_v1`, then compare all reports:

```bash
python3 -m tools.qualification.cli --manifest selftest_scheduler_no_yield_v1 --raw-report <A1.json> --output-root hil_reports/qualification
python3 -m tools.qualification.cli --manifest selftest_scheduler_cooperative_v1 --raw-report <B1.json> --output-root hil_reports/qualification
python3 tools/compare_selftest_scheduler_ab.py \
  <A1.json> <B1.json> <B2.json> <A2.json> <A3.json> <B3.json> \
  --final-safe <final_safe.json> \
  --out hil_reports/selftest_scheduler_ab_comparison.json
```

The cooperative manifest requires `rf=yc=29`, pressure gap and current age no
greater than 125 ms, no I2C failure/recovery delta, complete unsaturated
evidence, and clean host checks. The pressure-sensor watchdog participant has
a 500 ms deadline so one complete recovery retains substantial reset margin;
the 125 ms qualification gates remain unchanged and prevent the larger
watchdog window from accepting degraded normal scheduling. If MSBuild reports
`FileTracker` access denied during local checks,
rerun the firmware script from a normal non-sandboxed PowerShell session.

Prerequisites:

- CMake available on `PATH`
- STM32CubeIDE installed at `C:\ST\STM32CubeIDE_1.18.1\STM32CubeIDE`, or pass `-CubeIde` to `firmware/scripts/build_firmware_headless.ps1`

Run host firmware tests plus a headless CubeIDE build:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Run the focused shallow-angle flash/HIL workflow only on the designated,
operator-attended LC-001 machine after confirming non-dispensing heads and a
clear motion envelope:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 `
  -PiHost 192.168.0.33 `
  -Profile FULL `
  -CoordinatedXyShallowEdgeSuite
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

### Production-path gripper refresh FULL HIL

Milestone 4 adds an operator-gated two-layer qualification for deferred gripper
refresh. It first runs the ordinary FULL flash/self-test lane, then exercises the
public production command sequence (safe 1 psi print-pressure setup/readiness,
`CLOSE_GRIPPER`, print profile `p1=1`, real print-only dispense boundaries,
profile disable, and calibration profile `p1=0`) before selector `2599` runs
firmware rows `2510`-`2513`.

Prerequisites are Windows OpenSSH (`ssh`/`scp`), the Pi checkout and virtualenv,
an existing `local/machine_identity.json` on the Pi, the dummy blocked head,
the evaporation plate, and an operator present for the complete run. Start it
from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_gripper_refresh_hil_windows.ps1 `
  -PiHost 192.168.0.33
```

The wrapper requires an explicit `RUN` confirmation before flashing. It uploads
the exact qualification Python/JSON files, uses an interactive SSH terminal for
fixture and support prompts, and downloads the selected run under
`hil_reports/m4_gripper_refresh_<timestamp>/` even when qualification fails.
That directory contains `production_path.json`, `raw_selftest.json`,
`report.json`, `summary.csv`, and exported trace/plot artifacts.

The production-wire check requires a fast pre-expiry dispense, a host-observed
`3000..7000 ms` delay between the dispense that claims a pending refresh and the
next dispense, and two fast dispenses after a 31-second `p1=0` window. Its
setup uses existing production commands to regulate print pressure to 1 psi and
requires fresh status showing the regulator active and within the firmware
ready band before dispense timing begins. Its failure path disables the profile,
deregulates print pressure, and falls back to `CLEAR`; it never releases, turns
off, or shuts down the gripper before the operator support prompt. If SSH
cannot allocate an interactive terminal, rerun from a normal PowerShell console.
If the Pi identity is missing, restore the machine's existing identity rather
than creating an ad-hoc value for a qualification run.
For key-based SSH, add `-IdentityFile path\to\pi_key`; the option is passed
through to both the ordinary FULL runner and the selected qualification.
The upload loop is compatible with the Windows PowerShell 5.1 included with
Windows; no PowerShell 7-only path APIs are required.

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
Inside `FreeRTOS-interface/Presets`, JSON files are tracked starter templates. Legacy releases through `v1.3.0-rc.1` copied machine-specific data into checkout-local ignored `local/`. Starting with `v1.3.0-rc.2`, an authorized machine uses the checkout-independent external machine-data store established by the first-start migration; tracked presets and checkout-local files are not runtime fallback sources. Calibration memory, machine configuration, update evidence, and the active-machine pointer remain bound to that external store across checkouts and worktrees.

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
- For rc.2 and later, the updater first binds the exact external machine/root, acquires the update and configuration locks, and reopens a verified external backup. It verifies exact protected bytes and the target commit before authorizing relaunch.
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
<machine-data-root>/machines/<machine-uuid>/update_history/updater_logs/
```

For dirty worktrees, network failures, credential failures, or non-fast-forward Git state, the updater does not stash, reset, clean, or overwrite local changes. `Reopen Current Version` is shown only when the current deployment can still be reopened safely. A failure after Git mutation or ambiguous machine-data verification enters recovery and offers no normal relaunch.

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

Pre-M6 development checkouts can invoke an offline updater directly. On rc.2
and later, use the authorized app flow because direct apply also requires the
exact external machine-data launch binding:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --offline-manifest path\to\labcraft-stable-....json --no-relaunch
```

The shortened example intentionally fails closed on an M6-capable production
apply. See `docs/machine_data_update_and_rollback_runbook.md` for support and
recovery procedures.

### Controlled release rollback

The Firmware tab includes support-guided rollback controls for restoring a previous application version without allowing arbitrary tag selection. Use rollback only with support guidance after confirming the machine is idle and no print, calibration, capture, or firmware operation is active.

Expected UI flow:

- Click `Check Rollback`.
- If the installed release defines a rollback target, the app shows the exact path such as `v1.2.0 -> v1.1.2`.
- If the online rollback check cannot fetch release tags, the app scans removable drives for `LabCraftUpdates/*.json` release-aware rollback manifests.
- For an M6-capable rollback target, click `Restore Previous App Version`; the app confirms that application code will move backward and firmware will not be flashed.
- If the target is a legacy checkout-local release, the normal restore button remains disabled and LabCraft support is required.
- A `LabCraft Rollback` window appears after the main app closes, verifies the same target again, and applies it.
- For explicit support-provided bundles, click `Restore From Offline Rollback Bundle` and select a release-aware manifest directly.

M6-capable backend apply/rollback requires the full authorized binding. Do not
reconstruct it from guessed paths when the main app cannot launch; preserve
evidence and follow the recovery runbook.

Online rollback uses the installed `VERSION`, reads that release tag's manifest, and resets to its configured `rollback_version`:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --rollback --no-relaunch --record-result
```

Offline rollback requires a selected release-aware bundle manifest for the target release:

```powershell
.\env\Scripts\python.exe tools/update_and_restart.py --repo-root . --rollback --offline-manifest path\to\labcraft-stable-....json --no-relaunch --record-result
```

The rollback command checks for a dirty worktree before fetching or resetting and verifies target release metadata. For M6-to-M6 rollback it also verifies an external pre-change backup and protected bytes before authorizing relaunch. Legacy rollback is exact-profile-only, requires explicit operator/service/firmware attestations, and creates a verified checkout-local compatibility export before Git reset. Review external evidence under `<machine-data-root>/machines/<machine-uuid>/update_history/`; see `docs/machine_data_update_and_rollback_runbook.md`.

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

