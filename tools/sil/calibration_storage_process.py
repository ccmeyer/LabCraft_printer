"""Simulation-only calibration process and current-writer inspection helpers."""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
import sys
import time
from typing import Any, Mapping

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from ApplicationComposition import SIMULATION_RUNTIME_CONTEXT  # noqa: E402
from CalibrationClasses.Model import BaseCalibrationProcess  # noqa: E402
from simulation.machine import SimulatedMachine  # noqa: E402

from .calibration_storage_contract import (  # noqa: E402
    CalibrationStorageContractError,
    ScriptedCalibrationCase,
    distribution,
    normalized_legacy_step,
    normalized_recorder_update,
    semantic_sha256,
)


class StorageContractRuntimeError(RuntimeError):
    """Raised when the scripted process is used outside canonical SIL."""


@dataclass
class StorageMetricsCollector:
    update_latency_ms: list[float] = field(default_factory=list)
    process_finalize_latency_ms: list[float] = field(default_factory=list)
    history_load_latency_ms: list[float] = field(default_factory=list)
    fresh_reload_latency_ms: list[float] = field(default_factory=list)
    calibration_rewrite_latency_ms: list[float] = field(default_factory=list)
    recorder_append_latency_ms: list[float] = field(default_factory=list)
    calibration_rewrite_sizes: list[int] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        updates = list(self.update_latency_ms)
        quartile = max(1, len(updates) // 4) if updates else 0
        first = updates[:quartile] if quartile else []
        last = updates[-quartile:] if quartile else []
        first_median = distribution(first).get("median")
        last_median = distribution(last).get("median")
        ratio = (
            float(last_median) / float(first_median)
            if first_median not in (None, 0) and last_median is not None
            else None
        )
        return {
            "update_latency_ms": distribution(updates),
            "process_finalize_latency_ms": distribution(self.process_finalize_latency_ms),
            "history_load_latency_ms": distribution(self.history_load_latency_ms),
            "fresh_reload_latency_ms": distribution(self.fresh_reload_latency_ms),
            "calibration_rewrite_latency_ms": distribution(self.calibration_rewrite_latency_ms),
            "recorder_append_latency_ms": distribution(self.recorder_append_latency_ms),
            "first_quartile_update_latency_ms": distribution(first),
            "last_quartile_update_latency_ms": distribution(last),
            "last_to_first_median_ratio": ratio,
            "calibration_rewrite_count": len(self.calibration_rewrite_latency_ms),
            "calibration_rewrite_sizes": distribution(self.calibration_rewrite_sizes),
            "result_finalize_latency": {
                "status": "not_available_until_m2",
                "samples": [],
            },
            "index_latency": {
                "status": "not_available_until_m2",
                "samples": [],
            },
        }


class _SyntheticStock:
    def __init__(self, identity: Mapping[str, Any]):
        self.stock_id = str(identity.get("stock_id") or "sil-stock")
        self.reagent_name = str(identity.get("reagent_name") or "SIL Reagent")
        self.concentration = str(identity.get("concentration") or "1.0")
        self.raw_concentration = self.concentration
        self.units = str(identity.get("units") or "x")

    def get_stock_id(self):
        return self.stock_id

    def get_reagent_name(self):
        return self.reagent_name

    def get_stock_name(self):
        return f"{self.reagent_name} - {self.concentration} {self.units}"

    def get_display_stock_name(self):
        return self.get_stock_name()


class SyntheticStorageHead:
    """Minimum stable head identity needed by current calibration readers."""

    def __init__(self, identity: Mapping[str, Any]):
        self.identity = dict(identity)
        self.printer_head_id = str(identity.get("printer_head_id") or "sil-head")
        self.serial = self.printer_head_id
        self.id = self.printer_head_id
        self.stock_solution = _SyntheticStock(identity)
        self.color = "#4c72b0"

    def __str__(self):
        return self.printer_head_id

    def get_stock_solution(self):
        return self.stock_solution

    def get_stock_id(self):
        return self.stock_solution.get_stock_id()

    def get_reagent_name(self):
        return self.stock_solution.get_reagent_name()

    def get_stock_concentration(self):
        return self.stock_solution.concentration

    def get_display_stock_concentration(self):
        return self.stock_solution.concentration

    def get_stock_name(self):
        return self.stock_solution.get_stock_name()

    def get_display_stock_name(self, new_line=False):
        value = self.stock_solution.get_display_stock_name()
        return value.replace(" - ", "\n") if new_line else value

    def get_current_volume(self):
        return 100.0

    def get_color(self):
        return self.color

    def is_calibration_chip(self):
        return False

    def get_printing_mode(self):
        return "droplet"


class ScriptedCalibrationProcess(BaseCalibrationProcess):
    """Deterministic process that exercises normal manager storage wiring."""

    supports_operator_verdict = False

    def __init__(
        self,
        calibration_manager,
        model,
        *,
        case: ScriptedCalibrationCase,
        runtime_context: Any,
        machine: Any,
        metrics: StorageMetricsCollector | None = None,
        parent=None,
    ):
        if runtime_context is not SIMULATION_RUNTIME_CONTEXT:
            raise StorageContractRuntimeError(
                "scripted calibration storage process requires canonical simulation runtime"
            )
        if bool(getattr(runtime_context, "hardware_access_allowed", True)):
            raise StorageContractRuntimeError("hardware access must be disabled")
        if not isinstance(machine, SimulatedMachine):
            raise StorageContractRuntimeError("scripted process requires SimulatedMachine")
        if not isinstance(case, ScriptedCalibrationCase):
            raise TypeError("case must be a ScriptedCalibrationCase")
        super().__init__(calibration_manager, model, parent=parent)
        self.case = case
        self.phase_name = case.phase_name
        self.runtime_context = runtime_context
        self.machine = machine
        self.metrics = metrics or StorageMetricsCollector()
        self.emitted_update_hashes: list[str] = []
        self.submitted_capture_count = 0
        self._step_index = 0

    @staticmethod
    def missing_requirements(_manager, *_args, **_kwargs):
        return []

    def start(self):
        self._record_event(
            "storage_contract_script_started",
            {
                "fixture_id": self.case.fixture_id,
                "process_id": self.case.process_id,
                "result_kind": self.case.result_kind,
            },
        )
        self.stageChanged.emit(f"SIL storage contract: {self.case.process_id}")
        QtCore.QTimer.singleShot(0, self._advance)

    def _capture_selected(self, capture: Mapping[str, Any]) -> bool:
        if self.case.capture_mode == "structured_only_proxy":
            return False
        if self.case.capture_mode == "key_evidence_proxy":
            return bool(capture.get("key_evidence"))
        if self.case.capture_mode == "full_proxy":
            return True
        raise CalibrationStorageContractError(
            f"unsupported capture proxy: {self.case.capture_mode}"
        )

    def _emit_captures(self) -> None:
        for capture in self.case.captures:
            if not self._capture_selected(capture):
                continue
            value = int(capture.get("value", 0))
            frame = np.full((12, 16), value, dtype=np.uint8)
            result = self._record_capture(
                frame,
                role=str(capture.get("role") or "capture"),
                metadata={
                    "storage_contract": True,
                    "fixture_id": self.case.fixture_id,
                    "process_id": self.case.process_id,
                    "fixture_capture_index": int(capture.get("capture_index", 0)),
                    "key_evidence": bool(capture.get("key_evidence")),
                },
            )
            if result is not None:
                self.submitted_capture_count += 1

    def _advance(self) -> None:
        if self._step_index < len(self.case.updates):
            payload = dict(self.case.updates[self._step_index])
            started = time.perf_counter_ns()
            self.calibrationDataUpdated.emit(payload)
            self.metrics.update_latency_ms.append(
                (time.perf_counter_ns() - started) / 1_000_000.0
            )
            self.emitted_update_hashes.append(
                semantic_sha256({"phase": self.phase_name, "data": payload})
            )
            self._step_index += 1
            QtCore.QTimer.singleShot(0, self._advance)
            return
        self._emit_captures()
        started = time.perf_counter_ns()
        if self.case.terminal_outcome == "completed":
            self.calibrationCompleted.emit()
        else:
            self.calibrationError.emit(self.case.error_message)
        self.metrics.process_finalize_latency_ms.append(
            (time.perf_counter_ns() - started) / 1_000_000.0
        )

    def stop(self):
        self.calibrationError.emit("Calibration terminated by user")


@dataclass(frozen=True)
class StorageProcessEvidence:
    fixture_id: str
    process_id: str
    phase_name: str
    terminal_outcome: str
    run_id: str
    recording_dir: str | None
    update_hashes: tuple[str, ...]
    legacy_update_hashes: tuple[str, ...]
    recorder_update_hashes: tuple[str, ...]
    capture_count: int
    capture_bytes: int
    captures: tuple[dict[str, Any], ...]
    meta_outcome: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CalibrationStorageContractError(
                f"invalid JSONL at {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise CalibrationStorageContractError(f"JSONL row is not an object: {path}:{line_number}")
        rows.append(row)
    return rows


class StorageContractRunner:
    """Run scripted cases through a real CalibrationManager in SIL."""

    def __init__(
        self,
        *,
        model: Any,
        controller: Any,
        machine: Any,
        app: QtWidgets.QApplication,
        calibration_file_path: str | Path,
        timeout_seconds: float = 30.0,
        metrics: StorageMetricsCollector | None = None,
    ):
        runtime_context = getattr(controller, "runtime_context", None)
        if runtime_context is not SIMULATION_RUNTIME_CONTEXT:
            raise StorageContractRuntimeError(
                "storage runner requires canonical simulation Controller"
            )
        if not isinstance(machine, SimulatedMachine):
            raise StorageContractRuntimeError("storage runner requires SimulatedMachine")
        if app is None:
            raise StorageContractRuntimeError("storage runner requires QApplication")
        self.model = model
        self.controller = controller
        self.machine = machine
        self.app = app
        self.manager = model.calibration_manager
        self.calibration_file_path = Path(calibration_file_path).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self.metrics = metrics or StorageMetricsCollector()
        self._previous_head = None
        self._previous_gripper_slot = None
        self._previous_record_mode_enabled = self.manager.get_record_mode_enabled()
        self._identity_overridden = False

    def _activate_identity(self, identity: Mapping[str, Any]) -> None:
        rack = self.model.rack_model
        if not self._identity_overridden:
            self._previous_head = getattr(rack, "gripper_printer_head", None)
            self._previous_gripper_slot = getattr(rack, "gripper_slot_number", None)
            self._identity_overridden = True
        rack.gripper_printer_head = SyntheticStorageHead(identity)
        rack.gripper_slot_number = None
        sync = getattr(rack, "sync_expected_to_actual", None)
        if callable(sync):
            sync()
        signal = getattr(rack, "gripper_updated", None)
        if signal is not None:
            signal.emit()

    def activate_identity(self, identity: Mapping[str, Any]) -> SyntheticStorageHead:
        """Stage one synthetic identity without bypassing manager readers."""

        self._activate_identity(identity)
        return self.model.rack_model.gripper_printer_head

    def characterization_rows(
        self, identity: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Time and return current-reader rows for exactly one staged identity."""

        self._activate_identity(identity)
        started = time.perf_counter_ns()
        rows = [
            dict(row)
            for row in self.manager.get_characterization_summary_rows()
        ]
        self.metrics.history_load_latency_ms.append(
            (time.perf_counter_ns() - started) / 1_000_000.0
        )
        return rows

    def restore(self) -> None:
        self.manager.set_record_mode_enabled(self._previous_record_mode_enabled)
        rack = self.model.rack_model
        if self._identity_overridden:
            rack.gripper_printer_head = self._previous_head
            rack.gripper_slot_number = self._previous_gripper_slot
            sync = getattr(rack, "sync_expected_to_actual", None)
            if callable(sync):
                sync()
        self._previous_head = None
        self._previous_gripper_slot = None
        self._identity_overridden = False

    def _wait_terminal(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while self.manager.activeCalibration is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QtCore.QThread.msleep(1)
        self.app.processEvents()
        if self.manager.activeCalibration is not None:
            raise TimeoutError("scripted calibration did not reach a terminal state")

    def _instrument_current_writers(self):
        manager = self.manager
        original_save = manager._save_atomic
        recorder = manager._process_recorder
        original_analysis = recorder.append_analysis

        def measured_save():
            started = time.perf_counter_ns()
            try:
                return original_save()
            finally:
                self.metrics.calibration_rewrite_latency_ms.append(
                    (time.perf_counter_ns() - started) / 1_000_000.0
                )
                if self.calibration_file_path.is_file():
                    self.metrics.calibration_rewrite_sizes.append(
                        self.calibration_file_path.stat().st_size
                    )

        def measured_analysis(record):
            started = time.perf_counter_ns()
            try:
                return original_analysis(record)
            finally:
                self.metrics.recorder_append_latency_ms.append(
                    (time.perf_counter_ns() - started) / 1_000_000.0
                )

        manager._save_atomic = measured_save
        recorder.append_analysis = measured_analysis
        return original_save, original_analysis

    def run_case(self, case: ScriptedCalibrationCase) -> StorageProcessEvidence:
        self._activate_identity(case.identity)
        self.manager.set_record_mode_enabled(case.record_mode_enabled)
        self.manager.begin_session(
            str(self.calibration_file_path),
            notes="SIL storage-contract fixture",
        )
        run_id = str(self.manager._run_id)
        process = ScriptedCalibrationProcess(
            self.manager,
            self.model,
            case=case,
            runtime_context=self.controller.runtime_context,
            machine=self.machine,
            metrics=self.metrics,
            parent=self.manager,
        )
        originals = self._instrument_current_writers()
        try:
            self.manager.activeCalibration = process
            self.manager.start_active_calibration()
            recording_dir = getattr(process, "_recorder_run_dir", None)
            self._wait_terminal()
            self.manager.end_session(
                outcome=case.terminal_outcome,
                error_message=case.error_message,
                emit_stage=False,
            )
        finally:
            self.manager._save_atomic = originals[0]
            self.manager._process_recorder.append_analysis = originals[1]
        evidence = inspect_current_writer_case(
            self.calibration_file_path,
            case=case,
            run_id=run_id,
            recording_dir=recording_dir,
        )
        if evidence.update_hashes != case.expected_update_hashes:
            raise CalibrationStorageContractError(
                f"fixture update hash mismatch for {case.process_id}"
            )
        if evidence.legacy_update_hashes != evidence.update_hashes:
            raise CalibrationStorageContractError(
                f"legacy calibration payload mismatch for {case.process_id}"
            )
        expected_recorder = evidence.update_hashes if case.record_mode_enabled else ()
        if evidence.recorder_update_hashes != expected_recorder:
            raise CalibrationStorageContractError(
                f"recorder payload mismatch for {case.process_id}"
            )
        return evidence


def _decoded_capture_manifest(directory: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    capture_root = directory / "captures"
    for path in sorted(capture_root.glob("*")):
        if not path.is_file():
            continue
        image = QtGui.QImage(str(path))
        if image.isNull():
            raise CalibrationStorageContractError(
                f"recorded capture could not be decoded: {path}"
            )
        grayscale = image.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
        byte_count = int(grayscale.bytesPerLine() * grayscale.height())
        decoded = bytes(grayscale.constBits()[:byte_count])
        rows.append(
            {
                "name": path.name,
                "width": int(grayscale.width()),
                "height": int(grayscale.height()),
                "decoded_pixel_sha256": hashlib.sha256(decoded).hexdigest(),
                "compressed_bytes": int(path.stat().st_size),
            }
        )
    return tuple(rows)


def inspect_current_writer_case(
    calibration_file_path: str | Path,
    *,
    case: ScriptedCalibrationCase,
    run_id: str,
    recording_dir: str | Path | None,
) -> StorageProcessEvidence:
    calibration = json.loads(Path(calibration_file_path).read_text(encoding="utf-8"))
    matches = [run for run in calibration.get("runs", []) if str(run.get("run_id")) == str(run_id)]
    if len(matches) != 1:
        raise CalibrationStorageContractError(
            f"expected one legacy calibration run {run_id}; observed {len(matches)}"
        )
    run = matches[0]
    legacy_steps = list((run.get("steps") or {}).get(case.phase_name) or [])
    legacy_hashes = tuple(semantic_sha256(normalized_legacy_step(step)) for step in legacy_steps)
    recorder_hashes: tuple[str, ...] = ()
    capture_count = 0
    capture_bytes = 0
    capture_manifest: tuple[dict[str, Any], ...] = ()
    meta_outcome = None
    recording_text = None
    if recording_dir:
        directory = Path(recording_dir).resolve()
        recording_text = str(directory)
        analysis = [
            row
            for row in _read_jsonl(directory / "analysis.jsonl")
            if row.get("kind") == "calibration_data_updated"
        ]
        recorder_hashes = tuple(
            semantic_sha256(normalized_recorder_update(row)) for row in analysis
        )
        capture_manifest = _decoded_capture_manifest(directory)
        capture_count = len(capture_manifest)
        capture_bytes = sum(
            int(row["compressed_bytes"]) for row in capture_manifest
        )
        meta = json.loads((directory / "run_meta.json").read_text(encoding="utf-8"))
        meta_outcome = str(meta.get("outcome"))
    return StorageProcessEvidence(
        fixture_id=case.fixture_id,
        process_id=case.process_id,
        phase_name=case.phase_name,
        terminal_outcome=case.terminal_outcome,
        run_id=run_id,
        recording_dir=recording_text,
        update_hashes=case.expected_update_hashes,
        legacy_update_hashes=legacy_hashes,
        recorder_update_hashes=recorder_hashes,
        capture_count=capture_count,
        capture_bytes=capture_bytes,
        captures=capture_manifest,
        meta_outcome=meta_outcome,
    )


def file_inventory(root: str | Path) -> dict[str, Any]:
    base = Path(root).resolve()
    groups: dict[str, dict[str, int]] = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower() or "no_extension"
        group = groups.setdefault(suffix, {"count": 0, "bytes": 0})
        group["count"] += 1
        group["bytes"] += path.stat().st_size
    return {"root": str(base), "by_extension": groups}


__all__ = [
    "ScriptedCalibrationProcess",
    "StorageContractRunner",
    "StorageContractRuntimeError",
    "StorageMetricsCollector",
    "StorageProcessEvidence",
    "SyntheticStorageHead",
    "file_inventory",
    "inspect_current_writer_case",
]
