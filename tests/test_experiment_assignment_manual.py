from unittest.mock import Mock

import pytest

from Model import Model


def _configure_design_for_manual(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.1)
    em.add_choice_group("Choice")
    em.add_choice_option("Choice", "Opt1", [0.0, 0.5], "mM", 10.0, starting_conc=0.0)
    em.add_choice_option("Choice", "Opt2", [0.0, 0.5], "mM", 10.0, starting_conc=0.0)
    em.set_metadata(randomize_assignments=False, start_row=0, start_col=0, replicates=2)


def _assigned_ordered_pairs(well_plate):
    pairs = []
    for well in sorted(well_plate.get_all_wells(), key=lambda w: (w.row_num, w.col)):
        rxn = well.get_assigned_reaction()
        if rxn is not None:
            pairs.append((rxn.unique_id, well.well_id))
    return pairs


def test_manual_assignment_uses_explicit_well_ids_exactly(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_for_manual(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    num = em.get_number_of_reactions()
    explicit = [f"A{i+1}" for i in range(num)]
    em._uploaded_well_ids = explicit

    Model.load_experiment_from_model(model, load_progress=False)

    pairs = _assigned_ordered_pairs(model.well_plate)
    by_reaction_idx = sorted(pairs, key=lambda p: int(p[0][1:]))
    assert [wid for _, wid in by_reaction_idx] == explicit


def test_manual_assignment_overrides_printable_well_selection(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_for_manual(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    num = em.get_number_of_reactions()
    explicit = [f"B{i+1}" for i in range(num)]
    em._uploaded_well_ids = explicit
    em.set_well_selection(["A1"])

    Model.load_experiment_from_model(model, load_progress=False)

    pairs = _assigned_ordered_pairs(model.well_plate)
    by_reaction_idx = sorted(pairs, key=lambda p: int(p[0][1:]))
    assert [wid for _, wid in by_reaction_idx] == explicit


def test_manual_assignment_accepts_high_density_wells_on_384_plate(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_for_manual(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    explicit = [
        "G16", "P24", "A1", "B2", "C3", "D4", "E5", "F6",
        "H7", "I8", "J9", "K10", "L11", "M12", "N13", "O14",
    ]
    assert len(explicit) == em.get_number_of_reactions()
    em._uploaded_well_ids = explicit

    Model.load_experiment_from_model(model, load_progress=False)

    pairs = _assigned_ordered_pairs(model.well_plate)
    by_reaction_idx = sorted(pairs, key=lambda p: int(p[0][1:]))
    assert [wid for _, wid in by_reaction_idx] == explicit


def test_manual_assignment_length_mismatch_raises(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_for_manual(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em._uploaded_well_ids = ["A1"]  # intentionally wrong length

    with pytest.raises(ValueError, match="must match the number of reactions"):
        Model.load_experiment_from_model(model, load_progress=False)


def test_manual_assignment_sets_replicates_runtime_to_zero(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design_for_manual(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()

    n = em.get_number_of_reactions()
    em._uploaded_well_ids = [f"B{i+1}" for i in range(n)]
    original = em.metadata.get("replicates")

    Model.load_experiment_from_model(model, load_progress=False)

    assert em.metadata["replicates"] == 0
    assert em.metadata["_original_replicates"] == original


def test_manual_assignment_rejects_invalid_and_excluded_wells(experiment_model_factory):
    model_invalid = experiment_model_factory()
    em_invalid = model_invalid.experiment_model
    _configure_design_for_manual(em_invalid)
    assert em_invalid.optimize_stock_solutions()["best"]
    em_invalid.generate_experiment()
    n = em_invalid.get_number_of_reactions()
    invalid_ids = [f"A{i+1}" for i in range(n)]
    invalid_ids[0] = "G16"
    em_invalid._uploaded_well_ids = invalid_ids
    model_invalid.clear_experiment = Mock()
    with pytest.raises(ValueError) as excinfo_invalid:
        Model.load_experiment_from_model(model_invalid, plate_name="96well-8x12", load_progress=False)
    assert model_invalid.clear_experiment.call_count == 0
    assert "Explicit well assignments are invalid" in str(excinfo_invalid.value)
    assert "G16" in str(excinfo_invalid.value)
    assert "96well-8x12" in str(excinfo_invalid.value)

    model_excluded = experiment_model_factory()
    em_excluded = model_excluded.experiment_model
    _configure_design_for_manual(em_excluded)
    assert em_excluded.optimize_stock_solutions()["best"]
    em_excluded.generate_experiment()
    n2 = em_excluded.get_number_of_reactions()
    excluded_ids = [f"C{i+1}" for i in range(n2)]
    em_excluded._uploaded_well_ids = excluded_ids
    model_excluded.well_plate.excluded_wells.add(excluded_ids[0])
    model_excluded.clear_experiment = Mock()
    with pytest.raises(ValueError) as excinfo_excluded:
        Model.load_experiment_from_model(model_excluded, load_progress=False)
    assert model_excluded.clear_experiment.call_count == 0
    assert "Excluded wells" in str(excinfo_excluded.value)
    assert excluded_ids[0] in str(excinfo_excluded.value)
