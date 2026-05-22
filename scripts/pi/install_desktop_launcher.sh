#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_PATH="$REPO_ROOT/FreeRTOS-interface/App.py"
LAUNCHER_PATH="$SCRIPT_DIR/launch_labcraft.sh"
TEMPLATE_PATH="$SCRIPT_DIR/labcraft-printer.desktop.in"
ICON_PATH="$REPO_ROOT/FreeRTOS-interface/Presets/LabCraft_icon.png"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/labcraft-printer.desktop"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

choose_python() {
  if [ -x "$REPO_ROOT/venv/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/venv/bin/python"
    return 0
  fi
  if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/.venv/bin/python"
    return 0
  fi
  if [ -x "$REPO_ROOT/env/bin/python" ]; then
    printf '%s\n' "$REPO_ROOT/env/bin/python"
    return 0
  fi
  return 1
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[&|]/\\&/g'
}

case "$(uname -s)" in
  Linux*) ;;
  *)
    fail "This installer is intended to run on Linux desktop systems."
    ;;
esac

[ -f "$APP_PATH" ] || fail "App entrypoint not found at $APP_PATH"
[ -f "$TEMPLATE_PATH" ] || fail "Desktop template not found at $TEMPLATE_PATH"
[ -f "$ICON_PATH" ] || fail "Icon not found at $ICON_PATH"
[ -f "$LAUNCHER_PATH" ] || fail "Launcher script not found at $LAUNCHER_PATH"

PYTHON_BIN="$(choose_python)" || fail "No repo-local .venv, venv, or env interpreter was found. Keep using the current manual setup until the Python environment is ready."

printf 'Using repo root: %s\n' "$REPO_ROOT"
printf 'Using Python: %s\n' "$PYTHON_BIN"
printf 'Validating App import...\n'
if ! PYTHONPATH="$REPO_ROOT/FreeRTOS-interface${PYTHONPATH:+:$PYTHONPATH}" QT_QPA_PLATFORM=offscreen "$PYTHON_BIN" -c "import App" >/dev/null 2>&1; then
  fail "Could not import App with $PYTHON_BIN. Keep the existing manual Pi setup and fix the Python environment before installing the launcher."
fi

chmod +x "$LAUNCHER_PATH"
mkdir -p "$DESKTOP_DIR"

LABCRAFT_EXEC="\"$LAUNCHER_PATH\""
sed \
  -e "s|__LABCRAFT_EXEC__|$(escape_sed_replacement "$LABCRAFT_EXEC")|g" \
  -e "s|__LABCRAFT_PATH__|$(escape_sed_replacement "$REPO_ROOT")|g" \
  -e "s|__LABCRAFT_ICON__|$(escape_sed_replacement "$ICON_PATH")|g" \
  "$TEMPLATE_PATH" >"$DESKTOP_FILE"

chmod 0644 "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

printf 'Installed desktop launcher: %s\n' "$DESKTOP_FILE"
printf 'Launch it from the application menu as "LabCraft Printer".\n'
printf 'Launcher diagnostics will be written to: %s\n' "$REPO_ROOT/logs/desktop-launch.log"
