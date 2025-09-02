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

```bash
mkdir -p Documentation/env
{
  echo "== OS =="; cat /etc/os-release
  echo; echo "== Kernel =="; uname -a
  echo; echo "== Python =="; python3 --version; pip3 --version
  echo; echo "== dfu-util =="; dfu-util --version
  echo; echo "== gpiod =="; gpiod --version || true
} > Documentation/env/system_summary.txt

# Make sure the Raspberry Pi archive keyring is installed
sudo apt-get update
sudo apt-get install -y raspberrypi-archive-keyring

# Ensure the Raspberry Pi repo is present (Bookworm)
echo 'deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] http://archive.raspberrypi.org/debian/ bookworm main' | \
  sudo tee /etc/apt/sources.list.d/raspi.list

# Also make sure the Raspbian repo is present (usually already there)
sudo mkdir -p /etc/apt/sources.list.d
grep -q 'raspbian.raspberrypi.org' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || \
  echo 'deb http://raspbian.raspberrypi.org/raspbian/ bookworm main contrib non-free rpi' | \
  sudo tee -a /etc/apt/sources.list

sudo apt-get update

apt-cache policy python3-libcamera python3-picamera2
sudo apt-get install -y python3-libcamera python3-picamera2

# From your project root
deactivate 2>/dev/null || true
rm -rf venv
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Sanity check
python - <<'PY'
import sys
print("dist-packages in sys.path?", any("dist-packages" in p for p in sys.path))
try:
    import libcamera, picamera2
    print("OK: libcamera & picamera2 imported")
except Exception as e:
    print("Import failed:", e)
PY

sudo usermod -aG video,render $USER
