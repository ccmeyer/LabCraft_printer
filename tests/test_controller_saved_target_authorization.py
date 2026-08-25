import copy
from types import SimpleNamespace

from Controller import Controller
from ConfigurationSafetyPolicy import ConfigurationSafetyError
from MachineDataVerification import SavedTargetAuthorizationDecision
from Model import MachineModel


MACHINE_UUID = "00000000-0000-0000-0000-000000000123"


class RecordingAuthorizer:
    def __init__(self, *, allowed):
        self.allowed = bool(allowed)
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        return SavedTargetAuthorizationDecision(
            allowed=self.allowed,
            reason_code="authorized" if self.allowed else "target_unverified",
            message=(
                "Saved target matches verification."
                if self.allowed
                else "Saved target is not verified."
            ),
            target_key=request.target_key,
        )


class _Signal:
    def __init__(self):
        self.events = []

    def emit(self, payload):
        self.events.append(payload)


class _EndpointGuard:
    policy = SimpleNamespace(position_telemetry_max_age_ms=2500)

    @staticmethod
    def validate_endpoint(point):
        normalized = {axis: int(point[axis]) for axis in ("X", "Y", "Z")}
        if any(value < 0 or value > 150000 for value in normalized.values()):
            raise ConfigurationSafetyError("endpoint outside test bounds")
        return normalized


class TargetValueMismatchAuthorizer:
    def __init__(self):
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        return SavedTargetAuthorizationDecision(
            allowed=False,
            reason_code="target_value_changed",
            message="Saved target values changed after verification.",
            target_key=request.target_key,
        )


def _cleaning_checkpoint_controller(position=None):
    position = dict(position or {"X": 4321, "Y": 5432, "Z": 61000})
    clock = [10.0]
    queue_empty = {"value": True}
    calls = []
    callbacks = []
    errors = []
    events = []
    authorizer = TargetValueMismatchAuthorizer()
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
    controller.profile = SimpleNamespace(name="current")
    controller._monotonic_fn = lambda: clock[0]
    controller.expected_position = copy.deepcopy(position)
    controller.expected_location = "camera"
    controller._position_reconciliation = {
        "state": "settled",
        "reason": "test_setup",
        "expected_position": copy.deepcopy(position),
        "reported_position": copy.deepcopy(position),
        "trust_epoch": machine_model.get_motion_trust_epoch(),
    }
    controller._pending_motion_endpoint_evidence = None
    controller._printer_head_cleaning_checkpoint = None
    controller._printer_head_cleaning_return_scope = None
    controller.saved_target_authorizer = authorizer
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.configuration_safety_guard = _EndpointGuard()
    controller.configuration_transactions = SimpleNamespace()
    controller.model = SimpleNamespace(
        machine_model=machine_model,
        location_model=SimpleNamespace(
            get_location_dict=lambda _name: {"X": 11000, "Y": 22000, "Z": 33000},
            update_current_location=lambda name: events.append(("location", name)),
        ),
        rack_model=SimpleNamespace(calibrations={}),
        well_plate=None,
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda *args: errors.append(args)
    )
    controller.get_xy_motion_recovery_state = lambda: "idle"
    controller.get_array_run_state = lambda: "idle"
    controller._seq_state = "idle"
    controller.check_if_all_completed = lambda: queue_empty["value"]

    def set_z(value, **_kwargs):
        calls.append(("z", int(value)))
        controller.expected_position["Z"] = int(value)
        return True

    def set_xyz(x, y, z, **kwargs):
        calls.append(("xyz", int(x), int(y), int(z)))
        controller.expected_position.update({"X": int(x), "Y": int(y), "Z": int(z)})
        callbacks.append(kwargs.get("handler"))
        return True

    controller.set_absolute_Z = set_z
    controller.set_absolute_Y = lambda value, **_kwargs: calls.append(
        ("y", int(value))
    ) or True
    controller.set_absolute_X = lambda value, **_kwargs: calls.append(
        ("x", int(value))
    ) or True
    controller.set_absolute_coordinates = set_xyz
    controller.update_location_handler = lambda name=None: events.append(
        ("location", name)
    )
    return SimpleNamespace(
        controller=controller,
        machine_model=machine_model,
        authorizer=authorizer,
        clock=clock,
        queue_empty=queue_empty,
        calls=calls,
        callbacks=callbacks,
        errors=errors,
        events=events,
        position=position,
    )


def _set_cleaning_controller_position(context, position, *, location="loading"):
    context.clock[0] += 0.1
    context.machine_model.update_reported_position(
        position,
        received_monotonic=context.clock[0],
    )
    context.controller.expected_position = copy.deepcopy(position)
    context.controller.expected_location = location
    context.controller._position_reconciliation = {
        "state": "settled",
        "reason": "test_position_update",
        "expected_position": copy.deepcopy(position),
        "reported_position": copy.deepcopy(position),
        "trust_epoch": context.machine_model.get_motion_trust_epoch(),
    }


def _move_controller(target, *, allowed, name="camera", rack=None, plate=None):
    commands = []
    errors = []
    authorizer = RecordingAuthorizer(allowed=allowed)
    controller = Controller.__new__(Controller)
    controller.profile = SimpleNamespace(name="current")
    controller.expected_position = {"X": 0, "Y": 0, "Z": 50000}
    controller.expected_location = "home"
    controller.saved_target_authorizer = authorizer
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.model = SimpleNamespace(
        location_model=SimpleNamespace(
            get_location_dict=lambda _name: dict(target),
        ),
        rack_model=rack or SimpleNamespace(calibrations={}),
        well_plate=plate,
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda *args: errors.append(args)
    )
    controller.set_absolute_Z = lambda value, **_kwargs: commands.append(
        ("z", value)
    ) or True
    controller.set_absolute_Y = lambda value, **_kwargs: commands.append(
        ("y", value)
    ) or True
    controller.set_absolute_X = lambda value, **_kwargs: commands.append(
        ("x", value)
    ) or True
    controller.set_absolute_coordinates = (
        lambda x, y, z, **_kwargs: commands.append(("xyz", x, y, z)) or True
    )
    controller.update_location_handler = lambda **_kwargs: None
    return controller, commands, errors, authorizer, name


def test_unverified_camera_is_denied_before_safe_route_or_final_command():
    controller, commands, errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=False,
    )

    result = Controller.move_to_location(controller, name)

    assert result is False
    assert commands == []
    assert errors == [("Move Blocked", "Saved target is not verified.")]
    assert authorizer.requests[0].target_key == "location:camera"


def test_unverified_move_can_emit_an_actionable_location_verification_route():
    controller, _commands, _errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=False,
    )
    assert Controller.move_to_location(controller, name) is False
    request = authorizer.requests[0]
    decision = authorizer.authorize(request)
    signal = _Signal()
    host = SimpleNamespace(
        configuration_verification_required=signal,
        _configuration_verification_route=Controller._configuration_verification_route,
    )

    assert Controller._emit_configuration_verification_required(
        host, decision, request
    ) is True
    assert signal.events == [
        {
            "target_key": "location:camera",
            "target_kind": "location",
            "reason_code": "target_unverified",
            "message": "Saved target is not verified.",
            "verification_route": "location_verification",
        }
    ]


def test_manual_override_and_ignore_safe_height_do_not_bypass_authorization():
    controller, commands, _errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=False,
    )

    result = Controller.move_to_location(
        controller,
        name,
        manual=True,
        override=True,
        ignore_safe_height=True,
    )

    assert result is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.manual is True
    assert request.override is True
    assert request.ignore_safe_height is True


def test_authorized_camera_preserves_existing_route_behavior():
    controller, commands, errors, authorizer, name = _move_controller(
        {"X": 11000, "Y": 22000, "Z": 33000},
        allowed=True,
    )

    result = Controller.move_to_location(controller, name)

    assert result is True
    assert commands == [("xyz", 11000, 22000, 33000)]
    assert errors == []
    assert len(authorizer.requests) == 1


def test_rack_slot_uses_pair_authorization_and_denial_queues_nothing():
    calibrations = {
        "rack_position_Left": {"X": 100, "Y": 200, "Z": 300},
        "rack_position_Right": {"X": 400, "Y": 500, "Z": 600},
    }
    rack = SimpleNamespace(calibrations=calibrations)
    controller, commands, _errors, authorizer, _name = _move_controller(
        {"X": 250, "Y": 350, "Z": 450},
        allowed=False,
        name="Slot-2",
        rack=rack,
    )

    result = Controller.move_to_location(
        controller,
        "Slot-2",
        coords={"X": 250, "Y": 350, "Z": 450},
        override=True,
    )

    assert result is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.target_key == "rack:primary"
    assert request.target_kind == "rack"
    assert request.base_value == {
        "Left": calibrations["rack_position_Left"],
        "Right": calibrations["rack_position_Right"],
    }


def test_plate_location_uses_four_corner_authorization():
    calibrations = {
        "top_left": {"X": 1, "Y": 2, "Z": 3},
        "top_right": {"X": 4, "Y": 5, "Z": 6},
        "bottom_right": {"X": 7, "Y": 8, "Z": 9},
        "bottom_left": {"X": 10, "Y": 11, "Z": 12},
    }
    plate = SimpleNamespace(
        get_current_plate_name=lambda: "Plate96",
        get_all_current_plate_calibrations=lambda: calibrations,
        get_plate_reference_coords=lambda: {"X": 1, "Y": 2, "Z": 3},
    )
    controller, commands, _errors, authorizer, _name = _move_controller(
        {"X": 1, "Y": 2, "Z": 3},
        allowed=False,
        name="plate",
        plate=plate,
    )

    assert Controller.move_to_location(controller, "plate") is False
    assert commands == []
    request = authorizer.requests[0]
    assert request.target_key == "plate:plate96"
    assert request.target_kind == "plate"
    assert request.base_value == calibrations


def test_plate_array_denial_precedes_overshoot_and_well_commands():
    commands = []
    finalized = []
    errors = []
    authorizer = RecordingAuthorizer(allowed=False)
    calibrations = {
        "top_left": {"X": 1, "Y": 2, "Z": 3},
        "top_right": {"X": 4, "Y": 5, "Z": 6},
        "bottom_right": {"X": 7, "Y": 8, "Z": 9},
        "bottom_left": {"X": 10, "Y": 11, "Z": 12},
    }
    well = SimpleNamespace(
        well_id="A1",
        get_remaining_droplets=lambda _stock_id: 5,
        get_coordinates=lambda: {"X": 100, "Y": 200, "Z": 300},
    )
    controller = Controller.__new__(Controller)
    controller._array_context = {"stock_id": "stock-1"}
    controller._get_next_unplanned_array_well = lambda _context: well
    controller._complete_array_finalize = lambda reason: finalized.append(reason)
    controller.saved_target_authorizer = authorizer
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.model = SimpleNamespace(
        well_plate=SimpleNamespace(
            get_current_plate_name=lambda: "Plate96",
            get_all_current_plate_calibrations=lambda: calibrations,
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda *args: errors.append(args)
    )
    controller.set_absolute_coordinates = (
        lambda *args, **kwargs: commands.append((args, kwargs)) or True
    )

    assert Controller._queue_next_array_well(controller) is False
    assert commands == []
    assert finalized == ["hard_abort"]
    assert errors == [("Move Blocked", "Saved target is not verified.")]
    assert authorizer.requests[0].target_key == "plate:plate96"


def test_cleaning_checkpoint_return_allows_exact_transient_camera_position_only():
    context = _cleaning_checkpoint_controller()
    controller = context.controller

    checkpoint = controller.create_printer_head_cleaning_checkpoint()

    assert checkpoint["allowed"] is True
    assert checkpoint["position"] == context.position
    assert Controller.move_to_location(
        controller,
        "camera",
        coords=context.position,
        manual=True,
    ) is False
    assert context.calls == []
    assert context.errors[-1] == (
        "Move Blocked",
        "Saved target values changed after verification.",
    )
    assert len(context.authorizer.requests) == 1

    loading = {"X": 14500, "Y": 30500, "Z": 50000}
    _set_cleaning_controller_position(context, loading)
    completed = []

    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"],
        on_complete=lambda: completed.append(True),
    ) is True
    assert context.calls == [
        ("z", 35000),
        ("xyz", context.position["X"], context.position["Y"], context.position["Z"]),
    ]
    assert len(context.authorizer.requests) == 1
    assert controller._printer_head_cleaning_checkpoint["state"] == "returning"

    context.callbacks[-1]()

    assert completed == [True]
    assert controller._printer_head_cleaning_checkpoint["state"] == "completed"
    assert context.events == [("location", "camera")]
    calls_before_reuse = list(context.calls)
    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is False
    assert context.calls == calls_before_reuse
    assert controller.release_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is True
    assert controller._printer_head_cleaning_checkpoint is None


def test_cleaning_checkpoint_rejects_forged_identity_and_trust_changes_before_motion():
    context = _cleaning_checkpoint_controller()
    controller = context.controller
    checkpoint = controller.create_printer_head_cleaning_checkpoint()
    loading = {"X": 14500, "Y": 30500, "Z": 50000}
    _set_cleaning_controller_position(context, loading)

    assert controller.return_to_printer_head_cleaning_checkpoint("forged-token") is False
    assert context.calls == []

    controller.machine_data_paths = SimpleNamespace(machine_uuid="different-machine")
    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is False
    assert controller._printer_head_cleaning_checkpoint["state"] == "revoked"
    assert context.calls == []

    trust_context = _cleaning_checkpoint_controller()
    trust_checkpoint = (
        trust_context.controller.create_printer_head_cleaning_checkpoint()
    )
    _set_cleaning_controller_position(trust_context, loading)
    trust_context.machine_model.reset_home_status()
    trust_context.machine_model.motors_homed = True
    trust_context.clock[0] += 0.1
    trust_context.machine_model.update_reported_position(
        loading,
        received_monotonic=trust_context.clock[0],
    )

    assert trust_context.controller.return_to_printer_head_cleaning_checkpoint(
        trust_checkpoint["checkpoint_id"]
    ) is False
    assert trust_context.controller._printer_head_cleaning_checkpoint["state"] == "revoked"
    assert trust_context.calls == []


def test_cleaning_checkpoint_temporary_readiness_failure_can_retry_after_idle():
    context = _cleaning_checkpoint_controller()
    controller = context.controller
    checkpoint = controller.create_printer_head_cleaning_checkpoint()
    loading = {"X": 14500, "Y": 30500, "Z": 50000}
    _set_cleaning_controller_position(context, loading)
    context.queue_empty["value"] = False

    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is False
    assert controller._printer_head_cleaning_checkpoint["state"] == "active"
    assert context.calls == []

    context.queue_empty["value"] = True
    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is True
    assert context.calls[-1] == (
        "xyz",
        context.position["X"],
        context.position["Y"],
        context.position["Z"],
    )


def test_cleaning_checkpoint_live_readiness_failures_queue_nothing():
    loading = {"X": 14500, "Y": 30500, "Z": 50000}

    def disconnect(context):
        context.machine_model.machine_connected = False

    def unhome(context):
        context.machine_model.motors_homed = False

    def pause(context):
        context.machine_model.paused = True

    def pause_transport(context):
        context.machine_model.transport_paused = True

    def mark_busy(context):
        context.machine_model.machine_free = False

    def keep_queue_active(context):
        context.queue_empty["value"] = False

    def stale_telemetry(context):
        context.clock[0] += 3.0

    def mismatch_expected_position(context):
        context.controller.expected_position["X"] += 2

    for mutation in (
        disconnect,
        unhome,
        pause,
        pause_transport,
        mark_busy,
        keep_queue_active,
        stale_telemetry,
        mismatch_expected_position,
    ):
        context = _cleaning_checkpoint_controller()
        checkpoint = context.controller.create_printer_head_cleaning_checkpoint()
        _set_cleaning_controller_position(context, loading)
        mutation(context)

        assert context.controller.return_to_printer_head_cleaning_checkpoint(
            checkpoint["checkpoint_id"]
        ) is False, mutation.__name__
        assert context.controller._printer_head_cleaning_checkpoint["state"] == "active"
        assert context.calls == []


def test_cleaning_checkpoint_released_or_tampered_endpoint_queues_nothing():
    released_context = _cleaning_checkpoint_controller()
    released = released_context.controller.create_printer_head_cleaning_checkpoint()
    assert released_context.controller.release_printer_head_cleaning_checkpoint(
        released["checkpoint_id"]
    ) is True
    assert released_context.controller.return_to_printer_head_cleaning_checkpoint(
        released["checkpoint_id"]
    ) is False
    assert released_context.calls == []

    tampered_context = _cleaning_checkpoint_controller()
    tampered = tampered_context.controller.create_printer_head_cleaning_checkpoint()
    _set_cleaning_controller_position(
        tampered_context,
        {"X": 14500, "Y": 30500, "Z": 50000},
    )
    tampered_context.controller._printer_head_cleaning_checkpoint["position"]["Z"] = 160000

    assert tampered_context.controller.return_to_printer_head_cleaning_checkpoint(
        tampered["checkpoint_id"]
    ) is False
    assert tampered_context.controller._printer_head_cleaning_checkpoint["state"] == "revoked"
    assert tampered_context.calls == []


def test_cleaning_checkpoint_failed_dispatch_restores_active_state_for_recovery():
    context = _cleaning_checkpoint_controller()
    controller = context.controller
    checkpoint = controller.create_printer_head_cleaning_checkpoint()
    loading = {"X": 14500, "Y": 30500, "Z": 50000}
    _set_cleaning_controller_position(context, loading)
    original_xyz = controller.set_absolute_coordinates
    controller.set_absolute_coordinates = lambda *_args, **_kwargs: False

    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is False
    assert controller._printer_head_cleaning_checkpoint["state"] == "active"
    assert context.calls == [("z", 35000)]

    controller.set_absolute_coordinates = original_xyz
    reconciled = dict(controller.expected_position)
    _set_cleaning_controller_position(context, reconciled)
    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"]
    ) is True
    assert context.calls[-1] == (
        "xyz",
        context.position["X"],
        context.position["Y"],
        context.position["Z"],
    )


def test_cleaning_checkpoint_lost_callback_retry_ignores_stale_completion():
    context = _cleaning_checkpoint_controller()
    controller = context.controller
    checkpoint = controller.create_printer_head_cleaning_checkpoint()
    _set_cleaning_controller_position(
        context,
        {"X": 14500, "Y": 30500, "Z": 50000},
    )
    completed = []

    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"],
        on_complete=lambda: completed.append("first"),
    ) is True
    first_callback = context.callbacks[-1]

    _set_cleaning_controller_position(context, context.position)
    assert controller.return_to_printer_head_cleaning_checkpoint(
        checkpoint["checkpoint_id"],
        on_complete=lambda: completed.append("retry"),
    ) is True
    retry_callback = context.callbacks[-1]

    first_callback()
    assert completed == []
    assert controller._printer_head_cleaning_checkpoint["state"] == "returning"

    retry_callback()
    assert completed == ["retry"]
    assert controller._printer_head_cleaning_checkpoint["state"] == "completed"


def test_cleaning_checkpoint_scope_cannot_authorize_a_different_target_or_flags():
    context = _cleaning_checkpoint_controller()
    controller = context.controller
    checkpoint = controller.create_printer_head_cleaning_checkpoint()
    controller._printer_head_cleaning_checkpoint["state"] = "returning"
    different = dict(context.position)
    different["X"] += 2

    with controller._printer_head_cleaning_return_motion_scope(
        checkpoint["checkpoint_id"]
    ):
        assert Controller.move_to_location(
            controller,
            "camera",
            coords=different,
            manual=True,
        ) is False
    assert context.calls == []
    assert "does not match" in context.errors[-1][1]

    context.errors.clear()
    with controller._printer_head_cleaning_return_motion_scope(
        checkpoint["checkpoint_id"]
    ):
        assert Controller.move_to_location(
            controller,
            "camera",
            coords=context.position,
            manual=True,
            override=True,
        ) is False
    assert context.calls == []
    assert "does not match" in context.errors[-1][1]


def test_cleaning_checkpoint_creation_rejects_non_camera_and_out_of_bounds_positions():
    context = _cleaning_checkpoint_controller()
    context.controller.expected_location = "loading"

    rejected = context.controller.create_printer_head_cleaning_checkpoint()

    assert rejected["allowed"] is False
    assert rejected["reason_code"] == "not_camera_context"
    assert context.controller._printer_head_cleaning_checkpoint is None

    bounds_context = _cleaning_checkpoint_controller(
        {"X": 4321, "Y": 5432, "Z": 160000}
    )
    rejected = bounds_context.controller.create_printer_head_cleaning_checkpoint()

    assert rejected["allowed"] is False
    assert rejected["reason_code"] == "machine_not_ready"
    assert bounds_context.calls == []
