import copy
from types import SimpleNamespace

from Controller import Controller
from MachineDataTransactions import ConfigurationRecoveryRequired


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Service:
    def __init__(self, order, *, error=None):
        self.order = order
        self.error = error
        self.saved_target_authorizer = object()
        self.calls = []
        self.os_account = "test-account"

    def commit_documents(self, proposed, **kwargs):
        self.calls.append((copy.deepcopy(proposed), dict(kwargs)))
        self.order.append("disk")
        if self.error is not None:
            raise self.error
        return SimpleNamespace(documents=copy.deepcopy(proposed))


def _controller(service, model):
    controller = Controller.__new__(Controller)
    controller.configuration_transactions = service
    controller.model = model
    controller.machine = SimpleNamespace(_command_queue_blocked_reason=None)
    controller.error_occurred_signal = _Signal()
    controller._configuration_recovery_required = False
    controller.saved_target_authorizer = None
    return controller


def test_named_location_persists_before_one_complete_memory_install():
    order = []
    locations = {"camera": {"X": 1, "Y": 2, "Z": 3}}
    installed = []
    model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position=lambda: (10, 20, 30)),
        location_model=SimpleNamespace(get_all_locations=lambda: copy.deepcopy(locations)),
        install_committed_locations=lambda value: (
            order.append("memory"), installed.append(copy.deepcopy(value))
        ),
        install_committed_plates=lambda _value: None,
        install_committed_regulator_profiles=lambda _value: None,
    )
    service = _Service(order)
    controller = _controller(service, model)

    result = Controller.commit_named_location(
        controller,
        "camera",
        operator="Alice",
        reason="Physically recalibrated",
        require_existing=True,
    )

    assert result
    assert order == ["disk", "memory"]
    assert installed == [{"camera": {"X": 10, "Y": 20, "Z": 30}}]
    assert service.calls[0][1]["workflow"] == "named_location_modify"


def test_transaction_failure_keeps_prior_memory_and_sets_fatal_latch_for_recovery_error():
    order = []
    locations = {"camera": {"X": 1, "Y": 2, "Z": 3}}
    model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position=lambda: (10, 20, 30)),
        location_model=SimpleNamespace(get_all_locations=lambda: copy.deepcopy(locations)),
        install_committed_locations=lambda _value: order.append("memory"),
        install_committed_plates=lambda _value: None,
        install_committed_regulator_profiles=lambda _value: None,
    )
    service = _Service(order, error=ConfigurationRecoveryRequired("recover on restart"))
    controller = _controller(service, model)

    result = Controller.commit_named_location(
        controller,
        "camera",
        operator="Alice",
        reason="Fault test",
        require_existing=True,
    )

    assert result is False
    assert order == ["disk"]
    assert controller._configuration_recovery_required is True
    assert controller.error_occurred_signal.calls


def test_model_install_failure_blocks_machine_queue_until_restart():
    order = []
    model = SimpleNamespace(
        install_committed_locations=lambda _value: (_ for _ in ()).throw(
            RuntimeError("install failed")
        ),
        install_committed_plates=lambda _value: None,
        install_committed_regulator_profiles=lambda _value: None,
    )
    service = _Service(order)
    controller = _controller(service, model)
    result = SimpleNamespace(documents={"Locations.json": {"camera": {"X": 1, "Y": 2, "Z": 3}}})

    assert Controller._install_committed_configuration(controller, result) is False
    assert controller._configuration_recovery_required is True
    assert controller.machine._command_queue_blocked_reason == "configuration_recovery_required"
    assert controller.error_occurred_signal.calls[0][0] == "Configuration Restart Required"


def test_rack_and_plate_adapters_commit_complete_aggregates_once_then_clear_temp():
    order = []
    locations = {
        "rack_position_Left": {"X": 1, "Y": 2, "Z": 3},
        "rack_position_Right": {"X": 4, "Y": 5, "Z": 6},
        "Pause": {"X": 7, "Y": 8, "Z": 9},
    }
    rack_temp = {
        "rack_position_Left": {"X": 11, "Y": 12, "Z": 13},
        "rack_position_Right": {"X": 14, "Y": 15, "Z": 16},
    }
    rack_clears = []
    plate_clears = []
    plates = [
        {
            "name": "plate-a",
            "calibrations": {"top_left": {"X": 1, "Y": 2, "Z": 30}},
        }
    ]
    model = SimpleNamespace(
        location_model=SimpleNamespace(get_all_locations=lambda: copy.deepcopy(locations)),
        rack_model=SimpleNamespace(
            temp_calibration_data=copy.deepcopy(rack_temp),
            discard_temp_calibrations=lambda: rack_clears.append(True),
        ),
        well_plate=SimpleNamespace(
            proposed_calibration_document=lambda: copy.deepcopy(plates),
            get_current_plate_name=lambda: "plate-a",
            discard_temp_calibrations=lambda: plate_clears.append(True),
        ),
        install_committed_locations=lambda _value: order.append("locations-memory"),
        install_committed_plates=lambda _value: order.append("plates-memory"),
        install_committed_regulator_profiles=lambda _value: None,
    )
    service = _Service(order)
    controller = _controller(service, model)

    assert Controller.commit_rack_calibration(
        controller, operator="Alice", reason="Rack calibration"
    )
    assert Controller.commit_plate_calibration(
        controller, operator="Alice", reason="Plate calibration"
    )

    assert len(service.calls) == 2
    rack_document = service.calls[0][0]["Locations.json"]
    assert rack_document["rack_position_Left"] == rack_temp["rack_position_Left"]
    assert rack_document["rack_position_Right"] == rack_temp["rack_position_Right"]
    plate_documents = service.calls[1][0]
    assert plate_documents["Plates.json"] == plates
    assert plate_documents["Locations.json"]["Pause"] == {
        "X": 7,
        "Y": 8,
        "Z": 30,
    }
    assert rack_clears == [True]
    assert plate_clears == [True]
    assert order == [
        "disk",
        "locations-memory",
        "disk",
        "locations-memory",
        "plates-memory",
    ]
