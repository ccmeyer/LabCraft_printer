import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Model import (
    AdditionalConditionSpec,
    CURRENT_PROFILE,
    DesignSizeLimitError,
    ExperimentModel,
)


SAMPLE_DESIGN = (
    Path(__file__).resolve().parents[1]
    / "FreeRTOS-interface"
    / "Experiments"
    / "CSV_upload_examples"
    / "sample_target_concentrations.csv"
)


def _make_model() -> ExperimentModel:
    return ExperimentModel(prof=CURRENT_PROFILE)


def test_empty_design_estimates_zero_and_never_generates_fill_only_reaction():
    model = _make_model()

    estimate = model.estimate_design_size()

    assert estimate.mode == "empty"
    assert estimate.base_reaction_count == 0
    assert estimate.total_runs == 0
    assert model.get_number_of_reactions() == 0
    with pytest.raises(DesignSizeLimitError, match="Add at least one reagent") as exc_info:
        model.generate_experiment()
    assert exc_info.value.code == "empty_design"
    assert model.get_reactions_dataframe().empty


def test_manual_estimate_includes_choice_levels_replicates_and_additional_conditions():
    model = _make_model()
    model.add_additive("Salt", [0.0, 1.0, 2.0], "mM", 10.0)
    model.add_choice_group("Template")
    model.add_choice_option("Template", "Main", [0.0, 5.0], "nM", 10.0)
    model.add_choice_option("Template", "Blank", [0.0], "nM", 10.0)
    model.set_metadata(replicates=2)
    model.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Control",
                targets={("Salt", None): 0.0},
                replicates=3,
            )
        ]
    )

    estimate = model.estimate_design_size()

    assert estimate.mode == "full_factorial"
    assert estimate.factor_level_counts == (("Salt", 3), ("Template", 2))
    assert estimate.unreduced_factorial_count == 6
    assert estimate.base_reaction_count == 6
    assert estimate.replicate_count == 2
    assert estimate.additional_condition_count == 3
    assert estimate.total_runs == 15


def test_subset_estimate_counts_gsd_rows_without_materializing_reactions():
    model = _make_model()
    model.add_additive("A", list(range(3)), "arb", 10.0)
    model.add_additive("B", list(range(4)), "arb", 10.0)
    model.add_additive("C", list(range(6)), "arb", 10.0)
    model.set_metadata(use_subset_design=True, reduction_factor=4, replicates=2)

    estimate = model.estimate_design_size()

    assert estimate.mode == "subset"
    assert estimate.factor_level_counts == (("A", 3), ("B", 4), ("C", 6))
    assert estimate.unreduced_factorial_count == 72
    assert estimate.base_reaction_count == 18
    assert estimate.replicate_count == 2
    assert estimate.total_runs == 36
    assert estimate.subset_intermediate_rows == 64


def test_sample_csv_is_estimated_from_its_103_explicit_rows_not_factorial_levels():
    design = pd.read_csv(SAMPLE_DESIGN)
    model = _make_model()
    model.set_uploaded_design_from_dataframe(design, source_path=str(SAMPLE_DESIGN))

    estimate = model.estimate_design_size()
    implied_factorial = math.prod(count for _name, count in estimate.factor_level_counts)

    assert len(design.index) == 103
    assert estimate.mode == "uploaded"
    assert estimate.unreduced_factorial_count == 103
    assert estimate.base_reaction_count == 103
    assert estimate.total_runs == 103
    assert implied_factorial > 50_000_000_000


def test_clear_uploaded_design_removes_design_bound_state_but_keeps_setup_and_paths():
    model = _make_model()
    model.set_metadata(
        name="Keep Me",
        target_reaction_volume_nL=750.0,
        final_reaction_volume_nL=1000.0,
        plate_name="shallow-384_well_plate",
        start_row=2,
        start_col=3,
    )
    model.experiment_dir_path = "C:/experiments/keep-me"
    model.experiment_file_path = "C:/experiments/keep-me/experiment_design.json"
    model.set_uploaded_design_from_dataframe(
        pd.DataFrame({"Signal (mM)": [0.0, 1.0]}), source_path="import.csv"
    )
    model.set_additional_conditions(
        [{"label": "Control", "replicates": 2, "targets": {("Signal", None): 0.0}}]
    )
    model.plans_per_option[("Signal", None)] = {"n_stocks": 1}
    model._target_preview_map[("Signal", None)] = [{"requested_final": 1.0}]
    model._stock_rows_cache = [{"factor_name": "Signal"}]
    model._fill_row_cache = {"factor_name": "Water"}
    model._reactions_df = pd.DataFrame([{"well_id": "A1"}])
    model._last_worst_nonfill_volume_nL = 10.0
    model.stock_prep_state["entries"]["signal"] = {"prep_volume_uL": 25.0}
    model.applied_imaging_calibrations["records"]["signal"] = {"run_id": "cal-1"}
    model.manual_refuel_checks["records"]["signal"] = {"status": "pass"}
    model.unsaved_changes = False

    model.clear_uploaded_design()

    assert model.metadata["name"] == "Keep Me"
    assert model.metadata["target_reaction_volume_nL"] == pytest.approx(750.0)
    assert model.metadata["final_reaction_volume_nL"] == pytest.approx(1000.0)
    assert model.metadata["plate_name"] == "shallow-384_well_plate"
    assert model.metadata["start_row"] == 2
    assert model.metadata["start_col"] == 3
    assert model.experiment_dir_path == "C:/experiments/keep-me"
    assert model.experiment_file_path == "C:/experiments/keep-me/experiment_design.json"
    assert model.factors == []
    assert model.additional_conditions == []
    assert model.has_uploaded_design() is False
    assert model._uploaded_design_source is None
    assert model._uploaded_well_ids is None
    assert model.plans_per_option == {}
    assert model.get_target_preview_map() == {}
    assert model.get_stock_table_rows() == []
    assert model.get_reactions_dataframe().empty
    assert model.get_worst_nonfill_volume_nL() is None
    assert model.stock_prep_state["entries"] == {}
    assert model.applied_imaging_calibrations["records"] == {}
    assert model.manual_refuel_checks["records"] == {}
    assert model.get_number_of_reactions() == 0
    assert model.unsaved_changes is True


def test_model_limit_accepts_10000_and_rejects_10001_before_product(monkeypatch):
    at_limit = _make_model()
    at_limit.add_additive("Level", list(range(10_000)), "arb", 10.0)
    assert at_limit.validate_design_size().total_runs == 10_000

    over_limit = _make_model()
    over_limit.add_additive("Level", list(range(10_001)), "arb", 10.0)

    def fail_product(*_args, **_kwargs):
        raise AssertionError("itertools.product must not run for an oversized design")

    monkeypatch.setattr("Model.itertools.product", fail_product)
    with pytest.raises(DesignSizeLimitError) as exc_info:
        over_limit._enumerate_reactions()
    assert exc_info.value.code == "design_too_large"
    assert exc_info.value.estimate.total_runs == 10_001


def test_large_base_space_is_rejected_even_when_base_replicates_are_zero():
    model = _make_model()
    model.add_additive("A", list(range(101)), "arb", 10.0)
    model.add_additive("B", list(range(100)), "arb", 10.0)
    model.set_metadata(replicates=0)
    model.set_additional_conditions(
        [{"label": "Only run", "replicates": 1, "targets": {("A", None): 0.0}}]
    )

    estimate = model.estimate_design_size()

    assert estimate.base_reaction_count == 10_100
    assert estimate.total_runs == 1
    with pytest.raises(DesignSizeLimitError, match="10,100 base reactions"):
        model._enumerate_reactions()


def test_get_number_of_reactions_never_falls_back_to_enumeration(monkeypatch):
    model = _make_model()
    model.add_additive("A", list(range(100)), "arb", 10.0)
    model.add_additive("B", list(range(100)), "arb", 10.0)

    monkeypatch.setattr(
        model,
        "_enumerate_reactions",
        lambda: (_ for _ in ()).throw(AssertionError("must not enumerate")),
    )

    assert model.get_number_of_reactions() == 10_000


def test_subset_source_and_intermediate_limits_are_checked_before_gsd(monkeypatch):
    calls = []

    def fake_gsd(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    monkeypatch.setitem(sys.modules, "pyDOE3", SimpleNamespace(gsd=fake_gsd))

    source_too_large = _make_model()
    source_too_large.add_additive("A", list(range(101)), "arb", 10.0)
    source_too_large.add_additive("B", list(range(100)), "arb", 10.0)
    source_too_large.set_metadata(use_subset_design=True, reduction_factor=2)
    with pytest.raises(DesignSizeLimitError) as source_exc:
        source_too_large._enumerate_reactions()
    assert source_exc.value.code == "subset_source_too_large"

    intermediate_too_large = _make_model()
    for name in ("A", "B", "C", "D"):
        intermediate_too_large.add_additive(name, [0.0, 1.0], "arb", 10.0)
    intermediate_too_large.set_metadata(use_subset_design=True, reduction_factor=11)
    with pytest.raises(DesignSizeLimitError) as intermediate_exc:
        intermediate_too_large._enumerate_reactions()
    assert intermediate_exc.value.code == "subset_intermediate_too_large"
    assert calls == []


def test_gsd_failure_is_controlled_and_never_falls_back_to_factorial(monkeypatch):
    model = _make_model()
    model.add_additive("A", [0.0, 1.0, 2.0, 3.0], "arb", 10.0)
    model.add_additive("B", [0.0, 1.0, 2.0, 3.0], "arb", 10.0)
    model.set_metadata(use_subset_design=True, reduction_factor=2)

    def fail_gsd(*_args, **_kwargs):
        raise RuntimeError("synthetic GSD failure")

    monkeypatch.setitem(sys.modules, "pyDOE3", SimpleNamespace(gsd=fail_gsd))

    with pytest.raises(DesignSizeLimitError) as exc_info:
        model._enumerate_reactions()
    assert exc_info.value.code == "subset_generation_failed"
    assert "explicit row-based CSV" in str(exc_info.value)
