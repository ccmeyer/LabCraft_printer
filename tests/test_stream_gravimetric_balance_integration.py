from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from PySide6 import QtCore, QtGui

from ApplicationComposition import ExperimentalFeatures
from BalanceProtocol import (
    BalanceReading,
    StableMassFailureReason,
    StableMassOutcome,
    StableMassPhase,
    StableMassResult,
    StabilityEvidence,
)
from BalanceService import BalanceRequestProgress
from CalibrationClasses.View import ExperimentalBalanceConnectionGroup
from Controller import Controller
from tests.test_stream_gravimetric_capture import (
    SignalStub,
    _make_manager,
    _build_view_dialog,
)


class _UiController(QtCore.QObject):
    experimental_balance_connection_changed = QtCore.Signal(object)
    experimental_balance_reading_received = QtCore.Signal(object)
    experimental_balance_error_occurred = QtCore.Signal(object)
    experimental_balance_stream_opt_in_changed = QtCore.Signal(bool)

    def __init__(self, descriptors=(), cached_reading=None, cached_snapshot=None):
        super().__init__()
        self.experimental_balance_enabled = True
        self.descriptors = tuple(descriptors)
        self.cached_reading = cached_reading
        self.cached_snapshot = cached_snapshot
        self.list_calls = 0
        self.connect_calls = []
        self.disconnect_calls = 0
        self.experimental_balance_stream_opt_in = False
        self.measurement_calls = []

    def list_experimental_balance_ports(self):
        self.list_calls += 1
        return self.descriptors

    def connect_experimental_balance(self, port):
        self.connect_calls.append(port)
        return True

    def disconnect_experimental_balance(self):
        self.disconnect_calls += 1
        return True

    def get_experimental_balance_connection_snapshot(self):
        return self.cached_snapshot

    def get_experimental_balance_last_reading(self):
        return self.cached_reading

    def set_experimental_balance_stream_opt_in(self, enabled):
        if enabled and _snapshot_state(self.cached_snapshot) != "streaming":
            return False
        self.experimental_balance_stream_opt_in = bool(enabled)
        self.experimental_balance_stream_opt_in_changed.emit(bool(enabled))
        return True

    def cancel_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("cancel")
        return True, ""

    def retry_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("retry")
        return True, ""

    def use_manual_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("manual")
        return True, ""

    def confirm_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("confirm")
        return True, ""


def _port(path="/dev/serial/by-id/usb-Prolific_balance"):
    return SimpleNamespace(
        device_path=path,
        display_label=f"HPB balance — {path} [067b:23a3]",
    )


def _snapshot(state, detail=""):
    return SimpleNamespace(state=SimpleNamespace(value=state), detail=detail)


def _snapshot_state(snapshot):
    state = getattr(snapshot, "state", "")
    return str(getattr(state, "value", state) or "")


class _Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _StableMassService:
    def __init__(self, *, accept_requests=True):
        self.accept_requests = bool(accept_requests)
        self.requests = []
        self.cancel_calls = []
        self.connection_snapshot = _snapshot("streaming")

    def request_stable_mass(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            accepted=self.accept_requests,
            detail="" if self.accept_requests else "injected request rejection",
        )

    def cancel_stable_mass(self, request_id):
        self.cancel_calls.append(request_id)
        return SimpleNamespace(accepted=True, detail="")


def _controller_with_manager(manager, *, service=None, state="streaming"):
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(calibration_manager=manager)
    controller.experimental_features = ExperimentalFeatures(True)
    controller._experimental_balance_service = service or _StableMassService()
    controller._experimental_balance_connection_snapshot = _snapshot(state)
    controller._experimental_balance_stream_opt_in = False
    controller._experimental_balance_active_stream_request = None
    controller.error_occurred_signal = _Emitter()
    controller.experimental_balance_stream_opt_in_changed = _Emitter()
    controller.experimental_balance_request_progress = _Emitter()
    controller.experimental_balance_request_finished = _Emitter()
    return controller


def _evidence(mass="12.34"):
    value = Decimal(mass)
    return StabilityEvidence(
        sample_count=10,
        window_started_ns=1_000_000_000,
        window_ended_ns=4_000_000_000,
        window_duration_ns=3_000_000_000,
        mean_mass_mg_unrounded=value,
        quantized_mean_mass_mg=value,
        minimum_mass_mg=value,
        maximum_mass_mg=value,
        span_mg=Decimal("0.00"),
        population_standard_deviation_mg=Decimal("0.00"),
        fitted_slope_mg_per_second=Decimal("0.00"),
        device_stable_sample_count=10,
        device_unstable_sample_count=0,
        all_device_stable=True,
    )


def _stable_result(request, mass="12.34"):
    return StableMassResult(
        request_id=request.request_id,
        stream_session_id=request.stream_session_id,
        phase=request.phase,
        outcome=StableMassOutcome.STABLE,
        completed_monotonic_ns=request.started_monotonic_ns + 4_000_000_000,
        stable_mass_mg=Decimal(mass),
        evidence=_evidence(mass),
        failure_reason=StableMassFailureReason.NONE,
        detail="",
        total_readings_seen=10,
        total_stable_readings=10,
        total_unstable_readings=0,
    )


def _failed_result(request, outcome=StableMassOutcome.TIMEOUT):
    failure = {
        StableMassOutcome.CANCELLED: StableMassFailureReason.CANCELLED,
        StableMassOutcome.TIMEOUT: StableMassFailureReason.TIMEOUT,
        StableMassOutcome.ERROR: StableMassFailureReason.TRANSPORT_ERROR,
    }[outcome]
    return StableMassResult(
        request_id=request.request_id,
        stream_session_id=request.stream_session_id,
        phase=request.phase,
        outcome=outcome,
        completed_monotonic_ns=request.started_monotonic_ns + 30_000_000_000,
        stable_mass_mg=None,
        evidence=None,
        failure_reason=failure,
        detail=outcome.value,
        total_readings_seen=5,
        total_stable_readings=5,
        total_unstable_readings=0,
    )


def test_group_discovers_without_connecting_and_requires_button_click(qapp):
    descriptor = _port()
    controller = _UiController((descriptor,))

    group = ExperimentalBalanceConnectionGroup(
        controller,
        preselected_port=descriptor.device_path,
    )
    qapp.processEvents()

    assert controller.list_calls == 1
    assert controller.connect_calls == []
    assert group.port_combo.currentData() == descriptor.device_path
    assert group.connection_button.text() == "Connect"
    assert group.connection_button.isEnabled()

    group.connection_button.click()
    assert controller.connect_calls == [descriptor.device_path]
    assert controller.disconnect_calls == 0


def test_group_follows_typed_states_and_restores_last_reading(qapp):
    reading = SimpleNamespace(mass_mg=Decimal("125.34"), device_stable=True)
    controller = _UiController((_port(),), cached_reading=reading)
    group = ExperimentalBalanceConnectionGroup(controller)

    assert group.last_reading_label.text() == "Last reading: 125.34 mg (stable)"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("connecting")
    )
    assert not group.port_combo.isEnabled()
    assert not group.refresh_button.isEnabled()
    assert group.connection_button.text() == "Connecting…"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("streaming", "receiving data")
    )
    assert group.connection_state_label.text() == "Streaming: receiving data"
    assert group.connection_button.text() == "Disconnect"
    assert group.connection_button.isEnabled()
    group.connection_button.click()
    assert controller.disconnect_calls == 1

    controller.experimental_balance_reading_received.emit(
        SimpleNamespace(mass_mg=Decimal("125.33"), device_stable=False)
    )
    assert group.last_reading_label.text() == "Last reading: 125.33 mg (unstable)"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("disconnecting")
    )
    assert group.connection_button.text() == "Disconnecting…"
    assert not group.connection_button.isEnabled()

    controller.experimental_balance_connection_changed.emit(_snapshot("error"))
    assert group.connection_button.text() == "Disconnect"
    assert group.connection_button.isEnabled()


def test_dialog_group_is_hidden_by_default_and_enabled_group_is_connection_only(
    monkeypatch, qapp
):
    disabled_dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
    model = disabled_dialog.model
    assert not hasattr(disabled_dialog, "experimental_balance_group")
    disabled_dialog.close()

    descriptor = _port("COM8")
    controller.experimental_balance_enabled = True
    controller.experimental_balance_connection_changed = SignalStub()
    controller.experimental_balance_reading_received = SignalStub()
    controller.experimental_balance_error_occurred = SignalStub()
    controller.experimental_balance_stream_opt_in_changed = SignalStub()
    controller.experimental_balance_stream_opt_in = False
    controller.set_experimental_balance_stream_opt_in = lambda enabled: True
    controller.cancel_stream_gravimetric_starting_mass = lambda: (True, "")
    controller.retry_stream_gravimetric_starting_mass = lambda: (True, "")
    controller.use_manual_stream_gravimetric_starting_mass = lambda: (True, "")
    controller.confirm_stream_gravimetric_starting_mass = lambda: (True, "")
    controller.list_experimental_balance_ports = lambda: (descriptor,)
    controller.get_experimental_balance_connection_snapshot = lambda: None
    controller.get_experimental_balance_last_reading = lambda: None
    controller.experimental_connect_calls = []
    controller.connect_experimental_balance = (
        lambda port: controller.experimental_connect_calls.append(port) or True
    )
    controller.disconnect_experimental_balance = lambda: True
    model.get_default_balance_port = lambda: "COM8"

    enabled_dialog, _manager, _controller = _build_view_dialog(
        monkeypatch,
        qapp,
        manager=manager,
        model=model,
        controller=controller,
    )

    assert enabled_dialog.experimental_balance_group.title() == "Experimental Balance"
    assert enabled_dialog.stream_capture_group.isAncestorOf(
        enabled_dialog.experimental_balance_group
    )
    assert controller.experimental_connect_calls == []
    assert enabled_dialog.stream_capture_starting_mass_spin.value() == 0.0
    assert controller.stream_capture_start_calls == []


def test_controller_stages_candidate_without_starting_session_until_confirmation(
    monkeypatch, tmp_path
):
    _model, manager = _make_manager(tmp_path)
    begin_calls = []
    original_begin = manager.begin_session
    monkeypatch.setattr(
        manager,
        "begin_session",
        lambda *args, **kwargs: (
            begin_calls.append((args, kwargs)),
            original_begin(*args, **kwargs),
        )[1],
    )
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)

    result = controller.start_stream_gravimetric_capture_with_balance(
        rep_override=3,
        notes="balance start",
        capture_mode="timecourse",
    )

    assert result == (True, "")
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.phase is StableMassPhase.STARTING
    waiting = manager.get_stream_gravimetric_capture_state()
    assert waiting["status"] == "awaiting_starting_balance_mass"
    assert waiting["starting_mass_mg"] is None
    assert waiting["starting_flash"] is None
    assert waiting["mass_source"] == "veritas_balance"
    assert begin_calls == []
    assert manager.activeCalibration is None
    assert manager.calibration_queue == []

    reading = BalanceReading(
        timestamp_ns=request.started_monotonic_ns + 2_000_000_000,
        display_value=Decimal("12.34"),
        mass_mg=Decimal("12.34"),
        reported_unit="mg",
        raw_stability="S",
        device_stable=True,
        raw_frame=b"    12.34 mgS",
    )
    progress = BalanceRequestProgress(
        connection_generation=1,
        request_generation=1,
        request=request,
        latest_reading=reading,
        evidence=None,
        elapsed_ns=2_000_000_000,
        retained_sample_count=7,
    )
    controller._on_experimental_balance_request_progress(progress)
    progress_state = manager.get_stream_gravimetric_capture_state()
    assert progress_state["balance_progress"] == {
        "elapsed_ms": 2000,
        "retained_sample_count": 7,
        "latest_mass_mg": "12.34",
        "latest_device_stable": True,
        "evidence": None,
    }

    controller._on_experimental_balance_request_finished(
        _stable_result(request)
    )
    candidate = manager.get_stream_gravimetric_capture_state()
    assert candidate["status"] == "awaiting_starting_balance_confirmation"
    assert candidate["starting_mass_mg"] is None
    assert candidate["starting_flash"] is None
    assert candidate["starting_mass_capture"]["stable_mass_mg"] == "12.34"
    assert "raw_frame" not in str(candidate["starting_mass_capture"])
    assert begin_calls == []
    assert manager.calibration_queue == []

    assert controller.confirm_stream_gravimetric_starting_mass() == (True, "")
    started = manager.get_stream_gravimetric_capture_state()
    assert started["status"] == "pending_gripper_refresh"
    assert started["starting_mass_mg"] == 12.34
    assert started["mass_source"] == "veritas_balance"
    assert len(begin_calls) == 1
    assert controller.confirm_stream_gravimetric_starting_mass()[0] is False
    assert len(begin_calls) == 1


def test_request_rejection_timeout_retry_and_stale_result_are_safe(tmp_path):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService(accept_requests=False)
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)

    ok, message = controller.start_stream_gravimetric_capture_with_balance()
    assert not ok
    assert "rejection" in message
    rejected = manager.get_stream_gravimetric_capture_state()
    assert rejected["balance_request_status"] == "rejected"
    session_id = rejected["session_id"]
    first_id = rejected["balance_request_id"]
    assert manager.activeCalibration is None
    assert manager.calibration_queue == []

    service.accept_requests = True
    assert controller.retry_stream_gravimetric_starting_mass() == (True, "")
    error_request = service.requests[-1]
    controller._on_experimental_balance_request_finished(
        _failed_result(error_request, StableMassOutcome.ERROR)
    )
    failed = manager.get_stream_gravimetric_capture_state()
    assert failed["balance_request_status"] == "error"
    assert failed["starting_mass_capture"]["failure_reason"] == "transport_error"

    assert controller.retry_stream_gravimetric_starting_mass() == (True, "")
    request = service.requests[-1]
    assert request.request_id != first_id
    assert request.stream_session_id == session_id

    for stale in (
        replace(_stable_result(request), request_id="stale-request"),
        replace(_stable_result(request), stream_session_id="stale-session"),
        replace(_stable_result(request), phase=StableMassPhase.ENDING),
    ):
        controller._on_experimental_balance_request_finished(stale)
        assert (
            manager.get_stream_gravimetric_capture_state()[
                "balance_request_status"
            ]
            == "waiting"
        )
        assert controller._experimental_balance_active_stream_request is not None

    controller._on_experimental_balance_request_finished(_failed_result(request))
    timeout = manager.get_stream_gravimetric_capture_state()
    assert timeout["status"] == "awaiting_starting_balance_mass"
    assert timeout["balance_request_status"] == "timeout"
    assert manager.activeCalibration is None
    assert manager.calibration_queue == []


def test_cancel_race_cannot_become_candidate(tmp_path):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)
    assert controller.start_stream_gravimetric_capture_with_balance() == (True, "")
    request = service.requests[-1]

    assert controller.cancel_stream_gravimetric_starting_mass() == (True, "")
    assert service.cancel_calls == [request.request_id]
    controller._on_experimental_balance_request_finished(_stable_result(request))

    state = manager.get_stream_gravimetric_capture_state()
    assert state["status"] == "awaiting_starting_balance_mass"
    assert state["balance_request_status"] == "cancelled"
    assert state["starting_mass_capture"]["stable_mass_mg"] == "12.34"
    assert manager.activeCalibration is None
    assert manager.calibration_queue == []


def test_manual_fallback_invalidates_late_result_and_preserves_manual_marker(
    tmp_path,
):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)
    assert controller.start_stream_gravimetric_capture_with_balance(
        rep_override=4,
        notes="keep these inputs",
    ) == (True, "")
    request = service.requests[-1]

    assert controller.use_manual_stream_gravimetric_starting_mass() == (True, "")
    fallback = manager.get_stream_gravimetric_capture_state()
    assert fallback["status"] == "idle"
    assert fallback["mass_source"] == "manual"
    assert fallback["balance_fallback_reason"] == "operator_manual_fallback"
    assert fallback["preserve_start_inputs"] is True
    assert controller.experimental_balance_stream_opt_in is False
    assert service.cancel_calls == [request.request_id]

    controller._on_experimental_balance_request_finished(_stable_result(request))
    after_late = manager.get_stream_gravimetric_capture_state()
    assert after_late["status"] == "idle"
    assert after_late["starting_mass_mg"] == 0.0
    assert manager.activeCalibration is None
    assert manager.calibration_queue == []


def test_disconnected_cached_opt_in_cannot_stage_request(tmp_path):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService()
    controller = _controller_with_manager(
        manager,
        service=service,
        state="disconnected",
    )
    controller._experimental_balance_stream_opt_in = True

    ok, message = controller.start_stream_gravimetric_capture_with_balance()

    assert not ok
    assert "Streaming" in message
    assert manager.get_stream_gravimetric_capture_state()["status"] == "idle"
    assert service.requests == []


def test_unchecked_balance_flow_does_not_stage_request(tmp_path):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)

    ok, message = controller.start_stream_gravimetric_capture_with_balance()

    assert not ok
    assert "not enabled" in message
    assert manager.get_stream_gravimetric_capture_state()["status"] == "idle"
    assert service.requests == []


def test_opt_in_is_controller_cached_across_group_instances(qapp):
    controller = _UiController(
        (_port(),),
        cached_snapshot=_snapshot("streaming"),
    )
    first = ExperimentalBalanceConnectionGroup(controller)
    first.stream_opt_in_checkbox.click()
    assert controller.experimental_balance_stream_opt_in is True

    second = ExperimentalBalanceConnectionGroup(controller)
    assert second.stream_opt_in_checkbox.isChecked()


def test_group_shows_progress_candidate_and_explicit_controls(qapp):
    controller = _UiController(
        (_port(),),
        cached_snapshot=_snapshot("streaming"),
    )
    group = ExperimentalBalanceConnectionGroup(controller)
    group.update_stream_capture_state(
        {
            "status": "awaiting_starting_balance_mass",
            "balance_request_status": "waiting",
            "balance_status_message": "Waiting for stable readings.",
            "balance_progress": {
                "elapsed_ms": 2200,
                "retained_sample_count": 8,
                "latest_mass_mg": "12.33",
                "latest_device_stable": True,
            },
        }
    )
    assert not group.cancel_reading_button.isHidden()
    assert group.retry_reading_button.isHidden()
    assert group.measurement_progress_label.text().startswith("2.2 s | 8")

    group.update_stream_capture_state(
        {
            "status": "awaiting_starting_balance_confirmation",
            "balance_request_status": "stable_candidate",
            "starting_mass_capture": {"stable_mass_mg": "12.34"},
        }
    )
    assert group.candidate_mass_label.text() == "Candidate starting mass: 12.34 mg"
    assert not group.confirm_starting_mass_button.isHidden()
    assert not group.retry_reading_button.isHidden()
    assert not group.manual_starting_mass_button.isHidden()


def test_manual_fallback_state_preserves_inputs_and_confirmed_state_reflects_mass(
    monkeypatch, qapp
):
    dialog, _manager, _controller = _build_view_dialog(monkeypatch, qapp)
    dialog.stream_capture_starting_mass_spin.setValue(7.89)
    dialog.stream_capture_rep_spin.setValue(6)
    dialog.stream_capture_notes_edit.setPlainText("preserve me")
    dialog._stream_capture_last_status = "awaiting_starting_balance_mass"

    dialog._sync_stream_capture_panel_state(
        {
            "status": "idle",
            "status_message": "Returned to manual starting-mass entry.",
            "preserve_start_inputs": True,
            "suggested_rep": 1,
        }
    )

    assert dialog.stream_capture_starting_mass_spin.value() == 7.89
    assert dialog.stream_capture_rep_spin.value() == 6
    assert dialog.stream_capture_notes_edit.toPlainText() == "preserve me"
    assert dialog.stream_capture_starting_mass_spin.isEnabled()

    dialog._stream_capture_last_status = "awaiting_starting_balance_confirmation"
    dialog._sync_stream_capture_panel_state(
        {
            "status": "pending_gripper_refresh",
            "status_message": "Starting.",
            "starting_mass_mg": 12.34,
            "rep": 6,
        }
    )
    assert dialog.stream_capture_starting_mass_spin.value() == 12.34
    assert not dialog.stream_capture_starting_mass_spin.isEnabled()


def test_closing_imager_abandons_pending_measurement_without_disconnecting_balance(
    monkeypatch, qapp
):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
    manager.state["status"] = "awaiting_starting_balance_mass"
    calls = []

    def abandon(reason=""):
        calls.append(("abandon", reason))
        manager.state["status"] = "idle"
        return True, ""

    controller.abandon_stream_gravimetric_starting_mass = abandon
    controller.disconnect_experimental_balance = lambda: calls.append(
        ("disconnect", "")
    )
    dialog.camera_free_mode = True
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    event = QtGui.QCloseEvent()

    dialog.closeEvent(event)

    assert calls == [("abandon", "imager_closed_pending_balance_start")]
    assert event.isAccepted()
