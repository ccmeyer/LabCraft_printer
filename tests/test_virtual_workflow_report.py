from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

from tools.virtual_workflows.report import (
    ComposedReportAdapter,
    ComposedReportPayload,
    collect_source_tree_identity,
    composed_report_contract_projection,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def test_source_tree_identity_changes_for_code_but_not_documentation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("first\n", encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "plan.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", ".")

    initial = collect_source_tree_identity(repo)
    assert initial["error"] is None
    assert initial["file_count"] == 1

    (repo / "README.md").write_text("second\n", encoding="utf-8")
    (docs / "plan.txt").write_text("second\n", encoding="utf-8")
    documentation_only = collect_source_tree_identity(repo)
    assert documentation_only["sha256"] == initial["sha256"]

    (repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    code_changed = collect_source_tree_identity(repo)
    assert code_changed["sha256"] != initial["sha256"]

    (repo / "new_source.py").write_text("NEW = True\n", encoding="utf-8")
    untracked_changed = collect_source_tree_identity(repo)
    assert untracked_changed["sha256"] != code_changed["sha256"]


def test_composed_report_adapter_builds_common_truthful_envelope(tmp_path):
    report_dir = tmp_path / "reports" / "run"
    report_dir.mkdir(parents=True)
    scenario_root = tmp_path / "session"
    roots = SimpleNamespace(
        config_root=scenario_root / "config",
        experiments_root=scenario_root / "experiments",
        calibration_memory_root=scenario_root / "calibration-memory",
    )
    for value in vars(roots).values():
        Path(value).mkdir(parents=True)
    screenshot = report_dir / "screenshots" / "ready.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"png")
    harness = SimpleNamespace(
        run_id="run-1",
        started_at_utc="2026-01-01T00:00:00Z",
        duration_ms=12.5,
        failure=None,
        config=SimpleNamespace(visible=False, speed_multiplier=2, seed=7),
        session=SimpleNamespace(application_roots=roots),
        scenario_root=scenario_root,
        report_dir=report_dir,
        context=SimpleNamespace(
            screenshots={"ready": screenshot},
            action_results=[
                {
                    "action_id": "machine.connect_via_ui",
                    "interaction_surface": "ui",
                    "status": "pass",
                }
            ],
            milestones=[{"name": "ready"}],
            dialogs=[],
            unexpected_dialogs=[],
            errors=[],
        ),
        assertion_results=[
            {
                "assertion_id": "sil.host_hardware_disabled",
                "decision": "pass",
            }
        ],
    )
    sections = ComposedReportAdapter(
        harness, repo_root=Path(__file__).resolve().parents[1]
    ).sections(
        workload_id="workload",
        scenario_name="scenario",
        scenario_version="1",
        replay_command=["python", "runner.py"],
        passed=True,
    )
    assert sections["classification"]["status"] == "pass"
    assert sections["run"]["seed"] == 7
    assert sections["run"]["replay_command"] == ["python", "runner.py"]
    assert sections["safety"]["hardware_access_allowed"] is False
    assert sections["safety"]["root_containment_valid"] is True
    assert sections["artifacts"]["screenshots"] == {
        "ready": "screenshots/ready.png"
    }

    report = ComposedReportAdapter(
        harness, repo_root=Path(__file__).resolve().parents[1]
    ).build(
        workload_id="workload",
        scenario_name="scenario",
        scenario_version="1",
        replay_command=["python", "runner.py"],
        required_assertion_ids=("sil.host_hardware_disabled",),
        required_ui_action_ids=frozenset({"machine.connect_via_ui"}),
        payload=ComposedReportPayload(
            workload={"workload_id": "workload"},
            persistence={
                "status": "measured",
                "values": {
                    "assertion_decisions": {
                        "sil.host_hardware_disabled": "pass"
                    }
                },
            },
        ),
    )
    projection = composed_report_contract_projection(report)
    assert projection["actions"] == [
        {
            "action_id": "machine.connect_via_ui",
            "interaction_surface": "ui",
            "status": "pass",
        }
    ]
    assert projection["assertions"] == [
        {
            "assertion_id": "sil.host_hardware_disabled",
            "decision": "pass",
        }
    ]
