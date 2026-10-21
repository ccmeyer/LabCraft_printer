import hashlib
import sys
import types
from types import SimpleNamespace

import pytest

import App


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in self.callbacks:
            callback()


class _Splash:
    def __init__(self, events):
        self.events = events
        self.cancel_requested = _Signal()
        events.append("splash_created")

    def set_status(self, message):
        self.events.append(("splash_status", message))

    def show(self):
        self.events.append("splash_shown")

    def hide(self):
        self.events.append("splash_hidden")

    def finish(self, _view):
        self.events.append("splash_finished")

    def close_startup(self):
        self.events.append("splash_closed")


class _Application:
    def __init__(self, argv, events, *, result=0):
        self.events = events
        self.result = result
        self.aboutToQuit = _Signal()
        events.append("qapplication")

    def setOrganizationName(self, _value):
        pass

    def setApplicationName(self, _value):
        pass

    def setApplicationDisplayName(self, _value):
        pass

    def setDesktopFileName(self, _value):
        pass

    def setWindowIcon(self, _value):
        pass

    def processEvents(self):
        self.events.append("process_events")

    def exec(self):
        self.events.append("event_loop")
        return self.result

    def quit(self):
        self.events.append("app_quit")

    def exit(self, code):
        self.result = code
        self.events.append(("app_exit", code))


class _Lock:
    def __init__(self, events):
        self.events = events

    def unlock(self):
        self.events.append("app_lock_released")


class _Icon:
    def __init__(self, _path):
        pass

    def isNull(self):
        return True


def _install_bootstrap_modules(
    monkeypatch,
    events,
    *,
    dialog_result,
    inspection_state="candidate_selection_required",
    dialog_error=None,
    ready_error=None,
):
    machine_data = types.ModuleType("MachineData")
    machine_data.resolve_machine_data_base = lambda **_kwargs: events.append(
        "resolve_base"
    ) or object()

    bootstrap_module = types.ModuleType("MachineDataBootstrap")

    class BootstrapState:
        READY = "ready"
        RECOVERY_REQUIRED = "recovery_required"
        CANDIDATE_SELECTION_REQUIRED = "candidate_selection_required"

    class Bootstrap:
        def __init__(self, _base, **_kwargs):
            events.append("bootstrap_created")

        def inspect(self):
            events.append("bootstrap_inspected")
            return SimpleNamespace(state=inspection_state)

        def open_ready(self):
            events.append("bootstrap_open_ready")
            if ready_error is not None:
                raise ready_error
            return dialog_result

        def request_cancel(self):
            events.append("bootstrap_cancel_requested")

    class BootstrapError(RuntimeError):
        def __init__(self, code, message):
            self.code = code
            super().__init__(message)

    bootstrap_module.BootstrapState = BootstrapState
    bootstrap_module.BootstrapError = BootstrapError
    bootstrap_module.MachineDataBootstrap = Bootstrap

    dialog_module = types.ModuleType("MachineDataBootstrapDialog")

    def run_dialog(*_args, **_kwargs):
        assert "splash_hidden" in events
        assert _kwargs["inspection"].state == inspection_state
        events.append("bootstrap_dialog")
        if dialog_error is not None:
            raise dialog_error
        return dialog_result

    dialog_module.run_bootstrap_dialog = run_dialog
    monkeypatch.setitem(sys.modules, "MachineData", machine_data)
    monkeypatch.setitem(sys.modules, "MachineDataBootstrap", bootstrap_module)
    monkeypatch.setitem(sys.modules, "MachineDataBootstrapDialog", dialog_module)
    return BootstrapState


def _patch_app_shell(monkeypatch, tmp_path, events):
    monkeypatch.setattr(
        App.QMessageBox, "critical",
        lambda *_args: pytest.fail(f"Unexpected startup error: {_args[-1]}"),
    )
    monkeypatch.setattr(
        App,
        "QApplication",
        lambda argv: _Application(argv, events),
    )
    monkeypatch.setattr(App, "QIcon", _Icon)
    splashes = []

    def make_splash(_pixmap):
        splash = _Splash(events)
        splashes.append(splash)
        return splash

    monkeypatch.setattr(App, "StartupSplash", make_splash)
    monkeypatch.setattr(App, "QPixmap", lambda _path: object())

    def run_operation(operation, *, splash):
        assert splash is splashes[0]
        assert "splash_shown" in events
        events.append("splash_painted")
        return operation()

    monkeypatch.setattr(App, "run_startup_operation", run_operation)
    optimization_jobs = types.ModuleType("OptimizationJobs")
    optimization_jobs.optimization_job_manager = lambda: events.append("optimizer")
    monkeypatch.setitem(sys.modules, "OptimizationJobs", optimization_jobs)
    monkeypatch.setattr(App, "set_dark_theme", lambda _app: events.append("theme"))
    monkeypatch.setattr(App, "single_instance_lock_path", lambda: tmp_path / "app.lock")
    monkeypatch.setattr(
        App,
        "acquire_single_instance_lock",
        lambda _path: events.append("app_lock_acquired") or _Lock(events),
    )
    monkeypatch.setattr(
        App.QStandardPaths,
        "writableLocation",
        lambda _location: str(tmp_path / "app-data"),
    )
    return splashes


def test_bootstrap_cancel_closes_early_splash_before_settings_or_composition(
    monkeypatch, tmp_path
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    state = _install_bootstrap_modules(monkeypatch, events, dialog_result=None)
    # The post-dialog inspection uses the same state value object.
    monkeypatch.setitem(
        sys.modules,
        "ApplicationComposition",
        types.ModuleType("ApplicationComposition"),
    )
    assert App.main() == App.EXIT_BOOTSTRAP_CANCELLED
    assert events[:4] == [
        "qapplication",
        "app_lock_acquired",
        "theme",
        "splash_created",
    ]
    assert events.index("splash_painted") < events.index("resolve_base")
    assert "bootstrap_dialog" in events
    assert "splash_closed" in events
    assert "app_lock_released" == events[-1]
    assert state.CANDIDATE_SELECTION_REQUIRED == "candidate_selection_required"


def test_bootstrap_error_maps_exit_code_and_releases_app_lock(monkeypatch, tmp_path):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    error = RuntimeError("canonical state requires support")
    error.code = "recovery_required"
    _install_bootstrap_modules(
        monkeypatch,
        events,
        dialog_result=None,
        dialog_error=error,
    )
    messages = []
    monkeypatch.setattr(
        App.QMessageBox,
        "critical",
        lambda *_args: messages.append(_args),
    )

    assert App.main() == App.EXIT_RECOVERY_REQUIRED
    assert messages
    assert events[-1] == "app_lock_released"


def test_dialog_cancellation_reinspects_durable_state_for_recovery(
    monkeypatch, tmp_path
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    state = _install_bootstrap_modules(monkeypatch, events, dialog_result=None)
    bootstrap_type = sys.modules["MachineDataBootstrap"].MachineDataBootstrap
    inspections = iter(
        [state.CANDIDATE_SELECTION_REQUIRED, state.RECOVERY_REQUIRED]
    )
    monkeypatch.setattr(
        bootstrap_type, "inspect",
        lambda _self: SimpleNamespace(state=next(inspections)),
    )
    assert App.main() == App.EXIT_RECOVERY_REQUIRED
    assert "bootstrap_dialog" in events
    assert events[-2:] == ["splash_closed", "app_lock_released"]


@pytest.mark.parametrize(
    "code, expected_exit",
    [
        ("configuration_lock_unavailable", App.EXIT_CONFIGURATION_LOCK_UNAVAILABLE),
        ("recovery_required", App.EXIT_RECOVERY_REQUIRED),
        ("bootstrap_failed", App.EXIT_BOOTSTRAP_FAILED),
        ("bootstrap_cancelled", App.EXIT_BOOTSTRAP_CANCELLED),
    ],
)
def test_ready_revalidation_failure_never_constructs_components_or_opens_dialog(
    monkeypatch, tmp_path, code, expected_exit
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    error = RuntimeError("revalidation rejected")
    error.code = code
    _install_bootstrap_modules(
        monkeypatch, events, dialog_result=None, inspection_state="ready",
        ready_error=error,
    )
    messages = []
    monkeypatch.setattr(
        App.QMessageBox, "critical", lambda *_args: messages.append(_args)
    )

    assert App.main() == expected_exit
    assert "bootstrap_open_ready" in events
    assert "bootstrap_dialog" not in events
    assert "settings_consumed" not in events
    assert bool(messages) is (code != "bootstrap_cancelled")
    assert events[-2:] == ["splash_closed", "app_lock_released"]


@pytest.mark.parametrize("cancel_after_authorization", [False, True])
def test_splash_cancellation_waits_for_worker_and_releases_any_authorized_context(
    monkeypatch, tmp_path, cancel_after_authorization
):
    events = []
    splashes = _patch_app_shell(monkeypatch, tmp_path, events)
    context = SimpleNamespace(close=lambda: events.append("context_closed"))
    _install_bootstrap_modules(
        monkeypatch, events, dialog_result=context, inspection_state="ready"
    )

    def cancelled_operation(operation, *, splash):
        assert splash is splashes[0]
        if not cancel_after_authorization:
            splash.cancel_requested.emit()
        result = operation()
        splash.cancel_requested.emit()
        events.append("worker_stopped")
        return result

    monkeypatch.setattr(App, "run_startup_operation", cancelled_operation)
    assert App.main() == App.EXIT_BOOTSTRAP_CANCELLED
    assert "bootstrap_dialog" not in events
    assert "settings_consumed" not in events
    if cancel_after_authorization:
        assert events.index("worker_stopped") < events.index("context_closed")
        assert events.count("context_closed") == 1
    else:
        assert "bootstrap_open_ready" not in events
        assert "context_closed" not in events
    assert events[-2:] == ["splash_closed", "app_lock_released"]


@pytest.mark.parametrize("real_presentation", [False, True])
def test_ready_bootstrap_precedes_settings_and_component_construction(
    qapp, monkeypatch, tmp_path, real_presentation
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    if real_presentation:
        from PySide6 import QtGui
        from StartupPresentation import StartupSplash, run_startup_operation

        def make_splash(pixmap):
            splash = StartupSplash(pixmap)
            splash.painted.connect(lambda: events.append("splash_painted"))
            return splash

        monkeypatch.setattr(App, "StartupSplash", make_splash)
        monkeypatch.setattr(App, "QPixmap", QtGui.QPixmap)
        monkeypatch.setattr(App, "run_startup_operation", run_startup_operation)
    config_root = tmp_path / "machine" / "config"
    config_root.mkdir(parents=True)
    settings_path = config_root / "Settings.json"
    settings_path.write_text('{"HARDWARE_PROFILE":"current"}', encoding="utf-8")
    settings_sha = hashlib.sha256(settings_path.read_bytes()).hexdigest()

    class Context:
        def __init__(self):
            self.paths = SimpleNamespace(config_root=config_root)
            self.settings = {"HARDWARE_PROFILE": "current"}
            self.settings_raw_sha256 = settings_sha
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            events.append("context_closed")

    context = Context()
    _install_bootstrap_modules(
        monkeypatch, events, dialog_result=context, inspection_state="ready"
    )

    composition = types.ModuleType("ApplicationComposition")
    composition.ExperimentalFeatures = SimpleNamespace(
        from_environment=lambda _environment: object()
    )
    dependencies = object()
    composition.production_dependencies = lambda supplied: events.append(
        "production_dependencies"
    ) or (dependencies if supplied is context else None)

    model = SimpleNamespace(
        settings=dict(context.settings),
        machine_model=SimpleNamespace(update_dispense_frequency_hz=lambda _value: None),
    )
    view = SimpleNamespace(
        show=lambda: events.append("view_show"),
        show_pending_app_update_result_after_startup=lambda: events.append(
            "update_result"
        ),
    )
    if real_presentation:
        from PySide6 import QtWidgets

        class StartupView(QtWidgets.QWidget):
            def show(self):
                events.append("view_show")
                super().show()

            def show_pending_app_update_result_after_startup(self):
                events.append("update_result")

        view = StartupView()

    class Components:
        def __init__(self):
            self.view = view
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            if real_presentation:
                view.close()
            context.close()
            return True

    components = Components()

    def build(_profile, supplied_dependencies, *, model_setup, **_kwargs):
        assert supplied_dependencies is dependencies
        events.append("components_constructed")
        model_setup(model)
        return components

    composition.build_application_components = build
    monkeypatch.setitem(sys.modules, "ApplicationComposition", composition)
    monkeypatch.setattr(
        App,
        "get_profile",
        lambda _name: events.append("settings_consumed") or object(),
    )

    monkeypatch.setattr(
        App.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )
    monkeypatch.setattr(
        App,
        "install_ui_freeze_watchdog",
        lambda _app: events.append("watchdog"),
    )

    assert App.main() == 0
    assert "bootstrap_dialog" not in events
    assert events.index("splash_painted") < events.index("bootstrap_inspected")
    assert events.index("bootstrap_inspected") < events.index("bootstrap_open_ready")
    assert events.index("bootstrap_open_ready") < events.index("settings_consumed")
    assert events.index("settings_consumed") < events.index("components_constructed")
    assert components.close_calls == 1
    assert context.close_calls == 1
    assert events[-1] == "app_lock_released"


def test_settings_hash_change_after_bootstrap_closes_context_without_components(
    monkeypatch, tmp_path
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    config_root = tmp_path / "machine" / "config"
    config_root.mkdir(parents=True)
    settings_path = config_root / "Settings.json"
    settings_path.write_text('{"HARDWARE_PROFILE":"current"}', encoding="utf-8")
    context = SimpleNamespace(
        paths=SimpleNamespace(config_root=config_root),
        settings={"HARDWARE_PROFILE": "current"},
        settings_raw_sha256="0" * 64,
        close=lambda: events.append("context_closed"),
    )
    _install_bootstrap_modules(monkeypatch, events, dialog_result=context)
    composition = types.ModuleType("ApplicationComposition")
    composition.ExperimentalFeatures = object()
    composition.production_dependencies = lambda _context: object()
    composition.build_application_components = lambda *_args, **_kwargs: events.append(
        "components_constructed"
    )
    monkeypatch.setitem(sys.modules, "ApplicationComposition", composition)
    messages = []
    monkeypatch.setattr(
        App.QMessageBox,
        "critical",
        lambda *_args: messages.append(_args),
    )

    assert App.main() == App.EXIT_BOOTSTRAP_FAILED

    assert "components_constructed" not in events
    assert "context_closed" in events
    assert "Settings changed" in messages[0][-1]
    assert events[-1] == "app_lock_released"


def test_development_launch_requires_ready_store_skips_dialog_and_records_session(
    monkeypatch, tmp_path
):
    events = []
    _patch_app_shell(monkeypatch, tmp_path, events)
    monkeypatch.setenv("LABCRAFT_DEPLOYMENT_MODE", "development")
    monkeypatch.setenv("LABCRAFT_DEVELOPMENT_AUTOCLOSE_MS", "750")
    monkeypatch.setattr(App, "get_app_version", lambda _root: "v1.3.0-dev")
    monkeypatch.setattr(App, "get_app_commit", lambda _root: "d" * 40)

    base = SimpleNamespace(root=tmp_path / "development-machine-data")
    machine_data = types.ModuleType("MachineData")
    machine_data.resolve_machine_data_base = lambda **_kwargs: base
    monkeypatch.setitem(sys.modules, "MachineData", machine_data)

    config_root = tmp_path / "machine" / "config"
    config_root.mkdir(parents=True)
    settings_path = config_root / "Settings.json"
    settings_path.write_text('{"HARDWARE_PROFILE":"current"}', encoding="utf-8")
    context = SimpleNamespace(
        paths=SimpleNamespace(config_root=config_root),
        settings={"HARDWARE_PROFILE": "current"},
        settings_raw_sha256=hashlib.sha256(settings_path.read_bytes()).hexdigest(),
        close=lambda: events.append("context_closed"),
    )
    bootstrap_module = types.ModuleType("MachineDataBootstrap")

    class BootstrapState:
        READY = "ready"
        RECOVERY_REQUIRED = "recovery_required"

    class Bootstrap:
        def __init__(self, supplied_base, **kwargs):
            assert supplied_base is base
            assert kwargs["deployment_gate_enabled"] is False
            events.append("development_bootstrap_created")

        def inspect(self):
            events.append("development_inspected")
            return SimpleNamespace(state=BootstrapState.READY)

        def open_ready(self):
            events.append("development_open_ready")
            return context

    bootstrap_module.BootstrapState = BootstrapState
    bootstrap_module.BootstrapError = RuntimeError
    bootstrap_module.MachineDataBootstrap = Bootstrap
    monkeypatch.setitem(sys.modules, "MachineDataBootstrap", bootstrap_module)
    dialog_module = types.ModuleType("MachineDataBootstrapDialog")
    dialog_module.run_bootstrap_dialog = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("development launch must not open the migration dialog")
    )
    monkeypatch.setitem(sys.modules, "MachineDataBootstrapDialog", dialog_module)

    launch = SimpleNamespace(hardware_enabled=False)
    development = types.ModuleType("MachineDataDevelopment")
    development.development_launch_from_environment = (
        lambda root, _environment: launch if root == base.root else None
    )
    development.record_development_session = lambda supplied, **kwargs: (
        events.append(("development_session", supplied, kwargs))
        or tmp_path / "session.json"
    )
    development.record_no_hardware_runtime_evidence = (
        lambda path, **kwargs: (
            events.append(("development_runtime", path, kwargs))
            or tmp_path / "session.runtime.json"
        )
    )
    monkeypatch.setitem(sys.modules, "MachineDataDevelopment", development)

    composition = types.ModuleType("ApplicationComposition")
    composition.ExperimentalFeatures = SimpleNamespace(
        from_environment=lambda _environment: object()
    )
    def blocked_factory(name):
        def blocked(*_args, **_kwargs):
            raise AssertionError("blocked factory must not be called")

        blocked.__name__ = f"blocked_{name}"
        return blocked

    dependencies = SimpleNamespace(
        runtime_context=SimpleNamespace(
            mode=SimpleNamespace(value="development"),
            identity_text="DEVELOPMENT BUILD — NO HARDWARE CONNECTED",
            hardware_access_allowed=False,
            updater_access_allowed=False,
        ),
        serial_factory=blocked_factory("serial_access"),
        refuel_camera_factory=blocked_factory("refuel_camera_access"),
        droplet_camera_factory=blocked_factory("droplet_camera_access"),
        log_reader_factory=blocked_factory("log_reader_access"),
        balance_factory=blocked_factory("balance_access"),
        experimental_balance_factory=blocked_factory("experimental_balance_access"),
        legacy_calibration_model_factory=blocked_factory(
            "legacy_calibration_hardware_access"
        ),
    )
    composition.production_dependencies = lambda _context: (_ for _ in ()).throw(
        AssertionError("production dependencies must not be used")
    )
    composition.development_dependencies = lambda supplied, hardware_enabled: (
        events.append(("development_dependencies", hardware_enabled))
        or (dependencies if supplied is context else None)
    )
    model = SimpleNamespace(
        settings=dict(context.settings),
        machine_model=SimpleNamespace(update_dispense_frequency_hz=lambda _value: None),
    )
    view = SimpleNamespace(
        show=lambda: events.append("view_show"),
        show_pending_app_update_result_after_startup=lambda: events.append(
            "unexpected_update_result"
        ),
    )

    class Components:
        def __init__(self):
            self.view = view
            self.machine = type("SimulatedMachine", (), {})()

        def close(self):
            context.close()
            return True

    def build(_profile, supplied, *, model_setup, **_kwargs):
        assert supplied is dependencies
        model_setup(model)
        return Components()

    composition.build_application_components = build
    monkeypatch.setitem(sys.modules, "ApplicationComposition", composition)
    monkeypatch.setattr(App, "get_profile", lambda _name: object())
    monkeypatch.setattr(
        App.QTimer,
        "singleShot",
        lambda delay, callback: (events.append(("timer", delay)), callback()),
    )
    monkeypatch.setattr(App, "install_ui_freeze_watchdog", lambda _app: None)

    assert App.main() == 0
    assert events.index("development_inspected") < events.index("development_open_ready")
    assert any(isinstance(event, tuple) and event[0] == "development_session" for event in events)
    assert any(isinstance(event, tuple) and event[0] == "development_runtime" for event in events)
    assert ("development_dependencies", False) in events
    assert "unexpected_update_result" not in events
    assert ("timer", 750) in events
    assert "app_quit" in events


def test_development_autoclose_is_bounded_and_no_hardware_only():
    launch = SimpleNamespace(hardware_enabled=False)
    assert App.development_autoclose_delay_ms({}, launch) is None
    assert App.development_autoclose_delay_ms(
        {App.DEVELOPMENT_AUTOCLOSE_MS_ENV: "500"}, launch
    ) == 500
    for value in ("not-an-int", "499", "600001"):
        with pytest.raises(RuntimeError):
            App.development_autoclose_delay_ms(
                {App.DEVELOPMENT_AUTOCLOSE_MS_ENV: value}, launch
            )
    with pytest.raises(RuntimeError, match="no-hardware development"):
        App.development_autoclose_delay_ms(
            {App.DEVELOPMENT_AUTOCLOSE_MS_ENV: "1000"}, None
        )
    with pytest.raises(RuntimeError, match="no-hardware development"):
        App.development_autoclose_delay_ms(
            {App.DEVELOPMENT_AUTOCLOSE_MS_ENV: "1000"},
            SimpleNamespace(hardware_enabled=True),
        )
