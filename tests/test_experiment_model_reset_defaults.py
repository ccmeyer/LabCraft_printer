from Model import ExperimentModel
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE


def test_reset_experiment_model_uses_current_profile_fill_default():
    em = ExperimentModel(prof=CURRENT_PROFILE)
    em.metadata["fill_droplet_volume_nL"] = 77.0

    em.reset_experiment_model()

    assert em.metadata["fill_droplet_volume_nL"] == 10.0
    assert em.metadata["fill_printing_mode"] == "droplet"


def test_reset_experiment_model_uses_legacy_profile_fill_default():
    em = ExperimentModel(prof=LEGACY_PROFILE)
    em.metadata["fill_droplet_volume_nL"] = 77.0

    em.reset_experiment_model()

    assert em.metadata["fill_droplet_volume_nL"] == 40.0
    assert em.metadata["fill_printing_mode"] == "stream"
