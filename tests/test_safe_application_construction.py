import sys
import types
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore

import ApplicationComposition as composition
import LocalConfig
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE
from simulation import (
    SIMULATED_PORT,
    SimulationConfig,
    SimulationTimingPolicy,
    make_simulated_machine_factory,
)


class _SafeCommandQueue(QtCore.QObject):
    queue_updated = QtCore.Signal()
    commands_completed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.queue = []
        self.completed = []


class _SafeDropletCamera(QtCore.QObject):
    image_captured_signal = QtCore.Signal(object)
    capture_failed_signal = QtCore.Signal()


class _FakeExperimentalBalanceService(QtCore.QObject):
    connection_changed = QtCore.Signal(object)
    reading_received = QtCore.Signal(object)
    request_progress = QtCore.Signal(object)
    request_finished = QtCore.Signal(object)
    error_occurred = QtCore.Signal(object)

    def __init__(self, close_results=None):
        super().__init__()
        self.close_calls = 0
        self._close_results = list(close_results or [True])

    def close(self):
        self.close_calls += 1
        accepted = self._close_results.pop(0) if self._close_results else True
        return SimpleNamespace(
            accepted=accepted,
            detail="closed" if accepted else "worker still running",
        )


class _ConstructionSafeMachine(QtCore.QObject):
    status_updated = QtCore.Signal(dict)
    error_occurred = QtCore.Signal(str)
    homing_completed = QtCore.Signal()
    gripper_open = QtCore.Signal()
    gripper_closed = QtCore.Signal()
    machine_connected_signal = QtCore.Signal(bool)
    reset_report_received = QtCore.Signal(dict)
    serial_connection_lost = QtCore.Signal(dict)
    transport_faulted = QtCore.Signal(dict)
    disconnect_complete_signal = QtCore.Signal()
    flash_state_updated = QtCore.Signal(object)
    all_calibration_droplets_printed = QtCore.Signal()
    log_message_received = QtCore.Signal(str)
    require_gripper_confirmation = QtCore.Signal(str)

    def __init__(self, dependency_factories):
        super().__init__()
        self.dependency_factories = dict(dependency_factories)
        self.command_queue = _SafeCommandQueue()
        self.droplet_camera = _SafeDropletCamera()
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, args))

    def connect_board(self, port):
        self._record("connect_board", port)

    def disconnect_board(self):
        self._record("disconnect_board")

    def reset_mcu_board(self):
        self._record("reset_mcu_board")

    def reset_board(self):
        self._record("reset_board")

    def start_refuel_camera(self):
        self._record("start_refuel_camera")

    def stop_refuel_camera(self):
        self._record("stop_refuel_camera")

    def capture_refuel_image(self):
        self._record("capture_refuel_image")
        return None

    def refuel_led_on(self):
        self._record("refuel_led_on")

    def refuel_led_off(self):
        self._record("refuel_led_off")

    def start_droplet_camera(self):
        self._record("start_droplet_camera")

    def capture_droplet_image(self, *args, **kwargs):
        self._record("capture_droplet_image", args, kwargs)

    def confirm_gripper_ready(self):
        self._record("confirm_gripper_ready")

    def check_if_all_completed(self):
        return True


def _safe_machine_factory(
    model,
    *,
    profile,
    serial_factory,
    refuel_camera_factory,
    droplet_camera_factory,
    log_reader_factory,
):
    return _ConstructionSafeMachine(
        {
            "model": model,
            "profile": profile,
            "serial_factory": serial_factory,
            "refuel_camera_factory": refuel_camera_factory,
            "droplet_camera_factory": droplet_camera_factory,
            "log_reader_factory": log_reader_factory,
        }
    )


def _build_simulation(tmp_path, suffix="run"):
    dependencies = composition.simulation_dependencies(
        tmp_path / suffix,
        machine_factory=_safe_machine_factory,
    )
    components = composition.build_application_components(
        CURRENT_PROFILE,
        dependencies,
    )
    return dependencies, components


def _production_safe_dependencies(tmp_path, experimental_factory):
    simulation = composition.simulation_dependencies(
        tmp_path,
        machine_factory=_safe_machine_factory,
    )
    return replace(
        simulation,
        runtime_context=composition.PRODUCTION_RUNTIME_CONTEXT,
        experimental_balance_factory=experimental_factory,
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, False),
        ("", False),
        ("true", False),
        ("yes", False),
        (" 1", False),
        ("1 ", False),
        ("1", True),
    ],
)
def test_experimental_balance_environment_requires_exact_one(value, expected):
    environment = {}
    if value is not None:
        environment[composition.EXPERIMENTAL_BALANCE_ENV] = value
    features = composition.ExperimentalFeatures.from_environment(environment)
    assert features.balance_integration is expected


def test_experimental_balance_constructs_only_when_production_current_enabled(
    qapp, tmp_path
):
    services = []

    def factory():
        service = _FakeExperimentalBalanceService()
        services.append(service)
        return service

    dependencies = _production_safe_dependencies(tmp_path / "enabled", factory)
    components = composition.build_application_components(
        CURRENT_PROFILE,
        dependencies,
        experimental_features=composition.ExperimentalFeatures(True),
    )

    assert services == [components.balance_service]
    assert components.controller.experimental_balance_enabled is True
    assert components.experimental_features.balance_integration is True
    assert components.close() is True
    assert components.close() is True
    assert services[0].close_calls == 1


def test_default_and_simulation_construction_never_invoke_experimental_factory(
    qapp, tmp_path
):
    calls = []
    production = _production_safe_dependencies(
        tmp_path / "default",
        lambda: calls.append("production") or _FakeExperimentalBalanceService(),
    )
    default_components = composition.build_application_components(
        CURRENT_PROFILE,
        production,
    )
    simulation = composition.simulation_dependencies(
        tmp_path / "simulation-enabled-request",
        machine_factory=_safe_machine_factory,
    )
    simulated_components = composition.build_application_components(
        CURRENT_PROFILE,
        simulation,
        experimental_features=composition.ExperimentalFeatures(True),
    )

    assert calls == []
    assert default_components.balance_service is None
    assert simulated_components.balance_service is None
    assert default_components.controller.experimental_balance_enabled is False
    assert simulated_components.controller.experimental_balance_enabled is False
    default_components.close()
    simulated_components.close()


def test_legacy_profile_forces_experimental_balance_feature_off(tmp_path):
    calls = []
    dependencies = _production_safe_dependencies(
        tmp_path / "legacy-gate",
        lambda: calls.append("constructed"),
    )

    effective = composition._effective_experimental_features(
        LEGACY_PROFILE,
        dependencies,
        composition.ExperimentalFeatures(True),
    )

    assert effective == composition.ExperimentalFeatures(False)
    assert calls == []


def test_experimental_shutdown_rejection_is_retryable_and_not_forceful(
    qapp, tmp_path
):
    service = _FakeExperimentalBalanceService([False, True])
    dependencies = _production_safe_dependencies(
        tmp_path / "shutdown-retry",
        lambda: service,
    )
    components = composition.build_application_components(
        CURRENT_PROFILE,
        dependencies,
        experimental_features=composition.ExperimentalFeatures(True),
    )

    assert components.close() is False
    assert components._closed is False
    assert service.close_calls == 1
    assert not hasattr(service, "terminate")

    assert components.close() is True
    assert components._closed is True
    assert service.close_calls == 2


def test_construction_failure_closes_created_experimental_service(
    monkeypatch, qapp, tmp_path
):
    import View as view_module

    service = _FakeExperimentalBalanceService()
    dependencies = _production_safe_dependencies(
        tmp_path / "partial-construction",
        lambda: service,
    )
    monkeypatch.setattr(
        view_module,
        "MainWindow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected view failure")
        ),
    )

    with pytest.raises(composition.ApplicationConstructionError):
        composition.build_application_components(
            CURRENT_PROFILE,
            dependencies,
            experimental_features=composition.ExperimentalFeatures(True),
        )

    assert service.close_calls == 1


def _assert_beneath(path, root):
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    assert resolved_path == resolved_root or resolved_root in resolved_path.parents


def _wait_until(qapp, predicate, timeout_ms=5000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
    assert predicate(), "condition did not become true before timeout"


def test_simulation_dependencies_create_contained_roots_and_reject_hardware(tmp_path):
    dependencies = composition.simulation_dependencies(
        tmp_path / "simulation",
        machine_factory=_safe_machine_factory,
    )

    assert dependencies.runtime_context.is_simulation is True
    for root in (
        dependencies.roots.config_root,
        dependencies.roots.experiments_root,
        dependencies.roots.calibration_memory_root,
    ):
        assert root.is_dir()
        _assert_beneath(root, tmp_path / "simulation")

    for name in (
        "serial_factory",
        "refuel_camera_factory",
        "droplet_camera_factory",
        "log_reader_factory",
        "balance_factory",
        "experimental_balance_factory",
        "legacy_calibration_model_factory",
    ):
        with pytest.raises(composition.HardwareAccessBlocked, match="Simulation mode"):
            getattr(dependencies, name)()


def test_simulation_requires_an_explicit_machine_factory(tmp_path):
    with pytest.raises(TypeError, match="machine_factory"):
        composition.simulation_dependencies(
            tmp_path / "simulation",
            machine_factory=None,
        )


def test_production_machine_factory_selects_machine_class_lazily(monkeypatch):
    captured = {}

    class _ProductionMachine:
        def __init__(self, model, **kwargs):
            captured["model"] = model
            captured["kwargs"] = kwargs

    fake_module = types.ModuleType("Machine_FreeRTOS")
    fake_module.Machine = _ProductionMachine
    monkeypatch.setitem(sys.modules, "Machine_FreeRTOS", fake_module)

    dependencies = composition.production_dependencies()
    model = object()
    machine = dependencies.machine_factory(
        model,
        profile=CURRENT_PROFILE,
        serial_factory=object(),
        refuel_camera_factory=object(),
        droplet_camera_factory=object(),
        log_reader_factory=object(),
    )

    assert isinstance(machine, _ProductionMachine)
    assert captured["model"] is model
    assert captured["kwargs"]["profile"] is CURRENT_PROFILE


def test_machine_peripheral_factories_are_additive_and_explicit(qapp):
    from Machine_FreeRTOS import Machine

    calls = []
    refuel_camera = object()
    droplet_camera = object()
    log_reader_factory = object()

    machine = Machine(
        object(),
        profile=SimpleNamespace(
            name="factory-test",
            has_refuel_camera=True,
            has_droplet_camera=True,
            has_log_channel=False,
        ),
        serial_factory=lambda *args, **kwargs: None,
        refuel_camera_factory=lambda: (
            calls.append("refuel"),
            refuel_camera,
        )[1],
        droplet_camera_factory=lambda: (
            calls.append("droplet"),
            droplet_camera,
        )[1],
        log_reader_factory=log_reader_factory,
    )

    assert calls == ["refuel", "droplet"]
    assert machine.refuel_camera is refuel_camera
    assert machine.droplet_camera is droplet_camera
    assert machine._log_reader_factory is log_reader_factory


def test_throwing_simulation_machine_fails_closed_without_production_fallback(
    monkeypatch,
    qapp,
    tmp_path,
):
    production_calls = []
    monkeypatch.setattr(
        composition,
        "_production_machine_factory",
        lambda *args, **kwargs: production_calls.append((args, kwargs)),
    )

    def fail_machine(*_args, **_kwargs):
        raise RuntimeError("injected simulation machine failure")

    dependencies = composition.simulation_dependencies(
        tmp_path / "failure",
        machine_factory=fail_machine,
    )
    with pytest.raises(
        composition.ApplicationConstructionError,
        match="injected simulation machine failure",
    ) as exc_info:
        composition.build_application_components(CURRENT_PROFILE, dependencies)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert production_calls == []


def test_real_components_construct_close_and_show_simulation_identity(
    qapp,
    tmp_path,
):
    for index in range(2):
        _dependencies, components = _build_simulation(
            tmp_path,
            suffix=f"repeat-{index}",
        )
        view = components.view
        view.show()
        qapp.processEvents()

        assert type(components.model).__name__ == "Model"
        assert type(components.controller).__name__ == "Controller"
        assert type(view).__name__ == "MainWindow"
        assert view.windowTitle().startswith("[SIMULATION - NO HARDWARE]")
        assert view.simulation_identity_banner.objectName() == "simulationIdentityBanner"
        assert (
            view.simulation_identity_label.text()
            == composition.SIMULATION_IDENTITY_TEXT
        )
        assert view.simulation_identity_banner.isVisible()
        assert not view.connection_widget.machine_connect_button.isEnabled()
        assert not view.speed_profiles_tab.firmware_update_button.isEnabled()
        assert not view.speed_profiles_tab.app_update_check_button.isEnabled()
        assert not view.speed_profiles_tab.machine_qualification_button.isEnabled()
        assert not view.speed_profiles_tab.regulator_calibration_button.isEnabled()
        assert not view.speed_profiles_tab.reset_mcu_button.isEnabled()
        assert not view.pressure_box.refuel_camera_button.isEnabled()
        assert not view.pressure_box.calibrate_pressure_button.isEnabled()
        assert not view.start_guided_optics_calibration_button.isEnabled()
        assert not view.open_manual_optics_calibration_button.isEnabled()
        assert not hasattr(view.connection_widget, "_port_timer")

        components.close()
        components.close()
        assert components._closed is True


@pytest.mark.parametrize("iteration", range(2))
def test_official_simulator_constructs_real_components_and_controller_sequence(
    qapp,
    tmp_path,
    iteration,
):
    config = SimulationConfig(
        timing=SimulationTimingPolicy(speed_multiplier=1000.0)
    )
    dependencies = composition.simulation_dependencies(
        tmp_path / f"official-simulator-{iteration}",
        machine_factory=make_simulated_machine_factory(config),
    )
    components = composition.build_application_components(
        CURRENT_PROFILE,
        dependencies,
    )
    machine = components.machine
    controller = components.controller
    model = components.model
    callbacks = []

    assert controller.connect_machine(SIMULATED_PORT)
    _wait_until(qapp, lambda: model.machine_model.is_connected())

    controller.toggle_motors()
    controller.home_machine()
    _wait_until(qapp, machine.check_if_all_completed)
    assert model.machine_model.motors_are_enabled()
    assert model.machine_model.motors_are_homed()

    assert controller.toggle_regulation()
    _wait_until(qapp, machine.check_if_all_completed)
    assert model.machine_model.regulating_print_pressure is True
    assert model.machine_model.regulating_refuel_pressure is True

    assert controller.set_absolute_XY(1200, 3400, override=True) is True
    assert machine.wait_ms(5)
    assert controller.print_droplets(
        3,
        handler=lambda: callbacks.append("dispensed"),
    )
    _wait_until(qapp, machine.check_if_all_completed)

    assert callbacks == ["dispensed"]
    assert model.machine_model.regulating_print_pressure is True
    assert model.machine_model.regulating_refuel_pressure is True
    assert model.machine_model.get_current_position_dict()["X"] == 1200
    assert model.machine_model.get_current_position_dict()["Y"] == 3400
    assert machine.state.x == 1200
    assert machine.state.y == 3400
    assert machine.ser is None

    components.close()


def test_production_runtime_does_not_show_simulation_identity(qapp, tmp_path):
    simulation = composition.simulation_dependencies(
        tmp_path / "production-ui",
        machine_factory=_safe_machine_factory,
    )
    dependencies = composition.ApplicationDependencies(
        runtime_context=composition.PRODUCTION_RUNTIME_CONTEXT,
        roots=simulation.roots,
        machine_factory=simulation.machine_factory,
        serial_factory=simulation.serial_factory,
        refuel_camera_factory=simulation.refuel_camera_factory,
        droplet_camera_factory=simulation.droplet_camera_factory,
        log_reader_factory=simulation.log_reader_factory,
        balance_factory=simulation.balance_factory,
        experimental_balance_factory=simulation.experimental_balance_factory,
        legacy_calibration_model_factory=simulation.legacy_calibration_model_factory,
    )
    components = composition.build_application_components(
        CURRENT_PROFILE,
        dependencies,
    )

    assert not components.view.windowTitle().startswith("[SIMULATION")
    assert not hasattr(components.view, "simulation_identity_banner")
    assert components.view.connection_widget.machine_connect_button.isEnabled()
    assert components.view.speed_profiles_tab.firmware_update_button.isEnabled()

    components.close()


def test_simulation_configuration_and_experiment_writes_use_supplied_roots(
    qapp,
    tmp_path,
):
    dependencies, components = _build_simulation(tmp_path, suffix="roots")
    model = components.model
    config_root = dependencies.roots.config_root
    experiments_root = dependencies.roots.experiments_root
    calibration_root = dependencies.roots.calibration_memory_root

    for path in (
        model.locations_path,
        model.plates_path,
        model.settings_path,
        model.obstacles_path,
        model.regulator_profiles_path,
    ):
        _assert_beneath(path, config_root)
        assert Path(path).is_file()

    _assert_beneath(model.calibration_memory_store.root_dir, calibration_root)
    assert Path(model.calibration_memory_store.root_dir).is_dir()

    model.experiment_model.metadata["name"] = "slice3-construction"
    model.experiment_model.initialize_experiment()
    _assert_beneath(model.experiment_model.experiment_dir_path, experiments_root)
    assert model.experiment_model.rename_experiment("slice3-renamed")
    _assert_beneath(model.experiment_model.experiment_dir_path, experiments_root)

    components.close()


def test_local_config_explicit_roots_do_not_change_production_defaults(tmp_path):
    assert (
        LocalConfig.get_machine_config_path("Settings.json")
        == LocalConfig.LOCAL_DIR / "Settings.json"
    )
    assert (
        LocalConfig.get_calibration_memory_root()
        == LocalConfig.LOCAL_DIR / "CalibrationMemory"
    )

    explicit_config = tmp_path / "config"
    explicit_calibration = tmp_path / "calibration"
    assert LocalConfig.get_machine_config_path(
        "Settings.json",
        local_root=explicit_config,
    ) == explicit_config / "Settings.json"
    assert LocalConfig.get_calibration_memory_root(
        local_root=explicit_calibration,
    ) == explicit_calibration


def test_controller_rejects_physical_and_updater_actions_in_simulation(
    qapp,
    tmp_path,
):
    _dependencies, components = _build_simulation(tmp_path, suffix="guards")
    controller = components.controller
    machine = components.machine
    messages = []

    controller.error_occurred_signal.disconnect()
    controller.error_occurred_signal.connect(
        lambda title, message: messages.append((title, message))
    )

    controller.update_available_ports()
    controller.connect_machine("COM_TEST")
    controller.disconnect_machine()
    controller.connect_balance("COM_BALANCE")
    controller.disconnect_balance()
    controller.start_firmware_update()
    assert controller.start_app_update_check()[0] is False
    assert controller.start_app_rollback_check()[0] is False
    assert controller.launch_app_updater(123)[0] is False
    assert controller.launch_app_rollback(123)[0] is False
    assert controller.start_qualification_run({}) is False
    assert controller.start_regulator_calibration_run({}) is False
    assert controller.start_regulator_calibration_sweep({}) is False
    assert controller.start_regulator_calibration_batch({}) is False
    controller.reset_mcu_board()
    controller.start_refuel_camera()
    assert controller.capture_refuel_image() is None
    frame, context = controller.capture_refuel_image_with_context()
    assert frame is None
    assert "blocked_reason" in context
    controller.stop_refuel_camera()
    controller.start_droplet_camera()
    assert controller.capture_droplet_image() is False

    assert machine.calls == [("disconnect_board", ())]
    assert messages
    assert all(title == "Simulation Mode" for title, _message in messages)
    assert all("no physical hardware" in message for _title, message in messages)
    assert any(
        "application update or rollback" in blocker
        for blocker in controller.get_app_update_blockers()
    )

    components.close()
