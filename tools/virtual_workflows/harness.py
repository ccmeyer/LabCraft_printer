"""Shared session, evidence, and teardown owner for composed SIL journeys."""

from __future__ import annotations

import hashlib
import json
import time
import tempfile
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from tools.virtual_workflows.actions import (
    InteractionSurface,
    ScenarioActionError,
    ScenarioContext,
    execute_action,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class AutomationHarnessConfig:
    scenario_id: str
    workload_id: str
    output_root: Path
    visible: bool = False
    seed: int = 1
    speed_multiplier: float = 1.0
    timeout_seconds: float = 180.0
    run_id: str | None = None

    def __post_init__(self) -> None:
        if not str(self.scenario_id).strip() or not str(self.workload_id).strip():
            raise ValueError("scenario_id and workload_id must be nonempty")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if float(self.speed_multiplier) <= 0:
            raise ValueError("speed_multiplier must be greater than zero")
        if float(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())


class AutomationHarness:
    """Own composed application sessions and their generic evidence."""

    def __init__(self, config: AutomationHarnessConfig):
        self.config = config
        self.run_id = config.run_id or str(uuid.uuid4())
        self.started_at_utc = _utc_now()
        self.started_monotonic_ns = time.perf_counter_ns()
        self.events: list[dict[str, Any]] = []
        self.assertion_results: list[dict[str, Any]] = []
        self.failure: BaseException | None = None
        self.session = None
        self.session_id: str | None = None
        self.application_sessions: list[dict[str, Any]] = []
        self.closed = False

        self.report_dir = (
            config.output_root / config.workload_id / f"{_run_stamp()}_composed"
        ).resolve()
        self.report_dir.mkdir(parents=True, exist_ok=False)
        # Automation retains its session beneath the OS temporary root. This is
        # outside the repository and production data while remaining writable in
        # sandboxed test/agent environments. The report links the exact path.
        self.scenario_root = (
            Path(tempfile.gettempdir()).resolve()
            / "LabCraft"
            / "SIL"
            / "composed-sessions"
            / f"{_run_stamp()}-{self.run_id[:12]}"
        )
        self.screenshots_dir = self.report_dir / "screenshots"
        self.screenshots_dir.mkdir()
        if not self.report_dir.is_relative_to(config.output_root):
            raise ValueError("report directory escaped the configured output root")

        self.context = ScenarioContext(
            scenario_id=config.scenario_id,
            workload_id=config.workload_id,
            report_dir=self.report_dir,
            scenario_root=self.scenario_root,
            screenshots_dir=self.screenshots_dir,
            timeout_seconds=config.timeout_seconds,
            record_event=self.record_event,
        )

    def record_event(self, kind: str, **values: Any) -> None:
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "kind": str(kind),
                "monotonic_ns": time.perf_counter_ns(),
                **values,
            }
        )

    def _launch_application_session(self) -> Mapping[str, Any]:
        """Construct, launch, and bind one canonical retained session."""

        if self.session is not None:
            raise RuntimeError("an application session is already active")
        if self.closed:
            raise RuntimeError("automation harness is closed")
        try:
            from tools.sil.session import (
                ArtifactRetentionPolicy,
                QtOwnership,
                SessionRootPolicy,
                SimulationSession,
                SimulationSessionConfigV1,
            )
            from tools.virtual_workflows.qt_font_environment import (
                apply_and_validate_sil_application_font,
            )
            from PySide6 import QtCore, QtWidgets

            if self.config.visible:
                QtWidgets.QApplication.setAttribute(
                    QtCore.Qt.ApplicationAttribute.AA_DontUseNativeDialogs,
                    True,
                )

            ownership = (
                QtOwnership.BORROWED
                if QtWidgets.QApplication.instance() is not None
                else QtOwnership.OWNED
            )

            session = SimulationSession.create(
                SimulationSessionConfigV1(
                    # QTest coverage requires controls to be visible even when
                    # Qt itself is using the offscreen platform.
                    visible=True,
                    qt_ownership=ownership,
                    root_policy=SessionRootPolicy.RETAINED,
                    session_root=self.scenario_root,
                    seed=self.config.seed,
                    speed_multiplier=self.config.speed_multiplier,
                    automation_deadline_seconds=self.config.timeout_seconds,
                    artifact_retention=ArtifactRetentionPolicy.RETAIN,
                    source_identity="milestone6-composed-workflow",
                )
            )
            observed_session_id = str(session.session_id)
            if self.session_id is not None and observed_session_id != self.session_id:
                session.close("retained SIL session identity changed during reopen")
                raise RuntimeError("retained SIL session identity changed during reopen")
            self.session = session
            self.session_id = observed_session_id
            self.scenario_root = Path(session.session_root).resolve()
            self.context.scenario_root = self.scenario_root
            font = apply_and_validate_sil_application_font(session.app)
            view = session.launch()
            components = session.components
            context = self.context
            context.app = session.app
            context.qt_core = __import__("PySide6.QtCore", fromlist=["QtCore"])
            context.components, context.view = components, view
            context.model, context.machine = components.model, components.machine
            context.controller = components.controller
            context.experiment_model = components.model.experiment_model
            context.application_session_id = session.application_session_id
            evidence = {
                "session_id": session.session_id,
                "application_session_id": session.application_session_id,
                "application_session_index": len(self.application_sessions) + 1,
                "seed": self.config.seed,
                "speed_multiplier": self.config.speed_multiplier,
                "font_rendering": font,
                "scenario_root": str(self.scenario_root),
                "qt_non_native_dialogs": bool(self.config.visible),
                "component_type": type(components).__name__,
                "view_type": type(view).__name__,
                "machine_type": type(components.machine).__name__,
                "hardware_access_allowed": bool(components.controller.runtime_context.hardware_access_allowed),
            }
            self.application_sessions.append(
                {
                    "session_id": str(session.session_id),
                    "application_session_id": str(session.application_session_id),
                    "application_session_index": len(self.application_sessions) + 1,
                    "status": "active",
                    "recorder_artifact_dir": str(session.recorder.artifact_dir),
                }
            )
            return evidence
        except BaseException:
            if self.session is not None:
                try:
                    self.session.close("application session launch failed")
                except Exception:
                    pass
                self.session = None
            raise

    def start(self) -> dict[str, Any]:
        """Construct and launch the canonical retained SimulationSession."""

        return execute_action(
            self.context, "app.launch_simulated", self._launch_application_session,
            interaction_surface=InteractionSurface.HARNESS,
        )

    def _record_application_close(self, session: Any, succeeded: bool) -> tuple[dict[str, Any], bool]:
        recorder = dict(session.recorder.health_snapshot())
        lock_present = (self.scenario_root / ".sil-session.lock").exists()
        application_session_id = str(session.application_session_id)
        for record in reversed(self.application_sessions):
            if record["application_session_id"] == application_session_id:
                record.update(
                    status="completed" if succeeded else "failed",
                    close_succeeded=succeeded,
                    recorder=recorder,
                    session_lock_present_after_close=lock_present,
                )
                break
        return recorder, lock_present

    def close_application_session(self) -> dict[str, Any]:
        """Close one application while retaining the reusable SIL root."""

        def operation() -> Mapping[str, Any]:
            if self.session is None:
                raise RuntimeError("no application session is active")
            session = self.session
            application_session_id = str(session.application_session_id)
            session_id = str(session.session_id)
            recorder_dir = Path(session.recorder.artifact_dir).resolve()
            succeeded = bool(session.close())
            recorder, lock_present = self._record_application_close(session, succeeded)
            self.session = None
            context = self.context
            for name in ("components", "model", "machine", "controller", "view", "experiment_model"):
                setattr(context, name, None)
            evidence = {
                "session_id": session_id,
                "application_session_id": application_session_id,
                "close_succeeded": succeeded,
                "recorder": recorder,
                "recorder_artifact_dir": str(recorder_dir),
                "session_lock_present": lock_present,
                "root_retained": self.scenario_root.is_dir(),
            }
            if not succeeded or lock_present or recorder.get("status") != "closed":
                raise ScenarioActionError(
                    "app.close_simulated_session",
                    "application session did not close cleanly",
                    stage="cleanup",
                    evidence=evidence,
                )
            return evidence

        return execute_action(
            self.context, "app.close_simulated_session", operation,
            interaction_surface=InteractionSurface.HARNESS,
        )

    def reopen_application_session(self) -> dict[str, Any]:
        """Open a fresh application composition on the retained SIL root."""

        result = execute_action(
            self.context, "app.launch_simulated", self._launch_application_session,
            interaction_surface=InteractionSurface.HARNESS,
        )
        if len(self.application_sessions) < 2:
            raise RuntimeError("application session reopen did not create a fresh record")
        first, current = self.application_sessions[-2:]
        if first["application_session_id"] == current["application_session_id"]:
            raise RuntimeError("application session reopen reused an application identity")
        return result

    def run_action(
        self,
        action_id: str,
        operation: Callable[[], Mapping[str, Any] | None],
        *,
        surface: InteractionSurface = InteractionSurface.UI,
        precondition: Callable[[], tuple[bool, str, Mapping[str, Any] | None]]
        | None = None,
        allowed_dialogs: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        def bounded_operation() -> Mapping[str, Any] | None:
            evidence = operation()
            self.assert_no_unexpected_dialog(allowed_dialogs=allowed_dialogs)
            if self.session is not None and self.session.recorder is not None:
                health = self.session.recorder.health_snapshot()
                if health.get("status") != "healthy":
                    raise ScenarioActionError(
                        action_id,
                        "state recorder is not healthy",
                        stage="evidence",
                        evidence={"recorder": health},
                    )
                self.session.snapshot(
                    f"action:{action_id}",
                    correlation={"action_id": action_id},
                )
            return evidence

        try:
            result = execute_action(
                self.context,
                action_id,
                bounded_operation,
                precondition=precondition,
                interaction_surface=surface,
            )
            return result
        except BaseException as exc:
            if self.failure is None:
                self.failure = exc
            raise

    def assert_no_unexpected_dialog(
        self,
        *,
        allowed_dialogs: tuple[Any, ...] = (),
    ) -> None:
        if self.context.app is None:
            return
        from PySide6 import QtWidgets

        visible = [
            widget
            for widget in self.context.app.topLevelWidgets()
            if isinstance(widget, QtWidgets.QDialog) and widget.isVisible()
            and widget not in allowed_dialogs
            and widget
            is not getattr(
                getattr(self.context.view, "pressure_box", None),
                "_droplet_imager_dialog",
                None,
            )
        ]
        if not visible:
            return
        entries = [
            {"type": type(widget).__name__, "title": widget.windowTitle()}
            for widget in visible
        ]
        self.context.unexpected_dialogs.extend(entries)
        for widget in visible:
            widget.reject()
        raise RuntimeError(f"unexpected dialog(s) remained visible: {entries}")

    def add_assertion_result(self, result: Mapping[str, Any]) -> None:
        row = dict(result)
        self.assertion_results.append(row)
        self.record_event(
            "assertion_completed",
            assertion_id=row.get("assertion_id"),
            decision=row.get("decision"),
        )

    def capture_failure(self, exc: BaseException) -> None:
        if self.failure is None:
            self.failure = exc
        if self.session is not None:
            self.session.mark_failed(str(exc))
            try:
                self.session.snapshot("automation_failure", include_persistence=True)
            except Exception:
                pass
        if self.context.view is not None:
            try:
                image = self.context.view.grab()
                path = self.screenshots_dir / "failure.png"
                if image.save(str(path)):
                    self.context.screenshots["failure"] = path
            except Exception:
                pass
        (self.report_dir / "failure_traceback.txt").write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )

    def close(self) -> dict[str, Any]:
        if self.closed:
            existing = [
                item
                for item in self.context.action_results
                if item.get("action_id") == "scenario.teardown"
            ]
            return existing[-1] if existing else {}

        def operation() -> Mapping[str, Any]:
            if self.session is None:
                return {
                    "session_created": False,
                    "close_succeeded": True,
                    "application_sessions": [
                        dict(row) for row in self.application_sessions
                    ],
                }
            session = self.session
            succeeded = bool(session.close(failure=self.failure))
            if not succeeded and self.failure is None:
                raise RuntimeError("SimulationSession teardown failed")
            _recorder, lock_present = self._record_application_close(
                session, succeeded
            )
            return {
                "session_created": True,
                "close_succeeded": succeeded or self.failure is not None,
                "session_terminal_success": succeeded,
                "session_lock_present": lock_present,
                "root_retained": self.scenario_root.is_dir(),
                "application_sessions": [
                    dict(row) for row in self.application_sessions
                ],
            }

        try:
            return execute_action(
                self.context,
                "scenario.teardown",
                operation,
                enforce_deadline=False,
                interaction_surface=InteractionSurface.HARNESS,
            )
        finally:
            self.closed = True
            self.context.closed = True

    def write_ledgers(self) -> None:
        (self.report_dir / "action_ledger.json").write_text(
            json.dumps(self.context.action_results, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (self.report_dir / "assertion_ledger.json").write_text(
            json.dumps(self.assertion_results, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with (self.report_dir / "events.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    def write_evidence_manifest(self) -> Path:
        destination = self.report_dir / "evidence_manifest.json"
        files: list[dict[str, Any]] = []
        for path in sorted(self.report_dir.rglob("*")):
            if not path.is_file() or path == destination:
                continue
            files.append(
                {
                    "path": path.relative_to(self.report_dir).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        payload = {
            "schema_version": 1,
            "generated_at_utc": _utc_now(),
            "excluded": ["evidence_manifest.json"],
            "files": files,
        }
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    @property
    def duration_ms(self) -> float:
        return (time.perf_counter_ns() - self.started_monotonic_ns) / 1_000_000.0


__all__ = ["AutomationHarness", "AutomationHarnessConfig"]
