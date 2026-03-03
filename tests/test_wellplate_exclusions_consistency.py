import pytest


def test_exclude_well_string_is_removed_from_available_wells(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    wp.exclude_well("A1")
    ids = {w.well_id for w in wp.get_available_wells()}
    assert "A1" not in ids


def test_exclusion_set_normalizes_legacy_object_entries(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    a1 = wp.get_well("A1")
    wp.excluded_wells = {a1, "B1", "NOT_A_WELL"}

    wp.normalize_excluded_wells()
    assert wp.excluded_wells == {"A1", "B1"}


def test_auto_assignment_respects_excluded_wells(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    wp.exclude_well("A1")
    wp.exclude_well("A2")

    reactions = []
    for i in range(2):
        from Model import ReactionComposition

        rxn = ReactionComposition(f"R{i+1}")
        reactions.append(rxn)

    assigned = wp.assign_reactions_to_wells(reactions)
    assert set(assigned.values()).isdisjoint({"A1", "A2"})
