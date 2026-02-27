#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# LabCraft Pi-side HIL runner: flash firmware via DFU and run self-test
#
# Typical usage:
#   ./hil/flash_and_test.sh
#   ./hil/flash_and_test.sh --bin firmware/artifacts/LabCraft_firmware.bin
#   ./hil/flash_and_test.sh --profile SAFE
#   ./hil/flash_and_test.sh --port /dev/ttyACM0
#
# Exit codes:
#   0  success (flash ok; selftest ok if run)
#   2  missing dependency / config
#   3  flash failed
#   4  serial port did not appear
#   5  self-test failed or script missing when required
#
# Notes:
# - Uses dfu_update.py to enter DFU via Pi GPIO and flash with dfu-util
# - Assumes dfu_update.py is in repo (root or FreeRTOS-interface/)
# - Self-test runner is optional: tools/run_selftest.py (recommended) or set --selftest-cmd
# ==============================================================================

# -------------------------
# Defaults (override with args)
# -------------------------
PROFILE="SAFE"  # SAFE or FULL (your future selftest profiles)
BIN_PATH=""     # default resolved below
PORT=""         # auto-detect if not provided
DFU_SCRIPT=""   # auto-detect if not provided
REPORT_PATH=""  # default resolved below
LOG_DIR=""      # default resolved below
SELFTEST_CMD="" # optional explicit command
WAIT_PORT_S=20
BAUD=115200

# -------------------------
# Helpers
# -------------------------
die() { echo "ERROR: $*" >&2; exit 2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing dependency '$1'. Install it and retry."
}

now_ts() { date +"%Y%m%d_%H%M%S"; }

# Find repo root (script can be run from anywhere)
find_repo_root() {
  if command -v git >/dev/null 2>&1; then
    if git rev-parse --show-toplevel >/dev/null 2>&1; then
      git rev-parse --show-toplevel
      return
    fi
  fi
  # fallback: assume script lives at <repo>/hil/flash_and_test.sh
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  (cd "$script_dir/.." && pwd)
}

# Auto-detect dfu_update.py
detect_dfu_script() {
  local repo="$1"
  if [[ -n "$DFU_SCRIPT" ]]; then
    echo "$DFU_SCRIPT"
    return
  fi
  if [[ -f "$repo/dfu_update.py" ]]; then
    echo "$repo/dfu_update.py"
    return
  fi
  if [[ -f "$repo/FreeRTOS-interface/dfu_update.py" ]]; then
    echo "$repo/FreeRTOS-interface/dfu_update.py"
    return
  fi
  # Add more fallback paths here if you keep it elsewhere:
  die "Could not find dfu_update.py. Pass --dfu-script /path/to/dfu_update.py"
}

# Auto-detect firmware bin
default_bin_path() {
  local repo="$1"
  # Prefer the artifact produced by your laptop build step
  if [[ -f "$repo/firmware/artifacts/LabCraft_firmware.bin" ]]; then
    echo "$repo/firmware/artifacts/LabCraft_firmware.bin"
    return
  fi
  # Fallback to any bin in artifacts
  local any
  any="$(ls -1 "$repo/firmware/artifacts/"*.bin 2>/dev/null | head -n 1 || true)"
  if [[ -n "$any" ]]; then
    echo "$any"
    return
  fi
  die "No firmware .bin found. Expected firmware/artifacts/LabCraft_firmware.bin (or pass --bin)."
}

# Auto-detect a serial port created by the MCU after reboot
detect_port() {
  # If user specified a port, honor it.
  if [[ -n "$PORT" ]]; then
    echo "$PORT"
    return
  fi

  # Prefer /dev/serial/by-id because it is stable across reboots.
  # If present, pick the newest entry.
  if ls /dev/serial/by-id/* >/dev/null 2>&1; then
    local p
    p="$(ls -t /dev/serial/by-id/* 2>/dev/null | head -n 1 || true)"
    if [[ -n "$p" ]]; then
      echo "$p"
      return
    fi
  fi

  # Fallback: pick newest ttyACM or ttyUSB
  local acm usb
  acm="$(ls -t /dev/ttyACM* 2>/dev/null | head -n 1 || true)"
  if [[ -n "$acm" ]]; then
    echo "$acm"
    return
  fi
  usb="$(ls -t /dev/ttyUSB* 2>/dev/null | head -n 1 || true)"
  if [[ -n "$usb" ]]; then
    echo "$usb"
    return
  fi

  echo ""
}

wait_for_port() {
  local timeout="$1"
  local t0
  t0="$(date +%s)"

  while true; do
    local p
    p="$(detect_port)"
    if [[ -n "$p" ]] && [[ -e "$p" ]]; then
      echo "$p"
      return 0
    fi
    local t
    t="$(date +%s)"
    if (( t - t0 >= timeout )); then
      return 1
    fi
    sleep 0.25
  done
}

# Run self-test if available/configured
run_selftest() {
  local repo="$1"
  local port="$2"
  local report="$3"
  local log="$4"

  # If an explicit command is provided, use it verbatim.
  if [[ -n "$SELFTEST_CMD" ]]; then
    echo "Running self-test command: $SELFTEST_CMD" | tee -a "$log"
    # shellcheck disable=SC2086
    bash -lc "$SELFTEST_CMD" 2>&1 | tee -a "$log"
    return "${PIPESTATUS[0]}"
  fi

  # Default: use tools/run_selftest.py if present (you will add this later)
  if [[ -f "$repo/tools/run_selftest.py" ]]; then
    echo "Running tools/run_selftest.py (profile=$PROFILE, port=$port)" | tee -a "$log"
    python3 -u "$repo/tools/run_selftest.py" \
      --port "$port" \
      --baud "$BAUD" \
      --profile "$PROFILE" \
      --out "$report" 2>&1 | tee -a "$log"
    return "${PIPESTATUS[0]}"
  fi

  # If no selftest runner exists yet, treat as "flash-only" success.
  echo "NOTE: tools/run_selftest.py not found; skipping self-test (flash-only run)." | tee -a "$log"
  return 0
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --bin PATH            Firmware .bin to flash (default: firmware/artifacts/LabCraft_firmware.bin)
  --dfu-script PATH     Path to dfu_update.py (default: auto-detect in repo)
  --port PATH           Serial device to use after flashing (default: auto-detect)
  --profile NAME        Self-test profile (SAFE or FULL). Default: SAFE
  --report PATH         JSON report output path (default: hil_reports/selftest_<ts>.json)
  --log-dir PATH        Log directory (default: hil_reports/)
  --selftest-cmd CMD    Explicit self-test command to run (overrides tools/run_selftest.py)
  --wait-port SEC       How long to wait for serial port after flashing (default: 20)
  --baud BAUD           Baud rate for self-test runner (default: 115200)
  -h, --help            Show help

Example:
  ./hil/flash_and_test.sh --bin firmware/artifacts/LabCraft_firmware.bin --profile SAFE
EOF
}

# -------------------------
# Parse args
# -------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bin) BIN_PATH="$2"; shift 2 ;;
    --dfu-script) DFU_SCRIPT="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --report) REPORT_PATH="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --selftest-cmd) SELFTEST_CMD="$2"; shift 2 ;;
    --wait-port) WAIT_PORT_S="$2"; shift 2 ;;
    --baud) BAUD="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

# -------------------------
# Main
# -------------------------
need_cmd python3
need_cmd dfu-util

REPO_ROOT="$(find_repo_root)"
DFU_SCRIPT="$(detect_dfu_script "$REPO_ROOT")"

if [[ -z "$BIN_PATH" ]]; then
  BIN_PATH="$(default_bin_path "$REPO_ROOT")"
else
  # resolve relative bin path from repo root
  if [[ "${BIN_PATH:0:1}" != "/" ]]; then
    BIN_PATH="$REPO_ROOT/$BIN_PATH"
  fi
fi

# Reports/logs
if [[ -z "$LOG_DIR" ]]; then
  LOG_DIR="$REPO_ROOT/hil_reports"
else
  if [[ "${LOG_DIR:0:1}" != "/" ]]; then
    LOG_DIR="$REPO_ROOT/$LOG_DIR"
  fi
fi
mkdir -p "$LOG_DIR"

TS="$(now_ts)"
if [[ -z "$REPORT_PATH" ]]; then
  REPORT_PATH="$LOG_DIR/selftest_${TS}.json"
else
  if [[ "${REPORT_PATH:0:1}" != "/" ]]; then
    REPORT_PATH="$REPO_ROOT/$REPORT_PATH"
  fi
fi

LOG_PATH="$LOG_DIR/flash_and_test_${TS}.log"

echo "=== LabCraft HIL flash_and_test ===" | tee "$LOG_PATH"
echo "Repo root     : $REPO_ROOT" | tee -a "$LOG_PATH"
echo "DFU script    : $DFU_SCRIPT" | tee -a "$LOG_PATH"
echo "BIN           : $BIN_PATH" | tee -a "$LOG_PATH"
echo "Profile       : $PROFILE" | tee -a "$LOG_PATH"
echo "Report path   : $REPORT_PATH" | tee -a "$LOG_PATH"
echo "Wait port (s) : $WAIT_PORT_S" | tee -a "$LOG_PATH"
echo "Baud          : $BAUD" | tee -a "$LOG_PATH"
echo "" | tee -a "$LOG_PATH"

# dfu_update.py imports PySide6 at module import time in your current version.
# If PySide6 isn't installed on the Pi, flashing will fail.
python3 - <<'PY' 2>/dev/null || {
  echo "ERROR: PySide6 is not importable; dfu_update.py will likely fail on import." | tee -a "$LOG_PATH"
  echo "Install PySide6 or refactor dfu_update.py to avoid importing PySide6 for CLI use." | tee -a "$LOG_PATH"
  exit 2
}
import PySide6
PY

# Flash firmware
echo "--- Flashing via DFU ---" | tee -a "$LOG_PATH"
set +e
python3 -u "$DFU_SCRIPT" --bin "$BIN_PATH" --timeout 20 --vidpid 0483:df11 --addr 0x08000000 2>&1 | tee -a "$LOG_PATH"
FLASH_RC="${PIPESTATUS[0]}"
set -e

if [[ "$FLASH_RC" -ne 0 ]]; then
  echo "FLASH FAILED (rc=$FLASH_RC)" | tee -a "$LOG_PATH"
  exit 3
fi
echo "Flash OK" | tee -a "$LOG_PATH"

# Wait for serial port to appear
echo "--- Waiting for serial device ---" | tee -a "$LOG_PATH"
if ! PORT_FOUND="$(wait_for_port "$WAIT_PORT_S")"; then
  echo "ERROR: Serial port did not appear within ${WAIT_PORT_S}s" | tee -a "$LOG_PATH"
  echo "Tip: check dmesg/lsusb and ensure firmware enumerates as USB CDC (ttyACM*) or provide --port." | tee -a "$LOG_PATH"
  exit 4
fi
PORT="$PORT_FOUND"
echo "Using port: $PORT" | tee -a "$LOG_PATH"

# Run self-test (if available)
echo "--- Running self-test ---" | tee -a "$LOG_PATH"
set +e
run_selftest "$REPO_ROOT" "$PORT" "$REPORT_PATH" "$LOG_PATH"
TEST_RC="$?"
set -e

if [[ "$TEST_RC" -ne 0 ]]; then
  echo "SELF-TEST FAILED (rc=$TEST_RC)" | tee -a "$LOG_PATH"
  exit 5
fi

echo "SELF-TEST OK (or skipped)" | tee -a "$LOG_PATH"
echo "DONE. Report: $REPORT_PATH" | tee -a "$LOG_PATH"
exit 0