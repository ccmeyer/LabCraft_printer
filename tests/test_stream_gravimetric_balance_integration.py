import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

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
from CalibrationClasses.View import (
    ExperimentalBalanceConnectionGroup,
    StreamCaptureMassEntryDialog,
)
from Controller import Controller, ExperimentalBalancePort
from GravimetricLedger import (
    EjectionCommandEvent,
    EjectionCommandLifecycle,
    ImagingEjectionEvent,
    ImagingEjectionLifecycle,
)
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

    def use_previous_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("reuse")
        return True, ""

    def measure_new_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("measure_new")
        return True, ""

    def start_stream_gravimetric_starting_mass(self):
        self.measurement_calls.append("start_reading")
        return True, ""

    def confirm_stream_gravimetric_starting_return_ready(self):
        self.measurement_calls.append("return_ready")
        return True, ""


def _port(path="/dev/serial/by-id/usb-Prolific_balance"):
    return SimpleNamespace(
        device_path=path,
        display_label=f"HPB balance — {path} [067b:23a3]",
    )


def _snapshot(state, detail="", *, port=None, generation=1):
    return SimpleNamespace(
        state=SimpleNamespace(value=state),
        detail=detail,
        port=port,
        connection_generation=generation,
    )


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
    manager.start_calibration_queue = lambda: None
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(calibration_manager=manager)
    controller.experimental_features = ExperimentalFeatures(True)
    controller._experimental_balance_service = service or _StableMassService()
    controller._experimental_balance_connection_snapshot = _snapshot(state)
    controller._experimental_balance_ports = ()
    controller._experimental_balance_stream_opt_in = False
    controller._experimental_balance_active_stream_request = None
    controller.error_occurred_signal = _Emitter()
    controller.experimental_balance_stream_opt_in_changed = _Emitter()
    controller.experimental_balance_request_progress = _Emitter()
    controller.experimental_balance_request_finished = _Emitter()
    return controller


def _stage_and_start_balance_read(controller, manager, **start_kwargs):
    assert controller.start_stream_gravimetric_capture_with_balance(**start_kwargs) == (True, "")
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_starting_loading_move"
    assert controller.begin_stream_gravimetric_starting_loading_move() == (True, "")
    assert controller.on_stream_gravimetric_starting_loading_reached() == (True, "")
    assert manager.get_stream_gravimetric_capture_state()["status"] == "awaiting_starting_balance_ready"
    assert controller.start_stream_gravimetric_starting_mass() == (True, "")
    return controller._experimental_balance_service.requests[-1]


def _prepare_completed_balance_run(manager, *, starting_mass="10.00"):
    state = manager._build_default_stream_capture_state()
    state.update(
        {
            "status": "pending_loading_move",
            "status_message": "Imaging complete.",
            "session_id": "stream_capture_ending_balance",
            "mass_source": "veritas_balance",
            "ending_mass_source": "manual",
            "starting_mass_mg": float(starting_mass),
            "starting_flash": 100,
            "ending_flash": 110,
            "raw_flash_delta": 10,
            "dataset_run_id": "run_ending_balance",
            "timecourse_run_id": "run_ending_balance",
            "dataset_process_name": "DropletTimecourseProcess",
            "capture_process_name": "DropletTimecourseProcess",
            "printed_capture_count": 10,
            "background_capture_count": 1,
            "printed_capture_event_count": 10,
            "rep": 1,
            "suggested_rep": 1,
            "condition_snapshot": {},
            "gripper_refresh_suspended": True,
        }
    )
    manager._stream_capture_state = state
    return state


def _record_imaging_attempt(
    manager,
    attempt_index,
    *,
    count=1,
    request_id="timecourse-capture",
):
    for lifecycle in (
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.ACKNOWLEDGED,
    ):
        assert manager.record_stream_gravimetric_ejection_event(
            ImagingEjectionEvent(
                transport_epoch=1,
                capture_generation=1,
                request_id=request_id,
                attempt_index=attempt_index,
                requested_droplet_count=count,
                lifecycle=lifecycle,
                monotonic_ns=1000 + attempt_index,
            )
        )


def _complete_balance_ending_and_return(manager, controller, service, mass="12.50"):
    assert controller.on_stream_gravimetric_capture_loading_reached() == (True, "")
    assert controller.start_stream_gravimetric_ending_mass() == (True, "")
    controller._on_experimental_balance_request_finished(
        _stable_result(service.requests[-1], mass)
    )
    assert controller.confirm_stream_gravimetric_ending_mass() == (True, "")
    assert manager.begin_stream_gravimetric_capture_camera_return() == (True, "")
    assert manager.mark_stream_gravimetric_capture_camera_reached() == (True, "")


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


def test_long_persistent_port_label_does_not_expand_balance_panel(qapp):
    short_controller = _UiController((_port("/dev/ttyUSB1"),))
    long_path = "/dev/serial/by-id/" + ("usb-Prolific_balance_adapter_" * 20)
    long_descriptor = _port(long_path)
    long_controller = _UiController((long_descriptor,))

    short_group = ExperimentalBalanceConnectionGroup(short_controller)
    long_group = ExperimentalBalanceConnectionGroup(long_controller)
    short_group.ensurePolished()
    long_group.ensurePolished()

    assert long_group.port_combo.currentData() == long_path
    assert len(long_group.port_combo.currentText()) <= 56
    assert long_group.port_combo.currentText() != long_descriptor.display_label
    assert long_group.port_combo.toolTip() == long_descriptor.display_label
    assert (
        long_group.port_combo.itemData(
            0,
            QtCore.Qt.ItemDataRole.ToolTipRole,
        )
        == long_descriptor.display_label
    )
    assert (
        long_group.port_combo.sizeAdjustPolicy()
        == QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    assert (
        long_group.port_combo.sizeHint().width()
        == short_group.port_combo.sizeHint().width()
    )
    assert long_group.sizeHint().width() == short_group.sizeHint().width()


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
    assert service.requests == []
    staged = manager.get_stream_gravimetric_capture_state()
    assert staged["status"] == "pending_starting_loading_move"
    assert begin_calls == []
    assert controller.begin_stream_gravimetric_starting_loading_move() == (True, "")
    assert controller.on_stream_gravimetric_starting_loading_reached() == (True, "")
    assert service.requests == []
    assert controller.start_stream_gravimetric_starting_mass() == (True, "")
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
    assert candidate["starting_mass_capture"]["phase"] == "starting"
    assert candidate["starting_mass_capture"]["request"]["started_monotonic_ns"] == (
        request.started_monotonic_ns
    )
    assert (
        candidate["starting_mass_capture"]["request"]["policy"]["maximum_span_mg"]
        == "0.03"
    )
    assert candidate["starting_mass_capture"]["connection"]["serial_settings"][
        "receive_only"
    ] is True
    assert "raw_frame" not in str(candidate["starting_mass_capture"])
    assert begin_calls == []
    assert manager.calibration_queue == []

    assert controller.confirm_stream_gravimetric_starting_mass() == (True, "")
    returning = manager.get_stream_gravimetric_capture_state()
    assert returning["status"] == "pending_starting_camera_return"
    assert returning["starting_mass_mg"] == 12.34
    assert begin_calls == []
    assert controller.begin_stream_gravimetric_starting_camera_return() == (True, "")
    assert controller.on_stream_gravimetric_starting_camera_reached() == (True, "")
    started = manager.get_stream_gravimetric_capture_state()
    assert started["status"] == "running"
    assert started["starting_mass_mg"] == 12.34
    assert started["mass_source"] == "veritas_balance"
    assert started["starting_mass_origin"] == "measured"
    assert len(begin_calls) == 1
    assert controller.confirm_stream_gravimetric_starting_mass()[0] is False
    assert len(begin_calls) == 1


def test_request_rejection_timeout_retry_and_stale_result_are_safe(tmp_path):
    _model, manager = _make_manager(tmp_path)
    service = _StableMassService(accept_requests=False)
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)

    assert controller.start_stream_gravimetric_capture_with_balance() == (True, "")
    assert controller.begin_stream_gravimetric_starting_loading_move() == (True, "")
    assert controller.on_stream_gravimetric_starting_loading_reached() == (True, "")
    ok, message = controller.start_stream_gravimetric_starting_mass()
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
    request = _stage_and_start_balance_read(controller, manager)

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
    request = _stage_and_start_balance_read(
        controller,
        manager,
        rep_override=4,
        notes="keep these inputs",
    )

    assert controller.use_manual_stream_gravimetric_starting_mass() == (True, "")
    fallback = manager.get_stream_gravimetric_capture_state()
    assert fallback["status"] == "awaiting_starting_camera_return_ready"
    assert fallback["balance_fallback_reason"] == "operator_manual_fallback"
    assert fallback["preserve_start_inputs"] is True
    assert controller.experimental_balance_stream_opt_in is False
    assert service.cancel_calls == [request.request_id]

    controller._on_experimental_balance_request_finished(_stable_result(request))
    after_late = manager.get_stream_gravimetric_capture_state()
    assert after_late["status"] == "awaiting_starting_camera_return_ready"
    assert controller.confirm_stream_gravimetric_starting_return_ready() == (True, "")
    assert controller.begin_stream_gravimetric_starting_camera_return() == (True, "")
    assert controller.on_stream_gravimetric_starting_camera_reached() == (True, "")
    after_return = manager.get_stream_gravimetric_capture_state()
    assert after_return["status"] == "idle"
    assert after_return["starting_mass_mg"] == 0.0
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


def test_loading_reached_requires_explicit_ending_read_and_confirmed_save(tmp_path):
    model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    port = "/dev/serial/by-id/usb-Prolific_balance"
    descriptor = ExperimentalBalancePort(
        device_path=port,
        system_device="/dev/ttyUSB1",
        by_id_paths=(port,),
        display_label="USB-Serial Controller",
        vid="067b",
        pid="23a3",
        vid_pid="067b:23a3",
        description="USB-Serial Controller",
        manufacturer="Prolific Technology Inc.",
        product="USB-Serial Controller",
        serial_number="fixture-serial",
    )
    controller._experimental_balance_ports = (descriptor,)
    controller._experimental_balance_connection_snapshot = _snapshot(
        "streaming",
        port=port,
        generation=4,
    )
    assert controller.set_experimental_balance_stream_opt_in(True)

    assert controller.on_stream_gravimetric_capture_loading_reached() == (True, "")
    ready = manager.get_stream_gravimetric_capture_state()
    assert ready["status"] == "awaiting_ending_balance_ready"
    assert ready["ending_mass_mg"] is None
    assert service.requests == []

    assert controller.start_stream_gravimetric_ending_mass() == (True, "")
    request = service.requests[-1]
    assert request.phase is StableMassPhase.ENDING
    waiting = manager.get_stream_gravimetric_capture_state()
    assert waiting["status"] == "awaiting_ending_balance_mass"
    assert waiting["balance_request_status"] == "waiting"

    controller._on_experimental_balance_request_finished(
        _stable_result(request, "12.50")
    )
    candidate = manager.get_stream_gravimetric_capture_state()
    assert candidate["status"] == "awaiting_ending_balance_confirmation"
    assert candidate["ending_mass_mg"] is None
    capture = candidate["ending_mass_capture"]
    assert capture["stable_mass_mg"] == "12.50"
    assert capture["request"]["policy"]["maximum_span_mg"] == "0.03"
    assert capture["connection"]["connection_generation"] == 4
    assert capture["connection"]["device"]["vid_pid"] == "067b:23a3"
    assert capture["connection"]["serial_settings"]["receive_only"] is True
    assert "raw_frame" not in str(capture)

    assert controller.confirm_stream_gravimetric_ending_mass(
        rep_override=1,
        notes="confirmed ending",
    ) == (True, "")
    saved = manager.get_stream_gravimetric_capture_state()
    assert saved["status"] == "pending_camera_return"
    assert saved["ending_mass_mg"] == 12.5
    assert saved["ending_mass_source"] == "veritas_balance"

    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8").splitlines()[0])
    assert sidecar["ending_mass_capture"]["stable_mass_mg"] == "12.50"
    assert sidecar["ending_mass_capture"]["connection"]["port"] == port


def test_confirmed_ending_mass_is_offered_and_explicitly_reused(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    controller._experimental_balance_stream_opt_in = True

    _complete_balance_ending_and_return(manager, controller, service, mass="12.50")
    idle = manager.get_stream_gravimetric_capture_state()
    assert idle["status"] == "idle"
    assert idle["reusable_baseline_available"] is True
    assert idle["reusable_baseline_mass_mg"] == "12.50"
    source_session_id = idle["reusable_baseline_session_id"]

    request_count = len(service.requests)
    assert controller.start_stream_gravimetric_capture_with_balance() == (True, "")
    choice = manager.get_stream_gravimetric_capture_state()
    assert choice["status"] == "awaiting_starting_baseline_choice"
    assert choice["reusable_baseline_session_id"] == source_session_id

    assert controller.use_previous_stream_gravimetric_starting_mass() == (True, "")
    started = manager.get_stream_gravimetric_capture_state()
    assert started["status"] == "running"
    assert started["starting_mass_mg"] == 12.5
    assert started["starting_mass_origin"] == "carried_forward"
    assert started["carried_from_session_id"] == source_session_id
    assert started["starting_mass_capture"]["origin"] == "carried_forward"
    assert len(service.requests) == request_count


def test_ejection_attempt_invalidates_reusable_ending_mass(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    controller._experimental_balance_stream_opt_in = True
    _complete_balance_ending_and_return(manager, controller, service, mass="12.50")

    assert manager.record_stream_gravimetric_ejection_event(
        EjectionCommandEvent(
            transport_epoch=1,
            command_number=72,
            command_type="DISPENSE",
            requested_droplet_count=20,
            lifecycle=EjectionCommandLifecycle.QUEUED,
            monotonic_ns=10,
        )
    )
    invalidated = manager.get_stream_gravimetric_capture_state()
    assert invalidated["reusable_baseline_available"] is False
    assert "ejection" in invalidated["reusable_baseline_invalid_reason"].lower()

    assert controller.start_stream_gravimetric_capture_with_balance() == (True, "")
    staged = manager.get_stream_gravimetric_capture_state()
    assert staged["status"] == "pending_starting_loading_move"
    assert service.requests[-1].phase is StableMassPhase.ENDING


def test_gpio_ejection_attempt_invalidates_reusable_ending_mass(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    controller._experimental_balance_stream_opt_in = True
    _complete_balance_ending_and_return(manager, controller, service, mass="12.50")

    _record_imaging_attempt(
        manager,
        1,
        count=1,
        request_id="outside-gravimetric-workflow",
    )

    invalidated = manager.get_stream_gravimetric_capture_state()
    assert invalidated["reusable_baseline_available"] is False
    assert "ejection" in invalidated["reusable_baseline_invalid_reason"].lower()


def test_command_derived_count_warns_on_camera_mismatch_and_uncertainty_blocks_save(
    monkeypatch,
    tmp_path,
):
    _model, manager = _make_manager(tmp_path)
    state = _prepare_completed_balance_run(manager)
    state["ejection_completed_total_start"] = 0
    state["ejection_uncertainty_generation_start"] = 0
    state["ejection_integrity_status"] = "clean"
    monkeypatch.setattr(
        manager,
        "_derive_stream_capture_counts",
        lambda: {
            "background_capture_count": 1,
            "printed_capture_count": 5,
            "printed_capture_event_count": 5,
        },
    )
    for lifecycle in (
        EjectionCommandLifecycle.QUEUED,
        EjectionCommandLifecycle.COMPLETED,
    ):
        manager.record_stream_gravimetric_ejection_event(
            EjectionCommandEvent(
                transport_epoch=1,
                command_number=80,
                command_type="DISPENSE_PRINT",
                requested_droplet_count=7,
                lifecycle=lifecycle,
                monotonic_ns=20 + len(lifecycle.value),
            )
        )

    manager._update_stream_capture_counts()
    counted = manager.get_stream_gravimetric_capture_state()
    assert counted["capture_derived_printed_count"] == 5
    assert counted["printed_capture_count"] == 12
    assert counted["ejection_completed_total_end"] == 7
    assert counted["ejection_serial_completed_delta"] == 7
    assert counted["ejection_imaging_acknowledged_delta"] == 0
    assert counted["ejection_count_source"] == "serial_plus_capture_fallback"
    assert counted["ejection_integrity_status"] == "warning"
    assert "coverage was incomplete" in counted["ejection_integrity_message"].lower()

    for lifecycle in (
        EjectionCommandLifecycle.QUEUED,
        EjectionCommandLifecycle.ACCEPTED,
        EjectionCommandLifecycle.CANCELLED,
    ):
        manager.record_stream_gravimetric_ejection_event(
            EjectionCommandEvent(
                transport_epoch=1,
                command_number=81,
                command_type="DISPENSE",
                requested_droplet_count=3,
                lifecycle=lifecycle,
                monotonic_ns=40 + len(lifecycle.value),
            )
        )

    uncertain = manager.get_stream_gravimetric_capture_state()
    assert uncertain["ejection_integrity_status"] == "uncertain"
    with pytest.raises(ValueError, match="uncertain completion"):
        manager._build_stream_capture_metadata_row(
            ending_mass_mg=12.5,
            rep_value=1,
            notes="must not save",
        )


def test_balance_timecourse_falls_back_to_140_capture_droplets_when_gpio_coverage_is_missing(
    monkeypatch,
    tmp_path,
):
    model, manager = _make_manager(tmp_path)
    state = _prepare_completed_balance_run(manager)
    state["ejection_completed_total_start"] = 0
    state["ejection_uncertainty_generation_start"] = 0
    state["ejection_integrity_status"] = "clean"
    monkeypatch.setattr(
        manager,
        "_derive_stream_capture_counts",
        lambda: {
            "background_capture_count": 10,
            "printed_capture_count": 140,
            "printed_capture_event_count": 140,
        },
    )

    manager._update_stream_capture_counts()
    counted = manager.get_stream_gravimetric_capture_state()

    assert counted["background_capture_count"] == 10
    assert counted["capture_derived_printed_count"] == 140
    assert counted["printed_capture_count"] == 140
    assert counted["ejection_count_source"] == "serial_plus_capture_fallback"
    assert counted["ejection_integrity_status"] == "warning"
    assert counted["ejection_ledger_snapshot_end"][
        "imaging_acknowledged_droplet_total"
    ] == 0
    manager._write_stream_capture_log(outcome="count_reconciliation_test")
    sidecar_path = (
        Path(model.experiment_model.experiment_dir_path)
        / "stream_capture_log.jsonl"
    )
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8").splitlines()[0])
    assert sidecar["ejection_count_source"] == "serial_plus_capture_fallback"
    assert sidecar["ejection_serial_completed_delta"] == 0
    assert sidecar["ejection_imaging_acknowledged_delta"] == 0
    assert sidecar["capture_derived_printed_count"] == 140
    assert sidecar["ejection_ledger_snapshot_end"][
        "serial_completed_droplet_total"
    ] == 0
    assert "raw serial" not in json.dumps(sidecar).lower()
    assert "raw gpio" not in json.dumps(sidecar).lower()


def test_balance_timecourse_uses_clean_acknowledged_gpio_count(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)
    state = _prepare_completed_balance_run(manager)
    start = manager._stream_gravimetric_ejection_ledger.snapshot()
    state["ejection_completed_total_start"] = start.completed_droplet_total
    state["ejection_uncertainty_generation_start"] = start.uncertainty_generation
    state["ejection_ledger_snapshot_start"] = manager._stream_ejection_snapshot_dict(start)
    state["ejection_integrity_status"] = "clean"
    for attempt_index in range(1, 141):
        _record_imaging_attempt(manager, attempt_index)
    monkeypatch.setattr(
        manager,
        "_derive_stream_capture_counts",
        lambda: {
            "background_capture_count": 10,
            "printed_capture_count": 140,
            "printed_capture_event_count": 140,
        },
    )

    manager._update_stream_capture_counts()
    counted = manager.get_stream_gravimetric_capture_state()

    assert counted["printed_capture_count"] == 140
    assert counted["ejection_imaging_acknowledged_delta"] == 140
    assert counted["ejection_imaging_attempt_delta"] == 140
    assert counted["ejection_count_source"] == "serial_plus_imaging_ledger"
    assert counted["ejection_integrity_status"] == "clean"
    assert counted["ejection_coverage_warning"] == ""


def test_acknowledged_gpio_retry_is_counted_and_warned(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)
    state = _prepare_completed_balance_run(manager)
    start = manager._stream_gravimetric_ejection_ledger.snapshot()
    state["ejection_completed_total_start"] = start.completed_droplet_total
    state["ejection_uncertainty_generation_start"] = start.uncertainty_generation
    state["ejection_ledger_snapshot_start"] = manager._stream_ejection_snapshot_dict(start)
    state["ejection_integrity_status"] = "clean"
    for attempt_index in range(1, 7):
        _record_imaging_attempt(manager, attempt_index)
    monkeypatch.setattr(
        manager,
        "_derive_stream_capture_counts",
        lambda: {
            "background_capture_count": 1,
            "printed_capture_count": 5,
            "printed_capture_event_count": 5,
        },
    )

    manager._update_stream_capture_counts()
    counted = manager.get_stream_gravimetric_capture_state()

    assert counted["printed_capture_count"] == 6
    assert counted["ejection_count_source"] == (
        "serial_plus_imaging_ledger_with_retries"
    )
    assert counted["ejection_integrity_status"] == "warning"
    assert "retries" in counted["ejection_coverage_warning"].lower()


def test_serial_and_gpio_deltas_are_combined_without_cross_source_collision(
    tmp_path,
    monkeypatch,
):
    _model, manager = _make_manager(tmp_path)
    state = _prepare_completed_balance_run(manager)
    start = manager._stream_gravimetric_ejection_ledger.snapshot()
    state["ejection_completed_total_start"] = start.completed_droplet_total
    state["ejection_uncertainty_generation_start"] = start.uncertainty_generation
    state["ejection_ledger_snapshot_start"] = manager._stream_ejection_snapshot_dict(start)
    state["ejection_integrity_status"] = "clean"
    for lifecycle in (
        EjectionCommandLifecycle.QUEUED,
        EjectionCommandLifecycle.COMPLETED,
    ):
        manager.record_stream_gravimetric_ejection_event(
            EjectionCommandEvent(
                transport_epoch=1,
                command_number=1,
                command_type="DISPENSE",
                requested_droplet_count=7,
                lifecycle=lifecycle,
                monotonic_ns=10,
            )
        )
    for attempt_index in range(1, 6):
        _record_imaging_attempt(manager, attempt_index)
    monkeypatch.setattr(
        manager,
        "_derive_stream_capture_counts",
        lambda: {
            "background_capture_count": 1,
            "printed_capture_count": 5,
            "printed_capture_event_count": 5,
        },
    )

    manager._update_stream_capture_counts()
    counted = manager.get_stream_gravimetric_capture_state()

    assert counted["ejection_serial_completed_delta"] == 7
    assert counted["ejection_imaging_acknowledged_delta"] == 5
    assert counted["printed_capture_count"] == 12
    assert counted["ejection_count_source"] == "serial_plus_imaging_ledger"
    assert counted["ejection_integrity_status"] == "clean"


def test_manual_and_balance_sources_build_identical_csv_rows(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    manager._stream_capture_state["status"] = "awaiting_ending_balance_confirmation"
    manager._stream_capture_state["ending_mass_source"] = "veritas_balance"

    balance_row = manager._build_stream_capture_metadata_row(
        ending_mass_mg=12.5,
        rep_value=2,
        notes="same row",
    )
    manager._stream_capture_state["mass_source"] = "manual"
    manager._stream_capture_state["ending_mass_source"] = "manual"
    manual_row = manager._build_stream_capture_metadata_row(
        ending_mass_mg=12.5,
        rep_value=2,
        notes="same row",
    )

    assert balance_row == manual_row


def test_ending_balance_save_failure_is_terminal_without_duplicate_csv(
    monkeypatch,
    tmp_path,
):
    model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)
    assert controller.on_stream_gravimetric_capture_loading_reached() == (True, "")
    assert controller.start_stream_gravimetric_ending_mass() == (True, "")
    request = service.requests[-1]
    controller._on_experimental_balance_request_finished(_stable_result(request, "12.50"))

    monkeypatch.setattr(
        manager,
        "_append_stream_capture_metadata_row",
        lambda _row: (_ for _ in ()).throw(OSError("injected save failure")),
    )
    ok, message = controller.confirm_stream_gravimetric_ending_mass()
    assert not ok
    assert "injected save failure" in message
    failed = manager.get_stream_gravimetric_capture_state()
    assert failed["status"] == "error"
    assert failed["session_outcome"] is None
    assert failed["sidecar_outcome"] == "invalid_save"

    assert controller.confirm_stream_gravimetric_ending_mass()[0] is False
    csv_path = Path(model.experiment_model.experiment_dir_path) / "stream_metadata.csv"
    assert not csv_path.exists()
    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    assert len(sidecar_path.read_text(encoding="utf-8").splitlines()) == 1


def test_ending_balance_failure_retry_and_manual_fallback_keep_completed_run(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)
    assert controller.on_stream_gravimetric_capture_loading_reached() == (True, "")
    assert controller.start_stream_gravimetric_ending_mass() == (True, "")
    first_request = service.requests[-1]

    controller._on_experimental_balance_request_finished(
        _failed_result(first_request)
    )
    failed = manager.get_stream_gravimetric_capture_state()
    assert failed["balance_request_status"] == "timeout"

    assert controller.retry_stream_gravimetric_ending_mass() == (True, "")
    second_request = service.requests[-1]
    assert second_request.request_id != first_request.request_id
    assert second_request.stream_session_id == first_request.stream_session_id

    assert controller.use_manual_stream_gravimetric_ending_mass() == (True, "")
    manual = manager.get_stream_gravimetric_capture_state()
    assert manual["status"] == "awaiting_mass_entry"
    assert manual["ending_mass_source"] == "manual"
    assert manual["session_id"] == first_request.stream_session_id
    assert manual["printed_capture_count"] == 10
    assert controller.experimental_balance_stream_opt_in is True
    assert service.cancel_calls == [second_request.request_id]


def test_loading_reached_uses_manual_ending_when_opted_out_or_disconnected(tmp_path):
    for index, (state, opted_in) in enumerate(
        (("streaming", False), ("disconnected", True))
    ):
        _model, manager = _make_manager(tmp_path / str(index))
        _prepare_completed_balance_run(manager)
        controller = _controller_with_manager(manager, state=state)
        controller._experimental_balance_stream_opt_in = opted_in

        assert controller.on_stream_gravimetric_capture_loading_reached() == (
            True,
            "",
        )
        manual = manager.get_stream_gravimetric_capture_state()
        assert manual["status"] == "awaiting_mass_entry"
        assert manual["ending_mass_source"] == "manual"
        assert manual["balance_request_id"] is None


def test_ending_stale_events_and_cancel_race_cannot_create_candidate(tmp_path):
    _model, manager = _make_manager(tmp_path)
    _prepare_completed_balance_run(manager)
    service = _StableMassService()
    controller = _controller_with_manager(manager, service=service)
    assert controller.set_experimental_balance_stream_opt_in(True)
    assert controller.on_stream_gravimetric_capture_loading_reached() == (True, "")
    assert controller.start_stream_gravimetric_ending_mass() == (True, "")
    request = service.requests[-1]

    for stale in (
        replace(_stable_result(request), request_id="stale-request"),
        replace(_stable_result(request), stream_session_id="stale-session"),
        replace(_stable_result(request), phase=StableMassPhase.STARTING),
    ):
        controller._on_experimental_balance_request_finished(stale)
        state = manager.get_stream_gravimetric_capture_state()
        assert state["balance_request_status"] == "waiting"
        assert state["ending_mass_capture"] is None

    assert controller.cancel_stream_gravimetric_ending_mass() == (True, "")
    controller._on_experimental_balance_request_finished(_stable_result(request))
    cancelled = manager.get_stream_gravimetric_capture_state()
    assert cancelled["status"] == "awaiting_ending_balance_mass"
    assert cancelled["balance_request_status"] == "cancelled"
    assert cancelled["ending_mass_capture"]["stable_mass_mg"] == "12.34"
    assert cancelled["ending_mass_mg"] is None

    controller._on_experimental_balance_request_finished(_stable_result(request))
    duplicate = manager.get_stream_gravimetric_capture_state()
    assert duplicate["balance_request_status"] == "cancelled"
    assert duplicate["ending_mass_mg"] is None


def test_ending_balance_states_belong_to_gravimetric_guards(tmp_path):
    _model, manager = _make_manager(tmp_path)
    for status in (
        "awaiting_starting_balance_mass",
        "awaiting_starting_balance_confirmation",
        "awaiting_ending_balance_ready",
        "awaiting_ending_balance_mass",
        "awaiting_ending_balance_confirmation",
    ):
        manager._stream_capture_state["status"] = status
        assert manager.has_open_stream_gravimetric_capture()
        assert manager.is_stream_gravimetric_capture_busy()
    manager._stream_calibration_sequence_state["status"] = (
        "awaiting_starting_balance_mass"
    )
    assert not manager.has_open_stream_calibration_sequence()
    assert not manager.is_stream_calibration_sequence_busy()


def test_ending_mass_dialog_warns_but_allows_nonpositive_candidate(qapp):
    parent = QtWidgets.QWidget()
    dialog = StreamCaptureMassEntryDialog(
        parent,
        controller=SimpleNamespace(),
        model=SimpleNamespace(machine_model=SimpleNamespace()),
    )
    dialog.update_state(
        {
            "status": "awaiting_ending_balance_confirmation",
            "status_message": "Review ending mass.",
            "balance_request_status": "stable_candidate",
            "balance_status_message": "Review before saving.",
            "starting_mass_mg": 12.50,
            "printed_capture_count": 10,
            "ending_mass_capture": {
                "stable_mass_mg": "12.40",
                "evidence": {
                    "sample_count": 10,
                    "window_duration_ns": 3_000_000_000,
                    "span_mg": "0.01",
                    "population_standard_deviation_mg": "0.003",
                    "fitted_slope_mg_per_second": "0.001",
                },
            },
        },
        rep_value=1,
        notes="diagnostic",
    )

    assert dialog.ending_mass_spin.value() == 12.40
    assert not dialog.ending_mass_spin.isEnabled()
    assert "Mass change: -0.1000 mg" in dialog.balance_preview_label.text()
    assert "Warning" in dialog.balance_warning_label.text()
    assert dialog.complete_button.text() == (
        "Same Tube Reinstalled - Confirm Ending Mass & Save"
    )
    assert dialog.complete_button.isEnabled()


def test_ending_mass_read_action_calls_controller_once(monkeypatch, qapp):
    dialog, _manager, controller = _build_view_dialog(monkeypatch, qapp)
    calls = []
    controller.start_stream_gravimetric_ending_mass = (
        lambda: calls.append("read") or (True, "")
    )

    assert dialog._request_stream_gravimetric_ending_mass() is True
    assert calls == ["read"]


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


def test_group_shows_baseline_choice_and_explicit_starting_sample_action(qapp):
    controller = _UiController(
        (_port(),),
        cached_snapshot=_snapshot("streaming"),
    )
    group = ExperimentalBalanceConnectionGroup(controller)

    group.update_stream_capture_state(
        {
            "status": "awaiting_starting_baseline_choice",
            "reusable_baseline_mass_mg": "12.50",
            "reusable_baseline_session_id": "prior-run",
        }
    )
    assert group.candidate_mass_label.text() == (
        "Previous verified ending mass: 12.50 mg"
    )
    assert not group.use_previous_mass_button.isHidden()
    assert not group.measure_new_mass_button.isHidden()
    assert group.start_reading_button.isHidden()

    group.use_previous_mass_button.click()
    group.measure_new_mass_button.click()
    assert controller.measurement_calls == ["reuse", "measure_new"]

    group.update_stream_capture_state(
        {"status": "awaiting_starting_balance_ready"}
    )
    assert not group.start_reading_button.isHidden()
    assert group.use_previous_mass_button.isHidden()
    group.start_reading_button.click()
    assert controller.measurement_calls[-1] == "start_reading"


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
            "status": "running",
            "status_message": "Starting.",
            "starting_mass_mg": 12.34,
            "rep": 6,
        }
    )
    assert dialog.stream_capture_starting_mass_spin.value() == 12.34
    assert not dialog.stream_capture_starting_mass_spin.isEnabled()


def test_closing_imager_cancels_pending_measurement_without_disconnecting_or_abandoning(
    monkeypatch, qapp
):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
    manager.state.update(
        {
            "status": "awaiting_starting_balance_mass",
            "balance_request_status": "waiting",
        }
    )
    calls = []

    controller.cancel_stream_gravimetric_starting_mass = (
        lambda: calls.append(("cancel", "")) or (True, "")
    )
    controller.disconnect_experimental_balance = lambda: calls.append(
        ("disconnect", "")
    )
    dialog.camera_free_mode = True
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    event = QtGui.QCloseEvent()

    dialog.closeEvent(event)

    assert calls == [("cancel", "")]
    assert manager.state["status"] == "awaiting_starting_balance_mass"
    assert event.isAccepted()


def test_closing_imager_cancels_active_ending_read_without_discarding_run(
    monkeypatch,
    qapp,
):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
    manager.state.update(
        {
            "status": "awaiting_ending_balance_mass",
            "balance_request_status": "waiting",
            "session_id": "completed-run",
        }
    )
    calls = []
    controller.cancel_stream_gravimetric_ending_mass = (
        lambda: calls.append("cancel") or (True, "")
    )
    controller.disconnect_experimental_balance = lambda: calls.append(
        "disconnect"
    )
    dialog.camera_free_mode = True
    dialog._should_confirm_close_without_applied_calibration = lambda: False
    event = QtGui.QCloseEvent()

    dialog.closeEvent(event)

    assert calls == ["cancel"]
    assert manager.state["session_id"] == "completed-run"
    assert event.isAccepted()
