from __future__ import annotations

import subprocess
from pathlib import Path

from tests.calibration_history_conversion_helpers import experiment


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / "env" / "Scripts" / "python.exe"
TOOL = REPO_ROOT / "tools" / "convert_calibration_history.py"


def test_cli_dry_run_writes_nothing_and_emits_progress(tmp_path):
    root = experiment(tmp_path)
    before = (root / "calibration.json").read_bytes()
    result = subprocess.run(
        [
            str(PYTHON), str(TOOL), "--experiment-dir", str(root),
            "--progress", "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "CALIBRATION_MIGRATION_PROGRESS" in result.stdout
    assert '"writes_performed": 0' in result.stdout
    assert not (root / "calibration_history_migration.json").exists()
    assert (root / "calibration.json").read_bytes() == before


def test_cli_rejects_repository_root():
    result = subprocess.run(
        [str(PYTHON), str(TOOL), "--experiment-dir", str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "refusing broad conversion target" in result.stderr
