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

Use the project virtual environment, then run:

```bash
py -m pytest -q
```

If your repo venv is in `env` on Windows:

```bash
.\env\Scripts\python.exe -m pytest -q
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

To run launch the user interface that connects and drives the machine use the following command once the virtual environment is active:
```bash
python .\MVC-Interface\App.py
```
Inside of the `.\MVC-Interface\Presets` directory is the file `Settings.json`. This file sets several predefined values such as the default COM ports, default plate setup, etc.

## First-time setup on a new Pi

```bash
# 1) Clone
git clone https://github.com/ccmeyer/LabCraft_printer
cd LabCraft_printer

# 2) Provision OS deps, groups, DFU rule, UART
./scripts/setup_pi.sh
# Log out / reboot if groups changed

# 3) Python env
./scripts/post_clone.sh

# 4) Run
source .venv/bin/activate
python FreeRTOS_interface/App.py
```


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
sudo apt-get install -y python3-numpy python3-scipy \   python3-skimage python3-sklearn python3-opencv

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

# Numpy and associated libraries are reinstalled during pip-sync and must be removed from site-packages so that they rely on the dist-packages version. 
rm -rf /home/labcraft/LabCraft_printer/venv/lib/python3.11/site-packages/numpy*
rm -rf /home/labcraft/LabCraft_printer/venv/lib/python3.11/site-packages/pandas*
rm -rf /home/labcraft/LabCraft_printer/venv/lib/python3.11/site-packages/matplotlib*
rm -rf /home/labcraft/LabCraft_printer/venv/lib/python3.11/site-packages/scipy*
rm -rf /home/labcraft/LabCraft_printer/venv/lib/python3.11/site-packages/sklearn*
```

