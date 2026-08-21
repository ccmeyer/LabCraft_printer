from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "run_development_app.py"
SPEC = importlib.util.spec_from_file_location("run_development_app", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_no_hardware_launch_isolates_qt_state_and_reports_child_pid(
    monkeypatch, tmp_path, capsys
):
    root = (tmp_path / "development-machine-data").resolve()
    root.mkdir()
    monkeypatch.setattr(
        launcher,
        "load_development_store",
        lambda supplied: type("Store", (), {"root": Path(supplied).resolve()})(),
    )
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/unsafe/plugins")
    captured = {}

    class Process:
        pid = 4242

        def __init__(self, arguments, **kwargs):
            captured["arguments"] = list(arguments)
            captured.update(kwargs)

        def wait(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", Process)
    result = launcher.main(
        [
            "--machine-data-root", str(root),
            "--operator", "Conary-Codex",
            "--auto-close-seconds", "1.25",
        ]
    )

    assert result == 0
    environment = captured["env"]
    assert environment["LABCRAFT_MACHINE_DATA_ROOT"] == str(root)
    assert environment["LABCRAFT_DEPLOYMENT_MODE"] == "development"
    assert environment["LABCRAFT_DEVELOPMENT_OPERATOR"] == "Conary-Codex"
    assert environment["LABCRAFT_DEVELOPMENT_HARDWARE"] == "0"
    assert environment["LABCRAFT_DEVELOPMENT_AUTOCLOSE_MS"] == "1250"
    assert environment["QT_QPA_PLATFORM"] == "offscreen"
    assert "QT_PLUGIN_PATH" not in environment
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        assert root in Path(environment[name]).resolve().parents
    assert captured["cwd"] == REPO_ROOT
    assert captured["arguments"][-1] == str(REPO_ROOT / "FreeRTOS-interface" / "App.py")
    output = capsys.readouterr().out
    assert "Development mode: NO HARDWARE" in output
    assert "Development app PID: 4242" in output


def test_autoclose_rejects_hardware_or_out_of_range(monkeypatch, tmp_path, capsys):
    root = (tmp_path / "development-machine-data").resolve()
    root.mkdir()
    monkeypatch.setattr(
        launcher,
        "load_development_store",
        lambda supplied: type("Store", (), {"root": Path(supplied).resolve()})(),
    )
    for extra in (
        ["--auto-close-seconds", "0.1"],
        [
            "--enable-hardware",
            "--hardware-confirmation",
            launcher.DEVELOPMENT_HARDWARE_CONFIRMATION,
            "--clear-envelope-confirmation",
            launcher.DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION,
            "--hardware-authorization",
            str(tmp_path / "authorization.json"),
            "--expected-commit",
            "a" * 40,
            "--auto-close-seconds",
            "1",
        ],
    ):
        result = launcher.main(
            ["--machine-data-root", str(root), "--operator", "Operator", *extra]
        )
        assert result == 2
        assert "auto-close requires no-hardware mode" in capsys.readouterr().err


def test_empty_operator_fails_before_process_creation(monkeypatch, tmp_path):
    root = (tmp_path / "development-machine-data").resolve()
    root.mkdir()
    monkeypatch.setattr(
        launcher,
        "load_development_store",
        lambda supplied: type("Store", (), {"root": Path(supplied).resolve()})(),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("process must not start")
        ),
    )
    assert launcher.main(
        ["--machine-data-root", str(root), "--operator", "   "]
    ) == 2


def test_hardware_inputs_are_complete_and_rejected_in_no_hardware_mode(
    monkeypatch, tmp_path, capsys
):
    root = (tmp_path / "development-machine-data").resolve()
    root.mkdir()
    monkeypatch.setattr(
        launcher,
        "load_development_store",
        lambda supplied: type("Store", (), {"root": Path(supplied).resolve()})(),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("process must not start")
        ),
    )
    base = ["--machine-data-root", str(root), "--operator", "Operator"]
    assert launcher.main([*base, "--enable-hardware", "--hardware-confirmation",
                          launcher.DEVELOPMENT_HARDWARE_CONFIRMATION]) == 2
    assert "clear-envelope" in capsys.readouterr().err
    assert launcher.main([*base, "--expected-commit", "a" * 40]) == 2
    assert "cannot be used in no-hardware" in capsys.readouterr().err


def test_complete_hardware_launch_passes_only_commit_bound_environment(
    monkeypatch, tmp_path
):
    root = (tmp_path / "development-machine-data").resolve()
    root.mkdir()
    authorization = (tmp_path / "authorization.json").resolve()
    authorization.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        launcher,
        "load_development_store",
        lambda supplied: type("Store", (), {"root": Path(supplied).resolve()})(),
    )
    captured = {}

    class Process:
        pid = 4243

        def __init__(self, arguments, **kwargs):
            captured["arguments"] = list(arguments)
            captured.update(kwargs)

        def wait(self):
            return 0

    monkeypatch.setattr(launcher.subprocess, "Popen", Process)
    result = launcher.main(
        [
            "--machine-data-root", str(root), "--operator", "Operator",
            "--enable-hardware",
            "--hardware-confirmation", launcher.DEVELOPMENT_HARDWARE_CONFIRMATION,
            "--clear-envelope-confirmation",
            launcher.DEVELOPMENT_CLEAR_ENVELOPE_CONFIRMATION,
            "--hardware-authorization", str(authorization),
            "--expected-commit", "a" * 40,
        ]
    )
    assert result == 0
    environment = captured["env"]
    assert environment["LABCRAFT_DEVELOPMENT_HARDWARE"] == "1"
    assert environment["LABCRAFT_DEVELOPMENT_HARDWARE_AUTHORIZATION"] == str(authorization)
    assert environment["LABCRAFT_DEVELOPMENT_EXPECTED_COMMIT"] == "a" * 40
    assert "LABCRAFT_DEVELOPMENT_AUTOCLOSE_MS" not in environment
