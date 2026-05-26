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

## Pull Calibration Records From The Pi

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
Inside `FreeRTOS-interface/Presets`, `Settings.json` stores predefined values such as default COM ports and plate setup.

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
pip-compile --generate-hashes --output-file requirements-pi.lock requirements.in

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

