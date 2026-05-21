from types import SimpleNamespace

from Controller import Controller


class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self._callbacks = []
            return
        self._callbacks = [cb for cb in self._callbacks if cb != callback]

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)


def test_disconnect_droplet_camera_signals_only_removes_controller_handlers():
    c = Controller.__new__(Controller)

    capture = FakeSignal()
    move = FakeSignal()
    move_abs = FakeSignal()
    settings = FakeSignal()
    img = FakeSignal()
    fail = FakeSignal()

    c.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            captureImageRequested=capture,
            moveRequested=move,
            moveAbsoluteRequested=move_abs,
            changeSettingsRequested=settings,
        )
    )
    c.machine = SimpleNamespace(
        droplet_camera=SimpleNamespace(
            image_captured_signal=img,
            capture_failed_signal=fail,
        )
    )

    external_calls = {"capture": 0, "img": 0}
    capture.connect(lambda: external_calls.__setitem__("capture", external_calls["capture"] + 1))
    img.connect(lambda *_: external_calls.__setitem__("img", external_calls["img"] + 1))

    Controller.connect_droplet_camera_signals(c)
    Controller.disconnect_droplet_camera_signals(c)

    capture.emit()
    img.emit("frame")

    assert external_calls["capture"] == 1
    assert external_calls["img"] == 1


def test_camera_capture_phase_signal_records_active_calibration_event():
    c = Controller.__new__(Controller)

    capture = FakeSignal()
    move = FakeSignal()
    move_abs = FakeSignal()
    settings = FakeSignal()
    completion = FakeSignal()
    phase = FakeSignal()
    recorded = []

    c.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            captureImageRequested=capture,
            moveRequested=move,
            moveAbsoluteRequested=move_abs,
            changeSettingsRequested=settings,
            activeCalibration=SimpleNamespace(
                _record_event=lambda event_type, payload, level="info": recorded.append(
                    (event_type, dict(payload), level)
                )
            ),
        )
    )
    c.machine = SimpleNamespace(
        droplet_camera=SimpleNamespace(
            capture_completed_signal=completion,
            capture_phase_signal=phase,
        )
    )

    Controller.connect_droplet_camera_signals(c)
    phase.emit({"phase": "backend_created", "backend_id": "2", "level": "warning"})

    assert recorded == [
        (
            "camera_capture_phase",
            {"phase": "backend_created", "backend_id": "2", "level": "warning"},
            "warning",
        )
    ]


def test_handle_settings_change_request_binds_traced_commands_to_machine_snapshot():
    c = Controller.__new__(Controller)

    bind_calls = []
    trace_snapshot_calls = []
    queued_calls = []
    next_command_number = {"value": 41}

    def _queue(command_type, **kwargs):
        command_number = next_command_number["value"]
        next_command_number["value"] += 1
        queued_calls.append(
            {
                "command_type": command_type,
                "handler": kwargs.get("handler"),
                "trace_metadata": dict(kwargs.get("trace_metadata") or {}),
            }
        )
        return SimpleNamespace(command_number=command_number, command_type=command_type)

    c.machine = SimpleNamespace(
        register_settings_trace_binding=lambda payload: bind_calls.append(dict(payload)),
        get_settings_trace_snapshot=lambda request_id, timed_out_monotonic_ns=None: trace_snapshot_calls.append(
            (request_id, timed_out_monotonic_ns)
        ) or {
            "request_id": request_id,
            "stall_hint": "completion_command_sent_not_retired",
        },
    )
    c.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(update_exposure_time=lambda *_args, **_kwargs: None),
    )
    c.intermediate_callback = lambda: None
    c.set_flash_delay = lambda value, callback=None, trace_metadata=None: _queue(
        "SET_DELAY_F",
        handler=callback,
        trace_metadata=trace_metadata,
    )
    c.set_imaging_droplets = lambda value, callback=None, trace_metadata=None: _queue(
        "SET_IMAGE_DROPLETS",
        handler=callback,
        trace_metadata=trace_metadata,
    )

    def _bind_callback(payload):
        bind_calls.append({"bound_event": dict(payload)})

    def _callback():
        return None

    _callback._settings_request_id = "req-42"
    _callback._settings_context = "online_stream_apply_flow_delay"
    _callback._settings_requested_settings = {"flash_delay": 6000, "num_droplets": 1}
    _callback._settings_created_monotonic_ns = 123456789
    _callback._settings_guard_timeout_ms = 10000
    _callback._settings_bind_callback = _bind_callback
    _callback._settings_trace_provider = lambda: {"stall_hint": "commands_not_bound"}
    _callback._settings_timed_out_monotonic_ns = None

    Controller.handle_settings_change_request(
        c,
        {"flash_delay": 6000, "num_droplets": 1},
        _callback,
    )

    assert queued_calls[0]["trace_metadata"]["request_id"] == "req-42"
    assert queued_calls[0]["trace_metadata"]["setting_key"] == "flash_delay"
    assert queued_calls[1]["trace_metadata"]["setting_key"] == "num_droplets"
    assert queued_calls[0]["handler"] is not _callback
    assert queued_calls[1]["handler"] is _callback

    binding_payload = bind_calls[0]
    assert binding_payload["request_id"] == "req-42"
    assert binding_payload["completion_command_number"] == 42
    assert [item["command_type"] for item in binding_payload["commands"]] == [
        "SET_DELAY_F",
        "SET_IMAGE_DROPLETS",
    ]

    bound_event_payload = bind_calls[1]["bound_event"]
    assert bound_event_payload["request_id"] == "req-42"
    assert bound_event_payload["completion_command_number"] == 42

    snapshot = _callback._settings_trace_provider()
    assert snapshot["stall_hint"] == "completion_command_sent_not_retired"
    assert trace_snapshot_calls == [("req-42", None)]
