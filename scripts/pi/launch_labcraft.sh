#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_PATH="$REPO_ROOT/FreeRTOS-interface/App.py"
LOG_DIR="$REPO_ROOT/logs"
LOG_FILE="$LOG_DIR/desktop-launch.log"

mkdir -p "$LOG_DIR"

if [ ! -f "$APP_PATH" ]; then
  {
    printf '\n[%s] Launcher failed: app entrypoint not found.\n' "$(date -Iseconds)"
    printf 'Expected: %s\n' "$APP_PATH"
  } >>"$LOG_FILE"
  exit 1
fi

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/venv/bin/python"
elif [ -x "$REPO_ROOT/env/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/env/bin/python"
else
  {
    printf '\n[%s] Launcher failed: no repo-local Python interpreter found.\n' "$(date -Iseconds)"
    printf 'Expected one of:\n'
    printf '  %s\n' "$REPO_ROOT/.venv/bin/python"
    printf '  %s\n' "$REPO_ROOT/venv/bin/python"
    printf '  %s\n' "$REPO_ROOT/env/bin/python"
  } >>"$LOG_FILE"
  exit 1
fi

{
  printf '\n[%s] Starting LabCraft Printer desktop launch.\n' "$(date -Iseconds)"
  printf 'Repo root: %s\n' "$REPO_ROOT"
  printf 'Python: %s\n' "$PYTHON_BIN"
  printf 'App: %s\n' "$APP_PATH"
} >>"$LOG_FILE"

cd "$REPO_ROOT"
export PYTHONUNBUFFERED=1
exec >>"$LOG_FILE" 2>&1
exec "$PYTHON_BIN" "$APP_PATH"
