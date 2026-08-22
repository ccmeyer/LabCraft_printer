import copy
from types import SimpleNamespace

from Controller import Controller
from Model import MachineModel


COMMAND_TARGET = {"X": 33050, "Y": 29874, "Z": 84350}
PARTIAL_DRAIN_POSITION = {"X": 33050, "Y": 29874, "Z": 84312}


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _EndpointGuard:
    def __init__(self, timeout_ms=2500):
        self.policy = SimpleNamespace(position_telemetry_max_age_ms=timeout_ms)

    @staticmethod
    def validate_endpoint(point):
        return dict(point)


def _capture_controller(clock, *, position=None, timeout_ms=2500):
    position = dict(position or PARTIAL_DRAIN_POSITION)
    machine_model = MachineModel()
    machine_model.machine_connected = True
    machine_model.motors_enabled = True
    machine_model.motors_homed = True
    machine_model.machine_free = True
    machine_model.update_reported_position(
        position,
        received_monotonic=clock[0],
    )

    controller = Controller.__new__(Controller)
    controller._monotonic_fn = lambda: clock[0]
    controller.model = SimpleNamespace(
        machine_model=machine_model,
        rack_model=SimpleNamespace(sync_expected_to_actual=lambda: None),
        well_plate=SimpleNamespace(temp_calibration_data={}),
    )
    controller.configuration_safety_guard = _EndpointGuard(timeout_ms)
    controller.configuration_transactions = SimpleNamespace(os_account="test-operator")
    controller.machine_data_paths = SimpleNamespace(machine_uuid="test-machine-uuid")
    controller.expected_position = copy.deepcopy(COMMAND_TARGET)
    controller.expected_location = None
    controller._position_reconciliation = {
        "state": "settled",
        "reason": "test_setup",
        "expected_position": copy.deepcopy(COMMAND_TARGET),
    }
    controller._configuration_capture_evidence = {}
    controller.error_occurred_signal = _Signal()
    controller.recorded_attempts = []
    controller.record_configuration_attempt = lambda **kwargs: (
        controller.recorded_attempts.append(copy.deepcopy(kwargs))
    )
    controller.get_xy_motion_recovery_state = lambda: "idle"
    controller.get_array_run_state = lambda: "idle"
    controller._seq_state = "idle"
    controller.check_if_all_completed = lambda: True
    return controller, machine_model


def _advance_axis(controller, machine_model, clock, axis, value):
    clock[0] += 0.01
    machine_model.update_reported_position(
        {axis: value},
        received_monotonic=clock[0],
    )
    return controller._advance_position_reconciliation()


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


def test_queue_drain_waits_for_complete_post_motion_position_before_capture():
    clock = [10.0]
    controller, machine_model = _capture_controller(clock)

    controller._begin_position_reconciliation()

    assert controller.expected_position == COMMAND_TARGET
    assert controller._position_reconciliation["state"] == "pending"
    assert _advance_axis(
        controller, machine_model, clock, "X", COMMAND_TARGET["X"]
    )["state"] == "pending"
    assert _advance_axis(
        controller, machine_model, clock, "Y", COMMAND_TARGET["Y"]
    )["state"] == "pending"
    pending = controller._configuration_capture_readiness()
    assert pending["reason_codes"] == ["position_reconciliation_pending"]
    assert controller.capture_configuration_point(
        "plate:test:bottom_right",
        workflow="plate_calibration",
    ) is False
    assert "wait briefly and retry" in controller.error_occurred_signal.calls[-1][1]

    settled = _advance_axis(
        controller, machine_model, clock, "Z", COMMAND_TARGET["Z"]
    )
    captured = controller.capture_configuration_point(
        "plate:test:bottom_right",
        workflow="plate_calibration",
    )

    assert settled["state"] == "settled"
    assert settled["reported_position"] == COMMAND_TARGET
    assert controller.expected_position == COMMAND_TARGET
    assert captured == COMMAND_TARGET
    evidence = controller._configuration_capture_evidence[
        ("plate_calibration", "plate:test:bottom_right")
    ]
    assert evidence["position_reconciliation"]["state"] == "settled"


def test_coherent_post_drain_disagreement_remains_a_true_mismatch():
    clock = [20.0]
    controller, machine_model = _capture_controller(clock)
    controller._begin_position_reconciliation()

    _advance_axis(controller, machine_model, clock, "X", COMMAND_TARGET["X"])
    _advance_axis(controller, machine_model, clock, "Y", COMMAND_TARGET["Y"])
    mismatch = _advance_axis(controller, machine_model, clock, "Z", 84349)
    readiness = controller._configuration_capture_readiness()

    assert mismatch["state"] == "mismatch"
    assert mismatch["reported_position"]["Z"] == 84349
    assert controller.expected_position == COMMAND_TARGET
    assert "expected_position_mismatch" in readiness["reason_codes"]

    machine_model.update_reported_position(
        COMMAND_TARGET,
        received_monotonic=clock[0] + 0.01,
    )
    assert controller._advance_position_reconciliation()["state"] == "mismatch"


def test_incomplete_post_drain_cycle_times_out_then_can_recover():
    clock = [30.0]
    controller, machine_model = _capture_controller(clock)
    controller._begin_position_reconciliation()
    _advance_axis(controller, machine_model, clock, "X", COMMAND_TARGET["X"])
    _advance_axis(controller, machine_model, clock, "Y", COMMAND_TARGET["Y"])

    clock[0] = 32.51
    timed_out = controller._advance_position_reconciliation()
    timeout_readiness = controller._configuration_capture_readiness()

    assert timed_out["state"] == "timed_out"
    assert "position_reconciliation_timeout" in timeout_readiness["reason_codes"]

    _advance_axis(controller, machine_model, clock, "X", COMMAND_TARGET["X"])
    _advance_axis(controller, machine_model, clock, "Y", COMMAND_TARGET["Y"])
    recovered = _advance_axis(
        controller, machine_model, clock, "Z", COMMAND_TARGET["Z"]
    )
    assert recovered["state"] == "settled"
    assert controller._configuration_capture_readiness()["ready"] is True


def test_motion_trust_change_during_reconciliation_is_fail_closed():
    clock = [40.0]
    controller, machine_model = _capture_controller(clock)
    controller._begin_position_reconciliation()

    machine_model.reset_home_status()
    machine_model.motors_homed = True
    trust_changed = controller._advance_position_reconciliation()
    readiness = controller._configuration_capture_readiness()

    assert trust_changed["state"] == "trust_changed"
    assert "position_reconciliation_trust_changed" in readiness["reason_codes"]


def test_later_queue_drain_supersedes_older_pending_record():
    clock = [50.0]
    controller, machine_model = _capture_controller(clock)
    controller._begin_position_reconciliation()
    first = copy.deepcopy(controller._position_reconciliation)
    _advance_axis(controller, machine_model, clock, "X", COMMAND_TARGET["X"])

    clock[0] += 0.5
    later_target = {"X": 33100, "Y": 29900, "Z": 84400}
    controller.expected_position = copy.deepcopy(later_target)
    controller._begin_position_reconciliation()
    second = controller._position_reconciliation

    assert second["state"] == "pending"
    assert second["started_monotonic"] > first["started_monotonic"]
    assert second["expected_position"] == later_target
    assert second["baseline_generations"]["X"] > first["baseline_generations"]["X"]


def test_explicit_current_resync_clears_pending_reconciliation():
    clock = [60.0]
    controller, machine_model = _capture_controller(clock)
    controller._begin_position_reconciliation()
    machine_model.update_reported_position(
        {"X": 33049, "Y": 29873, "Z": 84349},
        received_monotonic=clock[0],
    )

    controller.update_expected_with_current()

    assert controller.expected_position == {"X": 33049, "Y": 29873, "Z": 84349}
    assert controller._position_reconciliation["state"] == "settled"
    assert controller._position_reconciliation["reason"] == "explicit_current_resync"


def test_rejected_plate_capture_does_not_change_temporary_or_governed_data():
    clock = [70.0]
    controller, machine_model = _capture_controller(clock)
    temporary = {
        "top_left": {"X": 1, "Y": 2, "Z": 3},
        "top_right": {"X": 4, "Y": 5, "Z": 6},
    }
    governed = [{"name": "test", "calibrations": copy.deepcopy(temporary)}]
    controller.model.well_plate.temp_calibration_data = copy.deepcopy(temporary)
    before_temporary = copy.deepcopy(controller.model.well_plate.temp_calibration_data)
    before_governed = copy.deepcopy(governed)
    controller._begin_position_reconciliation()
    _advance_axis(controller, machine_model, clock, "X", COMMAND_TARGET["X"])
    _advance_axis(controller, machine_model, clock, "Y", COMMAND_TARGET["Y"])
    _advance_axis(controller, machine_model, clock, "Z", 84349)

    captured = controller.capture_configuration_point(
        "plate:test:bottom_right",
        workflow="plate_calibration",
    )

    assert captured is False
    assert controller.model.well_plate.temp_calibration_data == before_temporary
    assert governed == before_governed
    assert controller._configuration_capture_evidence == {}
    assert controller.recorded_attempts[0]["event_type"] == "rejected"
    assert "expected_position_mismatch" in controller.recorded_attempts[0]["reason"]


def test_each_model_status_hook_advances_position_reconciliation():
    calls = []
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_command_numbers=lambda: (1, 2, 3, 4))
    )
    controller.machine = SimpleNamespace(
        update_command_numbers=lambda *args: calls.append(("queue", args))
    )
    controller._advance_position_reconciliation = lambda: calls.append(
        ("reconciliation", None)
    )

    controller.update_command_numbers()

    assert calls == [
        ("queue", (1, 2, 3, 4)),
        ("reconciliation", None),
    ]
