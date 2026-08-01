"""Pure, bounded cross-layer projections for interactive SIL evidence."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from PySide6 import QtWidgets


_AUTHORITATIVE_FILENAMES = (
    "execution_plan.json",
    "progress.json",
    "execution_resume.json",
    "execution_calibrations.json",
    "migration_manifest.json",
)


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _safe_call(obj: Any, name: str, default: Any = None) -> Any:
    value = _safe_attr(obj, name, default)
    if not callable(value):
        return default
    try:
        return value()
    except Exception:
        return default


def _layer(projector: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return {"available": True, "state": dict(projector()), "error": None}
    except Exception as exc:
        return {
            "available": False,
            "state": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


def _head_identity(head: Any) -> dict[str, Any] | None:
    if head is None:
        return None
    return {
        "printer_head_id": _safe_attr(head, "printer_head_id"),
        "head_type_id": _safe_attr(head, "head_type_id"),
        "display_name": _safe_attr(head, "display_name"),
        "stock_id": _safe_call(head, "get_stock_id"),
        "reagent_name": _safe_call(head, "get_reagent_name"),
        "printing_mode": _safe_call(head, "get_printing_mode"),
        "current_volume_uL": _safe_attr(head, "current_volume"),
        "target_droplet_volume_nL": _safe_attr(head, "target_droplet_volume"),
        "confirmed": bool(_safe_attr(head, "confirmed", False)),
        "completed": bool(_safe_attr(head, "completed", False)),
        "calibration_chip": bool(_safe_attr(head, "calibration_chip", False)),
    }


def _button_state(button: Any) -> dict[str, Any]:
    return {
        "object_name": str(_safe_call(button, "objectName", "") or ""),
        "text": str(_safe_call(button, "text", "") or ""),
        "enabled": bool(_safe_call(button, "isEnabled", False)),
        "visible": bool(_safe_call(button, "isVisible", False)),
    }


class StateProjectionBuilder:
    """Read application state without invoking a mutation or repair path."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._cached_persistence: dict[str, Any] = {
            "available": False,
            "state": {"status": "not_captured"},
            "error": None,
        }

    def capture(
        self,
        *,
        reason: str,
        include_persistence: bool = False,
    ) -> dict[str, Any]:
        layers = {
            "session": _layer(self._session_state),
            "simulator": _layer(self._simulator_state),
            "controller": _layer(self._controller_state),
            "model_machine": _layer(self._model_machine_state),
            "rack_head": _layer(self._rack_state),
            "experiment": _layer(self._experiment_state),
            "calibration": _layer(self._calibration_state),
            "refuel_check": _layer(self._refuel_state),
            "ui": _layer(self._ui_state),
        }
        if include_persistence:
            self._cached_persistence = _layer(self._persistence_state)
        layers["persistence"] = dict(self._cached_persistence)
        return {
            "reason": str(reason),
            "layers": layers,
            "reconciliation": self._reconcile(layers),
        }

    def _session_state(self) -> dict[str, Any]:
        config = self.session.config
        roots = self.session.application_roots
        recorder = _safe_attr(self.session, "recorder")
        return {
            "session_id": self.session.session_id,
            "application_session_id": self.session.application_session_id,
            "source_identity": config.source_identity,
            "runtime_mode": config.expected_runtime_mode,
            "seed": config.seed,
            "speed_multiplier": config.speed_multiplier,
            "profile": _safe_attr(_safe_attr(self.session, "components"), "model").profile.name,
            "session_root": str(self.session.session_root),
            "application_roots": {
                "config": str(_safe_attr(roots, "config_root")),
                "experiments": str(_safe_attr(roots, "experiments_root")),
                "calibration_memory": str(_safe_attr(roots, "calibration_memory_root")),
            },
            "recorder": (
                recorder.health_snapshot()
                if recorder is not None
                else {"status": "unavailable"}
            ),
        }

    def _simulator_state(self) -> dict[str, Any]:
        machine = self.session.components.machine
        state = machine.state
        if is_dataclass(state):
            result = asdict(state)
        else:
            result = dict(state)
        for raw_name, psi_name in (
            ("current_print_pressure_raw", "current_print_pressure_psi"),
            ("current_refuel_pressure_raw", "current_refuel_pressure_psi"),
            ("target_print_pressure_raw", "target_print_pressure_psi"),
            ("target_refuel_pressure_raw", "target_refuel_pressure_psi"),
        ):
            raw_value = result.get(raw_name)
            result[psi_name] = (
                None if raw_value is None else machine.convert_to_psi(raw_value)
            )
        active = _safe_attr(machine, "_active_command")
        result["active_command"] = (
            None
            if active is None
            else {
                "command_number": _safe_attr(active, "command_number"),
                "command_type": _safe_attr(active, "command_type"),
                "status": _safe_attr(active, "status"),
            }
        )
        return result

    def _controller_state(self) -> dict[str, Any]:
        controller = self.session.components.controller
        context = _safe_attr(controller, "_array_context") or {}
        pass_summary = {
            key: _value(context.get(key))
            for key in (
                "stock_id",
                "pass_index",
                "soft_stop_pending",
                "last_completed_well_id",
            )
            if key in context
        }
        return {
            "array_state": controller.get_array_run_state(),
            "active_pass": pass_summary or None,
            "last_transport_fault": bool(
                _safe_attr(controller, "_last_transport_fault_debug_bundle_context")
            ),
            "disconnect_pending": bool(
                _safe_attr(self.session.components.view, "_close_disconnect_pending", False)
            ),
            "failure_reason": _safe_attr(self.session, "_failure_reason"),
        }

    def _model_machine_state(self) -> dict[str, Any]:
        machine = self.session.components.model.machine_model
        names = (
            "machine_connected",
            "motors_enabled",
            "motors_homed",
            "current_x",
            "current_y",
            "current_z",
            "current_p",
            "current_r",
            "target_x",
            "target_y",
            "target_z",
            "target_p",
            "target_r",
            "current_print_pressure",
            "current_refuel_pressure",
            "target_print_pressure",
            "target_refuel_pressure",
            "regulating_print_pressure",
            "regulating_refuel_pressure",
            "print_pulse_width",
            "refuel_pulse_width",
            "dispense_frequency_hz",
            "gripper_open",
            "gripper_active",
            "current_command_num",
            "last_completed_command_num",
            "last_accepted_command_num",
            "last_retired_command_num",
            "command_depth",
            "pause_after_seq32",
            "pause_watermark_reached",
            "transport_paused",
            "paused",
            "machine_free",
            "current_micros",
        )
        return {name: _value(_safe_attr(machine, name)) for name in names}

    def _rack_state(self) -> dict[str, Any]:
        rack = self.session.components.model.rack_model
        slots = []
        for index, slot in enumerate(list(_safe_attr(rack, "slots", []))):
            slots.append(
                {
                    "slot": int(_safe_attr(slot, "number", index)),
                    "confirmed": bool(_safe_attr(slot, "confirmed", False)),
                    "locked": bool(_safe_attr(slot, "locked", False)),
                    "printer_head": _head_identity(_safe_attr(slot, "printer_head")),
                    "expected_printer_head": _head_identity(
                        list(_safe_attr(rack, "expected_slot_printer_heads", []))[index]
                        if index < len(list(_safe_attr(rack, "expected_slot_printer_heads", [])))
                        else None
                    ),
                }
            )
        return {
            "slots": slots,
            "gripper_printer_head": _head_identity(
                _safe_attr(rack, "gripper_printer_head")
            ),
            "gripper_slot_number": _safe_attr(rack, "gripper_slot_number"),
            "expected_gripper_printer_head": _head_identity(
                _safe_attr(rack, "expected_gripper_printer_head")
            ),
            "expected_gripper_slot_number": _safe_attr(
                rack, "expected_gripper_slot_number"
            ),
        }

    def _experiment_state(self) -> dict[str, Any]:
        experiment = self.session.components.model.experiment_model
        plan = _safe_call(experiment, "get_execution_plan_snapshot")
        eligibility = _safe_call(experiment, "get_execution_resume_eligibility")
        plan_state = None
        if plan is not None:
            plan_state = {
                "plan_id": _safe_attr(plan, "plan_id"),
                "plan_revision": _safe_attr(plan, "plan_revision"),
                "state": _value(_safe_attr(plan, "state")),
                "design_sha256": _safe_attr(plan, "design_sha256"),
                "stock_count": len(tuple(_safe_attr(plan, "stocks", ()))),
                "well_count": len(tuple(_safe_attr(plan, "wells", ()))),
            }
        metadata = _safe_attr(experiment, "metadata", {}) or {}
        return {
            "experiment_dir": _safe_attr(experiment, "experiment_dir_path"),
            "calibration_file": _safe_attr(experiment, "calibration_file_path"),
            "name": metadata.get("name"),
            "plan": plan_state,
            "eligibility": eligibility,
            "runtime_active": bool(
                _safe_call(experiment, "is_authoritative_execution_runtime_active", False)
            ),
        }

    @staticmethod
    def _record_summary(record: Any) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            return {}
        keys = (
            "calibration_record_id",
            "run_id",
            "phase",
            "stock_id",
            "printer_head_id",
            "printing_mode",
            "applied_printing_mode",
            "effective_volume_nL",
            "pressure_psi",
            "pulse_width_us",
            "source_row_fingerprint",
            "status",
            "outcome",
            "required",
            "stale",
            "applied_calibration_fingerprint",
        )
        return {key: _value(record.get(key)) for key in keys if key in record}

    def _calibration_state(self) -> dict[str, Any]:
        experiment = self.session.components.model.experiment_model
        document = _safe_attr(experiment, "applied_imaging_calibrations", {}) or {}
        records = document.get("records", {}) if isinstance(document, Mapping) else {}
        manager = self.session.components.model.calibration_manager
        active = _safe_attr(manager, "activeCalibration")
        return {
            "schema_version": (
                document.get("schema_version")
                if isinstance(document, Mapping)
                else None
            ),
            "applied_records": {
                str(key): self._record_summary(value)
                for key, value in sorted(records.items(), key=lambda item: str(item[0]))
            },
            "active_phase": _safe_attr(active, "phase_name"),
            "queue_depth": len(list(_safe_attr(manager, "calibration_queue", []))),
            "stream_sequence": _safe_call(
                manager, "get_stream_calibration_sequence_state", {}
            ),
            "droplet_sequence": _safe_call(
                manager, "get_droplet_calibration_sequence_state", {}
            ),
        }

    def _refuel_state(self) -> dict[str, Any]:
        experiment = self.session.components.model.experiment_model
        document = _safe_attr(experiment, "manual_refuel_checks", {}) or {}
        records = document.get("records", {}) if isinstance(document, Mapping) else {}
        return {
            "schema_version": (
                document.get("schema_version")
                if isinstance(document, Mapping)
                else None
            ),
            "records": {
                str(key): self._record_summary(value)
                for key, value in sorted(records.items(), key=lambda item: str(item[0]))
            }
        }

    def _ui_state(self) -> dict[str, Any]:
        view = self.session.components.view
        app = QtWidgets.QApplication.instance()
        modal = app.activeModalWidget() if app is not None else None
        tab_widget = _safe_attr(view, "tab_widget")
        buttons = []
        accepted = (
            "connect",
            "motor",
            "home",
            "regulate",
            "array",
            "pause",
            "resume",
            "gripper",
        )
        for button in view.findChildren(QtWidgets.QPushButton):
            state = _button_state(button)
            identity = f"{state['object_name']} {state['text']}".lower()
            if any(token in identity for token in accepted):
                buttons.append(state)
            if len(buttons) >= 24:
                break
        current_tab = None
        if tab_widget is not None:
            try:
                current_tab = str(tab_widget.tabText(tab_widget.currentIndex()))
            except Exception:
                current_tab = None
        return {
            "window_visible": bool(view.isVisible()),
            "current_tab": current_tab,
            "primary_controls": buttons,
            "active_modal": (
                None
                if modal is None
                else {
                    "class": type(modal).__name__,
                    "object_name": str(modal.objectName() or ""),
                    "window_title": str(modal.windowTitle() or ""),
                }
            ),
        }

    def _experiment_directory(self) -> Path | None:
        experiment = self.session.components.model.experiment_model
        raw = _safe_attr(experiment, "experiment_dir_path")
        if not raw:
            return None
        path = Path(raw).resolve()
        experiments_root = Path(self.session.application_roots.experiments_root).resolve()
        if path != experiments_root and experiments_root not in path.parents:
            raise ValueError("active experiment path escaped session experiments root")
        return path

    @staticmethod
    def _document_summary(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return {"type": type(payload).__name__}
        summary = {
            key: _value(payload.get(key))
            for key in (
                "schema_id",
                "schema_name",
                "schema_version",
                "plan_id",
                "plan_revision",
                "state",
                "progress_sha256",
            )
            if key in payload
        }
        wells = payload.get("wells")
        if isinstance(wells, Mapping):
            summary["well_count"] = len(wells)
        elif isinstance(wells, list):
            summary["well_count"] = len(wells)
        intents = payload.get("intents")
        if isinstance(intents, list):
            counts: dict[str, int] = {}
            for intent in intents:
                status = str((intent or {}).get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
            summary["intent_counts"] = counts
        records = payload.get("records")
        if isinstance(records, Mapping):
            summary["record_count"] = len(records)
        manual_checks = payload.get("manual_refuel_checks")
        if isinstance(manual_checks, Mapping):
            summary["manual_refuel_check_count"] = len(manual_checks)
        return summary

    def _persistence_state(self) -> dict[str, Any]:
        directory = self._experiment_directory()
        if directory is None:
            return {"status": "no_active_experiment", "documents": {}}
        documents = {}
        for filename in _AUTHORITATIVE_FILENAMES:
            path = directory / filename
            row: dict[str, Any] = {
                "path": path.relative_to(self.session.session_root).as_posix(),
                "exists": path.is_file(),
            }
            if path.is_file():
                raw = path.read_bytes()
                row["size_bytes"] = len(raw)
                row["sha256"] = hashlib.sha256(raw).hexdigest()
                try:
                    row["document"] = self._document_summary(
                        json.loads(raw.decode("utf-8-sig"))
                    )
                except Exception as exc:
                    row["parse_error"] = f"{type(exc).__name__}: {exc}"
            documents[filename] = row
        return {
            "status": "captured",
            "experiment_dir": directory.relative_to(self.session.session_root).as_posix(),
            "documents": documents,
        }

    @staticmethod
    def _reconcile(layers: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        simulator_layer = layers.get("simulator") or {}
        model_layer = layers.get("model_machine") or {}
        if not simulator_layer.get("available") or not model_layer.get("available"):
            return {
                "status": "unavailable",
                "compared_fields": 0,
                "mismatches": [],
                "domains": {},
            }
        simulator = simulator_layer.get("state") or {}
        model = model_layer.get("state") or {}
        pairs = [
            ("connected", "machine_connected"),
            ("motors_enabled", "motors_enabled"),
            ("homed", "motors_homed"),
            ("x", "current_x"),
            ("y", "current_y"),
            ("z", "current_z"),
            ("target_x", "target_x"),
            ("target_y", "target_y"),
            ("target_z", "target_z"),
            ("regulating_print_pressure", "regulating_print_pressure"),
            ("regulating_refuel_pressure", "regulating_refuel_pressure"),
            ("gripper_open", "gripper_open"),
            ("current_command", "current_command_num"),
            ("last_completed", "last_completed_command_num"),
            ("last_accepted", "last_accepted_command_num"),
            ("last_retired", "last_retired_command_num"),
            ("command_depth", "command_depth"),
            ("pause_after_seq32", "pause_after_seq32"),
            ("pause_watermark_reached", "pause_watermark_reached"),
            ("transport_paused", "transport_paused"),
        ]
        # The Model intentionally retains the last gripper-active value while
        # disconnected, and does not consume raw pressure until connection.
        # Those values are comparable only while both layers are live.
        if simulator.get("connected") and model.get("machine_connected"):
            pairs.extend(
                (
                    ("current_print_pressure_psi", "current_print_pressure"),
                    ("current_refuel_pressure_psi", "current_refuel_pressure"),
                    ("target_print_pressure_psi", "target_print_pressure"),
                    ("target_refuel_pressure_psi", "target_refuel_pressure"),
                    ("gripper_active", "gripper_active"),
                )
            )
        mismatches = []
        domain_counts: dict[str, int] = {"simulator_model": 0}
        for simulator_name, model_name in pairs:
            left = simulator.get(simulator_name)
            right = model.get(model_name)
            domain_counts["simulator_model"] += 1
            if left != right:
                mismatches.append(
                    {
                        "domain": "simulator_model",
                        "field": simulator_name,
                        "simulator": left,
                        "model": right,
                    }
                )

        controller_layer = layers.get("controller") or {}
        ui_layer = layers.get("ui") or {}
        if controller_layer.get("available") and ui_layer.get("available"):
            controller = controller_layer.get("state") or {}
            ui = ui_layer.get("state") or {}
            expected_text = {
                "running": "Stop After Well",
                "stop_requested": "Stop Pending",
                "resume_ready": "Resume Print",
            }.get(str(controller.get("array_state")), "Start Array")
            array_buttons = [
                button
                for button in (ui.get("primary_controls") or [])
                if str(button.get("text"))
                in {"Start Array", "Stop After Well", "Stop Pending", "Resume Print"}
            ]
            if array_buttons:
                domain_counts["controller_ui"] = 1
                actual_text = str(array_buttons[0].get("text"))
                if actual_text != expected_text:
                    mismatches.append(
                        {
                            "domain": "controller_ui",
                            "field": "array_control_text",
                            "controller": expected_text,
                            "ui": actual_text,
                        }
                    )

        rack_layer = layers.get("rack_head") or {}
        if rack_layer.get("available"):
            for slot in (rack_layer.get("state") or {}).get("slots", []):
                expected = slot.get("expected_printer_head")
                if not expected or not slot.get("confirmed"):
                    continue
                actual = slot.get("printer_head")
                domain_counts["rack_head"] = domain_counts.get("rack_head", 0) + 1
                expected_identity = (
                    expected.get("printer_head_id"),
                    expected.get("stock_id"),
                )
                actual_identity = (
                    (actual or {}).get("printer_head_id"),
                    (actual or {}).get("stock_id"),
                )
                if actual_identity != expected_identity:
                    mismatches.append(
                        {
                            "domain": "rack_head",
                            "field": f"slot_{slot.get('slot')}",
                            "expected": expected_identity,
                            "actual": actual_identity,
                        }
                    )

        experiment_layer = layers.get("experiment") or {}
        persistence_layer = layers.get("persistence") or {}
        if experiment_layer.get("available") and persistence_layer.get("available"):
            experiment = experiment_layer.get("state") or {}
            persistence = persistence_layer.get("state") or {}
            documents = persistence.get("documents") or {}
            memory_plan = experiment.get("plan")
            if memory_plan:
                for filename in ("execution_plan.json", "progress.json"):
                    document = (documents.get(filename) or {}).get("document")
                    if not document:
                        continue
                    for field in ("plan_id", "plan_revision"):
                        if field not in document:
                            continue
                        domain_counts["experiment_persistence"] = (
                            domain_counts.get("experiment_persistence", 0) + 1
                        )
                        if memory_plan.get(field) != document.get(field):
                            mismatches.append(
                                {
                                    "domain": "experiment_persistence",
                                    "field": f"{filename}:{field}",
                                    "memory": memory_plan.get(field),
                                    "persistence": document.get(field),
                                }
                            )

            sidecar = (documents.get("execution_calibrations.json") or {}).get(
                "document"
            )
            calibration_layer = layers.get("calibration") or {}
            refuel_layer = layers.get("refuel_check") or {}
            if (
                sidecar
                and calibration_layer.get("available")
                and refuel_layer.get("available")
            ):
                count_pairs = (
                    (
                        "calibration_records",
                        len(
                            (calibration_layer.get("state") or {}).get(
                                "applied_records", {}
                            )
                        ),
                        sidecar.get("record_count", 0),
                    ),
                    (
                        "manual_refuel_checks",
                        len((refuel_layer.get("state") or {}).get("records", {})),
                        sidecar.get("manual_refuel_check_count", 0),
                    ),
                )
                for field, memory_count, persistent_count in count_pairs:
                    domain_counts["calibration_persistence"] = (
                        domain_counts.get("calibration_persistence", 0) + 1
                    )
                    if memory_count != persistent_count:
                        mismatches.append(
                            {
                                "domain": "calibration_persistence",
                                "field": field,
                                "memory": memory_count,
                                "persistence": persistent_count,
                            }
                        )
        return {
            "status": "ok" if not mismatches else "mismatch",
            "compared_fields": sum(domain_counts.values()),
            "mismatches": mismatches,
            "domains": domain_counts,
        }
