from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_launch_script_sets_repo_root_and_logs_to_root_logs_dir():
    text = _read("scripts/pi/launch_labcraft.sh")

    assert 'REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"' in text
    assert 'cd "$REPO_ROOT"' in text
    assert 'LOG_FILE="$LOG_DIR/desktop-launch.log"' in text
    assert 'exec >>"$LOG_FILE" 2>&1' in text
    assert 'exec "$PYTHON_BIN" "$APP_PATH"' in text


def test_launch_script_supports_dotvenv_venv_and_env_repo_layouts():
    text = _read("scripts/pi/launch_labcraft.sh")

    assert '$REPO_ROOT/.venv/bin/python' in text
    assert '$REPO_ROOT/venv/bin/python' in text
    assert '$REPO_ROOT/env/bin/python' in text
    assert "no repo-local Python interpreter found" in text


def test_installer_is_user_scoped_and_does_not_reconfigure_pi():
    text = _read("scripts/pi/install_desktop_launcher.sh")

    assert '${XDG_DATA_HOME:-$HOME/.local/share}/applications' in text
    assert '$REPO_ROOT/.venv/bin/python' in text
    assert '$REPO_ROOT/venv/bin/python' in text
    assert '$REPO_ROOT/env/bin/python' in text
    assert 'chmod +x "$LAUNCHER_PATH"' in text
    assert 'import App' in text
    assert "apt-get" not in text
    assert "usermod" not in text
    assert "groupadd" not in text
    assert "udevadm" not in text
    assert "/boot/firmware" not in text
    assert "python3 -m venv" not in text
    assert "pip install" not in text


def test_desktop_template_uses_absolute_runtime_placeholders_and_no_terminal():
    text = _read("scripts/pi/labcraft-printer.desktop.in")

    assert "Exec=__LABCRAFT_EXEC__" in text
    assert "Path=__LABCRAFT_PATH__" in text
    assert "Icon=__LABCRAFT_ICON__" in text
    assert "Terminal=false" in text
    assert "Name=LabCraft Printer" in text
