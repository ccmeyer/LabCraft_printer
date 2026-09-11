import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import worktree_development as dev


def test_lock_is_complete_pinned_and_scoped_away_from_pi_inventory():
    pins = dev.lock_pins(dev.ROOT)
    assert {"pytest", "pytest-qt", "pyside6", "numpy", "scipy", "psutil"} <= pins.keys()
    assert len(dev.LOCK.parts) > 1


@pytest.mark.parametrize("args", [
    ["--basetemp=x"], ["--junitxml", "x"], ["--junit-xml=x"], ["-o", "addopts=x"],
    ["-oaddopts=x"], ["-cother.ini"], ["-p", "other"], ["--log-file=x"], ["--rootdir=x"],
])
def test_runner_refuses_evidence_overrides(args):
    with pytest.raises(ValueError, match="Runner owns"):
        dev.test_arguments(args)


def test_runner_preserves_selectors_and_opt_in_arguments():
    args = ["-q", "tests/a file.py", "-k", "one or two", "--run-sil-lifecycle",
            "--historical-fixture-root", "C:/fixture data"]
    assert dev.test_arguments(args) == args


def test_runner_scrubs_authority_without_mutating_parent(tmp_path):
    source = dict(LABCRAFT_MACHINE_DATA_ROOT="production", LABCRAFT_DEVELOPMENT_HARDWARE="1",
                  LABCRAFT_DEPLOYMENT_MODE="production", PYTEST_ADDOPTS="--basetemp=shared",
                  PYTHONPATH="other-worktree", PATH="unchanged")
    env = dev.test_environment(tmp_path, source)
    assert env["PATH"] == "unchanged"
    assert env["QT_QPA_PLATFORM"] == "offscreen"
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert not any(k.startswith("LABCRAFT_") for k in env)
    assert "PYTHONPATH" not in env and "PYTEST_ADDOPTS" not in env
    assert source["LABCRAFT_MACHINE_DATA_ROOT"] == "production"
    assert Path(env["TEMP"]).is_relative_to(tmp_path)


def _fake_setup(monkeypatch, root):
    monkeypatch.setattr(dev, "validate_root", lambda r: r)
    monkeypatch.setattr(dev, "python_identity", lambda p: {})
    monkeypatch.setattr(dev, "lock_pins", lambda r: {"pytest": "1"})
    calls = []
    monkeypatch.setattr(dev, "invoke", lambda a, **k: calls.append(a))
    monkeypatch.setattr(dev, "verify_environment", lambda r: {"prefix": str(root / "env")})
    return calls


def test_setup_check_only_never_creates_environment(tmp_path, monkeypatch):
    calls = _fake_setup(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="env is missing"):
        dev.setup(tmp_path, Path(sys.executable), check_only=True)
    assert not (tmp_path / "env").exists()
    assert calls == []


def test_setup_creates_only_this_environment_then_rechecks(tmp_path, monkeypatch):
    root = tmp_path / "worktree with spaces"
    root.mkdir()
    calls = _fake_setup(monkeypatch, root)
    dev.setup(root, Path(sys.executable))
    assert calls[0][-1] == root / "env"
    assert calls[1][0] == root / "env/Scripts/python.exe"
    assert "--no-deps" in calls[1]
    calls.clear()
    dev.setup(root, Path(sys.executable))
    dev.setup(root, Path(sys.executable), check_only=True)
    assert calls == []


def test_partial_environment_is_preserved_and_never_reinstalled(tmp_path, monkeypatch):
    calls = _fake_setup(monkeypatch, tmp_path)
    (tmp_path / "env").mkdir()
    marker = tmp_path / "env/partial.txt"
    marker.write_text("preserve")
    def refuse(root):
        raise ValueError("partial environment")
    monkeypatch.setattr(dev, "verify_environment", refuse)
    with pytest.raises(ValueError, match="partial"):
        dev.setup(tmp_path, Path(sys.executable))
    assert calls == [] and marker.read_text() == "preserve"


def test_setup_interruption_leaves_a_refused_partial_environment(tmp_path, monkeypatch):
    _fake_setup(monkeypatch, tmp_path)
    def interrupt(*a, **k):
        raise subprocess.CalledProcessError(37, ["pip"], "", "interrupted")
    monkeypatch.setattr(dev, "invoke", interrupt)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        dev.setup(tmp_path, Path(sys.executable))
    assert exc.value.returncode == 37
    assert (tmp_path / "env").is_dir()


def test_main_preserves_subprocess_exit_code(monkeypatch):
    def fail(*a, **k):
        raise subprocess.CalledProcessError(37, ["pip"], "output", "error")
    monkeypatch.setattr(dev, "setup", fail)
    assert dev.main(["setup", "--python", sys.executable]) == 37


def test_git_bash_arguments_are_not_interpolated(tmp_path, monkeypatch):
    (tmp_path / "cmd").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/bash.exe").touch()
    monkeypatch.setattr(dev.shutil, "which", lambda n: str(tmp_path / "cmd/git.exe"))
    calls = []
    monkeypatch.setattr(dev, "invoke", lambda a, **k: calls.append(a) or "")
    dev.git_submodule("status", "--", dev.SUBMODULE, root=tmp_path / "worktree with spaces")
    assert calls[0][2] == 'exec git "$@"'
    assert calls[0][-1] == dev.SUBMODULE
