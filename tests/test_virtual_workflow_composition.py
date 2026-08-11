from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import inspect

import pytest

from tools.virtual_workflows.actions import InteractionSurface
from tools.virtual_workflows.composition import (
    JourneyDefinition,
    JourneyRuntime,
    SemanticStep,
    normalized_steps,
    replay_command,
)


class _Harness:
    def __init__(self):
        self.context = SimpleNamespace()
        self.calls = []
        self.assertion_results = []

    def run_action(
        self,
        action_id,
        operation,
        *,
        surface,
        precondition=None,
        allowed_dialogs=(),
    ):
        evidence = operation()
        row = {
            "action_id": action_id,
            "surface": surface,
            "evidence": evidence,
            "precondition": precondition,
            "allowed_dialogs": allowed_dialogs,
        }
        self.calls.append(row)
        return row

    def add_assertion_result(self, result):
        self.assertion_results.append(dict(result))


def _definition(**overrides):
    values = {
        "registry_id": "virtual_print_array_24_v1",
        "scenario_name": "virtual_print_array",
        "scenario_version": "1",
        "workload_id": "virtual_print_array_24_v1",
        "required_action_ids": frozenset(
            {"app.launch_simulated", "scenario.teardown"}
        ),
        "required_ui_action_ids": frozenset(),
        "required_assertion_ids": ("sil.host_hardware_disabled",),
        "required_screenshots": frozenset(),
        "fixture_loader": lambda: ({}, Path("fixture.json")),
        "body": lambda runtime: None,
        "artifact_assertion": lambda runtime, teardown: {},
        "payload_builder": lambda runtime, teardown: {},
        "summary_builder": lambda report, runtime: "summary",
    }
    values.update(overrides)
    return JourneyDefinition(**values)


def test_semantic_steps_validate_and_normalize_surface_contract():
    step = SemanticStep(
        "machine.connect_via_ui",
        InteractionSurface.UI,
        lambda runtime: {"connected": True},
    )

    assert normalized_steps((step,)) == [
        {
            "action_id": "machine.connect_via_ui",
            "interaction_surface": "ui",
        }
    ]
    with pytest.raises(ValueError, match="unknown semantic action"):
        SemanticStep("unknown.action", InteractionSurface.UI, lambda runtime: {})
    with pytest.raises(ValueError, match="InteractionSurface"):
        SemanticStep("machine.connect_via_ui", "ui", lambda runtime: {})


def test_definition_rejects_duplicate_assertions_and_non_ui_membership():
    with pytest.raises(ValueError, match="assertion IDs must be unique"):
        _definition(
            required_assertion_ids=(
                "sil.host_hardware_disabled",
                "sil.host_hardware_disabled",
            )
        )
    with pytest.raises(ValueError, match="required UI actions"):
        _definition(
            required_ui_action_ids=frozenset({"machine.connect_via_ui"})
        )


def test_definition_validates_optional_evidence_profile_and_midpoint():
    with pytest.raises(ValueError, match="evidence profile"):
        _definition(evidence_profile_factory="not-callable")
    with pytest.raises(ValueError, match="midpoint"):
        _definition(midpoint_completion_count=0)

    profile_factory = lambda runtime: runtime
    definition = _definition(
        evidence_profile_factory=profile_factory,
        midpoint_completion_count=48,
    )
    assert definition.evidence_profile_factory is profile_factory
    assert definition.midpoint_completion_count == 48


def test_replay_command_retains_requested_stall_controls(tmp_path):
    config = SimpleNamespace(
        output_root=tmp_path,
        seed=7,
        speed_multiplier=1000.0,
        timeout_seconds=60.0,
        visible=False,
        inject_ui_stall_ms=300,
        inject_after_completion=48,
    )
    command = replay_command(SimpleNamespace(config=config), "scenario")

    assert command[-4:] == [
        "--inject-ui-stall-ms",
        "300",
        "--inject-after-completion",
        "48",
    ]


def test_replay_command_can_retain_a_typed_matrix_case_selector(tmp_path):
    config = SimpleNamespace(
        output_root=tmp_path,
        seed=1,
        speed_multiplier=20.0,
        timeout_seconds=120.0,
        visible=True,
        inject_ui_stall_ms=0,
        inject_after_completion=48,
    )

    command = replay_command(
        SimpleNamespace(config=config),
        "mixed_mode_calibration_v1",
        selector_args=(
            "--matrix",
            "mixed_mode_calibration_v1",
            "--case",
            "mixed_ab_baseline_pass",
        ),
    )

    assert "--scenario" not in command
    assert command[2:6] == [
        "--matrix",
        "mixed_mode_calibration_v1",
        "--case",
        "mixed_ab_baseline_pass",
    ]
    assert command[-1] == "--visible"


def test_runtime_executes_steps_through_harness_and_records_assertions(tmp_path):
    harness = _Harness()
    runtime = JourneyRuntime(
        definition=_definition(
            required_action_ids=frozenset(
                {
                    "app.launch_simulated",
                    "machine.connect_via_ui",
                    "scenario.teardown",
                }
            )
        ),
        harness=harness,
        fixture={},
        fixture_path=tmp_path / "fixture.json",
    )
    step = SemanticStep(
        "machine.connect_via_ui",
        InteractionSurface.UI,
        lambda current: {"same_runtime": current is runtime},
    )

    results = runtime.run_steps((step,))
    runtime.add_assertion(
        {
            "assertion_id": "sil.host_hardware_disabled",
            "decision": "pass",
        }
    )

    assert results[0]["evidence"] == {"same_runtime": True}
    assert harness.calls[0]["surface"] is InteractionSurface.UI
    assert harness.assertion_results[0]["decision"] == "pass"


def test_runtime_restores_in_reverse_order_once_and_retains_snapshots(tmp_path):
    events = []

    class Restorable:
        def __init__(self, name):
            self.name = name

        def restore(self):
            events.append(self.name)

        def snapshot(self):
            return {"name": self.name, "restored": True}

    runtime = JourneyRuntime(
        definition=_definition(),
        harness=_Harness(),
        fixture={},
        fixture_path=tmp_path / "fixture.json",
    )
    runtime.register_restorable("first", Restorable("first"))
    runtime.register_restorable("second", Restorable("second"))

    runtime.restore_all()
    runtime.restore_all()

    assert events == ["second", "first"]
    assert runtime.observations["first_snapshot"] == {
        "name": "first",
        "restored": True,
    }
    assert runtime.observations["second_snapshot"]["restored"] is True


def test_required_failed_assertion_fails_closed(tmp_path):
    runtime = JourneyRuntime(
        definition=_definition(),
        harness=_Harness(),
        fixture={},
        fixture_path=tmp_path / "fixture.json",
    )

    with pytest.raises(RuntimeError, match="required assertion"):
        runtime.add_assertion(
            {
                "assertion_id": "sil.host_hardware_disabled",
                "decision": "fail",
                "evidence": {"hardware": "unexpected"},
            }
        )


def test_named_journeys_meet_concision_and_generic_dispatch_gates():
    from tools.virtual_workflows import journeys, registry

    for runner in (
        journeys.run_composed_journey,
        journeys.run_virtual_print_array_24_journey,
        journeys.run_editor_create_finalize_journey,
        journeys.run_multi_stock_24x2_journey,
        journeys.run_soft_stop_resume_24_journey,
    ):
        source = inspect.getsource(runner)
        assert len(
            [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        ) <= 80

    module = ast.parse(Path(journeys.__file__).read_text(encoding="utf-8"))
    lengths = {
        node.name: node.end_lineno - node.lineno + 1
        for node in module.body
        if isinstance(node, ast.FunctionDef)
    }
    assert lengths["_smoke_body"] <= 120
    assert lengths["_editor_body"] <= 120
    assert lengths["_experiment_design_body"] <= 120
    assert lengths["_editor_revision_body"] <= 120
    assert lengths["_multi_body"] <= 120
    assert lengths["_soft_stop_body"] <= 120
    assert lengths["_soft_stop_payload"] <= 90
    assert lengths["_authoritative_reload_body"] <= 140
    assert lengths["_authoritative_reload_payload"] <= 100
    dispatch_source = inspect.getsource(registry.run_registered_scenario)
    assert "definition.workload_id == EDITOR_WORKLOAD_ID" not in dispatch_source
    assert "definition.workload_id == MULTI_STOCK_WORKLOAD_ID" not in dispatch_source
    assert "definition.workload_id == RENAME_WORKLOAD_ID" not in dispatch_source


def test_matrix_journey_dispatch_uses_registered_family_and_fails_closed(
    tmp_path, monkeypatch
):
    from tools.virtual_workflows import journeys, matrices

    case = SimpleNamespace(
        case_id="control",
        normalized=lambda: {"case_id": "control"},
    )
    definition = matrices.MatrixDefinition(
        matrix_id="synthetic_dispatch_v1",
        base_scenario_id=journeys.MIXED_MODE_WORKLOAD_ID,
        journey_family="synthetic_dispatch",
        platform="windows_sil",
        execution="manual_on_demand",
        cases=(case,),
        catalog_metadata={},
        fixture_builder=lambda _case: ({}, Path(__file__)),
    )
    monkeypatch.setattr(
        matrices,
        "MATRIX_REGISTRY",
        matrices.MatrixRegistry((definition,)),
    )
    calls = []

    def run_synthetic(config, *, matrix_id, case_id):
        calls.append((config.scenario_id, matrix_id, case_id))
        return {"classification": {"status": "pass"}}

    monkeypatch.setitem(
        journeys._MATRIX_JOURNEY_RUNNERS,
        "synthetic_dispatch",
        run_synthetic,
    )
    config = journeys.JourneyRunConfig(
        scenario_id=journeys.MIXED_MODE_WORKLOAD_ID,
        output_root=tmp_path,
    )

    assert journeys.run_matrix_case(
        config,
        matrix_id=definition.matrix_id,
        case_id="control",
    )["classification"]["status"] == "pass"
    assert calls == [
        (
            journeys.MIXED_MODE_WORKLOAD_ID,
            definition.matrix_id,
            "control",
        )
    ]

    wrong_base = journeys.JourneyRunConfig(
        scenario_id=journeys.SMOKE_WORKLOAD_ID,
        output_root=tmp_path,
    )
    with pytest.raises(ValueError, match="requires composed base"):
        journeys.run_matrix_case(
            wrong_base,
            matrix_id=definition.matrix_id,
            case_id="control",
        )

    unsupported = matrices.MatrixDefinition(
        matrix_id="unsupported_dispatch_v1",
        base_scenario_id=journeys.MIXED_MODE_WORKLOAD_ID,
        journey_family="not_registered",
        platform="windows_sil",
        execution="manual_on_demand",
        cases=(case,),
        catalog_metadata={},
        fixture_builder=lambda _case: ({}, Path(__file__)),
    )
    monkeypatch.setattr(
        matrices,
        "MATRIX_REGISTRY",
        matrices.MatrixRegistry((unsupported,)),
    )
    with pytest.raises(ValueError, match="unsupported matrix journey family"):
        journeys.run_matrix_case(
            config,
            matrix_id=unsupported.matrix_id,
            case_id="control",
        )
