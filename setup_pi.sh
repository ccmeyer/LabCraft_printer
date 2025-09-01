#!/usr/bin/env bash
set -euo pipefail

# ---- Config ----
USER_NAME="${SUDO_USER:-$USER}"   # the intended non-root user
UDEV_RULE_PATH="/etc/udev/rules.d/45-st-dfu.rules"

echo "=== 1) Apt packages ==="
sudo apt-get update
sudo apt-get install -y \
  git python3 python3-venv python3-pip \
  dfu-util gpiod python3-libgpiod libgpiod-dev \
  build-essential

echo "=== 2) Groups ==="
# gpio = access /dev/gpiochip*, dialout = serial, plugdev = DFU rule (we set below)
for grp in gpio dialout plugdev; do
  if ! getent group "$grp" >/dev/null; then
    sudo groupadd "$grp"
  fi
  sudo usermod -aG "$grp" "$USER_NAME"
done

echo "=== 3) Udev rule for ST DFU ==="
sudo bash -c "cat > '$UDEV_RULE_PATH'" <<'RULE'
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", GROUP="plugdev", MODE="0664"
RULE
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "=== 4) (Optional) Enable UART0 on Pi ==="
# If you use /dev/ttyAMA0 (/dev/serial0), you usually want:
# - enable_uart=1 in /boot/firmware/config.txt (Bookworm) or /boot/config.txt (Bullseye)
# - remove console=serial0,115200 from /boot/firmware/cmdline.txt if present
CFG="/boot/firmware/config.txt"
if [ -f /boot/config.txt ]; then CFG="/boot/config.txt"; fi
if ! grep -q '^enable_uart=1' "$CFG"; then
  echo "enable_uart=1" | sudo tee -a "$CFG"
  echo "NOTE: If serial console is enabled, remove 'console=serial0,115200' from cmdline.txt and reboot."
fi

echo "=== 5) Done. Reboot recommended if groups/uart changed ==="
echo "Log out/in (or reboot) so group membership takes effect."