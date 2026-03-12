import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "tools" / "pull_pi_calibration_records.ps1"


def _powershell_exe():
    return shutil.which("powershell") or shutil.which("pwsh")


def _write_fake_openssh_bin(bin_dir: Path):
    ssh_cmd = bin_dir / "ssh.cmd"
    ssh_cmd.write_text(
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        "if not \"%SSH_CALLS%\"==\"\" echo %*>>\"%SSH_CALLS%\"\r\n"
        "if /I \"%SSH_SCENARIO%\"==\"multi\" (\r\n"
        "  echo 1700000200^|ExpAlpha^|/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/ExpAlpha\r\n"
        "  echo 1700000100^|ExpBeta^|/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/ExpBeta\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        "if /I \"%SSH_SCENARIO%\"==\"single\" (\r\n"
        "  echo 1700000200^|ScreeningA^|/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/ScreeningA\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        "echo 1700000300^|LatestExp^|/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/LatestExp\r\n"
        "echo 1700000200^|OlderExp^|/home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/OlderExp\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    scp_cmd = bin_dir / "scp.cmd"
    scp_cmd.write_text(
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        "if not \"%SCP_CALLS%\"==\"\" echo %*>>\"%SCP_CALLS%\"\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )


def _run_script(args, tmp_path, *, scenario="default"):
    exe = _powershell_exe()
    if exe is None:
        pytest.skip("PowerShell is not available")

    bin_dir = tmp_path / "fake_bin"
    bin_dir.mkdir()
    _write_fake_openssh_bin(bin_dir)

    ssh_calls = tmp_path / "ssh_calls.txt"
    scp_calls = tmp_path / "scp_calls.txt"

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["SSH_CALLS"] = str(ssh_calls)
    env["SCP_CALLS"] = str(scp_calls)
    env["SSH_SCENARIO"] = scenario

    cmd = [
        exe,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT_PATH),
        *args,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    return result, ssh_calls, scp_calls


def test_pull_pi_calibration_records_requires_exactly_one_selector(tmp_path):
    result, _ssh_calls, _scp_calls = _run_script(
        ["-PiHost", "192.168.0.29", "-DryRun"],
        tmp_path,
    )

    assert result.returncode != 0
    assert "Provide exactly one experiment selector" in (result.stderr + result.stdout)


def test_pull_pi_calibration_records_dry_run_normalizes_user_at_host(tmp_path):
    result, ssh_calls, scp_calls = _run_script(
        ["-PiHost", "tester@pi-box", "-Latest", "-DryRun"],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "SSH target: tester@pi-box" in result.stdout
    assert "Selected experiment: LatestExp" in result.stdout
    assert ssh_calls.read_text(encoding="utf-8")
    assert not scp_calls.exists() or scp_calls.read_text(encoding="utf-8").strip() == ""


def test_pull_pi_calibration_records_dry_run_reports_layout_and_replay_command(tmp_path):
    result, _ssh_calls, _scp_calls = _run_script(
        [
            "-PiHost",
            "192.168.0.29",
            "-ExperimentName",
            "LatestExp",
            "-CopyMode",
            "CalibrationOnly",
            "-ProcessName",
            "NozzlePositionCalibrationProcess",
            "-RunId",
            "run_20260304_111716_24e5f347",
            "-DryRun",
        ],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "Remote experiment path: /home/labcraft/LabCraft_printer/FreeRTOS-interface/Experiments/LatestExp" in result.stdout
    assert "Local destination:" in result.stdout
    assert "Selected records destination:" in result.stdout
    assert "tools\\replay_calibration_run.py --root" in result.stdout


def test_pull_pi_calibration_records_match_reports_ambiguous_candidates(tmp_path):
    result, _ssh_calls, _scp_calls = _run_script(
        ["-PiHost", "192.168.0.29", "-ExperimentMatch", "Exp", "-DryRun"],
        tmp_path,
        scenario="multi",
    )

    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "ambiguous" in combined.lower()
    assert "ExpAlpha" in combined
    assert "ExpBeta" in combined
