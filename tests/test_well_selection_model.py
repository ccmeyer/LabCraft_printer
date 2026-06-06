import pytest

from hardware.profile import CURRENT_PROFILE
from Model import ExperimentModel, ReactionComposition, WellPlate


def _high_density_plate(tmp_path):
    plate_data = [{
        "name": "1536-32x48",
        "rows": 32,
        "columns": 48,
        "spacing": 4.5,
        "default": True,
        "calibrations": {},
    }]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")
    return WellPlate(plate_data, str(plates_tmp))


def _reactions(count):
    return [ReactionComposition(f"R{i + 1}") for i in range(count)]


def test_experiment_model_defaults_include_start_offset_well_selection():
    em = ExperimentModel(prof=CURRENT_PROFILE)

    assert em.metadata["well_selection"] == {
        "mode": "start_offset",
        "included_wells": None,
    }
    assert em.get_well_selection() == {
        "mode": "start_offset",
        "included_wells": None,
    }
    assert em.get_auto_assignment_included_wells() is None


def test_reset_experiment_model_restores_default_well_selection():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.set_well_selection(["A1", "B2"])

    em.reset_experiment_model()

    assert em.metadata["well_selection"] == {
        "mode": "start_offset",
        "included_wells": None,
    }
    assert em.get_auto_assignment_included_wells() is None


def test_from_dict_adds_default_well_selection_for_legacy_design():
    em = ExperimentModel(prof=CURRENT_PROFILE)

    em.from_dict({
        "metadata": {
            "name": "legacy-design",
            "fill_droplet_volume_nL": 9.0,
        },
        "factors": [],
    })

    assert em.metadata["well_selection"] == {
        "mode": "start_offset",
        "included_wells": None,
    }


def test_experiment_model_custom_well_selection_normalizes_and_deduplicates():
    em = ExperimentModel(prof=CURRENT_PROFILE)

    em.set_well_selection(["a1", "A1", "b2"])

    assert em.get_well_selection() == {
        "mode": "custom",
        "included_wells": ["A1", "B2"],
    }
    assert em.get_auto_assignment_included_wells() == ["A1", "B2"]


def test_experiment_model_rejects_malformed_custom_well_selection():
    em = ExperimentModel(prof=CURRENT_PROFILE)

    with pytest.raises(ValueError, match="Invalid well ID"):
        em.set_well_selection(["not-a-well"])


def test_normalize_included_wells_accepts_case_and_high_density_rows(tmp_path):
    wp = _high_density_plate(tmp_path)

    assert wp.normalize_included_wells(["aa1", "AA1", "af48"]) == ["AA1", "AF48"]


def test_normalize_included_wells_rejects_malformed_and_out_of_bounds(tmp_path):
    wp = _high_density_plate(tmp_path)

    with pytest.raises(ValueError, match="Invalid well IDs"):
        wp.normalize_included_wells(["not-a-well"])

    with pytest.raises(ValueError, match="Out of bounds"):
        wp.normalize_included_wells(["AG1", "A49"])


def test_get_available_wells_without_custom_selection_preserves_start_offset(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    expected = [
        well.well_id
        for well in wp.get_available_wells(fill_by="rows", start_row=1, start_col=1)
    ]
    actual = [
        well.well_id
        for well in wp.get_available_wells(
            fill_by="rows",
            start_row=1,
            start_col=1,
            included_wells=None,
        )
    ]

    assert actual == expected


def test_custom_included_wells_restrict_availability_and_ignore_start_offset(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate
    wp.exclude_well("B1")

    ids = [
        well.well_id
        for well in wp.get_available_wells(
            fill_by="rows",
            start_row=999,
            start_col=999,
            included_wells=["A1", "B1", "A2"],
        )
    ]

    assert ids == ["A1", "A2"]


def test_assign_reactions_to_wells_uses_custom_pool_in_zigzag_order(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    assigned = wp.assign_reactions_to_wells(
        _reactions(2),
        fill_by="columns",
        included_wells=["C1", "A1"],
    )

    assert list(assigned.values()) == ["A1", "C1"]


def test_assign_reactions_to_wells_fails_when_custom_pool_is_too_small(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    with pytest.raises(ValueError, match="Not enough available wells"):
        wp.assign_reactions_to_wells(
            _reactions(3),
            included_wells=["A1", "A2"],
        )


def test_explicit_well_validation_is_not_constrained_by_model_well_selection(experiment_model_factory):
    model = experiment_model_factory()
    model.experiment_model.set_well_selection(["A1"])

    assert model.well_plate.validate_explicit_well_ids(["B1"]) == ["B1"]
