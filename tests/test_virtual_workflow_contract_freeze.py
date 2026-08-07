from __future__ import annotations

import inspect
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
from tools.virtual_workflows.registry import get_registered_scenario
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
