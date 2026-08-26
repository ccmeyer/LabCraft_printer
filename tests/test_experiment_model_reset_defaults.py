from Model import ExperimentModel, printing_mode_default_ejection_volume_nl
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


def test_reset_experiment_model_uses_current_profile_fill_default():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.metadata["fill_droplet_volume_nL"] = 77.0

    em.reset_experiment_model()

    assert printing_mode_default_ejection_volume_nl("droplet") == 9.0
    assert em.metadata["fill_droplet_volume_nL"] == 9.0
    assert em.metadata["fill_printing_mode"] == "droplet"
    assert em.metadata["target_reaction_volume_nL"] == 2000.0
    assert em.metadata["final_reaction_volume_nL"] == 2000.0
    assert em.metadata["allow_avoidable_target_grouping"] is False


def test_older_design_metadata_defaults_to_resolution_first():
    source = ExperimentModel(prof=CURRENT_PROFILE)
    payload = source.to_dict()
    payload["metadata"].pop("allow_avoidable_target_grouping", None)

    loaded = ExperimentModel(prof=CURRENT_PROFILE)
    loaded.from_dict(payload)

    assert loaded.metadata["allow_avoidable_target_grouping"] is False


def test_reset_experiment_model_uses_legacy_profile_fill_default():
    em = ExperimentModel(prof=LEGACY_PROFILE)
    em.metadata["fill_droplet_volume_nL"] = 77.0

    em.reset_experiment_model()

    assert em.metadata["fill_droplet_volume_nL"] == 40.0
    assert em.metadata["fill_printing_mode"] == "stream"


def test_reset_experiment_model_clears_runtime_context():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em._runtime_well_plate = object()
    em._runtime_reaction_collection = object()

    em.reset_experiment_model()

    assert em._runtime_well_plate is None
    assert em._runtime_reaction_collection is None


def test_reset_experiment_model_clears_terminal_transition_cache():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em._last_authoritative_terminal_transition = {
        "cache_path": "cached_completion",
    }

    em.reset_experiment_model()

    assert em._last_authoritative_terminal_transition is None
