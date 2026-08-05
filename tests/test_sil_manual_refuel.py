from __future__ import annotations

import json
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub
from tools.sil.manual_refuel import (
    SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION,
    SIMULATED_MANUAL_REFUEL_SOURCE,
    SimulatedManualRefuelOutcomeAdapter,
)


class _Recorder:
    healthy = True

    def __init__(self):
        self.events = []

    def record_event(self, kind, **kwargs):
        self.events.append((kind, kwargs))


def _adapter(*, recording_failure=False):
    head = object()
    applied = {
        "stock_id": "stock-1",
        "printer_head_id": "head-1",
        "printing_mode": "stream",
        "applied_printing_mode": "stream",
        "factor_name": "Factor A",
        "option_name": "",
        "is_fill": False,
        "measured_volume_nL": 40.0,
        "applied_design_volume_nL": 40.0,
        "pw_us": 1400,
        "pressure_psi": 1.2,
        "run_id": "stream-run",
        "phase": "stream",
        "timestamp": "2000-01-01T00:00:00Z",
        "source_row_fingerprint": ["stream-run", "stream", "2000-01-01T00:00:00Z", 1400, 1.2, 40.0],
    }
    experiment = SimpleNamespace(
        manual_refuel_check_changed=SignalStub(),
        current_record=None,
        get_execution_plan_snapshot=lambda: SimpleNamespace(stocks=(object(),)),
        get_execution_plan_source=lambda: "finalized",
        _resolve_applied_imaging_context=lambda **_kwargs: {
            "printer_head_id": "head-1",
            "stock_id": "stock-1",
            "factor_name": "Factor A",
            "option_name": "",
            "is_fill": False,
            "printing_mode": "stream",
        },
        get_applied_imaging_calibration=lambda **_kwargs: dict(applied),
        _manual_refuel_applied_fingerprint=lambda _record: "calibration-fingerprint-1",
        get_manual_refuel_check=lambda **_kwargs: (
            dict(experiment.current_record)
            if isinstance(experiment.current_record, dict)
            else None
        ),
    )
    model = SimpleNamespace(
        experiment_model=experiment,
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: head),
    )
    calls = []

    def preflight():
        record = experiment.current_record
        if not isinstance(record, dict):
            return {"ok": False, "code": "required_refuel_check", "record": None}
        status = record["status"]
        return {
            "ok": status == "passed",
            "code": "passed_refuel_check" if status == "passed" else f"{status}_refuel_check",
            "record": dict(record),
        }

    def record(status, source, **kwargs):
        calls.append((status, source, dict(kwargs)))
        if recording_failure:
            return {"ok": False, "message": "verified persistence failure"}
        record = {
            "status": status,
            "source": source,
            "notes": kwargs["notes"],
            "operator_judgment": kwargs["operator_judgment"],
            "trial_count": kwargs["trial_count"],
            "trial_droplet_count": kwargs["trial_droplet_count"],
            "applied_calibration_fingerprint": "calibration-fingerprint-1",
            "print_pulse_width_us": 1400,
            "refuel_pulse_width_us": 2400,
            "print_pressure_psi": 1.2,
            "refuel_pressure_psi": 0.4,
        }
        experiment.current_record = record
        experiment.manual_refuel_check_changed.emit(dict(record))
        return dict(record)

    controller = SimpleNamespace(
        get_array_run_state=lambda: "idle",
        get_print_array_refuel_check_preflight=preflight,
        record_manual_refuel_check_outcome=record,
    )
    machine = SimpleNamespace(
        state=SimpleNamespace(
            connected=True,
            motors_enabled=True,
            homed=True,
            regulating_print_pressure=True,
            regulating_refuel_pressure=True,
            simulated_elapsed_ms=10,
        ),
        check_if_all_completed=lambda: True,
    )
    recorder = _Recorder()
    failures = []
    adapter = SimulatedManualRefuelOutcomeAdapter(
        seed=7,
        model=model,
        controller=controller,
        machine=machine,
        recorder=recorder,
        failure_callback=failures.append,
    )
    return adapter, experiment, recorder, calls, failures


def test_simulated_pass_uses_existing_controller_path_and_records_provenance():
    adapter, _experiment, recorder, calls, failures = _adapter()

    result = adapter.record_outcome(
        "passed",
        expected_calibration_fingerprint="calibration-fingerprint-1",
    )

    assert result["ok"] is True
    assert result["after_preflight"]["code"] == "passed_refuel_check"
    assert len(calls) == 1
    status, source, kwargs = calls[0]
    assert status == "passed"
    assert source == SIMULATED_MANUAL_REFUEL_SOURCE
    assert kwargs["trial_count"] == 1
    assert kwargs["trial_droplet_count"] == 5
    assert kwargs["operator_judgment"] == "simulated"
    assert json.loads(kwargs["notes"]) == {
        "provider_version": SIMULATED_MANUAL_REFUEL_PROVIDER_VERSION,
        "seed": 7,
        "synthetic": True,
    }
    assert failures == []
    assert recorder.events[0][0] == "simulated_manual_refuel_outcome_recorded"
    payload = recorder.events[0][1]["payload"]
    assert payload["calibration_fingerprint"] == "calibration-fingerprint-1"
    assert payload["before_preflight"]["code"] == "required_refuel_check"


def test_deferred_failed_and_passed_outcomes_reconcile_preflight():
    adapter, _experiment, _recorder, calls, _failures = _adapter()

    deferred = adapter.record_deferred()
    failed = adapter.record_outcome("failed")
    unclear = adapter.record_outcome(
        "unclear",
        operator_judgment="unclear",
        trial_count=2,
        trial_droplet_count=10,
    )
    passed = adapter.record_outcome("passed")

    assert deferred["after_preflight"]["code"] == "deferred_refuel_check"
    assert failed["after_preflight"]["code"] == "failed_refuel_check"
    assert unclear["after_preflight"]["code"] == "unclear_refuel_check"
    assert passed["after_preflight"]["code"] == "passed_refuel_check"
    assert [item[0] for item in calls] == [
        "deferred",
        "failed",
        "unclear",
        "passed",
    ]
    assert calls[0][2]["trial_count"] == 0
    assert calls[0][2]["trial_droplet_count"] == 0
    assert calls[2][2]["operator_judgment"] == "unclear"
    assert calls[2][2]["trial_count"] == 2
    assert calls[2][2]["trial_droplet_count"] == 10


def test_stale_fingerprint_fails_before_recording_and_repeat_is_idempotent():
    adapter, _experiment, recorder, calls, _failures = _adapter()

    stale = adapter.record_outcome(
        "passed",
        expected_calibration_fingerprint="old-fingerprint",
    )
    first = adapter.record_outcome("passed")
    repeated = adapter.record_outcome("passed")

    assert stale["code"] == "stale_calibration_fingerprint"
    assert first["code"] == "recorded"
    assert repeated["code"] == "already_recorded"
    assert len(calls) == 1
    assert len(recorder.events) == 1


def test_ambiguous_recording_failure_latches_and_is_not_retried():
    adapter, _experiment, _recorder, calls, failures = _adapter(
        recording_failure=True
    )

    first = adapter.record_outcome("passed")
    second = adapter.record_outcome("passed")

    assert first["code"] == "recording_failed"
    assert second["code"] == "recording_failed"
    assert len(calls) == 1
    assert failures and "verified persistence failure" in failures[0]


def test_bypass_is_not_an_exposed_simulated_outcome():
    adapter, _experiment, _recorder, calls, _failures = _adapter()

    result = adapter.record_outcome("bypassed")

    assert result["code"] == "unsupported_outcome"
    assert calls == []
