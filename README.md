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

Slice 3 exposes one programmatic composition seam for the real `Model`,
`Controller`, and `MainWindow`. Production startup continues through
`FreeRTOS-interface/App.py`; there is intentionally no simulation command-line
flag until the dedicated runner is added in Slice 5.

`ApplicationComposition.production_dependencies()` selects the existing
Machine, serial, camera, log-reader, and legacy balance implementations.
`simulation_dependencies(run_root, machine_factory=...)` instead requires a
caller-supplied safe machine factory and creates `config/`, `experiments/`, and
`calibration-memory/` beneath the supplied run root. It never falls back to
production hardware if construction fails.

Simulation windows show a persistent
`SIMULATION — NO HARDWARE CONNECTED` banner. Connection, firmware/DFU, MCU
reset, physical camera, machine qualification/calibration, balance, and
application update controls remain visible but disabled. The Controller also
rejects direct calls to those entry points before port enumeration, worker
construction, or peripheral access.

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
camera analysis, or droplet quality. There remains no simulation CLI or
complete virtual print-array scenario in the Slice 4 API itself.

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

Each successful run contains the validated JSON report, text summary, bounded
event trace, stack diagnostics, retained isolated config/experiment/calibration
roots, and ready/printing/mid-array/completed screenshots. Failed runs retain a
traceback and failure screenshot when possible. Generated reports are ignored
by Git and are machine-specific.

The report's responsiveness phase timings include `ui.pressure_render`, the
count and duration distribution for the real pressure-plot update slot. The
text summary shows its count, p95, and maximum. This diagnostic covers the
synchronous pressure-series/label update, not deferred native paint or
compositor work, and it is not yet a performance gate.

If Windows reports `WinError 5` while rapidly replacing an execution file,
retain the failed diagnostics and retry once with a fresh ignored
repository-local output root, for example:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root tmp\virtual_workflows
```

Do not disable atomic replacement or `fsync` to work around host filesystem
contention. Some minimal PySide6 installations also lack bundled fonts; the
offscreen screenshots remain diagnostic but may render text as placeholder
glyphs until system fonts or fontconfig are available.

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

