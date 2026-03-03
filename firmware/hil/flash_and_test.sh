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
MODE="full"     # full or bisect
BIN_PATH=""     # default resolved below
PORT="/dev/ttyAMA0"  # default Pi UART; override with --port
DFU_SCRIPT=""   # auto-detect if not provided
REPORT_PATH=""  # default resolved below
LOG_DIR=""      # default resolved below
SELFTEST_CMD="" # optional explicit command
WAIT_PORT_S=20
BAUD=115200
HELLO_TIMEOUT_MS=""
SELFTEST_TIMEOUT_MS=""
PROGRESS_TIMEOUT_MS=""
ACTIVITY_TIMEOUT_MS=""
STATUS_ONLY_TIMEOUT_MS=""
HELLO_RETRY_MS=250
SKIP_SELFTEST_AFTER_MISSING_HELLO=0
CAMERA_BENCHMARK=0
CAMERA_BENCHMARK_CYCLES=""
CAMERA_BENCHMARK_EXPOSURE_US=""
CAMERA_BENCHMARK_FLASH_DELAY_US=""
CAMERA_BENCHMARK_FLASH_WIDTH_US=""
CAMERA_BENCHMARK_NUM_DROPLETS=""
CAMERA_BENCHMARK_ATTEMPT_TIMEOUT_MS=""
CAMERA_BENCHMARK_MAX_NEW_FRAMES=""
CAMERA_BENCHMARK_ORDER=""
CAMERA_BENCHMARK_MODE=""
CAMERA_BENCHMARK_PREFLIGHT_PRESSURE_TIMEOUT_MS=""

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
    local cmd=(
      python3 -u "$repo/tools/run_selftest.py"
      --port "$port" \
      --baud "$BAUD" \
      --profile "$PROFILE" \
      --out "$report"
    )
    if [[ -n "$SELFTEST_TIMEOUT_MS" ]]; then
      cmd+=(--timeout-ms "$SELFTEST_TIMEOUT_MS")
    fi
    if [[ -n "$PROGRESS_TIMEOUT_MS" ]]; then
      cmd+=(--progress-timeout-ms "$PROGRESS_TIMEOUT_MS")
    fi
    if [[ -n "$ACTIVITY_TIMEOUT_MS" ]]; then
      cmd+=(--activity-timeout-ms "$ACTIVITY_TIMEOUT_MS")
    fi
    if [[ -n "$STATUS_ONLY_TIMEOUT_MS" ]]; then
      cmd+=(--status-only-timeout-ms "$STATUS_ONLY_TIMEOUT_MS")
    fi
    if [[ -n "$HELLO_TIMEOUT_MS" ]]; then
      cmd+=(--hello-timeout-ms "$HELLO_TIMEOUT_MS")
    fi
    if [[ -n "$HELLO_RETRY_MS" ]]; then
      cmd+=(--hello-retry-ms "$HELLO_RETRY_MS")
    fi
    if [[ "$SKIP_SELFTEST_AFTER_MISSING_HELLO" -ne 0 ]]; then
      cmd+=(--fast-fail-on-missing-hello)
    fi
    if [[ "$CAMERA_BENCHMARK" -ne 0 ]]; then
      cmd+=(--camera-benchmark)
    fi
    if [[ -n "$CAMERA_BENCHMARK_CYCLES" ]]; then
      cmd+=(--camera-benchmark-cycles "$CAMERA_BENCHMARK_CYCLES")
    fi
    if [[ -n "$CAMERA_BENCHMARK_EXPOSURE_US" ]]; then
      cmd+=(--camera-benchmark-exposure-us "$CAMERA_BENCHMARK_EXPOSURE_US")
    fi
    if [[ -n "$CAMERA_BENCHMARK_FLASH_DELAY_US" ]]; then
      cmd+=(--camera-benchmark-flash-delay-us "$CAMERA_BENCHMARK_FLASH_DELAY_US")
    fi
    if [[ -n "$CAMERA_BENCHMARK_FLASH_WIDTH_US" ]]; then
      cmd+=(--camera-benchmark-flash-width-us "$CAMERA_BENCHMARK_FLASH_WIDTH_US")
    fi
    if [[ -n "$CAMERA_BENCHMARK_NUM_DROPLETS" ]]; then
      cmd+=(--camera-benchmark-num-droplets "$CAMERA_BENCHMARK_NUM_DROPLETS")
    fi
    if [[ -n "$CAMERA_BENCHMARK_ATTEMPT_TIMEOUT_MS" ]]; then
      cmd+=(--camera-benchmark-attempt-timeout-ms "$CAMERA_BENCHMARK_ATTEMPT_TIMEOUT_MS")
    fi
    if [[ -n "$CAMERA_BENCHMARK_MAX_NEW_FRAMES" ]]; then
      cmd+=(--camera-benchmark-max-new-frames "$CAMERA_BENCHMARK_MAX_NEW_FRAMES")
    fi
    if [[ -n "$CAMERA_BENCHMARK_ORDER" ]]; then
      cmd+=(--camera-benchmark-order "$CAMERA_BENCHMARK_ORDER")
    fi
    if [[ -n "$CAMERA_BENCHMARK_MODE" ]]; then
      cmd+=(--camera-benchmark-mode "$CAMERA_BENCHMARK_MODE")
    fi
    if [[ -n "$CAMERA_BENCHMARK_PREFLIGHT_PRESSURE_TIMEOUT_MS" ]]; then
      cmd+=(--camera-benchmark-preflight-pressure-timeout-ms "$CAMERA_BENCHMARK_PREFLIGHT_PRESSURE_TIMEOUT_MS")
    fi
    "${cmd[@]}" 2>&1 | tee -a "$log"
    return "${PIPESTATUS[0]}"
  fi

  echo "ERROR: tools/run_selftest.py not found; cannot run required self-test." | tee -a "$log"
  return 5
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --bin PATH            Firmware .bin to flash (default: firmware/artifacts/LabCraft_firmware.bin)
  --dfu-script PATH     Path to dfu_update.py (default: auto-detect in repo)
  --port PATH           Serial device to use after flashing (default: /dev/ttyAMA0)
  --profile NAME        Self-test profile (SAFE or FULL). Default: SAFE
  --mode NAME           Runner mode (full or bisect). Default: full
  --report PATH         JSON report output path (default: hil_reports/selftest_<ts>.json)
  --log-dir PATH        Log directory (default: hil_reports/)
  --selftest-cmd CMD    Explicit self-test command to run (overrides tools/run_selftest.py)
  --wait-port SEC       How long to wait for serial port after flashing (default: 20)
  --baud BAUD           Baud rate for self-test runner (default: 115200)
  --hello-timeout-ms N  HELLO_ACK timeout for tools/run_selftest.py
  --selftest-timeout-ms N  Overall self-test timeout for tools/run_selftest.py
  --progress-timeout-ms N  Progress watchdog timeout for tools/run_selftest.py
  --activity-timeout-ms N  Serial-activity watchdog timeout for tools/run_selftest.py
  --status-only-timeout-ms N  Fail fast if only CMD_STATUS traffic remains after selftest frames
  --hello-retry-ms N    HELLO retry interval for tools/run_selftest.py
  --skip-selftest-after-missing-hello  Fail immediately when HELLO_ACK never arrives
  --camera-benchmark     Run camera/flash timing benchmark and attach artifact
  --camera-benchmark-cycles N
  --camera-benchmark-exposure-us N
  --camera-benchmark-flash-delay-us N
  --camera-benchmark-flash-width-us N
  --camera-benchmark-num-droplets N
  --camera-benchmark-attempt-timeout-ms N
  --camera-benchmark-max-new-frames N
  --camera-benchmark-order auto|pre_selftest|post_selftest
  --camera-benchmark-mode flash_only|print_then_flash
  --camera-benchmark-preflight-pressure-timeout-ms N
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
    --mode) MODE="$2"; shift 2 ;;
    --report) REPORT_PATH="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --selftest-cmd) SELFTEST_CMD="$2"; shift 2 ;;
    --wait-port) WAIT_PORT_S="$2"; shift 2 ;;
    --baud) BAUD="$2"; shift 2 ;;
    --hello-timeout-ms) HELLO_TIMEOUT_MS="$2"; shift 2 ;;
    --selftest-timeout-ms) SELFTEST_TIMEOUT_MS="$2"; shift 2 ;;
    --progress-timeout-ms) PROGRESS_TIMEOUT_MS="$2"; shift 2 ;;
    --activity-timeout-ms) ACTIVITY_TIMEOUT_MS="$2"; shift 2 ;;
    --status-only-timeout-ms) STATUS_ONLY_TIMEOUT_MS="$2"; shift 2 ;;
    --hello-retry-ms) HELLO_RETRY_MS="$2"; shift 2 ;;
    --skip-selftest-after-missing-hello) SKIP_SELFTEST_AFTER_MISSING_HELLO=1; shift 1 ;;
    --camera-benchmark) CAMERA_BENCHMARK=1; shift 1 ;;
    --camera-benchmark-cycles) CAMERA_BENCHMARK_CYCLES="$2"; shift 2 ;;
    --camera-benchmark-exposure-us) CAMERA_BENCHMARK_EXPOSURE_US="$2"; shift 2 ;;
    --camera-benchmark-flash-delay-us) CAMERA_BENCHMARK_FLASH_DELAY_US="$2"; shift 2 ;;
    --camera-benchmark-flash-width-us) CAMERA_BENCHMARK_FLASH_WIDTH_US="$2"; shift 2 ;;
    --camera-benchmark-num-droplets) CAMERA_BENCHMARK_NUM_DROPLETS="$2"; shift 2 ;;
    --camera-benchmark-attempt-timeout-ms) CAMERA_BENCHMARK_ATTEMPT_TIMEOUT_MS="$2"; shift 2 ;;
    --camera-benchmark-max-new-frames) CAMERA_BENCHMARK_MAX_NEW_FRAMES="$2"; shift 2 ;;
    --camera-benchmark-order) CAMERA_BENCHMARK_ORDER="$2"; shift 2 ;;
    --camera-benchmark-mode) CAMERA_BENCHMARK_MODE="$2"; shift 2 ;;
    --camera-benchmark-preflight-pressure-timeout-ms) CAMERA_BENCHMARK_PREFLIGHT_PRESSURE_TIMEOUT_MS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

case "$MODE" in
  full)
    ;;
  bisect)
    PROFILE="SAFE"
    if [[ -z "$HELLO_TIMEOUT_MS" ]]; then HELLO_TIMEOUT_MS=8000; fi
    if [[ -z "$SELFTEST_TIMEOUT_MS" ]]; then SELFTEST_TIMEOUT_MS=12000; fi
    if [[ -z "$HELLO_RETRY_MS" ]]; then HELLO_RETRY_MS=250; fi
    SKIP_SELFTEST_AFTER_MISSING_HELLO=1
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    usage
    exit 2
    ;;
esac

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
echo "Mode          : $MODE" | tee -a "$LOG_PATH"
echo "Profile       : $PROFILE" | tee -a "$LOG_PATH"
echo "Report path   : $REPORT_PATH" | tee -a "$LOG_PATH"
echo "Wait port (s) : $WAIT_PORT_S" | tee -a "$LOG_PATH"
echo "Baud          : $BAUD" | tee -a "$LOG_PATH"
echo "HELLO t/o ms  : ${HELLO_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
echo "Selftest t/o  : ${SELFTEST_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
echo "Progress t/o  : ${PROGRESS_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
echo "Activity t/o  : ${ACTIVITY_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
echo "Status-only t/o: ${STATUS_ONLY_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
echo "HELLO retry   : ${HELLO_RETRY_MS:-default}" | tee -a "$LOG_PATH"
echo "Camera bench  : $CAMERA_BENCHMARK" | tee -a "$LOG_PATH"
if [[ "$CAMERA_BENCHMARK" -ne 0 ]]; then
  echo "  cycles      : ${CAMERA_BENCHMARK_CYCLES:-default}" | tee -a "$LOG_PATH"
  echo "  exposure us : ${CAMERA_BENCHMARK_EXPOSURE_US:-default}" | tee -a "$LOG_PATH"
  echo "  delay us    : ${CAMERA_BENCHMARK_FLASH_DELAY_US:-default}" | tee -a "$LOG_PATH"
  echo "  width us    : ${CAMERA_BENCHMARK_FLASH_WIDTH_US:-default}" | tee -a "$LOG_PATH"
  echo "  droplets    : ${CAMERA_BENCHMARK_NUM_DROPLETS:-default}" | tee -a "$LOG_PATH"
  echo "  timeout ms  : ${CAMERA_BENCHMARK_ATTEMPT_TIMEOUT_MS:-default}" | tee -a "$LOG_PATH"
  echo "  max frames  : ${CAMERA_BENCHMARK_MAX_NEW_FRAMES:-default}" | tee -a "$LOG_PATH"
fi
echo "" | tee -a "$LOG_PATH"

# dfu_update.py imports PySide6 at module import time in your current version.
# If PySide6 isn't installed on the Pi, flashing will fail.
# python3 -c 'import PySide6' 2>/dev/null || {
#   echo "ERROR: PySide6 is not importable; dfu_update.py will likely fail on import." | tee -a "$LOG_PATH"
#   echo "Install PySide6 or refactor dfu_update.py to avoid importing PySide6 for CLI use." | tee -a "$LOG_PATH"
#   exit 2
# }

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
