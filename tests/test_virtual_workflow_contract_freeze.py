from __future__ import annotations

import inspect
import ast
from dataclasses import fields
from pathlib import Path

from tools.run_virtual_workflow import _comparison_exit_code, _parser
from tools.virtual_workflows.compare import (
    BASELINE_SCHEMA_NAME,
    COMPARISON_SCHEMA_NAME,
    COMPARISON_SCHEMA_VERSION,
    POLICY_VERSION,
    REPORT_SET_SCHEMA_NAME,
    load_baseline_summary,
)
from tools.virtual_workflows.report import (
    METRIC_GROUPS,
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    REQUIRED_TOP_LEVEL_FIELDS,
)
from tools.virtual_workflows.suite_runner import (
    AGGREGATE_SCHEMA_NAME,
    AGGREGATE_SCHEMA_VERSION,
)
from tools.virtual_workflows.pi_sil import (
    PI_ARTIFACT_MANIFEST_SCHEMA,
    PI_SIL_SCHEMA_VERSION,
    PI_SUITE_ARTIFACT_MANIFEST_VERSION,
)
from tools.virtual_workflows.coverage import (
    COVERAGE_SCHEMA_NAME,
    COVERAGE_SCHEMA_VERSION,
)
from tools.virtual_workflows.exploration import (
    EXPLORATION_PLAN_SCHEMA_NAME,
    EXPLORATION_SCHEMA_VERSION,
)
from tools.virtual_workflows.exploration_runner import (
    EXPLORATION_AGGREGATE_SCHEMA_NAME,
    EXPLORATION_AGGREGATE_SCHEMA_VERSION,
)
from tools.virtual_workflows.registry import get_registered_scenario
from tools.virtual_workflows.joined_interaction_cases import (
    JOINED_INTERACTION_CASE,
    JOINED_INTERACTION_CASE_ID,
    joined_fixture_sha256,
)
from tools.virtual_workflows.journeys import (
    AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS,
    AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS,
    EDITOR_REVISION_REQUIRED_ASSERTIONS,
    EDITOR_REVISION_REQUIRED_UI_ACTIONS,
    SOFT_STOP_REQUIRED_ASSERTIONS,
    SOFT_STOP_REQUIRED_UI_ACTIONS,
    REGRESSION_REQUIRED_ASSERTIONS,
    REGRESSION_WORKLOAD_ID,
    STRESS_REQUIRED_ASSERTIONS,
    STRESS_REQUIRED_SCREENSHOTS,
    get_journey_definition,
    JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS,
    JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS,
    RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS,
    RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS,
    run_joined_calibrated_checkpoint,
)
from tools.virtual_workflows.scenarios import (
    AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
    MULTI_STOCK_WORKLOAD_ID,
    SCENARIO_COMPLETION_COUNTS,
    SCENARIO_FIXTURES,
    SCENARIO_NAME,
    SCENARIO_VERSION,
    STRESS_WORKLOAD_ID,
    WORKLOAD_ID,
    VirtualPrintArrayScenarioConfig,
    load_virtual_print_array_fixture,
    run_virtual_print_array_scenario,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = REPO_ROOT / "tests" / "performance" / "baselines"


def test_milestone_11_joined_contract_is_frozen_with_complete_registration():
    from tools.virtual_workflows.registry import registered_scenario_ids

    assert JOINED_INTERACTION_CASE.sha256() == (
        "77ae121969768739a057a415ea12b076e6404b48332f2ab44d997e99431d0874"
    )
    assert JOINED_INTERACTION_CASE.count_oracle_sha256() == (
        "468d78216fd52f326898c5b5625f6ae591995c642118a72ddb1cdf0cb5790814"
    )
    assert joined_fixture_sha256() == (
            "579d7cb186347dfc55fbbdcd58c571cb3ce9feff61260436099a928f9a887ef1"
    )
    assert JOINED_INTERACTION_CASE_ID in registered_scenario_ids()
    registry = get_registered_scenario(JOINED_INTERACTION_CASE_ID)
    journey = get_journey_definition(JOINED_INTERACTION_CASE_ID)
    assert registry.runner_family == "composed_journey"
    assert registry.expected_completion_count == 24
    assert journey.required_assertion_ids == RANDOMIZED_CALIBRATION_REQUIRED_ASSERTIONS
    assert journey.required_screenshots == RANDOMIZED_CALIBRATION_REQUIRED_SCREENSHOTS


def test_milestone_11_complete_journey_uses_precalibrated_stock_passes():
    from tools.virtual_workflows.registry import registered_scenario_ids

    source = inspect.getsource(run_joined_calibrated_checkpoint)

    assert JOINED_CALIBRATED_CHECKPOINT_REQUIRED_ASSERTIONS == (
        "sil.host_hardware_disabled",
        "ui.real_app_constructed",
        "experiment.editor_create_finalize",
        "experiment.randomized_joined_design_exact",
        "execution.calibrated_zero_progress_exact",
        "ui.fresh_application_session_constructed",
        "execution.first_session_teardown_clean",
        "execution.authoritative_reload_valid",
        "execution.authoritative_runtime_rehydrated",
        "execution.clean_session_rotation_exact",
        "execution.remaining_calibrations_exact",
        "execution.completed_terminal_reload_exact",
        "execution.randomized_calibration_terminal_exact",
    )
    assert "array.start_via_ui" in JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS
    assert "experiment.activate_authoritative_via_ui" in (
        JOINED_CALIBRATED_CHECKPOINT_REQUIRED_UI_ACTIONS
    )
    assert "run_stock_passes" not in source
    assert "run_precalibrated_stock_passes" in source
    assert "manual_refuel" not in source
    assert "run_authoritative_reload_resume_boundary" not in source
    assert "run_clean_authoritative_session_rotation_boundary" in source
    assert JOINED_INTERACTION_CASE_ID in registered_scenario_ids()


def test_clean_session_rotation_phase_is_lifecycle_neutral():
    from tools.virtual_workflows.journey_phases import (
        run_clean_authoritative_session_rotation_boundary,
    )

    source = inspect.getsource(run_clean_authoritative_session_rotation_boundary)

    assert "run_soft_stop_boundary" not in source
    assert "resume_soft_stopped_array" not in source
    assert "run_stock_passes" not in source
    assert 'expected_eligibility_status="ready_to_start"' in source
    assert 'expected_array_state="idle"' in source


def test_authoritative_evidence_readers_are_centralized_and_read_only():
    source = (
        REPO_ROOT / "tools" / "virtual_workflows" / "authoritative_evidence.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert {
        "capture_authoritative_bundle",
        "read_csv_rows",
        "read_audit_rows",
        "runtime_assignments",
        "snapshot_directory",
    } <= functions
    for forbidden in (
        "load_authoritative_execution_runtime",
        "save_execution_",
        "write_report_atomic",
        "run_action(",
        "QTest",
        "os.replace",
    ):
        assert forbidden not in source

    assertions = (
        REPO_ROOT / "tools" / "virtual_workflows" / "assertions.py"
    ).read_text(encoding="utf-8")
    editor = (
        REPO_ROOT / "tools" / "virtual_workflows" / "editor_scenarios.py"
    ).read_text(encoding="utf-8")
    scenarios = (
        REPO_ROOT / "tools" / "virtual_workflows" / "scenarios.py"
    ).read_text(encoding="utf-8")
    for removed in (
        "def _editor_csv_rows",
        "def _editor_file_sha256",
        "def _editor_audit_rows",
        "def _editor_runtime_assignments",
    ):
        assert removed not in assertions
    for removed in (
        "def _csv_rows",
        "def _file_sha256",
        "def _audit_rows",
        "def _runtime_assignments",
        "def _directory_file_snapshot",
    ):
        assert removed not in editor
    assert "def _file_inventory" not in scenarios
    assert "def _read_audit_rows" not in scenarios


def test_multi_stock_v4_composed_contract_is_frozen():
    fixture = load_virtual_print_array_fixture(
        scenario_id=MULTI_STOCK_WORKLOAD_ID
    )
    definition = get_registered_scenario(MULTI_STOCK_WORKLOAD_ID)
    assert definition.runner_family == "composed_journey"
    assert fixture["schema_version"] == 4
    assert [stock["concentration"] for stock in fixture["stocks"]] == [3.0, 1.5]
    assert [stock["droplet_volume_nL"] for stock in fixture["stocks"]] == [
        9.0,
        18.0,
    ]
    assert [
        stock["printer_head"]["print_pulse_width_us"]
        for stock in fixture["stocks"]
    ] == [1300, 1800]


def test_96_well_regression_uses_the_shared_composed_one_stock_contract():
    from tools.virtual_workflows import journeys

    registry_definition = get_registered_scenario(REGRESSION_WORKLOAD_ID)
    regression = get_journey_definition(REGRESSION_WORKLOAD_ID)
    smoke = get_journey_definition(journeys.SMOKE_WORKLOAD_ID)

    assert registry_definition.runner_family == "composed_journey"
    assert registry_definition.supports_injected_stall is True
    assert registry_definition.supports_pi_evidence is True
    assert registry_definition.supports_report_sets is True
    assert regression.body is smoke.body
    assert regression.payload_builder is smoke.payload_builder
    assert regression.required_action_ids == smoke.required_action_ids
    assert regression.required_ui_action_ids == smoke.required_ui_action_ids
    assert regression.midpoint_completion_count == 48
    assert regression.required_assertion_ids == REGRESSION_REQUIRED_ASSERTIONS
    assert regression.required_screenshots == {
        "editor_opened",
        "generated",
        "ready",
        "printing",
        "mid_array",
        "completed",
    }


def test_384x10_stress_uses_shared_multi_stock_composition():
    from tools.virtual_workflows import journeys

    registry = get_registered_scenario(STRESS_WORKLOAD_ID)
    stress = get_journey_definition(STRESS_WORKLOAD_ID)
    multi = get_journey_definition(MULTI_STOCK_WORKLOAD_ID)

    assert registry.runner_family == "composed_journey"
    assert stress.body is multi.body
    assert stress.payload_builder is multi.payload_builder
    assert stress.artifact_assertion is multi.artifact_assertion
    assert stress.required_ui_action_ids == multi.required_ui_action_ids
    assert stress.required_assertion_ids == STRESS_REQUIRED_ASSERTIONS
    assert stress.required_screenshots == STRESS_REQUIRED_SCREENSHOTS
    assert stress.midpoint_completion_count == 1920
    assert journeys.STRESS_FIXED_CALIBRATION_PULSE_WIDTH_US == 1355


def test_prepared_editor_refinalize_composed_contract_is_frozen():
    definition = get_registered_scenario(
        "experiment_editor_prestart_rename_refinalize_v1"
    )
    assert definition.runner_family == "composed_journey"
    assert EDITOR_REVISION_REQUIRED_ASSERTIONS == (
        "sil.host_hardware_disabled",
        "ui.real_app_constructed",
        "experiment.prepared_rename_refinalize",
        "experiment.prepared_design_refinalize",
        "experiment.renamed_artifacts_unique",
        "experiment.refinalized_bundle_valid",
        "experiment.prepared_reload_ready",
        "experiment.runtime_assignments_match",
        "experiment.key_files_consistent",
        "artifacts.required_present",
    )
    assert "experiment.load_authoritative_via_ui" in (
        EDITOR_REVISION_REQUIRED_UI_ACTIONS
    )


def test_soft_stop_composed_contract_is_frozen():
    definition = get_registered_scenario("print_array_soft_stop_resume_24_v1")

    assert definition.runner_family == "composed_journey"
    assert SOFT_STOP_REQUIRED_ASSERTIONS == (
        "sil.host_hardware_disabled",
        "ui.real_app_constructed",
        "execution.soft_stop_requested",
        "execution.soft_stop_boundary_valid",
        "execution.stopped_boundary_quiescent",
        "execution.resume_exactly_once",
        "execution.expected_completions",
        "execution.intent_durability_exact",
        "execution.terminal_bundle_valid",
        "artifacts.required_present",
    )
    assert {"array.request_soft_stop_via_ui", "array.resume_via_ui"} <= (
        SOFT_STOP_REQUIRED_UI_ACTIONS
    )


def test_authoritative_reload_composed_contract_is_frozen():
    definition = get_registered_scenario("authoritative_reload_resume_24_v1")
    assert definition.runner_family == "composed_journey"
    assert AUTHORITATIVE_RELOAD_REQUIRED_ASSERTIONS == (
        "sil.host_hardware_disabled",
        "ui.real_app_constructed",
        "ui.fresh_application_session_constructed",
        "execution.first_session_paused",
        "execution.first_session_teardown_clean",
        "execution.authoritative_reload_valid",
        "execution.authoritative_runtime_rehydrated",
        "execution.reload_resume_exactly_once",
        "execution.expected_completions",
        "execution.intent_durability_exact",
        "execution.terminal_bundle_valid",
        "artifacts.required_present",
    )
    assert {
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "array.request_soft_stop_via_ui",
        "array.resume_via_ui",
    } <= AUTHORITATIVE_RELOAD_REQUIRED_UI_ACTIONS

    action_source = (
        REPO_ROOT / "tools" / "virtual_workflows" / "actions.py"
    ).read_text(encoding="utf-8")
    driver_source = (
        REPO_ROOT / "tools" / "virtual_workflows" / "page_drivers.py"
    ).read_text(encoding="utf-8")
    action_function = ast.get_source_segment(
        action_source,
        next(
            node
            for node in ast.parse(action_source).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "drive_authoritative_reload_via_editor"
        ),
    )
    assert "QTest" not in action_function
    assert "load_authoritative_execution" in action_function
    assert "def load_authoritative_execution" in driver_source
    assert "def inspect_completed_execution" in driver_source
    assert "experiment.inspect_completed_via_ui" in driver_source


def test_legacy_cli_surface_remains_additively_compatible():
    parser = _parser()
    args = parser.parse_args([])
    scenario_action = next(
        action for action in parser._actions if action.dest == "scenario"
    )

    assert {WORKLOAD_ID, STRESS_WORKLOAD_ID} <= set(scenario_action.choices)
    assert args.scenario == WORKLOAD_ID
    assert args.seed == 1
    assert args.output_root == (
        REPO_ROOT / "verification_reports" / "virtual_workflows"
    )
    assert args.speed_multiplier == 1.0
    assert args.timeout_seconds == 180.0
    assert args.visible is False
    assert args.qt_platform == "offscreen"
    assert args.target_pi is False
    assert args.pi_preflight is None
    assert args.pi_hardware_proof is None
    assert args.inject_ui_stall_ms == 0
    assert args.inject_after_completion == 48
    assert args.warmup_runs == 0
    assert args.measured_runs == 1
    assert args.host_label is None
    assert args.emit_report_set is False
    assert args.accept_baseline is None
    assert args.replace_accepted_baseline is False
    assert args.threshold_maturity == "candidate"
    assert args.compare is None
    assert args.suite is None
    assert args.capability is None
    assert args.matrix is None
    assert args.case is None
    assert args.exploration is None
    assert args.sequence is None
    assert args.list_section is None
    assert args.recommend_changed is False
    assert args.changed_path == []
    assert args.dry_run is False

    assert parser.parse_args(["--scenario", WORKLOAD_ID]).scenario == WORKLOAD_ID
    assert (
        parser.parse_args(["--scenario", STRESS_WORKLOAD_ID]).scenario
        == STRESS_WORKLOAD_ID
    )

    help_text = parser.format_help()
    for option in (
        "--scenario",
        "--seed",
        "--output-root",
        "--speed-multiplier",
        "--timeout-seconds",
        "--visible",
        "--qt-platform",
        "--target-pi",
        "--pi-preflight",
        "--pi-hardware-proof",
        "--inject-ui-stall-ms",
        "--inject-after-completion",
        "--warmup-runs",
        "--measured-runs",
        "--host-label",
        "--emit-report-set",
        "--accept-baseline",
        "--replace-accepted-baseline",
        "--threshold-maturity",
        "--compare",
        "--suite",
        "--capability",
        "--matrix",
        "--case",
        "--exploration",
        "--sequence",
        "--list",
        "--recommend-changed",
        "--changed-path",
        "--dry-run",
    ):
        assert option in help_text

    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "pass",
                "overall_status": "pass",
            }
        }
    ) == 0
    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "pass",
                "overall_status": "warning",
            }
        }
    ) == 0
    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "fail",
                "overall_status": "fail",
            }
        }
    ) == 2
    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "pass",
                "overall_status": "incomplete",
            }
        }
    ) == 3
    assert _comparison_exit_code(
        {
            "classification": {
                "functional_status": "pass",
                "overall_status": "fail",
            }
        }
    ) == 4


def test_host_selection_aggregate_schema_is_frozen():
    assert AGGREGATE_SCHEMA_NAME == "labcraft.virtual_workflow_aggregate"
    assert AGGREGATE_SCHEMA_VERSION == 1
    assert PI_ARTIFACT_MANIFEST_SCHEMA == "labcraft.pi_sil_artifact_bundle"
    assert PI_SIL_SCHEMA_VERSION == 1
    assert PI_SUITE_ARTIFACT_MANIFEST_VERSION == 2
    assert COVERAGE_SCHEMA_NAME == "labcraft.sil_capability_evaluation"
    assert COVERAGE_SCHEMA_VERSION == 1
    assert EXPLORATION_PLAN_SCHEMA_NAME == (
        "labcraft.virtual_workflow_exploration_plan"
    )
    assert EXPLORATION_SCHEMA_VERSION == 1
    assert EXPLORATION_AGGREGATE_SCHEMA_NAME == (
        "labcraft.virtual_workflow_exploration_aggregate"
    )
    assert EXPLORATION_AGGREGATE_SCHEMA_VERSION == 1


def test_legacy_scenario_api_remains_additively_compatible():
    defaults = {
        field.name: field.default
        for field in fields(VirtualPrintArrayScenarioConfig)
    }
    required_defaults = {
        "fixture_path": None,
        "scenario_id": WORKLOAD_ID,
        "visible": False,
        "speed_multiplier": 1.0,
        "timeout_seconds": 180.0,
        "inject_ui_stall_ms": 0,
        "inject_after_completion": 48,
        "run_id": None,
        "pi_preflight_path": None,
        "pi_hardware_proof_path": None,
    }

    assert required_defaults.items() <= defaults.items()
    assert defaults["output_root"] == (
        REPO_ROOT / "verification_reports" / "virtual_workflows"
    )
    assert {WORKLOAD_ID, STRESS_WORKLOAD_ID} <= set(SCENARIO_FIXTURES)
    assert SCENARIO_COMPLETION_COUNTS[WORKLOAD_ID] == 96
    assert SCENARIO_COMPLETION_COUNTS[STRESS_WORKLOAD_ID] == 3840
    assert (
        SCENARIO_COMPLETION_COUNTS[
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID
        ]
        == 24
    )
    assert (
        SCENARIO_FIXTURES[
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID
        ].name
        == "authoritative_reload_resume_24_v1.json"
    )
    assert SCENARIO_COMPLETION_COUNTS[MULTI_STOCK_WORKLOAD_ID] == 48
    assert (
        SCENARIO_FIXTURES[MULTI_STOCK_WORKLOAD_ID].name
        == "print_array_multi_stock_24x2_v1.json"
    )
    assert SCENARIO_NAME == "virtual_print_array"
    assert SCENARIO_VERSION == "1"

    run_signature = inspect.signature(run_virtual_print_array_scenario)
    assert "config" in run_signature.parameters
    assert run_signature.parameters["config"].default is inspect.Parameter.empty
    fixture_signature = inspect.signature(load_virtual_print_array_fixture)
    assert "path" in fixture_signature.parameters
    assert "scenario_id" in fixture_signature.parameters

    assert VirtualPrintArrayScenarioConfig(
        scenario_id=WORKLOAD_ID
    ).scenario_id == WORKLOAD_ID
    assert VirtualPrintArrayScenarioConfig(
        scenario_id=STRESS_WORKLOAD_ID
    ).scenario_id == STRESS_WORKLOAD_ID
    assert load_virtual_print_array_fixture(
        scenario_id=WORKLOAD_ID
    )["fixture_id"] == WORKLOAD_ID
    assert load_virtual_print_array_fixture(
        scenario_id=STRESS_WORKLOAD_ID
    )["fixture_id"] == STRESS_WORKLOAD_ID


def test_report_and_comparison_identity_remains_compatible():
    assert REPORT_SCHEMA_NAME == "labcraft.virtual_workflow_report"
    assert REPORT_SCHEMA_VERSION == 1
    assert {
        "schema_name",
        "schema_version",
        "run",
        "source",
        "environment",
        "safety",
        "workload",
        "metrics",
        "artifacts",
        "classification",
        "limitations",
    } <= REQUIRED_TOP_LEVEL_FIELDS
    assert {
        "responsiveness",
        "workflow",
        "queue",
        "persistence",
        "resources",
    } <= METRIC_GROUPS
    assert REPORT_SET_SCHEMA_NAME == "labcraft.virtual_workflow_report_set"
    assert BASELINE_SCHEMA_NAME == "labcraft.virtual_workflow_baseline"
    assert COMPARISON_SCHEMA_NAME == "labcraft.virtual_workflow_comparison"
    assert COMPARISON_SCHEMA_VERSION == 1
    assert POLICY_VERSION == "virtual_workflow_policy_v1"

    pi_baseline = load_baseline_summary(
        BASELINE_ROOT / "virtual_print_array_96_v1_pi5_sil_primary_v1.json"
    )
    windows_baseline = load_baseline_summary(
        BASELINE_ROOT / "virtual_print_array_96_v1_windows_sil_primary_v1.json"
    )

    for baseline in (pi_baseline, windows_baseline):
        assert baseline["schema_name"] == BASELINE_SCHEMA_NAME
        assert baseline["schema_version"] == 1
        assert baseline["policy"]["policy_version"] == POLICY_VERSION
        assert (
            baseline["compatibility"]["workload"]["workload_id"]
            == WORKLOAD_ID
        )
        assert (
            baseline["compatibility"]["workload"]["expected_completion_count"]
            == 96
        )

    assert {
        pi_baseline["compatibility"]["run_mode"],
        windows_baseline["compatibility"]["run_mode"],
    } == {
        "offscreen_pi_sil",
        "offscreen_windows_sil",
    }
