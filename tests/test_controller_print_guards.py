from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

import pytest

from Controller import (
    ARRAY_AXIS_ACCEL_DEFAULT,
    ARRAY_PAUSE_DEPARTURE_ACCEL,
    ARRAY_PAUSE_DEPARTURE_SETTLE_MS,
    Controller,
)

ROW_START_OVERSHOOT_FOR_TEST = 200


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class FakeWell:
    def __init__(self, well_id, remaining, coords=None):
        self.well_id = well_id
        row = ''.join(ch for ch in self.well_id if ch.isalpha()).upper()
        col = ''.join(ch for ch in self.well_id if ch.isdigit())
        self.row = row
        self.col = int(col)
        row_num = 0
        for ch in row:
            row_num = row_num * 26 + (ord(ch) - ord('A') + 1)
        self.row_num = row_num - 1
        self.remaining = int(remaining)
        self.coords = coords or {"X": 1, "Y": 2, "Z": 3}
        self.record_calls = []

    def get_remaining_droplets(self, _stock_id):
        return self.remaining

    def get_coordinates(self):
        if isinstance(self.coords, dict):
            return dict(self.coords)
        return self.coords

    def record_stock_print(self, stock_id, droplets):
        droplets = int(droplets)
        self.record_calls.append((stock_id, droplets))
        self.remaining = max(0, self.remaining - droplets)


class FakeWellPlate:
    def __init__(self, wells, calibration_ok=True):
        self.wells = {well.well_id: well for well in wells}
        self._calibration_ok = bool(calibration_ok)

    def check_calibration_applied(self):
        return self._calibration_ok

    def get_all_wells_with_reactions(self, fill_by="rows", serpentine=True):
        assert fill_by == "rows"
        wells = list(self.wells.values())
        if serpentine:
            return sorted(
                wells,
                key=lambda well: (
                    well.row_num,
                    well.col if well.row_num % 2 == 0 else -well.col,
                ),
            )
        return sorted(wells, key=lambda well: (well.row_num, well.col))

    def get_well(self, well_id):
        return self.wells.get(well_id)


def _make_printer_head(stock_id="stock-a", calibration_complete=False, current_volume=20.0, droplet_volume=1000.0):
    return SimpleNamespace(
        get_stock_id=lambda: stock_id,
        check_calibration_complete=lambda: calibration_complete,
        get_current_volume=lambda: current_volume,
        get_target_droplet_volume=lambda: droplet_volume,
        record_droplet_volume_lost=Mock(),
    )


def _make_controller(
    *,
    well_plate,
    printer_head,
    regulation_on=True,
    gripper_info=object(),
    queue_empty=True,
    initial_state="idle",
    current_accels=None,
    profile_name="default",
    imaging_guard_ok=True,
    imaging_guard_message="Applied imaging calibration is required.",
    imaging_guard_code=None,
    imaging_guard_record=None,
    refuel_guard_ok=True,
    refuel_guard_message="Manual refuel check is required.",
    refuel_guard_code=None,
    refuel_guard_record=None,
    progress_status=None,
    reset_dock_required=False,
):
    c = Controller.__new__(Controller)
    c.array_complete = Emitter()
    c.array_state_changed = Emitter()
    c.update_slots_signal = Emitter()
    c.error_occurred_signal = Emitter()
    c._array_state = initial_state
    c._array_context = None
    c.profile = SimpleNamespace(name=profile_name)

    seq_counter = {"value": 100}
    command_events = []

    def _fake_print_droplets(*args, **kwargs):
        seq_counter["value"] += 1
        return SimpleNamespace(command_number=seq_counter["value"])

    def _fake_set_axis_accel(_axis_idx, _accel, handler=None, kwargs=None, manual=False):
        command_events.append(("set_axis_accel", _axis_idx, _accel))
        seq_counter["value"] += 1
        if callable(handler):
            handler(**(kwargs or {}))
        return SimpleNamespace(command_number=seq_counter["value"])

    def _fake_resume_commands():
        command_events.append(("resume_commands",))

    def _fake_move_to_location(*args, **kwargs):
        command_events.append(("move_to_location", args, kwargs))
        return True

    if current_accels is None:
        current_accels = (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)

    c.command_events = command_events
    c.close_gripper = Mock()
    c.move_to_location = Mock(side_effect=_fake_move_to_location)
    c.enable_print_profile = Mock()
    c.disable_print_profile = Mock()
    c.set_absolute_coordinates = Mock(return_value=True)
    c.print_droplets = Mock(side_effect=_fake_print_droplets)
    c.update_expected_with_current = Mock()

    c.machine = SimpleNamespace(
        check_if_all_completed=lambda: queue_empty,
        clear_command_queue=Mock(),
        pause_commands=Mock(),
        resume_commands=Mock(side_effect=_fake_resume_commands),
        request_pause_after_seq32=Mock(return_value=True),
        set_axis_accel=Mock(side_effect=_fake_set_axis_accel),
        set_print_pulse_width=Mock(return_value=SimpleNamespace(command_number=201)),
        set_absolute_print_pressure=Mock(return_value=SimpleNamespace(command_number=202)),
        wait_ms=Mock(),
    )
    if imaging_guard_code is None:
        imaging_guard_code = "ok" if imaging_guard_ok else "missing_record"
    if imaging_guard_record is None and imaging_guard_ok:
        imaging_guard_record = {"run_id": "run-1", "pw_us": 1400, "pressure_psi": 1.20}
    if refuel_guard_code is None:
        refuel_guard_code = "passed_refuel_check" if refuel_guard_ok else "required_refuel_check"
    if refuel_guard_record is None and refuel_guard_ok:
        refuel_guard_record = {"status": "passed"}
    if progress_status is None:
        progress_status = {"has_printed_progress": True}
    c.model = SimpleNamespace(
        well_plate=well_plate,
        update_state=Mock(side_effect=lambda status: None),
        rack_model=SimpleNamespace(
            get_gripper_info=lambda: gripper_info,
            get_gripper_printer_head=Mock(return_value=printer_head),
            gripper_printer_head=printer_head,
        ),
        machine_model=SimpleNamespace(
            regulating_print_pressure=regulation_on,
            clear_command_queue=Mock(),
            get_current_accelerations=lambda: current_accels,
            get_print_pulse_width=lambda: 1400,
            get_refuel_pulse_width=lambda: 2200,
            get_current_print_pressure=lambda: 1.20,
            get_target_print_pressure=lambda: 1.20,
            get_current_refuel_pressure=lambda: 0.30,
            get_target_refuel_pressure=lambda: 0.30,
            transport_paused=False,
            pause_watermark_reached=False,
            pause_commands=Mock(),
            resume_commands=Mock(),
        ),
        experiment_model=SimpleNamespace(
            create_progress_file=Mock(),
            get_progress_status=Mock(return_value=progress_status),
            validate_applied_imaging_calibration_for_print=Mock(
                return_value={
                    "ok": bool(imaging_guard_ok),
                    "code": imaging_guard_code,
                    "message": "" if imaging_guard_ok else imaging_guard_message,
                    "record": imaging_guard_record,
                }
            ),
            validate_manual_refuel_check_for_print=Mock(
                return_value={
                    "ok": bool(refuel_guard_ok),
                    "code": refuel_guard_code,
                    "message": "" if refuel_guard_ok else refuel_guard_message,
                    "record": refuel_guard_record,
                }
            ),
            record_manual_refuel_check_outcome=Mock(
                return_value={"status": "passed", "source": "manual_dialog"}
            ),
        ),
    )
    dock_reasons = {"after_board_reset"} if reset_dock_required else set()
    c.model.machine_model._evap_plate_dock_check_reasons = dock_reasons
    c.model.machine_model.evap_plate_dock_check_required_after_reset = bool(reset_dock_required)

    def _mark_dock_check(reason):
        dock_reasons.add(str(reason))

    def _clear_dock_checks():
        dock_reasons.clear()
        c.model.machine_model.evap_plate_dock_check_required_after_reset = False

    def _clear_reset_dock_check():
        dock_reasons.discard("after_board_reset")
        c.model.machine_model.evap_plate_dock_check_required_after_reset = False

    c.model.machine_model.mark_evap_plate_dock_check_required = _mark_dock_check
    c.model.machine_model.get_evap_plate_dock_check_reasons = lambda: sorted(dock_reasons)
    c.model.machine_model.clear_evap_plate_dock_check_required = _clear_dock_checks
    c.model.machine_model.clear_evap_plate_dock_check_required_after_reset = _clear_reset_dock_check
    return c


def _parking_move_side_effect(*args, on_complete=None, **kwargs):
    if callable(on_complete):
        on_complete()
    return True


def _with_lowered_array_accels(context, restore_accels=None):
    if restore_accels is None:
        restore_accels = (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)
    context.update(
        {
            "pause_departure_restore_accels": restore_accels,
            "gentle_accel_enabled": True,
            "array_accels_lowered": True,
            "array_accels_restored": False,
        }
    )
    return context


def test_authoritative_array_queue_persists_intent_before_dispense_command():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    events = []
    em = c.model.experiment_model
    em.uses_durable_execution_checkpoint = Mock(return_value=True)
    em.begin_execution_print_intent = Mock(
        side_effect=lambda **kwargs: events.append(("intent", kwargs)) or "intent-1"
    )
    em.attach_execution_print_command = Mock(
        side_effect=lambda intent_id, seq: events.append(("attach", intent_id, seq))
    )
    original_print = c.print_droplets.side_effect
    c.print_droplets.side_effect = (
        lambda *args, **kwargs: events.append(("dispense", args[0]))
        or original_print(*args, **kwargs)
    )
    assert Controller._start_array_run_context(c)

    assert Controller._queue_next_array_well(c)

    assert [event[0] for event in events] == ["intent", "dispense", "attach"]
    assert c.print_droplets.call_args.kwargs["kwargs"]["execution_intent_id"] == "intent-1"


def test_authoritative_progress_completes_intent_only_after_progress_write():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    events = []
    em = c.model.experiment_model
    em.create_progress_file.side_effect = lambda: events.append("progress")
    em.complete_execution_print_intent = Mock(
        side_effect=lambda intent_id: events.append(("complete", intent_id))
    )

    Controller._record_array_progress(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        execution_intent_id="intent-1",
    )

    assert events == ["progress", ("complete", "intent-1")]


def test_authoritative_intent_write_failure_prevents_dispense_queueing():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    em = c.model.experiment_model
    em.uses_durable_execution_checkpoint = Mock(return_value=True)
    em.begin_execution_print_intent = Mock(side_effect=OSError("checkpoint unavailable"))
    em.set_execution_plan_sync_error = Mock()
    assert Controller._start_array_run_context(c)

    assert Controller._queue_next_array_well(c) is False

    c.print_droplets.assert_not_called()
    em.set_execution_plan_sync_error.assert_called_once()
    assert "checkpoint unavailable" in c.error_occurred_signal.calls[-1][1]


def _restore_calls(restore_accels=None):
    if restore_accels is None:
        restore_accels = (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)
    return [
        call(0, restore_accels[0]),
        call(1, restore_accels[1]),
        call(2, restore_accels[2], handler=ANY),
    ]


def test_evap_plate_dock_context_requires_first_experiment_start_not_resume():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        progress_status={"has_printed_progress": False},
    )

    start_context = Controller.get_evap_plate_dock_check_context(c, request_kind="start")
    resume_context = Controller.get_evap_plate_dock_check_context(c, request_kind="resume")

    assert start_context["required"] is True
    assert start_context["reasons"] == ["first_experiment_print"]
    assert resume_context["required"] is False
    assert resume_context["reasons"] == []


def test_evap_plate_dock_context_requires_after_board_reset_for_start_and_resume():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        reset_dock_required=True,
    )

    start_context = Controller.get_evap_plate_dock_check_context(c, request_kind="start")
    resume_context = Controller.get_evap_plate_dock_check_context(c, request_kind="resume")

    assert "after_board_reset" in start_context["reasons"]
    assert start_context["required"] is True
    assert resume_context["reasons"] == ["after_board_reset"]
    assert resume_context["required"] is True


def test_evap_plate_dock_context_includes_persistent_reasons_for_start_and_resume():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.machine_model.mark_evap_plate_dock_check_required("transport_fault")
    c.model.machine_model.mark_evap_plate_dock_check_required("array_hard_abort")

    start_context = Controller.get_evap_plate_dock_check_context(c, request_kind="start")
    resume_context = Controller.get_evap_plate_dock_check_context(c, request_kind="resume")

    assert start_context["reasons"] == ["array_hard_abort", "transport_fault"]
    assert resume_context["reasons"] == ["array_hard_abort", "transport_fault"]
    assert start_context["required"] is True
    assert resume_context["required"] is True
    assert "aborted" in start_context["message"]
    assert "transport fault" in start_context["message"]


def test_in_place_pause_resume_does_not_latch_dock_check_or_move():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    Controller.pause_commands(c)
    Controller.resume_commands(c)

    c.machine.pause_commands.assert_called_once_with()
    c.model.machine_model.pause_commands.assert_called_once_with()
    c.machine.resume_commands.assert_called_once_with()
    c.model.machine_model.resume_commands.assert_called_once_with()
    assert c.get_array_run_state() == "running"
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == []
    c.move_to_location.assert_not_called()
    c.model.experiment_model.get_progress_status.assert_not_called()


def test_print_array_blocks_when_evap_plate_dock_confirmation_required():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        progress_status={"has_printed_progress": False},
    )

    Controller.print_array(c)

    assert c.error_occurred_signal.calls[-1][0] == "Evaporation Plate Dock Check Required"
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()
    c.set_absolute_coordinates.assert_not_called()
    assert c.get_array_run_state() == "idle"


def test_print_array_confirmed_after_reset_clears_reset_dock_latch():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        reset_dock_required=True,
    )

    Controller.print_array(c, evap_plate_dock_confirmed=True)

    assert c.model.machine_model.evap_plate_dock_check_required_after_reset is False
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == []
    c.close_gripper.assert_called_once_with()
    assert c.get_array_run_state() == "running"


def test_print_array_confirmed_start_clears_all_persistent_dock_reasons():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.machine_model.mark_evap_plate_dock_check_required("array_hard_abort")
    c.model.machine_model.mark_evap_plate_dock_check_required("transport_fault")

    Controller.print_array(c, evap_plate_dock_confirmed=True)

    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == []
    assert c.get_array_run_state() == "running"


def test_print_array_preflight_failure_preserves_persistent_dock_reasons():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)], calibration_ok=False),
        printer_head=_make_printer_head(),
    )
    c.model.machine_model.mark_evap_plate_dock_check_required("array_hard_abort")

    Controller.print_array(c, evap_plate_dock_confirmed=True)

    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == ["array_hard_abort"]
    c.close_gripper.assert_not_called()


def test_print_array_empty_run_context_preserves_persistent_dock_reasons():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 0)]),
        printer_head=_make_printer_head(),
    )
    c.model.machine_model.mark_evap_plate_dock_check_required("array_hard_abort")

    Controller.print_array(c, evap_plate_dock_confirmed=True)

    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == ["array_hard_abort"]
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_plate_not_calibrated():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)], calibration_ok=False),
        printer_head=_make_printer_head(),
    )
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "Calibration has not been applied to this plate"
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_no_printer_head_loaded():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        gripper_info=None,
    )
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "No printer head is loaded"
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_regulation_disabled():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        regulation_on=False,
    )
    Controller.print_array(c)
    assert c.error_occurred_signal.calls[0][1] == "Pressure regulation is not enabled"
    c.close_gripper.assert_not_called()


def test_print_array_blocks_when_applied_imaging_calibration_missing():
    message = "No applied imaging calibration was found for the loaded stock/head."
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        imaging_guard_ok=False,
        imaging_guard_message=message,
        imaging_guard_code="missing_record",
    )

    Controller.print_array(c)

    c.model.experiment_model.validate_applied_imaging_calibration_for_print.assert_called_once_with(
        printer_head=c.model.rack_model.gripper_printer_head,
        machine_model=c.model.machine_model,
    )
    assert c.error_occurred_signal.calls[0][1] == message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_allows_missing_applied_calibration_with_explicit_override():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        imaging_guard_ok=False,
        imaging_guard_message="No applied imaging calibration was found.",
        imaging_guard_code="missing_record",
    )

    Controller.print_array(c, imaging_calibration_override=True)

    c.close_gripper.assert_called_once_with()
    assert c.error_occurred_signal.calls == []


def test_print_array_blocks_settings_mismatch_without_override():
    message = "Print pulse width does not match the applied imaging calibration."
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        imaging_guard_ok=False,
        imaging_guard_message=message,
        imaging_guard_code="pulse_width_mismatch",
        imaging_guard_record={"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35},
    )

    Controller.print_array(c)

    assert c.error_occurred_signal.calls[0][1] == message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_allows_settings_mismatch_with_explicit_override():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        imaging_guard_ok=False,
        imaging_guard_message="Print pressure does not match the applied imaging calibration.",
        imaging_guard_code="pressure_mismatch",
        imaging_guard_record={"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35},
    )

    Controller.print_array(c, settings_mismatch_override=True)

    c.close_gripper.assert_called_once_with()
    assert c.error_occurred_signal.calls == []


@pytest.mark.parametrize(
    "code",
    [
        "required_refuel_check",
        "missing_refuel_check",
        "stale_refuel_check",
    ],
)
def test_print_array_blocks_refuel_check_failures_without_bypass(code):
    message = "Manual refuel check is required before stream printing."
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        refuel_guard_ok=False,
        refuel_guard_code=code,
        refuel_guard_message=message,
    )

    Controller.print_array(c)

    assert c.error_occurred_signal.calls[0][1] == message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


@pytest.mark.parametrize(
    ("ok", "code", "record"),
    [
        (True, "passed_refuel_check", {"status": "passed"}),
        (True, "not_required", None),
    ],
)
def test_print_array_allows_passed_or_not_required_refuel_check(ok, code, record):
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        refuel_guard_ok=ok,
        refuel_guard_code=code,
        refuel_guard_record=record,
    )

    Controller.print_array(c)

    c.close_gripper.assert_called_once_with()
    assert c.error_occurred_signal.calls == []


@pytest.mark.parametrize(
    "code",
    [
        "required_refuel_check",
        "missing_refuel_check",
        "deferred_refuel_check",
        "failed_refuel_check",
        "unclear_refuel_check",
        "bypassed_refuel_check",
        "stale_refuel_check",
        "settings_unavailable",
        "print_pulse_width_mismatch",
        "refuel_pulse_width_mismatch",
        "print_pressure_mismatch",
        "refuel_pressure_mismatch",
    ],
)
def test_print_array_allows_promptable_refuel_check_failure_with_explicit_bypass(code):
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        refuel_guard_ok=False,
        refuel_guard_code=code,
        refuel_guard_message="Manual refuel check is not passed.",
    )

    Controller.print_array(c, manual_refuel_check_bypass=True)

    c.close_gripper.assert_called_once_with()
    assert c.error_occurred_signal.calls == []


@pytest.mark.parametrize("code", ["context_unavailable", "validation_unavailable"])
def test_print_array_refuel_context_failures_block_even_with_bypass(code):
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        refuel_guard_ok=False,
        refuel_guard_code=code,
        refuel_guard_message="Manual refuel check context is unavailable.",
    )

    Controller.print_array(c, manual_refuel_check_bypass=True)

    assert c.error_occurred_signal.calls[0][1] == "Manual refuel check context is unavailable."
    c.close_gripper.assert_not_called()


def test_apply_applied_imaging_calibration_print_settings_only_sets_parameters():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )

    result = Controller.apply_applied_imaging_calibration_print_settings(
        c,
        {"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35},
    )

    assert result["ok"] is True
    c.machine.set_print_pulse_width.assert_called_once()
    assert c.machine.set_print_pulse_width.call_args.args[0] == 1450
    c.machine.set_absolute_print_pressure.assert_called_once()
    assert c.machine.set_absolute_print_pressure.call_args.args[0] == 1.35
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_refuel_check_preflight_delegates_with_loaded_head_and_machine_model():
    printer_head = _make_printer_head()
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=printer_head,
    )

    result = Controller.get_print_array_refuel_check_preflight(c)

    assert result["ok"] is True
    c.model.experiment_model.validate_manual_refuel_check_for_print.assert_called_once_with(
        printer_head=printer_head,
        machine_model=c.model.machine_model,
    )


def test_refuel_check_preflight_reports_missing_head():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=None,
    )

    result = Controller.get_print_array_refuel_check_preflight(c)

    assert result["ok"] is False
    assert result["code"] == "context_unavailable"
    c.model.experiment_model.validate_manual_refuel_check_for_print.assert_not_called()


def test_refuel_check_preflight_is_not_required_for_legacy_profile():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        profile_name="legacy",
    )

    result = Controller.get_print_array_refuel_check_preflight(c)

    assert result["ok"] is True
    assert result["code"] == "not_required"
    c.model.experiment_model.validate_manual_refuel_check_for_print.assert_not_called()


def test_record_manual_refuel_check_outcome_passes_loaded_head_and_machine_model():
    printer_head = _make_printer_head()
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=printer_head,
    )
    c.model.experiment_model.record_manual_refuel_check_outcome.return_value = {
        "status": "passed",
        "trial_count": 2,
    }

    result = Controller.record_manual_refuel_check_outcome(
        c,
        "passed",
        "manual_dialog",
        trial_count=2,
    )

    assert result["status"] == "passed"
    c.model.experiment_model.record_manual_refuel_check_outcome.assert_called_once_with(
        status="passed",
        source="manual_dialog",
        printer_head=printer_head,
        machine_model=c.model.machine_model,
        trial_count=2,
    )


def test_refuel_check_deferred_and_bypass_helpers_record_expected_statuses():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )

    Controller.mark_manual_refuel_check_deferred(c)
    Controller.record_manual_refuel_check_bypass(c, reason="operator_confirmed")

    assert c.model.experiment_model.record_manual_refuel_check_outcome.call_args_list == [
        call(
            status="deferred",
            source="post_apply_prompt",
            printer_head=c.model.rack_model.gripper_printer_head,
            machine_model=c.model.machine_model,
        ),
        call(
            status="bypassed",
            source="print_array_preflight",
            printer_head=c.model.rack_model.gripper_printer_head,
            machine_model=c.model.machine_model,
            bypass_reason="operator_confirmed",
        ),
    ]


@pytest.mark.parametrize(
    "message",
    [
        "Loaded printer head does not match the applied imaging calibration.",
        "Loaded stock does not match the applied imaging calibration.",
        "Print pulse width does not match the applied imaging calibration.",
        "Target print pressure does not match the applied imaging calibration.",
        "Applied imaging calibration is stale for the current design.",
    ],
)
def test_print_array_blocks_when_applied_imaging_guard_reports_mismatch(message):
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        imaging_guard_ok=False,
        imaging_guard_message=message,
        imaging_guard_code="validation_failed",
    )

    Controller.print_array(c)

    assert c.error_occurred_signal.calls[0][1] == message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_skips_applied_imaging_guard_for_legacy_profile():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        profile_name="legacy",
        imaging_guard_ok=False,
    )

    Controller.print_array(c)

    c.model.experiment_model.validate_applied_imaging_calibration_for_print.assert_not_called()
    c.model.experiment_model.validate_manual_refuel_check_for_print.assert_not_called()
    c.close_gripper.assert_called_once_with()


def test_print_array_prefetches_one_lookahead_well():
    first = FakeWell("A1", 5, {"X": 10, "Y": 20, "Z": 30})
    second = FakeWell("A2", 7, {"X": 40, "Y": 50, "Z": 60})
    c = _make_controller(
        well_plate=FakeWellPlate([first, second]),
        printer_head=_make_printer_head(),
    )

    Controller.print_array(c)

    c.close_gripper.assert_called_once_with()
    assert c.move_to_location.call_args_list[:2] == [
        call("pause", z_offset=-5000),
        call("pause", ignore_safe_height=True),
    ]
    c.enable_print_profile.assert_called_once_with()
    assert c.command_events == [
        ("move_to_location", ("pause",), {"z_offset": -5000}),
        ("move_to_location", ("pause",), {"ignore_safe_height": True}),
    ]
    assert c.set_absolute_coordinates.call_args_list == [
        call(10, 20, 30, override=True),
        call(40, 50, 60, override=True),
    ]
    assert c.print_droplets.call_count == 2
    assert c.print_droplets.call_args_list[0].args[0] == 5
    assert c.print_droplets.call_args_list[1].args[0] == 7
    assert c.print_droplets.call_args_list[0].kwargs["handler"] == c._handle_array_well_complete
    c.machine.set_axis_accel.assert_not_called()
    c.machine.wait_ms.assert_called_once_with(ARRAY_PAUSE_DEPARTURE_SETTLE_MS)
    assert c._array_context["stock_id"] == "stock-a"
    assert [item["well_id"] for item in c._array_context["queued_wells"]] == ["A1", "A2"]
    assert c._array_context["pause_departure_pending"] is False
    assert c.get_array_run_state() == "running"


def test_print_array_uses_serpentine_order_by_default():
    a1 = FakeWell("A1", 1, {"X": 10, "Y": 0, "Z": 30})
    a2 = FakeWell("A2", 1, {"X": 20, "Y": 0, "Z": 30})
    b1 = FakeWell("B1", 1, {"X": 10, "Y": 10, "Z": 30})
    b2 = FakeWell("B2", 1, {"X": 20, "Y": 10, "Z": 30})
    c = _make_controller(
        well_plate=FakeWellPlate([a1, a2, b2, b1]),
        printer_head=_make_printer_head(),
    )
    c._array_row_start_overshoot_steps = 0

    Controller.print_array(c)
    Controller._handle_array_well_complete(c, well_id="A1", stock_id="stock-a", target_droplets=1)
    Controller._handle_array_well_complete(c, well_id="A2", stock_id="stock-a", target_droplets=1)

    assert c.set_absolute_coordinates.call_args_list == [
        call(10, 0, 30, override=True),
        call(20, 0, 30, override=True),
        call(20, 10, 30, override=True),
        call(10, 10, 30, override=True),
    ]
    assert [call.kwargs["kwargs"]["well_id"] for call in c.print_droplets.call_args_list] == [
        "A1",
        "A2",
        "B2",
        "B1",
    ]


def test_print_array_can_use_row_major_order_when_serpentine_disabled():
    a1 = FakeWell("A1", 1, {"X": 10, "Y": 0, "Z": 30})
    a2 = FakeWell("A2", 1, {"X": 20, "Y": 0, "Z": 30})
    b1 = FakeWell("B1", 1, {"X": 10, "Y": 10, "Z": 30})
    b2 = FakeWell("B2", 1, {"X": 20, "Y": 10, "Z": 30})
    c = _make_controller(
        well_plate=FakeWellPlate([a1, a2, b2, b1]),
        printer_head=_make_printer_head(),
    )
    c._array_print_serpentine = False
    c._array_row_start_overshoot_steps = 0

    Controller.print_array(c)
    Controller._handle_array_well_complete(c, well_id="A1", stock_id="stock-a", target_droplets=1)
    Controller._handle_array_well_complete(c, well_id="A2", stock_id="stock-a", target_droplets=1)

    assert c.set_absolute_coordinates.call_args_list == [
        call(10, 0, 30, override=True),
        call(20, 0, 30, override=True),
        call(10, 10, 30, override=True),
        call(20, 10, 30, override=True),
    ]
    assert [call.kwargs["kwargs"]["well_id"] for call in c.print_droplets.call_args_list] == [
        "A1",
        "A2",
        "B1",
        "B2",
    ]


def test_print_array_overshoots_first_well_of_next_row_when_enabled():
    a2 = FakeWell("A2", 1, {"X": 20, "Y": 0, "Z": 30})
    b1 = FakeWell("B1", 1, {"X": 0, "Y": 10, "Z": 40})
    b2 = FakeWell("B2", 0, {"X": 10, "Y": 10, "Z": 40})
    c = _make_controller(
        well_plate=FakeWellPlate([a2, b1, b2]),
        printer_head=_make_printer_head(),
    )
    c._array_print_serpentine = False
    c._array_row_start_overshoot_steps = ROW_START_OVERSHOOT_FOR_TEST

    Controller.print_array(c)

    assert c.set_absolute_coordinates.call_args_list == [
        call(20, 0, 30, override=True),
        call(-ROW_START_OVERSHOOT_FOR_TEST, 10, 40, override=True),
        call(0, 10, 40, override=True),
    ]
    assert [call.kwargs["kwargs"]["well_id"] for call in c.print_droplets.call_args_list] == ["A2", "B1"]


def test_print_array_skips_row_overshoot_when_neighbor_coordinates_are_invalid():
    a2 = FakeWell("A2", 1, {"X": 20, "Y": 0, "Z": 30})
    b1 = FakeWell("B1", 1, {"X": 0, "Y": 10, "Z": 40})
    b2 = FakeWell("B2", 0, "bad-coordinates")
    c = _make_controller(
        well_plate=FakeWellPlate([a2, b1, b2]),
        printer_head=_make_printer_head(),
    )
    c._array_print_serpentine = False
    c._array_row_start_overshoot_steps = ROW_START_OVERSHOOT_FOR_TEST

    Controller.print_array(c)

    assert c.set_absolute_coordinates.call_args_list == [
        call(20, 0, 30, override=True),
        call(0, 10, 40, override=True),
    ]
    assert [call.kwargs["kwargs"]["well_id"] for call in c.print_droplets.call_args_list] == ["A2", "B1"]


def test_print_array_resume_ready_starts_next_incomplete_well():
    completed = FakeWell("A1", 0, {"X": 10, "Y": 20, "Z": 30})
    remaining = FakeWell("A2", 7, {"X": 40, "Y": 50, "Z": 60})
    c = _make_controller(
        well_plate=FakeWellPlate([completed, remaining]),
        printer_head=_make_printer_head(),
        initial_state="resume_ready",
    )

    Controller.print_array(c)

    c.set_absolute_coordinates.assert_called_once_with(40, 50, 60, override=True)
    c.machine.set_axis_accel.assert_not_called()
    c.machine.wait_ms.assert_called_once_with(ARRAY_PAUSE_DEPARTURE_SETTLE_MS)
    assert c.print_droplets.call_args.args[0] == 7
    assert c.get_array_run_state() == "running"


def test_print_array_does_not_change_accels_by_default_on_completion():
    last = FakeWell("A1", 5, {"X": 10, "Y": 20, "Z": 30})
    c = _make_controller(
        well_plate=FakeWellPlate([last]),
        printer_head=_make_printer_head(),
    )
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)

    Controller.print_array(c)
    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=False,
    )

    c.machine.set_axis_accel.assert_not_called()
    assert c.get_array_run_state() == "idle"
    assert c.array_complete.calls == [()]


def test_print_array_restores_captured_custom_accels_on_completion_when_gentle_accel_enabled():
    custom_accels = (50000, 60000, 70000)
    last = FakeWell("A1", 5, {"X": 10, "Y": 20, "Z": 30})
    c = _make_controller(
        well_plate=FakeWellPlate([last]),
        printer_head=_make_printer_head(),
        current_accels=custom_accels,
    )
    c._array_gentle_accel_enabled = True
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)

    Controller.print_array(c)
    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=False,
    )

    assert c.machine.set_axis_accel.call_args_list == [
        call(0, ARRAY_PAUSE_DEPARTURE_ACCEL),
        call(1, ARRAY_PAUSE_DEPARTURE_ACCEL),
        call(2, ARRAY_PAUSE_DEPARTURE_ACCEL),
        *_restore_calls(custom_accels),
    ]
    assert c.get_array_run_state() == "idle"
    assert c.array_complete.calls == [()]


def test_print_array_resume_ready_reapplies_and_restores_array_accels():
    completed = FakeWell("A1", 0, {"X": 10, "Y": 20, "Z": 30})
    remaining = FakeWell("A2", 7, {"X": 40, "Y": 50, "Z": 60})
    c = _make_controller(
        well_plate=FakeWellPlate([completed, remaining]),
        printer_head=_make_printer_head(),
        initial_state="resume_ready",
    )
    c._array_gentle_accel_enabled = True
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)

    Controller.print_array(c)
    Controller._handle_array_well_complete(
        c,
        well_id="A2",
        stock_id="stock-a",
        target_droplets=7,
        update_volume=False,
    )

    assert c.machine.set_axis_accel.call_args_list == [
        call(0, ARRAY_PAUSE_DEPARTURE_ACCEL),
        call(1, ARRAY_PAUSE_DEPARTURE_ACCEL),
        call(2, ARRAY_PAUSE_DEPARTURE_ACCEL),
        *_restore_calls(),
    ]
    assert c.get_array_run_state() == "idle"


def test_print_array_resume_ready_resumes_transport_before_queueing():
    completed = FakeWell("A1", 0, {"X": 10, "Y": 20, "Z": 30})
    remaining = FakeWell("A2", 7, {"X": 40, "Y": 50, "Z": 60})
    c = _make_controller(
        well_plate=FakeWellPlate([completed, remaining]),
        printer_head=_make_printer_head(),
        initial_state="resume_ready",
    )
    c.model.machine_model.transport_paused = True
    c.resume_commands = Mock()

    Controller.print_array(c)

    c.resume_commands.assert_called_once_with()
    c.set_absolute_coordinates.assert_called_once_with(40, 50, 60, override=True)


def test_request_array_soft_stop_sends_pause_after_current_barrier():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )
    c._array_context = {
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
        "current_barrier_seq32": None,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True
    assert c.get_array_run_state() == "stop_requested"
    assert c.array_state_changed.calls == [("stop_requested",)]
    assert c._array_context["soft_stop_phase"] == "waiting_watermark"
    c.machine.pause_commands.assert_not_called()
    args, kwargs = c.machine.request_pause_after_seq32.call_args
    assert args == (123,)
    assert callable(kwargs["on_failure"])


def test_request_array_soft_stop_watermark_rejection_retries_next_queued_well():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5), FakeWell("A2", 2)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _reject_first_pause_after(barrier, on_success=None, on_failure=None):
        if barrier == 123:
            on_failure(
                {
                    "reason": "ack_rejected",
                    "ack_result": "watermark_rejected",
                    "barrier_seq32": 123,
                }
            )
        return True

    c.machine.request_pause_after_seq32 = Mock(side_effect=_reject_first_pause_after)
    c._array_context = {
        "queued_wells": [
            {"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123},
            {"well_id": "A2", "target_droplets": 2, "dispense_seq32": 130},
        ],
        "current_barrier_seq32": 123,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True

    requested_barriers = [call_args.args[0] for call_args in c.machine.request_pause_after_seq32.call_args_list]
    assert requested_barriers == [123, 130]
    c.machine.clear_command_queue.assert_not_called()
    c.model.machine_model.clear_command_queue.assert_not_called()
    assert c.get_array_run_state() == "stop_requested"
    assert c._array_context["current_barrier_seq32"] == 130
    assert c._array_context["soft_stop_phase"] == "waiting_watermark"
    assert c._array_context["soft_stop_pending"] is True
    assert c._array_context["soft_stop_rejected_barriers"] == {123}
    assert c.error_occurred_signal.calls == []


def test_request_array_soft_stop_repeated_watermark_rejection_waits_for_completion_catchup():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5), FakeWell("A2", 2)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _reject_all_pause_after(barrier, on_success=None, on_failure=None):
        on_failure(
            {
                "reason": "ack_rejected",
                "ack_result": "watermark_rejected",
                "barrier_seq32": barrier,
            }
        )
        return True

    c.machine.request_pause_after_seq32 = Mock(side_effect=_reject_all_pause_after)
    c._array_context = {
        "queued_wells": [
            {"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123},
            {"well_id": "A2", "target_droplets": 2, "dispense_seq32": 130},
        ],
        "current_barrier_seq32": 123,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True

    requested_barriers = [call_args.args[0] for call_args in c.machine.request_pause_after_seq32.call_args_list]
    assert requested_barriers == [123, 130]
    c.machine.clear_command_queue.assert_not_called()
    assert c.get_array_run_state() == "stop_requested"
    assert c._array_context["current_barrier_seq32"] is None
    assert c._array_context["soft_stop_phase"] == "waiting_completion_catchup"
    assert c._array_context["soft_stop_pending"] is True
    assert c._array_context["soft_stop_rejected_barriers"] == {123, 130}
    assert c.error_occurred_signal.calls == []


def test_request_array_soft_stop_watermark_rejection_without_future_barrier_waits_for_completion_catchup():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5), FakeWell("A2", 2)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _reject_pause_after(_barrier, on_success=None, on_failure=None):
        on_failure(
            {
                "reason": "ack_rejected",
                "ack_result": "watermark_rejected",
                "barrier_seq32": 123,
            }
        )
        return True

    c.machine.request_pause_after_seq32 = Mock(side_effect=_reject_pause_after)
    c._array_context = {
        "stock_id": "stock-a",
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
        "current_barrier_seq32": 123,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True

    c.machine.clear_command_queue.assert_not_called()
    assert c.get_array_run_state() == "stop_requested"
    assert c._array_context["current_barrier_seq32"] is None
    assert c._array_context["soft_stop_phase"] == "waiting_completion_catchup"
    assert c._array_context["soft_stop_pending"] is True
    assert c.error_occurred_signal.calls == []


def test_request_array_soft_stop_write_failure_aborts_to_idle():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _fail_pause_after(_barrier, on_success=None, on_failure=None):
        assert on_success is None
        on_failure({"reason": "write_failed", "barrier_seq32": 123})
        return False

    c.machine.request_pause_after_seq32 = Mock(side_effect=_fail_pause_after)
    c._array_context = _with_lowered_array_accels(
        {
            "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
            "current_barrier_seq32": 123,
            "soft_stop_pending": False,
        }
    )

    assert Controller.request_array_soft_stop(c) is False
    c.machine.clear_command_queue.assert_called_once_with()
    c.model.machine_model.clear_command_queue.assert_called_once_with()
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    assert c.get_array_run_state() == "idle"
    assert c._array_context is None
    assert c.error_occurred_signal.calls[-1][0] == "Soft Stop Failed"
    assert "queued commands were cleared" in c.error_occurred_signal.calls[-1][1]


def test_request_array_soft_stop_ack_rejection_aborts_to_idle():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _reject_pause_after(_barrier, on_success=None, on_failure=None):
        on_failure({"reason": "ack_rejected", "barrier_seq32": 123})
        return True

    c.machine.request_pause_after_seq32 = Mock(side_effect=_reject_pause_after)
    c._array_context = {
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
        "current_barrier_seq32": 123,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True
    c.machine.clear_command_queue.assert_called_once_with()
    assert c.get_array_run_state() == "idle"
    assert c._array_context is None
    assert "MCU rejected" in c.error_occurred_signal.calls[-1][1]


def test_request_array_soft_stop_not_confirmed_aborts_to_idle():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )

    def _timeout_pause_after(_barrier, on_success=None, on_failure=None):
        on_failure({"reason": "not_confirmed", "barrier_seq32": 123})
        return True

    c.machine.request_pause_after_seq32 = Mock(side_effect=_timeout_pause_after)
    c._array_context = {
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
        "current_barrier_seq32": 123,
        "soft_stop_pending": False,
    }

    assert Controller.request_array_soft_stop(c) is True
    c.machine.clear_command_queue.assert_called_once_with()
    assert c.get_array_run_state() == "idle"
    assert c._array_context is None
    assert "not confirmed within the grace window" in c.error_occurred_signal.calls[-1][1]


def test_handle_array_well_complete_updates_progress_and_queues_next_well():
    first = FakeWell("A1", 5)
    second = FakeWell("A2", 3)
    printer_head = _make_printer_head(calibration_complete=True, current_volume=20.0, droplet_volume=1000.0)
    c = _make_controller(
        well_plate=FakeWellPlate([first, second]),
        printer_head=printer_head,
        initial_state="running",
    )
    c._array_context = {
        "stock_id": "stock-a",
        "expected_volume": 20.0,
        "update_volume": True,
        "droplet_volume": 1000.0,
        "finalize_reason": None,
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 101}],
        "planned_well_ids": {"A1"},
    }
    c._fill_array_lookahead = Mock()
    c._enqueue_array_finalize = Mock()

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=True,
    )

    assert first.record_calls == [("stock-a", 5)]
    printer_head.record_droplet_volume_lost.assert_called_once_with(5)
    c.model.experiment_model.create_progress_file.assert_called_once_with()
    assert c._array_context["expected_volume"] == 15.0
    c._fill_array_lookahead.assert_called_once_with()
    c._enqueue_array_finalize.assert_not_called()


def test_handle_array_well_complete_finalizes_completed_array():
    last = FakeWell("A1", 5)
    c = _make_controller(
        well_plate=FakeWellPlate([last]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )
    c._array_context = _with_lowered_array_accels(
        {
            "stock_id": "stock-a",
            "expected_volume": None,
            "update_volume": False,
            "droplet_volume": None,
            "finalize_reason": None,
            "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 101}],
            "planned_well_ids": {"A1"},
        }
    )
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=False,
    )

    c.disable_print_profile.assert_called_once_with()
    assert c.move_to_location.call_args_list[0] == call("pause")
    assert c.move_to_location.call_args_list[1].args == ("pause",)
    assert c.move_to_location.call_args_list[1].kwargs["z_offset"] == -5000
    assert callable(c.move_to_location.call_args_list[1].kwargs["on_complete"])
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    assert c.get_array_run_state() == "idle"
    assert c.array_complete.calls == [()]
    assert c.update_slots_signal.calls == []


def test_handle_array_well_complete_soft_stop_waits_for_watermark():
    current = FakeWell("A1", 5)
    later = FakeWell("A2", 2)
    c = _make_controller(
        well_plate=FakeWellPlate([current, later]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = {
        "stock_id": "stock-a",
        "expected_volume": None,
        "update_volume": False,
        "droplet_volume": None,
        "finalize_reason": None,
        "queued_wells": [
            {"well_id": "A1", "target_droplets": 5, "dispense_seq32": 101},
            {"well_id": "A2", "target_droplets": 2, "dispense_seq32": 102},
        ],
        "planned_well_ids": {"A1", "A2"},
        "soft_stop_pending": True,
    }
    c._enqueue_array_finalize = Mock()

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=False,
    )

    assert c.get_array_run_state() == "stop_requested"
    assert c._array_context["soft_stop_pending"] is True
    c._enqueue_array_finalize.assert_not_called()


def test_handle_array_well_complete_completion_catchup_finalizes_soft_stop_when_wells_remain():
    current = FakeWell("A1", 5)
    later = FakeWell("A2", 2)
    c = _make_controller(
        well_plate=FakeWellPlate([current, later]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = {
        "stock_id": "stock-a",
        "expected_volume": None,
        "update_volume": False,
        "droplet_volume": None,
        "finalize_reason": None,
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 101}],
        "planned_well_ids": {"A1"},
        "soft_stop_pending": True,
        "soft_stop_phase": "waiting_completion_catchup",
    }
    c._enqueue_array_finalize = Mock(return_value=True)

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=5,
        update_volume=False,
    )

    assert current.record_calls == [("stock-a", 5)]
    assert c._array_context["queued_wells"] == []
    assert c._array_context["soft_stop_pending"] is False
    assert c._array_context["soft_stop_phase"] == "done"
    c._enqueue_array_finalize.assert_called_once_with("soft_stop")


def test_handle_status_update_completes_soft_stop_when_watermark_reached():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True
    c._begin_soft_stop_clear_and_park = Mock()

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    c.model.update_state.assert_called_once()
    c._begin_soft_stop_clear_and_park.assert_called_once_with()


def test_handle_status_update_completion_catchup_finalizes_when_queue_is_empty():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 0), FakeWell("A2", 2)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = {
        "stock_id": "stock-a",
        "finalize_reason": None,
        "queued_wells": [],
        "soft_stop_pending": True,
        "soft_stop_phase": "waiting_completion_catchup",
    }
    c._enqueue_array_finalize = Mock(return_value=True)

    Controller.handle_status_update(c, {"Current_command": 130, "Last_completed": 130, "Last_retired": 130})

    c.model.update_state.assert_called_once()
    c._enqueue_array_finalize.assert_called_once_with("soft_stop")
    assert c._array_context["soft_stop_pending"] is False
    assert c._array_context["soft_stop_phase"] == "done"


def test_handle_status_update_ignores_repeated_watermark_frames_after_clear_begins():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True
    c.machine.clear_command_queue.side_effect = lambda handler=None: None

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})
    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    c.machine.clear_command_queue.assert_called_once()
    assert c._array_context["soft_stop_phase"] == "clearing"


def test_handle_status_update_soft_stop_clear_and_park_completes_before_resume_ready():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)
    c.machine.clear_command_queue.side_effect = lambda handler=None: handler(
        {
            "ack_received": False,
            "ack_timed_out": True,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    )

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    c.model.machine_model.clear_command_queue.assert_called_once_with()
    c.update_expected_with_current.assert_called_once_with()
    c.disable_print_profile.assert_called_once_with()
    assert c.move_to_location.call_args_list[0] == call("pause")
    assert c.move_to_location.call_args_list[1].args == ("pause",)
    assert c.move_to_location.call_args_list[1].kwargs["z_offset"] == -5000
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    assert c.get_array_run_state() == "resume_ready"
    assert c.update_slots_signal.calls == [()]
    assert c.error_occurred_signal.calls == []
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == []


def test_soft_stop_resumes_paused_transport_after_clear_before_parking():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True

    def _parking_move(*args, on_complete=None, **kwargs):
        c.command_events.append(("move_to_location", args, kwargs))
        if callable(on_complete):
            on_complete()
        return True

    c.move_to_location = Mock(side_effect=_parking_move)
    c.machine.clear_command_queue.side_effect = lambda handler=None: handler(
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    )

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    event_names = [event[0] for event in c.command_events]
    assert event_names[:3] == ["resume_commands", "move_to_location", "move_to_location"]
    c.machine.resume_commands.assert_called_once_with()
    c.model.machine_model.resume_commands.assert_called_once_with()
    assert c.get_array_run_state() == "resume_ready"


def test_soft_stop_clear_unconfirmed_warns_and_preserves_resume_ready():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True
    c.machine.clear_command_queue.side_effect = lambda handler=None: handler(
        {
            "ack_received": False,
            "ack_timed_out": True,
            "status_confirmed": False,
            "status_timed_out": True,
        }
    )

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    c.model.machine_model.clear_command_queue.assert_called_once_with()
    c.update_expected_with_current.assert_not_called()
    c.move_to_location.assert_not_called()
    c.machine.set_axis_accel.assert_not_called()
    assert c.get_array_run_state() == "resume_ready"
    assert c.error_occurred_signal.calls[-1] == (
        "Soft Stop Warning",
        "Soft stop reached the watermark, but the queue clear was not confirmed within the grace window after CLEAR_ACK timed out. Preserving resume state without parking.",
    )
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "soft_stop_clear_unconfirmed"
    ]


def test_soft_stop_clear_exception_latches_dock_check_before_finalize():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels(
        {"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"}
    )
    c.machine.clear_command_queue.side_effect = RuntimeError("clear failed")

    Controller._begin_soft_stop_clear_and_park(c)

    assert c.get_array_run_state() == "resume_ready"
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "soft_stop_clear_unconfirmed"
    ]
    c.move_to_location.assert_not_called()


def test_soft_stop_transport_resume_failure_latches_park_check():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels(
        {
            "soft_stop_pending": True,
            "soft_stop_phase": "clearing",
            "soft_stop_transport_was_paused": True,
        }
    )
    c.machine.resume_commands.side_effect = RuntimeError("resume failed")

    Controller._on_soft_stop_queue_cleared(
        c,
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        },
    )

    assert c.get_array_run_state() == "resume_ready"
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "soft_stop_park_failed"
    ]
    c.move_to_location.assert_not_called()


def test_soft_stop_park_failure_warns_and_preserves_resume_ready():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="stop_requested",
    )
    c._array_context = _with_lowered_array_accels({"soft_stop_pending": True, "soft_stop_phase": "waiting_watermark"})
    c.model.machine_model.pause_watermark_reached = True
    c.model.machine_model.transport_paused = True
    c.machine.clear_command_queue.side_effect = lambda handler=None: handler(
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": True,
            "status_timed_out": False,
        }
    )
    c.move_to_location = Mock(return_value=False)

    Controller.handle_status_update(c, {"Pause_watermark_reached": 1, "Transport_paused": 1})

    c.disable_print_profile.assert_called_once_with()
    c.update_expected_with_current.assert_called_once_with()
    c.move_to_location.assert_called_once_with("pause")
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    assert c.get_array_run_state() == "resume_ready"
    assert c.error_occurred_signal.calls[-1] == (
        "Soft Stop Warning",
        "Soft stop reached the watermark, but the machine could not be parked. Preserving resume state without parking.",
    )
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "soft_stop_park_failed"
    ]


def test_normal_array_park_failure_latches_dock_check():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 0)]),
        printer_head=_make_printer_head(),
        initial_state="running",
    )
    c._array_context = _with_lowered_array_accels({"stock_id": "stock-a"})
    c.move_to_location = Mock(return_value=False)

    Controller._enqueue_array_finalize(c, "completed")

    assert c.get_array_run_state() == "idle"
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "array_park_failed"
    ]


def test_resume_array_blocks_when_persistent_dock_confirmation_required():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="resume_ready",
    )
    c.model.machine_model.mark_evap_plate_dock_check_required("soft_stop_park_failed")

    Controller.print_array(c)

    assert c.error_occurred_signal.calls[-1][0] == "Evaporation Plate Dock Check Required"
    assert c.get_array_run_state() == "resume_ready"
    c.machine.resume_commands.assert_not_called()
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == [
        "soft_stop_park_failed"
    ]


def test_print_array_blocks_read_only_legacy_execution_before_hardware_actions():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.experiment_model.is_read_only_legacy_execution = Mock(return_value=True)

    Controller.print_array(c)

    message = c.error_occurred_signal.calls[0][1]
    assert "read-only for analysis" in message
    assert "resume" in message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_blocks_after_execution_plan_finalization_failure():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.experiment_model.get_execution_plan_finalization_error = Mock(
        return_value="disk unavailable"
    )

    Controller.print_array(c)

    message = c.error_occurred_signal.calls[0][1]
    assert "did not finish creating its execution artifacts" in message
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_blocks_execution_plan_sync_error_before_hardware_actions():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.experiment_model.get_execution_plan_sync_error = Mock(
        return_value="progress reference differs"
    )

    Controller.print_array(c)

    assert "not synchronized" in c.error_occurred_signal.calls[0][1]
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def test_print_array_durably_locks_before_first_hardware_action():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    events = []
    c.model.experiment_model.lock_execution_plan = Mock(
        side_effect=lambda reason: events.append(("lock", reason))
    )
    c.close_gripper = Mock(side_effect=lambda: events.append(("close_gripper",)))
    c.move_to_location = Mock(side_effect=lambda *args, **kwargs: events.append(("move",)) or True)

    Controller.print_array(c)

    assert events[0] == ("lock", "printing_started")
    assert c.model.experiment_model.lock_execution_plan.call_count == 1


def test_print_array_lock_failure_prevents_hardware_actions():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
    )
    c.model.experiment_model.lock_execution_plan = Mock(
        side_effect=OSError("disk full")
    )

    Controller.print_array(c)

    assert "durably locked" in c.error_occurred_signal.calls[0][1]
    c.close_gripper.assert_not_called()
    c.move_to_location.assert_not_called()


def _make_pickup_ready_controller(*, initial_state="resume_ready", transport_paused=False):
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state=initial_state,
    )
    c.model.machine_model.transport_paused = bool(transport_paused)
    c.model.rack_model = SimpleNamespace(
        verify_transfer_to_gripper=Mock(return_value=(True, "")),
        plan_transfer_to_gripper=Mock(return_value=(True, "")),
        get_slot_coordinates=Mock(return_value={"X": 10, "Y": 20, "Z": 30}),
        transfer_to_gripper=Mock(),
    )
    c.machine.open_gripper = Mock(return_value=True)

    def _close_gripper(handler=None):
        if callable(handler):
            handler()
        return True

    c.machine.close_gripper = Mock(side_effect=_close_gripper)
    c.close_gripper = lambda handler=None: c.machine.close_gripper(handler=handler)
    c.move_to_location = Mock(return_value=True)
    return c


def test_manual_head_pickup_resumes_paused_transport_before_queueing_rack_moves():
    c = _make_pickup_ready_controller(transport_paused=True)

    Controller.pick_up_printer_head(c, 0, manual=True)

    assert c.command_events[0] == ("resume_commands",)
    c.machine.resume_commands.assert_called_once_with()
    c.model.machine_model.resume_commands.assert_called_once_with()
    c.machine.open_gripper.assert_called_once_with(handler=None)
    assert c.move_to_location.call_count == 3
    c.model.rack_model.transfer_to_gripper.assert_called_once_with(0)


def test_manual_head_pickup_blocks_while_soft_stop_is_still_finishing():
    c = _make_pickup_ready_controller(initial_state="stop_requested")

    Controller.pick_up_printer_head(c, 0, manual=True)

    c.machine.open_gripper.assert_not_called()
    c.move_to_location.assert_not_called()
    assert c.error_occurred_signal.calls[-1] == (
        "Head Transfer Blocked",
        "Cannot load or unload a printer head while the print array is still stopping.",
    )


def test_manual_head_pickup_blocks_after_unconfirmed_soft_stop_clear():
    c = _make_pickup_ready_controller()
    c._soft_stop_clear_uncertain = True

    Controller.pick_up_printer_head(c, 0, manual=True)

    c.machine.open_gripper.assert_not_called()
    c.move_to_location.assert_not_called()
    assert c.error_occurred_signal.calls[-1] == (
        "Head Transfer Blocked",
        "The last soft stop did not confirm that the firmware queue was cleared. Clear the queue or reconnect before loading another printer head.",
    )


def test_handle_array_well_complete_refill_required_parks_and_becomes_resume_ready():
    current = FakeWell("A1", 1)
    later = FakeWell("A2", 2)
    printer_head = _make_printer_head(calibration_complete=True, current_volume=9.0, droplet_volume=1000.0)
    c = _make_controller(
        well_plate=FakeWellPlate([current, later]),
        printer_head=printer_head,
        initial_state="running",
    )
    c._array_context = _with_lowered_array_accels(
        {
            "stock_id": "stock-a",
            "expected_volume": 9.0,
            "update_volume": True,
            "droplet_volume": 1000.0,
            "finalize_reason": None,
            "queued_wells": [{"well_id": "A1", "target_droplets": 1, "dispense_seq32": 101}],
            "planned_well_ids": {"A1"},
        }
    )
    c.move_to_location = Mock(side_effect=_parking_move_side_effect)

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=1,
        update_volume=True,
    )

    assert c.get_array_run_state() == "resume_ready"
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    assert c.update_slots_signal.calls == [()]
    assert c.error_occurred_signal.calls[-1] == ("Error", "Printer head needs to be reloaded")


def test_soft_stop_wins_over_refill_required():
    current = FakeWell("A1", 1)
    later = FakeWell("A2", 2)
    printer_head = _make_printer_head(calibration_complete=True, current_volume=9.0, droplet_volume=1000.0)
    c = _make_controller(
        well_plate=FakeWellPlate([current, later]),
        printer_head=printer_head,
        initial_state="stop_requested",
    )
    c._array_context = {
        "stock_id": "stock-a",
        "expected_volume": 9.0,
        "update_volume": True,
        "droplet_volume": 1000.0,
        "finalize_reason": None,
        "queued_wells": [{"well_id": "A1", "target_droplets": 1, "dispense_seq32": 101}],
        "planned_well_ids": {"A1"},
        "soft_stop_pending": True,
    }
    c._enqueue_array_finalize = Mock()
    c._fill_array_lookahead = Mock()

    Controller._handle_array_well_complete(
        c,
        well_id="A1",
        stock_id="stock-a",
        target_droplets=1,
        update_volume=True,
    )

    c._enqueue_array_finalize.assert_not_called()
    c._fill_array_lookahead.assert_not_called()
    assert c._array_context["soft_stop_pending"] is True


def test_clear_command_queue_resets_array_runner_state():
    c = _make_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)]),
        printer_head=_make_printer_head(),
        initial_state="resume_ready",
    )
    c._array_context = _with_lowered_array_accels({"stock_id": "stock-a"})

    Controller.clear_command_queue(c)

    c.machine.clear_command_queue.assert_called_once_with()
    c.model.machine_model.clear_command_queue.assert_called_once_with()
    assert c.machine.set_axis_accel.call_args_list == _restore_calls()
    c.update_expected_with_current.assert_called_once_with()
    assert c.get_array_run_state() == "idle"
    assert c._array_context is None
    assert c.model.machine_model.get_evap_plate_dock_check_reasons() == ["array_hard_abort"]
