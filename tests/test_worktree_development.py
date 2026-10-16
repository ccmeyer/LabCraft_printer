import json
from pathlib import Path
import re
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
    ["--config-file", "other.ini"], ["--config-file=other.ini"],
    ["--debug"], ["--debug=other.log"], ["--debug", "other.log"],
])
def test_runner_refuses_evidence_overrides(args):
    with pytest.raises(ValueError, match="Runner owns"):
        dev.test_arguments(args)


@pytest.mark.parametrize("option", ["config", "config_equals", "debug", "debug_equals", "debug_path"])
def test_runner_refuses_config_and_debug_before_launch(tmp_path, option):
    protected = tmp_path / "protected.log"
    protected.write_text("preserve existing evidence")
    plugin_marker = tmp_path / "plugin-loaded"
    plugin = tmp_path / "conftest.py"
    plugin.write_text(f"from pathlib import Path\nPath({str(plugin_marker)!r}).touch()\n")
    config = tmp_path / "custom.ini"
    config.write_text(f"[pytest]\nlog_file={protected.as_posix()}\n")
    args = {
        "config": ["--config-file", str(config)],
        "config_equals": [f"--config-file={config}"],
        "debug": ["--debug"],
        "debug_equals": [f"--debug={protected}"],
        "debug_path": ["--debug", str(protected)],
    }[option]
    result = subprocess.run(
        [sys.executable, "-B", str(dev.ROOT / "tools/worktree_development.py"), "test", "--", *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Runner owns pytest configuration and evidence paths" in result.stderr
    assert not plugin_marker.exists()
    assert not (tmp_path / "pytestdebug.log").exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert protected.read_text() == "preserve existing evidence"


def test_runner_preserves_selectors_and_opt_in_arguments():
    args = ["-q", "tests/a file.py", "-k", "one or two", "--run-sil-lifecycle",
            "--historical-fixture-root", "C:/fixture data"]
    assert dev.test_arguments(args) == args


def test_documented_historical_command_collects_through_powershell(tmp_path):
    guide = (dev.ROOT / "docs/windows_worktrees.md").read_text(encoding="utf-8")
    section = guide.split("## Historical recording replays", 1)[1]
    command = re.search(r"\.\\tools\\run_worktree_tests\.ps1 -PytestArgs @\((.*?)\)",
                        section, re.DOTALL)
    assert command is not None
    arguments = re.findall(r"'([^']*)'", command.group(1))
    fixture_option = arguments.index("--historical-fixture-root")
    # An existing external path used to change pytest's initial conftest lookup.
    # Collect only: this checks the documented invocation without archive inputs.
    arguments[fixture_option + 1] = str(tmp_path)
    arguments.append("--collect-only")
    wrapper = dev.ROOT / "tools/run_worktree_tests.ps1"
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    script = tmp_path / "documented-command.ps1"
    script.write_text(
        f"& {quote(wrapper)} -PytestArgs @({','.join(map(quote, arguments))})\n"
        "exit $LASTEXITCODE\n", encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=dev.ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sparse_online_tail_replay_matches_dense_offline_tail_start_with_scout_backtrack" in result.stdout
    assert "test_replay_legacy_metric_keeps_best_actual_y_in_known_focus_basin" in result.stdout
    assert "unrecognized arguments" not in result.stdout + result.stderr


@pytest.fixture
def accented_git_worktrees(tmp_path):
    primary = tmp_path / "primary"
    accented = tmp_path / "worktree-\u00e9 with spaces"
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    subprocess.run(["git", "init", "-q", str(primary)], check=True, capture_output=True)
    prefix = ["git", "-C", str(primary), "-c", f"core.hooksPath={hooks}",
              "-c", "user.name=Worktree Regression", "-c", "user.email=regression@example.invalid"]
    subprocess.run([*prefix, "commit", "--allow-empty", "-qm", "Owned regression fixture"],
                   check=True, capture_output=True)
    subprocess.run([*prefix, "worktree", "add", "-qb", "regression", str(accented)],
                   check=True, capture_output=True)
    return primary, accented


def test_git_accepts_accented_worktree_root(accented_git_worktrees):
    _, accented = accented_git_worktrees
    assert dev.validate_root(accented) == accented.resolve()


@pytest.mark.parametrize("active", [0, 1])
def test_runner_refuses_temp_inside_accented_registered_worktree(accented_git_worktrees, monkeypatch, active):
    primary, accented = accented_git_worktrees
    run_root = accented / "temporary-output"
    run_root.mkdir()
    monkeypatch.setattr(dev, "verify_environment", lambda root: {})
    monkeypatch.setattr(dev.tempfile, "mkdtemp", lambda **kwargs: str(run_root))
    monkeypatch.setattr(dev, "test_environment", lambda *args: pytest.fail("Output setup reached"))
    with pytest.raises(ValueError, match="outside all worktrees"):
        dev.run_tests((primary, accented)[active], [])
    assert list(run_root.iterdir()) == []


def test_runner_refuses_missing_worktree_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "validate_root", lambda root: root)
    monkeypatch.setattr(dev, "verify_environment", lambda root: {})
    monkeypatch.setattr(dev.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(dev, "git", lambda *args, **kwargs: "")
    monkeypatch.setattr(dev, "test_environment", lambda *args: pytest.fail("Output setup reached"))
    with pytest.raises(ValueError, match="Cannot establish registered worktree boundaries"):
        dev.run_tests(tmp_path, [])
    assert list(tmp_path.iterdir()) == []


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


def test_child_imports_belong_to_current_worktree():
    result = subprocess.run([sys.executable, "-c",
        "import sys,json;from pathlib import Path;"
        "from tools import worktree_development as d;"
        "sys.path.insert(0,str(d.ROOT/'FreeRTOS-interface'));import LocalConfig;"
        "print(json.dumps(dict(root=str(d.ROOT),module=LocalConfig.__file__,prefix=sys.prefix)))"],
        cwd=dev.ROOT, capture_output=True, text=True, timeout=30, check=True)
    identity = json.loads(result.stdout)
    assert Path(identity["root"]).resolve() == dev.ROOT
    assert Path(identity["module"]).resolve().is_relative_to(dev.ROOT / "FreeRTOS-interface")
    assert Path(identity["prefix"]).resolve() == dev.ROOT / "env"


def test_verify_environment_rejects_another_worktree_prefix(tmp_path, monkeypatch):
    (tmp_path / "env/Scripts").mkdir(parents=True)
    (tmp_path / "env/Scripts/python.exe").touch()
    monkeypatch.setattr(dev, "python_identity", lambda p:
                        {"prefix": str(tmp_path / "other/env"), "base_prefix": "base"})
    with pytest.raises(ValueError, match="not this worktree"):
        dev.verify_environment(tmp_path)


def test_verify_environment_rejects_changed_package_version(tmp_path, monkeypatch):
    (tmp_path / "env/Scripts").mkdir(parents=True)
    (tmp_path / "env/Scripts/python.exe").touch()
    monkeypatch.setattr(dev, "python_identity", lambda p:
                        {"prefix": str(tmp_path / "env"), "base_prefix": "base"})
    monkeypatch.setattr(dev, "lock_pins", lambda r: {"pytest": "required"})
    monkeypatch.setattr(dev, "invoke", lambda *a, **k: '{"pytest":"different"}')
    with pytest.raises(ValueError, match="Environment differs"):
        dev.verify_environment(tmp_path)


def test_incomplete_environment_names_missing_interpreter_and_preserves_files(tmp_path):
    (tmp_path / "env").mkdir()
    marker = tmp_path / "env/partial.txt"
    marker.write_text("preserve")
    with pytest.raises(ValueError, match="Environment is missing or incomplete.*python.exe"):
        dev.verify_environment(tmp_path)
    assert list((tmp_path / "env").iterdir()) == [marker]
    assert marker.read_text() == "preserve"


@pytest.mark.parametrize("status", ["+wrong commit", "Uconflict", "-uninitialized"])
def test_firmware_check_refuses_invalid_submodule_without_mutation(tmp_path, monkeypatch, status):
    cube = tmp_path / "cube"
    cube.mkdir()
    (cube / "headless-build.bat").touch()
    monkeypatch.setattr(dev, "CUBE", cube)
    monkeypatch.setattr(dev.shutil, "which", lambda n: "available")
    calls = []
    monkeypatch.setattr(dev, "git_submodule", lambda *a, **k: calls.append(a) or status)
    monkeypatch.setattr(dev, "git", lambda *a, **k: "160000 commit abc module")
    with pytest.raises(ValueError):
        dev.firmware_preflight(tmp_path, check_only=True)
    assert len(calls) == 1 and calls[0][0] == "status"
