from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import run_simulated_app
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
)


def test_launcher_defaults_to_clean_fresh_session():
    args = run_simulated_app.build_parser().parse_args([])
    config = run_simulated_app.config_from_args(args)
    assert config.root_policy is SessionRootPolicy.FRESH
    assert config.session_root is None
    assert (
        config.artifact_retention
        is ArtifactRetentionPolicy.DELETE_CLEAN_FRESH
    )
    assert config.seed == 1
    assert config.speed_multiplier == 1.0


def test_launcher_keep_and_retained_root_policies(tmp_path):
    keep_args = run_simulated_app.build_parser().parse_args(["--keep-session"])
    keep_config = run_simulated_app.config_from_args(keep_args)
    assert keep_config.root_policy is SessionRootPolicy.FRESH
    assert keep_config.artifact_retention is ArtifactRetentionPolicy.RETAIN

    root = (tmp_path / "retained").resolve()
    retained_args = run_simulated_app.build_parser().parse_args(
        [
            "--session-root",
            str(root),
            "--seed",
            "42",
            "--speed-multiplier",
            "3.5",
        ]
    )
    retained = run_simulated_app.config_from_args(retained_args)
    assert retained.root_policy is SessionRootPolicy.RETAINED
    assert retained.session_root == root
    assert retained.artifact_retention is ArtifactRetentionPolicy.RETAIN
    assert retained.seed == 42
    assert retained.speed_multiplier == 3.5


def test_launcher_rejects_relative_retained_root():
    args = run_simulated_app.build_parser().parse_args(
        ["--session-root", "relative-session"]
    )
    with pytest.raises(ValueError, match="must be absolute"):
        run_simulated_app.config_from_args(args)


def test_launcher_exit_contract_and_console_identity(monkeypatch, capsys, tmp_path):
    calls = []

    class _FakeSession:
        session_root = (tmp_path / "fake-session").resolve()
        root_removed = False

        def launch(self):
            calls.append("launch")

        def run(self):
            calls.append("run")
            return 0

        def close(self):
            calls.append("close")
            return True

        def mark_failed(self, reason):
            calls.append(("failed", reason))

    monkeypatch.setattr(
        run_simulated_app.SimulationSession,
        "create",
        lambda _config: _FakeSession(),
    )

    assert run_simulated_app.main(["--keep-session"]) == 0
    assert calls == ["launch", "run", "close"]
    output = capsys.readouterr().out
    assert "Hardware access: BLOCKED" in output
    assert "SIMULATED" in output
    assert "Simulation session retained at:" in output


def test_launcher_returns_failure_when_teardown_fails(monkeypatch, tmp_path):
    fake = SimpleNamespace(
        session_root=(tmp_path / "failed").resolve(),
        root_removed=False,
        launch=lambda: None,
        run=lambda: 0,
        close=lambda: False,
        mark_failed=lambda _reason: None,
    )
    monkeypatch.setattr(
        run_simulated_app.SimulationSession,
        "create",
        lambda _config: fake,
    )
    assert run_simulated_app.main(["--keep-session"]) == 1

