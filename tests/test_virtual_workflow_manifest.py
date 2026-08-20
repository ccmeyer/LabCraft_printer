from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.run_virtual_workflow import _parser, main
from tools.virtual_workflows.registry import (
    DEFAULT_SCENARIO_ID,
    MANIFEST_ID,
    MANIFEST_PATH,
    MANIFEST_SCHEMA_NAME,
    MANIFEST_SCHEMA_VERSION,
    REGISTERED_SCENARIOS,
    ManifestValidationError,
    get_registered_scenario,
    load_capability_manifest,
    registered_scenario_ids,
    run_registered_scenario,
    validate_capability_manifest,
)
from tools.virtual_workflows.scenarios import (
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
            DISCONNECT_WORKLOAD_ID,
            NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
            MULTI_STOCK_WORKLOAD_ID,
            MIXED_MODE_WORKLOAD_ID,
            STRESS_WORKLOAD_ID,
    SCENARIO_COMPLETION_COUNTS,
    SCENARIO_FIXTURES,
    SOFT_STOP_RESUME_WORKLOAD_ID,
    SMOKE_WORKLOAD_ID,
    STRESS_WORKLOAD_ID,
    WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    load_virtual_print_array_fixture,
)
from tools.virtual_workflows.editor_scenarios import (
    POST_START_LOCK_WORKLOAD_ID as EDITOR_POST_START_WORKLOAD_ID,
    RENAME_WORKLOAD_ID as EDITOR_RENAME_WORKLOAD_ID,
    WORKLOAD_ID as EDITOR_WORKLOAD_ID,
)
from tools.virtual_workflows.journeys import LEGACY_READ_ONLY_WORKLOAD_ID
from tools.virtual_workflows.calibration_storage_journeys import (
    AUTHORITATIVE_FUNCTIONAL_ID as CALIBRATION_STORAGE_AUTHORITATIVE_CONTRACT_ID,
    AUTHORITATIVE_PERFORMANCE_ID as CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_ID,
    FUNCTIONAL_ID as CALIBRATION_STORAGE_CONTRACT_ID,
    PERFORMANCE_ID as CALIBRATION_STORAGE_PERFORMANCE_ID,
    PRIMARY_READER_FUNCTIONAL_ID as CALIBRATION_STORAGE_PRIMARY_READER_CONTRACT_ID,
    PRIMARY_READER_PERFORMANCE_ID as CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_ID,
    SECONDARY_READER_FUNCTIONAL_ID as CALIBRATION_STORAGE_SECONDARY_READER_CONTRACT_ID,
    SECONDARY_READER_PERFORMANCE_ID as CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_ID,
    NEW_STORE_ONLY_FUNCTIONAL_ID as CALIBRATION_STORAGE_NEW_STORE_ONLY_CONTRACT_ID,
    SHADOW_FUNCTIONAL_ID as CALIBRATION_STORAGE_SHADOW_CONTRACT_ID,
    SHADOW_PERFORMANCE_ID as CALIBRATION_STORAGE_SHADOW_PERFORMANCE_ID,
)
from tools.virtual_workflows.calibration_history_conversion_journey import (
    SCENARIO_ID as CALIBRATION_STORAGE_HISTORICAL_CONVERSION_ID,
)
from tools.virtual_workflows.actions import ACTION_INTERACTION_SURFACES
from tools.virtual_workflows.joined_interaction_cases import (
    JOINED_INTERACTION_CASE_ID,
    JOINED_INTERACTION_FIXTURE_PATH,
)
from tools.virtual_workflows.optimizer_360_cases import (
    OPTIMIZER_360_CASE_ID,
    OPTIMIZER_360_FIXTURE_PATH,
)
from tools.virtual_workflows.matrices import get_matrix_definition


REPO_ROOT = Path(__file__).resolve().parents[1]


def _raw_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _row(payload: dict[str, object], section: str, row_id: str) -> dict[str, object]:
    return next(
        row
        for row in payload[section]
        if isinstance(row, dict) and row["id"] == row_id
    )


def test_registry_preserves_legacy_default_order_fixtures_and_counts():
    assert DEFAULT_SCENARIO_ID == WORKLOAD_ID
    assert registered_scenario_ids() == (
        WORKLOAD_ID,
        STRESS_WORKLOAD_ID,
        SMOKE_WORKLOAD_ID,
        EDITOR_WORKLOAD_ID,
        EDITOR_RENAME_WORKLOAD_ID,
        EDITOR_POST_START_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
        LEGACY_READ_ONLY_WORKLOAD_ID,
        MIXED_MODE_WORKLOAD_ID,
        DISCONNECT_WORKLOAD_ID,
        JOINED_INTERACTION_CASE_ID,
        OPTIMIZER_360_CASE_ID,
        CALIBRATION_STORAGE_CONTRACT_ID,
        CALIBRATION_STORAGE_PERFORMANCE_ID,
        CALIBRATION_STORAGE_SHADOW_CONTRACT_ID,
        CALIBRATION_STORAGE_SHADOW_PERFORMANCE_ID,
        CALIBRATION_STORAGE_AUTHORITATIVE_CONTRACT_ID,
        CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_ID,
        CALIBRATION_STORAGE_PRIMARY_READER_CONTRACT_ID,
        CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_ID,
        CALIBRATION_STORAGE_SECONDARY_READER_CONTRACT_ID,
        CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_ID,
        CALIBRATION_STORAGE_HISTORICAL_CONVERSION_ID,
        CALIBRATION_STORAGE_NEW_STORE_ONLY_CONTRACT_ID,
    )

    for scenario_id in (WORKLOAD_ID, STRESS_WORKLOAD_ID, SMOKE_WORKLOAD_ID):
        definition = get_registered_scenario(scenario_id)
        fixture = load_virtual_print_array_fixture(scenario_id=scenario_id)

        assert definition.registry_id == scenario_id
        assert definition.workload_id == scenario_id
        assert definition.fixture_path == SCENARIO_FIXTURES[scenario_id]
        assert definition.expected_completion_count == (
            SCENARIO_COMPLETION_COUNTS[scenario_id]
        )
        assert fixture["fixture_id"] == scenario_id
        assert fixture["workload"]["completion_count"] == (
            definition.expected_completion_count
        )

    with pytest.raises(TypeError):
        REGISTERED_SCENARIOS["another"] = get_registered_scenario(WORKLOAD_ID)


def test_tracked_manifest_validates_and_describes_current_truth():
    payload = load_capability_manifest()

    assert payload["schema_name"] == MANIFEST_SCHEMA_NAME
    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["manifest_id"] == MANIFEST_ID
    assert {
        scenario["registry_id"] for scenario in payload["scenarios"]
    } == set(registered_scenario_ids())
    assert payload["policy"]["coverage_join_status"] == (
        "implemented_milestone_8_slice_4"
    )
    assert payload["policy"]["safeguard_matrix_coverage_join_status"] == (
        "implemented_milestone_12_slice_5"
    )
    safeguard_matrices = {
        row["id"]: row
        for row in payload["policy"]["safeguard_matrix_catalog"]
    }
    assert set(safeguard_matrices) == {
        "editor_safeguards_v1",
        "execution_preflight_safeguards_v1",
        "authoritative_persistence_safeguards_v1",
    }
    for matrix_id, row in safeguard_matrices.items():
        definition = get_matrix_definition(matrix_id)
        assert row["case_ids"] == list(definition.case_ids())
        assert row["case_count"] == len(definition.case_ids())
        assert row["required_assertion_ids"] == [
            "safeguard_rejection_no_mutation_no_dispatch"
        ]
    assert {
        row["id"]: row["interaction_surface"]
        for row in payload["policy"]["action_catalog"]
    } == {
        action_id: surface.value
        for action_id, surface in ACTION_INTERACTION_SURFACES.items()
    }

    standard = _row(payload, "suites", "standard")
    lifecycle = _row(payload, "suites", "lifecycle")
    assert standard["status"] == "active"
    assert standard["scenario_ids"] == ["print_array_smoke_24_v1"]
    assert lifecycle["status"] == "active"
    assert lifecycle["scenario_ids"] == [
        "experiment_editor_create_finalize_v1",
        "experiment_editor_prestart_rename_refinalize_v1",
        "experiment_editor_post_start_lock_v1",
        LEGACY_READ_ONLY_WORKLOAD_ID,
        "print_array_soft_stop_resume_24_v1",
            NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
            MULTI_STOCK_WORKLOAD_ID,
            MIXED_MODE_WORKLOAD_ID,
            DISCONNECT_WORKLOAD_ID,
            JOINED_INTERACTION_CASE_ID,
            CALIBRATION_STORAGE_CONTRACT_ID,
            CALIBRATION_STORAGE_SHADOW_CONTRACT_ID,
                CALIBRATION_STORAGE_AUTHORITATIVE_CONTRACT_ID,
                CALIBRATION_STORAGE_PRIMARY_READER_CONTRACT_ID,
                CALIBRATION_STORAGE_SECONDARY_READER_CONTRACT_ID,
                CALIBRATION_STORAGE_HISTORICAL_CONVERSION_ID,
                CALIBRATION_STORAGE_NEW_STORE_ONLY_CONTRACT_ID,
        ]
    rename_scenario = _row(
        payload,
        "scenarios",
        "experiment_editor_prestart_rename_refinalize_v1",
    )
    assert rename_scenario["status"] == "active"
    assert rename_scenario["suite_ids"] == ["lifecycle"]
    assert rename_scenario["registry_id"] == EDITOR_RENAME_WORKLOAD_ID
    post_start = _row(
        payload,
        "scenarios",
        EDITOR_POST_START_WORKLOAD_ID,
    )
    assert post_start["status"] == "active"
    assert post_start["suite_ids"] == ["lifecycle"]
    assert post_start["registry_id"] == EDITOR_POST_START_WORKLOAD_ID
    soft_stop = _row(
        payload,
        "scenarios",
        SOFT_STOP_RESUME_WORKLOAD_ID,
    )
    assert soft_stop["status"] == "active"
    assert soft_stop["suite_ids"] == ["lifecycle"]
    assert soft_stop["registry_id"] == SOFT_STOP_RESUME_WORKLOAD_ID
    assert "fixture.prepare_authoritative" not in soft_stop["action_ids"]
    assert "array.resume_via_ui" in soft_stop["action_ids"]
    assert soft_stop["required_artifacts"] == [
        "report_json",
        "summary_text",
        "event_trace",
        "action_ledger",
        "assertion_ledger",
        "evidence_manifest",
        "screenshots",
        "scenario_root",
    ]
    new_session = _row(
        payload,
        "scenarios",
        NEW_EXPERIMENT_SESSION_WORKLOAD_ID,
    )
    assert new_session["status"] == "active"
    assert new_session["suite_ids"] == ["lifecycle"]
    assert new_session["registry_id"] == NEW_EXPERIMENT_SESSION_WORKLOAD_ID
    assert new_session["capability_ids"] == [
        "sil.hardware_isolation.host",
        "ui.real_app_construction",
        "experiment.new_session_transactional",
    ]
    authoritative_reload = _row(
        payload,
        "scenarios",
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
    )
    assert authoritative_reload["status"] == "active"
    assert authoritative_reload["suite_ids"] == ["lifecycle"]
    assert authoritative_reload["registry_id"] == (
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID
    )
    randomized = _row(payload, "scenarios", JOINED_INTERACTION_CASE_ID)
    assert randomized["status"] == "active"
    assert randomized["suite_ids"] == ["lifecycle"]
    assert randomized["timeout_seconds"] == 180
    assert randomized["workload_fixture_path"] == (
        JOINED_INTERACTION_FIXTURE_PATH.relative_to(REPO_ROOT).as_posix()
    )
    assert randomized["capability_ids"] == [
        "sil.hardware_isolation.host",
        "ui.real_app_construction",
        "execution.randomized_calibration_reload_execution",
    ]
    optimizer_360 = _row(payload, "scenarios", OPTIMIZER_360_CASE_ID)
    assert optimizer_360["status"] == "active"
    assert optimizer_360["tier"] == "stress"
    assert optimizer_360["suite_ids"] == ["host_stress"]
    assert optimizer_360["supported_platforms"] == ["windows_sil"]
    assert optimizer_360["timeout_seconds"] == 600
    assert optimizer_360["workload_fixture_path"] == (
        OPTIMIZER_360_FIXTURE_PATH.relative_to(REPO_ROOT).as_posix()
    )
    assert optimizer_360["capability_ids"] == [
        "sil.hardware_isolation.host",
        "ui.real_app_construction",
        "execution.optimizer_360_calibration_reload_execution",
    ]
    host_stress = _row(payload, "suites", "host_stress")
    assert host_stress["scenario_ids"] == [
        "print_array_stress_384x10_v1",
        OPTIMIZER_360_CASE_ID,
        CALIBRATION_STORAGE_PERFORMANCE_ID,
        CALIBRATION_STORAGE_SHADOW_PERFORMANCE_ID,
        CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_ID,
        CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_ID,
        CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_ID,
    ]
    assert OPTIMIZER_360_CASE_ID not in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    assert CALIBRATION_STORAGE_PERFORMANCE_ID in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    assert CALIBRATION_STORAGE_SHADOW_PERFORMANCE_ID in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    assert CALIBRATION_STORAGE_AUTHORITATIVE_PERFORMANCE_ID in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    assert CALIBRATION_STORAGE_PRIMARY_READER_PERFORMANCE_ID in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    assert CALIBRATION_STORAGE_SECONDARY_READER_PERFORMANCE_ID in _row(
        payload, "suites", "pi_stress"
    )["scenario_ids"]
    multi_stock = _row(payload, "scenarios", MULTI_STOCK_WORKLOAD_ID)
    assert multi_stock["status"] == "active"
    assert multi_stock["suite_ids"] == ["lifecycle"]
    assert multi_stock["registry_id"] == MULTI_STOCK_WORKLOAD_ID
    assert "fixture.prepare_authoritative" not in multi_stock["action_ids"]
    assert "head.stage_virtual" not in multi_stock["action_ids"]
    assert {
        "editor.configure_design_via_ui",
        "head.bind_identity",
        "head.stage_via_ui",
        "head.return_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
    } <= set(multi_stock["action_ids"])
    assert multi_stock["required_artifacts"] == [
        "report_json",
        "summary_text",
        "event_trace",
        "action_ledger",
        "assertion_ledger",
        "evidence_manifest",
        "screenshots",
        "scenario_root",
    ]
    disconnect = _row(payload, "scenarios", DISCONNECT_WORKLOAD_ID)
    assert disconnect["status"] == "active"
    assert disconnect["suite_ids"] == ["lifecycle"]
    assert "machine.disconnect_via_ui" in disconnect["action_ids"]
    assert "array.wait_for_completions" not in disconnect["action_ids"]
    assert "execution.disconnect_fail_closed" in disconnect["assertion_ids"]
    stress = _row(payload, "scenarios", "print_array_stress_384x10_v1")
    assert "fixture.prepare_authoritative" not in stress["action_ids"]
    assert "head.stage_virtual" not in stress["action_ids"]
    assert {"head.bind_identity", "head.stage_via_ui", "head.return_via_ui",
            "validation.stock_pass_boundary"} <= set(stress["action_ids"])
    assert "ui.sustained_responsiveness_acceptable" in stress["assertion_ids"]
    assert {"action_ledger", "assertion_ledger", "evidence_manifest"} <= set(
        stress["required_artifacts"]
    )

    smoke = _row(payload, "scenarios", "print_array_smoke_24_v1")
    assert smoke["registry_id"] == SMOKE_WORKLOAD_ID
    assert smoke["tier"] == "smoke"
    assert smoke["suite_ids"] == ["standard"]
    assert smoke["supported_platforms"] == ["windows_sil"]
    assert smoke["pi_safety_evidence"] == []
    assert "calibration.post_completion_diagnostics_available" in smoke[
        "assertion_ids"
    ]
    assert "calibration.post_completion_diagnostics" in smoke[
        "capability_ids"
    ]
    assert "experiment.inspect_completed_via_ui" in smoke["action_ids"]
    assert "execution.same_session_completed_projection_exact" in smoke[
        "assertion_ids"
    ]
    assert "execution.same_session_completed_projection" in smoke[
        "capability_ids"
    ]

    capabilities = {
        capability["id"]: capability for capability in payload["capabilities"]
    }
    assert capabilities["execution.refill_resume"]["status"] == "deferred"
    assert capabilities["calibration.post_completion_diagnostics"] == {
        "id": "calibration.post_completion_diagnostics",
        "risk": (
            "Terminal completion could prevent same-session printer-head diagnostics "
            "or allow a diagnostic result to mutate completed execution artifacts."
        ),
        "owner_role": "calibration verification maintainers",
        "status": "covered",
        "required_verification_layers": ["contract", "host_sil"],
        "active_scenario_ids": ["print_array_smoke_24_v1"],
        "required_assertion_ids": [
            "calibration.post_completion_diagnostics_available"
        ],
        "related_source_areas": [
            "FreeRTOS-interface/View.py",
            "FreeRTOS-interface/CalibrationClasses/View.py",
            "FreeRTOS-interface/Model.py",
        ],
        "limitations": [
            "The host SIL uses a synthetic full calibration; trajectory-aware "
            "Recheck dispatch remains focused Qt integration coverage and no "
            "physical camera, pressure, or droplet behavior is claimed."
        ],
        "max_evidence_age_days": 2,
    }
    assert capabilities["execution.same_session_completed_projection"] == {
        "id": "execution.same_session_completed_projection",
        "risk": (
            "A completed execution could fail to display read-only in the live "
            "session because plate-format signals reassign stale runtime reactions "
            "during authoritative projection."
        ),
        "owner_role": "execution persistence maintainers",
        "status": "covered",
        "required_verification_layers": ["contract", "host_sil"],
        "active_scenario_ids": ["print_array_smoke_24_v1"],
        "required_assertion_ids": [
            "execution.same_session_completed_projection_exact"
        ],
        "related_source_areas": [
            "FreeRTOS-interface/Model.py",
            "FreeRTOS-interface/View.py",
            "tools/virtual_workflows/page_drivers.py",
        ],
        "limitations": [
            "The host SIL verifies same-session Qt projection and persisted "
            "immutability with a generated design; explicit uploaded/manual "
            "assignments remain focused Model integration coverage."
        ],
        "max_evidence_age_days": 2,
    }
    assert capabilities["experiment.editor_create_finalize"]["status"] == "covered"
    assert capabilities["experiment.prepared_reopen"]["status"] == "covered"
    assert capabilities["experiment.design_plan_consistency"]["status"] == "covered"
    assert (
        capabilities["experiment.prepared_rename_refinalize"]["status"]
        == "covered"
    )
    assert capabilities["experiment.active_edit_lock"]["status"] == "covered"
    assert capabilities["experiment.editable_copy"]["status"] == "covered"
    assert capabilities["execution.soft_stop_resume"]["status"] == "covered"
    assert capabilities["experiment.new_session_transactional"]["status"] == (
        "covered"
    )
    assert capabilities["experiment.new_session_transactional"][
        "active_scenario_ids"
    ] == [NEW_EXPERIMENT_SESSION_WORKLOAD_ID]
    assert (
        capabilities["execution.authoritative_reload_resume"]["status"]
        == "covered"
    )
    assert (
        capabilities["execution.authoritative_reload_resume"][
            "active_scenario_ids"
        ]
        == [AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID]
    )
    assert (
        capabilities["execution.authoritative_reload_resume"][
            "max_evidence_age_days"
        ]
        == 2
    )
    assert (
        capabilities["execution.soft_stop_resume"]["max_evidence_age_days"]
        == 2
    )
    assert (
        capabilities["experiment.active_edit_lock"]["max_evidence_age_days"]
        == 2
    )
    assert (
        capabilities["experiment.editable_copy"]["max_evidence_age_days"]
        == 2
    )
    assert capabilities["execution.multi_stock_head_exchange"]["status"] == (
        "covered"
    )
    assert capabilities["execution.multi_stock_head_exchange"][
        "active_scenario_ids"
    ] == [MULTI_STOCK_WORKLOAD_ID]
    assert capabilities["execution.multi_stock_head_exchange"][
        "max_evidence_age_days"
    ] == 2
    assert capabilities["execution.mixed_droplet_stream_lifecycle"][
        "active_scenario_ids"
    ] == [MIXED_MODE_WORKLOAD_ID]
    assert capabilities["execution.disconnect_fail_closed"]["status"] == "covered"
    assert capabilities["execution.disconnect_fail_closed"][
        "active_scenario_ids"
    ] == [DISCONNECT_WORKLOAD_ID]
    assert {
        schedule["automation_status"] for schedule in payload["schedules"]
    } == {"manual"}
    assert {schedule["cadence"] for schedule in payload["schedules"]} == {
        "on_demand"
    }
    assert all(
        schedule["id"] == f"{schedule['suite_id']}_on_demand"
        for schedule in payload["schedules"]
    )
    assert payload["policy"]["coverage_join_status"] == (
        "implemented_milestone_8_slice_4"
    )
    assert payload["policy"]["generated_evidence_updates_manifest"] is False


def test_cli_scenario_surface_is_registry_driven_and_legacy_compatible():
    parser = _parser()
    action = next(item for item in parser._actions if item.dest == "scenario")

    assert tuple(action.choices) == registered_scenario_ids()
    assert parser.parse_args([]).scenario == DEFAULT_SCENARIO_ID
    assert parser.parse_args(
        ["--scenario", STRESS_WORKLOAD_ID]
    ).scenario == STRESS_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", SMOKE_WORKLOAD_ID]
    ).scenario == SMOKE_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", EDITOR_WORKLOAD_ID]
    ).scenario == EDITOR_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", EDITOR_RENAME_WORKLOAD_ID]
    ).scenario == EDITOR_RENAME_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", EDITOR_POST_START_WORKLOAD_ID]
    ).scenario == EDITOR_POST_START_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", SOFT_STOP_RESUME_WORKLOAD_ID]
    ).scenario == SOFT_STOP_RESUME_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", MULTI_STOCK_WORKLOAD_ID]
    ).scenario == MULTI_STOCK_WORKLOAD_ID
    assert parser.parse_args(
        ["--scenario", MIXED_MODE_WORKLOAD_ID]
    ).scenario == MIXED_MODE_WORKLOAD_ID


@pytest.mark.parametrize(
    "scenario_id",
    [
        WORKLOAD_ID,
        STRESS_WORKLOAD_ID,
        SMOKE_WORKLOAD_ID,
        EDITOR_WORKLOAD_ID,
        EDITOR_RENAME_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
    ],
)
def test_registry_dispatch_uses_existing_config_and_runner(
    scenario_id,
    tmp_path,
    monkeypatch,
):
    from tools.virtual_workflows import journeys, scenarios

    captured = []

    def fake_run(config):
        captured.append(config)
        return {"scenario_id": config.scenario_id}

    monkeypatch.setattr(scenarios, "run_virtual_print_array_scenario", fake_run)
    monkeypatch.setattr(journeys, "run_virtual_print_array_24_journey", fake_run)
    monkeypatch.setattr(journeys, "run_editor_create_finalize_journey", fake_run)
    monkeypatch.setattr(journeys, "run_multi_stock_24x2_journey", fake_run)
    monkeypatch.setattr(journeys, "run_composed_journey", fake_run)

    result = run_registered_scenario(
        scenario_id,
        output_root=tmp_path,
        speed_multiplier=25,
        timeout_seconds=90,
    )

    assert result == {"scenario_id": scenario_id}
    assert len(captured) == 1
    config = captured[0]
    if scenario_id in {
        WORKLOAD_ID,
        SMOKE_WORKLOAD_ID,
        EDITOR_WORKLOAD_ID,
        EDITOR_RENAME_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
        MIXED_MODE_WORKLOAD_ID,
        STRESS_WORKLOAD_ID,
    }:
        from tools.virtual_workflows.journeys import JourneyRunConfig

        assert isinstance(config, JourneyRunConfig)
    else:
        assert isinstance(config, VirtualPrintArrayScenarioConfig)
    assert config.scenario_id == scenario_id
    if scenario_id not in {
        WORKLOAD_ID,
        SMOKE_WORKLOAD_ID,
        EDITOR_WORKLOAD_ID,
        EDITOR_RENAME_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
        STRESS_WORKLOAD_ID,
    }:
        assert config.fixture_path == SCENARIO_FIXTURES[scenario_id].resolve()
    assert config.output_root == tmp_path.resolve()
    assert config.speed_multiplier == 25
    assert config.timeout_seconds == 90


@pytest.mark.parametrize(
    "scenario_id",
    [
        EDITOR_WORKLOAD_ID,
        EDITOR_RENAME_WORKLOAD_ID,
        EDITOR_POST_START_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
    ],
)
@pytest.mark.parametrize(
    "extra_args",
    [
        ["--target-pi"],
        ["--inject-ui-stall-ms", "10"],
        ["--inject-after-completion", "1"],
        ["--warmup-runs", "1", "--host-label", "local"],
        ["--measured-runs", "2", "--host-label", "local"],
        ["--emit-report-set", "--host-label", "local"],
        ["--accept-baseline", "baseline.json", "--host-label", "local"],
    ],
)
def test_editor_lifecycle_cli_rejects_unsupported_evidence_modes(
    scenario_id,
    extra_args,
    capsys,
):
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "--scenario",
                scenario_id,
                "--timeout-seconds",
                "60",
                *extra_args,
            ]
        )

    assert caught.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "scenario_id",
    [
        WORKLOAD_ID,
        STRESS_WORKLOAD_ID,
        SMOKE_WORKLOAD_ID,
        SOFT_STOP_RESUME_WORKLOAD_ID,
        AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        MULTI_STOCK_WORKLOAD_ID,
    ],
)
def test_cli_dispatches_each_registered_id_through_registry(
    scenario_id,
    tmp_path,
    monkeypatch,
):
    import tools.run_virtual_workflow as cli

    calls = []

    def fake_dispatch(selected, **config_values):
        calls.append((selected, config_values))
        report_dir = tmp_path / f"report-{len(calls)}"
        scenario_root = report_dir / "scenario-root"
        scenario_root.mkdir(parents=True)
        (report_dir / "summary.txt").write_text("synthetic\n", encoding="utf-8")
        return {
            "safety": {"scenario_root": str(scenario_root)},
            "classification": {"status": "pass"},
        }

    monkeypatch.setattr(cli, "run_registered_scenario", fake_dispatch)

    assert main(
        [
            "--scenario",
            scenario_id,
            "--output-root",
            str(tmp_path / "unused-output"),
        ]
    ) == 0
    assert len(calls) == 1
    selected, config_values = calls[0]
    assert selected == scenario_id
    assert config_values["output_root"] == (tmp_path / "unused-output")
    assert config_values["visible"] is False
    assert config_values["speed_multiplier"] == 1.0
    assert config_values["timeout_seconds"] == 180.0
    assert config_values["pi_preflight_path"] is None
    assert config_values["pi_hardware_proof_path"] is None


def test_registry_import_and_cli_help_are_application_import_free():
    script = """
import sys
from tools.run_virtual_workflow import _parser
_parser().format_help()
forbidden = {
    "App",
    "Controller",
    "Model",
    "View",
    "Machine_FreeRTOS",
    "PySide6",
    "tools.virtual_workflows.scenarios",
}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit(f"unexpected imports: {loaded}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def _unknown_top_level(payload):
    payload["unexpected"] = True


def _invalid_capability_status(payload):
    payload["capabilities"][0]["status"] = "green"


def _duplicate_capability(payload):
    payload["capabilities"].append(copy.deepcopy(payload["capabilities"][0]))


def _duplicate_scenario(payload):
    payload["scenarios"].append(copy.deepcopy(payload["scenarios"][0]))


def _duplicate_suite(payload):
    payload["suites"].append(copy.deepcopy(payload["suites"][0]))


def _duplicate_action(payload):
    catalog = payload["policy"]["action_catalog"]
    catalog.append(copy.deepcopy(catalog[0]))


def _duplicate_assertion(payload):
    catalog = payload["policy"]["assertion_catalog"]
    catalog.append(copy.deepcopy(catalog[0]))


def _unreferenced_action(payload):
    payload["policy"]["action_catalog"].append(
        {
            "id": "unused.action",
            "implementation_status": "embedded",
            "source_path": "tools/virtual_workflows/scenarios.py",
        }
    )


def _unreferenced_assertion(payload):
    payload["policy"]["assertion_catalog"].append(
        {
            "id": "unused.assertion",
            "evidence_kind": "pytest",
            "evidence_path": None,
            "test_node_ids": [
                "tests/test_virtual_workflow_manifest.py::test_tracked_manifest_validates_and_describes_current_truth"
            ],
        }
    )


def _missing_registry_scenario(payload):
    payload["scenarios"].pop()


def _unknown_registry_scenario(payload):
    payload["scenarios"][0]["registry_id"] = "unknown_scenario_v1"


def _absolute_fixture_path(payload):
    payload["scenarios"][0]["workload_fixture_path"] = "C:/private/fixture.json"


def _scenario_without_assertions(payload):
    payload["scenarios"][0]["assertion_ids"] = []


def _scenario_with_unknown_action(payload):
    payload["scenarios"][0]["action_ids"].append("unknown.action")


def _scenario_with_unknown_suite(payload):
    payload["scenarios"][0]["suite_ids"].append("unknown_suite")


def _scenario_with_missing_test(payload):
    payload["scenarios"][0]["test_node_ids"][0] = (
        "tests/system/test_virtual_print_array_workflow.py::test_missing"
    )


def _covered_capability_without_scenario(payload):
    payload["capabilities"][0]["active_scenario_ids"] = []


def _covered_capability_without_required_assertion(payload):
    payload["capabilities"][0]["active_scenario_ids"] = [
        "print_array_regression_96_v1"
    ]
    payload["capabilities"][0]["required_assertion_ids"] = ["resources.metrics_present"]


def _capability_scenario_membership_drift(payload):
    stress = _row(payload, "scenarios", "print_array_stress_384x10_v1")
    stress["capability_ids"].remove("sil.hardware_isolation.host")


def _stress_in_standard(payload):
    stress = _row(payload, "scenarios", "print_array_stress_384x10_v1")
    standard = _row(payload, "suites", "standard")
    stress["suite_ids"].append("standard")
    standard["scenario_ids"].append(stress["id"])


def _regression_in_standard(payload):
    regression = _row(payload, "scenarios", "print_array_regression_96_v1")
    standard = _row(payload, "suites", "standard")
    regression["suite_ids"].append("standard")
    standard["scenario_ids"].append(regression["id"])


def _pi_suite_without_proof(payload):
    suite = _row(payload, "suites", "pi_primary")
    suite["requires_pi_safety_evidence"] = ["preflight"]


def _schedule_with_unknown_suite(payload):
    payload["schedules"][0]["suite_id"] = "unknown_suite"


def _secret_like_field(payload):
    payload["policy"]["password"] = "do-not-store"


def _uri_credentials(payload):
    payload["capabilities"][0]["limitations"][0] = "https://user:pass@example.test"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (_unknown_top_level, "unknown fields"),
        (_invalid_capability_status, "must be one of"),
        (_duplicate_capability, "duplicate ID"),
        (_duplicate_scenario, "duplicate ID"),
        (_duplicate_suite, "duplicate ID"),
        (_duplicate_action, "duplicate ID"),
        (_duplicate_assertion, "duplicate ID"),
        (_unreferenced_action, "unreferenced actions"),
        (_unreferenced_assertion, "unreferenced assertions"),
        (_missing_registry_scenario, "manifest/registry scenario drift"),
        (_unknown_registry_scenario, "unsupported registered scenario"),
        (_absolute_fixture_path, "portable POSIX separators"),
        (_scenario_without_assertions, "requires assertions"),
        (_scenario_with_unknown_action, "unknown actions"),
        (_scenario_with_unknown_suite, "unknown suites"),
        (_scenario_with_missing_test, "missing test function"),
        (_covered_capability_without_scenario, "requires scenarios and assertions"),
        (
            _covered_capability_without_required_assertion,
            "capability .* lacks assertion-backed scenario",
        ),
        (_capability_scenario_membership_drift, "scenario membership drifted"),
        (_stress_in_standard, "cannot join standard"),
        (_regression_in_standard, "cannot join standard"),
        (_pi_suite_without_proof, "Pi safety evidence is inconsistent"),
        (_schedule_with_unknown_suite, "references unknown suite"),
        (_secret_like_field, "secret-like field"),
        (_uri_credentials, "URI credentials"),
    ],
)
def test_manifest_validator_rejects_drift_and_unsafe_claims(mutator, message):
    payload = _raw_manifest()
    mutator(payload)

    with pytest.raises(ManifestValidationError, match=message):
        validate_capability_manifest(payload)
