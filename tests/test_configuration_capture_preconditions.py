from Model import MachineModel


def test_position_telemetry_refreshes_only_axes_present_in_received_status(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("Model.time.monotonic", lambda: clock[0])
    model = MachineModel()

    model.update_reported_position({"X": 100, "Y": 200, "Z": 300})
    clock[0] = 11.0
    model.update_reported_position({"X": 101, "Pressure_P": 10})
    snapshot = model.get_position_telemetry_snapshot(now_monotonic=12.0)

    assert snapshot["axes"]["X"]["generation"] == 2
    assert snapshot["axes"]["X"]["age_ms"] == 1000
    assert snapshot["axes"]["Y"]["generation"] == 1
    assert snapshot["axes"]["Y"]["age_ms"] == 2000
    assert snapshot["axes"]["Z"]["generation"] == 1


def test_motion_trust_epoch_invalidates_prior_position_freshness():
    model = MachineModel()
    model.update_reported_position({"X": 1, "Y": 2, "Z": 3}, received_monotonic=1.0)
    before = model.get_motion_trust_epoch()

    model.reset_home_status()
    snapshot = model.get_position_telemetry_snapshot(now_monotonic=2.0)

    assert model.get_motion_trust_epoch() == before + 1
    assert all(item["received_monotonic"] is None for item in snapshot["axes"].values())
    assert all(item["generation"] == 1 for item in snapshot["axes"].values())
