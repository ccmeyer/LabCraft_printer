from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.run_virtual_workflow import _parser, main
from tools.virtual_workflows.registry import MANIFEST_PATH
from tools.virtual_workflows.joined_interaction_cases import (
    JOINED_INTERACTION_CASE_ID,
)
from tools.virtual_workflows.selection import (
    SELECTION_CATALOG_SCHEMA_NAME,
    SELECTION_PLAN_SCHEMA_NAME,
    SELECTION_RECOMMENDATION_SCHEMA_NAME,
    SelectionError,
    SelectionRequest,
    build_catalog,
    deterministic_json,
    discover_changed_paths,
    recommend_changed_paths,
    resolve_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_standard_suite_plan_is_frozen_and_non_executing():
    plan = resolve_selection(
        SelectionRequest(kind="suite", selector_id="standard")
    )

    assert plan["schema_name"] == SELECTION_PLAN_SCHEMA_NAME
    assert plan["execution_authorized"] is False
    assert plan["readiness"] == "ready"
    assert plan["scenario_count"] == 1
    assert plan["selector"] == {
        "kind": "suite",
        "id": "standard",
        "status": "active",
    }
    assert plan["scenarios"] == [
        {
            "order": 1,
            "scenario_id": "print_array_smoke_24_v1",
            "registry_id": "virtual_print_array_24_v1",
            "seed": 1,
            "timeout_seconds": 60.0,
            "tier": "smoke",
            "runner_family": "composed_journey",
            "assertion_ids": [
                "sil.host_hardware_disabled",
                "machine.normal_ui_ready",
                "experiment.prepared_bundle_valid",
                "execution.rack_head_associated",
                "execution.applied_calibration_valid",
                "execution.terminal_bundle_valid",
                "calibration.post_completion_diagnostics_available",
                "artifacts.cleanup_complete",
            ],
            "capability_ids": [
                "sil.hardware_isolation.host",
                "ui.real_app_construction",
                "execution.array_happy_path",
                "execution.terminal_bundle",
                "calibration.post_completion_diagnostics",
            ],
            "required_pi_evidence": [],
        }
    ]
    assert len(plan["manifest"]["sha256"]) == 64


def test_lifecycle_suite_preserves_manifest_order_and_per_scenario_timeouts():
    plan = resolve_selection(
        SelectionRequest(kind="suite", selector_id="lifecycle", seed=7)
    )

    assert [row["scenario_id"] for row in plan["scenarios"]] == [
        "experiment_editor_create_finalize_v1",
        "experiment_editor_prestart_rename_refinalize_v1",
        "experiment_editor_post_start_lock_v1",
        "legacy_experiment_read_only_v1",
        "print_array_soft_stop_resume_24_v1",
        "authoritative_reload_resume_24_v1",
        "print_array_multi_stock_24x2_v1",
        "print_array_mixed_mode_24x2_v1",
        "print_array_disconnect_mid_array_24_v1",
        JOINED_INTERACTION_CASE_ID,
        "calibration_storage_contract_v1",
        "calibration_storage_shadow_contract_v1",
        "calibration_storage_authoritative_contract_v1",
        "calibration_storage_primary_reader_contract_v1",
        "calibration_storage_secondary_reader_contract_v1",
        "calibration_storage_historical_conversion_contract_v1",
        "calibration_storage_new_store_only_contract_v1",
    ]
    assert [row["order"] for row in plan["scenarios"]] == list(range(1, 18))
    assert {row["seed"] for row in plan["scenarios"]} == {7}
    assert [row["timeout_seconds"] for row in plan["scenarios"]] == [
        60.0,
        60.0,
        60.0,
        60.0,
        60.0,
        60.0,
        60.0,
        90.0,
        60.0,
        180.0,
        300.0,
        600.0,
        600.0,
        600.0,
        600.0,
        120.0,
        180.0,
    ]


def test_capability_plan_preserves_active_scenario_order():
    plan = resolve_selection(
        SelectionRequest(
            kind="capability",
            selector_id="execution.mixed_droplet_stream_lifecycle",
        )
    )

    assert plan["selector"]["status"] == "covered"
    assert [row["registry_id"] for row in plan["scenarios"]] == [
        "print_array_mixed_mode_24x2_v1"
    ]


def test_pi_suite_plan_requires_and_retains_declared_evidence():
    plan = resolve_selection(
        SelectionRequest(
            kind="suite",
            selector_id="pi_primary",
            platform="pi_sil",
            pi_evidence=("preflight", "hardware_proof"),
        )
    )

    assert plan["platform"] == "pi_sil"
    assert plan["scenarios"][0]["registry_id"] == "virtual_print_array_96_v1"
    assert plan["scenarios"][0]["required_pi_evidence"] == [
        "preflight",
        "hardware_proof",
    ]


@pytest.mark.parametrize(
    ("section", "row_id"),
    [("suites", "lifecycle"), ("scenarios", "print_array_smoke_24_v1")],
)
def test_planner_rejects_inactive_manifest_rows(tmp_path, section, row_id):
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    row = next(item for item in payload[section] if item["id"] == row_id)
    row["status"] = "planned"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    request = SelectionRequest(
        kind="suite",
        selector_id=("lifecycle" if section == "suites" else "standard"),
    )
    with pytest.raises(SelectionError, match="is 'planned'"):
        resolve_selection(request, manifest_path=manifest_path)


@pytest.mark.parametrize(
    ("selection_request", "message"),
    [
        (
            SelectionRequest(kind="suite", selector_id="unknown"),
            "unknown suite",
        ),
        (
            SelectionRequest(
                kind="capability", selector_id="execution.refill_resume"
            ),
            "cannot be selected",
        ),
        (
            SelectionRequest(
                kind="suite", selector_id="pi_primary", platform="windows_sil"
            ),
            "requires platform",
        ),
        (
            SelectionRequest(
                kind="suite", selector_id="pi_primary", platform="pi_sil"
            ),
            "requires Pi safety evidence",
        ),
        (
            SelectionRequest(kind="suite", selector_id="standard", seed=2),
            "seed is frozen",
        ),
        (
            SelectionRequest(
                kind="suite",
                selector_id="standard",
                timeout_override=61,
            ),
            "timeout is frozen",
        ),
    ],
)
def test_selection_rejects_unready_ambiguous_or_drifted_requests(
    selection_request, message
):
    with pytest.raises(SelectionError, match=message):
        resolve_selection(selection_request)


def test_direct_scenario_dry_plan_accepts_existing_seed_and_timeout_controls():
    plan = resolve_selection(
        SelectionRequest(
            kind="scenario",
            selector_id="virtual_print_array_96_v1",
            seed=19,
            timeout_override=240,
        )
    )

    scenario = plan["scenarios"][0]
    assert scenario["scenario_id"] == "print_array_regression_96_v1"
    assert scenario["registry_id"] == "virtual_print_array_96_v1"
    assert scenario["seed"] == 19
    assert scenario["timeout_seconds"] == 240.0


def test_catalog_sections_are_manual_read_only_and_deterministic():
    suites = build_catalog("suites")
    capabilities = build_catalog("capabilities")
    all_rows = build_catalog("all")

    assert suites["schema_name"] == SELECTION_CATALOG_SCHEMA_NAME
    assert suites["execution_authorized"] is False
    assert "capabilities" not in suites
    assert "scenarios" not in suites
    assert {
        row["manual_trigger"]["automation_status"] for row in suites["suites"]
    } == {"manual"}
    assert {
        row["manual_trigger"]["cadence"] for row in suites["suites"]
    } == {"on_demand"}
    assert all(
        row["manual_trigger"]["max_evidence_age_days"] > 0
        for row in suites["suites"]
    )
    assert "suites" not in capabilities
    assert "capabilities" in all_rows and "scenarios" in all_rows
    assert deterministic_json(suites) == deterministic_json(
        build_catalog("suites")
    )


def test_changed_source_recommendations_match_exact_and_directory_paths():
    result = recommend_changed_paths(
        [
            "tools/virtual_workflows/page_drivers.py",
            "FreeRTOS-interface",
        ]
    )

    assert result["schema_name"] == SELECTION_RECOMMENDATION_SCHEMA_NAME
    assert result["execution_authorized"] is False
    assert result["changed_paths"] == [
        "FreeRTOS-interface",
        "tools/virtual_workflows/page_drivers.py",
    ]
    by_id = {
        row["capability_id"]: row for row in result["recommendations"]
    }
    assert "execution.mixed_droplet_stream_lifecycle" in by_id
    assert by_id["execution.mixed_droplet_stream_lifecycle"]["scenario_ids"] == [
        "print_array_mixed_mode_24x2_v1"
    ]
    assert "protocol.serial_lifecycle" in by_id
    assert by_id["protocol.serial_lifecycle"]["status"] == "deferred"
    assert all(
        set(row) == {"scenario_id", "registry_id"}
        for row in result["scenarios"]
    )


def test_changed_source_recommendations_reject_paths_outside_repo():
    with pytest.raises(SelectionError, match="outside the repository"):
        recommend_changed_paths([REPO_ROOT.parent / "outside-selection.py"])


def test_git_discovery_combines_tracked_and_untracked_paths(monkeypatch):
    responses = iter(
        [
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="README.md\n", stderr=""
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="tools/virtual_workflows/new.py\nREADME.md\n",
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(responses))

    assert discover_changed_paths() == (
        "README.md",
        "tools/virtual_workflows/new.py",
    )


def test_cli_selection_modes_are_mutually_exclusive_and_execution_is_available():
    parser = _parser()
    with pytest.raises(SystemExit) as conflict:
        parser.parse_args(["--suite", "standard", "--capability", "x"])
    assert conflict.value.code == 2

    args = parser.parse_args(["--suite", "standard"])
    assert args.suite == "standard"
    assert args.dry_run is False

    with pytest.raises(SystemExit) as coverage_conflict:
        parser.parse_args(
            ["--coverage-from", "aggregate.json", "--suite", "standard"]
        )
    assert coverage_conflict.value.code == 2


def test_cli_coverage_mode_is_explicit_repeatable_and_qt_free(
    tmp_path, monkeypatch, capsys
):
    import tools.virtual_workflows.coverage as coverage

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("{}\n", encoding="utf-8")
    second.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "output"
    evaluation_path = tmp_path / "coverage.json"
    summary_path = tmp_path / "summary.txt"
    evaluation_path.write_text("{}\n", encoding="utf-8")
    summary_path.write_text("coverage summary\n", encoding="utf-8")
    captured = {}

    def fake_execute(config):
        captured["config"] = config
        return SimpleNamespace(
            evaluation_path=evaluation_path,
            summary_path=summary_path,
            exit_code=0,
        )

    monkeypatch.setattr(coverage, "execute_coverage_evaluation", fake_execute)
    assert main(
        [
            "--coverage-from", str(first),
            "--coverage-from", str(second),
            "--output-root", str(output),
        ]
    ) == 0
    config = captured["config"]
    assert config.aggregate_paths == (first, second)
    assert config.output_root == output
    assert config.replay_command.count("--coverage-from") == 2
    rendered = capsys.readouterr().out
    assert "coverage summary" in rendered
    assert f"Coverage: {evaluation_path}" in rendered


@pytest.mark.parametrize(
    "extra",
    [
        ["--seed", "2"],
        ["--speed-multiplier", "1000"],
        ["--timeout-seconds", "1"],
        ["--visible"],
        ["--dry-run"],
        ["--target-pi"],
        ["--compare", "a.json", "b.json"],
    ],
)
def test_cli_coverage_rejects_execution_planning_and_comparison_controls(extra):
    with pytest.raises(SystemExit) as exc_info:
        main(["--coverage-from", "aggregate.json", *extra])
    assert exc_info.value.code == 2


def test_cli_planning_prints_json_without_dispatch_or_artifact_writes(
    tmp_path, monkeypatch, capsys
):
    import tools.run_virtual_workflow as cli

    monkeypatch.setattr(
        cli,
        "run_registered_scenario",
        lambda *args, **kwargs: pytest.fail("planning dispatched a workflow"),
    )
    output_root = tmp_path / "must-not-exist"

    assert main(
        [
            "--suite",
            "standard",
            "--dry-run",
            "--output-root",
            str(output_root),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert not output_root.exists()


def test_cli_changed_path_overrides_git_discovery(monkeypatch, capsys):
    import tools.run_virtual_workflow as cli

    monkeypatch.setattr(
        cli,
        "discover_changed_paths",
        lambda *args: pytest.fail("explicit paths must override Git discovery"),
    )
    assert main(
        [
            "--recommend-changed",
            "--changed-path",
            "tools/virtual_workflows/page_drivers.py",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed_paths"] == [
        "tools/virtual_workflows/page_drivers.py"
    ]


def test_cli_planning_and_catalog_are_qt_application_import_free():
    script = """
import sys
from tools.run_virtual_workflow import main
assert main(['--suite', 'standard', '--dry-run']) == 0
assert main(['--list', 'capabilities']) == 0
forbidden = {
    'App', 'Controller', 'Model', 'View', 'Machine_FreeRTOS', 'PySide6',
    'tools.virtual_workflows.scenarios',
}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit(f'unexpected imports: {loaded}')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_manifest_identity_hashes_the_tracked_bytes():
    plan = resolve_selection(
        SelectionRequest(kind="suite", selector_id="standard")
    )
    assert plan["manifest"]["sha256"] == hashlib.sha256(
        MANIFEST_PATH.read_bytes()
    ).hexdigest()
