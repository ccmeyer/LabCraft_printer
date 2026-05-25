from unittest.mock import Mock

import pytest

from Controller import Controller
from test_controller_print_guards import (
    FakeWell,
    FakeWellPlate,
    _make_controller,
    _make_printer_head,
)


class AuditSink:
    def __init__(self):
        self.events = []

    def record(self, event_type, summary, details=None, level="info", context=None):
        event = {
            "event_type": event_type,
            "summary": summary,
            "details": dict(details or {}),
            "level": level,
            "context": context,
        }
        self.events.append(event)
        return event


def _make_audited_controller(*, wells=None, well_plate=None, printer_head=None, **kwargs):
    c = _make_controller(
        well_plate=well_plate or FakeWellPlate(wells or [FakeWell("A1", 5)]),
        printer_head=printer_head or _make_printer_head(),
        **kwargs,
    )
    sink = AuditSink()
    c.audit_sink = sink
    c.model.record_experiment_audit_event = sink.record
    return c


def _event_types(c):
    return [event["event_type"] for event in c.audit_sink.events]


class ResettableFakeWellPlate(FakeWellPlate):
    def __init__(self, wells, calibration_ok=True):
        super().__init__(wells, calibration_ok=calibration_ok)
        self.reset_stock_calls = []
        self.reset_all_calls = 0

    def reset_all_wells_for_stock(self, stock_id):
        self.reset_stock_calls.append(stock_id)

    def reset_all_wells(self):
        self.reset_all_calls += 1


def _array_context(reason=None):
    return {
        "stock_id": "stock-a",
        "expected_volume": 20.0,
        "update_volume": False,
        "droplet_volume": 1000.0,
        "finalize_reason": reason,
        "lookahead_wells": 2,
        "queued_wells": [{"well_id": "A1", "target_droplets": 5, "dispense_seq32": 123}],
        "planned_well_ids": {"A1"},
        "current_barrier_seq32": 123,
        "soft_stop_pending": reason == "soft_stop",
        "soft_stop_phase": "done" if reason == "soft_stop" else None,
    }


def test_print_array_records_requested_and_started_events():
    c = _make_audited_controller(wells=[FakeWell("A1", 5), FakeWell("A2", 3)])

    Controller.print_array(c)

    assert _event_types(c) == ["print_array_requested", "print_array_started"]
    requested, started = c.audit_sink.events
    assert requested["details"]["request_kind"] == "start"
    assert started["details"]["queued_well_count"] == 2
    assert started["details"]["lookahead_added"] is True
    assert started["details"]["settings"]["print_pulse_width_us"] == 1400
    assert started["details"]["loaded_printer_head"]["stock_id"] == "stock-a"


def test_print_array_resume_ready_records_resumed_event():
    c = _make_audited_controller(
        wells=[FakeWell("A1", 0), FakeWell("A2", 7)],
        initial_state="resume_ready",
    )
    c.model.machine_model.transport_paused = True
    c.resume_commands = Mock()

    Controller.print_array(c)

    assert _event_types(c) == [
        "print_array_requested",
        "print_array_resumed",
        "print_array_started",
    ]
    assert c.audit_sink.events[0]["details"]["request_kind"] == "resume"
    assert c.audit_sink.events[1]["details"]["transport_resumed"] is True
    c.resume_commands.assert_called_once_with()


def test_print_array_guard_failure_does_not_record_audit_events():
    c = _make_audited_controller(
        well_plate=FakeWellPlate([FakeWell("A1", 5)], calibration_ok=False),
    )

    Controller.print_array(c)

    assert c.audit_sink.events == []


def test_request_array_soft_stop_records_accepted_request():
    c = _make_audited_controller(
        wells=[FakeWell("A1", 5)],
        initial_state="running",
    )
    c._array_context = _array_context()

    assert Controller.request_array_soft_stop(c) is True

    assert _event_types(c) == ["print_array_soft_stop_requested"]
    event = c.audit_sink.events[0]
    assert event["details"]["array_state"] == "stop_requested"
    assert event["details"]["barrier_seq32"] == 123
    assert event["details"]["current_barrier_seq32"] == 123


@pytest.mark.parametrize(
    ("reason", "event_type", "level", "expected_state"),
    [
        ("soft_stop", "print_array_paused", "info", "resume_ready"),
        ("completed", "print_array_completed", "info", "idle"),
        ("refill_required", "print_array_refill_required", "warning", "resume_ready"),
        ("hard_abort", "print_array_aborted", "error", "idle"),
    ],
)
def test_finish_array_finalize_records_lifecycle_event(reason, event_type, level, expected_state):
    c = _make_audited_controller(wells=[FakeWell("A1", 5)], initial_state="running")
    c._array_context = _array_context(reason)

    Controller._finish_array_finalize(c, reason)

    assert c.get_array_run_state() == expected_state
    assert c._array_context is None
    assert _event_types(c) == [event_type]
    event = c.audit_sink.events[0]
    assert event["level"] == level
    assert event["details"]["finalize_reason"] == reason
    assert event["details"]["array_state"] == expected_state
    assert event["details"]["queued_well_count"] == 1
    if reason == "soft_stop":
        assert c.update_slots_signal.calls == [()]
    elif reason == "completed":
        assert c.array_complete.calls == [()]
    elif reason == "refill_required":
        assert c.update_slots_signal.calls == [()]
        assert c.error_occurred_signal.calls[-1] == ("Error", "Printer head needs to be reloaded")


def test_audit_failure_does_not_block_print_array_or_finalize():
    c = _make_audited_controller(wells=[FakeWell("A1", 5)])
    c.model.record_experiment_audit_event = Mock(side_effect=RuntimeError("audit unavailable"))

    Controller.print_array(c)

    assert c.get_array_run_state() == "running"
    assert c.set_absolute_coordinates.called

    Controller._finish_array_finalize(c, "completed")

    assert c.get_array_run_state() == "idle"
    assert c.array_complete.calls == [()]


def test_reset_single_array_records_warning_audit_event():
    plate = ResettableFakeWellPlate([FakeWell("A1", 5), FakeWell("A2", 0)])
    c = _make_audited_controller(well_plate=plate)
    c.model.experiment_model.progress_file_path = "progress.json"

    Controller.reset_single_array(c)

    assert plate.reset_stock_calls == ["stock-a"]
    c.model.experiment_model.create_progress_file.assert_called_once_with()
    assert _event_types(c) == ["print_array_reset"]
    event = c.audit_sink.events[0]
    assert event["level"] == "warning"
    assert event["details"]["reset_scope"] == "single_stock"
    assert event["details"]["stock_id"] == "stock-a"
    assert event["details"]["affected_well_count"] == 2
    assert event["details"]["remaining_well_count_before_reset"] == 1
    assert event["details"]["progress_file_path"] == "progress.json"
    assert event["details"]["loaded_printer_head"]["stock_id"] == "stock-a"


def test_reset_all_arrays_records_warning_audit_event():
    plate = ResettableFakeWellPlate([FakeWell("A1", 5), FakeWell("A2", 3)])
    c = _make_audited_controller(well_plate=plate)
    c.model.experiment_model.progress_file_path = "progress.json"

    Controller.reset_all_arrays(c)

    assert plate.reset_all_calls == 1
    c.model.experiment_model.create_progress_file.assert_called_once_with()
    assert c.update_slots_signal.calls == [()]
    assert _event_types(c) == ["print_arrays_reset_all"]
    event = c.audit_sink.events[0]
    assert event["level"] == "warning"
    assert event["details"]["reset_scope"] == "all_stocks"
    assert event["details"]["affected_well_count"] == 2
    assert event["details"]["progress_file_path"] == "progress.json"


def test_reset_audit_failure_does_not_block_reset_behavior():
    plate = ResettableFakeWellPlate([FakeWell("A1", 5)])
    c = _make_audited_controller(well_plate=plate)
    c.model.record_experiment_audit_event = Mock(side_effect=RuntimeError("audit unavailable"))

    Controller.reset_single_array(c)
    Controller.reset_all_arrays(c)

    assert plate.reset_stock_calls == ["stock-a"]
    assert plate.reset_all_calls == 1
    assert c.model.experiment_model.create_progress_file.call_count == 2
    assert c.update_slots_signal.calls == [()]
