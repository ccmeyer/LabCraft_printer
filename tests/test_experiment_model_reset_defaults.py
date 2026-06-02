from Model import ExperimentModel
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


def test_reset_experiment_model_uses_current_profile_fill_default():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.metadata["fill_droplet_volume_nL"] = 77.0

    em.reset_experiment_model()

    assert em.metadata["fill_droplet_volume_nL"] == 10.0
    assert em.metadata["fill_printing_mode"] == "droplet"
    assert em.metadata["target_reaction_volume_nL"] == 2000.0
    assert em.metadata["final_reaction_volume_nL"] == 2000.0


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
