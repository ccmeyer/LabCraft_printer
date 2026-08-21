from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
UI = REPO_ROOT / "FreeRTOS-interface"
for candidate in (str(TOOLS), str(UI)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
SPEC = importlib.util.spec_from_file_location(
    "pi_development_hardware", TOOLS / "pi_development_hardware.py"
)
assert SPEC is not None and SPEC.loader is not None
hardware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hardware)


def test_remote_worker_is_valid_and_launch_is_explicitly_gated() -> None:
    compile(hardware.REMOTE_WORKER, "<remote-hardware>", "exec")
    source = hardware.REMOTE_WORKER
    assert 'request["execute"]' in source
    assert "create_authorization" in source
    assert '"--enable-hardware"' in source
    assert "start_new_session=True" in source
    assert "os.killpg(process.pid" in source
    assert "update_and_restart.py" in source
    assert "dfu_update.py" in source


def test_dry_run_does_not_use_ssh_or_launch(capsys) -> None:
    code = hardware.main(
        ["--pi-host", "192.0.2.10", "--operator", "Operator", "--dry-run"]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "No SSH call, application launch, or evidence write" in output
    assert "Updater, rollback, and in-app DFU remain blocked" in output


def test_launch_requires_execute_and_exact_confirmation(capsys) -> None:
    base = ["--action", "launch", "--pi-host", "192.0.2.10", "--operator", "Operator"]
    assert hardware.main(base) == 1
    assert "exact attended confirmation" in capsys.readouterr().err
    assert hardware.main([*base, "--execute", "--attended-confirmation", "wrong"]) == 1
    assert "exact attended confirmation" in capsys.readouterr().err


def test_no_hardware_runtime_is_visible_in_dry_run(capsys) -> None:
    assert hardware.main(
        ["--pi-host", "192.0.2.10", "--runtime-mode", "no-hardware", "--dry-run"]
    ) == 0
    assert "runtime=no-hardware" in capsys.readouterr().out


def test_powershell_wrapper_dry_run() -> None:
    wrapper = TOOLS / "run_pi_development_hardware.ps1"
    completed = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
         "-PiHost", "192.0.2.10", "-Operator", "Operator", "-DryRun"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "No SSH call, application launch, or evidence write" in completed.stdout


def test_hardware_session_root_cannot_enter_either_worktree() -> None:
    for path in (
        "/home/labcraft/LabCraft_printer/session",
        "/home/labcraft/LabCraft_printer-dev/session",
    ):
        try:
            hardware._external_path(
                path, pi_user="labcraft",
                worktrees=("/home/labcraft/LabCraft_printer", "/home/labcraft/LabCraft_printer-dev"),
            )
        except hardware.DevelopmentHardwareError:
            pass
        else:
            raise AssertionError("worktree-contained evidence path was accepted")
