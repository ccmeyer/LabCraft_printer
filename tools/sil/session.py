"""Reusable lifecycle for the real application running against SimulatedMachine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
from typing import Any
import uuid

from PySide6 import QtCore, QtWidgets


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from ApplicationComposition import (  # noqa: E402
    ApplicationRoots,
    SIMULATION_RUNTIME_CONTEXT,
    build_application_components,
    simulation_dependencies,
)
from hardware.profile import CURRENT_PROFILE  # noqa: E402
from simulation import (  # noqa: E402
    SIMULATED_PORT,
    SimulationConfig,
    SimulationTimingPolicy,
    make_simulated_machine_factory,
)

from .control import SimulatorControlDock
from .calibration_application import SyntheticCalibrationApplicationAdapter
from .manual_refuel import SimulatedManualRefuelOutcomeAdapter
from .inspector import StateInspectorDock
from .state_observer import SimulationStateObserver
from .state_projection import StateProjectionBuilder
from .state_recorder import StateRecorder, StateRecorderError


SESSION_SCHEMA_ID = "labcraft.sil_simulation_session"
SESSION_SCHEMA_VERSION = 1
SESSION_FILENAME = "session.json"
LOCK_FILENAME = "session.lock"
DEFAULT_SEED = 1
DEFAULT_SPEED_MULTIPLIER = 1.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_session_parent() -> Path:
    """Return the local, application-owned interactive simulation root."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    elif os.name == "nt":
        base = Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "share"
    return (base / "LabCraft" / "SIL" / "interactive-sessions").resolve()


class QtOwnership(str, Enum):
    OWNED = "owned"
    BORROWED = "borrowed"


class SessionRootPolicy(str, Enum):
    FRESH = "fresh"
    RETAINED = "retained"


class ArtifactRetentionPolicy(str, Enum):
    DELETE_CLEAN_FRESH = "delete_clean_fresh"
    RETAIN = "retain"


class SimulationSessionError(RuntimeError):
    """A fail-closed session construction or lifecycle error."""

    def __init__(self, message: str, *, session_root: Path | None = None):
        super().__init__(message)
        self.session_root = session_root


@dataclass(frozen=True)
class SimulationSessionConfigV1:
    """Frozen configuration contract for Milestone 1 simulation sessions."""

    visible: bool = True
    qt_ownership: QtOwnership = QtOwnership.OWNED
    root_policy: SessionRootPolicy = SessionRootPolicy.FRESH
    session_root: Path | None = None
    retained_experiment: Path | None = None
    seed: int = DEFAULT_SEED
    speed_multiplier: float = DEFAULT_SPEED_MULTIPLIER
    dialog_policy: str = "interactive"
    automation_deadline_seconds: float | None = None
    artifact_retention: ArtifactRetentionPolicy = (
        ArtifactRetentionPolicy.DELETE_CLEAN_FRESH
    )
    source_identity: str = "local-worktree"
    expected_runtime_mode: str = "simulation"

    def __post_init__(self):
        try:
            qt_ownership = QtOwnership(self.qt_ownership)
            root_policy = SessionRootPolicy(self.root_policy)
            retention = ArtifactRetentionPolicy(self.artifact_retention)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "qt_ownership", qt_ownership)
        object.__setattr__(self, "root_policy", root_policy)
        object.__setattr__(self, "artifact_retention", retention)

        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.seed < 0 or self.seed > (2**63 - 1):
            raise ValueError("seed must be between 0 and 2^63-1")

        speed = float(self.speed_multiplier)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_multiplier must be finite and greater than zero")
        object.__setattr__(self, "speed_multiplier", speed)

        if self.dialog_policy != "interactive":
            raise ValueError("Milestone 1 supports only the interactive dialog policy")
        if self.automation_deadline_seconds is not None:
            deadline = float(self.automation_deadline_seconds)
            if not math.isfinite(deadline) or deadline <= 0:
                raise ValueError(
                    "automation_deadline_seconds must be finite and greater than zero"
                )
            object.__setattr__(self, "automation_deadline_seconds", deadline)

        if str(self.source_identity).strip() == "":
            raise ValueError("source_identity must not be empty")
        if self.expected_runtime_mode != "simulation":
            raise ValueError("expected_runtime_mode must be 'simulation'")

        root = self.session_root
        if root_policy is SessionRootPolicy.FRESH:
            if root is not None:
                raise ValueError("fresh sessions allocate their own session_root")
        else:
            if root is None:
                raise ValueError("retained sessions require session_root")
            root_path = Path(root).expanduser()
            if not root_path.is_absolute():
                raise ValueError("retained session_root must be absolute")
            object.__setattr__(self, "session_root", root_path.resolve())
            if retention is not ArtifactRetentionPolicy.RETAIN:
                raise ValueError("retained sessions must use artifact_retention='retain'")

        retained_experiment = self.retained_experiment
        if retained_experiment is not None:
            experiment_path = Path(retained_experiment).expanduser()
            if not experiment_path.is_absolute():
                raise ValueError("retained_experiment must be absolute")
            object.__setattr__(
                self,
                "retained_experiment",
                experiment_path.resolve(),
            )


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second
        or first in second.parents
        or second in first.parents
    )


def _validate_safe_session_root(root: Path) -> None:
    resolved = root.expanduser().resolve()
    anchor = Path(resolved.anchor).resolve()
    home = Path.home().resolve()
    production_roots = (
        REPO_ROOT.resolve(),
        (REPO_ROOT / "local").resolve(),
        (UI_ROOT / "Experiments").resolve(),
    )

    if resolved == anchor:
        raise ValueError("session_root must not be a drive or filesystem root")
    if resolved == home:
        raise ValueError("session_root must not be the user home directory")
    for protected in production_roots:
        if _paths_overlap(resolved, protected):
            raise ValueError(
                f"session_root overlaps repository or production data: {protected}"
            )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}_",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class SimulationSession:
    """Own the application, simulator, roots, evidence, and teardown."""

    def __init__(self, config: SimulationSessionConfigV1):
        self.config = config
        self.session_root: Path | None = None
        self.application_roots: ApplicationRoots | None = None
        self.session_id: str | None = None
        self.application_session_id = uuid.uuid4().hex
        self.rng = random.Random(config.seed)
        self.app: QtWidgets.QApplication | None = None
        self.components = None
        self.control: SimulatorControlDock | None = None
        self.inspector: StateInspectorDock | None = None
        self.recorder: StateRecorder | None = None
        self.calibration_adapter: SyntheticCalibrationApplicationAdapter | None = None
        self.manual_refuel_adapter: SimulatedManualRefuelOutcomeAdapter | None = None
        self.projector: StateProjectionBuilder | None = None
        self.observer: SimulationStateObserver | None = None
        self._lock: QtCore.QLockFile | None = None
        self._metadata: dict[str, Any] | None = None
        self._default_parent: Path | None = None
        self._launched = False
        self._closed = False
        self._close_succeeded: bool | None = None
        self._failure_reason: str | None = None
        self._machine_signal_connected = False
        self._root_removed = False
        self._pending_connection_action: tuple[str, str] | None = None

    @classmethod
    def create(cls, config: SimulationSessionConfigV1) -> "SimulationSession":
        if not isinstance(config, SimulationSessionConfigV1):
            raise TypeError("config must be a SimulationSessionConfigV1")
        session = cls(config)
        try:
            session._create()
        except Exception as exc:
            session._abort_create(exc)
            if isinstance(exc, SimulationSessionError):
                raise
            raise SimulationSessionError(
                f"Could not create simulation session: {exc}",
                session_root=session.session_root,
            ) from exc
        return session

    @property
    def root_removed(self) -> bool:
        return self._root_removed

    @property
    def close_succeeded(self) -> bool | None:
        return self._close_succeeded

    def _create(self) -> None:
        self.session_root = self._select_and_prepare_root()
        self._acquire_lock()
        self._load_or_initialize_metadata()
        self._append_application_session("constructing")
        self._write_metadata()
        self._append_log("constructing real application with simulation dependencies")

        self.app = self._establish_qapplication()
        simulation_config = SimulationConfig(
            timing=SimulationTimingPolicy(
                speed_multiplier=self.config.speed_multiplier,
            )
        )
        dependencies = simulation_dependencies(
            self.session_root,
            machine_factory=make_simulated_machine_factory(simulation_config),
        )
        self.application_roots = dependencies.roots
        self.components = build_application_components(
            CURRENT_PROFILE,
            dependencies,
        )
        if self.components.controller.runtime_context is not SIMULATION_RUNTIME_CONTEXT:
            raise SimulationSessionError(
                "constructed Controller is not in the canonical simulation runtime",
                session_root=self.session_root,
            )

        self.recorder = StateRecorder(
            session_root=self.session_root,
            session_id=self.session_id,
            application_session_id=self.application_session_id,
            on_failure=self._on_recorder_failure,
        )
        self.projector = StateProjectionBuilder(self)
        self.observer = SimulationStateObserver(
            recorder=self.recorder,
            projector=self.projector,
            machine=self.components.machine,
            controller=self.components.controller,
            model=self.components.model,
            on_failure=self._on_recorder_failure,
            action_id_provider=self._pending_action_id,
        )
        if self.recorder.healthy:
            self.observer.install()
        self.calibration_adapter = SyntheticCalibrationApplicationAdapter(
            session_root=self.session_root,
            session_id=self.session_id,
            application_session_id=self.application_session_id,
            seed=self.config.seed,
            model=self.components.model,
            controller=self.components.controller,
            machine=self.components.machine,
            recorder=self.recorder,
            open_dialog_callback=(
                self.components.view.pressure_box.open_simulated_calibration_result
            ),
            snapshot_callback=self.snapshot,
            failure_callback=self.mark_failed,
        )
        self.manual_refuel_adapter = SimulatedManualRefuelOutcomeAdapter(
            seed=self.config.seed,
            model=self.components.model,
            controller=self.components.controller,
            machine=self.components.machine,
            recorder=self.recorder,
            snapshot_callback=self.snapshot,
            failure_callback=self.mark_failed,
        )
        self._update_recorder_metadata()

        self.components.machine.machine_connected_signal.connect(
            self._on_machine_connection_changed
        )
        self._machine_signal_connected = True
        self._set_application_session_status("constructed")
        self._metadata["terminal_status"] = "active"
        self._write_metadata()

    def _select_and_prepare_root(self) -> Path:
        if self.config.root_policy is SessionRootPolicy.FRESH:
            parent = default_session_parent()
            _validate_safe_session_root(parent)
            parent.mkdir(parents=True, exist_ok=True)
            self._default_parent = parent
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            root = (parent / f"{stamp}-{uuid.uuid4().hex[:12]}").resolve()
            _validate_safe_session_root(root)
            root.mkdir(parents=False, exist_ok=False)
            return root

        root = Path(self.config.session_root).resolve()
        _validate_safe_session_root(root)
        if root.exists():
            if not root.is_dir():
                raise ValueError("retained session_root must be a directory")
            entries = list(root.iterdir())
            if entries and not (root / SESSION_FILENAME).is_file():
                raise ValueError(
                    "nonempty retained session_root is missing a valid session.json marker"
                )
        else:
            root.mkdir(parents=True, exist_ok=False)
        return root

    def _acquire_lock(self) -> None:
        lock = QtCore.QLockFile(str(self.session_root / LOCK_FILENAME))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise SimulationSessionError(
                f"Simulation session is already locked: {self.session_root}",
                session_root=self.session_root,
            )
        self._lock = lock

    def _load_or_initialize_metadata(self) -> None:
        marker = self.session_root / SESSION_FILENAME
        (self.session_root / "logs").mkdir(parents=True, exist_ok=True)
        (self.session_root / "artifacts").mkdir(parents=True, exist_ok=True)
        roots = {
            "config": "config",
            "experiments": "experiments",
            "calibration_memory": "calibration-memory",
        }

        if marker.exists():
            try:
                metadata = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"could not read retained session marker: {exc}") from exc
            if metadata.get("schema_id") != SESSION_SCHEMA_ID:
                raise ValueError("retained session marker has the wrong schema_id")
            if metadata.get("schema_version") != SESSION_SCHEMA_VERSION:
                raise ValueError("retained session marker has an unsupported schema_version")
            if metadata.get("runtime_mode") != "simulation":
                raise ValueError("retained session marker is not a simulation session")
            if metadata.get("application_roots") != roots:
                raise ValueError("retained session application roots do not match v1")
            safety = metadata.get("safety") or {}
            if safety.get("hardware_access_allowed") is not False:
                raise ValueError("retained session does not prove hardware isolation")
            session_id = str(metadata.get("session_id") or "").strip()
            if not session_id:
                raise ValueError("retained session marker is missing session_id")
            self.session_id = session_id
            self._metadata = metadata
        else:
            self.session_id = uuid.uuid4().hex
            self._metadata = {
                "schema_id": SESSION_SCHEMA_ID,
                "schema_version": SESSION_SCHEMA_VERSION,
                "session_id": self.session_id,
                "created_at": _utc_now(),
                "source_identity": self.config.source_identity,
                "runtime_mode": "simulation",
                "root_policy": self.config.root_policy.value,
                "containment": {
                    "validated": True,
                    "all_application_roots_relative": True,
                },
                "application_roots": roots,
                "safety": {
                    "hardware_access_allowed": False,
                    "serial_allowed": False,
                    "physical_cameras_allowed": False,
                    "balance_allowed": False,
                    "firmware_or_updater_allowed": False,
                },
                "simulator": {
                    "port": SIMULATED_PORT,
                    "seed": self.config.seed,
                    "speed_multiplier": self.config.speed_multiplier,
                    "profile": CURRENT_PROFILE.name,
                },
                "retained_experiment": None,
                "application_sessions": [],
                "artifact_map": {
                    "launcher_log": "logs/launcher.log",
                    "session_metadata": SESSION_FILENAME,
                    "artifacts_root": "artifacts",
                },
                "latest_snapshot": None,
                "terminal_status": "constructing",
                "cleanup": {
                    "status": "pending",
                    "root_retained": True,
                    "root_removal_planned": False,
                },
            }

        retained_experiment = self.config.retained_experiment
        if retained_experiment is not None:
            experiments_root = (self.session_root / "experiments").resolve()
            experiment = retained_experiment.resolve()
            if experiment != experiments_root and experiments_root not in experiment.parents:
                raise ValueError(
                    "retained_experiment must remain beneath the session experiments root"
                )
            if not experiment.exists():
                raise ValueError("retained_experiment does not exist")
            self._metadata["retained_experiment"] = experiment.relative_to(
                self.session_root
            ).as_posix()

    def _append_application_session(self, status: str) -> None:
        self._metadata.setdefault("application_sessions", []).append(
            {
                "application_session_id": self.application_session_id,
                "started_at": _utc_now(),
                "ended_at": None,
                "status": status,
            }
        )

    def _application_session_record(self) -> dict[str, Any]:
        for record in reversed(self._metadata.get("application_sessions", [])):
            if record.get("application_session_id") == self.application_session_id:
                return record
        raise RuntimeError("application session record is missing")

    def _set_application_session_status(self, status: str) -> None:
        self._application_session_record()["status"] = status

    def _write_metadata(self) -> None:
        _atomic_write_json(self.session_root / SESSION_FILENAME, self._metadata)

    def _pending_action_id(self) -> str | None:
        pending = self._pending_connection_action
        return pending[0] if pending is not None else None

    def _on_recorder_failure(self, reason: str) -> None:
        text = str(reason).strip() or "state recorder failed"
        self.mark_failed(text)
        if self.observer is not None:
            try:
                self.observer.dispose()
            except Exception:
                pass
        try:
            self._append_log(f"STATE RECORDER FAILED: {text}")
        except OSError:
            pass

    def _update_recorder_metadata(self) -> None:
        if self._metadata is None or self.recorder is None:
            return
        health = self.recorder.health_snapshot()
        recorder_record = {
            "schema_version": health["schema_version"],
            "recorder_version": health["recorder_version"],
            "status": health["status"],
            "failure": health["failure"],
            "artifacts": self.recorder.artifact_map(),
            "last_event_sequence": health["last_event_sequence"],
            "event_count": health["event_count"],
            "retained_memory_count": health["retained_memory_count"],
            "evicted_memory_count": health["evicted_memory_count"],
        }
        self._metadata["state_recorder"] = recorder_record
        self._application_session_record()["state_recorder"] = dict(
            recorder_record
        )
        self._metadata.setdefault("artifact_map", {})[
            "state_traces_root"
        ] = "artifacts/state"
        self._metadata.setdefault("artifact_map", {})[
            "synthetic_calibration_root"
        ] = "artifacts/synthetic-calibration"

    def _append_log(self, message: str) -> None:
        if self.session_root is None:
            return
        log_path = self.session_root / "logs" / "launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{_utc_now()} {message}\n")

    def _establish_qapplication(self) -> QtWidgets.QApplication:
        existing = QtWidgets.QApplication.instance()
        if self.config.qt_ownership is QtOwnership.OWNED:
            if existing is not None:
                raise ValueError(
                    "qt_ownership='owned' requires no existing QApplication"
                )
            app = QtWidgets.QApplication([sys.argv[0]])
            app.setOrganizationName("LabCraft")
            app.setApplicationName("LabCraft Simulator")
            display_name = getattr(app, "setApplicationDisplayName", None)
            if callable(display_name):
                display_name("LabCraft Simulator")
            try:
                from App import set_dark_theme

                set_dark_theme(app)
            except Exception as exc:
                self._append_log(f"dark theme setup failed: {exc}")
            return app

        if existing is None:
            raise ValueError(
                "qt_ownership='borrowed' requires an existing QApplication"
            )
        return existing

    def launch(self):
        self._require_open()
        if self._launched:
            return self.components.view
        self.inspector = StateInspectorDock(
            parent=self.components.view,
            recorder=self.recorder,
            export_snapshot_callback=self.export_state_snapshot,
        )
        self.components.view.addDockWidget(
            QtCore.Qt.LeftDockWidgetArea,
            self.inspector,
        )
        self.inspector.hide()
        self.control = SimulatorControlDock(
            parent=self.components.view,
            machine=self.components.machine,
            session_id=self.session_id,
            session_root=str(self.session_root),
            seed=self.config.seed,
            speed_multiplier=self.config.speed_multiplier,
            connect_callback=self.connect_simulator,
            disconnect_callback=self.disconnect_simulator,
            show_inspector_callback=self.show_state_inspector,
            export_snapshot_callback=self.export_state_snapshot,
            generate_calibration_callback=(
                self.calibration_adapter.generate_and_present
            ),
            calibration_availability_callback=self.calibration_adapter.availability,
            record_refuel_outcome_callback=(
                self.manual_refuel_adapter.record_outcome
            ),
            refuel_availability_callback=self.manual_refuel_adapter.availability,
        )
        self.components.view.addDockWidget(
            QtCore.Qt.RightDockWidgetArea,
            self.control,
        )
        self.calibration_adapter.set_status_changed_callback(
            self.control.set_calibration_status
        )
        self.manual_refuel_adapter.set_status_changed_callback(
            self.control.set_refuel_status
        )
        if self.config.visible:
            self.components.view.show()
        else:
            self.components.view.hide()
        self.app.processEvents()
        self._launched = True
        self._set_application_session_status("launched")
        self._append_log("application launched")
        if self.recorder.healthy:
            self.snapshot("launch", include_persistence=True)
        return self.components.view

    def run(self) -> int:
        self._require_open()
        if self.config.qt_ownership is not QtOwnership.OWNED:
            raise RuntimeError("run() is available only when the session owns QApplication")
        if not self._launched:
            self.launch()
        try:
            result = int(self.app.exec())
        except Exception as exc:
            self.mark_failed(f"Qt event loop failed: {exc}")
            raise
        if result != 0:
            self.mark_failed(f"Qt event loop returned {result}")
        return result

    def connect_simulator(self):
        self._require_open()
        self._append_log(f"requesting connection to {SIMULATED_PORT}")
        action_id = self._begin_connection_action("connect_simulator")
        result = self.components.controller.connect_machine(SIMULATED_PORT)
        if result is False:
            self._complete_connection_action(
                connected=False,
                outcome="rejected",
                expected_action_id=action_id,
            )
        return result

    def disconnect_simulator(self):
        self._require_open()
        self._append_log("requesting simulator disconnect")
        action_id = self._begin_connection_action("disconnect_simulator")
        result = self.components.controller.disconnect_machine()
        if result is False:
            self._complete_connection_action(
                connected=bool(self.components.machine.state.connected),
                outcome="rejected",
                expected_action_id=action_id,
            )
        return result

    def _begin_connection_action(self, action_kind: str) -> str | None:
        if self.recorder is None or not self.recorder.healthy:
            return None
        try:
            action_id = self.recorder.begin_action(
                action_kind,
                source_layer="session",
            )
            self._pending_connection_action = (action_id, str(action_kind))
            return action_id
        except Exception as exc:
            self._on_recorder_failure(f"could not begin {action_kind}: {exc}")
            return None

    def _complete_connection_action(
        self,
        *,
        connected: bool,
        outcome: str = "completed",
        expected_action_id: str | None = None,
    ) -> str | None:
        pending = self._pending_connection_action
        if pending is None:
            return None
        action_id, action_kind = pending
        if expected_action_id is not None and action_id != expected_action_id:
            return None
        self._pending_connection_action = None
        if self.recorder is not None and self.recorder.healthy:
            try:
                self.recorder.complete_action(
                    action_id,
                    action_kind=action_kind,
                    outcome=outcome,
                    source_layer="session",
                    payload={"connected": bool(connected)},
                )
            except Exception as exc:
                self._on_recorder_failure(
                    f"could not complete {action_kind}: {exc}"
                )
        return action_id

    def _on_machine_connection_changed(self, connected: bool):
        if self._closed:
            return
        action_id = self._complete_connection_action(connected=bool(connected))
        try:
            if self.recorder is not None and self.recorder.healthy:
                self.snapshot(
                    "connected" if connected else "disconnected",
                    correlation=(
                        {"action_id": action_id} if action_id is not None else None
                    ),
                )
        except Exception as exc:
            self.mark_failed(f"could not persist connection snapshot: {exc}")

    def snapshot(
        self,
        reason: str,
        *,
        include_persistence: bool = False,
        correlation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_open()
        if self.recorder is None or self.projector is None:
            raise StateRecorderError("state recorder is unavailable")
        projection = self.projector.capture(
            reason=str(reason),
            include_persistence=include_persistence,
        )
        snapshot = self.recorder.record_snapshot(
            projection,
            reason=str(reason),
            correlation=correlation,
            simulated_elapsed_ms=self.components.machine.state.simulated_elapsed_ms,
            persist=True,
        )
        self._metadata["latest_snapshot"] = {
            "captured_at": snapshot["captured_at_utc"],
            "reason": snapshot["reason"],
            "application_session_id": self.application_session_id,
            "snapshot_id": snapshot["snapshot_id"],
            "event_sequence": snapshot["event_sequence"],
            "artifact": self.recorder.relative_path(
                self.recorder.latest_snapshot_path
            ),
        }
        self._update_recorder_metadata()
        self._write_metadata()
        return snapshot

    def export_state_snapshot(self) -> dict[str, Any] | None:
        self._require_open()
        if self.recorder is None or not self.recorder.healthy:
            return None
        action_id = None
        try:
            action_id = self.recorder.begin_action(
                "export_state_snapshot",
                source_layer="session",
            )
            snapshot = self.snapshot(
                "manual_export",
                include_persistence=True,
                correlation={"action_id": action_id},
            )
            self.recorder.complete_action(
                action_id,
                action_kind="export_state_snapshot",
                source_layer="session",
                payload={"snapshot_id": snapshot["snapshot_id"]},
            )
            if self.inspector is not None:
                self.inspector.refresh()
            return snapshot
        except Exception as exc:
            self._on_recorder_failure(f"manual state snapshot failed: {exc}")
            return None

    def show_state_inspector(self) -> bool:
        self._require_open()
        if self.inspector is None:
            return False
        self.inspector.refresh()
        self.inspector.show()
        self.inspector.raise_()
        return True

    def mark_failed(self, reason: str) -> None:
        text = str(reason).strip() or "unspecified session failure"
        if self._failure_reason is None:
            self._failure_reason = text
        try:
            if self._lock is None:
                return
            self._append_log(f"FAILED: {text}")
        except OSError:
            pass

    def close(self, failure: Exception | str | None = None) -> bool:
        if self._closed:
            return bool(self._close_succeeded)
        if failure is not None:
            self.mark_failed(str(failure))
        errors: list[str] = []

        if (
            self.recorder is not None
            and self.recorder.healthy
            and self.projector is not None
        ):
            try:
                self.recorder.record_event(
                    "teardown_started",
                    source_layer="session",
                    payload={"failure": self._failure_reason},
                    simulated_elapsed_ms=(
                        self.components.machine.state.simulated_elapsed_ms
                        if self.components is not None
                        else None
                    ),
                )
                projection = self.projector.capture(
                    reason="pre_cleanup",
                    include_persistence=True,
                )
                self.recorder.record_snapshot(
                    projection,
                    reason="pre_cleanup",
                    source_layer="session",
                    simulated_elapsed_ms=self.components.machine.state.simulated_elapsed_ms,
                    persist=True,
                )
            except Exception as exc:
                self._on_recorder_failure(f"pre-cleanup state capture failed: {exc}")

        self._closed = True

        if self.components is not None:
            if self._machine_signal_connected:
                try:
                    self.components.machine.machine_connected_signal.disconnect(
                        self._on_machine_connection_changed
                    )
                except (RuntimeError, TypeError):
                    pass
                self._machine_signal_connected = False
            try:
                connection_timer = getattr(
                    self.components.machine,
                    "_connection_timer",
                    None,
                )
                connection_pending = bool(
                    connection_timer is not None
                    and connection_timer.isActive()
                )
                if self.components.machine.state.connected or connection_pending:
                    self.components.controller.disconnect_machine()
            except Exception as exc:
                errors.append(f"simulator disconnect failed: {exc}")

            if self.app is not None:
                try:
                    self.app.processEvents()
                except RuntimeError:
                    pass

            if self.observer is not None:
                try:
                    self.observer.dispose()
                except Exception as exc:
                    errors.append(f"state observer cleanup failed: {exc}")

            if self.calibration_adapter is not None:
                try:
                    self.calibration_adapter.dispose()
                except Exception as exc:
                    errors.append(f"synthetic calibration adapter cleanup failed: {exc}")

            if self.manual_refuel_adapter is not None:
                try:
                    self.manual_refuel_adapter.dispose()
                except Exception as exc:
                    errors.append(f"simulated manual-refuel adapter cleanup failed: {exc}")

            for timer in list(
                getattr(self.components.machine, "_deferred_timers", set())
            ):
                try:
                    timer.stop()
                except RuntimeError:
                    pass
            deferred = getattr(self.components.machine, "_deferred_timers", None)
            if deferred is not None:
                deferred.clear()

            if self.control is not None:
                try:
                    self.control.dispose()
                except Exception as exc:
                    errors.append(f"simulator control cleanup failed: {exc}")
            if self.inspector is not None:
                try:
                    self.inspector.dispose()
                except Exception as exc:
                    errors.append(f"state inspector cleanup failed: {exc}")
            try:
                self.components.close()
            except Exception as exc:
                errors.append(f"application component cleanup failed: {exc}")
            if self.app is not None:
                try:
                    self.app.processEvents()
                except RuntimeError:
                    pass
            errors.extend(self._active_timer_errors())

        if self.config.qt_ownership is QtOwnership.OWNED and self.app is not None:
            try:
                self.app.quit()
            except RuntimeError:
                pass

        if errors and self._failure_reason is None:
            self._failure_reason = "; ".join(errors)

        application_cleanup_succeeded = self._failure_reason is None and not errors
        if self.recorder is not None:
            if self.recorder.healthy:
                try:
                    latest = self.recorder.latest_snapshot() or {}
                    cached_projection = latest.get("projection") or {
                        "reason": "cleanup",
                        "layers": {},
                        "reconciliation": {
                            "status": "unavailable",
                            "compared_fields": 0,
                            "mismatches": [],
                        },
                    }
                    self.recorder.record_snapshot(
                        cached_projection,
                        reason="cleanup",
                        event_kind=(
                            "cleanup_completed"
                            if application_cleanup_succeeded
                            else "cleanup_failed"
                        ),
                        source_layer="session",
                        persist=True,
                        terminal=True,
                        payload={
                            "application_cleanup_succeeded": application_cleanup_succeeded,
                            "errors": list(errors),
                            "failure": self._failure_reason,
                        },
                    )
                except Exception as exc:
                    self._on_recorder_failure(f"terminal state capture failed: {exc}")
            if not self.recorder.close():
                self.mark_failed(
                    self.recorder.health_snapshot().get("failure")
                    or "state recorder close failed"
                )
            self._update_recorder_metadata()

        succeeded = self._failure_reason is None and not errors

        if self._metadata is not None:
            record = self._application_session_record()
            record["ended_at"] = _utc_now()
            record["status"] = "completed" if succeeded else "failed"
            if self._failure_reason is not None:
                record["failure"] = self._failure_reason
            remove_clean_fresh = (
                succeeded
                and self.config.root_policy is SessionRootPolicy.FRESH
                and self.config.artifact_retention
                is ArtifactRetentionPolicy.DELETE_CLEAN_FRESH
            )
            self._metadata["terminal_status"] = (
                "completed" if succeeded else "failed"
            )
            self._metadata["cleanup"] = {
                "status": "complete" if succeeded else "failed",
                "root_retained": not remove_clean_fresh,
                "root_removal_planned": remove_clean_fresh,
                "errors": errors,
            }
            try:
                self._write_metadata()
                self._append_log(
                    "session cleanup completed"
                    if succeeded
                    else f"session cleanup failed: {self._failure_reason}"
                )
            except Exception as exc:
                succeeded = False
                self._failure_reason = (
                    self._failure_reason
                    or f"could not persist terminal session metadata: {exc}"
                )
                remove_clean_fresh = False

        self._release_lock()

        if (
            succeeded
            and self.config.root_policy is SessionRootPolicy.FRESH
            and self.config.artifact_retention
            is ArtifactRetentionPolicy.DELETE_CLEAN_FRESH
        ):
            try:
                self._remove_clean_fresh_root()
                self._root_removed = True
            except Exception as exc:
                succeeded = False
                self._failure_reason = f"could not remove clean fresh root: {exc}"
                try:
                    self._metadata["terminal_status"] = "failed"
                    self._metadata["cleanup"]["status"] = "failed"
                    self._metadata["cleanup"]["root_retained"] = True
                    self._metadata["cleanup"]["errors"].append(
                        self._failure_reason
                    )
                    self._write_metadata()
                except Exception:
                    pass

        self._close_succeeded = succeeded
        return succeeded

    def _active_timer_errors(self) -> list[str]:
        errors = []
        timers = {
            "simulator command timer": getattr(
                self.components.machine, "_command_timer", None
            ),
            "simulator connection timer": getattr(
                self.components.machine, "_connection_timer", None
            ),
            "Controller sequence timer": getattr(
                self.components.controller, "_seq_timer", None
            ),
            "Controller capture timer": getattr(
                self.components.controller, "pending_capture_guard_timer", None
            ),
            "window disconnect timer": getattr(
                self.components.view, "_close_disconnect_timer", None
            ),
        }
        for name, timer in timers.items():
            active = getattr(timer, "isActive", None)
            if not callable(active):
                continue
            try:
                if active():
                    errors.append(f"{name} remained active")
            except RuntimeError:
                pass
        deferred = getattr(self.components.machine, "_deferred_timers", set())
        if deferred:
            errors.append("simulator deferred timers remained registered")
        return errors

    def _remove_clean_fresh_root(self) -> None:
        root = self.session_root.resolve()
        parent = self._default_parent.resolve()
        if parent not in root.parents or root.parent != parent:
            raise RuntimeError("fresh root no longer has the expected contained parent")
        marker = root / SESSION_FILENAME
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        if (
            metadata.get("schema_id") != SESSION_SCHEMA_ID
            or metadata.get("session_id") != self.session_id
        ):
            raise RuntimeError("fresh root marker does not match this session")
        shutil.rmtree(root)

    def _release_lock(self) -> None:
        if self._lock is not None:
            try:
                self._lock.unlock()
            finally:
                self._lock = None

    def _abort_create(self, exc: Exception) -> None:
        self.mark_failed(f"construction failed: {exc}")
        if self.observer is not None:
            try:
                self.observer.dispose()
            except Exception:
                pass
        if self.calibration_adapter is not None:
            try:
                self.calibration_adapter.dispose()
            except Exception:
                pass
        if self.manual_refuel_adapter is not None:
            try:
                self.manual_refuel_adapter.dispose()
            except Exception:
                pass
        if self.inspector is not None:
            try:
                self.inspector.dispose()
            except Exception:
                pass
        if self.control is not None:
            try:
                self.control.dispose()
            except Exception:
                pass
        if self.components is not None:
            try:
                self.components.close()
            except Exception:
                pass
        if self.recorder is not None:
            try:
                self.recorder.close()
                self._update_recorder_metadata()
            except Exception:
                pass
        if self._metadata is not None:
            try:
                record = self._application_session_record()
                record["ended_at"] = _utc_now()
                record["status"] = "failed"
                record["failure"] = self._failure_reason
                self._metadata["terminal_status"] = "failed"
                self._metadata["cleanup"] = {
                    "status": "construction_failed",
                    "root_retained": True,
                    "root_removal_planned": False,
                }
                self._write_metadata()
            except Exception:
                pass
        self._release_lock()
        if self.config.qt_ownership is QtOwnership.OWNED and self.app is not None:
            try:
                self.app.quit()
            except RuntimeError:
                pass

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("simulation session is closed")
        if self.components is None:
            raise RuntimeError("simulation session is not constructed")

