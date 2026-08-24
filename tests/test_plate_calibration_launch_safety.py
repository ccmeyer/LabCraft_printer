import copy
from types import SimpleNamespace

from PySide6 import QtWidgets

import View
import Controller as controller_module
from Controller import Controller, PLATE_DOCK_SAFE_Z
from MachineDataVerification import canonical_value_sha256


PLATE_NAME = "shallow-384_well_plate"
MACHINE_UUID = "00000000-0000-0000-0000-000000000384"
CALIBRATIONS = {
    "top_left": {"X": 43770, "Y": 13320, "Z": 84050},
    "top_right": {"X": 43770, "Y": 29844, "Z": 84050},
    "bottom_right": {"X": 33020, "Y": 29844, "Z": 84050},
    "bottom_left": {"X": 33020, "Y": 13320, "Z": 84050},
}


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Plate:
    def __init__(self):
        self.temp_calibration_data = {}

    def get_current_plate_name(self):
        return PLATE_NAME

    def get_all_current_plate_calibrations(self):
        return copy.deepcopy(CALIBRATIONS)

    def set_calibration_position(self, name, position):
        self.temp_calibration_data[name] = copy.deepcopy(position)

    def discard_temp_calibrations(self):
        self.temp_calibration_data.clear()


def _entry_preflight(*, verified):
    return {
        "allowed": True,
        "machine_uuid": MACHINE_UUID,
        "trust_epoch": 7,
        "plate_name": PLATE_NAME,
        "target_key": f"plate:{PLATE_NAME}",
        "target_state": (
            "verified_by_controlled_calibration"
            if verified
            else "revoked_pending_verification"
        ),
        "verified": bool(verified),
        "initial_calibrations": copy.deepcopy(CALIBRATIONS),
        "initial_value_sha256": "a" * 64,
    }


def _route_controller(*, verified, reject_call=None):
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = None
    controller._configuration_capture_evidence = {}
    controller.expected_position = {"X": 500, "Y": 500, "Z": 66000}
    controller.expected_location = "Slot-5"
    controller.error_occurred_signal = _Signal()
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            is_busy=lambda: False,
            get_current_position_dict_capital=lambda: copy.deepcopy(
                controller.expected_position
            ),
        ),
        well_plate=_Plate(),
    )
    controller.plate_calibration_entry_preflight = lambda: _entry_preflight(
        verified=verified
    )
    controller._emit_optional = lambda *_args, **_kwargs: None
    controller.update_location_handler = lambda **_kwargs: None
    calls = []

    def record(kind, coordinates, kwargs):
        calls.append((kind, *coordinates, dict(kwargs)))
        if reject_call is not None and len(calls) == reject_call:
            return False
        if kind == "Z":
            controller.expected_position["Z"] = int(coordinates[0])
        elif kind == "XY":
            controller.expected_position.update(
                {"X": int(coordinates[0]), "Y": int(coordinates[1])}
            )
        else:
            controller.expected_position.update(
                {
                    "X": int(coordinates[0]),
                    "Y": int(coordinates[1]),
                    "Z": int(coordinates[2]),
                }
            )
        return True

    controller.set_absolute_Z = lambda z, **kwargs: record("Z", (z,), kwargs)
    controller.set_absolute_XY = lambda x, y, **kwargs: record(
        "XY", (x, y), kwargs
    )
    controller.set_absolute_coordinates = lambda x, y, z, **kwargs: record(
        "XYZ", (x, y, z), kwargs
    )
    return controller, calls


def test_unverified_entry_stops_at_safe_height_without_any_automatic_descent():
    controller, calls = _route_controller(verified=False)

    result = controller.begin_plate_calibration_entry(manual_first=True)

    assert result["state"] == "staging"
    assert [(call[0], *call[1:-1]) for call in calls] == [
        ("Z", PLATE_DOCK_SAFE_Z),
        ("XYZ", 38770, 13320, PLATE_DOCK_SAFE_Z),
        ("XYZ", 43770, 13320, PLATE_DOCK_SAFE_Z),
    ]
    assert not any(
        call[0] == "Z" and call[1] in {83550, 84050}
        for call in calls
    )
    assert calls[-1][-1]["handler"] is not None


def test_plate_dialog_constructor_issues_no_motion(qapp, monkeypatch):
    monkeypatch.setattr(
        View,
        "SimplePositionWidget",
        lambda *_args, **_kwargs: QtWidgets.QWidget(),
    )
    monkeypatch.setattr(
        View,
        "ShortcutTableWidget",
        lambda *_args, **_kwargs: QtWidgets.QWidget(),
    )
    motion_calls = []
    machine_model = SimpleNamespace(
        step_size=500,
        increase_step_size=lambda: None,
        decrease_step_size=lambda: None,
    )
    plate = _Plate()
    model = SimpleNamespace(machine_model=machine_model, well_plate=plate)
    main_window = SimpleNamespace(
        color_dict={
            "dark_blue": "#000088",
            "dark_red": "#880000",
            "dark_gray": "#444444",
            "darker_gray": "#222222",
        }
    )
    controller = SimpleNamespace(
        set_absolute_coordinates=lambda *args, **kwargs: motion_calls.append(
            (args, kwargs)
        ),
        jog_plate_calibration=lambda *args, **kwargs: motion_calls.append(
            (args, kwargs)
        ),
    )

    dialog = View.PlateCalibrationDialog(
        main_window,
        model,
        controller,
        session_token="session",
        manual_first=True,
    )

    assert motion_calls == []
    assert "safe Z=500" in dialog.instructions_label.text()
    dialog.deleteLater()


def test_verified_entry_descends_only_after_safe_z_and_both_xy_stages():
    controller, calls = _route_controller(verified=True)

    result = controller.begin_plate_calibration_entry(manual_first=False)

    assert result["state"] == "staging"
    assert [(call[0], *call[1:-1]) for call in calls] == [
        ("Z", 500),
        ("XYZ", 38770, 13320, 500),
        ("XYZ", 43770, 13320, 500),
        ("Z", 84050),
    ]
    assert calls[-1][-1]["override"] is True


def test_rejected_entry_step_never_queues_a_dependent_step_or_opens_session():
    controller, calls = _route_controller(verified=False, reject_call=2)

    result = controller.begin_plate_calibration_entry(manual_first=True)

    assert result is False
    assert len(calls) == 2
    assert controller._plate_calibration_session["state"] == "failed"
    assert controller._plate_calibration_session["failure_reason"] == "plate_dogleg_rejected"


def test_duplicate_entry_is_rejected_before_machine_or_configuration_access():
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = {
        "session_token": "active",
        "state": "staging",
    }

    result = Controller.plate_calibration_entry_preflight(controller)

    assert result["allowed"] is False
    assert result["reason_code"] == "plate_calibration_already_active"


def test_missing_calibration_head_precedes_stale_position_reconciliation():
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = None
    controller._rack_calibration_session = None
    controller.expected_location = "Home"
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            is_connected=lambda: True,
            motors_are_enabled=lambda: True,
            motors_are_homed=lambda: True,
            paused=False,
            transport_paused=False,
            is_busy=lambda: False,
        ),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
    )
    controller.check_if_all_completed = lambda: True
    readiness_calls = []
    controller._configuration_capture_readiness = lambda: readiness_calls.append(
        True
    ) or {
        "ready": False,
        "reason_codes": ["expected_position_mismatch"],
    }

    result = controller.plate_calibration_entry_preflight()

    assert result["allowed"] is False
    assert result["reason_code"] == "calibration_head_required"
    assert readiness_calls == []


def test_revoked_plate_preflight_exposes_historical_review_without_authorizing_motion(
    monkeypatch,
):
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = None
    controller.expected_location = "Slot-5"
    controller.machine_data_paths = SimpleNamespace(machine_uuid=MACHINE_UUID)
    controller.configuration_safety_guard = SimpleNamespace(
        validate_active_documents=lambda _documents: None
    )
    authorization = {
        "state": "revoked_pending_verification",
        "value_sha256": canonical_value_sha256(CALIBRATIONS),
    }
    controller.configuration_transactions = SimpleNamespace(
        paths=SimpleNamespace(),
        refresh=lambda **_kwargs: SimpleNamespace(
            authorization={f"plate:{PLATE_NAME}": authorization}
        ),
    )
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            is_connected=lambda: True,
            motors_are_enabled=lambda: True,
            motors_are_homed=lambda: True,
            paused=False,
            transport_paused=False,
            is_busy=lambda: False,
        ),
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: SimpleNamespace(
                is_calibration_chip=lambda: True
            )
        ),
        well_plate=_Plate(),
    )
    controller.check_if_all_completed = lambda: True
    controller._configuration_capture_readiness = lambda: {
        "ready": True,
        "trust_epoch": 7,
    }
    candidate = {"source_event_id": "event-1"}
    controller.controlled_calibration_promotion_candidates = lambda: {
        f"plate:{PLATE_NAME}": candidate
    }
    monkeypatch.setattr(
        controller_module,
        "read_governed_documents",
        lambda _paths: {"Plates.json": []},
    )

    result = controller.plate_calibration_entry_preflight()

    assert result["allowed"] is True
    assert result["verified"] is False
    assert result["historical_candidate"] == candidate


def test_non_session_motion_is_blocked_while_calibration_is_active():
    controller = Controller.__new__(Controller)
    controller._plate_calibration_session = {
        "session_token": "active",
        "state": "manual_first_point",
    }
    controller.error_occurred_signal = _Signal()

    result = Controller.set_absolute_Z(controller, 1234)

    assert result is False
    assert controller.error_occurred_signal.calls == [
        (
            "Plate Calibration Active",
            "Other motion is blocked while the guarded plate-calibration session is active.",
        )
    ]


def test_first_capture_predicts_xyz_and_lifts_before_next_corner_xy():
    controller, calls = _route_controller(verified=False)
    controller._plate_calibration_session = {
        **_entry_preflight(verified=False),
        "session_token": "session",
        "state": "manual_first_point",
        "phase": "entry",
        "captured_points": {},
        "next_point_index": 0,
        "expected_point": "top_left",
        "initial_value_sha256": "a" * 64,
    }
    controller._plate_calibration_session_invariants = lambda _session: (True, "")
    controller.check_if_all_completed = lambda: True
    captured = {"X": 43800, "Y": 13350, "Z": 84350}
    controller.capture_configuration_point = lambda *_args, **_kwargs: copy.deepcopy(
        captured
    )
    controller.expected_position = copy.deepcopy(captured)

    result = controller.capture_and_advance_plate_calibration(
        "session", "top_left"
    )

    assert result is True
    assert controller.model.well_plate.temp_calibration_data["top_left"] == captured
    assert [(call[0], *call[1:-1]) for call in calls] == [
        ("Z", 83850),
        ("XY", 43800, 29874),
        ("Z", 84350),
    ]
    session = controller._plate_calibration_session
    assert session["expected_point"] == "top_right"
    assert session["expected_endpoint"] == {
        "X": 43800,
        "Y": 29874,
        "Z": 84350,
    }


def test_interruption_discards_partial_capture_and_stale_callback_cannot_resume():
    controller, calls = _route_controller(verified=False)
    controller.begin_plate_calibration_entry(manual_first=True)
    token = controller._plate_calibration_session["session_token"]
    stale_callback = calls[-1][-1]["handler"]
    controller.model.well_plate.temp_calibration_data["top_left"] = {
        "X": 1,
        "Y": 2,
        "Z": 3,
    }

    controller._on_plate_calibration_workflow_interrupted(
        {"reason": "queue_cleared"}
    )

    assert controller._plate_calibration_session["state"] == "failed"
    assert controller.model.well_plate.temp_calibration_data == {}
    assert stale_callback() is False
    assert controller._plate_calibration_session["session_token"] == token
    assert controller._plate_calibration_session["state"] == "failed"


def test_back_discards_target_and_later_captures_before_recalculation():
    controller, calls = _route_controller(verified=True)
    captures = {
        "top_left": {"X": 43800, "Y": 13350, "Z": 84350},
        "top_right": {"X": 43800, "Y": 29874, "Z": 84350},
        "bottom_right": {"X": 33050, "Y": 29874, "Z": 84350},
    }
    controller._plate_calibration_session = {
        **_entry_preflight(verified=True),
        "session_token": "session",
        "state": "automatic_points",
        "manual_first": False,
        "captured_points": copy.deepcopy(captures),
        "next_point_index": 3,
        "expected_point": "bottom_left",
    }
    controller.model.well_plate.temp_calibration_data = copy.deepcopy(captures)
    controller._configuration_capture_evidence = {
        ("plate_calibration", name): {"ready": True}
        for name in captures
    }
    controller._plate_calibration_session_invariants = lambda _session: (True, "")
    controller.check_if_all_completed = lambda: True
    controller.expected_position = {"X": 33050, "Y": 13350, "Z": 84350}

    result = controller.move_plate_calibration_to_captured_point(
        "session", "top_right"
    )

    assert result is True
    assert set(controller._plate_calibration_session["captured_points"]) == {
        "top_left"
    }
    assert set(controller.model.well_plate.temp_calibration_data) == {"top_left"}
    assert set(controller._configuration_capture_evidence) == {
        ("plate_calibration", "top_left")
    }
    assert [(call[0], *call[1:-1]) for call in calls] == [
        ("Z", 83850),
        ("XY", 43800, 29874),
        ("Z", 84350),
    ]


def test_cancelled_ready_session_cannot_be_reused_for_jog_or_capture():
    controller, _calls = _route_controller(verified=False)
    controller._plate_calibration_session = {
        **_entry_preflight(verified=False),
        "session_token": "session",
        "state": "manual_first_point",
        "captured_points": {},
    }
    controller.model.well_plate.temp_calibration_data["top_left"] = {
        "X": 1,
        "Y": 2,
        "Z": 3,
    }

    assert controller.cancel_plate_calibration_entry("session") is True

    assert controller._plate_calibration_session is None
    assert controller.model.well_plate.temp_calibration_data == {}
    assert controller.jog_plate_calibration("session", z=500) is False
    assert controller.capture_and_advance_plate_calibration(
        "session", "top_left"
    ) is False


def test_reconciliation_mismatch_fails_closed_without_enabling_capture():
    controller, _calls = _route_controller(verified=True)
    controller._plate_calibration_session = {
        **_entry_preflight(verified=True),
        "session_token": "session",
        "state": "reconciling",
        "phase": "entry",
        "expected_endpoint": copy.deepcopy(CALIBRATIONS["top_left"]),
        "awaiting_queue_drain": False,
    }
    controller._plate_calibration_session_invariants = lambda _session: (True, "")
    controller._advance_position_reconciliation = lambda **_kwargs: {
        "state": "mismatch"
    }

    snapshot = controller._advance_plate_calibration_session()

    assert snapshot["state"] == "failed"
    assert snapshot["failure_reason"] == "expected_position_mismatch"


def test_entry_becomes_manual_first_only_after_exact_reconciliation():
    controller, _calls = _route_controller(verified=False)
    endpoint = {"X": 43770, "Y": 13320, "Z": 500}
    controller._plate_calibration_session = {
        **_entry_preflight(verified=False),
        "session_token": "session",
        "state": "reconciling",
        "phase": "entry",
        "manual_first": True,
        "expected_endpoint": copy.deepcopy(endpoint),
        "awaiting_queue_drain": False,
    }
    controller._plate_calibration_session_invariants = lambda _session: (True, "")
    controller._advance_position_reconciliation = lambda **_kwargs: {
        "state": "settled",
        "expected_position": copy.deepcopy(endpoint),
    }
    controller._configuration_capture_readiness = lambda: {
        "ready": True,
        "captured_position": copy.deepcopy(endpoint),
    }

    snapshot = controller._advance_plate_calibration_session()

    assert snapshot["state"] == "manual_first_point"
    assert controller.expected_location == "plate"


def test_reconciliation_timeout_and_trust_change_both_fail_closed():
    for reconciliation, invariant_result, expected_reason in (
        ({"state": "timed_out"}, (True, ""), "position_reconciliation_timeout"),
        (
            {"state": "pending"},
            (False, "motion_trust_epoch_changed"),
            "motion_trust_epoch_changed",
        ),
    ):
        controller, _calls = _route_controller(verified=True)
        controller._plate_calibration_session = {
            **_entry_preflight(verified=True),
            "session_token": "session",
            "state": "reconciling",
            "phase": "entry",
            "expected_endpoint": copy.deepcopy(CALIBRATIONS["top_left"]),
            "awaiting_queue_drain": False,
        }
        controller._plate_calibration_session_invariants = (
            lambda _session, result=invariant_result: result
        )
        controller._advance_position_reconciliation = (
            lambda **_kwargs: copy.deepcopy(reconciliation)
        )

        snapshot = controller._advance_plate_calibration_session()

        assert snapshot["state"] == "failed"
        assert snapshot["failure_reason"] == expected_reason
