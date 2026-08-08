"""Application construction with explicit production or simulation dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from PySide6.QtCore import QCoreApplication

from hardware.profile import HardwareProfile


SIMULATION_IDENTITY_TEXT = "SIMULATION — NO HARDWARE CONNECTED"


EXPERIMENTAL_BALANCE_ENV = "LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE"


class RuntimeMode(str, Enum):
    PRODUCTION = "production"
    SIMULATION = "simulation"


@dataclass(frozen=True)
class RuntimeContext:
    mode: RuntimeMode
    identity_text: str = ""

    @property
    def is_simulation(self) -> bool:
        return self.mode is RuntimeMode.SIMULATION

    @property
    def hardware_access_allowed(self) -> bool:
        return not self.is_simulation

    def blocked_message(self, action: str) -> str:
        return (
            f"Simulation mode blocks {str(action).strip() or 'this action'}; "
            "no physical hardware or updater action was attempted."
        )


PRODUCTION_RUNTIME_CONTEXT = RuntimeContext(RuntimeMode.PRODUCTION)
SIMULATION_RUNTIME_CONTEXT = RuntimeContext(
    RuntimeMode.SIMULATION,
    SIMULATION_IDENTITY_TEXT,
)


@dataclass(frozen=True)
class ExperimentalFeatures:
    balance_integration: bool = False

    def __post_init__(self):
        if not isinstance(self.balance_integration, bool):
            raise TypeError("balance_integration must be a bool")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str]
    ) -> "ExperimentalFeatures":
        if not isinstance(environment, Mapping):
            raise TypeError("environment must be a mapping")
        return cls(
            balance_integration=(
                environment.get(EXPERIMENTAL_BALANCE_ENV) == "1"
            )
        )


@dataclass(frozen=True)
class ApplicationRoots:
    config_root: Path | None = None
    experiments_root: Path | None = None
    calibration_memory_root: Path | None = None

    @classmethod
    def production(cls) -> "ApplicationRoots":
        return cls()

    @classmethod
    def beneath(cls, run_root: str | Path) -> "ApplicationRoots":
        root = Path(run_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        children = cls(
            config_root=root / "config",
            experiments_root=root / "experiments",
            calibration_memory_root=root / "calibration-memory",
        )
        for path in (
            children.config_root,
            children.experiments_root,
            children.calibration_memory_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
            if root not in path.resolve().parents:
                raise ValueError(f"Application root escaped simulation run root: {path}")
        return children


Factory = Callable[..., Any]


@dataclass(frozen=True)
class ApplicationDependencies:
    runtime_context: RuntimeContext
    roots: ApplicationRoots
    machine_factory: Factory
    serial_factory: Factory
    refuel_camera_factory: Factory
    droplet_camera_factory: Factory
    log_reader_factory: Factory
    balance_factory: Factory
    experimental_balance_factory: Factory
    legacy_calibration_model_factory: Factory

    def __post_init__(self):
        factories = (
            "machine_factory",
            "serial_factory",
            "refuel_camera_factory",
            "droplet_camera_factory",
            "log_reader_factory",
            "balance_factory",
            "experimental_balance_factory",
            "legacy_calibration_model_factory",
        )
        for name in factories:
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")
        if self.runtime_context.is_simulation:
            missing = [
                name
                for name in (
                    "config_root",
                    "experiments_root",
                    "calibration_memory_root",
                )
                if getattr(self.roots, name) is None
            ]
            if missing:
                raise ValueError(
                    "Simulation dependencies require explicit roots: "
                    + ", ".join(missing)
                )


class ApplicationConstructionError(RuntimeError):
    """Raised when explicit application dependencies cannot be constructed."""


class HardwareAccessBlocked(RuntimeError):
    """Raised by rejecting simulation dependency factories."""


@dataclass
class ApplicationComponents:
    model: Any
    machine: Any
    controller: Any
    view: Any
    balance: Any = None
    balance_service: Any = None
    experimental_features: ExperimentalFeatures = ExperimentalFeatures()
    _closed: bool = False

    def close(self):
        """Release Qt-owned construction objects without initiating hardware work."""
        if self._closed:
            return True
        if not _close_experimental_balance_service(self.balance_service):
            return False
        self._closed = True

        timers = (
            getattr(getattr(self.view, "connection_widget", None), "_port_timer", None),
            getattr(self.controller, "_seq_timer", None),
            getattr(self.controller, "pending_capture_guard_timer", None),
            getattr(self.view, "_close_disconnect_timer", None),
        )
        for timer in timers:
            stop = getattr(timer, "stop", None)
            if callable(stop):
                try:
                    stop()
                except RuntimeError:
                    pass

        hide = getattr(self.view, "hide", None)
        if callable(hide):
            try:
                hide()
            except RuntimeError:
                pass

        for obj in (
            self.view,
            self.controller,
            self.balance,
            self.balance_service,
            self.machine,
            self.model,
        ):
            delete_later = getattr(obj, "deleteLater", None)
            if callable(delete_later):
                try:
                    delete_later()
                except RuntimeError:
                    pass

        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        return True


def _blocked_factory(label: str) -> Factory:
    def _blocked(*_args, **_kwargs):
        raise HardwareAccessBlocked(
            SIMULATION_RUNTIME_CONTEXT.blocked_message(label)
        )

    _blocked.__name__ = f"blocked_{label.replace(' ', '_')}"
    return _blocked


def _production_machine_factory(model, *, profile, **peripheral_factories):
    from Machine_FreeRTOS import Machine

    return Machine(model, profile=profile, **peripheral_factories)


def _production_serial_factory(*args, **kwargs):
    import serial

    return serial.Serial(*args, **kwargs)


def _production_refuel_camera_factory(*args, **kwargs):
    from Machine_FreeRTOS import RefuelCamera

    return RefuelCamera(*args, **kwargs)


def _production_droplet_camera_factory(*args, **kwargs):
    from Machine_FreeRTOS import DropletCamera

    return DropletCamera(*args, **kwargs)


def _production_log_reader_factory(*args, **kwargs):
    from Machine_FreeRTOS import LogReader

    return LogReader(*args, **kwargs)


def _production_balance_factory(*, machine, model):
    from legacy.mass_calibration import Balance

    return Balance(machine=machine, model=model)


def _production_experimental_balance_factory():
    from BalanceService import BalanceService

    return BalanceService()


def _production_legacy_calibration_model_factory(model):
    from legacy.mass_calibration import MassCalibrationModel

    return MassCalibrationModel(
        machine_model=model.machine_model,
        printer_head_manager=model.printer_head_manager,
        rack_model=model.rack_model,
        prediction_model_dir=model.predictive_model_dir,
    )


def production_dependencies() -> ApplicationDependencies:
    return ApplicationDependencies(
        runtime_context=PRODUCTION_RUNTIME_CONTEXT,
        roots=ApplicationRoots.production(),
        machine_factory=_production_machine_factory,
        serial_factory=_production_serial_factory,
        refuel_camera_factory=_production_refuel_camera_factory,
        droplet_camera_factory=_production_droplet_camera_factory,
        log_reader_factory=_production_log_reader_factory,
        balance_factory=_production_balance_factory,
        experimental_balance_factory=_production_experimental_balance_factory,
        legacy_calibration_model_factory=_production_legacy_calibration_model_factory,
    )


def simulation_dependencies(
    run_root: str | Path,
    *,
    machine_factory: Factory,
) -> ApplicationDependencies:
    if not callable(machine_factory):
        raise TypeError("Simulation construction requires an explicit machine_factory")
    return ApplicationDependencies(
        runtime_context=SIMULATION_RUNTIME_CONTEXT,
        roots=ApplicationRoots.beneath(run_root),
        machine_factory=machine_factory,
        serial_factory=_blocked_factory("serial access"),
        refuel_camera_factory=_blocked_factory("refuel camera access"),
        droplet_camera_factory=_blocked_factory("droplet camera access"),
        log_reader_factory=_blocked_factory("log-reader access"),
        balance_factory=_blocked_factory("balance access"),
        experimental_balance_factory=_blocked_factory(
            "experimental balance access"
        ),
        legacy_calibration_model_factory=_blocked_factory(
            "legacy calibration hardware access"
        ),
    )


def _close_experimental_balance_service(balance_service) -> bool:
    if balance_service is None:
        return True
    close = getattr(balance_service, "close", None)
    if not callable(close):
        print("Experimental balance service has no close() method")
        return False
    try:
        result = close()
    except Exception as exc:
        print(
            "Experimental balance service shutdown failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return False
    if result is not None and not bool(getattr(result, "accepted", True)):
        detail = str(getattr(result, "detail", "shutdown was rejected"))
        print(f"Experimental balance service shutdown rejected: {detail}")
        return False
    return True


def _delete_partial_objects(*objects, balance_service=None):
    balance_service_closed = _close_experimental_balance_service(balance_service)
    if not balance_service_closed:
        print(
            "Experimental balance service remains open after construction "
            "failure; no forced thread termination was attempted."
        )
    cleanup_objects = list(objects)
    if balance_service_closed and balance_service is not None:
        cleanup_objects.append(balance_service)
    for obj in cleanup_objects:
        delete_later = getattr(obj, "deleteLater", None)
        if callable(delete_later):
            try:
                delete_later()
            except RuntimeError:
                pass
    app = QCoreApplication.instance()
    if app is not None:
        app.processEvents()


def _effective_experimental_features(
    profile: HardwareProfile,
    dependencies: ApplicationDependencies,
    requested: ExperimentalFeatures,
) -> ExperimentalFeatures:
    return ExperimentalFeatures(
        balance_integration=(
            requested.balance_integration
            and dependencies.runtime_context.mode is RuntimeMode.PRODUCTION
            and profile.name == "current"
        )
    )


def build_application_components(
    profile: HardwareProfile,
    dependencies: ApplicationDependencies,
    *,
    model_setup: Callable[[Any], None] | None = None,
    experimental_features: ExperimentalFeatures = ExperimentalFeatures(),
) -> ApplicationComponents:
    """Construct the real MVC objects using only the supplied dependencies."""
    from Controller import Controller
    from Model import Model
    from View import MainWindow

    if not isinstance(experimental_features, ExperimentalFeatures):
        raise TypeError("experimental_features must be ExperimentalFeatures")

    effective_features = _effective_experimental_features(
        profile,
        dependencies,
        experimental_features,
    )

    model = machine = controller = balance = balance_service = view = None
    try:
        roots = dependencies.roots
        model = Model(
            profile=profile,
            config_root=roots.config_root,
            experiments_root=roots.experiments_root,
            calibration_memory_root=roots.calibration_memory_root,
        )
        if model_setup is not None:
            model_setup(model)
        machine_kwargs = {
            "profile": profile,
            "serial_factory": dependencies.serial_factory,
            "refuel_camera_factory": dependencies.refuel_camera_factory,
            "droplet_camera_factory": dependencies.droplet_camera_factory,
            "log_reader_factory": dependencies.log_reader_factory,
        }
        if (
            dependencies.runtime_context.mode is RuntimeMode.PRODUCTION
            and profile.has_log_channel
        ):
            machine_kwargs["machine_log_port"] = (
                model.get_default_machine_log_port()
            )
        machine = dependencies.machine_factory(model, **machine_kwargs)
        if effective_features.balance_integration:
            balance_service = dependencies.experimental_balance_factory()
        controller = Controller(
            machine,
            model,
            profile=profile,
            runtime_context=dependencies.runtime_context,
            experimental_features=effective_features,
            experimental_balance_service=balance_service,
        )

        if profile.name == "legacy":
            model.calibration_model = dependencies.legacy_calibration_model_factory(
                model
            )
            balance = dependencies.balance_factory(machine=machine, model=model)
            controller.balance = balance
            balance.balance_mass_updated_signal.connect(
                model.calibration_model.update_mass
            )
            balance.connected_signal.connect(
                lambda ok: (
                    model.machine_model.connect_balance()
                    if ok
                    else model.machine_model.disconnect_balance()
                )
            )
            balance.balance_error_signal.connect(
                controller.error_occurred_signal.emit
            )

        view = MainWindow(
            model,
            controller,
            profile=profile,
            runtime_context=dependencies.runtime_context,
        )
        return ApplicationComponents(
            model=model,
            machine=machine,
            controller=controller,
            view=view,
            balance=balance,
            balance_service=balance_service,
            experimental_features=effective_features,
        )
    except Exception as exc:
        _delete_partial_objects(
            view,
            controller,
            balance,
            machine,
            model,
            balance_service=balance_service,
        )
        if isinstance(exc, ApplicationConstructionError):
            raise
        raise ApplicationConstructionError(
            f"Could not construct {dependencies.runtime_context.mode.value} "
            f"application components: {exc}"
        ) from exc
