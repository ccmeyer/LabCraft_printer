from PySide6.QtCore import QObject, Signal
from PySide6 import QtCore
from serial.tools.list_ports import comports
from Model import Model,PrinterHead,Slot
from dfu_update_worker import DfuUpdateWorker
from ResetDebugBundle import export_reset_debug_bundle
from AppVersion import get_app_commit, get_app_version as read_app_version
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass

import ast
import time
import numpy as np
import os
import subprocess
import serial
import sys
import math
import json
import uuid
import inspect
import copy

from hardware.profile import CURRENT_PROFILE, HardwareProfile
from hardware.null_devices import NullCamera
from hardware.serial_ports import (
    normalized_usb_id as _normalized_usb_id,
    resolved_serial_path as _resolved_serial_path,
    serial_by_id_aliases as _serial_by_id_aliases,
)
from simulation import SIMULATED_PORT
from CaptureCoordinator import CaptureCoordinator
from CaptureTypes import CaptureResult, CaptureSource, CaptureStatus
from ApplicationComposition import ExperimentalFeatures, PRODUCTION_RUNTIME_CONTEXT
from MachineDataVerification import (
    SavedTargetAuthorizationRequest,
    canonical_value_sha256,
)
from MachineDataTransactions import (
    CURRENT_VERIFIED_STATES,
    ConfigurationRecoveryRequired,
    ConfigurationTransactionError,
    ConfigurationValidationError,
    read_governed_documents,
)
from ConfigurationSafetyPolicy import (
    ConfigurationSafetyError,
    parse_guard_assessment,
)
from MotionPositionContract import (
    MotionPositionContractError,
    canonicalize_position,
    canonicalize_relative_position,
)

ARRAY_PAUSE_DEPARTURE_ACCEL = 32000
ARRAY_PAUSE_DEPARTURE_SETTLE_MS = 200
ARRAY_AXIS_ACCEL_DEFAULT = 140000
ARRAY_PRINT_SERPENTINE = True
ARRAY_GENTLE_ACCEL_ENABLED = False
ARRAY_ROW_START_OVERSHOOT_STEPS = 0
PAUSED_ARRAY_SOFT_STOP_PHASE_TIMEOUT_MS = 4_000
PLATE_DOCK_SAFE_Z = 500
PLATE_DOCK_X_OFFSET = -5000
PLATE_SEATED_LOCATIONS = {"pause", "plate"}
APP_UPDATE_QT_ENV_VARS_TO_REMOVE = (
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_QPA_FONTDIR",
    "QT_PLUGIN_PATH",
)
APP_UPDATE_QT_PLATFORM_WAYLAND = "wayland;xcb"
CALIBRATION_MODE_PRINT_PULSE_WIDTH_US = {
    "droplet": 1300,
    "stream": 2500,
}
PROMPTABLE_MANUAL_REFUEL_CHECK_CODES = {
    "missing_refuel_check",
    "required_refuel_check",
    "deferred_refuel_check",
    "failed_refuel_check",
    "unclear_refuel_check",
    "bypassed_refuel_check",
    "stale_refuel_check",
    "settings_unavailable",
    "print_pulse_width_mismatch",
    "refuel_pulse_width_mismatch",
    "print_pressure_mismatch",
    "refuel_pressure_mismatch",
}


@dataclass(frozen=True)
class ExperimentalBalancePort:
    device_path: str
    system_device: str
    by_id_paths: tuple[str, ...]
    display_label: str
    vid: str | None
    pid: str | None
    vid_pid: str | None
    description: str | None
    manufacturer: str | None
    product: str | None
    serial_number: str | None

    def __post_init__(self):
        if not self.device_path or not self.system_device:
            raise ValueError("balance port paths must not be empty")
        if not isinstance(self.by_id_paths, tuple):
            raise TypeError("by_id_paths must be a tuple")


class DropletCapturePerformanceDiagnostics:
    """Small in-memory event buffer for droplet-capture timing diagnostics."""

    def __init__(self, max_events=20000):
        self.max_events = int(max(1, max_events))
        self.enabled = False
        self.events = deque(maxlen=self.max_events)
        self.next_event_index = 1
        self.session_id = None
        self.last_snapshot_path = None

    @staticmethod
    def _now_utc():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def _json_safe(cls, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, dict):
            return {str(k): cls._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(v) for v in value]
        if hasattr(value, "item"):
            try:
                return cls._json_safe(value.item())
            except Exception:
                pass
        return str(value)

    @staticmethod
    def _coerce_ns(value):
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _delta_ms(start_ns, end_ns):
        start = DropletCapturePerformanceDiagnostics._coerce_ns(start_ns)
        end = DropletCapturePerformanceDiagnostics._coerce_ns(end_ns)
        if start is None or end is None:
            return None
        return max(0.0, float(end - start) / 1_000_000.0)

    @classmethod
    def _context_dict(cls, value):
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") and text.endswith("}") and len(text) <= 10000:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    return dict(parsed)
        return {}

    @classmethod
    def _event_capture_context(cls, row, context_by_request=None):
        out = {}
        request_id = row.get("request_id") if isinstance(row, dict) else None
        if request_id and isinstance(context_by_request, dict):
            out.update(context_by_request.get(str(request_id)) or {})
        out.update(cls._context_dict(row.get("capture_context") if isinstance(row, dict) else None))
        for key in (
            "calibration_run_id",
            "calibration_run_index",
            "calibration_process_instance_id",
            "calibration_process_instance_index",
            "calibration_process",
            "calibration_phase",
            "stage_text",
            "set_attr",
            "capture_role",
            "capture_diag_id",
            "attempt",
            "attempts_total",
        ):
            if isinstance(row, dict) and row.get(key) not in (None, ""):
                out[key] = row.get(key)
        return out

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled and not self.enabled:
            self.events.clear()
            self.next_event_index = 1
            self.session_id = (
                f"droplet_capture_perf_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            )
        self.enabled = enabled
        return self.enabled

    def record(self, event_kind, payload=None):
        if not self.enabled:
            return None
        record = {
            "event_index": int(self.next_event_index),
            "event_kind": str(event_kind or "event"),
            "timestamp_utc": self._now_utc(),
            "monotonic_ns": int(time.monotonic_ns()),
            "session_id": self.session_id,
        }
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key not in record:
                    record[str(key)] = value
        record = self._json_safe(record)
        self.next_event_index += 1
        self.events.append(record)
        return dict(record)

    def build_snapshot(self, *, reason="manual_export", runtime_summaries=None):
        events = list(self.events)
        event_counts = Counter(str(row.get("event_kind") or "") for row in events)
        rejection_counts = Counter(
            str(row.get("reason") or row.get("rejection_reason") or row.get("ignored_reason") or "")
            for row in events
            if row.get("reason") or row.get("rejection_reason") or row.get("ignored_reason")
        )

        by_request = {}
        by_ui_sequence = {}
        context_by_request = {}
        for row in events:
            request_id = row.get("request_id")
            if request_id:
                by_request.setdefault(str(request_id), []).append(row)
                context = self._event_capture_context(row)
                if context:
                    context_by_request.setdefault(str(request_id), {}).update(context)
            ui_sequence = row.get("ui_sequence")
            if ui_sequence is not None:
                by_ui_sequence.setdefault(str(ui_sequence), []).append(row)

        def _first_by_kind(rows):
            first = {}
            for item in rows:
                first.setdefault(str(item.get("event_kind") or ""), item)
            return first

        def _last_by_kind(rows, event_kind):
            wanted = str(event_kind)
            for item in reversed(rows):
                if str(item.get("event_kind") or "") == wanted:
                    return item
            return {}

        def _first_nonempty(*values):
            for value in values:
                if value not in (None, ""):
                    return value
            return None

        def _float_or_none(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _int_or_none(value):
            try:
                if value in (None, ""):
                    return None
                return int(value)
            except (TypeError, ValueError):
                return None

        def _command_completed_ms(command):
            return _float_or_none((command or {}).get("completed_ms"))

        def _camera_phase_rows(rows):
            return [row for row in rows if str(row.get("event_kind") or "") == "camera_phase"]

        def _camera_summary_row(rows):
            return _last_by_kind(rows, "camera_capture_summary")

        def _last_camera_phase(camera_rows, phase):
            wanted = str(phase)
            for row in reversed(camera_rows):
                if str(row.get("phase") or "") == wanted:
                    return row
            return {}

        def _phase_elapsed_delta(camera_rows, start_phase, end_phase):
            start = _float_or_none(_last_camera_phase(camera_rows, start_phase).get("elapsed_ms"))
            end = _float_or_none(_last_camera_phase(camera_rows, end_phase).get("elapsed_ms"))
            if start is None or end is None:
                return None
            return max(0.0, end - start)

        def _worker_timing_fields(rows):
            compact = _camera_summary_row(rows)
            if compact:
                field_names = (
                    "edge_wait_duration_ms", "post_ack_to_result_ms", "arm_to_result_ms",
                    "make_array_ms", "signal_mean_ms", "rotate_ms", "frame_select_reason",
                    "selected_frame_mean", "selected_frame_threshold", "cap_seen", "cap_max_new",
                    "capture_profile", "requested_profile", "effective_profile",
                    "capture_profile_fallback_active", "capture_profile_fallback_reason",
                    "capture_profile_fallback_error", "signal_stride", "signal_channel",
                    "cap_emit_rotate", "detection_stream", "lores_size", "lores_format",
                    "lores_make_array_ms", "lores_signal_mean_ms", "main_make_array_ms",
                    "main_converted_for_selected_frame", "capture_arm_timing_mode", "early_arm_mark",
                    "early_arm_to_ack_ms", "early_arm_to_result_ms", "buffered_post_arm_frames",
                    "buffered_threshold_selected", "selected_frame_index", "selected_frame_interval_ms",
                    "selected_frame_index_after_ack", "selected_frame_done_after_ack_ms",
                    "stream_main_size", "stream_main_format", "stream_buffer_count",
                    "configured_exposure_time_us", "configured_frame_duration_us",
                    "selected_metadata_exposure_time_us", "selected_metadata_frame_duration_us",
                    "selected_metadata_sensor_timestamp_ns",
                )
                return {name: compact.get(name) for name in field_names}
            camera_rows = _camera_phase_rows(rows)
            retry_result = _last_camera_phase(camera_rows, "retry_attempt_result")
            early_arm_row = _last_camera_phase(camera_rows, "early_arm_mark")
            fields = {
                "edge_wait_duration_ms": _phase_elapsed_delta(
                    camera_rows,
                    "edge_wait_start",
                    "edge_wait_done",
                ),
                "post_ack_to_result_ms": _phase_elapsed_delta(
                    camera_rows,
                    "edge_wait_done",
                    "retry_attempt_result",
                ),
                "arm_to_result_ms": _phase_elapsed_delta(
                    camera_rows,
                    "arm_start",
                    "retry_attempt_result",
                ),
                "make_array_ms": _float_or_none(retry_result.get("make_array_ms")),
                "signal_mean_ms": _float_or_none(retry_result.get("signal_mean_ms")),
                "rotate_ms": _float_or_none(retry_result.get("rotate_ms")),
                "frame_select_reason": retry_result.get("frame_select_reason"),
                "selected_frame_mean": _float_or_none(retry_result.get("mean")),
                "selected_frame_threshold": _float_or_none(retry_result.get("threshold")),
                "cap_seen": _int_or_none(retry_result.get("cap_seen")),
                "cap_max_new": _int_or_none(retry_result.get("cap_max_new")),
                "capture_profile": retry_result.get("capture_profile"),
                "requested_profile": retry_result.get("requested_profile"),
                "effective_profile": retry_result.get("effective_profile"),
                "capture_profile_fallback_active": retry_result.get("fallback_active"),
                "capture_profile_fallback_reason": retry_result.get("fallback_reason"),
                "capture_profile_fallback_error": retry_result.get("fallback_error"),
                "signal_stride": _int_or_none(retry_result.get("signal_stride")),
                "signal_channel": retry_result.get("signal_channel"),
                "cap_emit_rotate": retry_result.get("cap_emit_rotate"),
                "detection_stream": retry_result.get("detection_stream"),
                "lores_size": retry_result.get("lores_size"),
                "lores_format": retry_result.get("lores_format"),
                "lores_make_array_ms": _float_or_none(retry_result.get("lores_make_array_ms")),
                "lores_signal_mean_ms": _float_or_none(retry_result.get("lores_signal_mean_ms")),
                "main_make_array_ms": _float_or_none(retry_result.get("main_make_array_ms")),
                "main_converted_for_selected_frame": retry_result.get("main_converted_for_selected_frame"),
                "capture_arm_timing_mode": retry_result.get("capture_arm_timing_mode"),
                "early_arm_mark": bool(retry_result.get("early_arm_mark") or early_arm_row),
                "early_arm_to_ack_ms": _float_or_none(
                    retry_result.get("early_arm_to_ack_ms")
                ) or _phase_elapsed_delta(camera_rows, "early_arm_mark", "edge_wait_done"),
                "early_arm_to_result_ms": _float_or_none(
                    retry_result.get("early_arm_to_result_ms")
                ) or _phase_elapsed_delta(camera_rows, "early_arm_mark", "retry_attempt_result"),
                "buffered_post_arm_frames": _int_or_none(retry_result.get("buffered_post_arm_frames")),
                "buffered_threshold_selected": retry_result.get("buffered_threshold_selected"),
                "selected_frame_index": _int_or_none(retry_result.get("selected_frame_index")),
                "selected_frame_interval_ms": _float_or_none(
                    retry_result.get("selected_frame_interval_ms")
                ),
                "selected_frame_index_after_ack": _int_or_none(
                    retry_result.get("selected_frame_index_after_ack")
                ),
                "selected_frame_done_after_ack_ms": _float_or_none(
                    retry_result.get("selected_frame_done_after_ack_ms")
                ),
                "stream_main_size": retry_result.get("stream_main_size"),
                "stream_main_format": retry_result.get("stream_main_format"),
                "stream_buffer_count": _int_or_none(retry_result.get("stream_buffer_count")),
                "configured_exposure_time_us": _int_or_none(
                    retry_result.get("configured_exposure_time_us")
                ),
                "configured_frame_duration_us": _int_or_none(
                    retry_result.get("configured_frame_duration_us")
                ),
                "selected_metadata_exposure_time_us": _int_or_none(
                    retry_result.get("selected_metadata_exposure_time_us")
                ),
                "selected_metadata_frame_duration_us": _int_or_none(
                    retry_result.get("selected_metadata_frame_duration_us")
                ),
                "selected_metadata_sensor_timestamp_ns": _int_or_none(
                    retry_result.get("selected_metadata_sensor_timestamp_ns")
                ),
            }
            return fields

        request_summaries = []
        for request_id, rows in by_request.items():
            first_by_kind = _first_by_kind(rows)
            completion = first_by_kind.get("controller_completion_received") or {}
            summary = {
                "request_id": request_id,
                "event_count": len(rows),
                "status": completion.get("status"),
                "cap_id": completion.get("cap_id"),
                "generation": completion.get("generation"),
                "backend_id": completion.get("backend_id"),
                "queue_to_worker_start_ms": completion.get("queue_to_worker_start_ms"),
                "worker_duration_ms": completion.get("worker_duration_ms"),
                "worker_complete_to_controller_ms": completion.get("worker_complete_to_controller_ms"),
                "controller_completion_to_pending_clear_ms": self._delta_ms(
                    (first_by_kind.get("controller_completion_received") or {}).get("monotonic_ns"),
                    (first_by_kind.get("controller_pending_cleared") or {}).get("monotonic_ns"),
                ),
                "controller_completion_to_ui_clear_ms": self._delta_ms(
                    (first_by_kind.get("controller_completion_received") or {}).get("monotonic_ns"),
                    (first_by_kind.get("ui_pending_cleared") or {}).get("monotonic_ns"),
                ),
            }
            summary.update(_worker_timing_fields(rows))
            request_summaries.append(self._json_safe(summary))

        ui_sequence_summaries = []
        for ui_sequence, rows in by_ui_sequence.items():
            first_by_kind = _first_by_kind(rows)
            received = first_by_kind.get("ui_trigger_received") or {}
            returned = first_by_kind.get("ui_request_returned") or {}
            ignored = next((row for row in rows if str(row.get("event_kind") or "").startswith("ui_trigger_ignored")), {})
            ui_sequence_summaries.append(
                self._json_safe(
                    {
                        "ui_sequence": ui_sequence,
                        "request_id": returned.get("request_id"),
                        "accepted": returned.get("accepted"),
                        "ignored_reason": ignored.get("ignored_reason"),
                        "trigger_to_return_ms": self._delta_ms(
                            received.get("monotonic_ns"),
                            returned.get("monotonic_ns"),
                        ),
                    }
                )
            )

        by_calibration_process = {}
        by_capture_diag = {}
        by_settings_request = {}
        for row in events:
            context = self._event_capture_context(row, context_by_request)
            process = context.get("calibration_process")
            phase = context.get("calibration_phase")
            process_instance_id = context.get("calibration_process_instance_id")
            if process or phase or process_instance_id:
                if process_instance_id:
                    key = ("instance", str(process_instance_id))
                else:
                    key = (
                        "legacy",
                        str(context.get("calibration_run_id") or ""),
                        str(context.get("calibration_run_index") if context.get("calibration_run_index") is not None else ""),
                        str(process or ""),
                        str(phase or ""),
                    )
                by_calibration_process.setdefault(key, []).append(row)
            capture_diag_id = context.get("capture_diag_id")
            if capture_diag_id:
                by_capture_diag.setdefault(str(capture_diag_id), []).append(row)
            settings_request_id = row.get("settings_request_id")
            if settings_request_id:
                by_settings_request.setdefault(str(settings_request_id), []).append(row)

        calibration_process_summaries = []
        for key, rows in by_calibration_process.items():
            first_by_kind = _first_by_kind(rows)
            started = first_by_kind.get("calibration_process_started") or rows[0]
            terminal = (
                _last_by_kind(rows, "calibration_process_completed")
                or _last_by_kind(rows, "calibration_process_failed")
                or _last_by_kind(rows, "calibration_process_stopped")
                or _last_by_kind(rows, "calibration_session_ended")
                or rows[-1]
            )
            context = {}
            capture_diag_ids = set()
            settings_request_ids = set()
            for row in rows:
                context.update(self._event_capture_context(row, context_by_request))
                capture_diag_id = self._event_capture_context(row, context_by_request).get("capture_diag_id")
                if capture_diag_id:
                    capture_diag_ids.add(str(capture_diag_id))
                settings_request_id = row.get("settings_request_id")
                if settings_request_id:
                    settings_request_ids.add(str(settings_request_id))
            if key and key[0] == "legacy":
                _tag, run_id, run_index, process, phase = key
                context.setdefault("calibration_run_id", run_id or None)
                context.setdefault("calibration_run_index", _int_or_none(run_index))
                context.setdefault("calibration_process", process or None)
                context.setdefault("calibration_phase", phase or None)
            calibration_process_summaries.append(
                self._json_safe(
                    {
                        "calibration_run_id": context.get("calibration_run_id"),
                        "calibration_run_index": _int_or_none(context.get("calibration_run_index")),
                        "calibration_process_instance_id": context.get("calibration_process_instance_id"),
                        "calibration_process_instance_index": _int_or_none(
                            context.get("calibration_process_instance_index")
                        ),
                        "calibration_process": context.get("calibration_process"),
                        "calibration_phase": context.get("calibration_phase"),
                        "event_count": len(rows),
                        "capture_count": len(capture_diag_ids),
                        "settings_count": len(settings_request_ids),
                        "started_event_index": started.get("event_index"),
                        "terminal_event_kind": terminal.get("event_kind"),
                        "duration_ms": self._delta_ms(
                            started.get("monotonic_ns"),
                            terminal.get("monotonic_ns"),
                        ),
                    }
                )
            )

        calibration_capture_summaries = []
        for capture_diag_id, rows in by_capture_diag.items():
            first_by_kind = _first_by_kind(rows)
            attempt = first_by_kind.get("calibration_capture_attempt_started") or rows[0]
            callback = first_by_kind.get("calibration_capture_callback_received") or {}
            result = _last_by_kind(rows, "calibration_capture_result") or rows[-1]
            completed = _last_by_kind(rows, "calibration_capture_completed_emitted")
            completion = _last_by_kind(rows, "controller_completion_received")
            context = {}
            for row in rows:
                context.update(self._event_capture_context(row, context_by_request))
            attempts = sorted(
                {
                    int(row.get("attempt"))
                    for row in rows
                    if row.get("attempt") is not None and str(row.get("attempt")).lstrip("-").isdigit()
                }
            )
            camera_rows = _camera_phase_rows(rows)
            compact_camera_summary = _camera_summary_row(rows)
            trigger_count = sum(1 for row in camera_rows if str(row.get("phase") or "") == "trigger_high")
            edge_done_rows = [row for row in camera_rows if str(row.get("phase") or "") == "edge_wait_done"]
            edge_timeout_count = sum(1 for row in edge_done_rows if row.get("fired") is False)
            edge_wait_values = [
                value
                for row in edge_done_rows
                for value in [_float_or_none(row.get("elapsed_ms"))]
                if value is not None
            ]
            delayed_ack_threshold_ms = 100.0
            delayed_ack_count = sum(
                1 for value in edge_wait_values
                if value > delayed_ack_threshold_ms
            )
            retry_result_rows = [
                row for row in camera_rows
                if str(row.get("phase") or "") == "retry_attempt_result"
            ]
            retry_reasons = [
                str(row.get("reason") or "")
                for row in retry_result_rows
                if row.get("reason")
            ]
            if compact_camera_summary:
                trigger_count = int(compact_camera_summary.get("trigger_count") or 0)
                edge_done_count = int(compact_camera_summary.get("edge_wait_done_count") or 0)
                edge_timeout_count = int(compact_camera_summary.get("edge_timeout_count") or 0)
                max_edge_wait_elapsed_ms = _float_or_none(
                    compact_camera_summary.get("max_edge_wait_elapsed_ms")
                )
                retry_reasons = list(compact_camera_summary.get("retry_reasons") or [])
                delayed_ack_count = int(
                    max_edge_wait_elapsed_ms is not None
                    and max_edge_wait_elapsed_ms > delayed_ack_threshold_ms
                )
            else:
                edge_done_count = len(edge_done_rows)
                max_edge_wait_elapsed_ms = max(edge_wait_values) if edge_wait_values else None
            capture_summary = {
                "capture_diag_id": capture_diag_id,
                "request_id": _first_nonempty(
                    callback.get("request_id"),
                    result.get("request_id"),
                    completion.get("request_id"),
                ),
                "calibration_run_id": _first_nonempty(
                    context.get("calibration_run_id"),
                    attempt.get("calibration_run_id"),
                ),
                "calibration_run_index": _first_nonempty(
                    context.get("calibration_run_index"),
                    attempt.get("calibration_run_index"),
                ),
                "calibration_process_instance_id": _first_nonempty(
                    context.get("calibration_process_instance_id"),
                    attempt.get("calibration_process_instance_id"),
                ),
                "calibration_process_instance_index": _first_nonempty(
                    context.get("calibration_process_instance_index"),
                    attempt.get("calibration_process_instance_index"),
                ),
                "calibration_process": _first_nonempty(
                    context.get("calibration_process"),
                    attempt.get("calibration_process"),
                ),
                "calibration_phase": _first_nonempty(
                    context.get("calibration_phase"),
                    attempt.get("calibration_phase"),
                ),
                "stage_text": _first_nonempty(
                    context.get("stage_text"),
                    attempt.get("stage_text"),
                ),
                "set_attr": _first_nonempty(
                    context.get("set_attr"),
                    attempt.get("set_attr"),
                ),
                "capture_role": _first_nonempty(
                    context.get("capture_role"),
                    attempt.get("capture_role"),
                ),
                "attempts": attempts,
                "attempts_total": _first_nonempty(
                    context.get("attempts_total"),
                    attempt.get("attempts_total"),
                ),
                "status": _first_nonempty(
                    result.get("capture_status"),
                    result.get("status"),
                    completion.get("status"),
                ),
                "worker_duration_ms": completion.get("worker_duration_ms"),
                "queue_to_worker_start_ms": completion.get("queue_to_worker_start_ms"),
                "worker_complete_to_controller_ms": completion.get("worker_complete_to_controller_ms"),
                "trigger_count": trigger_count,
                "worker_retry_count": int(
                    compact_camera_summary.get("worker_retry_count")
                    if compact_camera_summary and compact_camera_summary.get("worker_retry_count") is not None
                    else max(0, trigger_count - 1)
                ),
                "edge_wait_done_count": edge_done_count,
                "edge_timeout_count": edge_timeout_count,
                "delayed_ack_threshold_ms": delayed_ack_threshold_ms,
                "delayed_ack_count": delayed_ack_count,
                "max_edge_wait_elapsed_ms": max_edge_wait_elapsed_ms,
                "retry_reasons": retry_reasons,
                "attempt_to_callback_ms": self._delta_ms(
                    attempt.get("monotonic_ns"),
                    callback.get("monotonic_ns"),
                ),
                "attempt_to_result_ms": self._delta_ms(
                    attempt.get("monotonic_ns"),
                    result.get("monotonic_ns"),
                ),
                "attempt_to_capture_completed_emit_ms": self._delta_ms(
                    attempt.get("monotonic_ns"),
                    completed.get("monotonic_ns"),
                ),
            }
            capture_summary.update(_worker_timing_fields(rows))
            calibration_capture_summaries.append(self._json_safe(capture_summary))

        settings_request_summaries = []
        for settings_request_id, rows in by_settings_request.items():
            first_by_kind = _first_by_kind(rows)
            requested = first_by_kind.get("calibration_settings_requested") or rows[0]
            bound = first_by_kind.get("calibration_settings_bound") or {}
            terminal = (
                _last_by_kind(rows, "calibration_settings_completed")
                or _last_by_kind(rows, "calibration_settings_timeout")
                or _last_by_kind(rows, "calibration_settings_cancelled")
                or _last_by_kind(rows, "calibration_settings_completed_ignored")
                or rows[-1]
            )
            context = {}
            for row in rows:
                context.update(self._event_capture_context(row, context_by_request))
            commands = list(terminal.get("commands") or bound.get("commands") or [])
            command_status_counts = Counter(
                str(command.get("status") or "")
                for command in commands
                if command.get("status")
            )
            completed_values = [
                value
                for command in commands
                for value in [_command_completed_ms(command)]
                if value is not None
            ]
            slowest_command = None
            if completed_values:
                slowest_command = max(
                    commands,
                    key=lambda command: _command_completed_ms(command) if _command_completed_ms(command) is not None else -1.0,
                )
            completion_command_number = bound.get("completion_command_number")
            completion_command_completed_ms = None
            for command in commands:
                if _int_or_none(command.get("command_number")) == _int_or_none(completion_command_number):
                    completion_command_completed_ms = _command_completed_ms(command)
                    break
            settings_request_summaries.append(
                self._json_safe(
                    {
                        "settings_request_id": settings_request_id,
                        "calibration_run_id": _first_nonempty(
                            context.get("calibration_run_id"),
                            requested.get("calibration_run_id"),
                        ),
                        "calibration_run_index": _first_nonempty(
                            context.get("calibration_run_index"),
                            requested.get("calibration_run_index"),
                        ),
                        "calibration_process_instance_id": _first_nonempty(
                            context.get("calibration_process_instance_id"),
                            requested.get("calibration_process_instance_id"),
                        ),
                        "calibration_process_instance_index": _first_nonempty(
                            context.get("calibration_process_instance_index"),
                            requested.get("calibration_process_instance_index"),
                        ),
                        "calibration_process": _first_nonempty(
                            context.get("calibration_process"),
                            requested.get("calibration_process"),
                        ),
                        "calibration_phase": _first_nonempty(
                            context.get("calibration_phase"),
                            requested.get("calibration_phase"),
                        ),
                        "context": requested.get("context"),
                        "requested_settings": requested.get("requested_settings"),
                        "command_count": len(commands),
                        "completion_command_number": completion_command_number,
                        "commands": commands,
                        "command_status_counts": dict(command_status_counts),
                        "slowest_command": slowest_command,
                        "max_command_completed_ms": max(completed_values) if completed_values else None,
                        "completion_command_completed_ms": completion_command_completed_ms,
                        "stall_hint": terminal.get("stall_hint"),
                        "terminal_event_kind": terminal.get("event_kind"),
                        "request_to_bound_ms": self._delta_ms(
                            requested.get("monotonic_ns"),
                            bound.get("monotonic_ns"),
                        ),
                        "request_to_terminal_ms": self._delta_ms(
                            requested.get("monotonic_ns"),
                            terminal.get("monotonic_ns"),
                        ),
                    }
                )
            )

        def _distribution(values):
            ordered = sorted(float(value) for value in values if value is not None)
            if not ordered:
                return {"count": 0, "median_ms": None, "p95_ms": None, "maximum_ms": None}
            count = len(ordered)
            midpoint = count // 2
            median = (
                ordered[midpoint]
                if count % 2
                else (ordered[midpoint - 1] + ordered[midpoint]) / 2.0
            )
            p95_index = max(0, min(count - 1, int((0.95 * count) + 0.999999) - 1))
            return {
                "count": count,
                "median_ms": median,
                "p95_ms": ordered[p95_index],
                "maximum_ms": ordered[-1],
            }

        ui_metric_sources = {
            "model_ui_image_update": ("model_image_updated", "duration_ms"),
            "calibration_callback_handling": ("calibration_callback_handled", "duration_ms"),
            "image_rendering": ("image_rendered", "duration_ms"),
            "characterization_summary_refresh": ("characterization_summary_refreshed", "duration_ms"),
        }
        ui_work_summaries = {
            name: _distribution(
                _float_or_none(row.get(field_name))
                for row in events
                if str(row.get("event_kind") or "") == event_kind
            )
            for name, (event_kind, field_name) in ui_metric_sources.items()
        }

        snapshot = {
            "kind": "droplet_capture_performance_snapshot",
            "schema_version": 11,
            "reason": str(reason or "manual_export"),
            "generated_at_utc": self._now_utc(),
            "generated_monotonic_ns": int(time.monotonic_ns()),
            "enabled": bool(self.enabled),
            "session_id": self.session_id,
            "event_count": len(events),
            "max_events": int(self.max_events),
            "event_counts": dict(event_counts),
            "rejection_counts": dict(rejection_counts),
            "request_summaries": request_summaries,
            "ui_sequence_summaries": ui_sequence_summaries,
            "calibration_process_summaries": calibration_process_summaries,
            "calibration_capture_summaries": calibration_capture_summaries,
            "settings_request_summaries": settings_request_summaries,
            "ui_work_summaries": ui_work_summaries,
            "runtime_summaries": self._json_safe(dict(runtime_summaries or {})),
            "event_log_tail": events,
            "last_snapshot_path": self.last_snapshot_path,
        }
        return self._json_safe(snapshot)


class AppUpdateCheckWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    def __init__(self, repo_root, command_runner=None, offline_manifest_path=None, release_channel="stable"):
        super().__init__()
        self.repo_root = Path(repo_root)
        self.command_runner = command_runner
        self.offline_manifest_path = Path(offline_manifest_path) if offline_manifest_path is not None else None
        self.release_channel = str(release_channel or "stable")

    @QtCore.Slot()
    def run(self):
        from tools import update_and_restart

        config = update_and_restart.UpdaterConfig(
            repo_root=self.repo_root,
            offline_manifest_path=self.offline_manifest_path,
            release_channel=self.release_channel,
        )
        kwargs = {}
        if self.command_runner is not None:
            kwargs["command_runner"] = self.command_runner
        if self.offline_manifest_path is not None or self.release_channel == "release_candidate":
            result = update_and_restart.run_update_check(config, **kwargs)
        else:
            result = update_and_restart.run_update_check_with_offline_fallback(config, **kwargs)
        self.finished.emit(result)


class AppRollbackCheckWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    def __init__(self, repo_root, command_runner=None, offline_manifest_path=None):
        super().__init__()
        self.repo_root = Path(repo_root)
        self.command_runner = command_runner
        self.offline_manifest_path = Path(offline_manifest_path) if offline_manifest_path is not None else None

    @QtCore.Slot()
    def run(self):
        from tools import update_and_restart

        config = update_and_restart.UpdaterConfig(
            repo_root=self.repo_root,
            offline_manifest_path=self.offline_manifest_path,
            rollback=True,
        )
        kwargs = {}
        if self.command_runner is not None:
            kwargs["command_runner"] = self.command_runner
        if self.offline_manifest_path is not None:
            result = update_and_restart.run_rollback_check(config, **kwargs)
        else:
            result = update_and_restart.run_rollback_check_with_offline_fallback(config, **kwargs)
        self.finished.emit(result)


class Controller(QObject):
    """Controller class for the application."""
    CALIBRATION_GRIPPER_SETTLE_MS = 3000

    array_complete = Signal()
    array_state_changed = Signal(str)
    update_slots_signal = Signal()
    update_volumes_in_view_signal = Signal()
    error_occurred_signal = Signal(str,str)
    transport_fault_ui_signal = Signal(object)
    machine_workflow_interrupted_signal = Signal(object)
    plate_calibration_state_changed = Signal(object)
    xy_motion_recovery_requested = Signal(object)
    xy_motion_recovery_state_changed = Signal(str)
    experimental_balance_connection_changed = Signal(object)
    experimental_balance_reading_received = Signal(object)
    experimental_balance_error_occurred = Signal(object)
    experimental_balance_stream_opt_in_changed = Signal(bool)
    experimental_balance_request_progress = Signal(object)
    experimental_balance_request_finished = Signal(object)

    # DFU signals
    dfu_progress = QtCore.Signal(int)
    dfu_stage    = QtCore.Signal(str)
    dfu_finished = QtCore.Signal(bool, str)
    dfu_output   = QtCore.Signal(str)

    # Qualification run signals
    qualification_stage = QtCore.Signal(str)
    qualification_output = QtCore.Signal(str)
    qualification_prompt = QtCore.Signal(str)
    qualification_selftest_event = QtCore.Signal(object)
    qualification_campaign_event = QtCore.Signal(object)
    qualification_finished = QtCore.Signal(bool, str, object)

    # Regulator calibration run signals
    regulator_calibration_stage = QtCore.Signal(str)
    regulator_calibration_output = QtCore.Signal(str)
    regulator_calibration_finished = QtCore.Signal(bool, str, object)
    regulator_calibration_batch_stage = QtCore.Signal(str)
    regulator_calibration_batch_output = QtCore.Signal(str)
    regulator_calibration_batch_progress = QtCore.Signal(int, int, object)
    regulator_calibration_batch_finished = QtCore.Signal(bool, str, object)

    # Plate-reader analysis signals
    plate_reader_analysis_preview_stage = QtCore.Signal(str)
    plate_reader_analysis_preview_finished = QtCore.Signal(bool, str, object)
    plate_reader_analysis_stage = QtCore.Signal(str)
    plate_reader_analysis_output = QtCore.Signal(str)
    plate_reader_analysis_finished = QtCore.Signal(bool, str, object)

    # Application update check signals
    app_update_check_started = QtCore.Signal()
    app_update_check_finished = QtCore.Signal(object)

    # Preprogrammed sequence signals
    sequence_state_changed = QtCore.Signal(str)         # "idle" | "countdown" | "running"
    sequence_countdown_s   = QtCore.Signal(float)       # seconds remaining
    sequence_started       = QtCore.Signal(str)         # seq_id
    sequence_completed     = QtCore.Signal(str)         # seq_id
    sequence_error         = QtCore.Signal(str)         # message

    def __init__(
        self,
        machine,
        model,
        profile: HardwareProfile = CURRENT_PROFILE,
        monotonic_fn=None,
        timer_factory=None,
        runtime_context=None,
        experimental_features=None,
        experimental_balance_service=None,
        saved_target_authorizer=None,
        machine_data_paths=None,
        authorized_machine_context=None,
        configuration_transactions=None,
        configuration_safety_guard=None,
    ):
        super().__init__()

        self.machine = machine
        self.model = model
        self.profile = profile
        self.runtime_context = runtime_context or PRODUCTION_RUNTIME_CONTEXT
        self.saved_target_authorizer = saved_target_authorizer
        self.machine_data_paths = machine_data_paths
        self.authorized_machine_context = authorized_machine_context
        self.configuration_transactions = configuration_transactions
        self.configuration_safety_guard = configuration_safety_guard
        self._configuration_capture_evidence = {}
        self._configuration_recovery_required = False
        self._plate_calibration_session = None
        self.experimental_features = (
            experimental_features or ExperimentalFeatures()
        )
        if not isinstance(self.experimental_features, ExperimentalFeatures):
            raise TypeError("experimental_features must be ExperimentalFeatures")
        self._experimental_balance_service = experimental_balance_service
        self._experimental_balance_connection_snapshot = None
        self._experimental_balance_last_reading = None
        self._experimental_balance_ports = ()
        self._experimental_balance_stream_opt_in = False
        self._experimental_balance_active_stream_request = None
        if self.experimental_features.balance_integration:
            if self._experimental_balance_service is None:
                raise ValueError(
                    "enabled experimental balance requires a service"
                )
            self._experimental_balance_service.connection_changed.connect(
                self._on_experimental_balance_connection_changed
            )
            self._experimental_balance_service.reading_received.connect(
                self._on_experimental_balance_reading_received
            )
            self._experimental_balance_service.error_occurred.connect(
                self._on_experimental_balance_error_occurred
            )
            self._experimental_balance_service.request_progress.connect(
                self._on_experimental_balance_request_progress
            )
            self._experimental_balance_service.request_finished.connect(
                self._on_experimental_balance_request_finished
            )
        elif self._experimental_balance_service is not None:
            raise ValueError(
                "experimental balance service supplied while feature is disabled"
            )
        self._monotonic_fn = monotonic_fn or time.monotonic
        self._timer_factory = timer_factory or (lambda parent: QtCore.QTimer(parent))
        self.balance = None  # to be set for legacy if needed
        self._port_info = {}  # device -> ListPortInfo

        self.expected_position = self.model.machine_model.get_current_position_dict()
        self.expected_location = self.model.machine_model.get_current_location()
        self._position_reconciliation = {
            "state": "settled",
            "reason": "controller_initialization",
            "expected_position": copy.deepcopy(self.expected_position),
        }
        self._pending_motion_endpoint_evidence = None

        self._dfu_thread: DfuUpdateWorker | None = None
        self._qualification_worker = None
        self._regulator_calibration_worker = None
        self._regulator_calibration_state = None
        self._regulator_calibration_batch_state = None
        self._plate_reader_analysis_preview_worker = None
        self._plate_reader_analysis_worker = None
        self._app_update_process = None
        self._app_update_check_thread = None
        self._app_update_check_worker = None
        self._last_app_update_check_result = None
        self._last_app_rollback_check_result = None
        self._app_update_launch_grace_s = 0.25

        # Defaults; tweak if you keep them elsewhere
        self._dfu_script = Path(__file__).resolve().parent / "dfu_update.py"
        self._bin_path   = Path("/home/labcraft/LabCraft_printer/firmware/freeRTOS_LabCraft.bin")
        self._boot_chip  = "gpiochip0"; self._boot_off = 24
        self._rst_chip   = "gpiochip0"; self._rst_off  = 23
        self._cwd        = None  # or Path("/home/labcraft/LabCraft_printer")

        self._ui_dir = Path(__file__).resolve().parent              # LabCraft_Printer/FreeRTOS-interface
        self._repo_root = self._ui_dir.parent                       # LabCraft_Printer
        self._reset_report_log_path = self._repo_root / "logs" / "board_reset_reports.jsonl"
        self._last_reset_debug_bundle_context = None
        self._last_connection_loss_debug_bundle_context = None
        self._last_transport_fault_debug_bundle_context = None

        self._dfu_script = (self._ui_dir / "dfu_update.py").resolve()
        self._cwd = self._repo_root                                 # IMPORTANT: run child from repo root

        self._bin_path_current = (self._repo_root / "firmware" / "artifacts"/ "LabCraft_firmware.bin").resolve()
        self._bin_path_legacy  = (self._repo_root / "firmware" / "freeRTOS_LabCraft_legacy.bin").resolve()

        # This variable will temporarily hold the callback for the next capture.
        self.pending_capture_callback = None
        self.pending_capture_context = None
        self.pending_capture_active = False
        self.pending_capture_started_monotonic = None
        self.pending_capture_timeout_ms = 8_000
        self.pending_capture_throughput_timeout_ms = 1_500
        self.pending_capture_guard_timer = None
        self.pending_capture_request_id = None
        self.pending_capture_recovery_attempted = False
        self.pending_capture_throughput_mode = False
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None
        self.capture_coordinator = CaptureCoordinator()
        self.droplet_imager_dirty_shutdown = False
        self._droplet_capture_performance_diagnostics = DropletCapturePerformanceDiagnostics()

        self._array_state = "idle"
        self._array_context = None
        self._pending_reset_print_settings_restore = None

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)
        self.machine.homing_completed.connect(self.home_complete_handler)
        self.machine.gripper_open.connect(self.model.machine_model.open_gripper)
        self.machine.gripper_closed.connect(self.model.machine_model.close_gripper)
        
        self.machine.machine_connected_signal.connect(self.update_machine_connection_status)
        self.machine.reset_report_received.connect(self.handle_reset_report)
        serial_loss_signal = getattr(self.machine, "serial_connection_lost", None)
        if serial_loss_signal is not None:
            serial_loss_signal.connect(self.handle_serial_connection_lost)
        transport_fault_signal = getattr(self.machine, "transport_faulted", None)
        if transport_fault_signal is not None:
            transport_fault_signal.connect(self.handle_transport_fault)
        xy_motion_fault_signal = getattr(self.machine, "xy_motion_faulted", None)
        if xy_motion_fault_signal is not None:
            xy_motion_fault_signal.connect(self.handle_xy_motion_fault)
        xy_recovery_state_signal = getattr(
            self.machine,
            "xy_motion_recovery_state_changed",
            None,
        )
        if xy_recovery_state_signal is not None:
            xy_recovery_state_signal.connect(self.xy_motion_recovery_state_changed.emit)
        self.machine.disconnect_complete_signal.connect(self.reset_board)
        self.machine.flash_state_updated.connect(self.model.update_flash_session_state)
        ejection_signal = getattr(self.machine, "ejection_command_event", None)
        if ejection_signal is not None:
            ejection_signal.connect(self._on_machine_ejection_command_event)
        imaging_ejection_signal = getattr(
            self.machine,
            "imaging_ejection_event",
            None,
        )
        if imaging_ejection_signal is not None:
            imaging_ejection_signal.connect(self._on_machine_ejection_command_event)
        self.model.machine_model.command_numbers_updated.connect(self.update_command_numbers)
        self.machine.command_queue.commands_completed.connect(
            self._begin_position_reconciliation
        )
        self.machine_workflow_interrupted_signal.connect(
            self._on_plate_calibration_workflow_interrupted
        )
        machine_paused_signal = getattr(
            self.model.machine_model, "machine_paused", None
        )
        if machine_paused_signal is not None:
            machine_paused_signal.connect(self._on_plate_calibration_pause_changed)

        # self.machine.balance.balance_mass_updated_signal.connect(self.model.calibration_model.update_mass)
        self.machine.all_calibration_droplets_printed.connect(self.start_mass_stabilization_timer)

        self.model.printer_head_manager.volume_changed_signal.connect(self.update_volumes_in_view)
        
        self.connect_droplet_camera_signals()
        # self.model.calibration_manager.captureImageRequested.connect(self.handle_capture_request)
        # self.model.calibration_manager.moveRequested.connect(self.handle_move_request)
        # self.model.calibration_manager.moveAbsoluteRequested.connect(self.handle_absolute_move_request)
        # # self.model.calibration_manager.dropletChangeRequested.connect(self.handle_droplet_change_request)
        # self.model.calibration_manager.changeSettingsRequested.connect(self.handle_settings_change_request)
        # self.machine.droplet_camera.image_captured_signal.connect(self._on_image_captured)

        # --- Preprogrammed sequences runner ---
        self._seq_state   = "idle"
        self._seq_id      = None
        self._seq_params  = {}
        self._seq_deadline_monotonic = 0.0

        self._seq_timer = self._timer_factory(self)
        self._seq_timer.setInterval(100)  # 10 Hz countdown updates
        self._seq_timer.timeout.connect(self._on_seq_tick)

        # Detect end-of-sequence when queue drains
        self.machine.command_queue.commands_completed.connect(self._on_commands_completed_for_sequence)

        # Registry of available sequences
        self._sequence_builders = {
            "pickup_slot_imager_return": self._seq_pickup_slot_imager_return,
            "led_on_wait_off":           self._seq_led_on_wait_off,
            "imager_plate_imager":       self._seq_imager_plate_imager,
            "snake_grid_droplet_print": self._seq_snake_grid_droplet_print,
            "droplet_walk_y": self._seq_droplet_walk_y,
            "bridge_and_pull_y": self._seq_bridge_and_pull_y,
            "bridge_pull_y_3step": self._seq_bridge_pull_y_3step,
        }

    def _reject_physical_action(self, action):
        configuration_shutdown_actions = {
            "machine disconnection",
            "balance disconnection",
            "refuel camera stop",
        }
        if (
            getattr(self, "_configuration_recovery_required", False)
            and action not in configuration_shutdown_actions
        ):
            message = (
                "Configuration recovery is required. Restart the application and "
                "resolve the startup diagnostic before using hardware."
            )
            self.error_occurred_signal.emit("Configuration Recovery Required", message)
            return message
        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        if runtime_context.hardware_access_allowed:
            return None
        message = runtime_context.blocked_message(action)
        title = "Development Mode" if runtime_context.is_development else "Simulation Mode"
        self.error_occurred_signal.emit(title, message)
        return message

    def _reject_updater_action(self, action):
        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        if runtime_context.updater_access_allowed:
            return None
        message = runtime_context.blocked_message(action)
        title = "Development Mode" if runtime_context.is_development else "Simulation Mode"
        self.error_occurred_signal.emit(title, message)
        return message

    def connect_droplet_camera_signals(self):
        """Connect the droplet camera signals to the controller."""
        self.model.calibration_manager.captureImageRequested.connect(self.handle_capture_request)
        self.model.calibration_manager.moveRequested.connect(self.handle_move_request)
        self.model.calibration_manager.moveAbsoluteRequested.connect(self.handle_absolute_move_request)
        self.model.calibration_manager.changeSettingsRequested.connect(self.handle_settings_change_request)
        self._connect_calibration_capture_performance_diagnostics()
        try:
            camera = self.machine.droplet_camera
            phase_signal = getattr(camera, "capture_phase_signal", None)
            if phase_signal is not None:
                self._connect_qt_signal(phase_signal, self._on_camera_capture_phase, queued=True)
            completion_signal = getattr(camera, "capture_completed_signal", None)
            if completion_signal is not None:
                self._connect_qt_signal(completion_signal, self._on_capture_completed_payload, queued=True)
            else:
                self._connect_qt_signal(camera.image_captured_signal, self._on_image_captured, queued=True)
                self._connect_qt_signal(camera.capture_failed_signal, self._on_capture_failed, queued=True)
        except AttributeError:
            print("Droplet camera not initialized or image_captured_signal not available.")

    def _connect_calibration_capture_performance_diagnostics(self):
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        signal = getattr(manager, "capturePerformanceDiagnosticEvent", None)
        if signal is None:
            self._calibration_capture_performance_diagnostics_connected = False
            return
        manager_id = id(manager)
        if (
            bool(getattr(self, "_calibration_capture_performance_diagnostics_connected", False))
            and getattr(self, "_calibration_capture_performance_diagnostics_manager_id", None) == manager_id
        ):
            return
        try:
            signal.connect(self._on_calibration_capture_performance_diagnostic_event)
            self._calibration_capture_performance_diagnostics_connected = True
            self._calibration_capture_performance_diagnostics_manager_id = manager_id
        except (TypeError, RuntimeError):
            self._calibration_capture_performance_diagnostics_connected = False
            pass

    def _on_calibration_capture_performance_diagnostic_event(self, event_kind, payload=None):
        return self.record_droplet_capture_performance_marker(
            event_kind,
            payload if isinstance(payload, dict) else {},
        )

    def _calibration_capture_performance_bridge_status(self):
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        manager_enabled = None
        getter = getattr(manager, "is_capture_performance_diagnostics_enabled", None)
        if callable(getter):
            try:
                manager_enabled = bool(getter())
            except Exception:
                manager_enabled = None
        return {
            "bridge_connected": bool(getattr(self, "_calibration_capture_performance_diagnostics_connected", False)),
            "calibration_manager_present": manager is not None,
            "calibration_manager_enabled": manager_enabled,
        }

    def _set_droplet_camera_performance_diagnostics_enabled(self, enabled):
        machine = getattr(self, "machine", None)
        setter = getattr(machine, "set_droplet_capture_performance_diagnostics_enabled", None)
        if callable(setter):
            try:
                return setter(bool(enabled))
            except Exception:
                return None
        camera = getattr(machine, "droplet_camera", None)
        camera_setter = getattr(camera, "set_capture_performance_diagnostics_enabled", None)
        if callable(camera_setter):
            try:
                return camera_setter(bool(enabled))
            except Exception:
                return None
        return None
    
    def disconnect_droplet_camera_signals(self):
        try:
            self.model.calibration_manager.captureImageRequested.disconnect(self.handle_capture_request)
            self.model.calibration_manager.moveRequested.disconnect(self.handle_move_request)
            self.model.calibration_manager.moveAbsoluteRequested.disconnect(self.handle_absolute_move_request)
            self.model.calibration_manager.changeSettingsRequested.disconnect(self.handle_settings_change_request)
        except Exception:
            pass
        try:
            camera = self.machine.droplet_camera
            phase_signal = getattr(camera, "capture_phase_signal", None)
            if phase_signal is not None:
                phase_signal.disconnect(self._on_camera_capture_phase)
            completion_signal = getattr(camera, "capture_completed_signal", None)
            if completion_signal is not None:
                completion_signal.disconnect(self._on_capture_completed_payload)
            image_signal = getattr(camera, "image_captured_signal", None)
            if image_signal is not None:
                image_signal.disconnect(self._on_image_captured)
            fail_signal = getattr(camera, "capture_failed_signal", None)
            if fail_signal is not None:
                fail_signal.disconnect(self._on_capture_failed)
        except Exception:
            pass

    @staticmethod
    def _queued_connection_type():
        qt = getattr(QtCore, "Qt", None)
        connection = getattr(qt, "QueuedConnection", None)
        if connection is not None:
            return connection
        connection_type = getattr(qt, "ConnectionType", None)
        return getattr(connection_type, "QueuedConnection", None)

    def _connect_qt_signal(self, signal, slot, *, queued=False):
        if queued:
            connection = self._queued_connection_type()
            if connection is not None:
                try:
                    signal.connect(slot, connection)
                    return
                except TypeError:
                    pass
        signal.connect(slot)

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.model.update_state(status_dict)
        context = getattr(self, "_array_context", None) or {}
        if self.get_array_run_state() == "stop_requested" and context.get("soft_stop_pending"):
            if context.get("soft_stop_origin") == "immediate_pause":
                self._advance_paused_array_soft_stop_from_status()
                return
            soft_stop_phase = context.get("soft_stop_phase", "waiting_watermark")
            if (
                soft_stop_phase == "waiting_watermark"
                and self.model.machine_model.pause_watermark_reached
                and self.model.machine_model.transport_paused
            ):
                self._begin_soft_stop_clear_and_park()
            elif soft_stop_phase == "waiting_completion_catchup":
                self._maybe_complete_array_soft_stop_after_catchup()

    def handle_error(self, error_message):
        """Handle errors from the machine."""
        #print(f"Error occurred: {error_message}")
        self.error_occurred_signal.emit('Error Occurred',error_message)

    def update_command_numbers(self):
        """Pass the current command and last completed command to the command queue"""
        self.machine.update_command_numbers(*self.model.machine_model.get_command_numbers())
        self._advance_position_reconciliation()
        self._advance_plate_calibration_session()
    
    def update_volumes_in_view(self):
        """Update the volume in the view."""
        self.update_volumes_in_view_signal.emit()

    def set_axis_maxspeed(self, axis_idx, max_speed):
        """Set the maximum speed for a specific axis."""
        self.machine.set_axis_maxspeed(axis_idx, max_speed)

    def set_axis_accel(self, axis_idx, accel, handler=None, kwargs=None, manual=False):
        """Set the acceleration for a specific axis."""
        if handler is None and kwargs is None and manual is False:
            return self.machine.set_axis_accel(axis_idx, accel)
        if kwargs is None and manual is False:
            return self.machine.set_axis_accel(axis_idx, accel, handler=handler)
        return self.machine.set_axis_accel(axis_idx, accel, handler=handler, kwargs=kwargs, manual=manual)

    def reset_board(self):
        """Reset the machine board."""
        self._emit_machine_workflow_interrupted("machine_disconnected")
        self.machine.reset_board()
        self.model.machine_model.disconnect_machine()
    
    def update_available_ports(self):
        if self._reject_physical_action("serial port enumeration") is not None:
            self._port_info = {}
            self.model.machine_model.update_ports([])
            return
        ports = []
        self._port_info = {}

        for p in comports():
            dev = p.device  # e.g. "COM3" on Windows, "/dev/ttyACM0" on Linux
            if not dev:
                continue
            if "ttyAMA" in dev:  # keep your Pi filter
                continue

            ports.append(dev)
            self._port_info[dev] = p

        self.model.machine_model.update_ports(ports)

    @property
    def experimental_balance_enabled(self) -> bool:
        return bool(
            self.experimental_features.balance_integration
            and self._experimental_balance_service is not None
        )

    @staticmethod
    def _port_metadata_text(info) -> str:
        return " ".join(
            str(getattr(info, name, "") or "").casefold()
            for name in ("description", "manufacturer", "product")
        )

    @classmethod
    def _is_mcu_port_info(cls, info) -> bool:
        vid = _normalized_usb_id(getattr(info, "vid", None))
        pid = _normalized_usb_id(getattr(info, "pid", None))
        text = cls._port_metadata_text(info)
        return (
            (vid == "10c4" and pid == "ea60")
            or vid == "0483"
            or "cp210" in text
            or "stm" in text
        )

    @classmethod
    def _is_balance_port_info(cls, info) -> bool:
        vid = _normalized_usb_id(getattr(info, "vid", None))
        pid = _normalized_usb_id(getattr(info, "pid", None))
        if vid == "067b" and pid == "23a3":
            return True
        text = cls._port_metadata_text(info)
        return any(
            marker in text
            for marker in (
                "prolific",
                "balance",
                "scale",
                "ohaus",
                "sartorius",
                "mettler",
                "toledo",
            )
        )

    def _validated_machine_serial_paths(self) -> tuple[str, ...]:
        """Return only active or identity-validated printer serial paths."""

        paths = []
        active_machine_port = str(self.get_machine_port() or "").strip()
        if active_machine_port:
            paths.append(active_machine_port)

        identity_getter = getattr(
            self.machine,
            "get_machine_log_port_identity",
            None,
        )
        identity = identity_getter() if callable(identity_getter) else None
        if identity is not None:
            for value in (
                getattr(identity, "requested_path", None),
                getattr(identity, "system_device", None),
                *tuple(getattr(identity, "by_id_paths", ()) or ()),
            ):
                if isinstance(value, str) and value.strip():
                    paths.append(value.strip())
        return tuple(dict.fromkeys(paths))

    def list_experimental_balance_ports(
        self,
    ) -> tuple[ExperimentalBalancePort, ...]:
        if self._reject_physical_action(
            "experimental balance serial port enumeration"
        ) is not None:
            self._experimental_balance_ports = ()
            return ()
        if not self.experimental_balance_enabled:
            self._experimental_balance_ports = ()
            return ()

        reserved_devices = {
            _resolved_serial_path(path)
            for path in self._validated_machine_serial_paths()
        }
        aliases_by_device = _serial_by_id_aliases()
        descriptors = []
        seen_system_devices = set()
        for info in comports():
            system_device = str(getattr(info, "device", "") or "").strip()
            if not system_device or "ttyAMA" in system_device:
                continue
            resolved_device = _resolved_serial_path(system_device)
            if resolved_device in reserved_devices:
                continue
            if self._is_mcu_port_info(info) or not self._is_balance_port_info(info):
                continue
            if resolved_device in seen_system_devices:
                continue
            seen_system_devices.add(resolved_device)

            by_id_paths = aliases_by_device.get(resolved_device, ())
            device_path = by_id_paths[0] if by_id_paths else system_device
            vid = _normalized_usb_id(getattr(info, "vid", None))
            pid = _normalized_usb_id(getattr(info, "pid", None))
            vid_pid = f"{vid}:{pid}" if vid and pid else None
            description = str(getattr(info, "description", "") or "") or None
            manufacturer = str(getattr(info, "manufacturer", "") or "") or None
            product = str(getattr(info, "product", "") or "") or None
            serial_number = str(getattr(info, "serial_number", "") or "") or None
            identity = product or description or manufacturer or "Balance adapter"
            suffix = f" [{vid_pid}]" if vid_pid else ""
            descriptors.append(
                ExperimentalBalancePort(
                    device_path=device_path,
                    system_device=system_device,
                    by_id_paths=tuple(by_id_paths),
                    display_label=f"{identity} — {device_path}{suffix}",
                    vid=vid,
                    pid=pid,
                    vid_pid=vid_pid,
                    description=description,
                    manufacturer=manufacturer,
                    product=product,
                    serial_number=serial_number,
                )
            )
        self._experimental_balance_ports = tuple(
            sorted(descriptors, key=lambda item: item.display_label.casefold())
        )
        return self._experimental_balance_ports

    def _experimental_balance_command_accepted(
        self, result, action: str
    ) -> bool:
        if bool(getattr(result, "accepted", False)):
            return True
        detail = str(getattr(result, "detail", "") or f"{action} was rejected")
        self.error_occurred_signal.emit("Experimental Balance", detail)
        return False

    def connect_experimental_balance(self, port: str) -> bool:
        if self._reject_physical_action(
            "experimental balance connection"
        ) is not None:
            return False
        if not self.experimental_balance_enabled:
            self.error_occurred_signal.emit(
                "Experimental Balance",
                "Experimental balance integration is not enabled.",
            )
            return False
        selected = str(port or "").strip()
        available = {
            descriptor.device_path: descriptor
            for descriptor in self.list_experimental_balance_ports()
        }
        descriptor = available.get(selected)
        if descriptor is None:
            self.error_occurred_signal.emit(
                "Experimental Balance",
                "Select a currently available balance adapter before connecting.",
            )
            return False
        reserved_paths = self._validated_machine_serial_paths()
        if any(
            _resolved_serial_path(descriptor.device_path)
            == _resolved_serial_path(reserved_path)
            for reserved_path in reserved_paths
        ):
            self.error_occurred_signal.emit(
                "Experimental Balance",
                "The selected port is reserved by the printer controller or MCU log channel.",
            )
            return False
        result = self._experimental_balance_service.connect_balance(
            descriptor.device_path
        )
        return self._experimental_balance_command_accepted(result, "Connect")

    def disconnect_experimental_balance(self) -> bool:
        if self._reject_physical_action(
            "experimental balance disconnection"
        ) is not None:
            return False
        if not self.experimental_balance_enabled:
            return False
        result = self._experimental_balance_service.disconnect_balance()
        return self._experimental_balance_command_accepted(result, "Disconnect")

    def get_experimental_balance_connection_snapshot(self):
        return self._experimental_balance_connection_snapshot

    def get_experimental_balance_last_reading(self):
        return self._experimental_balance_last_reading

    @property
    def experimental_balance_stream_opt_in(self) -> bool:
        return bool(self._experimental_balance_stream_opt_in)

    @staticmethod
    def _experimental_balance_state_name(snapshot) -> str:
        state = getattr(snapshot, "state", "")
        return str(getattr(state, "value", state) or "").strip().casefold()

    def _experimental_balance_is_streaming(self) -> bool:
        snapshot = self._experimental_balance_connection_snapshot
        if snapshot is None and self._experimental_balance_service is not None:
            try:
                snapshot = self._experimental_balance_service.connection_snapshot
            except Exception:
                snapshot = None
        return self._experimental_balance_state_name(snapshot) == "streaming"

    def set_experimental_balance_stream_opt_in(self, enabled: bool) -> bool:
        desired = bool(enabled)
        if not self.experimental_balance_enabled:
            return False
        if desired and not self._experimental_balance_is_streaming():
            self.error_occurred_signal.emit(
                "Experimental Balance",
                "Connect the balance and wait for Streaming before enabling it for stream capture.",
            )
            return False
        if desired == self._experimental_balance_stream_opt_in:
            return True
        self._experimental_balance_stream_opt_in = desired
        self.experimental_balance_stream_opt_in_changed.emit(desired)
        return True

    @staticmethod
    def _balance_value(value):
        return str(getattr(value, "value", value) or "")

    @classmethod
    def _balance_evidence_payload(cls, evidence):
        if evidence is None:
            return None
        return {
            "sample_count": int(evidence.sample_count),
            "window_started_ns": int(evidence.window_started_ns),
            "window_ended_ns": int(evidence.window_ended_ns),
            "window_duration_ns": int(evidence.window_duration_ns),
            "mean_mass_mg_unrounded": str(evidence.mean_mass_mg_unrounded),
            "quantized_mean_mass_mg": str(evidence.quantized_mean_mass_mg),
            "minimum_mass_mg": str(evidence.minimum_mass_mg),
            "maximum_mass_mg": str(evidence.maximum_mass_mg),
            "span_mg": str(evidence.span_mg),
            "population_standard_deviation_mg": str(
                evidence.population_standard_deviation_mg
            ),
            "fitted_slope_mg_per_second": str(
                evidence.fitted_slope_mg_per_second
            ),
            "device_stable_sample_count": int(evidence.device_stable_sample_count),
            "device_unstable_sample_count": int(evidence.device_unstable_sample_count),
            "all_device_stable": bool(evidence.all_device_stable),
        }

    @classmethod
    def _balance_progress_payload(cls, progress):
        reading = progress.latest_reading
        return {
            "elapsed_ms": int(progress.elapsed_ns // 1_000_000),
            "retained_sample_count": int(progress.retained_sample_count),
            "latest_mass_mg": str(reading.mass_mg),
            "latest_device_stable": bool(reading.device_stable),
            "evidence": cls._balance_evidence_payload(progress.evidence),
        }

    @staticmethod
    def _balance_policy_payload(policy):
        return {
            "ignore_period_ns": int(policy.ignore_period_ns),
            "minimum_window_ns": int(policy.minimum_window_ns),
            "minimum_samples": int(policy.minimum_samples),
            "maximum_span_mg": str(policy.maximum_span_mg),
            "maximum_absolute_slope_mg_per_second": str(
                policy.maximum_absolute_slope_mg_per_second
            ),
            "timeout_ns": int(policy.timeout_ns),
            "require_every_sample_device_stable": bool(
                policy.require_every_sample_device_stable
            ),
            "maximum_retained_samples": int(policy.maximum_retained_samples),
            "display_resolution_mg": str(policy.display_resolution_mg),
        }

    def _balance_connection_provenance(self):
        snapshot = self._experimental_balance_connection_snapshot
        port = str(getattr(snapshot, "port", "") or "") or None
        descriptor = None
        for candidate in getattr(self, "_experimental_balance_ports", ()):
            candidate_paths = {
                str(candidate.device_path or ""),
                str(candidate.system_device or ""),
                *(str(path or "") for path in candidate.by_id_paths),
            }
            if port and port in candidate_paths:
                descriptor = candidate
                break
        device = None
        if descriptor is not None:
            device = {
                "device_path": descriptor.device_path,
                "system_device": descriptor.system_device,
                "by_id_paths": list(descriptor.by_id_paths),
                "vid": descriptor.vid,
                "pid": descriptor.pid,
                "vid_pid": descriptor.vid_pid,
                "description": descriptor.description,
                "manufacturer": descriptor.manufacturer,
                "product": descriptor.product,
                "serial_number": descriptor.serial_number,
            }
        return {
            "port": port,
            "connection_generation": int(
                getattr(snapshot, "connection_generation", 0) or 0
            ),
            "device": device,
            "serial_settings": {
                "baud_rate": 9600,
                "data_bits": 8,
                "parity": "N",
                "stop_bits": 1,
                "read_timeout_seconds": "0.1",
                "read_size_bytes": 64,
                "software_flow_control": False,
                "hardware_flow_control": False,
                "dsr_dtr_flow_control": False,
                "receive_only": True,
            },
        }

    @classmethod
    def _balance_result_payload(cls, result, binding=None):
        stable_mass = getattr(result, "stable_mass_mg", None)
        binding = dict(binding or {})
        request = binding.get("request")
        return {
            "request_id": str(result.request_id),
            "stream_session_id": str(result.stream_session_id),
            "phase": cls._balance_value(result.phase),
            "outcome": cls._balance_value(result.outcome),
            "completed_monotonic_ns": int(result.completed_monotonic_ns),
            "stable_mass_mg": None if stable_mass is None else str(stable_mass),
            "evidence": cls._balance_evidence_payload(result.evidence),
            "failure_reason": cls._balance_value(result.failure_reason),
            "detail": str(result.detail or ""),
            "total_readings_seen": int(result.total_readings_seen),
            "total_stable_readings": int(result.total_stable_readings),
            "total_unstable_readings": int(result.total_unstable_readings),
            "request": (
                {
                    "started_monotonic_ns": int(request.started_monotonic_ns),
                    "policy": cls._balance_policy_payload(request.policy),
                }
                if request is not None
                else None
            ),
            "connection": dict(binding.get("connection") or {}),
        }

    def _stream_capture_manager(self):
        return getattr(getattr(self, "model", None), "calibration_manager", None)

    def _on_machine_ejection_command_event(self, event):
        manager = self._stream_capture_manager()
        recorder = getattr(manager, "record_stream_gravimetric_ejection_event", None)
        if callable(recorder):
            recorder(event)

    def _submit_stream_gravimetric_mass_request(
        self,
        request_id: str,
        session_id: str,
        phase,
    ):
        from BalanceProtocol import StableMassPhase, StableMassRequest

        explicit_phase = (
            phase
            if isinstance(phase, StableMassPhase)
            else StableMassPhase(str(phase))
        )
        request = StableMassRequest(
            request_id=str(request_id),
            stream_session_id=str(session_id),
            phase=explicit_phase,
            started_monotonic_ns=time.monotonic_ns(),
        )
        binding = {
            "request_id": request.request_id,
            "session_id": request.stream_session_id,
            "phase": request.phase.value,
            "cancel_requested": False,
            "request": request,
            "connection": self._balance_connection_provenance(),
        }
        self._experimental_balance_active_stream_request = binding
        result = self._experimental_balance_service.request_stable_mass(request)
        manager = self._stream_capture_manager()
        if not bool(getattr(result, "accepted", False)):
            self._experimental_balance_active_stream_request = None
            detail = str(getattr(result, "detail", "") or "Stable-mass request was rejected.")
            if request.phase is StableMassPhase.STARTING:
                manager.mark_stream_gravimetric_balance_request_failure(
                    request.request_id,
                    request.stream_session_id,
                    request_status="rejected",
                    message=detail,
                )
            else:
                manager.mark_stream_gravimetric_ending_mass_request_failure(
                    request.request_id,
                    request.stream_session_id,
                    request_status="rejected",
                    message=detail,
                )
            self.error_occurred_signal.emit("Experimental Balance", detail)
            return False, detail
        if request.phase is StableMassPhase.STARTING:
            manager.mark_stream_gravimetric_balance_request_started(
                request.request_id,
                request.stream_session_id,
            )
        else:
            manager.mark_stream_gravimetric_ending_mass_request_started(
                request.request_id,
                request.stream_session_id,
            )
        return True, ""

    def _submit_stream_gravimetric_starting_mass_request(
        self,
        request_id: str,
        session_id: str,
    ):
        from BalanceProtocol import StableMassPhase

        return self._submit_stream_gravimetric_mass_request(
            request_id,
            session_id,
            StableMassPhase.STARTING,
        )

    def start_stream_gravimetric_capture_with_balance(
        self,
        rep_override=None,
        notes="",
        capture_mode="timecourse",
    ):
        if not self.experimental_balance_enabled:
            return False, "Experimental balance integration is not enabled."
        if not self.experimental_balance_stream_opt_in:
            return False, "Use connected balance is not enabled for this application session."
        if not self._experimental_balance_is_streaming():
            return False, "Balance must be Streaming before requesting a starting mass."
        if self._experimental_balance_active_stream_request is not None:
            return False, "A stream-capture balance request is already active."
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue to finish before starting the mass workflow."
        manager = self._stream_capture_manager()
        ok, message, session_id = manager.stage_stream_gravimetric_balance_start(
            None,
            rep_override=rep_override,
            notes=notes,
            capture_mode=capture_mode,
        )
        if not ok:
            return False, message
        return True, ""

    def _stream_gravimetric_machine_queue_empty(self):
        machine = getattr(self, "machine", None)
        checker = getattr(machine, "check_if_all_completed", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return False

    def start_stream_gravimetric_starting_mass(self):
        if not self.experimental_balance_enabled or not self._experimental_balance_is_streaming():
            return False, "Reconnect the balance before starting the starting-mass reading."
        if self._experimental_balance_active_stream_request is not None:
            return False, "A stream-capture balance request is already active."
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue before measuring the starting mass."
        manager = self._stream_capture_manager()
        request_id = f"stream_start_{uuid.uuid4().hex}"
        ok, message, session_id = manager.stage_stream_gravimetric_starting_mass_request(
            request_id
        )
        if not ok:
            return False, message
        return self._submit_stream_gravimetric_starting_mass_request(request_id, session_id)

    def use_previous_stream_gravimetric_starting_mass(self):
        if not self.experimental_balance_enabled or not self.experimental_balance_stream_opt_in:
            return False, "Balance-backed stream capture is not enabled."
        if not self._experimental_balance_is_streaming():
            return False, "Balance must remain Streaming before reusing the previous mass."
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue before reusing the previous mass."
        return self._stream_capture_manager().use_previous_stream_gravimetric_starting_mass()

    def measure_new_stream_gravimetric_starting_mass(self):
        return self._stream_capture_manager().measure_new_stream_gravimetric_starting_mass()

    def retry_stream_gravimetric_starting_mass(self):
        if not self.experimental_balance_enabled or not self._experimental_balance_is_streaming():
            return False, "Reconnect the balance before retrying the starting-mass reading."
        if self._experimental_balance_active_stream_request is not None:
            return False, "The current balance request has not finished."
        manager = self._stream_capture_manager()
        request_id = f"stream_start_{uuid.uuid4().hex}"
        ok, message, session_id = manager.prepare_stream_gravimetric_balance_retry(
            request_id
        )
        if not ok:
            return False, message
        return self._submit_stream_gravimetric_starting_mass_request(
            request_id,
            session_id,
        )

    def cancel_stream_gravimetric_starting_mass(self):
        binding = self._experimental_balance_active_stream_request
        if binding is None or binding.get("phase") != "starting":
            return False, "There is no active starting-mass request."
        manager = self._stream_capture_manager()
        ok, message = manager.mark_stream_gravimetric_balance_request_cancelling(
            binding["request_id"],
            binding["session_id"],
        )
        if not ok:
            return False, message
        binding["cancel_requested"] = True
        result = self._experimental_balance_service.cancel_stable_mass(
            binding["request_id"]
        )
        if not bool(getattr(result, "accepted", False)):
            detail = str(getattr(result, "detail", "") or "Cancellation was rejected.")
            self.error_occurred_signal.emit("Experimental Balance", detail)
            return False, detail
        return True, ""

    def confirm_stream_gravimetric_starting_mass(self):
        if self._experimental_balance_active_stream_request is not None:
            return False, "The stable-mass request has not finished."
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue before reinstalling the measured tube."
        return self._stream_capture_manager().confirm_stream_gravimetric_starting_mass()

    def _retire_stream_gravimetric_balance_request(self, *, phase=None):
        binding = self._experimental_balance_active_stream_request
        if binding is not None and phase is not None and binding.get("phase") != phase:
            return
        self._experimental_balance_active_stream_request = None
        if binding is None:
            return
        try:
            self._experimental_balance_service.cancel_stable_mass(
                binding["request_id"]
            )
        except Exception as exc:
            self.error_occurred_signal.emit(
                "Experimental Balance",
                f"Could not cancel retired stable-mass request: {exc}",
            )

    def _retire_stream_gravimetric_starting_mass_request(self):
        self._retire_stream_gravimetric_balance_request(phase="starting")

    def start_stream_gravimetric_ending_mass(self):
        from BalanceProtocol import StableMassPhase

        if not self.experimental_balance_enabled:
            return False, "Experimental balance integration is not enabled."
        if not self.experimental_balance_stream_opt_in:
            return False, "Use connected balance is not enabled for this application session."
        if not self._experimental_balance_is_streaming():
            return False, "Balance must be Streaming before requesting an ending mass."
        if self._experimental_balance_active_stream_request is not None:
            return False, "A stream-capture balance request is already active."
        manager = self._stream_capture_manager()
        request_id = f"stream_end_{uuid.uuid4().hex}"
        ok, message, session_id = (
            manager.stage_stream_gravimetric_ending_mass_request(request_id)
        )
        if not ok:
            return False, message
        return self._submit_stream_gravimetric_mass_request(
            request_id,
            session_id,
            StableMassPhase.ENDING,
        )

    def retry_stream_gravimetric_ending_mass(self):
        return self.start_stream_gravimetric_ending_mass()

    def cancel_stream_gravimetric_ending_mass(self):
        binding = self._experimental_balance_active_stream_request
        if binding is None or binding.get("phase") != "ending":
            return False, "There is no active ending-mass request."
        manager = self._stream_capture_manager()
        ok, message = (
            manager.mark_stream_gravimetric_ending_mass_request_cancelling(
                binding["request_id"],
                binding["session_id"],
            )
        )
        if not ok:
            return False, message
        binding["cancel_requested"] = True
        result = self._experimental_balance_service.cancel_stable_mass(
            binding["request_id"]
        )
        if not bool(getattr(result, "accepted", False)):
            detail = str(
                getattr(result, "detail", "") or "Cancellation was rejected."
            )
            self.error_occurred_signal.emit("Experimental Balance", detail)
            return False, detail
        return True, ""

    def confirm_stream_gravimetric_ending_mass(
        self,
        rep_override=None,
        notes="",
    ):
        if self._experimental_balance_active_stream_request is not None:
            return False, "The stable-mass request has not finished."
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue before confirming the ending mass."
        return self._stream_capture_manager().confirm_stream_gravimetric_ending_mass(
            rep_override=rep_override,
            notes=notes,
        )

    def use_manual_stream_gravimetric_ending_mass(
        self,
        reason="operator_manual_fallback",
    ):
        result = (
            self._stream_capture_manager().return_stream_gravimetric_ending_mass_to_manual(
                reason=reason,
            )
        )
        if isinstance(result, tuple) and result and result[0] is False:
            return result
        self._retire_stream_gravimetric_balance_request(phase="ending")
        return True, ""

    def use_manual_stream_gravimetric_starting_mass(
        self, reason="operator_manual_fallback"
    ):
        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate("Operator selected manual starting-mass fallback.")
        result = manager.return_stream_gravimetric_start_to_manual(
            reason=reason,
            preserve_inputs=True,
        )
        if isinstance(result, tuple) and result and result[0] is False:
            return result
        self._retire_stream_gravimetric_starting_mass_request()
        self.set_experimental_balance_stream_opt_in(False)
        return True, ""

    def abandon_stream_gravimetric_starting_mass(
        self, reason="operator_abandoned"
    ):
        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate("A staged starting-mass workflow was abandoned.")
        result = manager.return_stream_gravimetric_start_to_manual(
            reason=reason,
            preserve_inputs=False,
        )
        if isinstance(result, tuple) and result and result[0] is False:
            return result
        self._retire_stream_gravimetric_starting_mass_request()
        return True, ""

    def _on_experimental_balance_connection_changed(self, snapshot):
        self._experimental_balance_connection_snapshot = snapshot
        self.experimental_balance_connection_changed.emit(snapshot)

    def _on_experimental_balance_reading_received(self, reading):
        self._experimental_balance_last_reading = reading
        self.experimental_balance_reading_received.emit(reading)

    def _on_experimental_balance_request_progress(self, progress):
        binding = self._experimental_balance_active_stream_request
        request = getattr(progress, "request", None)
        if binding is None or request is None:
            return
        if (
            str(getattr(request, "request_id", "")) != binding["request_id"]
            or str(getattr(request, "stream_session_id", "")) != binding["session_id"]
            or self._balance_value(getattr(request, "phase", "")) != binding["phase"]
            or bool(binding.get("cancel_requested"))
        ):
            return
        payload = self._balance_progress_payload(progress)
        manager = self._stream_capture_manager()
        if binding["phase"] == "starting":
            handled = manager.update_stream_gravimetric_balance_progress(
                binding["request_id"],
                binding["session_id"],
                payload,
            )
        else:
            handled = manager.update_stream_gravimetric_ending_mass_progress(
                binding["request_id"],
                binding["session_id"],
                payload,
            )
        if handled:
            self.experimental_balance_request_progress.emit(progress)

    def _on_experimental_balance_request_finished(self, result):
        binding = self._experimental_balance_active_stream_request
        if binding is None:
            return
        if (
            str(getattr(result, "request_id", "")) != binding["request_id"]
            or str(getattr(result, "stream_session_id", "")) != binding["session_id"]
            or self._balance_value(getattr(result, "phase", "")) != binding["phase"]
        ):
            return
        self._experimental_balance_active_stream_request = None
        payload = self._balance_result_payload(result, binding)
        outcome = payload["outcome"]
        manager = self._stream_capture_manager()
        is_starting = binding["phase"] == "starting"
        cancelled = bool(binding.get("cancel_requested"))
        if outcome == "stable" and not cancelled:
            if is_starting:
                handled = manager.record_stream_gravimetric_starting_mass_candidate(
                    binding["request_id"],
                    binding["session_id"],
                    payload,
                )
            else:
                handled = manager.record_stream_gravimetric_ending_mass_candidate(
                    binding["request_id"],
                    binding["session_id"],
                    payload,
                )
        else:
            status = {
                "timeout": "timeout",
                "cancelled": "cancelled",
            }.get(outcome, "error")
            if cancelled:
                status = "cancelled"
            detail = payload.get("detail") or (
                "Stable-mass reading was cancelled."
                if status == "cancelled"
                else (
                    "Stable starting-mass request failed."
                    if is_starting
                    else "Stable ending-mass request failed."
                )
            )
            if is_starting:
                handled = manager.mark_stream_gravimetric_balance_request_failure(
                    binding["request_id"],
                    binding["session_id"],
                    request_status=status,
                    message=detail,
                    capture=payload,
                )
            else:
                handled = (
                    manager.mark_stream_gravimetric_ending_mass_request_failure(
                        binding["request_id"],
                        binding["session_id"],
                        request_status=status,
                        message=detail,
                        capture=payload,
                    )
                )
        if handled:
            self.experimental_balance_request_finished.emit(result)

    def _on_experimental_balance_error_occurred(self, error):
        self.experimental_balance_error_occurred.emit(error)
        detail = str(getattr(error, "detail", "") or "Balance service error")
        self.error_occurred_signal.emit("Experimental Balance Error", detail)

    def _classify_port(self, port: str) -> str | None:
        """Return ``mcu``, ``balance``, or ``None`` from cached USB metadata."""
        info = self._port_info.get(port)
        if info is None:
            for candidate in comports():
                if getattr(candidate, "device", None) == port:
                    info = candidate
                    break
        if info is None:
            return None
        if self._is_mcu_port_info(info):
            return "mcu"
        if self._is_balance_port_info(info):
            return "balance"
        return None

    @QtCore.Slot(str)
    def connect_machine(self, port: str):
        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        if runtime_context.is_simulation:
            if port != SIMULATED_PORT:
                self._reject_physical_action(
                    f"machine connection to {port!r}; only {SIMULATED_PORT!r} is allowed"
                )
                return False
            return self.machine.connect_board(SIMULATED_PORT)
        if self._reject_physical_action("machine connection") is not None:
            return
        kind = self._classify_port(port)
        if kind == "balance":
            self.error_occurred_signal.emit(
                "Connection Error", f"Port {port} looks like the BALANCE/scale, not the MCU. Please choose the MCU port."
            )
            return
        self.machine.connect_board(port)

    def disconnect_machine(self):
        """Disconnect from the machine."""
        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        if runtime_context.is_simulation:
            self._emit_machine_workflow_interrupted("disconnect_requested")
            return self.machine.disconnect_board()
        if self._reject_physical_action("machine disconnection") is not None:
            return
        self._emit_machine_workflow_interrupted("disconnect_requested")
        return self.machine.disconnect_board()
    # @QtCore.Slot()
    # def disconnect_machine(self):
    #     # self.machine.reset_board()
    #     # try:
    #     #     if getattr(self.machine, "ser", None):
    #     #         self.machine.ser.close()
    #     # except Exception:
    #     #     pass
    #     self.model.machine_model.disconnect_machine()

    @QtCore.Slot(str)
    def connect_balance(self, port: str):
        if self._reject_physical_action("balance connection") is not None:
            return
        if self.balance is None:
            self.error_occurred_signal.emit("Connection Error","Balance support is not enabled in this build/profile.")
            return

        kind = self._classify_port(port)
        if kind == "mcu":
            self.error_occurred_signal.emit(
               "Connection Error", f"Port {port} looks like the MCU, not the balance. Please choose the balance port."
            )
            return

        self.balance.connect_balance(port)

    @QtCore.Slot()
    def disconnect_balance(self):
        if self._reject_physical_action("balance disconnection") is not None:
            return
        if self.balance:
            self.balance.close_connection()
        self.model.machine_model.disconnect_balance()


    def update_machine_connection_status(self, status):
        """Update the machine connection status."""
        manager = self._stream_capture_manager()
        if manager is not None:
            if status:
                begin_epoch = getattr(manager, "begin_stream_gravimetric_transport_epoch", None)
                if callable(begin_epoch):
                    begin_epoch("Machine connection established; prior mass baseline is not reusable.")
            else:
                invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
                if callable(invalidate):
                    invalidate(
                        "Machine disconnected; prior mass baseline is not reusable.",
                        transport_uncertain=True,
                    )
        if status:
            print("Controller: Machine connected successfully.")
            self.model.machine_model.connect_machine()
            self._restore_print_settings_after_board_reset()
        else:
            print("Controller: Failed to connect to the machine.")
            self._emit_machine_workflow_interrupted("machine_disconnected")
            self._interrupt_array_after_machine_disconnect()
            self.model.machine_model.disconnect_machine()

    def handle_reset_report(self, report: dict):
        report = dict(report or {})
        self._emit_machine_workflow_interrupted("board_reset_detected")
        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate(
                "MCU reset invalidated the reusable mass baseline.",
                transport_uncertain=True,
            )
        machine_model = self.model.machine_model
        self._pending_reset_print_settings_restore = self._snapshot_print_settings_for_reset_restore(machine_model)
        self._interrupt_array_after_board_reset(report)
        machine_model.recover_after_board_reset()
        self.expected_position = machine_model.get_current_position_dict()
        self.expected_location = None

        host_context = report.get("host_context")
        if not isinstance(host_context, dict):
            host_context = {}
        benign_startup = (
            host_context.get("connection_phase") == "initial"
            and host_context.get("classification") == "benign_startup_recovery"
        )
        if benign_startup:
            self._last_reset_debug_bundle_context = None
            return

        update_report = getattr(machine_model, "update_last_reset_report", None)
        if callable(update_report):
            update_report(report)
        summary = report.get("summary", "Board reset detected.")
        guidance = (
            "Homing state was cleared. Home the motors before resuming motion. "
            "Before the next print array starts or resumes, confirm the evaporation "
            "plate is in the dock position."
        )
        try:
            log_path = self._append_reset_report_log(report)
            log_error = None
            log_status = f"Saved to: {log_path}"
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            log_path = None
            log_error = detail
            log_status = f"Log save failed: {detail}"
        self._last_reset_debug_bundle_context = self._build_reset_debug_bundle_context(
            report,
            reset_report_log_path=log_path,
            reset_report_log_error=log_error,
        )
        message = f"{summary}\n\n{guidance}\n\n{log_status}"
        self.error_occurred_signal.emit("Board Reset Detected", message)

    def _get_machine_debug_bundle_context(self):
        machine_context = {}
        machine = getattr(self, "machine", None)
        getter = getattr(machine, "get_debug_bundle_context", None)
        if not callable(getter):
            getter = getattr(machine, "get_reset_debug_bundle_context", None)
        if callable(getter):
            try:
                machine_context = dict(getter() or {})
            except Exception as exc:
                machine_context = {"context_error": str(exc) or exc.__class__.__name__}
        return machine_context

    def _build_reset_debug_bundle_context(self, report, *, reset_report_log_path=None, reset_report_log_error=None):
        machine_context = self._get_machine_debug_bundle_context()
        return {
            "bundle_kind": "reset_report",
            "repo_root": str(getattr(self, "_repo_root", Path(__file__).resolve().parents[1])),
            "reset_report": dict(report or {}),
            "reset_report_log_path": str(reset_report_log_path) if reset_report_log_path else None,
            "reset_report_log_error": reset_report_log_error,
            "machine": machine_context,
            "port": machine_context.get("port"),
            "profile": machine_context.get("profile"),
            "black_box_session_id": machine_context.get("black_box_session_id"),
            "black_box_snapshots": list(machine_context.get("black_box_snapshots") or []),
        }

    def _build_connection_loss_debug_bundle_context(self, report):
        report = dict(report or {})
        machine_context = self._get_machine_debug_bundle_context()
        snapshots = [dict(item or {}) for item in list(machine_context.get("black_box_snapshots") or [])]
        black_box_path = report.get("black_box_log_path")
        black_box_error = report.get("black_box_log_error")
        if black_box_path or black_box_error:
            existing_paths = {str(item.get("path") or "") for item in snapshots}
            if str(black_box_path or "") not in existing_paths:
                snapshots.append(
                    {
                        "path": black_box_path,
                        "reason": report.get("black_box_reason") or "serial_reader_stopped",
                        "session_id": machine_context.get("black_box_session_id"),
                        "error": black_box_error,
                    }
                )
        return {
            "bundle_kind": "connection_loss",
            "repo_root": str(getattr(self, "_repo_root", Path(__file__).resolve().parents[1])),
            "connection_loss_report": report,
            "machine": machine_context,
            "port": report.get("port") or machine_context.get("port"),
            "profile": machine_context.get("profile"),
            "black_box_session_id": machine_context.get("black_box_session_id"),
            "black_box_snapshots": snapshots,
        }

    def _resolve_downloads_dir(self):
        downloads = ""
        try:
            downloads = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.DownloadLocation)
        except Exception:
            downloads = ""
        if not downloads:
            downloads = str(Path.home() / "Downloads")
        return Path(downloads).expanduser()

    def export_last_reset_debug_bundle(self, output_dir=None):
        context = getattr(self, "_last_reset_debug_bundle_context", None)
        if not context:
            raise RuntimeError("No board reset debug context is available to export.")
        destination = Path(output_dir).expanduser() if output_dir is not None else self._resolve_downloads_dir()
        return export_reset_debug_bundle(context, output_dir=destination)

    def export_last_connection_loss_debug_bundle(self, output_dir=None):
        context = getattr(self, "_last_connection_loss_debug_bundle_context", None)
        if not context:
            raise RuntimeError("No machine connection-loss debug context is available to export.")
        destination = Path(output_dir).expanduser() if output_dir is not None else self._resolve_downloads_dir()
        return export_reset_debug_bundle(context, output_dir=destination)

    def export_last_transport_fault_debug_bundle(self, output_dir=None):
        context = getattr(self, "_last_transport_fault_debug_bundle_context", None)
        if not context:
            raise RuntimeError("No command transport-fault debug context is available to export.")
        destination = Path(output_dir).expanduser() if output_dir is not None else self._resolve_downloads_dir()
        return export_reset_debug_bundle(context, output_dir=destination)

    def handle_serial_connection_lost(self, report: dict):
        self._emit_machine_workflow_interrupted("serial_connection_lost")
        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate(
                "Serial connection loss invalidated the reusable mass baseline.",
                transport_uncertain=True,
            )
        report = dict(report or {})
        machine_model = self.model.machine_model
        self.expected_position = machine_model.get_current_position_dict()
        self.expected_location = None
        summary = report.get("summary") or "Machine serial connection ended unexpectedly."
        guidance = (
            "Machine state is no longer trusted. Reconnect to the MCU and home the motors "
            "before resuming motion or printing."
        )
        log_path = report.get("black_box_log_path")
        log_error = report.get("black_box_log_error")
        if log_path:
            log_status = f"Black-box log: {log_path}"
        elif log_error:
            log_status = f"Black-box log save failed: {log_error}"
        else:
            log_status = "Black-box log: not available"
        self._last_connection_loss_debug_bundle_context = self._build_connection_loss_debug_bundle_context(report)
        self.error_occurred_signal.emit(
            "Machine Connection Lost",
            f"{summary}\n\n{guidance}\n\n{log_status}",
        )

    def handle_transport_fault(self, report: dict):
        report = dict(report or {})
        self._emit_machine_workflow_interrupted("transport_fault")
        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate(
                "Command transport fault invalidated the reusable mass baseline.",
                transport_uncertain=True,
            )
        machine_model = self.model.machine_model
        self.expected_position = machine_model.get_current_position_dict()
        self.expected_location = None
        self._interrupt_array_after_transport_fault(report)

        context = self._build_connection_loss_debug_bundle_context(report)
        context["transport_fault_report"] = dict(report)
        self._last_transport_fault_debug_bundle_context = context
        self._emit_optional("transport_fault_ui_signal", dict(report))

        summary = report.get("summary") or "Command transport was paused after a synchronization fault."
        technical_message = str(report.get("message") or "").strip()
        guidance = (
            "No additional queued commands will be sent. A command already accepted by the MCU may still finish. "
            "Keep clear of the machine and wait for motion to stop. Then use Disconnect, reconnect to the MCU, "
            "inspect the printer and loaded materials, and home the motors before resuming motion or printing."
        )
        log_path = report.get("black_box_log_path")
        log_error = report.get("black_box_log_error")
        if log_path:
            log_status = f"Black-box log: {log_path}"
        elif log_error:
            log_status = f"Black-box log save failed: {log_error}"
        else:
            log_status = "Black-box log: not available"

        sections = [summary]
        if technical_message and technical_message != summary:
            sections.append(f"Technical detail: {technical_message}")
        sections.extend([guidance, log_status])
        self.error_occurred_signal.emit("Command Transport Paused", "\n\n".join(sections))

    def handle_xy_motion_fault(self, report: dict):
        report = dict(report or {})
        if getattr(self, "_seq_state", "idle") == "running":
            self._abort_sequence("Gantry motion stopped before the sequence completed.")

        manager = self._stream_capture_manager()
        invalidate = getattr(manager, "invalidate_stream_gravimetric_baseline", None)
        if callable(invalidate):
            invalidate(
                "Gantry motion failure invalidated the reusable mass baseline.",
                transport_uncertain=True,
            )

        machine_model = self.model.machine_model
        machine_model.reset_home_status()
        machine_model.home_status_signal.emit()
        self.expected_position = machine_model.get_current_position_dict()
        self.expected_location = None
        self._interrupt_array_after_transport_fault(
            report,
            reason="gantry_motion_failure",
        )
        self._emit_machine_workflow_interrupted("gantry_motion_failure")
        self.xy_motion_recovery_requested.emit(report)

    def _append_reset_report_log(self, report: dict) -> str:
        path = Path(getattr(self, "_reset_report_log_path", Path("logs") / "board_reset_reports.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "host_time_utc": datetime.now(timezone.utc).isoformat(),
            "report": dict(report),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return str(path)

    def get_machine_port(self):
        """Get the currently connected machine port."""
        getter = getattr(self.machine, "get_machine_port", None)
        if callable(getter):
            return getter()
        return getattr(self.machine, "port", "")

    def get_xy_motion_recovery_state(self):
        getter = getattr(self.machine, "get_xy_motion_recovery_state", None)
        if callable(getter):
            return str(getter() or "idle")
        return "idle"

    # def connect_balance(self, port):
    #     """Connect to the microbalance."""
    #     if self.machine.connect_balance(port):
    #         # Update the model state
    #         self.model.machine_model.connect_balance(port)
    
    # def disconnect_balance(self):
    #     """Disconnect from the balance."""
    #     self.machine.disconnect_balance()
    #     self.model.machine_model.disconnect_balance()

    # def update_firmware(self, bin_path: str):
    #     self.machine.update_firmware(bin_path)

    def start_firmware_update(self,manual: bool=False):
        if self._reject_updater_action("firmware/DFU update") is not None:
            return
        print("[Controller] Starting firmware update..., manual mode =", manual)
        if self._dfu_thread and self._dfu_thread.isRunning():
            return  # already running

        # bin_path = self._bin_path_legacy if manual else self._bin_path_current
        bin_path = self._bin_path_current

        self._dfu_thread = DfuUpdateWorker(
            dfu_script=self._dfu_script,
            bin_path=bin_path,
            cwd=self._cwd,
            boot_chip=self._boot_chip, boot_off=self._boot_off,
            rst_chip=self._rst_chip,   rst_off=self._rst_off,
            manual=manual,
            timeout_s=20.0,
            # optionally:
            dfu_vidpid="0483:df11",
            flash_address="0x08000000"
        )
        self._dfu_thread.progress.connect(self.dfu_progress)
        self._dfu_thread.stage.connect(self.dfu_stage)
        self._dfu_thread.finished.connect(self.dfu_finished)
        self._dfu_thread.output.connect(self.dfu_output)
        self._dfu_thread.start()

    def is_app_update_process_running(self):
        process = getattr(self, "_app_update_process", None)
        if process is None:
            return False

        poll = getattr(process, "poll", None)
        if callable(poll):
            try:
                if poll() is None:
                    return True
            except Exception:
                return True

        self._app_update_process = None
        return False

    def cancel_app_update_process(self):
        process = getattr(self, "_app_update_process", None)
        if process is None:
            return

        if self.is_app_update_process_running():
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except Exception:
                    pass
            wait = getattr(process, "wait", None)
            if callable(wait):
                try:
                    wait(timeout=1.0)
                except TypeError:
                    try:
                        wait()
                    except Exception:
                        pass
                except Exception:
                    pass

        self._app_update_process = None

    def is_app_update_check_running(self):
        thread = getattr(self, "_app_update_check_thread", None)
        is_running = getattr(thread, "isRunning", None)
        return bool(thread is not None and callable(is_running) and is_running())

    def get_last_app_update_check_result(self):
        return getattr(self, "_last_app_update_check_result", None)

    def get_last_app_rollback_check_result(self):
        return getattr(self, "_last_app_rollback_check_result", None)

    def get_app_version(self):
        try:
            return read_app_version(self._repo_root)
        except Exception:
            return "unknown"

    def start_app_update_check(self, command_runner=None, offline_manifest_path=None, release_channel="stable"):
        blocked = self._reject_updater_action("application update check")
        if blocked is not None:
            return False, blocked
        if self.is_app_update_check_running():
            return False, "An update check is already running."

        thread = QtCore.QThread(self)
        worker = AppUpdateCheckWorker(
            self._repo_root,
            command_runner=command_runner,
            offline_manifest_path=offline_manifest_path,
            release_channel=release_channel,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_app_update_check_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_app_update_check_thread", None))
        thread.finished.connect(lambda: setattr(self, "_app_update_check_worker", None))

        self._app_update_check_thread = thread
        self._app_update_check_worker = worker
        self.app_update_check_started.emit()
        thread.start()
        return True, "Update check started."

    def start_offline_app_update_check(self, manifest_path, command_runner=None):
        return self.start_app_update_check(
            command_runner=command_runner,
            offline_manifest_path=manifest_path,
        )

    @QtCore.Slot(object)
    def _handle_app_update_check_finished(self, result):
        self._last_app_update_check_result = result
        self._last_app_rollback_check_result = None
        self.app_update_check_finished.emit(result)

    def start_app_rollback_check(self, command_runner=None, offline_manifest_path=None):
        blocked = self._reject_updater_action("application rollback check")
        if blocked is not None:
            return False, blocked
        if self.is_app_update_check_running():
            return False, "An update or rollback check is already running."

        thread = QtCore.QThread(self)
        worker = AppRollbackCheckWorker(
            self._repo_root,
            command_runner=command_runner,
            offline_manifest_path=offline_manifest_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_app_rollback_check_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_app_update_check_thread", None))
        thread.finished.connect(lambda: setattr(self, "_app_update_check_worker", None))

        self._app_update_check_thread = thread
        self._app_update_check_worker = worker
        self.app_update_check_started.emit()
        thread.start()
        return True, "Rollback check started."

    def start_offline_app_rollback_check(self, manifest_path, command_runner=None):
        return self.start_app_rollback_check(
            command_runner=command_runner,
            offline_manifest_path=manifest_path,
        )

    @QtCore.Slot(object)
    def _handle_app_rollback_check_finished(self, result):
        self._last_app_rollback_check_result = result
        self._last_app_update_check_result = None
        self.app_update_check_finished.emit(result)

    def _resolve_app_update_python(self):
        candidates = []
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            venv_root = Path(virtual_env)
            candidates.extend(
                (
                    venv_root / "Scripts" / "python.exe",
                    venv_root / "bin" / "python",
                )
            )
        for env_name in ("env", ".venv", "venv"):
            env_root = self._repo_root / env_name
            candidates.extend(
                (
                    env_root / "Scripts" / "python.exe",
                    env_root / "bin" / "python",
                )
            )
        candidates.append(Path(sys.executable))

        probe_lines = []
        seen = set()
        for candidate in candidates:
            try:
                candidate_path = str(candidate.absolute())
                key = os.path.normcase(os.path.normpath(candidate_path))
                if key in seen:
                    continue
                seen.add(key)
                if not candidate.is_file():
                    probe_lines.append(f"{candidate_path}: missing")
                    continue
                ok, message = self._probe_app_update_python(candidate_path)
                probe_lines.append(message)
                if ok:
                    self._last_app_update_python_probe_lines = tuple(probe_lines)
                    return candidate_path
            except OSError as exc:
                probe_lines.append(f"{candidate}: error checking candidate ({exc})")
                continue
        self._last_app_update_python_probe_lines = tuple(probe_lines)
        detail = "; ".join(probe_lines) if probe_lines else "no Python candidates were found"
        raise RuntimeError(f"No Python environment with PySide6 was found for the updater window. {detail}")

    def _probe_app_update_python(self, python_path):
        try:
            result = subprocess.run(
                [str(python_path), "-c", "import PySide6"],
                cwd=str(self._repo_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except Exception as exc:
            return False, f"{python_path}: PySide6 probe failed ({exc})"
        if result.returncode == 0:
            return True, f"{python_path}: PySide6 OK"
        output = (result.stderr or result.stdout or "").strip().splitlines()
        reason = output[-1] if output else f"return code {result.returncode}"
        return False, f"{python_path}: PySide6 unavailable ({reason})"

    def _app_update_launcher_log_path(self, operation_label):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(ch if ch.isalnum() else "_" for ch in str(operation_label or "updater")).strip("_")
        if not safe_label:
            safe_label = "updater"
        paths = getattr(self, "machine_data_paths", None)
        if paths is not None:
            return paths.update_history_root / "launcher_logs" / f"app_update_launcher_{safe_label}_{stamp}.log"
        return self._repo_root / "local" / "update_logs" / f"app_update_launcher_{safe_label}_{stamp}.log"

    @staticmethod
    def _format_app_update_command(command):
        return " ".join(str(part) for part in command)

    @staticmethod
    def _append_text(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(str(text))

    @staticmethod
    def _app_update_launch_environment(source_env=None):
        env = dict(os.environ if source_env is None else source_env)
        removed = []
        for name in APP_UPDATE_QT_ENV_VARS_TO_REMOVE:
            if name in env:
                removed.append((name, env.pop(name)))
        current_platform = str(env.get("QT_QPA_PLATFORM") or "").strip()
        wayland_display = str(env.get("WAYLAND_DISPLAY") or "").strip()
        if wayland_display and (not current_platform or current_platform.lower() == "xcb"):
            env["QT_QPA_PLATFORM"] = APP_UPDATE_QT_PLATFORM_WAYLAND
            if current_platform:
                platform_decision = (
                    f"overrode QT_QPA_PLATFORM={current_platform} with {APP_UPDATE_QT_PLATFORM_WAYLAND} "
                    f"because WAYLAND_DISPLAY={wayland_display}"
                )
            else:
                platform_decision = (
                    f"preferred QT_QPA_PLATFORM={APP_UPDATE_QT_PLATFORM_WAYLAND} "
                    f"because WAYLAND_DISPLAY={wayland_display}"
                )
        elif current_platform:
            platform_decision = f"preserved QT_QPA_PLATFORM={current_platform}"
        else:
            platform_decision = "skipped Wayland preference because WAYLAND_DISPLAY is not set"
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env, tuple(removed), platform_decision

    def _write_app_update_launcher_failure_log(self, operation_label, message, *, command=None):
        log_path = self._app_update_launcher_log_path(operation_label)
        probe_lines = tuple(getattr(self, "_last_app_update_python_probe_lines", ()) or ())
        lines = [
            f"started_at_utc: {datetime.now(timezone.utc).isoformat()}",
            f"cwd: {self._repo_root}",
        ]
        if command is not None:
            lines.append(f"command: {self._format_app_update_command(command)}")
        if probe_lines:
            lines.append("python_probe:")
            lines.extend(f"- {line}" for line in probe_lines)
        lines.append(f"launch_error: {message}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log_path

    def _build_app_updater_base_command(self, wait_pid):
        updater_path = (self._repo_root / "tools" / "update_and_restart.py").resolve()
        python_path = self._resolve_app_update_python()
        command = [
            python_path,
            "-u",
            str(updater_path),
            "--repo-root",
            str(self._repo_root),
            "--python",
            python_path,
        ]
        if wait_pid is not None:
            command.extend(["--wait-pid", str(int(wait_pid))])
        command.append("--gui")
        command.append("--no-relaunch")
        command.append("--record-result")
        context = getattr(self, "authorized_machine_context", None)
        if context is not None:
            from MachineDataUpdate import build_update_launch_binding

            binding = build_update_launch_binding(
                context,
                source_app_version=read_app_version(self._repo_root),
                source_commit=get_app_commit(self._repo_root),
            )
            binding_args = (
                ("--machine-data-root", binding.machine_data_root),
                ("--machine-uuid", binding.machine_uuid),
                ("--machine-id", binding.machine_id),
                ("--activation-id", binding.activation_id),
                ("--migration-id", binding.migration_id),
                ("--active-pointer-sha256", binding.active_pointer_sha256),
                ("--source-app-version", binding.source_app_version),
                ("--source-commit", binding.source_commit),
                ("--update-request-id", binding.request_id),
            )
            for name, value in binding_args:
                command.extend([name, str(value)])
            updater_log = binding.machine_data_root / "machines" / binding.machine_uuid / "update_history" / "updater_logs" / f"{binding.request_id}.log"
            latest_result = self.machine_data_paths.latest_update_ui_result_path
            command.extend(["--log-path", str(updater_log)])
            command.extend(["--latest-result-path", str(latest_result)])
        return command

    def build_app_update_command(self, wait_pid):
        command = self._build_app_updater_base_command(wait_pid)
        check_result = self.get_last_app_update_check_result()
        if (
            getattr(check_result, "status", "") == "update_available"
            and getattr(check_result, "update_source", "") == "offline"
            and getattr(check_result, "offline_manifest_path", None)
        ):
            command.extend(["--offline-manifest", str(getattr(check_result, "offline_manifest_path"))])
        elif (
            getattr(check_result, "status", "") == "update_available"
            and getattr(check_result, "update_source", "") != "offline"
            and getattr(check_result, "target_release_version", "")
        ):
            command.extend(["--target-release", str(getattr(check_result, "target_release_version"))])
        return command

    def build_app_rollback_command(self, wait_pid):
        command = self._build_app_updater_base_command(wait_pid)
        command.append("--rollback")
        check_result = self.get_last_app_rollback_check_result()
        if (
            getattr(check_result, "status", "") == "rollback_available"
            and getattr(check_result, "update_source", "") == "offline"
            and getattr(check_result, "offline_manifest_path", None)
        ):
            command.extend(["--offline-manifest", str(getattr(check_result, "offline_manifest_path"))])
        return command

    def _default_app_update_launcher(self, command, *, cwd, log_path):
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env, removed_qt_env, qt_platform_decision = self._app_update_launch_environment()
        header = (
            f"started_at_utc: {datetime.now(timezone.utc).isoformat()}\n"
            f"cwd: {Path(cwd)}\n"
            f"command: {self._format_app_update_command(command)}\n\n"
        )
        probe_lines = tuple(getattr(self, "_last_app_update_python_probe_lines", ()) or ())
        if probe_lines:
            header += "python_probe:\n"
            header += "".join(f"- {line}\n" for line in probe_lines)
            header += "\n"
        if removed_qt_env:
            header += "sanitized_qt_environment:\n"
            header += "".join(f"- removed {name}={value}\n" for name, value in removed_qt_env)
            header += "\n"
        header += "qt_platform:\n"
        header += f"- {qt_platform_decision}\n\n"
        log_path.write_text(header, encoding="utf-8")
        log_file = log_path.open("a", encoding="utf-8")
        popen_kwargs = {
            "cwd": str(cwd),
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
            "env": env,
        }
        if os.name == "nt":
            detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            popen_kwargs["creationflags"] = detached | new_group | breakaway
        else:
            popen_kwargs["start_new_session"] = True
        try:
            return subprocess.Popen([str(part) for part in command], **popen_kwargs)
        finally:
            log_file.close()

    def _launch_app_update_process(self, command, launcher=None, *, operation_label="updater"):
        if self.is_app_update_process_running():
            return False, "An application update or rollback is already running."

        log_path = None
        try:
            if launcher is None:
                log_path = self._app_update_launcher_log_path(operation_label)
                process = self._default_app_update_launcher(command, cwd=self._repo_root, log_path=log_path)
            else:
                process = launcher(command, cwd=self._repo_root)
        except Exception as exc:
            self._app_update_process = None
            if log_path is not None:
                self._append_text(log_path, f"\nlaunch_error: {exc}\n")
                return False, f"Could not start the application {operation_label}: {exc}. Launcher log: {log_path}"
            return False, f"Could not start the application {operation_label}: {exc}"

        grace_s = float(getattr(self, "_app_update_launch_grace_s", 0.0) or 0.0)
        if grace_s > 0:
            time.sleep(grace_s)
        poll = getattr(process, "poll", None)
        if callable(poll):
            try:
                returncode = poll()
            except Exception:
                returncode = None
            if returncode is not None:
                self._app_update_process = None
                log_suffix = f" Launcher log: {log_path}" if log_path is not None else ""
                return False, f"Application {operation_label} exited immediately with code {returncode}.{log_suffix}"

        self._app_update_process = process
        return True, f"Application {operation_label} started."

    def launch_app_updater(self, wait_pid, launcher=None):
        blocked = self._reject_updater_action("application updater launch")
        if blocked is not None:
            return False, blocked
        try:
            command = self.build_app_update_command(wait_pid)
        except Exception as exc:
            log_path = self._write_app_update_launcher_failure_log("updater", str(exc))
            return False, f"Could not start the application updater: {exc}. Launcher log: {log_path}"
        return self._launch_app_update_process(
            command,
            launcher=launcher,
            operation_label="updater",
        )

    def launch_app_rollback(self, wait_pid, launcher=None):
        blocked = self._reject_updater_action("application rollback launch")
        if blocked is not None:
            return False, blocked
        try:
            command = self.build_app_rollback_command(wait_pid)
        except Exception as exc:
            log_path = self._write_app_update_launcher_failure_log("rollback", str(exc))
            return False, f"Could not start the application rollback: {exc}. Launcher log: {log_path}"
        return self._launch_app_update_process(
            command,
            launcher=launcher,
            operation_label="rollback",
        )

    def get_app_update_blockers(self):
        blockers = []

        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        if not runtime_context.updater_access_allowed:
            blockers.append(
                runtime_context.blocked_message("application update or rollback")
            )

        if self.is_app_update_process_running():
            blockers.append("An application update or rollback is already running.")

        dfu_thread = getattr(self, "_dfu_thread", None)
        dfu_running = getattr(dfu_thread, "isRunning", None)
        if dfu_thread is not None and callable(dfu_running) and dfu_running():
            blockers.append("Firmware update is running.")

        try:
            if self.is_qualification_running():
                blockers.append("Machine qualification is running.")
        except Exception:
            pass

        try:
            if self.is_regulator_calibration_running():
                blockers.append("Regulator calibration is running.")
        except Exception:
            pass

        try:
            if self.is_regulator_calibration_batch_running():
                blockers.append("Regulator calibration batch is running.")
        except Exception:
            pass

        array_state = str(getattr(self, "_array_state", "idle") or "idle")
        if array_state != "idle":
            blockers.append(f"Print array state is {array_state}.")

        seq_state = str(getattr(self, "_seq_state", "idle") or "idle")
        if seq_state != "idle":
            blockers.append(f"Preprogrammed sequence state is {seq_state}.")

        try:
            if not self.check_if_all_completed():
                blockers.append("Command queue is not empty.")
        except Exception:
            blockers.append("Command queue state could not be checked.")

        try:
            capture_active = self._pending_capture_active()
        except Exception:
            capture_active = bool(getattr(self, "pending_capture_active", False))
        if capture_active:
            blockers.append("Image capture is active.")

        blockers.extend(self._get_app_update_calibration_blockers())
        return blockers

    def _get_app_update_calibration_blockers(self):
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        if manager is None:
            return []

        blockers = []
        if getattr(manager, "activeCalibration", None) is not None:
            blockers.append("Calibration is active.")

        queue = getattr(manager, "calibration_queue", None) or []
        try:
            if len(queue) > 0:
                blockers.append("Calibration queue is not empty.")
        except Exception:
            blockers.append("Calibration queue state could not be checked.")

        sweep_active = getattr(manager, "is_pulsewidth_sweep_active", None)
        if callable(sweep_active):
            try:
                if sweep_active():
                    blockers.append("Pulse-width sweep is active.")
            except Exception:
                blockers.append("Pulse-width sweep state could not be checked.")

        for getter_name, label in (
            ("get_stream_gravimetric_capture_state", "Stream gravimetric capture"),
            ("get_stream_calibration_sequence_state", "Stream calibration sequence"),
            ("get_droplet_calibration_sequence_state", "Droplet calibration sequence"),
        ):
            getter = getattr(manager, getter_name, None)
            if not callable(getter):
                continue
            try:
                state = getter()
            except Exception:
                blockers.append(f"{label} state could not be checked.")
                continue
            if self._app_update_calibration_state_is_busy(state):
                status = state.get("status") if isinstance(state, dict) else state
                blockers.append(f"{label} state is {status}.")

        return blockers

    @staticmethod
    def _app_update_calibration_state_is_busy(state):
        if isinstance(state, dict):
            status = state.get("status")
        else:
            status = state

        normalized = str(status or "idle").strip().lower()
        return normalized in {
            "awaiting_starting_baseline_choice",
            "pending_starting_loading_move",
            "moving_to_starting_loading",
            "awaiting_starting_balance_ready",
            "awaiting_starting_balance_mass",
            "awaiting_starting_balance_confirmation",
            "awaiting_starting_camera_return_ready",
            "pending_starting_camera_return",
            "returning_to_starting_camera",
            "awaiting_ending_balance_ready",
            "awaiting_ending_balance_mass",
            "awaiting_ending_balance_confirmation",
            "pending_gripper_refresh",
            "refreshing_gripper",
            "pending_loading_move",
            "moving_to_loading",
            "awaiting_mass_entry",
            "running",
            "pending_camera_return",
            "returning_to_camera",
        }

    def qualification_report_root(self):
        return self._repo_root / "hil_reports"

    def qualification_manifest_root(self):
        return self._repo_root / "tools" / "qualification" / "manifests"

    def qualification_campaign_root(self):
        return self._repo_root / "tools" / "qualification" / "campaigns"

    def qualification_output_root(self):
        return self._repo_root / "hil_reports" / "qualification"

    def qualification_campaign_output_root(self):
        return self._repo_root / "hil_reports" / "qualification_campaigns"

    def qualification_identity_path(self):
        machine_data_paths = getattr(self, "machine_data_paths", None)
        if machine_data_paths is not None:
            return machine_data_paths.identity_path
        return self._repo_root / "local" / "machine_identity.json"

    def qualification_default_machine_id(self):
        path = self.qualification_identity_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str(payload.get("machine_id") or "")

    def list_qualification_reports(self):
        from QualificationReports import discover_report_entries

        return discover_report_entries(self.qualification_report_root())

    def load_qualification_report(self, report_path):
        from QualificationReports import load_report

        return load_report(report_path)

    def list_qualification_suites(self):
        from QualificationSuites import discover_suite_entries

        return discover_suite_entries(self.qualification_manifest_root())

    def list_qualification_campaigns(self):
        from QualificationCampaigns import discover_campaign_entries

        return discover_campaign_entries(self.qualification_campaign_root())

    def qualification_timing_estimates(self):
        from QualificationTiming import build_timing_model

        return build_timing_model(self.qualification_report_root())

    def is_qualification_running(self):
        worker = getattr(self, "_qualification_worker", None)
        is_running = getattr(worker, "isRunning", None)
        return bool(worker is not None and callable(is_running) and is_running())

    def start_qualification_run(self, config):
        if self._reject_physical_action("machine qualification") is not None:
            return False
        if self.is_qualification_running():
            return False

        from QualificationRunWorker import QualificationRunWorker

        run_config = dict(config)
        run_config.setdefault("identity_path", self.qualification_identity_path())
        run_config["require_explicit_identity_path"] = (
            getattr(self, "machine_data_paths", None) is not None
        )
        run_config.setdefault("output_root", self.qualification_output_root())
        run_config.setdefault("suite_output_root", self.qualification_output_root())
        run_config.setdefault("campaign_output_root", self.qualification_campaign_output_root())
        run_config.setdefault("run_selftest_path", self._repo_root / "tools" / "run_selftest.py")
        self._qualification_worker = QualificationRunWorker(run_config, repo_root=self._repo_root)
        self._qualification_worker.stage.connect(lambda msg: self.qualification_stage.emit(msg))
        self._qualification_worker.output.connect(lambda msg: self.qualification_output.emit(msg))
        self._qualification_worker.prompt.connect(lambda msg: self.qualification_prompt.emit(msg))
        self._qualification_worker.selftest_event.connect(lambda event: self.qualification_selftest_event.emit(event))
        self._qualification_worker.campaign_event.connect(lambda event: self.qualification_campaign_event.emit(event))
        self._qualification_worker.run_finished.connect(self._on_qualification_finished)
        self._qualification_worker.start()
        return True

    def respond_qualification_prompt(self, accepted: bool):
        worker = getattr(self, "_qualification_worker", None)
        if worker is not None:
            worker.resolve_prompt(bool(accepted))

    @QtCore.Slot(bool, str, object)
    def _on_qualification_finished(self, ok, message, payload):
        self.qualification_finished.emit(bool(ok), str(message), payload)
        self._qualification_worker = None

    def is_plate_reader_analysis_preview_running(self):
        worker = getattr(self, "_plate_reader_analysis_preview_worker", None)
        if worker is None:
            return False
        is_running = getattr(worker, "isRunning", None)
        return bool(worker is not None and (not callable(is_running) or is_running()))

    def is_plate_reader_analysis_running(self):
        worker = getattr(self, "_plate_reader_analysis_worker", None)
        if worker is None:
            return False
        is_running = getattr(worker, "isRunning", None)
        return bool(worker is not None and (not callable(is_running) or is_running()))

    def start_plate_reader_analysis_preview(self, config, worker_factory=None):
        if self.is_plate_reader_analysis_running():
            message = "A plate-reader analysis run is already active."
            self.plate_reader_analysis_preview_finished.emit(False, message, {"errors": [message], "warnings": []})
            return False
        if self.is_plate_reader_analysis_preview_running():
            message = "A plate-reader analysis preview is already active."
            self.plate_reader_analysis_preview_finished.emit(False, message, {"errors": [message], "warnings": []})
            return False

        if callable(worker_factory):
            worker = worker_factory(config)
        else:
            from PlateReaderAnalysisRunner import PlateReaderAnalysisPreviewWorker

            worker = PlateReaderAnalysisPreviewWorker(config)

        self._plate_reader_analysis_preview_worker = worker
        worker.stage.connect(lambda msg: self.plate_reader_analysis_preview_stage.emit(msg))
        worker.run_finished.connect(self._on_plate_reader_analysis_preview_finished)
        worker.start()
        return True

    @QtCore.Slot(bool, str, object)
    def _on_plate_reader_analysis_preview_finished(self, ok, message, payload):
        self.plate_reader_analysis_preview_finished.emit(bool(ok), str(message), payload)
        self._plate_reader_analysis_preview_worker = None

    def start_plate_reader_analysis(self, config, worker_factory=None):
        if self.is_plate_reader_analysis_preview_running():
            self.plate_reader_analysis_output.emit("A plate-reader analysis preview is already active.")
            return False
        if self.is_plate_reader_analysis_running():
            self.plate_reader_analysis_output.emit("A plate-reader analysis run is already active.")
            return False

        if callable(worker_factory):
            worker = worker_factory(config)
        else:
            from PlateReaderAnalysisRunner import PlateReaderAnalysisWorker

            worker = PlateReaderAnalysisWorker(config, repo_root=self._repo_root)

        self._plate_reader_analysis_worker = worker
        worker.stage.connect(lambda msg: self.plate_reader_analysis_stage.emit(msg))
        worker.output.connect(lambda msg: self.plate_reader_analysis_output.emit(msg))
        worker.run_finished.connect(self._on_plate_reader_analysis_finished)
        worker.start()
        return True

    def cancel_plate_reader_analysis(self):
        worker = getattr(self, "_plate_reader_analysis_worker", None)
        if worker is None:
            return False
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
            return True
        return False

    @QtCore.Slot(bool, str, object)
    def _on_plate_reader_analysis_finished(self, ok, message, payload):
        self.plate_reader_analysis_finished.emit(bool(ok), str(message), payload)
        self._plate_reader_analysis_worker = None

    def regulator_calibration_output_root(self):
        machine_data_paths = getattr(self, "machine_data_paths", None)
        if machine_data_paths is not None:
            return machine_data_paths.regulator_optimization_root
        return self._repo_root / "local" / "regulator_optimization"

    def is_regulator_calibration_running(self):
        worker = getattr(self, "_regulator_calibration_worker", None)
        is_running = getattr(worker, "isRunning", None)
        worker_running = bool(worker is not None and callable(is_running) and is_running())
        return worker_running or getattr(self, "_regulator_calibration_state", None) is not None

    def is_regulator_calibration_batch_running(self):
        return getattr(self, "_regulator_calibration_batch_state", None) is not None

    def _emit_regulator_calibration_signal(self, signal_name, *args):
        signal = getattr(self, signal_name, None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            emit(*args)

    def _regulator_profile_document(self):
        store = getattr(getattr(self, "model", None), "regulator_profile_store", None)
        if store is not None:
            document = getattr(store, "document", None)
            if document is None:
                return store.load()
            return document
        return getattr(getattr(self, "model", None), "regulator_profiles", None)

    def list_regulator_calibration_profiles(self):
        try:
            store = getattr(getattr(self, "model", None), "regulator_profile_store", None)
            if store is not None and hasattr(store, "list_profiles"):
                return store.list_profiles()
            document = self._regulator_profile_document()
            profiles = (document or {}).get("profiles", {})
            return [profiles[key] for key in sorted(profiles)]
        except Exception as exc:
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                f"Could not load regulator profiles: {exc}",
            )
            return []

    def get_regulator_calibration_active_profile_id(self, mode):
        try:
            document = self._regulator_profile_document()
            return (document or {}).get("active_profiles", {}).get(str(mode or "").strip().lower())
        except Exception as exc:
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                f"Could not load active regulator profile: {exc}",
            )
            return None

    def start_regulator_calibration_run(self, config, trace_worker_factory=None):
        if self._reject_physical_action("regulator calibration") is not None:
            return False
        run_config = dict(config or {})
        if self.is_regulator_calibration_batch_running() and not bool(run_config.get("_batch_run")):
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                "A regulator calibration batch is already active.",
            )
            return False
        if self.is_regulator_calibration_running():
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                "A regulator calibration run is already active.",
            )
            return False

        from RegulatorCalibrationRunner import (
            RegulatorCalibrationError,
            prepare_regulator_calibration_run,
            write_run_metadata,
        )

        dry_run = bool(run_config.get("dry_run", False))
        profile_document = run_config.get("_profile_document_override") or self._regulator_profile_document()
        try:
            prepared = prepare_regulator_calibration_run(
                run_config,
                profile_document=profile_document,
                output_root=run_config.get("output_root") or self.regulator_calibration_output_root(),
            )
        except RegulatorCalibrationError as exc:
            self._emit_regulator_calibration_signal("regulator_calibration_output", str(exc))
            return False

        if dry_run:
            try:
                metadata = write_run_metadata(
                    prepared,
                    status="completed",
                    restored_previous_profile=True,
                    error_message="",
                    trace_files=[],
                )
            except Exception as exc:
                self._emit_regulator_calibration_signal(
                    "regulator_calibration_output",
                    f"Could not write regulator calibration dry-run metadata: {exc}",
                )
                return False
            payload = self._regulator_calibration_payload(prepared, metadata=metadata)
            self._emit_regulator_calibration_signal("regulator_calibration_stage", "Dry run complete")
            self._emit_regulator_calibration_signal(
                "regulator_calibration_finished",
                True,
                f"Regulator calibration dry run wrote {prepared.run_dir}",
                payload,
            )
            return True

        if not self._regulator_calibration_machine_connected():
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                "Machine must be connected before starting regulator calibration.",
            )
            return False

        try:
            if not self.check_if_all_completed():
                self._emit_regulator_calibration_signal(
                    "regulator_calibration_output",
                    "Command queue must be idle before starting regulator calibration.",
                )
                return False
        except Exception:
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                "Command queue state could not be checked.",
            )
            return False

        port = str(run_config.get("port") or self.get_machine_port() or "").strip()
        if not port:
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                "Machine serial port is not available for pressure trace capture.",
            )
            return False
        baud = int(run_config.get("baud") or getattr(self.machine, "baud", 115200) or 115200)

        self._regulator_calibration_state = {
            "prepared": prepared,
            "config": run_config,
            "port": port,
            "baud": baud,
            "serial_handoff_mode": prepared.serial_handoff_mode,
            "trace_worker_factory": trace_worker_factory,
            "candidate_commands_queued": False,
            "candidate_applied": False,
            "cancel_requested": False,
            "trace_ok": False,
            "trace_message": "",
            "trace_payload": {},
            "restore_in_progress": False,
        }
        try:
            write_run_metadata(
                prepared,
                status="failed",
                restored_previous_profile=False,
                error_message="Run started but did not complete.",
                trace_files=[],
            )
        except Exception as exc:
            self._regulator_calibration_state = None
            self._emit_regulator_calibration_signal(
                "regulator_calibration_output",
                f"Could not initialize regulator calibration metadata: {exc}",
            )
            return False

        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Applying candidate profile")
        try:
            self._queue_regulator_calibration_candidate()
        except Exception as exc:
            self._handle_regulator_calibration_failure(
                f"Could not queue regulator candidate profile: {exc}",
                restore_if_needed=bool(self._regulator_calibration_state.get("candidate_commands_queued")),
            )
            return True
        return True

    def cancel_regulator_calibration_run(self):
        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return False
        state["cancel_requested"] = True
        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Cancel requested")
        worker = getattr(self, "_regulator_calibration_worker", None)
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
        if not state.get("candidate_commands_queued"):
            self._finish_regulator_calibration(
                ok=False,
                status="canceled",
                message="Regulator calibration canceled before candidate application.",
                restored_previous_profile=False,
                error_message="Canceled before candidate application.",
            )
        elif state.get("candidate_applied") and worker is None and not state.get("restore_in_progress"):
            self._restore_regulator_calibration(
                final_status="canceled",
                final_ok=False,
                final_message="Regulator calibration canceled.",
                error_message="Canceled.",
            )
        return True

    def _regulator_calibration_machine_connected(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        is_connected = getattr(machine_model, "is_connected", None)
        if callable(is_connected):
            return bool(is_connected())
        return bool(getattr(machine_model, "machine_connected", False))

    def _queue_regulator_calibration_candidate(self):
        state = self._regulator_calibration_state
        prepared = state["prepared"]
        channels = list(prepared.trace_case.channels)
        for channel_index, channel in enumerate(channels):
            channel_profile = prepared.candidate_profile[channel]
            last_channel = channel_index == len(channels) - 1
            recovery = self.set_regulator_recovery_profile(
                channel,
                channel_profile["recovery"],
                manual=True,
            )
            self._assert_regulator_command_queued(recovery, "recovery", channel)
            state["candidate_commands_queued"] = True

            slew = self.set_regulator_slew_profile(
                channel,
                channel_profile["slew"],
                manual=True,
            )
            self._assert_regulator_command_queued(slew, "slew", channel)

            ready = self.set_regulator_ready_profile(
                channel,
                channel_profile["ready"],
                handler=self._on_regulator_calibration_candidate_applied if last_channel else None,
                manual=True,
            )
            self._assert_regulator_command_queued(ready, "ready", channel)

    @staticmethod
    def _assert_regulator_command_queued(command_or_commands, section, channel):
        if command_or_commands is False or command_or_commands is None:
            raise RuntimeError(f"{section} profile command for {channel} was rejected")
        if isinstance(command_or_commands, (list, tuple)) and not command_or_commands:
            raise RuntimeError(f"{section} profile command for {channel} did not queue commands")

    def _on_regulator_calibration_candidate_applied(self):
        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return
        state["candidate_applied"] = True
        if state.get("cancel_requested"):
            self._restore_regulator_calibration(
                final_status="canceled",
                final_ok=False,
                final_message="Regulator calibration canceled after candidate application.",
                error_message="Canceled after candidate application.",
            )
            return
        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Releasing app serial port")
        self._disconnect_for_regulator_calibration_trace()

    def _connect_once(self, signal, callback):
        if signal is None or not hasattr(signal, "connect"):
            return False

        def _wrapper(*args):
            try:
                signal.disconnect(_wrapper)
            except Exception:
                pass
            callback(*args)

        signal.connect(_wrapper)
        return True

    def _disconnect_for_regulator_calibration_trace(self):
        state = getattr(self, "_regulator_calibration_state", None)
        handoff_mode = str((state or {}).get("serial_handoff_mode") or "soft")
        if handoff_mode == "soft":
            self._soft_release_for_regulator_calibration_trace()
            return

        signal = getattr(self.machine, "disconnect_complete_signal", None)
        connected = self._connect_once(
            signal,
            lambda *_args: self._start_regulator_calibration_trace_worker(),
        )
        try:
            self.disconnect_machine()
        except Exception as exc:
            self._handle_regulator_calibration_failure(
                f"Could not release app serial port for pressure trace: {exc}",
                restore_if_needed=True,
            )
            return
        if not connected:
            self._start_regulator_calibration_trace_worker()

    def _soft_release_for_regulator_calibration_trace(self):
        release = getattr(self.machine, "release_serial_for_external_owner", None)
        if not callable(release):
            self._handle_regulator_calibration_failure(
                "Machine transport does not support soft serial release for regulator calibration.",
                restore_if_needed=True,
            )
            return
        try:
            released = bool(release(reason="regulator_calibration"))
        except Exception as exc:
            self._handle_regulator_calibration_failure(
                f"Could not release app serial port for pressure trace: {exc}",
                restore_if_needed=True,
            )
            return
        if not released:
            self._handle_regulator_calibration_failure(
                "Could not release app serial port for pressure trace.",
                restore_if_needed=True,
            )
            return
        self._start_regulator_calibration_trace_worker()

    def _start_regulator_calibration_trace_worker(self):
        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return
        if state.get("cancel_requested"):
            self._restore_regulator_calibration(
                final_status="canceled",
                final_ok=False,
                final_message="Regulator calibration canceled before trace capture.",
                error_message="Canceled before trace capture.",
            )
            return

        from RegulatorCalibrationRunner import RegulatorTraceProcessWorker

        prepared = state["prepared"]
        factory = state.get("trace_worker_factory")
        skip_goodbye = str(state.get("serial_handoff_mode") or "soft") == "soft"
        if callable(factory):
            worker = factory(
                prepared,
                state["port"],
                state["baud"],
                self._repo_root,
                self._repo_root / "tools" / "run_selftest.py",
                skip_goodbye=skip_goodbye,
            )
        else:
            worker = RegulatorTraceProcessWorker(
                prepared,
                port=state["port"],
                baud=state["baud"],
                repo_root=self._repo_root,
                run_selftest_path=self._repo_root / "tools" / "run_selftest.py",
                timeout_ms=state["config"].get("timeout_ms"),
                skip_goodbye=skip_goodbye,
            )
        self._regulator_calibration_worker = worker
        self._connect_signal_if_present(worker, "stage", lambda msg: self._emit_regulator_calibration_signal("regulator_calibration_stage", msg))
        self._connect_signal_if_present(worker, "output", lambda msg: self._emit_regulator_calibration_signal("regulator_calibration_output", msg))
        self._connect_signal_if_present(worker, "run_finished", self._on_regulator_calibration_trace_finished)
        worker.start()

    @staticmethod
    def _connect_signal_if_present(obj, signal_name, callback):
        signal = getattr(obj, signal_name, None)
        connect = getattr(signal, "connect", None)
        if callable(connect):
            connect(callback)

    @QtCore.Slot(bool, str, object)
    def _on_regulator_calibration_trace_finished(self, ok, message, payload):
        state = getattr(self, "_regulator_calibration_state", None)
        self._regulator_calibration_worker = None
        if state is None:
            return
        state["trace_ok"] = bool(ok)
        state["trace_message"] = str(message or "")
        state["trace_payload"] = dict(payload or {})
        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Reconnecting app serial port")
        self._reconnect_after_regulator_calibration_trace()

    def _reconnect_after_regulator_calibration_trace(self):
        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return
        signal = getattr(self.machine, "machine_connected_signal", None)

        def _on_connected(connected):
            if connected:
                self._restore_regulator_calibration(
                    final_status="completed" if state.get("trace_ok") and not state.get("cancel_requested") else (
                        "canceled" if state.get("cancel_requested") else "failed"
                    ),
                    final_ok=bool(state.get("trace_ok") and not state.get("cancel_requested")),
                    final_message=state.get("trace_message") or "Pressure trace finished.",
                    error_message="" if state.get("trace_ok") and not state.get("cancel_requested") else state.get("trace_message", ""),
                )
            else:
                self._finish_regulator_calibration(
                    ok=False,
                    status="restore_failed",
                    message="Could not reconnect to restore regulator profile.",
                    restored_previous_profile=False,
                    error_message="Reconnect failed before restore.",
                )

        connected = self._connect_once(signal, _on_connected)
        try:
            self.connect_machine(state["port"])
        except Exception as exc:
            self._finish_regulator_calibration(
                ok=False,
                status="restore_failed",
                message=f"Could not reconnect to restore regulator profile: {exc}",
                restored_previous_profile=False,
                error_message=str(exc),
            )
            return
        if not connected:
            _on_connected(True)

    def _restore_regulator_calibration(self, *, final_status, final_ok, final_message, error_message):
        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return
        state["restore_in_progress"] = True
        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Restoring regulator profile")

        def _on_restore_complete():
            self._finish_regulator_calibration(
                ok=bool(final_ok),
                status=final_status,
                message=final_message,
                restored_previous_profile=True,
                error_message=error_message,
            )

        restore = self.restore_regulator_profile(
            list(state["prepared"].trace_case.channels),
            source="baseline",
            handler=_on_restore_complete,
            manual=True,
        )
        if restore is False or restore is None:
            self._finish_regulator_calibration(
                ok=False,
                status="restore_failed",
                message="Could not queue regulator profile restore.",
                restored_previous_profile=False,
                error_message="Restore command was rejected.",
            )

    def _handle_regulator_calibration_failure(self, message, *, restore_if_needed):
        state = getattr(self, "_regulator_calibration_state", None)
        self._emit_regulator_calibration_signal("regulator_calibration_output", str(message))
        if state is not None and restore_if_needed:
            self._restore_regulator_calibration(
                final_status="failed",
                final_ok=False,
                final_message=str(message),
                error_message=str(message),
            )
            return
        self._finish_regulator_calibration(
            ok=False,
            status="failed",
            message=str(message),
            restored_previous_profile=False,
            error_message=str(message),
        )

    def _finish_regulator_calibration(
        self,
        *,
        ok,
        status,
        message,
        restored_previous_profile,
        error_message,
    ):
        from RegulatorCalibrationRunner import write_run_metadata

        state = getattr(self, "_regulator_calibration_state", None)
        if state is None:
            return
        prepared = state["prepared"]
        trace_payload = dict(state.get("trace_payload") or {})
        trace_files = trace_payload.get("trace_files")
        try:
            metadata = write_run_metadata(
                prepared,
                status=status,
                restored_previous_profile=restored_previous_profile,
                error_message=error_message,
                trace_files=trace_files,
            )
            payload = self._regulator_calibration_payload(prepared, metadata=metadata, trace_payload=trace_payload)
        except Exception as exc:
            ok = False
            message = f"{message} Metadata write failed: {exc}"
            payload = self._regulator_calibration_payload(prepared, metadata=None, trace_payload=trace_payload)
            payload["metadata_error"] = str(exc)

        self._regulator_calibration_worker = None
        self._regulator_calibration_state = None
        self._emit_regulator_calibration_signal("regulator_calibration_stage", "Finished" if ok else "Failed")
        self._emit_regulator_calibration_signal(
            "regulator_calibration_finished",
            bool(ok),
            str(message),
            payload,
        )

    @staticmethod
    def _regulator_calibration_payload(prepared, *, metadata=None, trace_payload=None):
        payload = {
            "run_id": prepared.run_id,
            "session_id": prepared.session_id,
            "run_dir": str(prepared.run_dir),
            "run_meta_path": str(prepared.run_dir / "run_meta.json"),
            "raw_selftest_path": str(prepared.raw_selftest_path),
            "trace_case_id": prepared.trace_case.test_id,
            "trace_case_name": prepared.trace_case.name,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        if trace_payload:
            payload["trace"] = dict(trace_payload)
        return payload

    def _emit_regulator_calibration_batch_signal(self, signal_name, *args):
        signal = getattr(self, signal_name, None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            emit(*args)

    def is_regulator_calibration_sweep_running(self):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        return state is not None and state.get("prepared_sweep") is not None

    def start_regulator_calibration_sweep(self, config, trace_worker_factory=None, analysis_runner=None):
        if self._reject_physical_action("regulator calibration sweep") is not None:
            return False
        if self.is_regulator_calibration_batch_running():
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "A regulator calibration batch is already active.",
            )
            return False
        if self.is_regulator_calibration_running():
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "A regulator calibration run is already active.",
            )
            return False

        from RegulatorSweepBuilder import RegulatorSweepError, prepare_regulator_sweep

        sweep_config = dict(config or {})
        profile_document = self._regulator_profile_document()
        try:
            prepared_sweep = prepare_regulator_sweep(
                sweep_config,
                profile_document=profile_document,
            )
        except RegulatorSweepError as exc:
            self._emit_regulator_calibration_batch_signal("regulator_calibration_batch_output", str(exc))
            return False

        batch_config = dict(sweep_config)
        batch_config["candidate_profile_ids"] = list(prepared_sweep.candidate_profile_ids)
        batch_config["baseline_profile_id"] = prepared_sweep.baseline_profile_id
        batch_config["_profile_document_override"] = prepared_sweep.profile_document
        batch_config["_prepared_sweep"] = prepared_sweep
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_output",
            f"Generated {len(prepared_sweep.candidate_profile_ids)} regulator sweep candidates.",
        )
        return self.start_regulator_calibration_batch(
            batch_config,
            trace_worker_factory=trace_worker_factory,
            analysis_runner=analysis_runner,
        )

    def cancel_regulator_calibration_sweep(self):
        return self.cancel_regulator_calibration_batch()

    def start_regulator_calibration_batch(self, config, trace_worker_factory=None, analysis_runner=None):
        if self._reject_physical_action("regulator calibration batch") is not None:
            return False
        if self.is_regulator_calibration_batch_running():
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "A regulator calibration batch is already active.",
            )
            return False
        if self.is_regulator_calibration_running():
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "A regulator calibration run is already active.",
            )
            return False

        from RegulatorCalibrationRunner import (
            RegulatorCalibrationBatchError,
            batch_run_configs,
            prepare_regulator_calibration_batch,
            write_batch_manifest,
        )

        batch_config = dict(config or {})
        profile_document = batch_config.get("_profile_document_override") or self._regulator_profile_document()
        try:
            prepared = prepare_regulator_calibration_batch(
                batch_config,
                profile_document=profile_document,
                output_root=batch_config.get("output_root") or self.regulator_calibration_output_root(),
            )
            prepared_sweep = batch_config.get("_prepared_sweep")
            if prepared_sweep is not None:
                from RegulatorSweepBuilder import write_sweep_artifacts

                prepared.manifest["sweep"] = write_sweep_artifacts(prepared_sweep, prepared.session_dir)
                write_batch_manifest(prepared)
            write_batch_manifest(prepared, status="running")
        except (RegulatorCalibrationBatchError, Exception) as exc:
            self._emit_regulator_calibration_batch_signal("regulator_calibration_batch_output", str(exc))
            return False

        if not self._regulator_calibration_machine_connected():
            write_batch_manifest(prepared, status="failed", error_message="Machine is not connected.")
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "Machine must be connected before starting regulator calibration batch.",
            )
            return False
        try:
            if not self.check_if_all_completed():
                write_batch_manifest(prepared, status="failed", error_message="Command queue is not idle.")
                self._emit_regulator_calibration_batch_signal(
                    "regulator_calibration_batch_output",
                    "Command queue must be idle before starting regulator calibration batch.",
                )
                return False
        except Exception:
            write_batch_manifest(prepared, status="failed", error_message="Command queue state could not be checked.")
            self._emit_regulator_calibration_batch_signal(
                "regulator_calibration_batch_output",
                "Command queue state could not be checked.",
            )
            return False

        self._regulator_calibration_batch_state = {
            "prepared": prepared,
            "run_configs": batch_run_configs(prepared),
            "index": 0,
            "cancel_requested": False,
            "trace_worker_factory": trace_worker_factory,
            "analysis_runner": analysis_runner,
            "profile_document": profile_document,
            "prepared_sweep": batch_config.get("_prepared_sweep"),
        }
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_stage",
            f"Starting regulator calibration batch {prepared.session_id}",
        )
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_output",
            f"Session folder: {prepared.session_dir}",
        )
        self._start_next_regulator_calibration_batch_run()
        return True

    def cancel_regulator_calibration_batch(self):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        if state is None:
            return False
        state["cancel_requested"] = True
        self._emit_regulator_calibration_batch_signal("regulator_calibration_batch_stage", "Cancel requested")
        if self.is_regulator_calibration_running():
            self.cancel_regulator_calibration_run()
        else:
            self._finish_regulator_calibration_batch(False, "Regulator calibration batch canceled.", "canceled", "Canceled.")
        return True

    def _start_next_regulator_calibration_batch_run(self):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        if state is None:
            return
        prepared = state["prepared"]
        run_configs = state["run_configs"]
        index = int(state.get("index", 0))
        if index >= len(run_configs):
            self._run_regulator_calibration_batch_analysis()
            return
        run = prepared.runs[index]
        run["status"] = "running"
        from RegulatorCalibrationRunner import write_batch_manifest

        write_batch_manifest(prepared, runs=prepared.runs, status="running")
        self._emit_regulator_calibration_batch_progress(
            index + 1,
            len(run_configs),
            run,
        )
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_stage",
            f"Run {index + 1}/{len(run_configs)}: {run['role']} {run['profile_id']}",
        )

        self._connect_once(self.regulator_calibration_finished, self._on_regulator_calibration_batch_run_finished)
        started = self.start_regulator_calibration_run(
            dict(run_configs[index], _profile_document_override=state.get("profile_document")),
            trace_worker_factory=state.get("trace_worker_factory"),
        )
        if not started:
            run["status"] = "failed"
            run["message"] = "Could not start scheduled regulator calibration run."
            write_batch_manifest(prepared, runs=prepared.runs, status="failed", error_message=run["message"])
            self._finish_regulator_calibration_batch(False, run["message"], "failed", run["message"])

    def _emit_regulator_calibration_batch_progress(self, current, total, run):
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_progress",
            int(current),
            int(total),
            dict(run),
        )

    @QtCore.Slot(bool, str, object)
    def _on_regulator_calibration_batch_run_finished(self, ok, message, payload):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        if state is None:
            return
        from RegulatorCalibrationRunner import write_batch_manifest

        prepared = state["prepared"]
        index = int(state.get("index", 0))
        if index >= len(prepared.runs):
            return
        run = prepared.runs[index]
        payload = dict(payload or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        outcome = metadata.get("outcome") if isinstance(metadata.get("outcome"), dict) else {}
        status = str(outcome.get("status") or ("completed" if ok else "failed"))
        run.update(
            {
                "status": status,
                "message": str(message or ""),
                "run_dir": str(payload.get("run_dir") or run.get("run_dir") or ""),
                "run_meta_path": str(payload.get("run_meta_path") or run.get("run_meta_path") or ""),
            }
        )
        write_batch_manifest(prepared, runs=prepared.runs, status="running")

        if state.get("cancel_requested"):
            self._mark_remaining_regulator_calibration_batch_runs_skipped(prepared, index + 1)
            self._finish_regulator_calibration_batch(False, "Regulator calibration batch canceled.", "canceled", "Canceled.")
            return
        if status != "completed" or not ok:
            final_status = "failed"
            error_message = str(message or f"Run {index + 1} ended with status {status}.")
            if status == "restore_failed":
                error_message = "Restore failed during regulator calibration batch. " + error_message
            self._mark_remaining_regulator_calibration_batch_runs_skipped(prepared, index + 1)
            self._finish_regulator_calibration_batch(False, error_message, final_status, error_message)
            return

        state["index"] = index + 1
        self._start_next_regulator_calibration_batch_run()

    def _mark_remaining_regulator_calibration_batch_runs_skipped(self, prepared, start_index):
        for run in prepared.runs[int(start_index):]:
            if run.get("status") == "pending":
                run["status"] = "skipped"
                run["message"] = "Skipped after batch stopped."

    def _run_regulator_calibration_batch_analysis(self):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        if state is None:
            return
        prepared = state["prepared"]
        self._emit_regulator_calibration_batch_signal("regulator_calibration_batch_stage", "Analyzing regulator batch")
        analysis_runner = state.get("analysis_runner")
        try:
            if callable(analysis_runner):
                result = analysis_runner(prepared)
            else:
                if str(self._repo_root) not in sys.path:
                    sys.path.insert(0, str(self._repo_root))
                from tools.plot_pressure_traces import render_trace_file
                from tools.regulator_trace_analysis import analyze_inputs

                result = analyze_inputs(
                    [prepared.session_dir],
                    output_dir=prepared.session_dir / "analysis",
                    make_plots=True,
                    update_run_meta=True,
                    plot_renderer=render_trace_file,
                )
            analysis = {
                "output_dir": str(result.get("output_dir", "")),
                "candidate_ranking_json": str(result.get("candidate_ranking_json", "")),
                "candidate_ranking_csv": str(result.get("candidate_ranking_csv", "")),
                "all_pulses_csv": str(result.get("all_pulses_csv", "")),
                "error_message": "",
            }
        except Exception as exc:
            self._finish_regulator_calibration_batch(
                False,
                f"Regulator calibration batch analysis failed: {exc}",
                "analysis_failed",
                str(exc),
                analysis={"error_message": str(exc)},
            )
            return
        self._finish_regulator_calibration_batch(
            True,
            "Regulator calibration batch completed.",
            "completed",
            "",
            analysis=analysis,
        )

    def _finish_regulator_calibration_batch(self, ok, message, status, error_message, analysis=None):
        state = getattr(self, "_regulator_calibration_batch_state", None)
        if state is None:
            return
        from RegulatorCalibrationRunner import write_batch_manifest

        prepared = state["prepared"]
        manifest = write_batch_manifest(
            prepared,
            runs=prepared.runs,
            analysis=analysis,
            status=status,
            error_message=error_message,
        )
        payload = {
            "session_id": prepared.session_id,
            "session_dir": str(prepared.session_dir),
            "manifest_path": str(prepared.manifest_path),
            "manifest": manifest,
        }
        self._regulator_calibration_batch_state = None
        self._emit_regulator_calibration_batch_signal("regulator_calibration_batch_stage", "Finished" if ok else "Failed")
        self._emit_regulator_calibration_batch_signal(
            "regulator_calibration_batch_finished",
            bool(ok),
            str(message or ""),
            payload,
        )

    def reset_mcu_board(self):
        """Reset the MCU board."""
        if self._reject_physical_action("MCU/GPIO reset") is not None:
            return
        self._emit_machine_workflow_interrupted(
            "mcu_reset_requested",
            notify_user=True,
        )
        self.machine.reset_mcu_board()
        self.machine.reset_board()

    # def update_balance_prediction_models(self,target_volume=40):
    #     pred_model = self.model.calibration_model.get_selected_model_path()
        # resistance_model = self.model.calibration_model.get_selected_resistance_model_path()
        # self.machine.balance.update_prediction_models(pred_model,target_volume)

    def pause_commands(self):
        """Pause the machine."""
        sent = self.machine.pause_commands()
        if sent is False:
            return False
        self.model.machine_model.pause_commands()
        context = getattr(self, "_array_context", None)
        if (
            isinstance(context, dict)
            and context.get("soft_stop_origin") == "immediate_pause"
            and context.get("soft_stop_pending")
        ):
            phase = context.get("soft_stop_phase")
            if phase == "parking":
                context["soft_stop_phase_before_pause"] = phase
                context["soft_stop_phase"] = "paused_finalization"
                context["soft_stop_recovery_reason"] = "paused_during_finalization"
                self._invalidate_paused_array_soft_stop_attempt(context)
            elif phase == "clearing":
                # The CLEAR transaction must finish authoritatively. Its
                # callback will stop before queuing park/finalization work.
                context["soft_stop_pause_during_clearing"] = True
            elif phase in {
                "arming_watermark_from_pause",
                "resuming_to_watermark",
                "waiting_watermark",
            }:
                machine_model = getattr(self.model, "machine_model", None)
                if not bool(getattr(machine_model, "pause_watermark_reached", False)):
                    context["soft_stop_phase_before_pause"] = phase
                    context["soft_stop_phase"] = "paused_safe_stop_recovery"
                    context["soft_stop_recovery_reason"] = "operator_repaused"
                    self._invalidate_paused_array_soft_stop_attempt(context)
                    self._record_print_array_audit_event(
                        "print_array_safe_stop_repaused",
                        "Print array safe stop paused again",
                        details={"previous_phase": phase},
                        level="warning",
                    )
        return True

    def resume_commands(self):
        """Resume the machine commands."""
        sent = self.machine.resume_commands()
        if sent is False:
            return False
        self.model.machine_model.resume_commands()
        return True

    def clear_command_queue(self):
        """Clear the command queue."""
        self._invalidate_paused_array_soft_stop_attempt()
        self._clear_machine_and_model_command_queues(
            reason="queue_clear_requested",
            notify_user=True,
        )
        if self.get_array_run_state() != "idle":
            context = getattr(self, "_array_context", None)
            if isinstance(context, dict):
                context["array_clear_fallback_requested"] = True
            self._complete_array_finalize("hard_abort")
        try:
            self.update_expected_with_current()
        except Exception:
            pass

    def get_array_run_state(self):
        """Return the current array runner state."""
        return str(getattr(self, "_array_state", "idle") or "idle")

    def get_loaded_array_control_state(self):
        """Return print progress for the reagent in the loaded printer head."""
        result = {
            "state": "no_head",
            "stock_id": None,
            "target_well_count": 0,
            "completed_well_count": 0,
            "target_droplets": 0,
            "remaining_droplets": 0,
            "error": None,
        }

        try:
            rack_model = getattr(self.model, "rack_model", None)
            getter = getattr(rack_model, "get_gripper_printer_head", None)
            printer_head = getter() if callable(getter) else getattr(
                rack_model, "gripper_printer_head", None
            )
            if printer_head is None:
                return result

            stock_getter = getattr(printer_head, "get_stock_id", None)
            stock_id = stock_getter() if callable(stock_getter) else None
            result["stock_id"] = None if stock_id is None else str(stock_id)
            if not stock_id:
                result["state"] = "unavailable"
                result["error"] = "The loaded printer head has no stock ID."
                return result

            well_plate = getattr(self.model, "well_plate", None)
            wells_getter = getattr(
                well_plate, "get_all_wells_with_reactions", None
            )
            if not callable(wells_getter):
                raise RuntimeError("well-plate reaction lookup is unavailable")
            wells = list(
                wells_getter(
                    fill_by="rows",
                    serpentine=bool(
                        getattr(
                            self,
                            "_array_print_serpentine",
                            ARRAY_PRINT_SERPENTINE,
                        )
                    ),
                )
                or []
            )

            for well in wells:
                target_getter = getattr(well, "get_target_droplets", None)
                remaining_getter = getattr(well, "get_remaining_droplets", None)
                if not callable(target_getter) or not callable(remaining_getter):
                    raise RuntimeError("well droplet progress is unavailable")
                target = max(0, int(target_getter(stock_id) or 0))
                if target <= 0:
                    continue
                remaining = max(0, int(remaining_getter(stock_id) or 0))
                remaining = min(target, remaining)
                result["target_well_count"] += 1
                result["target_droplets"] += target
                result["remaining_droplets"] += remaining
                if remaining == 0:
                    result["completed_well_count"] += 1

            if result["target_well_count"] == 0:
                result["state"] = "no_array"
            elif result["remaining_droplets"] == 0:
                result["state"] = "complete"
            elif result["remaining_droplets"] < result["target_droplets"]:
                result["state"] = "in_progress"
            else:
                result["state"] = "not_started"
            return result
        except Exception as exc:
            result["state"] = "unavailable"
            result["error"] = str(exc) or exc.__class__.__name__
            return result

    def start_new_experiment_session(self, *, base_dir=None):
        array_state = self.get_array_run_state()
        array_runner_idle = (
            array_state in {"idle", "resume_ready"}
            and not bool(getattr(self, "_soft_stop_clear_uncertain", False))
        )
        experiment_path = self.model.start_new_experiment_session(
            array_runner_idle=array_runner_idle,
            command_queue_empty=bool(self.check_if_all_completed()),
            base_dir=base_dir,
        )
        self._array_context = None
        self._set_array_run_state("idle")
        return experiment_path

    def _emit_optional(self, signal_name, *args):
        signal = getattr(self, signal_name, None)
        if signal is None:
            return
        try:
            signal.emit(*args)
        except Exception:
            pass

    def clear_xy_motion_recovery(self):
        """Request the operator-confirmed Clear step for an XY motion fault."""
        if self.get_xy_motion_recovery_state() != "clear_required":
            return False
        try:
            result = self._clear_machine_and_model_command_queues(
                reason="xy_motion_recovery_clear",
                notify_user=False,
            )
        except Exception:
            return False
        return result is not False

    def _emit_machine_workflow_interrupted(self, reason, *, notify_user=False):
        payload = {
            "reason": str(reason or "machine_workflow_interrupted"),
            "notify_user": bool(notify_user),
        }
        self._emit_optional("machine_workflow_interrupted_signal", payload)
        return payload

    def _clear_machine_and_model_command_queues(
        self,
        *,
        reason,
        notify_user=False,
        handler=None,
    ):
        self._emit_machine_workflow_interrupted(
            reason,
            notify_user=notify_user,
        )
        if handler is None:
            result = self.machine.clear_command_queue()
        else:
            result = self.machine.clear_command_queue(handler=handler)
        self.model.machine_model.clear_command_queue()
        return result

    def _set_array_run_state(self, state):
        state = str(state or "idle")
        if getattr(self, "_array_state", None) == state:
            self._array_state = state
            return
        self._array_state = state
        self._emit_optional("array_state_changed", state)

    def _safe_audit_value(self, obj, name, default=None):
        if obj is None:
            return default
        try:
            value = getattr(obj, name, default)
            if callable(value):
                return value()
            return value
        except Exception:
            return default

    @staticmethod
    def _finite_float_or_none(value, *, minimum=None):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        if minimum is not None and result < minimum:
            return None
        return result

    @staticmethod
    def _valid_pulse_width_or_none(value):
        try:
            result = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        if 100 <= result <= 10000:
            return result
        return None

    def _snapshot_print_settings_for_reset_restore(self, machine_model=None):
        if machine_model is None:
            machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        if machine_model is None:
            return None

        snapshot = {}
        target_print = self._finite_float_or_none(
            self._safe_audit_value(machine_model, "get_target_print_pressure"),
            minimum=0.0,
        )
        target_refuel = self._finite_float_or_none(
            self._safe_audit_value(machine_model, "get_target_refuel_pressure"),
            minimum=0.0,
        )
        print_width = self._valid_pulse_width_or_none(
            self._safe_audit_value(machine_model, "get_print_pulse_width")
        )
        refuel_width = self._valid_pulse_width_or_none(
            self._safe_audit_value(machine_model, "get_refuel_pulse_width")
        )

        if target_print is not None:
            snapshot["target_print_pressure_psi"] = target_print
        if target_refuel is not None:
            snapshot["target_refuel_pressure_psi"] = target_refuel
        if print_width is not None:
            snapshot["print_pulse_width_us"] = print_width
        if refuel_width is not None:
            snapshot["refuel_pulse_width_us"] = refuel_width
        return snapshot or None

    def _restore_print_settings_after_board_reset(self):
        settings = getattr(self, "_pending_reset_print_settings_restore", None)
        if not isinstance(settings, dict) or not settings:
            return False

        self._pending_reset_print_settings_restore = None
        commands = [
            ("print_pulse_width_us", self.set_print_pulse_width),
            ("refuel_pulse_width_us", self.set_refuel_pulse_width),
            ("target_print_pressure_psi", self.set_absolute_print_pressure),
            ("target_refuel_pressure_psi", self.set_absolute_refuel_pressure),
        ]
        queued_any = False
        for key, setter in commands:
            if key not in settings:
                continue
            try:
                result = setter(
                    settings[key],
                    manual=True,
                    trace_metadata={
                        "source": "board_reset_reconnect_restore",
                        "setting_key": key,
                    },
                )
                queued_any = bool(result) or queued_any
            except Exception as exc:
                print(f"Could not restore {key} after board reset: {exc}")
        return queued_any

    def _get_experiment_progress_status_for_array(self):
        experiment_model = getattr(getattr(self, "model", None), "experiment_model", None)
        get_status = getattr(experiment_model, "get_progress_status", None)
        if not callable(get_status):
            return {}
        try:
            return dict(get_status() or {})
        except Exception as exc:
            return {"error": str(exc) or exc.__class__.__name__}

    def _array_has_remaining_wells_for_loaded_stock(self):
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        printer_head = None
        getter = getattr(rack_model, "get_gripper_printer_head", None)
        if callable(getter):
            try:
                printer_head = getter()
            except Exception:
                printer_head = None
        if printer_head is None:
            printer_head = getattr(rack_model, "gripper_printer_head", None)

        stock_id = self._safe_audit_value(printer_head, "get_stock_id")
        if not stock_id:
            return None
        try:
            return bool(self._get_array_remaining_wells(stock_id))
        except Exception:
            return None

    def _interrupt_array_after_board_reset(self, report=None):
        previous_state = self.get_array_run_state()
        if previous_state not in {"running", "stop_requested"}:
            return None

        context = getattr(self, "_array_context", None)
        try:
            audit_details = self._build_print_array_snapshot(context)
        except Exception:
            audit_details = {}

        progress_status = self._get_experiment_progress_status_for_array()
        has_progress = bool(progress_status.get("has_printed_progress", False))
        has_remaining = self._array_has_remaining_wells_for_loaded_stock()
        next_state = "resume_ready" if has_progress and has_remaining is not False else "idle"

        self._invalidate_paused_array_soft_stop_attempt(context)
        self._array_context = None
        self._soft_stop_clear_uncertain = False
        self._set_array_run_state(next_state)

        report = dict(report or {})
        audit_details.update(
            {
                "finalize_reason": "board_reset",
                "previous_array_state": previous_state,
                "array_state": self.get_array_run_state(),
                "progress_status": progress_status,
                "remaining_wells_for_loaded_stock": has_remaining,
                "reset_summary": report.get("summary"),
            }
        )
        self._record_print_array_audit_event(
            "print_array_interrupted_by_board_reset",
            "Print array interrupted by board reset",
            details=audit_details,
            level="warning",
        )
        return next_state

    def _interrupt_array_after_transport_fault(self, report=None, *, reason="transport_fault"):
        previous_state = self.get_array_run_state()
        if previous_state not in {"running", "stop_requested"}:
            return None

        reason = str(reason or "transport_fault")
        self._mark_evap_plate_dock_check_required(reason)

        context = getattr(self, "_array_context", None)
        try:
            audit_details = self._build_print_array_snapshot(context)
        except Exception:
            audit_details = {}

        progress_status = self._get_experiment_progress_status_for_array()
        has_progress = bool(progress_status.get("has_printed_progress", False))
        has_remaining = self._array_has_remaining_wells_for_loaded_stock()
        next_state = "resume_ready" if has_progress and has_remaining is not False else "idle"

        self._invalidate_paused_array_soft_stop_attempt(context)
        self._array_context = None
        self._soft_stop_clear_uncertain = False
        self._set_array_run_state(next_state)

        report = dict(report or {})
        audit_details.update(
            {
                "finalize_reason": reason,
                "fault_code": report.get("fault_code"),
                "previous_array_state": previous_state,
                "array_state": self.get_array_run_state(),
                "progress_status": progress_status,
                "remaining_wells_for_loaded_stock": has_remaining,
            }
        )
        gantry_motion_failure = reason in {
            "gantry_motion_failure",
            "xy_motion_failure",  # Legacy compatibility.
        }
        event_suffix = (
            "gantry_motion_failure" if gantry_motion_failure else "transport_fault"
        )
        event_message = (
            "Print array interrupted by gantry motion failure"
            if gantry_motion_failure
            else "Print array interrupted by command transport fault"
        )
        self._record_print_array_audit_event(
            f"print_array_interrupted_by_{event_suffix}",
            event_message,
            details=audit_details,
            level="error",
        )
        return next_state

    def _interrupt_array_after_machine_disconnect(self):
        """Retire active array state, reconciling only proven simulator cancels."""

        previous_state = self.get_array_run_state()
        if previous_state not in {"running", "stop_requested"}:
            return None

        context = getattr(self, "_array_context", None)
        try:
            audit_details = self._build_print_array_snapshot(context)
        except Exception:
            audit_details = {}

        queued_intent_ids = tuple(dict.fromkeys(
            str(row.get("execution_intent_id"))
            for row in list((context or {}).get("queued_wells") or [])
            if row.get("execution_intent_id")
        ))
        runtime_context = getattr(
            self,
            "runtime_context",
            PRODUCTION_RUNTIME_CONTEXT,
        )
        machine_state = getattr(getattr(self, "machine", None), "state", None)
        queue_checker = getattr(getattr(self, "machine", None), "check_if_all_completed", None)
        simulator_cancel_confirmed = bool(
            getattr(runtime_context, "is_simulation", False)
            and machine_state is not None
            and not bool(getattr(machine_state, "connected", True))
            and callable(queue_checker)
            and queue_checker()
        )
        reconciliation_status = (
            "not_required" if not queued_intent_ids else "unconfirmed"
        )
        if queued_intent_ids and simulator_cancel_confirmed:
            experiment_model = getattr(getattr(self, "model", None), "experiment_model", None)
            discard = getattr(experiment_model, "discard_execution_print_intents", None)
            try:
                if not callable(discard):
                    raise RuntimeError("execution-intent discard is unavailable")
                discard(queued_intent_ids)
                reconciliation_status = "discarded"
            except Exception as exc:
                reconciliation_status = "failed"
                setter = getattr(experiment_model, "set_execution_plan_sync_error", None)
                if callable(setter):
                    setter(exc)
                self.error_occurred_signal.emit(
                    "Saved Progress Error",
                    "The simulator canceled queued work, but the saved progress could "
                    "not be updated safely. Continuing remains unavailable.",
                )

        progress_status = self._get_experiment_progress_status_for_array()
        has_progress = bool(progress_status.get("has_printed_progress", False))
        has_remaining = self._array_has_remaining_wells_for_loaded_stock()
        next_state = "resume_ready" if has_progress and has_remaining is not False else "idle"

        self._mark_evap_plate_dock_check_required("machine_disconnect")
        self._invalidate_paused_array_soft_stop_attempt(context)
        self._array_context = None
        self._soft_stop_clear_uncertain = False
        self._set_array_run_state(next_state)

        audit_details.update(
            {
                "finalize_reason": "machine_disconnect",
                "previous_array_state": previous_state,
                "array_state": self.get_array_run_state(),
                "progress_status": progress_status,
                "remaining_wells_for_loaded_stock": has_remaining,
                "queued_intent_ids": list(queued_intent_ids),
                "simulator_cancel_confirmed": simulator_cancel_confirmed,
                "intent_reconciliation_status": reconciliation_status,
            }
        )
        self._record_print_array_audit_event(
            "print_array_interrupted_by_machine_disconnect",
            "Print array interrupted by machine disconnect",
            details=audit_details,
            level="warning",
        )
        return next_state

    def _build_print_settings_snapshot(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        return {
            "print_pressure_psi": self._safe_audit_value(machine_model, "get_current_print_pressure"),
            "target_print_pressure_psi": self._safe_audit_value(machine_model, "get_target_print_pressure"),
            "refuel_pressure_psi": self._safe_audit_value(machine_model, "get_current_refuel_pressure"),
            "target_refuel_pressure_psi": self._safe_audit_value(machine_model, "get_target_refuel_pressure"),
            "print_pulse_width_us": self._safe_audit_value(machine_model, "get_print_pulse_width"),
            "refuel_pulse_width_us": self._safe_audit_value(machine_model, "get_refuel_pulse_width"),
            "regulating_print_pressure": bool(
                getattr(machine_model, "regulating_print_pressure", False)
            ),
            "transport_paused": bool(getattr(machine_model, "transport_paused", False)),
        }

    def _build_loaded_printer_head_snapshot(self):
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        printer_head = self._safe_audit_value(rack_model, "get_gripper_printer_head")
        if printer_head is None:
            printer_head = getattr(rack_model, "gripper_printer_head", None)
        if printer_head is None:
            return {"loaded": False}

        return {
            "loaded": True,
            "stock_id": self._safe_audit_value(printer_head, "get_stock_id"),
            "stock_solution": self._safe_audit_value(printer_head, "get_stock_name"),
            "reagent": self._safe_audit_value(printer_head, "get_reagent_name"),
            "concentration": self._safe_audit_value(printer_head, "get_stock_concentration"),
            "printing_mode": self._safe_audit_value(printer_head, "get_printing_mode"),
            "printer_head_id": self._safe_audit_value(printer_head, "printer_head_id"),
            "display_name": self._safe_audit_value(printer_head, "display_name"),
            "head_type_id": self._safe_audit_value(printer_head, "head_type_id"),
            "printer_head_slot": getattr(rack_model, "gripper_slot_number", None),
            "calibration_complete": bool(
                self._safe_audit_value(printer_head, "check_calibration_complete", False)
            ),
            "current_volume_uL": self._safe_audit_value(printer_head, "get_current_volume"),
            "droplet_volume_nL": self._safe_audit_value(printer_head, "get_target_droplet_volume"),
        }

    def _count_audit_assigned_wells(self):
        well_plate = getattr(getattr(self, "model", None), "well_plate", None)
        getter = getattr(well_plate, "get_all_wells_with_reactions", None)
        if callable(getter):
            try:
                return len(getter(fill_by="rows", serpentine=False))
            except TypeError:
                try:
                    return len(getter())
                except Exception:
                    pass
            except Exception:
                pass

        wells = getattr(well_plate, "wells", None)
        if isinstance(wells, dict):
            try:
                assigned = [
                    well for well in wells.values()
                    if getattr(well, "assigned_reaction", None) is not None
                ]
                if assigned:
                    return len(assigned)
                return len(wells)
            except Exception:
                return None
        return None

    def _build_print_array_snapshot(self, context=None):
        if context is None:
            context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            context = {}

        stock_id = context.get("stock_id")
        remaining_well_count = None
        if stock_id:
            try:
                remaining_well_count = len(self._get_array_remaining_wells(stock_id))
            except Exception:
                remaining_well_count = None

        queued_wells = list(context.get("queued_wells") or [])
        planned_well_ids = context.get("planned_well_ids") or set()
        try:
            planned_well_count = len(planned_well_ids)
        except Exception:
            planned_well_count = None

        return {
            "array_state": self.get_array_run_state(),
            "stock_id": stock_id,
            "remaining_well_count": remaining_well_count,
            "queued_well_count": len(queued_wells),
            "planned_well_count": planned_well_count,
            "lookahead_wells": context.get("lookahead_wells"),
            "current_barrier_seq32": context.get("current_barrier_seq32"),
            "finalize_reason": context.get("finalize_reason"),
            "soft_stop_pending": bool(context.get("soft_stop_pending", False)),
            "soft_stop_phase": context.get("soft_stop_phase"),
            "soft_stop_origin": context.get("soft_stop_origin"),
            "soft_stop_frozen_barrier_seq32": context.get("soft_stop_frozen_barrier_seq32"),
            "soft_stop_attempt_token": context.get("soft_stop_attempt_token"),
            "soft_stop_recovery_reason": context.get("soft_stop_recovery_reason"),
            "soft_stop_clear_uncertain": bool(getattr(self, "_soft_stop_clear_uncertain", False)),
            "serpentine": bool(getattr(self, "_array_print_serpentine", ARRAY_PRINT_SERPENTINE)),
            "expected_volume_uL": context.get("expected_volume"),
            "droplet_volume_nL": context.get("droplet_volume"),
            "update_volume": bool(context.get("update_volume", False)),
            "settings": self._build_print_settings_snapshot(),
            "loaded_printer_head": self._build_loaded_printer_head_snapshot(),
        }

    def _record_print_array_audit_event(self, event_type, summary, details=None, level="info"):
        try:
            event_details = self._build_print_array_snapshot()
            if isinstance(details, dict):
                event_details.update(details)
            elif details is not None:
                event_details["details"] = details

            recorder = getattr(getattr(self, "model", None), "record_experiment_audit_event", None)
            if not callable(recorder):
                return None
            return recorder(event_type, summary, details=event_details, level=level)
        except Exception:
            return None

    def request_array_soft_stop(self):
        """Finish the active well, then park and leave the array resumable."""
        if self.get_array_run_state() != "running":
            return False
        context = getattr(self, "_array_context", None) or {}
        try:
            self._update_current_array_barrier()
        except Exception:
            pass
        current_barrier = context.get("current_barrier_seq32")
        if not current_barrier:
            return False
        self._set_array_run_state("stop_requested")
        context["soft_stop_pending"] = True
        context["soft_stop_phase"] = "waiting_watermark"
        context["soft_stop_barrier_seq32"] = current_barrier
        context["soft_stop_rejected_barriers"] = set()
        if not self._request_array_pause_after_barrier(current_barrier):
            return False
        self._record_print_array_audit_event(
            "print_array_soft_stop_requested",
            "Print array soft stop requested",
            details={"barrier_seq32": current_barrier},
        )
        return True

    def get_array_pause_action_state(self):
        """Describe the safe actions available while the machine is paused."""
        array_state = self.get_array_run_state()
        context = getattr(self, "_array_context", None)
        context = context if isinstance(context, dict) else {}
        phase = context.get("soft_stop_phase")
        origin = context.get("soft_stop_origin")

        action = None
        can_resume_entire_array = False
        if array_state == "running":
            action = "finish"
            can_resume_entire_array = True
        elif array_state == "stop_requested":
            if phase == "paused_safe_stop_recovery":
                action = "retry"
            elif phase == "paused_finalization":
                action = "finalize"
            else:
                action = "continue"

        return {
            "array_active": array_state in {"running", "stop_requested"},
            "array_state": array_state,
            "safe_stop_action": action,
            "can_resume_entire_array": bool(can_resume_entire_array),
            "soft_stop_phase": phase,
            "soft_stop_origin": origin,
            "watermark_uncertain": bool(
                origin == "immediate_pause"
                and phase == "paused_safe_stop_recovery"
            ),
        }

    def request_paused_array_soft_stop(self):
        """Convert an immediate array pause into a frozen-boundary soft stop."""
        array_state = self.get_array_run_state()
        context = getattr(self, "_array_context", None)
        if array_state not in {"running", "stop_requested"} or not isinstance(context, dict):
            return False

        phase = context.get("soft_stop_phase")
        if phase == "paused_finalization":
            previous_phase = context.get("soft_stop_phase_before_pause") or "parking"
            if previous_phase == "post_clear_parking":
                context["soft_stop_phase_before_pause"] = None
                context["soft_stop_recovery_reason"] = None
                context["soft_stop_pause_during_clearing"] = False
                return self._continue_soft_stop_parking_after_clear(context)
            if previous_phase == "final_well_completion":
                if self.resume_commands() is False:
                    context["soft_stop_recovery_reason"] = "finalization_resume_write_failed"
                    return False
                context["soft_stop_phase"] = "done"
                context["soft_stop_phase_before_pause"] = None
                context["soft_stop_recovery_reason"] = None
                return self._enqueue_array_finalize("completed") is not False
            if self.resume_commands() is False:
                context["soft_stop_recovery_reason"] = "finalization_resume_write_failed"
                return False
            context["soft_stop_phase"] = previous_phase
            context["soft_stop_phase_before_pause"] = None
            context["soft_stop_recovery_reason"] = None
            self._record_print_array_audit_event(
                "print_array_safe_stop_finalization_resumed",
                "Print array safe-stop finalization resumed",
            )
            return True

        if (
            context.get("soft_stop_origin") == "immediate_pause"
            and phase in {
                "waiting_pause_confirmation",
                "arming_watermark_from_pause",
                "resuming_to_watermark",
                "waiting_watermark",
                "waiting_completion_catchup",
                "clearing",
                "parking",
                "done",
            }
        ):
            # The conversion is already in flight. Status is authoritative;
            # repeated button presses must not emit another arm or Resume.
            self._advance_paused_array_soft_stop_from_status()
            return True

        if array_state == "running":
            try:
                self._update_current_array_barrier()
            except Exception:
                pass
            frozen_barrier = self._coerce_positive_seq32(
                context.get("current_barrier_seq32")
            )
            if frozen_barrier is None:
                return False
            context["soft_stop_origin"] = "immediate_pause"
            context["soft_stop_frozen_barrier_seq32"] = frozen_barrier
            context["soft_stop_barrier_seq32"] = frozen_barrier
            context["soft_stop_pending"] = True
            context["soft_stop_resume_sent"] = False
            context["soft_stop_recovery_reason"] = None
            context["soft_stop_phase_before_pause"] = None
            self._set_array_run_state("stop_requested")
        elif context.get("soft_stop_origin") != "immediate_pause":
            # A second immediate pause may interrupt the ordinary Stop After
            # Well path. Adopt its already-selected barrier, then freeze it so
            # recovery can never retarget a later well.
            frozen_barrier = self._coerce_positive_seq32(
                context.get("soft_stop_barrier_seq32")
                or context.get("current_barrier_seq32")
            )
            if frozen_barrier is None:
                return False
            context["soft_stop_origin"] = "immediate_pause"
            context["soft_stop_frozen_barrier_seq32"] = frozen_barrier
            context["soft_stop_barrier_seq32"] = frozen_barrier
            context["soft_stop_pending"] = True

        frozen_barrier = self._coerce_positive_seq32(
            context.get("soft_stop_frozen_barrier_seq32")
        )
        if frozen_barrier is None:
            return False

        context["soft_stop_pending"] = True
        context["soft_stop_barrier_seq32"] = frozen_barrier
        context["soft_stop_phase"] = "waiting_pause_confirmation"
        context["soft_stop_recovery_reason"] = None
        context["soft_stop_resume_sent"] = False
        token = self._new_paused_array_soft_stop_attempt(context)
        self._schedule_paused_array_soft_stop_timeout(
            "waiting_pause_confirmation",
            token,
        )
        self._record_print_array_audit_event(
            "print_array_paused_safe_stop_requested",
            "Finish-current-well safe stop requested from immediate pause",
            details={"frozen_barrier_seq32": frozen_barrier},
        )
        self._advance_paused_array_soft_stop_from_status()

        active_context = getattr(self, "_array_context", None)
        if not isinstance(active_context, dict):
            return self.get_array_run_state() in {"resume_ready", "idle"}
        if self.get_array_run_state() == "running":
            return False
        return active_context.get("soft_stop_origin") == "immediate_pause"

    def _new_paused_array_soft_stop_attempt(self, context):
        token = int(context.get("soft_stop_attempt_token") or 0) + 1
        context["soft_stop_attempt_token"] = token
        return token

    def _invalidate_paused_array_soft_stop_attempt(self, context=None):
        if context is None:
            context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return None
        return self._new_paused_array_soft_stop_attempt(context)

    def _schedule_paused_array_soft_stop_timeout(self, phase, token):
        QtCore.QTimer.singleShot(
            PAUSED_ARRAY_SOFT_STOP_PHASE_TIMEOUT_MS,
            lambda expected_phase=str(phase), expected_token=int(token): self._handle_paused_array_soft_stop_timeout(
                expected_phase,
                expected_token,
            ),
        )

    def _paused_array_soft_stop_callback_is_current(self, phase, token):
        context = getattr(self, "_array_context", None)
        return bool(
            isinstance(context, dict)
            and self.get_array_run_state() == "stop_requested"
            and context.get("soft_stop_origin") == "immediate_pause"
            and context.get("soft_stop_phase") == phase
            and int(context.get("soft_stop_attempt_token") or 0) == int(token)
        )

    def _handle_paused_array_soft_stop_timeout(self, phase, token):
        if not self._paused_array_soft_stop_callback_is_current(phase, token):
            return
        if phase == "waiting_pause_confirmation":
            self._return_paused_soft_stop_to_running("pause_confirmation_timeout")
            return
        self._enter_paused_array_soft_stop_recovery(f"{phase}_timeout")

    def _advance_paused_array_soft_stop_from_status(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if (
            self.get_array_run_state() != "stop_requested"
            or context.get("soft_stop_origin") != "immediate_pause"
            or not context.get("soft_stop_pending")
        ):
            return False

        phase = context.get("soft_stop_phase")
        if phase in {
            "paused_safe_stop_recovery",
            "paused_finalization",
            "clearing",
            "parking",
            "done",
        }:
            return False

        machine_model = getattr(self.model, "machine_model", None)
        transport_paused = bool(getattr(machine_model, "transport_paused", False))
        watermark_reached = bool(getattr(machine_model, "pause_watermark_reached", False))
        frozen_barrier = self._coerce_positive_seq32(
            context.get("soft_stop_frozen_barrier_seq32")
        )
        if frozen_barrier is None:
            self._enter_paused_array_soft_stop_recovery("missing_frozen_barrier")
            return False

        if watermark_reached and transport_paused:
            if self._paused_array_frozen_well_finished_array(context):
                return self._finish_paused_array_final_well(context)
            context["soft_stop_phase"] = "waiting_watermark"
            self._invalidate_paused_array_soft_stop_attempt(context)
            return self._begin_soft_stop_clear_and_park()

        if phase == "waiting_completion_catchup":
            return self._maybe_complete_array_soft_stop_after_catchup()

        if phase == "waiting_pause_confirmation":
            if not transport_paused:
                return False
            if self._latest_retired_command_number() >= frozen_barrier:
                context["soft_stop_phase"] = "waiting_completion_catchup"
                token = self._new_paused_array_soft_stop_attempt(context)
                self._schedule_paused_array_soft_stop_timeout(
                    "waiting_completion_catchup",
                    token,
                )
                return self._maybe_complete_array_soft_stop_after_catchup()
            reported_barrier = self._coerce_positive_seq32(
                getattr(machine_model, "pause_after_seq32", 0)
            )
            if reported_barrier == frozen_barrier:
                return self._resume_paused_array_to_frozen_watermark(context)
            return self._arm_paused_array_frozen_watermark(context, frozen_barrier)

        if phase == "arming_watermark_from_pause":
            reported_barrier = self._coerce_positive_seq32(
                getattr(machine_model, "pause_after_seq32", 0)
            )
            if transport_paused and reported_barrier == frozen_barrier:
                return self._resume_paused_array_to_frozen_watermark(context)
            return False

        if phase == "resuming_to_watermark":
            if not transport_paused:
                context["soft_stop_phase"] = "waiting_watermark"
                self._invalidate_paused_array_soft_stop_attempt(context)
                self._record_print_array_audit_event(
                    "print_array_safe_stop_resumed",
                    "Print array resumed toward the frozen safe-stop watermark",
                    details={"frozen_barrier_seq32": frozen_barrier},
                )
                return True
            return False

        if phase == "waiting_watermark":
            return False
        return False

    def _paused_array_frozen_well_finished_array(self, context):
        if context.get("queued_wells"):
            return False
        try:
            return not bool(
                self._get_array_remaining_wells(context.get("stock_id"))
            )
        except Exception:
            return False

    def _finish_paused_array_final_well(self, context):
        self._invalidate_paused_array_soft_stop_attempt(context)
        context["soft_stop_pending"] = False
        if self.resume_commands() is False:
            context["soft_stop_phase_before_pause"] = "final_well_completion"
            context["soft_stop_phase"] = "paused_finalization"
            context["soft_stop_recovery_reason"] = "final_well_resume_write_failed"
            return False
        context["soft_stop_phase"] = "done"
        self._record_print_array_audit_event(
            "print_array_safe_stop_final_well_completed",
            "Frozen safe-stop well completed the print array",
        )
        return self._enqueue_array_finalize("completed") is not False

    def _arm_paused_array_frozen_watermark(self, context, frozen_barrier):
        context["soft_stop_phase"] = "arming_watermark_from_pause"
        token = self._new_paused_array_soft_stop_attempt(context)
        self._schedule_paused_array_soft_stop_timeout(
            "arming_watermark_from_pause",
            token,
        )
        try:
            sent = self.machine.request_pause_after_seq32(
                frozen_barrier,
                on_success=lambda payload, expected_token=token, barrier=frozen_barrier: self._handle_paused_array_watermark_ack(
                    payload,
                    expected_token,
                    barrier,
                ),
                on_failure=lambda payload, expected_token=token, barrier=frozen_barrier: self._handle_paused_array_watermark_failure(
                    payload,
                    expected_token,
                    barrier,
                ),
            )
        except Exception as exc:
            self._handle_paused_array_watermark_failure(
                {"reason": "write_failed", "error": str(exc)},
                token,
                frozen_barrier,
            )
            return False
        if sent is False and self._paused_array_soft_stop_callback_is_current(
            "arming_watermark_from_pause",
            token,
        ):
            self._handle_paused_array_watermark_failure(
                {"reason": "write_failed"},
                token,
                frozen_barrier,
            )
        return sent is not False

    def _handle_paused_array_watermark_ack(self, payload, token, barrier):
        if not self._paused_array_soft_stop_callback_is_current(
            "arming_watermark_from_pause",
            token,
        ):
            return
        self._record_print_array_audit_event(
            "print_array_safe_stop_watermark_acknowledged",
            "Frozen safe-stop watermark acknowledged; waiting for status confirmation",
            details={
                "frozen_barrier_seq32": barrier,
                "ack": dict(payload or {}),
            },
        )

    def _handle_paused_array_watermark_failure(self, payload, token, barrier):
        if not self._paused_array_soft_stop_callback_is_current(
            "arming_watermark_from_pause",
            token,
        ):
            return
        payload = dict(payload or {})
        reason = str(payload.get("reason") or "unknown")
        ack_result = str(payload.get("ack_result") or "")
        if reason == "ack_rejected" and ack_result == "watermark_rejected":
            context = getattr(self, "_array_context", None)
            if not isinstance(context, dict):
                return
            context["soft_stop_phase"] = "waiting_completion_catchup"
            context["soft_stop_recovery_reason"] = "frozen_barrier_already_retired"
            next_token = self._new_paused_array_soft_stop_attempt(context)
            self._schedule_paused_array_soft_stop_timeout(
                "waiting_completion_catchup",
                next_token,
            )
            self._record_print_array_audit_event(
                "print_array_safe_stop_frozen_barrier_retired",
                "Frozen safe-stop barrier had already retired; catching up completion",
                details={"frozen_barrier_seq32": barrier},
                level="warning",
            )
            self._maybe_complete_array_soft_stop_after_catchup()
            return
        if reason in {"write_failed", "invalid_barrier", "ack_rejected"}:
            self._return_paused_soft_stop_to_running(reason)
            return
        self._enter_paused_array_soft_stop_recovery(reason)

    def _resume_paused_array_to_frozen_watermark(self, context):
        if context.get("soft_stop_resume_sent"):
            return False
        context["soft_stop_resume_sent"] = True
        self._record_print_array_audit_event(
            "print_array_safe_stop_watermark_armed",
            "Frozen safe-stop watermark confirmed in machine status",
            details={
                "frozen_barrier_seq32": context.get(
                    "soft_stop_frozen_barrier_seq32"
                )
            },
        )
        context["soft_stop_phase"] = "resuming_to_watermark"
        token = self._new_paused_array_soft_stop_attempt(context)
        self._schedule_paused_array_soft_stop_timeout(
            "resuming_to_watermark",
            token,
        )
        if self.resume_commands() is False:
            if self._paused_array_soft_stop_callback_is_current(
                "resuming_to_watermark",
                token,
            ):
                self._enter_paused_array_soft_stop_recovery("resume_write_failed")
            return False
        return True

    def _return_paused_soft_stop_to_running(self, reason):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        self._invalidate_paused_array_soft_stop_attempt(context)
        context["soft_stop_pending"] = False
        context["soft_stop_phase"] = None
        context["soft_stop_origin"] = None
        context["soft_stop_frozen_barrier_seq32"] = None
        context["soft_stop_barrier_seq32"] = None
        context["soft_stop_resume_sent"] = False
        context["soft_stop_recovery_reason"] = str(reason or "unarmed_failure")
        self._set_array_run_state("running")
        self.error_occurred_signal.emit(
            "Safe Stop Not Armed",
            "The finish-current-well stop could not be armed. The machine remains paused; "
            "you may retry, resume the entire array, or abort it.",
        )
        return False

    def _enter_paused_array_soft_stop_recovery(self, reason):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        previous_phase = context.get("soft_stop_phase")
        self._invalidate_paused_array_soft_stop_attempt(context)
        context["soft_stop_phase_before_pause"] = previous_phase
        context["soft_stop_phase"] = "paused_safe_stop_recovery"
        context["soft_stop_pending"] = True
        context["soft_stop_recovery_reason"] = str(reason or "uncertain_state")
        context["soft_stop_resume_sent"] = False

        try:
            sent = self.machine.pause_commands()
        except Exception:
            sent = False
        if sent is not False:
            self.model.machine_model.pause_commands()
        self._record_print_array_audit_event(
            "print_array_safe_stop_recovery_required",
            "Print array safe stop requires operator recovery",
            details={
                "previous_phase": previous_phase,
                "recovery_reason": context.get("soft_stop_recovery_reason"),
            },
            level="warning",
        )
        self.error_occurred_signal.emit(
            "Safe Stop Needs Attention",
            "The safe-stop watermark or resume state could not be confirmed. The machine "
            "has been told to pause again. Retry the safe stop or abort the array; full-array "
            "resume is unavailable because a watermark may still be armed.",
        )
        return False

    @staticmethod
    def _coerce_positive_seq32(value):
        try:
            seq32 = int(value or 0)
        except (TypeError, ValueError):
            return None
        return seq32 if seq32 > 0 else None

    def _soft_stop_rejected_barriers(self, context):
        rejected = context.setdefault("soft_stop_rejected_barriers", set())
        if isinstance(rejected, set):
            return rejected
        rejected_set = set()
        try:
            for value in rejected:
                seq32 = self._coerce_positive_seq32(value)
                if seq32 is not None:
                    rejected_set.add(seq32)
        except Exception:
            rejected_set = set()
        context["soft_stop_rejected_barriers"] = rejected_set
        return rejected_set

    def _latest_retired_command_number(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        value = getattr(machine_model, "last_retired_command_num", 0)
        return self._coerce_positive_seq32(value) or 0

    def _select_array_soft_stop_barrier(self, context):
        if not isinstance(context, dict):
            return None
        rejected = self._soft_stop_rejected_barriers(context)
        last_retired = self._latest_retired_command_number()
        for well_info in list(context.get("queued_wells") or []):
            if not isinstance(well_info, dict):
                continue
            seq32 = self._coerce_positive_seq32(well_info.get("dispense_seq32"))
            if seq32 is None:
                continue
            if seq32 in rejected:
                continue
            if last_retired and seq32 <= last_retired:
                continue
            return seq32
        return None

    def _request_array_pause_after_barrier(self, barrier_seq32):
        barrier_seq32 = self._coerce_positive_seq32(barrier_seq32)
        if barrier_seq32 is None:
            return False
        return self.machine.request_pause_after_seq32(
            barrier_seq32,
            on_failure=lambda payload, barrier=barrier_seq32: self._handle_array_soft_stop_pause_after_failure(
                payload,
                requested_barrier_seq32=barrier,
            ),
        )

    def _handle_array_soft_stop_pause_after_failure(self, payload=None, requested_barrier_seq32=None):
        payload = dict(payload or {})
        reason = str(payload.get("reason") or "unknown")
        barrier_seq32 = (
            self._coerce_positive_seq32(payload.get("barrier_seq32"))
            or self._coerce_positive_seq32(requested_barrier_seq32)
        )
        ack_result = payload.get("ack_result")

        if self._retry_array_soft_stop_after_stale_barrier(reason, ack_result, barrier_seq32):
            return

        self._abort_array_after_soft_stop_failure(reason, barrier_seq32)

    def _retry_array_soft_stop_after_stale_barrier(self, reason, ack_result, barrier_seq32):
        if str(reason or "") != "ack_rejected" or str(ack_result or "") != "watermark_rejected":
            return False

        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return True
        if self.get_array_run_state() != "stop_requested":
            return True

        phase = context.get("soft_stop_phase", "waiting_watermark")
        if phase not in {"waiting_watermark", "waiting_completion_catchup"}:
            return True

        rejected = self._soft_stop_rejected_barriers(context)
        if barrier_seq32 is not None:
            rejected.add(int(barrier_seq32))

        retry_barrier = self._select_array_soft_stop_barrier(context)
        if retry_barrier is not None:
            context["current_barrier_seq32"] = retry_barrier
            context["soft_stop_barrier_seq32"] = retry_barrier
            context["soft_stop_pending"] = True
            context["soft_stop_phase"] = "waiting_watermark"
            ok = self._request_array_pause_after_barrier(retry_barrier)
            if ok:
                self._record_print_array_audit_event(
                    "print_array_soft_stop_retargeted",
                    "Print array soft stop retargeted after stale barrier",
                    details={
                        "rejected_barrier_seq32": barrier_seq32,
                        "retry_barrier_seq32": retry_barrier,
                    },
                )
            return True

        context["current_barrier_seq32"] = None
        context["soft_stop_pending"] = True
        context["soft_stop_phase"] = "waiting_completion_catchup"
        self._record_print_array_audit_event(
            "print_array_soft_stop_waiting_for_completion",
            "Print array soft stop waiting for completion after stale barrier",
            details={"rejected_barrier_seq32": barrier_seq32},
        )
        self._maybe_complete_array_soft_stop_after_catchup()
        return True

    def _abort_array_after_soft_stop_failure(self, reason, barrier_seq32=None):
        context = getattr(self, "_array_context", None)
        if context is not None:
            context["soft_stop_pending"] = False
            context["soft_stop_phase"] = "done"

        detail_map = {
            "write_failed": "the pause-after request could not be sent",
            "ack_rejected": "the MCU rejected the pause-after request",
            "ack_timeout": "the MCU did not acknowledge the pause-after request",
            "not_confirmed": "the pause-after request was not confirmed within the grace window",
            "invalid_barrier": "the pause-after request had an invalid barrier",
        }
        detail = detail_map.get(str(reason or "unknown"), f"the pause-after request failed ({reason})")
        barrier_text = f" for command {int(barrier_seq32)}" if barrier_seq32 else ""

        try:
            self.clear_command_queue()
        except Exception:
            self._complete_array_finalize("hard_abort")

        self.error_occurred_signal.emit(
            "Soft Stop Failed",
            f"Soft stop failed because {detail}{barrier_text}. The print array was aborted and the queued commands were cleared.",
        )

    def _warn_soft_stop_post_watermark(self, message):
        self.error_occurred_signal.emit("Soft Stop Warning", str(message or "Soft stop could not finish parking."))

    def _maybe_complete_array_soft_stop_after_catchup(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("soft_stop_phase") != "waiting_completion_catchup":
            return False
        if context.get("finalize_reason") is not None:
            return False

        queued_wells = list(context.get("queued_wells") or [])
        if context.get("soft_stop_origin") == "immediate_pause":
            frozen_barrier = self._coerce_positive_seq32(
                context.get("soft_stop_frozen_barrier_seq32")
            )
            for well_info in queued_wells:
                dispense_seq32 = self._coerce_positive_seq32(
                    well_info.get("dispense_seq32") if isinstance(well_info, dict) else None
                )
                if (
                    frozen_barrier is not None
                    and dispense_seq32 is not None
                    and dispense_seq32 <= frozen_barrier
                ):
                    return False
        elif queued_wells:
            return False

        stock_id = context.get("stock_id")
        try:
            remaining_wells = self._get_array_remaining_wells(stock_id)
        except Exception:
            remaining_wells = []

        if not remaining_wells and not queued_wells:
            if context.get("soft_stop_origin") == "immediate_pause":
                return self._finish_paused_array_final_well(context)
            context["soft_stop_pending"] = False
            context["soft_stop_phase"] = "done"
            return self._enqueue_array_finalize("completed")

        if context.get("soft_stop_origin") == "immediate_pause":
            context["soft_stop_phase"] = "waiting_watermark"
            self._invalidate_paused_array_soft_stop_attempt(context)
            return self._begin_soft_stop_clear_and_park()

        context["soft_stop_pending"] = False
        context["soft_stop_phase"] = "done"
        return self._enqueue_array_finalize("soft_stop")

    def _clear_command_queue_for_soft_stop(self, on_cleared=None):
        self._clear_machine_and_model_command_queues(
            reason="array_queue_clear",
            handler=on_cleared,
        )

    def _begin_soft_stop_clear_and_park(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("soft_stop_phase", "waiting_watermark") != "waiting_watermark":
            return False

        self._invalidate_paused_array_soft_stop_attempt(context)
        context["soft_stop_phase"] = "clearing"
        context["finalize_reason"] = "soft_stop"
        context["soft_stop_transport_was_paused"] = bool(
            getattr(self.model.machine_model, "transport_paused", False)
        )
        self._soft_stop_clear_uncertain = False

        try:
            self._clear_command_queue_for_soft_stop(self._on_soft_stop_queue_cleared)
        except Exception:
            context["soft_stop_phase"] = "done"
            context["soft_stop_pending"] = False
            self._mark_evap_plate_dock_check_required("soft_stop_clear_unconfirmed")
            self._warn_soft_stop_post_watermark(
                "Soft stop reached the watermark, but the queued commands could not be cleared. Preserving resume state without parking."
            )
            self._complete_array_finalize("soft_stop")
            return False
        return True

    def _on_soft_stop_queue_cleared(self, clear_result=None):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return

        clear_result = dict(clear_result or {})
        print(f"Soft stop clear completion: {clear_result}")
        context["soft_stop_pending"] = False

        if not bool(clear_result.get("status_confirmed")):
            self._soft_stop_clear_uncertain = True
            context["skip_array_accel_restore"] = True
            context["soft_stop_phase"] = "done"
            self._mark_evap_plate_dock_check_required("soft_stop_clear_unconfirmed")
            ack_received = bool(clear_result.get("ack_received"))
            ack_timed_out = bool(clear_result.get("ack_timed_out"))
            if ack_received:
                warning = (
                    "Soft stop reached the watermark and received CLEAR_ACK, but the queue clear was not confirmed within the grace window. "
                    "Preserving resume state without parking."
                )
            elif ack_timed_out:
                warning = (
                    "Soft stop reached the watermark, but the queue clear was not confirmed within the grace window after CLEAR_ACK timed out. "
                    "Preserving resume state without parking."
                )
            else:
                warning = (
                    "Soft stop reached the watermark, but the queue clear was not confirmed within the grace window. "
                    "Preserving resume state without parking."
                )
            self._warn_soft_stop_post_watermark(
                warning
            )
            self._complete_array_finalize("soft_stop")
            return

        barrier_seq32 = self._coerce_positive_seq32(
            context.get("soft_stop_barrier_seq32")
        )
        cleared_intent_ids = []
        if barrier_seq32 is not None:
            for well_info in list(context.get("queued_wells") or []):
                dispense_seq32 = self._coerce_positive_seq32(
                    well_info.get("dispense_seq32")
                )
                intent_id = well_info.get("execution_intent_id")
                if dispense_seq32 is not None and dispense_seq32 > barrier_seq32 and intent_id:
                    cleared_intent_ids.append(intent_id)
        if cleared_intent_ids:
            experiment_model = getattr(self.model, "experiment_model", None)
            discard = getattr(experiment_model, "discard_execution_print_intents", None)
            if callable(discard):
                try:
                    discard(cleared_intent_ids)
                except Exception as exc:
                    setter = getattr(experiment_model, "set_execution_plan_sync_error", None)
                    if callable(setter):
                        setter(exc)
                    self.error_occurred_signal.emit(
                        "Saved Progress Error",
                        "The queue was cleared safely, but the canceled look-ahead "
                        "work could not be reconciled with saved progress. Continuing "
                        "remains unavailable.",
                    )

        try:
            self.update_expected_with_current()
        except Exception:
            pass

        self._soft_stop_clear_uncertain = False
        if context.pop("soft_stop_pause_during_clearing", False):
            context["soft_stop_phase_before_pause"] = "post_clear_parking"
            context["soft_stop_phase"] = "paused_finalization"
            context["soft_stop_recovery_reason"] = "paused_after_queue_clear"
            return

        self._continue_soft_stop_parking_after_clear(context)

    def _continue_soft_stop_parking_after_clear(self, context):
        if not isinstance(context, dict) or context is not getattr(self, "_array_context", None):
            return False
        if context.get("soft_stop_transport_was_paused"):
            try:
                resumed = self.resume_commands()
            except Exception:
                resumed = False
            if resumed is False:
                if context.get("soft_stop_origin") == "immediate_pause":
                    context["soft_stop_phase_before_pause"] = "post_clear_parking"
                    context["soft_stop_phase"] = "paused_finalization"
                    context["soft_stop_recovery_reason"] = "park_resume_write_failed"
                    self._warn_soft_stop_post_watermark(
                        "Soft stop reached the watermark and cleared the queue, but transport could not be resumed for parking. The machine remains paused."
                    )
                    return False
                context["soft_stop_phase"] = "done"
                self._mark_evap_plate_dock_check_required("soft_stop_park_failed")
                self._warn_soft_stop_post_watermark(
                    "Soft stop reached the watermark and cleared the queue, but transport could not be resumed for parking. Preserving resume state without parking."
                )
                self._complete_array_finalize("soft_stop")
                return False

        self._queue_array_profile_disable_once(clear_on_failure=False)
        context["soft_stop_phase"] = "parking"
        context["soft_stop_recovery_reason"] = None

        def _finish_after_park():
            active_context = getattr(self, "_array_context", None)
            if isinstance(active_context, dict):
                active_context["soft_stop_phase"] = "done"
            self._complete_array_finalize("soft_stop")

        if self._queue_pause_park_sequence(on_complete=_finish_after_park) is False:
            context["soft_stop_phase"] = "done"
            self._mark_evap_plate_dock_check_required("soft_stop_park_failed")
            self._warn_soft_stop_post_watermark(
                "Soft stop reached the watermark, but the machine could not be parked. Preserving resume state without parking."
            )
            self._complete_array_finalize("soft_stop")
            return False
        return True

    def _queue_pause_park_sequence(self, on_complete=None):
        if self.move_to_location('pause') is False:
            return False
        if self.move_to_location('pause', z_offset=-5000, on_complete=on_complete) is False:
            return False
        return True

    def _prepare_motion_endpoint(self, requested_position, *, override):
        """Return the exact firmware-representable endpoint or reject safely."""

        try:
            plan = canonicalize_position(
                self.expected_position,
                requested_position,
            )
        except MotionPositionContractError as exc:
            self._reject_motion_position_contract(exc)
            return None

        return self._validate_motion_endpoint_plan(plan, override=override)

    def _prepare_relative_motion_endpoint(self, requested_displacement, *, override):
        """Return a firmware-representable plan for one relative request."""

        try:
            plan = canonicalize_relative_position(
                self.expected_position,
                requested_displacement,
            )
        except MotionPositionContractError as exc:
            self._reject_motion_position_contract(exc)
            return None
        return self._validate_motion_endpoint_plan(plan, override=override)

    def _reject_motion_position_contract(self, error):
        message = f"Motion target cannot be represented safely: {error}"
        print(message)
        signal = getattr(self, "error_occurred_signal", None)
        if signal is not None:
            signal.emit("Motion Target Rejected", message)

    def _validate_motion_endpoint_plan(self, plan, *, override):
        """Apply endpoint and path safety checks to a canonical motion plan."""

        requested = plan["requested_position"]
        canonical = plan["canonical_position"]
        if not self._hard_endpoint_allowed(requested):
            return None
        if canonical != requested and not self._hard_endpoint_allowed(canonical):
            return None
        if not override and self.check_collision(plan["origin_position"], canonical):
            print('Collision detected')
            return None
        return plan

    def _remember_motion_endpoint(
        self,
        plan,
        *,
        queue_result="accepted",
        accepted_position=None,
        failed_axis=None,
    ):
        """Retain one queue-batch endpoint for reconciliation/audit evidence."""

        evidence = copy.deepcopy(plan)
        evidence["queue_result"] = str(queue_result)
        if accepted_position is not None:
            accepted = {
                axis: int(accepted_position[axis])
                for axis in self._position_axes()
            }
            if accepted != evidence["canonical_position"]:
                evidence["accepted_position"] = accepted
        if failed_axis is not None:
            evidence["failed_axis"] = str(failed_axis)
        self._pending_motion_endpoint_evidence = evidence
        self._log_motion_endpoint_evidence(evidence)
        return copy.deepcopy(evidence)

    @staticmethod
    def _log_motion_endpoint_evidence(evidence):
        if evidence.get("adjusted_axes"):
            print(
                "Motion endpoint canonicalized: "
                + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
            )

    def _single_axis_requested_endpoint(self, axis, value):
        requested = dict(self.expected_position)
        requested[axis] = value
        return requested

    @staticmethod
    def _single_axis_requested_displacement(axis, value):
        requested = {"X": 0, "Y": 0, "Z": 0}
        requested[axis] = value
        return requested

    def _plate_calibration_motion_is_blocked(self):
        session = self._plate_calibration_active_session()
        if session is None:
            return False
        return getattr(self, "_plate_calibration_internal_motion_token", None) != session.get(
            "session_token"
        )

    def _reject_conflicting_plate_calibration_motion(self):
        if not self._plate_calibration_motion_is_blocked():
            return False
        self.error_occurred_signal.emit(
            "Plate Calibration Active",
            "Other motion is blocked while the guarded plate-calibration session is active.",
        )
        return True

    @contextmanager
    def _plate_calibration_motion_scope(self, session_token):
        previous = getattr(self, "_plate_calibration_internal_motion_token", None)
        self._plate_calibration_internal_motion_token = session_token
        try:
            yield
        finally:
            self._plate_calibration_internal_motion_token = previous

    def set_relative_X(self, x,manual=False,handler=None,override=False):
        """Set relative X using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_relative_motion_endpoint(
            self._single_axis_requested_displacement("X", x),
            override=override,
        )
        if plan is None:
            return False
        delta = plan["canonical_position"]["X"] - plan["origin_position"]["X"]
        if self.machine.set_relative_X(delta,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(x=plan["canonical_position"]["X"])
        self._remember_motion_endpoint(plan)
        return True

    def set_relative_Y(self, y,manual=False,handler=None, override=False):
        """Set relative Y using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_relative_motion_endpoint(
            self._single_axis_requested_displacement("Y", y),
            override=override,
        )
        if plan is None:
            return False
        delta = plan["canonical_position"]["Y"] - plan["origin_position"]["Y"]
        if self.machine.set_relative_Y(delta,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(y=plan["canonical_position"]["Y"])
        self._remember_motion_endpoint(plan)
        return True

    def set_relative_Z(self, z,manual=False,handler=None, override=False):
        """Set relative Z using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_relative_motion_endpoint(
            self._single_axis_requested_displacement("Z", z),
            override=override,
        )
        if plan is None:
            return False
        delta = plan["canonical_position"]["Z"] - plan["origin_position"]["Z"]
        if self.machine.set_relative_Z(delta,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(z=plan["canonical_position"]["Z"])
        self._remember_motion_endpoint(plan)
        return True
    
    def set_absolute_XY(self, x, y, manual=False, handler=None, override=False):
        """Set absolute X/Y using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        requested = dict(self.expected_position)
        requested.update({"X": x, "Y": y})
        plan = self._prepare_motion_endpoint(requested, override=override)
        if plan is None:
            return False
        canonical = plan["canonical_position"]
        if self.machine.set_absolute_XY(
            canonical["X"], canonical["Y"], manual=manual, handler=handler
        ) is False:
            return False
        self.update_expected_position(x=canonical["X"], y=canonical["Y"])
        self._remember_motion_endpoint(plan)
        return True

    def set_absolute_X(self, x,manual=False,handler=None, override=False):
        """Set absolute X using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_motion_endpoint(
            self._single_axis_requested_endpoint("X", x),
            override=override,
        )
        if plan is None:
            return False
        canonical = plan["canonical_position"]["X"]
        if self.machine.set_absolute_X(canonical,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(x=canonical)
        self._remember_motion_endpoint(plan)
        return True

    def set_absolute_Y(self, y,manual=False,handler=None, override=False):
        """Set absolute Y using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_motion_endpoint(
            self._single_axis_requested_endpoint("Y", y),
            override=override,
        )
        if plan is None:
            return False
        canonical = plan["canonical_position"]["Y"]
        if self.machine.set_absolute_Y(canonical,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(y=canonical)
        self._remember_motion_endpoint(plan)
        return True
    
    def set_absolute_Z(self, z,manual=False,handler=None, override=False):
        """Set absolute Z using the firmware-representable endpoint."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_motion_endpoint(
            self._single_axis_requested_endpoint("Z", z),
            override=override,
        )
        if plan is None:
            return False
        canonical = plan["canonical_position"]["Z"]
        if self.machine.set_absolute_Z(canonical,manual=manual,handler=handler) is False:
            return False
        self.update_expected_position(z=canonical)
        self._remember_motion_endpoint(plan)
        return True

    def _hard_endpoint_allowed(self, target_pos):
        """Enforce numeric/global travel bounds even when obstacle override is used."""

        guard = getattr(self, "configuration_safety_guard", None)
        if guard is None:
            return True
        try:
            guard.validate_endpoint(target_pos)
        except ConfigurationSafetyError as exc:
            print(f"Motion endpoint rejected: {exc}")
            signal = getattr(self, "error_occurred_signal", None)
            if signal is not None:
                signal.emit("Motion Endpoint Rejected", str(exc))
            return False
        return True

    def check_collision(self,current_pos, target_pos):
        """
        Check if a straight-line path from current_pos to target_pos intersects any 3D obstacles
        or goes out of bounds.

        Returns True on malformed safety config as a fail-safe (block motion).
        """
        boundaries = self.model.location_model.get_boundaries()
        obstacles = self.model.location_model.get_obstacles()

        try:
            for axis in ['X', 'Y', 'Z']:
                if not (boundaries['min'][axis] <= min(current_pos[axis], target_pos[axis]) and
                        max(current_pos[axis], target_pos[axis]) <= boundaries['max'][axis]):
                    return True

            for obstacle in obstacles:
                min_corner = {axis: min(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
                max_corner = {axis: max(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}

                for axis in ['X', 'Y', 'Z']:
                    min_proj = min(current_pos[axis], target_pos[axis])
                    max_proj = max(current_pos[axis], target_pos[axis])

                    if max_proj < min_corner[axis] or min_proj > max_corner[axis]:
                        break
                else:
                    return True
        except (TypeError, KeyError):
            print('Collision check misconfigured: invalid boundaries/obstacles payload')
            return True

        return False
    
    def set_relative_coordinates(self, x, y, z, manual=False, handler=None,override=False):
        """Set relative Cartesian coordinates using representable deltas."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        plan = self._prepare_relative_motion_endpoint(
            {"X": x, "Y": y, "Z": z},
            override=override,
        )
        if plan is None:
            return False

        origin = plan["origin_position"]
        canonical = plan["canonical_position"]
        deltas = {
            axis: canonical[axis] - origin[axis]
            for axis in self._position_axes()
        }
        commands = []
        if deltas["Z"] < 0:
            order = ("Z", "Y", "X")
        else:
            order = ("Y", "X", "Z")
        commands = [(axis, deltas[axis]) for axis in order if deltas[axis] != 0]

        if not commands:
            if handler:
                handler()
            self.update_expected_position(**{
                axis.lower(): canonical[axis] for axis in self._position_axes()
            })
            if plan.get("adjusted_axes"):
                evidence = copy.deepcopy(plan)
                evidence["queue_result"] = "canonical_noop"
                self._log_motion_endpoint_evidence(evidence)
            return True

        current = dict(origin)
        for index, (axis, value) in enumerate(commands):
            current_handler = handler if index == len(commands) - 1 else None
            queue_method = getattr(self.machine, f"set_relative_{axis}")
            queued = queue_method(value, manual=manual, handler=current_handler)
            if queued is False:
                self.update_expected_position(
                    x=current["X"], y=current["Y"], z=current["Z"]
                )
                if current != origin:
                    self._remember_motion_endpoint(
                        plan,
                        queue_result="partial",
                        accepted_position=current,
                        failed_axis=axis,
                    )
                return False
            current[axis] = canonical[axis]

        self.update_expected_position(
            x=canonical["X"], y=canonical["Y"], z=canonical["Z"]
        )
        self._remember_motion_endpoint(plan)
        return True
    
    def set_absolute_coordinates(self, x, y, z, manual=False, handler=None, kwargs=None, override=False):
        """Set absolute coordinates; always use XY for any X/Y movement."""
        if self._reject_conflicting_plate_calibration_motion():
            return False
        requested = {'X': x, 'Y': y, 'Z': z}
        plan = self._prepare_motion_endpoint(requested, override=override)
        if plan is None:
            return False

        canonical = plan["canonical_position"]
        cur = dict(plan["origin_position"])
        needs_xy = (canonical["X"] != cur['X']) or (canonical["Y"] != cur['Y'])
        needs_z  = canonical["Z"] != cur['Z']

        # 2) plan ordering: if moving "up", do Z first; otherwise XY first, then Z
        moves = []
        if needs_z and canonical["Z"] < cur['Z']:
            # up first
            moves.append(('Z', canonical["Z"]))
            if needs_xy:
                moves.append(('XY', (canonical["X"], canonical["Y"])))
        else:
            # XY first (if any), then Z (if any)
            if needs_xy:
                moves.append(('XY', (canonical["X"], canonical["Y"])))
            if needs_z:
                moves.append(('Z', canonical["Z"]))

        # 3) nothing to do
        if not moves:
            if handler:
                handler()
            self.update_expected_position(
                x=canonical["X"], y=canonical["Y"], z=canonical["Z"]
            )
            if plan.get("adjusted_axes"):
                evidence = copy.deepcopy(plan)
                evidence["queue_result"] = "canonical_noop"
                self._log_motion_endpoint_evidence(evidence)
            return True

        # 4) dispatch (XY is used even if only one axis actually changes)
        for idx, (axis, val) in enumerate(moves):
            is_last = (idx == len(moves) - 1)
            cb = handler if is_last else None

            if axis == 'XY':
                x_val, y_val = val
                queued = self.machine.set_absolute_XY(
                    x_val, y_val,
                    manual=manual,
                    handler=cb,
                    kwargs=kwargs
                )
                if queued is False:
                    self.update_expected_position(
                        x=cur['X'],
                        y=cur['Y'],
                        z=cur['Z'],
                    )
                    if cur != plan["origin_position"]:
                        self._remember_motion_endpoint(
                            plan,
                            queue_result="partial",
                            accepted_position=cur,
                            failed_axis=axis,
                        )
                    return False
                cur['X'], cur['Y'] = x_val, y_val
            elif axis == 'Z':
                queued = self.machine.set_absolute_Z(
                    val,
                    manual=manual,
                    handler=cb,
                    kwargs=kwargs
                )
                if queued is False:
                    self.update_expected_position(
                        x=cur['X'],
                        y=cur['Y'],
                        z=cur['Z'],
                    )
                    if cur != plan["origin_position"]:
                        self._remember_motion_endpoint(
                            plan,
                            queue_result="partial",
                            accepted_position=cur,
                            failed_axis=axis,
                        )
                    return False
                cur['Z'] = val
            else:
                raise ValueError(f"Unknown axis {axis}")

        # 5) update expected end position
        self.update_expected_position(
            x=canonical["X"], y=canonical["Y"], z=canonical["Z"]
        )
        self._remember_motion_endpoint(plan)
        return True

    def set_relative_print_pressure(self, pressure,manual=False):
        """Set the relative pressure for the machine."""
        #print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_print_pressure(pressure,manual=manual)

    def set_relative_refuel_pressure(self, pressure,manual=False):
        """Set the relative pressure for the machine."""
        #print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_refuel_pressure(pressure,manual=manual)

    def set_absolute_print_pressure(self, pressure,handler=None, manual=False, trace_metadata=None):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        return self.machine.set_absolute_print_pressure(
            pressure,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def set_absolute_refuel_pressure(self, pressure, handler=None, manual=False, trace_metadata=None):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        return self.machine.set_absolute_refuel_pressure(
            pressure,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def set_regulator_recovery_profile(self, channel, recovery, handler=None, kwargs=None, manual=False):
        return self.machine.set_regulator_recovery_profile(
            channel,
            recovery,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_regulator_slew_profile(self, channel, slew, handler=None, kwargs=None, manual=False):
        return self.machine.set_regulator_slew_profile(
            channel,
            slew,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_regulator_ready_profile(self, channel, ready, handler=None, kwargs=None, manual=False):
        return self.machine.set_regulator_ready_profile(
            channel,
            ready,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def restore_regulator_profile(self, channels, source="baseline", handler=None, kwargs=None, manual=False):
        return self.machine.restore_regulator_profile(
            channels,
            source=source,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def _validate_refuel_vacuum_pressure(self, pressure):
        try:
            pressure = float(pressure)
        except (TypeError, ValueError):
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                f"Invalid refuel vacuum pressure: {pressure}",
            )
            return None
        if pressure < -1.0 or pressure > 0.0:
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                "Refuel vacuum pressure must be between -1.0 and 0.0 psi.",
            )
            return None
        return pressure

    def enter_refuel_vacuum_mode(
        self,
        target_psi=-1.0,
        prep_position_steps=20000,
        move_hz=5000,
        handler=None,
        manual=False,
    ):
        target_psi = self._validate_refuel_vacuum_pressure(target_psi)
        if target_psi is None:
            return False
        return self.machine.enter_refuel_vacuum_mode(
            target_psi=target_psi,
            prep_position_steps=int(prep_position_steps),
            move_hz=int(move_hz),
            handler=handler,
            manual=manual,
        )

    def set_refuel_vacuum_pressure(self, pressure_psi, handler=None, manual=False):
        pressure_psi = self._validate_refuel_vacuum_pressure(pressure_psi)
        if pressure_psi is None:
            return False
        return self.machine.set_refuel_vacuum_pressure(
            pressure_psi,
            handler=handler,
            manual=manual,
        )

    def exit_refuel_vacuum_mode(self, restore_pressure_psi, handler=None, manual=False):
        try:
            restore_pressure_psi = float(restore_pressure_psi)
        except (TypeError, ValueError):
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                f"Invalid refuel restore pressure: {restore_pressure_psi}",
            )
            return False
        if restore_pressure_psi < 0.0:
            restore_pressure_psi = 0.0
        return self.machine.exit_refuel_vacuum_mode(
            restore_pressure_psi,
            handler=handler,
            manual=manual,
        )

    def set_print_pulse_width(self, pulse_width,handler=None, manual=False,update_model=False, trace_metadata=None):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_print_pulse_width(pulse_width)
        return self.machine.set_print_pulse_width(
            pulse_width,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def set_refuel_pulse_width(self, pulse_width, handler=None, manual=False,update_model=False, trace_metadata=None):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_refuel_pulse_width(pulse_width)
        return self.machine.set_refuel_pulse_width(
            pulse_width,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    @staticmethod
    def _normalize_calibration_mode(value, *, fallback="droplet"):
        mode = str(value or "").strip().lower()
        if mode in CALIBRATION_MODE_PRINT_PULSE_WIDTH_US:
            return mode
        if fallback is None:
            return None
        fallback_mode = str(fallback or "droplet").strip().lower()
        return fallback_mode if fallback_mode in CALIBRATION_MODE_PRINT_PULSE_WIDTH_US else "droplet"

    @staticmethod
    def _calibration_mode_label(mode):
        normalized = Controller._normalize_calibration_mode(mode)
        return "Stream" if normalized == "stream" else "Droplet"

    @classmethod
    def expected_calibration_print_pulse_width_us(cls, mode):
        normalized = cls._normalize_calibration_mode(mode, fallback=None)
        if normalized is None:
            return None
        return int(CALIBRATION_MODE_PRINT_PULSE_WIDTH_US[normalized])

    @staticmethod
    def _read_printer_head_printing_mode(printer_head):
        if printer_head is None:
            return None
        getter = getattr(printer_head, "get_printing_mode", None)
        try:
            if callable(getter):
                return Controller._normalize_calibration_mode(getter(), fallback=None)
        except Exception:
            pass
        return Controller._normalize_calibration_mode(
            getattr(printer_head, "printing_mode", None),
            fallback=None,
        )

    def _current_print_pulse_width_us_for_preflight(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        getter = getattr(machine_model, "get_print_pulse_width", None)
        try:
            value = getter() if callable(getter) else getattr(machine_model, "print_pulse_width", None)
            return int(value)
        except Exception:
            return None

    def _matching_print_profiles_for_calibration_mode(self, requested_mode, expected_pulse_width_us):
        profiles = list(getattr(getattr(self, "model", None), "print_profiles", []) or [])
        matches = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            mode = self._normalize_calibration_mode(profile.get("mode"), fallback=None)
            if mode != requested_mode:
                continue
            try:
                profile_pulse_width = int(profile.get("print_pulse_width"))
            except Exception:
                continue
            if profile_pulse_width != int(expected_pulse_width_us):
                continue
            matches.append(dict(profile))
        return matches

    def get_calibration_mode_preflight(self, requested_mode):
        requested_mode = self._normalize_calibration_mode(requested_mode, fallback=None)
        if requested_mode is None:
            return {
                "ok": False,
                "code": "invalid_requested_mode",
                "requested_mode": None,
                "head_mode": None,
                "current_print_pulse_width_us": self._current_print_pulse_width_us_for_preflight(),
                "expected_print_pulse_width_us": None,
                "matching_profiles": [],
                "message": "Calibration mode must be droplet or stream.",
            }

        expected_pulse_width_us = self.expected_calibration_print_pulse_width_us(requested_mode)
        current_pulse_width_us = self._current_print_pulse_width_us_for_preflight()
        matching_profiles = self._matching_print_profiles_for_calibration_mode(
            requested_mode,
            expected_pulse_width_us,
        )

        try:
            rack_model = getattr(getattr(self, "model", None), "rack_model", None)
            printer_head = rack_model.get_gripper_printer_head() if rack_model is not None else None
        except Exception:
            printer_head = None

        if printer_head is None:
            return {
                "ok": False,
                "code": "no_printer_head",
                "requested_mode": requested_mode,
                "head_mode": None,
                "current_print_pulse_width_us": current_pulse_width_us,
                "expected_print_pulse_width_us": expected_pulse_width_us,
                "matching_profiles": matching_profiles,
                "message": "No printer head is loaded.",
            }

        head_mode = self._read_printer_head_printing_mode(printer_head)
        if head_mode is None:
            return {
                "ok": False,
                "code": "head_mode_unavailable",
                "requested_mode": requested_mode,
                "head_mode": None,
                "current_print_pulse_width_us": current_pulse_width_us,
                "expected_print_pulse_width_us": expected_pulse_width_us,
                "matching_profiles": matching_profiles,
                "message": "Loaded printer head printing mode could not be read.",
            }

        if head_mode != requested_mode:
            return {
                "ok": False,
                "code": "head_mode_mismatch",
                "requested_mode": requested_mode,
                "head_mode": head_mode,
                "current_print_pulse_width_us": current_pulse_width_us,
                "expected_print_pulse_width_us": expected_pulse_width_us,
                "matching_profiles": matching_profiles,
                "message": (
                    f"The loaded printer head is set to {self._calibration_mode_label(head_mode)} mode, "
                    f"but {self._calibration_mode_label(requested_mode)} calibration was requested."
                ),
            }

        if current_pulse_width_us is None:
            return {
                "ok": False,
                "code": "pulse_width_unavailable",
                "requested_mode": requested_mode,
                "head_mode": head_mode,
                "current_print_pulse_width_us": current_pulse_width_us,
                "expected_print_pulse_width_us": expected_pulse_width_us,
                "matching_profiles": matching_profiles,
                "message": "Current print pulse width could not be read.",
            }

        if int(current_pulse_width_us) != int(expected_pulse_width_us):
            return {
                "ok": False,
                "code": "pulse_width_mismatch",
                "requested_mode": requested_mode,
                "head_mode": head_mode,
                "current_print_pulse_width_us": current_pulse_width_us,
                "expected_print_pulse_width_us": expected_pulse_width_us,
                "matching_profiles": matching_profiles,
                "message": (
                    f"{self._calibration_mode_label(requested_mode)} calibration expects "
                    f"{int(expected_pulse_width_us)} us print pulse width, but the machine is set to "
                    f"{int(current_pulse_width_us)} us."
                ),
            }

        return {
            "ok": True,
            "code": "ok",
            "requested_mode": requested_mode,
            "head_mode": head_mode,
            "current_print_pulse_width_us": current_pulse_width_us,
            "expected_print_pulse_width_us": expected_pulse_width_us,
            "matching_profiles": matching_profiles,
            "message": "",
        }

    def apply_print_profile(self, profile, callback=None):
        """Apply a print profile through the existing print/refuel setting commands."""
        profile = dict(profile or {})
        required = (
            "print_pressure",
            "refuel_pressure",
            "print_pulse_width",
            "refuel_pulse_width",
        )
        missing = [key for key in required if key not in profile]
        if missing:
            raise ValueError(f"Print profile missing required settings: {missing}")

        settings = {
            "print_pressure": float(profile["print_pressure"]),
            "refuel_pressure": float(profile["refuel_pressure"]),
            "print_pulse_width": int(profile["print_pulse_width"]),
            "refuel_pulse_width": int(profile["refuel_pulse_width"]),
        }
        self.handle_settings_change_request(settings, callback or self.intermediate_callback)
        return True

    def set_dispense_frequency_hz(self, hz, manual=False):
        """Set the print pacing used for future dispense commands."""
        return self.model.set_dispense_frequency_hz(
            hz,
        )

    def reset_print_syringe(self):
        """Reset the print syringe."""
        self.machine.reset_print_syringe()

    def reset_refuel_syringe(self):
        """Reset the refuel syringe."""
        self.machine.reset_refuel_syringe()

    def check_print_syringe_position(self):
        """Checks the syringe position and resets it if nearly at the limit."""
        current_p = self.model.machine_model.get_current_p_motor()
        if current_p > 95000:
            self.reset_print_syringe()
    
    def check_refuel_syringe_position(self):
        """Checks the syringe position and resets it if nearly at the limit."""
        current_r = self.model.machine_model.get_current_r_motor()
        if current_r > 95000:
            self.reset_refuel_syringe()

    def pause_machine(self):
        """Pause the machine."""
        self._emit_machine_workflow_interrupted("machine_paused")
        self.machine.pause_machine()

    def LED_on(self):
        """Turn on the LED."""
        self.machine.LED_on()
        
    def LED_off(self):
        """Turn off the LED."""
        self.machine.LED_off()

    def home_machine(self):
        """Home the machine."""
        recovery_state = self.get_xy_motion_recovery_state()
        if recovery_state not in {"idle", "home_required"}:
            return False
        self._emit_machine_workflow_interrupted("homing_started")
        print("Homing machine...")
        self.model.machine_model.reset_home_status()
        self.model.machine_model.home_status_signal.emit()
        return self.machine.home_motors()

    def home_regulators(self):
        """Home the regulators."""
        print("Homing regulators...")
        self.machine.home_regulators()

    def toggle_motors(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.motors_enabled:
            success = self.machine.disable_motors()  # Assuming method exists
        else:
            success = self.machine.enable_motors()  # Assuming method exists
        if success:
            self.model.machine_model.toggle_motor_state()  # Update the model state

    def toggle_regulation(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.regulating_print_pressure:
            success = self.machine.deregulate_print_pressure()  # Assuming method exists
            success_2 = self.machine.deregulate_refuel_pressure()
        else:
            success = self.machine.regulate_print_pressure()  # Assuming method exists
            success_2 = self.machine.regulate_refuel_pressure()
        return success and success_2

    def add_reagent_to_slot(self, slot):
        """Add a reagent to a slot."""
        if slot == 0:
            new_printer_head = PrinterHead('Water',1,'Blue')
        elif slot == 1:
            new_printer_head = PrinterHead('Ethanol',2,'Green')
        elif slot == 2:
            new_printer_head = PrinterHead('Acetone',3,'Red')
        elif slot == 3:
            new_printer_head = PrinterHead('Methanol',4,'Yellow')
        self.model.rack_model.update_slot_with_printer_head(slot, new_printer_head)

    def confirm_slot(self, slot):
        """Confirm that a reagent is present in a slot."""
        self.model.rack_model.confirm_slot(slot)

    def _install_committed_configuration(self, result):
        try:
            if "Locations.json" in result.documents:
                self.model.install_committed_locations(result.documents["Locations.json"])
            if "Plates.json" in result.documents:
                self.model.install_committed_plates(result.documents["Plates.json"])
            if "RegulatorProfiles.json" in result.documents:
                self.model.install_committed_regulator_profiles(
                    result.documents["RegulatorProfiles.json"]
                )
            self.saved_target_authorizer = (
                self.configuration_transactions.saved_target_authorizer
            )
            return True
        except Exception as exc:
            self._configuration_recovery_required = True
            # Machine_FreeRTOS rejects every newly queued command and stops
            # pumping an existing queue while this latch is set.  Safe
            # disconnection remains available through Controller.
            if getattr(self, "machine", None) is not None:
                try:
                    self.machine._command_queue_blocked_reason = (
                        "configuration_recovery_required"
                    )
                except Exception:
                    pass
            self.error_occurred_signal.emit(
                "Configuration Restart Required",
                "The configuration was durably committed, but runtime state could not "
                f"be refreshed: {exc}. Restart before any hardware action.",
            )
            return False

    @staticmethod
    def _position_axes():
        return ("X", "Y", "Z")

    def _position_reconciliation_now(self):
        clock = getattr(self, "_monotonic_fn", None)
        return float(clock() if callable(clock) else time.monotonic())

    def _position_reconciliation_snapshot(self, *, now_monotonic=None):
        machine_model = self.model.machine_model
        getter = getattr(machine_model, "get_position_telemetry_snapshot", None)
        if not callable(getter):
            return None
        now = (
            self._position_reconciliation_now()
            if now_monotonic is None
            else float(now_monotonic)
        )
        return getter(now_monotonic=now)

    def _position_reconciliation_timeout_ms(self):
        guard = getattr(self, "configuration_safety_guard", None)
        policy = getattr(guard, "policy", None)
        timeout_ms = getattr(policy, "position_telemetry_max_age_ms", 2500)
        try:
            return max(1, int(timeout_ms))
        except (TypeError, ValueError):
            return 2500

    def _settle_position_reconciliation(self, *, reason, now_monotonic=None):
        now = (
            self._position_reconciliation_now()
            if now_monotonic is None
            else float(now_monotonic)
        )
        machine_model = self.model.machine_model
        position_getter = getattr(
            machine_model,
            "get_current_position_dict_capital",
            machine_model.get_current_position_dict,
        )
        position = position_getter()
        self._position_reconciliation = {
            "state": "settled",
            "reason": str(reason),
            "completed_monotonic": now,
            "expected_position": copy.deepcopy(self.expected_position),
            "reported_position": {
                axis: int(position[axis]) for axis in self._position_axes()
            },
        }
        return copy.deepcopy(self._position_reconciliation)

    def _begin_position_reconciliation(self):
        """Wait for a complete post-drain position cycle before capture."""

        motion_endpoint = copy.deepcopy(
            getattr(self, "_pending_motion_endpoint_evidence", None)
        )
        self._pending_motion_endpoint_evidence = None
        if getattr(self, "configuration_safety_guard", None) is None:
            self.update_expected_with_current()
            return

        now = self._position_reconciliation_now()
        timeout_ms = self._position_reconciliation_timeout_ms()
        telemetry = self._position_reconciliation_snapshot(now_monotonic=now) or {}
        axes = telemetry.get("axes", {}) if isinstance(telemetry, dict) else {}
        position = self.model.machine_model.get_current_position_dict_capital()
        self._position_reconciliation = {
            "state": "pending",
            "reason": "command_queue_drained",
            "started_monotonic": now,
            "deadline_monotonic": now + (timeout_ms / 1000.0),
            "telemetry_max_age_ms": timeout_ms,
            "trust_epoch": telemetry.get("trust_epoch"),
            "baseline_generations": {
                axis: int((axes.get(axis) or {}).get("generation", 0))
                for axis in self._position_axes()
            },
            "observed_generations": {
                axis: int((axes.get(axis) or {}).get("generation", 0))
                for axis in self._position_axes()
            },
            "expected_position": copy.deepcopy(self.expected_position),
            "reported_position_at_drain": {
                axis: int(position[axis]) for axis in self._position_axes()
            },
        }
        if motion_endpoint is not None:
            self._position_reconciliation["motion_endpoint"] = motion_endpoint
        session = getattr(self, "_plate_calibration_session", None)
        if (
            isinstance(session, dict)
            and session.get("state") == "reconciling"
            and session.get("awaiting_queue_drain")
        ):
            session["awaiting_queue_drain"] = False
            session["reconciliation_started_monotonic"] = now
            self._advance_plate_calibration_session(now_monotonic=now)

    def _advance_position_reconciliation(self, *, now_monotonic=None):
        record = getattr(self, "_position_reconciliation", None)
        if not isinstance(record, dict):
            return {"state": "settled", "reason": "compatibility_default"}
        if record.get("state") not in {"pending", "timed_out"}:
            return copy.deepcopy(record)

        now = (
            self._position_reconciliation_now()
            if now_monotonic is None
            else float(now_monotonic)
        )
        telemetry = self._position_reconciliation_snapshot(now_monotonic=now)
        if not isinstance(telemetry, dict):
            if now >= float(record.get("deadline_monotonic", now)):
                record["state"] = "timed_out"
                record["reason"] = "position_telemetry_unavailable"
            return copy.deepcopy(record)

        observed_epoch = telemetry.get("trust_epoch")
        if observed_epoch != record.get("trust_epoch"):
            record["state"] = "trust_changed"
            record["reason"] = "motion_trust_epoch_changed"
            record["observed_trust_epoch"] = observed_epoch
            record["completed_monotonic"] = now
            return copy.deepcopy(record)

        try:
            queue_empty = bool(self.check_if_all_completed())
        except Exception:
            queue_empty = False
        if not queue_empty or bool(self.model.machine_model.is_busy()):
            if now >= float(record.get("deadline_monotonic", now)):
                record["state"] = "timed_out"
                record["reason"] = "motion_not_settled_before_deadline"
            return copy.deepcopy(record)

        axes = telemetry.get("axes", {})
        baseline = record.get("baseline_generations", {})
        observed = {
            axis: int((axes.get(axis) or {}).get("generation", 0))
            for axis in self._position_axes()
        }
        record["observed_generations"] = observed
        if not all(
            observed[axis] > int(baseline.get(axis, 0))
            for axis in self._position_axes()
        ):
            if now >= float(record.get("deadline_monotonic", now)):
                record["state"] = "timed_out"
                record["reason"] = "post_drain_position_cycle_incomplete"
            return copy.deepcopy(record)

        position = self.model.machine_model.get_current_position_dict_capital()
        reported = {
            axis: int(position[axis]) for axis in self._position_axes()
        }
        expected = {
            axis: record.get("expected_position", {}).get(axis)
            for axis in self._position_axes()
        }
        record["reported_position"] = reported
        record["completed_monotonic"] = now
        if reported == expected:
            record["state"] = "settled"
            record["reason"] = "fresh_post_drain_position_matches_expected"
        else:
            record["state"] = "mismatch"
            record["reason"] = "fresh_post_drain_position_mismatch"
        return copy.deepcopy(record)

    def _configuration_capture_readiness(self):
        """Return one JSON-safe, fail-closed current-position evidence snapshot."""

        guard = getattr(self, "configuration_safety_guard", None)
        if guard is None:
            return {"ready": True, "reason_codes": [], "compatibility_mode": True}
        machine_model = self.model.machine_model
        now = float(self._monotonic_fn())
        reconciliation = self._advance_position_reconciliation(
            now_monotonic=now
        )
        telemetry_getter = getattr(machine_model, "get_position_telemetry_snapshot", None)
        telemetry = telemetry_getter(now_monotonic=now) if callable(telemetry_getter) else None
        reasons = []
        if not machine_model.is_connected():
            reasons.append("not_connected")
        if not machine_model.motors_are_enabled():
            reasons.append("motors_disabled")
        if not machine_model.motors_are_homed():
            reasons.append("not_homed")
        if self.get_xy_motion_recovery_state() != "idle":
            reasons.append("motion_recovery_active")
        if bool(getattr(machine_model, "paused", False)):
            reasons.append("machine_paused")
        if bool(getattr(machine_model, "transport_paused", False)):
            reasons.append("transport_paused")
        if self.get_array_run_state() not in {"idle", "resume_ready"}:
            reasons.append("array_runner_active")
        if str(getattr(self, "_seq_state", "idle")) != "idle":
            reasons.append("sequence_runner_active")
        try:
            queue_empty = bool(self.check_if_all_completed())
        except Exception:
            queue_empty = False
        if not queue_empty:
            reasons.append("queue_not_empty")
        if bool(machine_model.is_busy()):
            reasons.append("machine_busy")
        position = machine_model.get_current_position_dict_capital()
        if telemetry is None:
            reasons.append("position_telemetry_unavailable")
            axes = {}
            trust_epoch = None
        else:
            axes = telemetry.get("axes", {})
            trust_epoch = telemetry.get("trust_epoch")
            for axis in ("X", "Y", "Z"):
                evidence = axes.get(axis, {})
                age = evidence.get("age_ms")
                if evidence.get("generation", 0) <= 0 or age is None:
                    reasons.append(f"position_missing_{axis.lower()}")
                elif age > guard.policy.position_telemetry_max_age_ms:
                    reasons.append(f"position_stale_{axis.lower()}")
        try:
            guard.validate_endpoint(position)
        except ConfigurationSafetyError:
            reasons.append("position_outside_global_bounds")
        expected = dict(self.expected_position)
        if any(type(position.get(axis)) is not int for axis in ("X", "Y", "Z")):
            reasons.append("position_invalid")
        reconciliation_state = str(reconciliation.get("state") or "settled")
        if reconciliation_state == "pending":
            reasons.append("position_reconciliation_pending")
        elif reconciliation_state == "timed_out":
            reasons.append("position_reconciliation_timeout")
        elif reconciliation_state == "trust_changed":
            reasons.append("position_reconciliation_trust_changed")
        elif reconciliation_state == "mismatch":
            reasons.append("expected_position_mismatch")
        elif any(
            expected.get(axis) != position.get(axis) for axis in ("X", "Y", "Z")
        ):
            reasons.append("expected_position_mismatch")
        machine_uuid = getattr(getattr(self, "machine_data_paths", None), "machine_uuid", None)
        if not machine_uuid:
            reasons.append("authorized_machine_missing")
        return {
            "ready": not reasons,
            "reason_codes": list(dict.fromkeys(reasons)),
            "machine_uuid": machine_uuid,
            "trust_epoch": trust_epoch,
            "captured_position": {axis: int(position[axis]) for axis in ("X", "Y", "Z")},
            "expected_position": copy.deepcopy(expected),
            "position_reconciliation": copy.deepcopy(reconciliation),
            "telemetry": copy.deepcopy(axes),
            "captured_monotonic": now,
            "telemetry_max_age_ms": guard.policy.position_telemetry_max_age_ms,
        }

    @staticmethod
    def _plate_calibration_points():
        return ("top_left", "top_right", "bottom_right", "bottom_left")

    @staticmethod
    def _plate_calibration_terminal_states():
        return {"failed", "cancelled"}

    def _plate_calibration_session_snapshot(self):
        session = getattr(self, "_plate_calibration_session", None)
        if not isinstance(session, dict):
            return {
                "session_token": None,
                "state": "idle",
                "target_key": None,
                "target_state": None,
                "manual_first": False,
                "expected_endpoint": None,
                "failure_reason": None,
            }
        public_keys = (
            "session_token",
            "state",
            "phase",
            "machine_uuid",
            "plate_name",
            "target_key",
            "target_state",
            "manual_first",
            "expected_endpoint",
            "expected_point",
            "next_point_index",
            "failure_reason",
        )
        return {
            key: copy.deepcopy(session.get(key))
            for key in public_keys
        }

    def _emit_plate_calibration_state(self):
        snapshot = self._plate_calibration_session_snapshot()
        self._emit_optional("plate_calibration_state_changed", snapshot)
        return snapshot

    def _set_plate_calibration_state(self, state, **updates):
        session = getattr(self, "_plate_calibration_session", None)
        if not isinstance(session, dict):
            return self._plate_calibration_session_snapshot()
        session.update(copy.deepcopy(updates))
        session["state"] = str(state)
        return self._emit_plate_calibration_state()

    def _plate_calibration_active_session(self, session_token=None):
        session = getattr(self, "_plate_calibration_session", None)
        if not isinstance(session, dict):
            return None
        if session.get("state") in self._plate_calibration_terminal_states():
            return None
        if session_token is not None and session.get("session_token") != session_token:
            return None
        return session

    def _fail_plate_calibration_session(self, reason, *, notify=True):
        session = getattr(self, "_plate_calibration_session", None)
        if not isinstance(session, dict):
            return False
        if session.get("state") in self._plate_calibration_terminal_states():
            return False
        reason = str(reason or "plate_calibration_failed")
        try:
            self.model.well_plate.discard_temp_calibrations()
        except Exception:
            pass
        self.discard_configuration_capture_evidence("plate_calibration")
        self._set_plate_calibration_state(
            "failed",
            failure_reason=reason,
            expected_endpoint=None,
            awaiting_queue_drain=False,
        )
        if notify:
            self.error_occurred_signal.emit(
                "Plate Calibration Stopped",
                "Plate calibration stopped safely. No calibration was saved. "
                f"Start it again after resolving: {reason}.",
            )
        return False

    def _on_plate_calibration_workflow_interrupted(self, payload):
        session = self._plate_calibration_active_session()
        if session is None:
            return
        reason = payload.get("reason") if isinstance(payload, dict) else payload
        self._fail_plate_calibration_session(
            f"workflow_interrupted:{reason or 'unknown'}",
            notify=False,
        )

    def _on_plate_calibration_pause_changed(self):
        if not bool(getattr(self.model.machine_model, "paused", False)):
            return
        self._fail_plate_calibration_session("machine_paused", notify=False)

    def _plate_calibration_fail_preflight(self, reason_code, message):
        return {
            "allowed": False,
            "reason_code": str(reason_code),
            "message": str(message),
            "state": "idle",
        }

    def plate_calibration_entry_preflight(self):
        """Inspect the governed plate and machine state without issuing motion."""

        if self._plate_calibration_active_session() is not None:
            return self._plate_calibration_fail_preflight(
                "plate_calibration_already_active",
                "A plate calibration is already active.",
            )

        machine_model = self.model.machine_model
        if not machine_model.is_connected():
            return self._plate_calibration_fail_preflight(
                "not_connected", "Connect to the machine before calibrating the plate."
            )
        if not machine_model.motors_are_enabled() or not machine_model.motors_are_homed():
            return self._plate_calibration_fail_preflight(
                "motors_not_ready", "Enable and home the motors before calibrating the plate."
            )
        if bool(getattr(machine_model, "paused", False)) or bool(
            getattr(machine_model, "transport_paused", False)
        ):
            return self._plate_calibration_fail_preflight(
                "motion_paused", "Resume or recover the motion system before calibrating the plate."
            )
        if not self.check_if_all_completed() or bool(machine_model.is_busy()):
            return self._plate_calibration_fail_preflight(
                "command_queue_not_idle", "Wait for the command queue to become idle."
            )
        origin = str(getattr(self, "expected_location", None) or "").strip().casefold()
        supported_origin = origin in {
            "home",
            "loading",
            "camera",
            "plate",
            "pause",
        } or origin.startswith("slot-")
        if not supported_origin:
            return self._plate_calibration_fail_preflight(
                "unsupported_plate_entry_origin",
                "Move through a known Home, rack-slot, Camera, or plate route before "
                "starting plate calibration.",
            )

        readiness = self._configuration_capture_readiness()
        if not readiness.get("ready"):
            reasons = ", ".join(readiness.get("reason_codes") or ["machine_not_ready"])
            return self._plate_calibration_fail_preflight(
                "machine_not_ready", f"Machine position is not ready for calibration: {reasons}."
            )

        rack_model = getattr(self.model, "rack_model", None)
        head_getter = getattr(rack_model, "get_gripper_printer_head", None)
        head = head_getter() if callable(head_getter) else getattr(
            rack_model, "gripper_printer_head", None
        )
        is_calibration_chip = getattr(head, "is_calibration_chip", None)
        if head is None or not callable(is_calibration_chip) or not is_calibration_chip():
            return self._plate_calibration_fail_preflight(
                "calibration_head_required",
                "Load the calibration printer head before calibrating the plate.",
            )

        service = getattr(self, "configuration_transactions", None)
        guard = getattr(self, "configuration_safety_guard", None)
        paths = getattr(self, "machine_data_paths", None)
        if service is None or guard is None or not getattr(paths, "machine_uuid", None):
            return self._plate_calibration_fail_preflight(
                "configuration_safety_unavailable",
                "The governed machine-data safety service is unavailable.",
            )

        plate = getattr(self.model, "well_plate", None)
        try:
            plate_name = str(plate.get_current_plate_name()).strip()
            calibrations = copy.deepcopy(
                plate.get_all_current_plate_calibrations()
            )
            required = set(self._plate_calibration_points())
            if set(calibrations) != required:
                raise ValueError("the active plate must contain exactly four corners")
            normalized = {}
            for point_name in self._plate_calibration_points():
                point = calibrations[point_name]
                normalized[point_name] = {
                    axis: int(point[axis]) for axis in self._position_axes()
                }
            guard.validate_active_documents(read_governed_documents(service.paths))
            state = service.refresh(allow_pending=False)
        except Exception as exc:
            return self._plate_calibration_fail_preflight(
                "plate_configuration_invalid",
                f"The active plate configuration is not safe to use: {exc}",
            )

        target_key = f"plate:{plate_name.casefold()}"
        authorization = dict(state.authorization.get(target_key) or {})
        if not authorization:
            return self._plate_calibration_fail_preflight(
                "plate_authorization_missing",
                f"Authorization state is missing for {target_key}.",
            )
        value_sha256 = canonical_value_sha256(normalized)
        if authorization.get("value_sha256") != value_sha256:
            return self._plate_calibration_fail_preflight(
                "plate_authorization_value_mismatch",
                "The plate coordinates differ from their authorization record.",
            )

        target_state = str(authorization.get("state") or "")
        promotion_candidates = self.controlled_calibration_promotion_candidates()
        if promotion_candidates is False:
            return self._plate_calibration_fail_preflight(
                "calibration_history_invalid",
                "Existing calibration history could not be verified.",
            )
        candidate = copy.deepcopy((promotion_candidates or {}).get(target_key))
        return {
            "allowed": True,
            "reason_code": "ready",
            "message": "Plate calibration entry is ready.",
            "state": "idle",
            "machine_uuid": paths.machine_uuid,
            "trust_epoch": readiness.get("trust_epoch"),
            "plate_name": plate_name,
            "target_key": target_key,
            "target_state": target_state,
            "verified": target_state in CURRENT_VERIFIED_STATES,
            "historical_candidate": candidate,
            "initial_calibrations": normalized,
            "initial_value_sha256": value_sha256,
        }

    def _plate_calibration_session_invariants(self, session):
        paths = getattr(self, "machine_data_paths", None)
        if getattr(paths, "machine_uuid", None) != session.get("machine_uuid"):
            return False, "authorized_machine_changed"
        telemetry = self._position_reconciliation_snapshot()
        if not isinstance(telemetry, dict):
            return False, "position_telemetry_unavailable"
        if telemetry.get("trust_epoch") != session.get("trust_epoch"):
            return False, "motion_trust_epoch_changed"
        plate = getattr(self.model, "well_plate", None)
        try:
            if str(plate.get_current_plate_name()).strip() != session.get("plate_name"):
                return False, "active_plate_changed"
            calibrations = {
                point_name: {
                    axis: int(plate.get_all_current_plate_calibrations()[point_name][axis])
                    for axis in self._position_axes()
                }
                for point_name in self._plate_calibration_points()
            }
        except Exception:
            return False, "active_plate_configuration_invalid"
        if canonical_value_sha256(calibrations) != session.get("initial_value_sha256"):
            return False, "active_plate_coordinates_changed"
        return True, ""

    def begin_plate_calibration_entry(self, *, manual_first):
        """Queue a safe-height plate entry and return its transient session token."""

        preflight = self.plate_calibration_entry_preflight()
        if not preflight.get("allowed"):
            self.error_occurred_signal.emit(
                "Plate Calibration Not Started", preflight.get("message", "Preflight failed.")
            )
            return False
        manual_first = bool(manual_first)
        if preflight["verified"] and manual_first:
            self.error_occurred_signal.emit(
                "Plate Calibration Not Started",
                "A verified plate must use its verified automatic first-corner approach.",
            )
            return False
        if not preflight["verified"] and not manual_first:
            self.error_occurred_signal.emit(
                "Plate Calibration Not Started",
                "An unverified plate may only be calibrated from safe height.",
            )
            return False

        token = str(uuid.uuid4())
        top_left = copy.deepcopy(preflight["initial_calibrations"]["top_left"])
        endpoint = {
            "X": top_left["X"],
            "Y": top_left["Y"],
            "Z": PLATE_DOCK_SAFE_Z if manual_first else top_left["Z"],
        }
        self._plate_calibration_session = {
            "session_token": token,
            "state": "staging",
            "phase": "entry",
            "machine_uuid": preflight["machine_uuid"],
            "trust_epoch": preflight["trust_epoch"],
            "plate_name": preflight["plate_name"],
            "target_key": preflight["target_key"],
            "target_state": preflight["target_state"],
            "manual_first": manual_first,
            "initial_calibrations": copy.deepcopy(preflight["initial_calibrations"]),
            "initial_value_sha256": preflight["initial_value_sha256"],
            "captured_points": {},
            "next_point_index": 0,
            "expected_point": "top_left",
            "expected_endpoint": endpoint,
            "failure_reason": None,
            "awaiting_queue_drain": False,
            "reconciliation_started_monotonic": None,
        }
        self._emit_plate_calibration_state()

        approach_x = top_left["X"] + PLATE_DOCK_X_OFFSET
        with self._plate_calibration_motion_scope(token):
            if self.set_absolute_Z(PLATE_DOCK_SAFE_Z, override=False) is False:
                return self._fail_plate_calibration_session("safe_z_rejected")
            if self.set_absolute_coordinates(
                approach_x, top_left["Y"], PLATE_DOCK_SAFE_Z, override=False
            ) is False:
                return self._fail_plate_calibration_session("plate_dogleg_rejected")

            if manual_first:
                queued = self.set_absolute_coordinates(
                    top_left["X"],
                    top_left["Y"],
                    PLATE_DOCK_SAFE_Z,
                    override=False,
                    handler=lambda token=token: self._plate_calibration_motion_completed(token),
                )
            else:
                if self.set_absolute_coordinates(
                    top_left["X"], top_left["Y"], PLATE_DOCK_SAFE_Z, override=False
                ) is False:
                    return self._fail_plate_calibration_session("plate_seated_safe_rejected")
                queued = self.set_absolute_Z(
                    top_left["Z"],
                    override=True,
                    handler=lambda token=token: self._plate_calibration_motion_completed(token),
                )
        if queued is False:
            return self._fail_plate_calibration_session("plate_entry_endpoint_rejected")
        self._plate_calibration_session["expected_endpoint"] = copy.deepcopy(
            self.expected_position
        )
        return self._plate_calibration_session_snapshot()

    def _plate_calibration_motion_completed(self, session_token):
        session = self._plate_calibration_active_session(session_token)
        if session is None or session.get("state") != "staging":
            return False
        self._set_plate_calibration_state(
            "reconciling",
            awaiting_queue_drain=True,
            reconciliation_started_monotonic=None,
        )
        timeout_ms = self._position_reconciliation_timeout_ms()
        QtCore.QTimer.singleShot(
            timeout_ms + 25,
            lambda token=session_token: self._plate_calibration_timeout_check(token),
        )
        return True

    def _plate_calibration_timeout_check(self, session_token):
        session = self._plate_calibration_active_session(session_token)
        if session is None or session.get("state") != "reconciling":
            return
        self._advance_plate_calibration_session()

    def _advance_plate_calibration_session(self, *, now_monotonic=None):
        session = self._plate_calibration_active_session()
        if session is None or session.get("state") != "reconciling":
            return self._plate_calibration_session_snapshot()
        if session.get("awaiting_queue_drain"):
            return self._plate_calibration_session_snapshot()

        valid, reason = self._plate_calibration_session_invariants(session)
        if not valid:
            self._fail_plate_calibration_session(reason)
            return self._plate_calibration_session_snapshot()
        reconciliation = self._advance_position_reconciliation(
            now_monotonic=now_monotonic
        )
        state = reconciliation.get("state")
        if state == "pending":
            return self._plate_calibration_session_snapshot()
        if state == "timed_out":
            self._fail_plate_calibration_session("position_reconciliation_timeout")
            return self._plate_calibration_session_snapshot()
        if state == "trust_changed":
            self._fail_plate_calibration_session("position_reconciliation_trust_changed")
            return self._plate_calibration_session_snapshot()
        if state != "settled":
            self._fail_plate_calibration_session("expected_position_mismatch")
            return self._plate_calibration_session_snapshot()
        if reconciliation.get("expected_position") != session.get("expected_endpoint"):
            self._fail_plate_calibration_session("stale_motion_completion")
            return self._plate_calibration_session_snapshot()

        readiness = self._configuration_capture_readiness()
        if not readiness.get("ready"):
            reasons = readiness.get("reason_codes") or ["position_not_ready"]
            if "position_reconciliation_pending" in reasons:
                return self._plate_calibration_session_snapshot()
            self._fail_plate_calibration_session(";".join(reasons))
            return self._plate_calibration_session_snapshot()
        if readiness.get("captured_position") != session.get("expected_endpoint"):
            self._fail_plate_calibration_session("expected_position_mismatch")
            return self._plate_calibration_session_snapshot()

        phase = session.get("phase")
        if phase == "entry":
            self.expected_location = "plate"
            self.update_location_handler(name="plate")
            ready_state = "manual_first_point" if session.get("manual_first") else "automatic_points"
        elif phase in {"point", "jog"}:
            ready_state = str(session.get("resume_state") or "automatic_points")
        elif phase == "final_lift":
            ready_state = "complete"
        else:
            self._fail_plate_calibration_session("invalid_calibration_phase")
            return self._plate_calibration_session_snapshot()
        return self._set_plate_calibration_state(
            ready_state,
            awaiting_queue_drain=False,
            reconciliation_started_monotonic=None,
        )

    def _require_plate_calibration_ready_session(self, session_token):
        session = self._plate_calibration_active_session(session_token)
        if session is None:
            return None
        if session.get("state") not in {"manual_first_point", "automatic_points"}:
            return None
        valid, reason = self._plate_calibration_session_invariants(session)
        if not valid:
            self._fail_plate_calibration_session(reason)
            return None
        if not self.check_if_all_completed() or bool(self.model.machine_model.is_busy()):
            return None
        return session

    def jog_plate_calibration(self, session_token, x=0, y=0, z=0):
        """Queue one session-bound manual jog and require telemetry reconciliation."""

        session = self._require_plate_calibration_ready_session(session_token)
        deltas = {"X": int(x), "Y": int(y), "Z": int(z)}
        if session is None or sum(value != 0 for value in deltas.values()) != 1:
            return False
        resume_state = session["state"]
        self._set_plate_calibration_state(
            "staging", phase="jog", resume_state=resume_state
        )
        with self._plate_calibration_motion_scope(session_token):
            queued = self.set_relative_coordinates(
                deltas["X"],
                deltas["Y"],
                deltas["Z"],
                manual=True,
                override=True,
                handler=lambda token=session_token: self._plate_calibration_motion_completed(token),
            )
        if queued is False:
            return self._fail_plate_calibration_session("manual_jog_rejected")
        session["expected_endpoint"] = copy.deepcopy(self.expected_position)
        return True

    def _predicted_plate_calibration_point(self, session, point_name):
        initial = session["initial_calibrations"]
        captures = session["captured_points"]
        if point_name not in initial or not captures:
            return None
        totals = {axis: 0 for axis in self._position_axes()}
        for captured_name, captured in captures.items():
            for axis in self._position_axes():
                totals[axis] += int(captured[axis]) - int(initial[captured_name][axis])
        count = len(captures)
        return {
            axis: int(initial[point_name][axis]) + int(totals[axis] / count)
            for axis in self._position_axes()
        }

    def capture_and_advance_plate_calibration(self, session_token, point_name):
        """Capture the current corner and safely approach the next one."""

        session = self._require_plate_calibration_ready_session(session_token)
        point_name = str(point_name or "")
        points = self._plate_calibration_points()
        if session is None or session.get("expected_point") != point_name:
            return False
        point_index = int(session.get("next_point_index", 0))
        if point_index >= len(points) or points[point_index] != point_name:
            return False

        captured = self.capture_configuration_point(
            point_name, workflow="plate_calibration"
        )
        if captured is False:
            return False
        captured = {
            axis: int(captured[axis]) for axis in self._position_axes()
        }
        session["captured_points"][point_name] = copy.deepcopy(captured)
        self.model.well_plate.set_calibration_position(point_name, captured)

        next_index = point_index + 1
        if next_index < len(points):
            next_name = points[next_index]
            target = self._predicted_plate_calibration_point(session, next_name)
            if target is None:
                return self._fail_plate_calibration_session("next_corner_unavailable")
            traverse_z = min(int(captured["Z"]) - 500, int(target["Z"]) - 500)
            endpoint = copy.deepcopy(target)
            self._set_plate_calibration_state(
                "staging",
                phase="point",
                resume_state="automatic_points",
                expected_point=next_name,
                next_point_index=next_index,
                expected_endpoint=endpoint,
            )
            with self._plate_calibration_motion_scope(session_token):
                if self.set_absolute_Z(traverse_z, override=True) is False:
                    return self._fail_plate_calibration_session("corner_lift_rejected")
                if self.set_absolute_XY(target["X"], target["Y"], override=True) is False:
                    return self._fail_plate_calibration_session("corner_xy_rejected")
                if self.set_absolute_Z(
                    target["Z"],
                    override=True,
                    handler=lambda token=session_token: self._plate_calibration_motion_completed(token),
                ) is False:
                    return self._fail_plate_calibration_session("corner_descent_rejected")
            session["expected_endpoint"] = copy.deepcopy(self.expected_position)
            return True

        lift_z = int(captured["Z"]) - 500
        self._set_plate_calibration_state(
            "staging",
            phase="final_lift",
            next_point_index=len(points),
            expected_point=None,
            expected_endpoint={
                "X": captured["X"], "Y": captured["Y"], "Z": lift_z
            },
        )
        with self._plate_calibration_motion_scope(session_token):
            if self.set_absolute_Z(
                lift_z,
                override=True,
                handler=lambda token=session_token: self._plate_calibration_motion_completed(token),
            ) is False:
                return self._fail_plate_calibration_session("final_lift_rejected")
        session["expected_endpoint"] = copy.deepcopy(self.expected_position)
        return True

    def move_plate_calibration_to_captured_point(self, session_token, point_name):
        """Safely revisit an already captured corner within the active session."""

        session = self._require_plate_calibration_ready_session(session_token)
        point_name = str(point_name or "")
        target = copy.deepcopy((session or {}).get("captured_points", {}).get(point_name))
        if session is None or target is None:
            return False
        current = self.model.machine_model.get_current_position_dict_capital()
        traverse_z = min(int(current["Z"]) - 500, int(target["Z"]) - 500)
        point_index = self._plate_calibration_points().index(point_name)
        for obsolete_name in self._plate_calibration_points()[point_index:]:
            session["captured_points"].pop(obsolete_name, None)
            try:
                self.model.well_plate.temp_calibration_data.pop(
                    obsolete_name, None
                )
            except Exception:
                pass
            self._configuration_capture_evidence.pop(
                ("plate_calibration", obsolete_name), None
            )
        self._set_plate_calibration_state(
            "staging",
            phase="point",
            resume_state="automatic_points" if point_index else (
                "manual_first_point" if session.get("manual_first") else "automatic_points"
            ),
            expected_point=point_name,
            next_point_index=point_index,
            expected_endpoint=copy.deepcopy(target),
        )
        with self._plate_calibration_motion_scope(session_token):
            if self.set_absolute_Z(traverse_z, override=True) is False:
                return self._fail_plate_calibration_session("corner_lift_rejected")
            if self.set_absolute_XY(target["X"], target["Y"], override=True) is False:
                return self._fail_plate_calibration_session("corner_xy_rejected")
            if self.set_absolute_Z(
                target["Z"],
                override=True,
                handler=lambda token=session_token: self._plate_calibration_motion_completed(token),
            ) is False:
                return self._fail_plate_calibration_session("corner_descent_rejected")
        session["expected_endpoint"] = copy.deepcopy(self.expected_position)
        return True

    def finish_plate_calibration_session(self, session_token, *, accepted):
        session = getattr(self, "_plate_calibration_session", None)
        if not isinstance(session, dict) or session.get("session_token") != session_token:
            return False
        if accepted and session.get("state") != "complete":
            return False
        if not accepted:
            try:
                self.model.well_plate.discard_temp_calibrations()
            except Exception:
                pass
            self.discard_configuration_capture_evidence("plate_calibration")
            if session.get("state") != "failed":
                self._set_plate_calibration_state(
                    "cancelled", failure_reason="operator_cancelled"
                )
        snapshot = self._plate_calibration_session_snapshot()
        self._plate_calibration_session = None
        self._emit_optional(
            "plate_calibration_state_changed",
            {**snapshot, "state": snapshot["state"]},
        )
        return True

    def cancel_plate_calibration_entry(self, session_token):
        """Cancel an idle calibration dialog without interrupting active motion."""

        session = self._plate_calibration_active_session(session_token)
        if session is None or session.get("state") in {"staging", "reconciling"}:
            return False
        return self.finish_plate_calibration_session(
            session_token, accepted=False
        )

    def capture_configuration_point(self, target_key, *, workflow):
        """Capture one calibration point only from trusted, fresh machine state."""

        target_key = str(target_key or "").strip()
        workflow = str(workflow or "").strip()
        evidence = self._configuration_capture_readiness()
        if not evidence.get("ready"):
            reason_codes = evidence["reason_codes"]
            message = "Position capture is not safe: " + ", ".join(reason_codes)
            if "position_reconciliation_pending" in reason_codes:
                message += ". Final position telemetry is still settling; wait briefly and retry."
            self.error_occurred_signal.emit("Position Not Captured", message)
            self.record_configuration_attempt(
                event_type="rejected",
                operator=getattr(getattr(self, "configuration_transactions", None), "os_account", "application operator"),
                reason=message,
                workflow=workflow,
                details={"target_key": target_key, "stage": "capture", "preconditions": evidence},
            )
            return False
        point = copy.deepcopy(evidence.get("captured_position") or self.model.machine_model.get_current_position_dict_capital())
        evidence["workflow"] = workflow
        evidence["target_key"] = target_key
        self._configuration_capture_evidence[(workflow, target_key)] = copy.deepcopy(evidence)
        return point

    def discard_configuration_capture_evidence(self, workflow):
        workflow = str(workflow or "")
        self._configuration_capture_evidence = {
            key: value
            for key, value in self._configuration_capture_evidence.items()
            if key[0] != workflow
        }

    def _governed_proposal_inputs(self):
        service = getattr(self, "configuration_transactions", None)
        guard = getattr(self, "configuration_safety_guard", None)
        if service is None or guard is None:
            return None, None, None
        state = service.refresh(allow_pending=False)
        documents = read_governed_documents(service.paths)
        return guard, documents, dict(state.config_sha256)

    def _capture_bundle(self, workflow, target_keys):
        evidence = []
        for key in target_keys:
            item = self._configuration_capture_evidence.get((workflow, key))
            if item is None:
                raise ConfigurationSafetyError(f"Fresh capture evidence is missing for {key}.")
            evidence.append(copy.deepcopy(item))
        machine_uuids = {item.get("machine_uuid") for item in evidence}
        trust_epochs = {item.get("trust_epoch") for item in evidence}
        if len(machine_uuids) != 1 or None in machine_uuids:
            raise ConfigurationSafetyError("Captured points do not share one authorized machine UUID.")
        if len(trust_epochs) != 1 or None in trust_epochs:
            raise ConfigurationSafetyError("Captured points do not share one motion trust epoch.")
        return evidence

    def _prepare_guarded_proposal(
        self,
        proposed,
        *,
        workflow,
        target_keys,
        captures,
        restore_precondition=None,
    ):
        guard, before, raw_hashes = self._governed_proposal_inputs()
        if guard is None:
            return None
        profile = before["Settings.json"].get("HARDWARE_PROFILE", self.profile.name)
        preconditions = {"captures": copy.deepcopy(captures)}
        if restore_precondition is not None:
            preconditions["restore"] = copy.deepcopy(restore_precondition)
        try:
            assessment = guard.assess(
                before_documents=before,
                proposed_documents=proposed,
                workflow=workflow,
                target_keys=target_keys,
                hardware_profile=profile,
                preconditions=preconditions,
                governed_file_sha256=raw_hashes,
            )
        except ConfigurationSafetyError as exc:
            self.error_occurred_signal.emit("Configuration Change Rejected", str(exc))
            return False
        return {
            "documents": copy.deepcopy(proposed),
            "assessment": assessment,
            "expected_config_sha256": raw_hashes,
        }

    def prepare_named_location_change(self, name, *, require_existing=False):
        name = str(name or "").strip()
        guard = getattr(self, "configuration_safety_guard", None)
        if guard is None:
            return None
        existing = self.model.location_model.get_all_locations()
        if not name or (require_existing and name not in existing):
            self.error_occurred_signal.emit("Configuration Change Failed", "The selected location is invalid.")
            return False
        workflow = "named_location_modify" if require_existing else "named_location_add"
        point = self.capture_configuration_point(name, workflow=workflow)
        if point is False:
            return False
        proposed_locations = copy.deepcopy(existing)
        proposed_locations[name] = point
        captures = self._capture_bundle(workflow, (name,))
        return self._prepare_guarded_proposal(
            {"Locations.json": proposed_locations},
            workflow=workflow,
            target_keys=(name,),
            captures=captures,
        )

    def prepare_rack_calibration_change(self):
        workflow = "rack_calibration"
        keys = ("rack_position_Left", "rack_position_Right")
        temporary = copy.deepcopy(self.model.rack_model.temp_calibration_data)
        try:
            captures = self._capture_bundle(workflow, keys)
        except ConfigurationSafetyError as exc:
            self.error_occurred_signal.emit("Rack Calibration Not Saved", str(exc))
            return False
        proposed = copy.deepcopy(self.model.location_model.get_all_locations())
        proposed.update(temporary)
        return self._prepare_guarded_proposal(
            {"Locations.json": proposed}, workflow=workflow, target_keys=keys, captures=captures
        )

    def prepare_plate_calibration_change(self):
        workflow = "plate_calibration"
        keys = ("top_left", "top_right", "bottom_right", "bottom_left")
        try:
            captures = self._capture_bundle(workflow, keys)
            proposed = self.model.well_plate.proposed_calibration_document()
        except Exception as exc:
            self.error_occurred_signal.emit("Plate Calibration Not Saved", str(exc))
            return False
        return self._prepare_guarded_proposal(
            {"Plates.json": proposed},
            workflow=workflow,
            target_keys=(self.model.well_plate.get_current_plate_name(),),
            captures=captures,
        )

    def prepare_configuration_import(self, selected_files):
        service = getattr(self, "configuration_transactions", None)
        guard = getattr(self, "configuration_safety_guard", None)
        if service is None or guard is None:
            return None
        proposed = {}
        try:
            for filename, source_path in selected_files.items():
                if filename not in {"Locations.json", "Plates.json", "RegulatorProfiles.json"}:
                    raise ConfigurationSafetyError(f"Unsupported import target {filename!r}.")
                with open(source_path, "r", encoding="utf-8") as source:
                    proposed[filename] = json.load(source)
        except (OSError, json.JSONDecodeError, ConfigurationSafetyError) as exc:
            self.error_occurred_signal.emit("Configuration Import Failed", str(exc))
            return False
        if not set(proposed).intersection({"Locations.json", "Plates.json"}):
            return None
        prepared = self._prepare_guarded_proposal(
            proposed,
            workflow="governed_configuration_import",
            target_keys=tuple(sorted(proposed)),
            captures=[],
        )
        if prepared:
            prepared["operation"] = "import"
        return prepared

    def prepare_configuration_restore(self, transaction_id, *, machine_id_confirmation):
        service = getattr(self, "configuration_transactions", None)
        guard = getattr(self, "configuration_safety_guard", None)
        if service is None or guard is None:
            return None
        if machine_id_confirmation != service.identity.machine_id:
            self.error_occurred_signal.emit("Configuration Restore Failed", "Exact machine ID confirmation is required.")
            return False
        try:
            proposed, restore_precondition = service.read_restore_preview(transaction_id)
        except ConfigurationTransactionError as exc:
            self.error_occurred_signal.emit("Configuration Restore Failed", str(exc))
            return False
        if not set(proposed).intersection({"Locations.json", "Plates.json"}):
            return None
        prepared = self._prepare_guarded_proposal(
            proposed,
            workflow="configuration_restore",
            target_keys=tuple(sorted(proposed)),
            captures=[],
            restore_precondition=restore_precondition,
        )
        if prepared:
            prepared.update(
                operation="restore",
                transaction_id=str(transaction_id),
                machine_id_confirmation=str(machine_id_confirmation),
            )
        return prepared

    def _validate_guard_confirmation(self, assessment, confirmation):
        parsed = parse_guard_assessment(assessment)
        if parsed["result"] == "reject":
            raise ConfigurationSafetyError("Rejected guard assessment cannot be saved.")
        if not isinstance(confirmation, dict) or confirmation.get("proposal_sha256") != parsed["proposal_sha256"]:
            raise ConfigurationSafetyError("Confirmation is missing or belongs to another proposal.")
        if confirmation.get("acknowledged") is not True:
            raise ConfigurationSafetyError("The displayed coordinate deltas were not acknowledged.")
        if parsed.get("schema_version") == 2 and confirmation.get(
            "acknowledgement_version"
        ) != parsed.get("confirmation_version"):
            raise ConfigurationSafetyError(
                "The acknowledgement belongs to a different confirmation policy."
            )
        return parsed

    def commit_guarded_configuration_proposal(self, proposal, *, operator, reason, confirmation):
        if not isinstance(proposal, dict):
            return False
        try:
            assessment = self._validate_guard_confirmation(proposal.get("assessment"), confirmation)
            captures = assessment.get("preconditions", {}).get("captures", [])
            if captures:
                readiness = self._configuration_capture_readiness()
                if not readiness.get("ready"):
                    raise ConfigurationSafetyError(
                        "Machine state changed after preview: " + ", ".join(readiness["reason_codes"])
                    )
                current_epoch = readiness.get("trust_epoch")
                if any(item.get("trust_epoch") != current_epoch for item in captures):
                    raise ConfigurationSafetyError("Motion trust epoch changed after capture.")
                if assessment["workflow"].startswith("named_location"):
                    captured = captures[0]["captured_position"]
                    if readiness.get("captured_position") != captured:
                        raise ConfigurationSafetyError("Current position changed after the named-location preview.")
        except (ConfigurationSafetyError, TypeError, KeyError, IndexError) as exc:
            self.error_occurred_signal.emit("Configuration Change Not Saved", str(exc))
            return False
        if proposal.get("operation") == "restore":
            try:
                result = self.configuration_transactions.restore_transaction(
                    proposal["transaction_id"],
                    operator=operator,
                    reason=reason,
                    machine_id_confirmation=proposal["machine_id_confirmation"],
                    expected_config_sha256=proposal["expected_config_sha256"],
                    guard_evidence=assessment,
                )
            except ConfigurationTransactionError as exc:
                if isinstance(exc, ConfigurationRecoveryRequired):
                    self._configuration_recovery_required = True
                self.error_occurred_signal.emit("Configuration Restore Failed", str(exc))
                return False
            result = result if self._install_committed_configuration(result) else False
        else:
            result = self._commit_configuration_documents(
                proposal["documents"],
                operator=operator,
                reason=reason,
                workflow=assessment["workflow"],
                event_type="import" if proposal.get("operation") == "import" else "change",
                expected_config_sha256=proposal["expected_config_sha256"],
                guard_evidence=assessment,
            )
        if result:
            self.discard_configuration_capture_evidence(assessment["workflow"])
        return result

    def _commit_configuration_documents(
        self,
        proposed,
        *,
        operator,
        reason,
        workflow,
        event_type="change",
        restore_reference=None,
        expected_config_sha256=None,
        guard_evidence=None,
    ):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return None
        try:
            result = service.commit_documents(
                proposed,
                operator=operator,
                reason=reason,
                workflow=workflow,
                event_type=event_type,
                restore_reference=restore_reference,
                expected_config_sha256=expected_config_sha256,
                guard_evidence=guard_evidence,
            )
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit("Configuration Change Failed", str(exc))
            return False
        if not self._install_committed_configuration(result):
            return False
        return result

    def commit_named_location(self, name, *, operator, reason, require_existing=False):
        """Persist one complete Locations snapshot before changing Model memory."""

        name = str(name or "").strip()
        if not name:
            self.error_occurred_signal.emit("Configuration Change Failed", "A location name is required.")
            return False
        existing = self.model.location_model.get_all_locations()
        if require_existing and name not in existing:
            self.error_occurred_signal.emit("Configuration Change Failed", f"Location {name!r} does not exist.")
            return False
        try:
            x, y, z = self.model.machine_model.get_current_position()
            proposed = copy.deepcopy(existing)
            proposed[name] = {"X": int(x), "Y": int(y), "Z": int(z)}
        except Exception as exc:
            self.error_occurred_signal.emit("Configuration Change Failed", f"Current position is invalid: {exc}")
            return False
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            if require_existing:
                self.model.location_model.update_location(name, x, y, z)
            else:
                self.model.location_model.add_location(name, x, y, z)
            self.model.location_model.save_locations()
            return True
        return self._commit_configuration_documents(
            {"Locations.json": proposed},
            operator=operator,
            reason=reason,
            workflow="named_location_modify" if require_existing else "named_location_add",
        )

    def add_new_location(self, name, *, operator=None, reason=None):
        """Compatibility adapter; canonical production still uses one transaction."""

        service = getattr(self, "configuration_transactions", None)
        actor = operator or getattr(service, "os_account", None) or "application operator"
        return self.commit_named_location(
            name,
            operator=actor,
            reason=reason or "Save current position as named location",
            require_existing=False,
        )

    def modify_location(self, name, *, operator=None, reason=None):
        """Compatibility adapter for one transactional location modification."""

        service = getattr(self, "configuration_transactions", None)
        actor = operator or getattr(service, "os_account", None) or "application operator"
        return self.commit_named_location(
            name,
            operator=actor,
            reason=reason or "Update named location from current position",
            require_existing=True,
        )

    # def update_current_location(self, name):
    #     """Update the current location to the specified name."""
    #     self.model.machine_model.update_current_location(name)
    
    def print_locations(self):
        """Print the saved locations."""
        print(self.model.location_model.get_all_locations())

    def save_locations(self):
        """Save the locations to a file."""
        if getattr(self, "configuration_transactions", None) is not None:
            raise ConfigurationValidationError(
                "Canonical locations must be committed through the transaction service."
            )
        self.model.location_model.save_locations()

    def commit_rack_calibration(self, *, operator, reason):
        temporary = copy.deepcopy(self.model.rack_model.temp_calibration_data)
        required = {"rack_position_Left", "rack_position_Right"}
        if set(temporary) != required:
            self.error_occurred_signal.emit(
                "Rack Calibration Not Saved", "Both Left and Right rack anchors are required."
            )
            return False
        proposed = copy.deepcopy(self.model.location_model.get_all_locations())
        proposed.update(temporary)
        result = self._commit_configuration_documents(
            {"Locations.json": proposed},
            operator=operator,
            reason=reason,
            workflow="rack_calibration",
        )
        if result:
            self.model.rack_model.discard_temp_calibrations()
        return result

    def commit_plate_calibration(self, *, operator, reason):
        try:
            proposed = self.model.well_plate.proposed_calibration_document()
        except Exception as exc:
            self.error_occurred_signal.emit("Plate Calibration Not Saved", str(exc))
            return False
        result = self._commit_configuration_documents(
            {"Plates.json": proposed},
            operator=operator,
            reason=reason,
            workflow="plate_calibration",
        )
        if result:
            self.model.well_plate.discard_temp_calibrations()
        return result

    def record_configuration_attempt(self, *, event_type, operator, reason, workflow, details=None):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return None
        try:
            return service.record_attempt(
                event_type=event_type,
                operator=operator,
                reason=reason,
                workflow=workflow,
                details=details,
            )
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit("Configuration Audit Failed", str(exc))
            return False

    def verify_configuration_targets(self, confirmations, *, operator, reason, method="physical_check", service_record_reference=None):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return False
        try:
            guard = getattr(self, "configuration_safety_guard", None)
            if guard is not None:
                guard.validate_active_documents(read_governed_documents(service.paths))
            result = service.verify_targets(
                confirmations,
                operator=operator,
                reason=reason,
                method=method,
                service_record_reference=service_record_reference,
            )
            self.saved_target_authorizer = service.saved_target_authorizer
            return result
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit("Configuration Verification Failed", str(exc))
            return False

    def controlled_calibration_promotion_candidates(self):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return {}
        try:
            guard = getattr(self, "configuration_safety_guard", None)
            if guard is not None:
                guard.validate_active_documents(read_governed_documents(service.paths))
            return service.controlled_calibration_promotion_candidates()
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit(
                "Calibration Evidence Verification Failed", str(exc)
            )
            return False

    def promote_controlled_calibration(
        self, target_key, source_event_id, *, operator, reason
    ):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return False
        try:
            guard = getattr(self, "configuration_safety_guard", None)
            if guard is not None:
                guard.validate_active_documents(read_governed_documents(service.paths))
            result = service.promote_controlled_calibration(
                target_key,
                source_event_id,
                operator=operator,
                reason=reason,
            )
            self.saved_target_authorizer = service.saved_target_authorizer
            return result
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit(
                "Calibration Evidence Verification Failed", str(exc)
            )
            return False

    def import_configuration_files(self, selected_files, *, operator, reason):
        """Import an explicit governed-file mapping and refresh runtime state."""

        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return False
        supported = {"Locations.json", "Plates.json", "RegulatorProfiles.json"}
        unsupported = sorted(set(selected_files).difference(supported))
        if unsupported:
            self.error_occurred_signal.emit(
                "Configuration Import Failed",
                "This running application cannot safely install imported "
                f"{', '.join(unsupported)}. Use a reviewed offline migration workflow.",
            )
            return False
        try:
            guard = getattr(self, "configuration_safety_guard", None)
            if guard is not None and set(selected_files).intersection({"Locations.json", "Plates.json"}):
                complete = read_governed_documents(service.paths)
                for filename, source_path in selected_files.items():
                    with open(source_path, "r", encoding="utf-8") as source:
                        complete[filename] = json.load(source)
                guard.validate_active_documents(complete)
            result = service.import_files(
                selected_files,
                operator=operator,
                reason=reason,
            )
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit("Configuration Import Failed", str(exc))
            return False
        if not self._install_committed_configuration(result):
            return False
        return result

    def restore_configuration_transaction(self, transaction_id, *, operator, reason, machine_id_confirmation):
        service = getattr(self, "configuration_transactions", None)
        if service is None:
            return False
        try:
            result = service.restore_transaction(
                transaction_id,
                operator=operator,
                reason=reason,
                machine_id_confirmation=machine_id_confirmation,
            )
        except ConfigurationTransactionError as exc:
            if isinstance(exc, ConfigurationRecoveryRequired):
                self._configuration_recovery_required = True
            self.error_occurred_signal.emit("Configuration Restore Failed", str(exc))
            return False
        if not self._install_committed_configuration(result):
            return False
        return result

    def home_complete_handler(self):
        """Handle the home complete signal."""
        self.model.machine_model.handle_home_complete()
        self.update_expected_position(x=500, y=500, z=500)
        try:
            self.expected_location = self.model.machine_model.get_current_location()
        except Exception:
            self.expected_location = "Home"

    def update_expected_position(self, x=None, y=None, z=None):
        """Update the expected position after a move."""
        if x is not None:
            self.expected_position['X'] = x
        if y is not None:
            self.expected_position['Y'] = y
        if z is not None:
            self.expected_position['Z'] = z

    def update_expected_with_current(self):
        """Update the expected position with the current position."""
        self.expected_position = self.model.machine_model.get_current_position_dict()
        self._pending_motion_endpoint_evidence = None
        try:
            self.expected_location = self.model.machine_model.get_current_location()
        except Exception:
            self.expected_location = None

        self._settle_position_reconciliation(reason="explicit_current_resync")

        # resync rack expected state when queue drains
        try:
            self.model.rack_model.sync_expected_to_actual()
        except Exception:
            pass
    
    def update_location_handler(self,name=None):
        """Update the current location."""
        # self.model.machine_model.update_current_location(name)
        self.model.location_model.update_current_location(name)

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        return self.machine.check_if_all_completed()

    def _saved_target_authorization_request(
        self,
        *,
        name,
        original_target,
        final_target,
        x_offset,
        z_offset,
        manual,
        override,
        ignore_safe_height,
    ):
        authorizer = getattr(self, "saved_target_authorizer", None)
        paths = getattr(self, "machine_data_paths", None)
        if authorizer is None or paths is None:
            return None
        normalized = str(name or "").strip().casefold()
        target_key = f"location:{normalized}"
        target_kind = "location"
        base_value = dict(original_target)
        if normalized.startswith("slot-"):
            calibrations = getattr(self.model.rack_model, "calibrations", {})
            left = calibrations.get("rack_position_Left")
            right = calibrations.get("rack_position_Right")
            if not isinstance(left, dict) or not isinstance(right, dict):
                return SavedTargetAuthorizationRequest(
                    paths.machine_uuid,
                    "rack:primary",
                    "rack",
                    {},
                    dict(final_target),
                    "rack_slot_move",
                    {},
                    manual,
                    override,
                    ignore_safe_height,
                )
            target_key = "rack:primary"
            target_kind = "rack"
            base_value = {"Left": dict(left), "Right": dict(right)}
        elif normalized == "plate":
            plate = getattr(self.model, "well_plate", None)
            get_name = getattr(plate, "get_current_plate_name", None)
            get_calibrations = getattr(plate, "get_all_current_plate_calibrations", None)
            if callable(get_name) and callable(get_calibrations):
                target_key = f"plate:{str(get_name()).casefold()}"
                target_kind = "plate"
                base_value = dict(get_calibrations() or {})
        return SavedTargetAuthorizationRequest(
            machine_uuid=paths.machine_uuid,
            target_key=target_key,
            target_kind=target_kind,
            base_value=base_value,
            final_coordinates=dict(final_target),
            workflow="move_to_location",
            offsets={"X": int(x_offset), "Y": 0, "Z": int(z_offset)},
            manual=bool(manual),
            override=bool(override),
            ignore_safe_height=bool(ignore_safe_height),
        )

    def _authorize_saved_target(self, **kwargs):
        authorizer = getattr(self, "saved_target_authorizer", None)
        request = self._saved_target_authorization_request(**kwargs)
        if request is None:
            return True
        decision = authorizer.authorize(request)
        if decision.allowed:
            return True
        self.error_occurred_signal.emit("Move Blocked", decision.message)
        print(
            f"Move blocked by saved-target verification: "
            f"{decision.reason_code}: {decision.message}"
        )
        return False

    def _authorize_active_plate_derived_target(self, final_target, workflow):
        authorizer = getattr(self, "saved_target_authorizer", None)
        paths = getattr(self, "machine_data_paths", None)
        if authorizer is None or paths is None:
            return True
        plate = getattr(self.model, "well_plate", None)
        get_name = getattr(plate, "get_current_plate_name", None)
        get_calibrations = getattr(plate, "get_all_current_plate_calibrations", None)
        if not callable(get_name) or not callable(get_calibrations):
            self.error_occurred_signal.emit(
                "Move Blocked", "Active plate calibration evidence is unavailable."
            )
            return False
        request = SavedTargetAuthorizationRequest(
            machine_uuid=paths.machine_uuid,
            target_key=f"plate:{str(get_name()).casefold()}",
            target_kind="plate",
            base_value=dict(get_calibrations() or {}),
            final_coordinates=dict(final_target),
            workflow=str(workflow),
            offsets={},
            manual=False,
            override=True,
            ignore_safe_height=False,
        )
        decision = authorizer.authorize(request)
        if decision.allowed:
            return True
        self.error_occurred_signal.emit("Move Blocked", decision.message)
        print(
            f"Plate-derived move blocked by verification: "
            f"{decision.reason_code}: {decision.message}"
        )
        return False

    def move_to_location(self, name, direct=True, safe_y=False, x_offset: int = 0,z_offset: int = 0,manual=False,coords=None,override=False,ignore_safe_height=False,on_complete=None):
        """Move to the saved location."""
        if self.profile.name != "legacy":
            safe_z = 35000
        else:
            safe_z = 5000
        current_location = str(getattr(self, "expected_location", None) or "")
        current_location_norm = current_location.strip().lower()
        target_name_norm = str(name or "").strip().lower()

        if coords is not None:
            original_target = coords
        elif target_name_norm == "plate":
            # Treat "plate" as the active plate anchor first, with the legacy
            # persisted waypoint preserved as a fallback for uncalibrated plates.
            original_target = None
            well_plate = getattr(self.model, "well_plate", None)
            if well_plate is not None:
                get_plate_reference_coords = getattr(well_plate, "get_plate_reference_coords", None)
                if callable(get_plate_reference_coords):
                    original_target = get_plate_reference_coords()
            if original_target is None:
                original_target = self.model.location_model.get_location_dict(name)
        else:
            original_target = self.model.location_model.get_location_dict(name)

        if original_target is None:
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' not found")
            print(f"Move aborted: location '{name}' not found")
            return False

        if not isinstance(original_target, dict) or not all(axis in original_target for axis in ("X", "Y", "Z")):
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' has invalid coordinates")
            print(f"Move aborted: location '{name}' has invalid coordinates: {original_target}")
            return False

        target = original_target.copy()
        try:
            target['X'] = int(target['X'])
            target['Y'] = int(target['Y'])
            target['Z'] = int(target['Z'])
        except (TypeError, ValueError, KeyError):
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' has non-numeric coordinates")
            print(f"Move aborted: location '{name}' has non-numeric coordinates: {original_target}")
            return False

        current_is_camera = current_location_norm == 'camera'
        target_is_camera = target_name_norm == 'camera'
        current_is_balance = current_location_norm == 'balance'
        target_is_balance = target_name_norm == 'balance'
        current_is_slot = current_location_norm.startswith('slot-')
        target_is_slot = target_name_norm.startswith('slot-')
        current_is_plate_seated = current_location_norm in PLATE_SEATED_LOCATIONS
        target_is_plate_seated = target_name_norm in PLATE_SEATED_LOCATIONS
        needs_plate_entry_dogleg = target_is_plate_seated and not current_is_plate_seated
        needs_plate_departure_dogleg = current_is_plate_seated and not target_is_plate_seated

        current_anchor = {
            'X': int(self.expected_position['X']),
            'Y': int(self.expected_position['Y']),
            'Z': int(self.expected_position['Z']),
        }
        final_target = target.copy()
        if x_offset != 0:
            final_target['X'] += x_offset
        if z_offset != 0:
            final_target['Z'] += z_offset

        if not self._authorize_saved_target(
            name=name,
            original_target=original_target,
            final_target=final_target,
            x_offset=x_offset,
            z_offset=z_offset,
            manual=manual,
            override=override,
            ignore_safe_height=ignore_safe_height,
        ):
            return False

        needs_route_safe_z = (
            (current_is_camera or target_is_camera) or
            (current_is_slot and not target_is_slot) or
            (not current_is_slot and target_is_slot)
        )

        def queue_safe_z(safe_z_value):
            print(f'Must move up to safe height before moving to {name} from {current_location}')
            if self.set_absolute_Z(safe_z_value, manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to safe Z height')
                return False
            return True

        def queue_plate_safe_z():
            if int(self.expected_position['Z']) == PLATE_DOCK_SAFE_Z:
                return True
            return queue_safe_z(PLATE_DOCK_SAFE_Z)

        def queue_plate_dogleg_point(point, error_detail):
            if self.set_absolute_coordinates(
                point['X'], point['Y'], point['Z'],
                manual=manual,
                override=override,
            ) is False:
                self.error_occurred_signal.emit('Move Error', error_detail)
                return False
            return True

        def queue_plate_entry_dogleg():
            if queue_plate_safe_z() is False:
                return False
            approach = {
                'X': final_target['X'] + PLATE_DOCK_X_OFFSET,
                'Y': final_target['Y'],
                'Z': PLATE_DOCK_SAFE_Z,
            }
            seated_safe = {
                'X': final_target['X'],
                'Y': final_target['Y'],
                'Z': PLATE_DOCK_SAFE_Z,
            }
            if queue_plate_dogleg_point(approach, 'Failed to move to plate approach dogleg') is False:
                return False
            if queue_plate_dogleg_point(seated_safe, 'Failed to move to plate seated safe position') is False:
                return False
            return True

        def queue_plate_departure_dogleg():
            if queue_plate_safe_z() is False:
                return False
            departure = {
                'X': current_anchor['X'] + PLATE_DOCK_X_OFFSET,
                'Y': current_anchor['Y'],
                'Z': PLATE_DOCK_SAFE_Z,
            }
            return queue_plate_dogleg_point(departure, 'Failed to move to plate departure dogleg')

        print(f'Moving to location: {name} from {current_location}')
        if needs_plate_departure_dogleg:
            if queue_plate_departure_dogleg() is False:
                return False

        if current_is_balance or target_is_balance:
            balance_safe_z = PLATE_DOCK_SAFE_Z if needs_plate_entry_dogleg else safe_z
            balance_safe_x = (
                final_target['X'] + PLATE_DOCK_X_OFFSET
                if needs_plate_entry_dogleg
                else final_target['X']
            )
            if needs_plate_entry_dogleg:
                if queue_plate_safe_z() is False:
                    return False
            elif not ignore_safe_height and self.expected_position['Z'] > balance_safe_z:
                if queue_safe_z(balance_safe_z) is False:
                    return False
            print(f'Must move up to safe height before moving to {name} from {current_location}')
            print("Must move to safe Y before moving to or from balance")
            if self.set_absolute_Y(15000, manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to safe Y height')
                return False
            if self.set_absolute_X(balance_safe_x, manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to target X for balance route')
                return False

        if needs_plate_entry_dogleg:
            if queue_plate_entry_dogleg() is False:
                return False

        # Only insert an intermediate safe-Z move when both endpoints are at/below
        # the selected safe plane (in inverted-Z coordinates: numerically >= safe).
        needs_intermediate_safe_z = self.expected_position['Z'] > safe_z and final_target['Z'] > safe_z

        if needs_route_safe_z and not ignore_safe_height and needs_intermediate_safe_z:
            if queue_safe_z(safe_z) is False:
                return False

        def final_location_handler(name=name):
            self.update_location_handler(name=name)
            if on_complete is not None:
                on_complete()

        if self.set_absolute_coordinates(
            final_target['X'], final_target['Y'], final_target['Z'],
            manual=manual,
            override=override,
            handler=final_location_handler,
            kwargs={'name': name}
        ) is False:
            self.error_occurred_signal.emit('Move Error', 'Failed to move to target coordinates')
            return False

        self.expected_location = name
        return True
        
    def open_gripper(self,handler=None):
        """Open the gripper."""
        return self.machine.open_gripper(handler=handler)

    def close_gripper(self,handler=None):
        """Close the gripper."""
        return self.machine.close_gripper(handler=handler)

    def _emit_manual_calibration_chip_failure(self, title, message, on_failed=None):
        self.error_occurred_signal.emit(title, message)
        if callable(on_failed):
            on_failed(message)
        return False

    def _get_calibration_chip_for_manual_load(self):
        manager = getattr(getattr(self, "model", None), "printer_head_manager", None)
        getter = getattr(manager, "get_calibration_chip", None)
        if callable(getter):
            return getter()
        return None

    def _get_gripper_printer_head_for_manual_calibration(self, rack_model):
        getter = getattr(rack_model, "get_gripper_printer_head", None)
        if callable(getter):
            return getter()
        return getattr(rack_model, "gripper_printer_head", None)

    def _is_calibration_chip_for_manual_calibration(self, printer_head):
        checker = getattr(printer_head, "is_calibration_chip", None)
        return bool(callable(checker) and checker())

    def _resolve_manual_calibration_chip_origin_slot(self, rack_model, calibration_chip, origin_slot_number=None):
        if origin_slot_number is None:
            finder = getattr(rack_model, "find_slot_for_printer_head", None)
            if callable(finder):
                origin_slot_number = finder(calibration_chip)

        if origin_slot_number is None:
            return None, "Calibration chip is not assigned to a rack slot."

        raw_slot_number = origin_slot_number
        try:
            origin_slot_number = int(origin_slot_number)
        except (TypeError, ValueError):
            return None, f"Slot number {raw_slot_number} is out of range."

        slots = getattr(rack_model, "slots", None)
        if slots is None:
            get_all_slots = getattr(rack_model, "get_all_slots", None)
            slots = get_all_slots() if callable(get_all_slots) else None

        if slots is None or not 0 <= origin_slot_number < len(slots):
            return None, f"Slot number {origin_slot_number} is out of range."

        if getattr(slots[origin_slot_number], "printer_head", None) is not calibration_chip:
            return None, "Origin slot does not contain the calibration chip."

        return origin_slot_number, ""

    def _manual_calibration_chip_load_context(self, origin_slot_number=None):
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        if rack_model is None:
            return None, None, None, "Rack model is unavailable."

        if self._get_gripper_printer_head_for_manual_calibration(rack_model) is not None:
            return None, None, None, "Gripper is already holding a printer head."

        calibration_chip = self._get_calibration_chip_for_manual_load()
        if calibration_chip is None:
            return None, None, None, "Calibration chip is unavailable."
        if not self._is_calibration_chip_for_manual_calibration(calibration_chip):
            return None, None, None, "Manual load requires a calibration chip."

        origin_slot_number, message = self._resolve_manual_calibration_chip_origin_slot(
            rack_model,
            calibration_chip,
            origin_slot_number=origin_slot_number,
        )
        if origin_slot_number is None:
            return None, None, None, message

        return rack_model, calibration_chip, origin_slot_number, ""

    def _manual_calibration_chip_removal_context(self):
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        if rack_model is None:
            return None, "Rack model is unavailable."

        gripper_head = self._get_gripper_printer_head_for_manual_calibration(rack_model)
        if gripper_head is None:
            return None, "Gripper is empty."
        if not self._is_calibration_chip_for_manual_calibration(gripper_head):
            return None, "Gripper is not holding a calibration chip."
        return rack_model, ""

    def begin_manual_calibration_chip_load(self, origin_slot_number=None, on_open=None, on_failed=None):
        """Open the gripper so an operator can manually insert the calibration chip."""
        title = "Manual Calibration Chip Load Failed"
        _rack_model, _calibration_chip, _origin_slot_number, message = self._manual_calibration_chip_load_context(
            origin_slot_number=origin_slot_number,
        )
        if message:
            return self._emit_manual_calibration_chip_failure(title, message, on_failed=on_failed)

        if self.open_gripper(handler=on_open) is False:
            return self._emit_manual_calibration_chip_failure(
                title,
                "Failed to send open gripper command.",
                on_failed=on_failed,
            )
        return True

    def complete_manual_calibration_chip_load(self, origin_slot_number=None, on_loaded=None, on_failed=None):
        """Close the gripper and record a completed manual calibration-chip load."""
        title = "Manual Calibration Chip Load Failed"
        rack_model, calibration_chip, origin_slot_number, message = self._manual_calibration_chip_load_context(
            origin_slot_number=origin_slot_number,
        )
        if message:
            return self._emit_manual_calibration_chip_failure(title, message, on_failed=on_failed)

        def after_close():
            loader = getattr(rack_model, "manual_load_calibration_chip_to_gripper", None)
            if not callable(loader):
                self._emit_manual_calibration_chip_failure(
                    title,
                    "Rack model does not support manual calibration chip loading.",
                    on_failed=on_failed,
                )
                return
            ok, load_message = loader(calibration_chip, origin_slot_number=origin_slot_number)
            if not ok:
                self._emit_manual_calibration_chip_failure(title, load_message, on_failed=on_failed)
                return
            if callable(on_loaded):
                on_loaded()

        if self.close_gripper(handler=after_close) is False:
            return self._emit_manual_calibration_chip_failure(
                title,
                "Failed to send close gripper command.",
                on_failed=on_failed,
            )
        return True

    def begin_manual_calibration_chip_removal(self, on_open=None, on_failed=None):
        """Open the gripper so an operator can manually remove the calibration chip."""
        title = "Manual Calibration Chip Removal Failed"
        _rack_model, message = self._manual_calibration_chip_removal_context()
        if message:
            return self._emit_manual_calibration_chip_failure(title, message, on_failed=on_failed)

        if self.open_gripper(handler=on_open) is False:
            return self._emit_manual_calibration_chip_failure(
                title,
                "Failed to send open gripper command.",
                on_failed=on_failed,
            )
        return True

    def complete_manual_calibration_chip_removal(self, on_removed=None, on_failed=None):
        """Close the gripper and record a completed manual calibration-chip removal."""
        title = "Manual Calibration Chip Removal Failed"
        rack_model, message = self._manual_calibration_chip_removal_context()
        if message:
            return self._emit_manual_calibration_chip_failure(title, message, on_failed=on_failed)

        def after_close():
            remover = getattr(rack_model, "manual_remove_calibration_chip_from_gripper", None)
            if not callable(remover):
                self._emit_manual_calibration_chip_failure(
                    title,
                    "Rack model does not support manual calibration chip removal.",
                    on_failed=on_failed,
                )
                return
            ok, remove_message = remover()
            if not ok:
                self._emit_manual_calibration_chip_failure(title, remove_message, on_failed=on_failed)
                return
            if callable(on_removed):
                on_removed()

        if self.close_gripper(handler=after_close) is False:
            return self._emit_manual_calibration_chip_failure(
                title,
                "Failed to send close gripper command.",
                on_failed=on_failed,
            )
        return True

    def set_gripper_params(self, refresh_period_ms, pulse_duration_ms, handler=None, manual=False):
        """Update the firmware gripper refresh timing."""
        return self.machine.set_gripper_params(
            int(refresh_period_ms),
            int(pulse_duration_ms),
            handler=handler,
            manual=manual,
        )

    def wait_command(self):
        """Tells the machine to wait a specified amount of time in milliseconds."""
        self.machine.wait_command()

    def test_print_wait(self):
        """Test the print wait command."""
        self.print_droplets(10)
        # self.wait_command()
        self.print_droplets(10)
    
    def pick_up_handler(self,slot):
        """Handle the pick up signal from the rack."""
        self.model.rack_model.transfer_to_gripper(slot)

    def _prepare_manual_head_transfer(self):
        array_state = self.get_array_run_state()
        if array_state in {"running", "stop_requested"}:
            self.error_occurred_signal.emit(
                'Head Transfer Blocked',
                'Cannot load or unload a printer head while the print array is still stopping.',
            )
            return False

        if getattr(self, "_soft_stop_clear_uncertain", False):
            self.error_occurred_signal.emit(
                'Head Transfer Blocked',
                'The last soft stop did not confirm that the firmware queue was cleared. Clear the queue or reconnect before loading another printer head.',
            )
            return False

        if self.machine.check_if_all_completed() == False:
            print('Cannot transfer printer head: Commands are still running')
            return False

        machine_model = getattr(self.model, "machine_model", None)
        if bool(getattr(machine_model, "transport_paused", False)) or bool(getattr(machine_model, "paused", False)):
            try:
                self.resume_commands()
            except Exception:
                self.error_occurred_signal.emit(
                    'Head Transfer Blocked',
                    'Cannot resume machine transport before loading or unloading a printer head.',
                )
                return False
        return True

    def pick_up_printer_head(self,slot,manual=False):
        """Pick up a printer head from the rack."""
        if manual == True:
            if not self._prepare_manual_head_transfer():
                return
        # is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot)
        is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot, use_expected=True)
        if is_valid:
            # update expected rack state NOW (so subsequent queued ops see it)
            ok, msg = self.model.rack_model.plan_transfer_to_gripper(slot)
            if not ok:
                print(f"Plan pickup failed: {msg}")
                return

            self.open_gripper()
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=9000,coords=coords)

            self.move_to_location(name,coords=coords,override=True,ignore_safe_height=True)
            self.close_gripper(handler=lambda: self.pick_up_handler(slot))
            self.move_to_location(name,x_offset=3000,coords=coords,override=True,ignore_safe_height=True)
        else:
            print(f'Error: {error_msg}')
            pass

    def drop_off_handler(self,slot):
        """Handle the drop off signal from the rack."""
        self.model.rack_model.transfer_from_gripper(slot)

    def drop_off_printer_head(self,slot,manual=False):
        """Drop off a printer head to the rack."""
        if manual == True:
            if not self._prepare_manual_head_transfer():
                return
        is_valid, error_msg = self.model.rack_model.verify_transfer_from_gripper(slot, use_expected=True)
        if is_valid:
            # update expected rack state NOW (so subsequent queued ops see it)
            ok, msg = self.model.rack_model.plan_transfer_from_gripper(slot)
            if not ok:
                print(f"Plan dropoff failed: {msg}")
                return
            
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=3000,coords=coords)
            self.move_to_location(name,coords=coords,override=True,ignore_safe_height=True)
            self.open_gripper(handler=lambda: self.drop_off_handler(slot))
            self.move_to_location(name,x_offset=9000,coords=coords,override=True,ignore_safe_height=True)
            self.close_gripper()
        else:
            print(f'Error: {error_msg}')
            return

    def swap_printer_head(self, slot_number, new_printer_head):
        """Handle swapping of printer heads."""
        self.model.printer_head_manager.swap_printer_head(slot_number, new_printer_head)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap printer heads between two slots in the rack.

        Args:
            slot_number_1 (int): The first slot number.
            slot_number_2 (int): The second slot number.
        """
        self.model.rack_model.swap_printer_heads_between_slots(slot_number_1, slot_number_2)

    def volume_update_handler(self,droplet_count=None):
        """Handle the volume update signal."""
        self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(droplet_count)

    def _record_refuel_ejection_event(self, count, *, source, event_kind, count_kind="observed", payload=None):
        try:
            refuel_model = getattr(self.model, "refuel_camera_model", None)
            recorder = getattr(refuel_model, "record_refuel_ejection_event", None)
            if callable(recorder):
                return recorder(
                    count,
                    source=source,
                    event_kind=event_kind,
                    count_kind=count_kind,
                    payload=payload or {},
                )
        except Exception as exc:
            print(f"[RefuelEjections] failed to record ejection event: {exc}")
        return None

    def _current_imaging_droplet_count(self):
        try:
            camera_model = getattr(self.model, "droplet_camera_model", None)
            getter = getattr(camera_model, "get_num_droplets", None)
            value = getter() if callable(getter) else getattr(camera_model, "num_droplets", None)
            return max(0, int(value))
        except Exception:
            return 0
    
    def print_droplets(self,droplets,handler=None,kwargs=None,manual=False,expected_volume=None):
        """Print a specified number of droplets."""
        if not self.model.machine_model.regulating_print_pressure:
            self.error_occurred_signal.emit('Error','Pressure regulation is not enabled')
            print('Cannot print: Pressure regulation is not enabled')
            return
        if self.profile.name != "legacy":
            # fall back to your current implementation
            result = self.machine.print_droplets(droplets, handler=handler, kwargs=kwargs, manual=manual)
            if result is not False:
                self._record_refuel_ejection_event(
                    droplets,
                    source="Controller.print_droplets",
                    event_kind="print_droplets_queued",
                    count_kind="commanded",
                    payload={"manual": bool(manual)},
                )
            return result
        
        # --- legacy behavior ---
        printer_head = self.model.rack_model.get_gripper_printer_head()
        if printer_head is not None:
            if printer_head.check_calibration_complete():
                # print('Controller: using calibrations to change pulse width')
                # vol, res, target, bias, pred_model, resistance_pulse_width = printer_head.get_prediction_data()
                # if expected_volume is not None:
                #     #print(f'Controller: using expected volume: {expected_volume}')
                #     vol = expected_volume
                # new_pulse_width = self.model.calibration_model.predict_pulse_width(vol, res, target, bias=bias, prediction_model=pred_model,resistance_pulse_width=resistance_pulse_width)
                # if abs(self.model.machine_model.get_print_pulse_width() - new_pulse_width) > 2:
                #     self.set_print_pulse_width(new_pulse_width,manual=False)
            
                if handler is None:
                    handler = self.volume_update_handler
                    kwargs = {'droplet_count':droplets}
                else:
                    if kwargs is None:
                        kwargs = {}
                    kwargs['update_volume'] = True
            else:
                print('Controller: using default pulse width')

        result = self.machine.print_droplets(droplets,handler=handler,kwargs=kwargs,manual=manual)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_droplets",
                event_kind="print_droplets_queued",
                count_kind="commanded",
                payload={"manual": bool(manual), "profile": "legacy"},
            )
        return result

    def print_only(self,droplets,manual=False):
        """Activate the print valve a specified number of times without refueling."""
        result = self.machine.print_only(droplets,manual=manual)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_only",
                event_kind="print_only_queued",
                count_kind="commanded",
                payload={"manual": bool(manual)},
            )
        return result
    
    def refuel_only(self,droplets,manual=False):
        """Activate the refuel valve a specified number of times without printing."""
        self.machine.refuel_only(droplets,manual=manual)

    def print_calibration_droplets(self,droplets,manual=False,pressure=None,pulse_width=None):
        """Print a specified number of droplets for calibration."""
        print('Controller: Printing calibration droplets')
        result = self.machine.print_calibration_droplets(droplets,manual=manual,pressure=pressure,pulse_width=pulse_width)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_calibration_droplets",
                event_kind="print_calibration_droplets_queued",
                count_kind="commanded",
                payload={
                    "manual": bool(manual),
                    "pressure": pressure,
                    "pulse_width": pulse_width,
                },
            )
        return result

    def start_mass_stabilization_timer(self):
        """Create a single shot timer that when triggered it will signal the model to check for the final stable mass."""
        print('Starting mass stabilization timer...')
        QtCore.QTimer.singleShot(3000, self.model.calibration_model.check_for_final_mass)

    def _record_array_progress(
        self,
        well_id=None,
        stock_id=None,
        target_droplets=None,
        update_volume=False,
        execution_intent_id=None,
    ):
        target_droplets = int(target_droplets or 0)
        well = self.model.well_plate.get_well(well_id)
        if well is not None:
            well.record_stock_print(stock_id, target_droplets)
        if update_volume:
            printer_head = self.model.rack_model.get_gripper_printer_head()
            if printer_head is not None:
                printer_head.record_droplet_volume_lost(target_droplets)
        try:
            if execution_intent_id is None:
                self.model.experiment_model.create_progress_file()
            else:
                self.model.experiment_model.create_progress_file(
                    execution_intent_id=execution_intent_id,
                )
        except Exception as exc:
            if execution_intent_id is None:
                raise
            setter = getattr(
                self.model.experiment_model, "set_execution_plan_sync_error", None
            )
            if callable(setter):
                setter(exc)
            self.error_occurred_signal.emit(
                "Progress Save Error",
                "The dispense completed, but progress could not be saved. Printing is "
                "unavailable because the app cannot safely determine where to continue.",
            )
            return False
        try:
            completer = getattr(
                self.model.experiment_model, "complete_execution_print_intent", None
            )
            if callable(completer):
                completer(execution_intent_id)
        except Exception as exc:
            self.model.experiment_model.set_execution_plan_sync_error(exc)
            self.error_occurred_signal.emit(
                "Saved Progress Error",
                "Progress was saved, but the print could not be marked complete. Printing "
                "is unavailable until the saved progress is recovered.",
            )
            return False
        return True

    def _get_array_remaining_wells(self, stock_id):
        if not stock_id:
            return []
        serpentine = bool(getattr(self, "_array_print_serpentine", ARRAY_PRINT_SERPENTINE))
        reaction_wells = self.model.well_plate.get_all_wells_with_reactions(fill_by='rows', serpentine=serpentine)
        return [well for well in reaction_wells if well.get_remaining_droplets(stock_id) > 0]

    def _start_array_run_context(self):
        current_printer_head = self.model.rack_model.get_gripper_printer_head()
        if current_printer_head is None:
            return False

        if current_printer_head.check_calibration_complete():
            print('\nController: Using calibrations during array printing')
            expected_volume = current_printer_head.get_current_volume()
            droplet_volume = current_printer_head.get_target_droplet_volume()
            update_volume = expected_volume is not None
        else:
            print('\nController: using default pulse width')
            expected_volume = None
            droplet_volume = None
            update_volume = False

        current_stock_id = current_printer_head.get_stock_id()
        wells_with_droplets = self._get_array_remaining_wells(current_stock_id)
        if not wells_with_droplets:
            self._array_context = None
            return False

        self._array_context = {
            "stock_id": current_stock_id,
            "expected_volume": expected_volume,
            "update_volume": update_volume,
            "droplet_volume": droplet_volume,
            "finalize_reason": None,
            "lookahead_wells": 2,
            "queued_wells": [],
            "planned_well_ids": set(),
            "current_barrier_seq32": None,
            "soft_stop_pending": False,
            "soft_stop_phase": None,
            "soft_stop_origin": None,
            "soft_stop_frozen_barrier_seq32": None,
            "soft_stop_attempt_token": 0,
            "soft_stop_recovery_reason": None,
            "soft_stop_phase_before_pause": None,
            "soft_stop_resume_sent": False,
            "soft_stop_pause_during_clearing": False,
            "pause_departure_pending": True,
            "pause_departure_accel": int(
                getattr(self, "_array_pause_departure_accel", ARRAY_PAUSE_DEPARTURE_ACCEL)
            ),
            "pause_departure_settle_ms": int(
                getattr(self, "_array_pause_departure_settle_ms", ARRAY_PAUSE_DEPARTURE_SETTLE_MS)
            ),
            "pause_departure_restore_accels": self._get_array_pause_departure_restore_accels(),
            "gentle_accel_enabled": bool(
                getattr(self, "_array_gentle_accel_enabled", ARRAY_GENTLE_ACCEL_ENABLED)
            ),
            "array_accels_lowered": False,
            "array_accels_restored": False,
            "print_profile_enable_queued": False,
            "print_profile_disable_queued": False,
            "row_start_overshoot_steps": int(
                getattr(self, "_array_row_start_overshoot_steps", ARRAY_ROW_START_OVERSHOOT_STEPS)
            ),
            "last_planned_row_num": None,
            "last_planned_col": None,
        }
        return True

    def _get_array_pause_departure_restore_accels(self):
        defaults = (ARRAY_AXIS_ACCEL_DEFAULT,) * 3
        machine_model = getattr(self.model, "machine_model", None)
        getter = getattr(machine_model, "get_current_accelerations", None)
        if not callable(getter):
            return defaults

        try:
            values = getter()
        except Exception:
            return defaults

        if not isinstance(values, (tuple, list)) or len(values) < 3:
            return defaults

        restore = []
        for idx, default in enumerate(defaults):
            try:
                value = int(values[idx])
            except Exception:
                value = default
            restore.append(value if value > 0 else default)
        return tuple(restore)

    def _apply_array_run_acceleration(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("array_accels_lowered"):
            return True

        if not context.get("gentle_accel_enabled", ARRAY_GENTLE_ACCEL_ENABLED):
            context["array_accels_lowered"] = False
            context["array_accels_restored"] = True
            return True

        accel = max(0, int(context.get("pause_departure_accel") or 0))
        if accel <= 0:
            context["array_accels_lowered"] = True
            context["array_accels_restored"] = True
            return True

        queued_any = False
        for axis_idx in range(3):
            if self.set_axis_accel(axis_idx, accel) is False:
                if queued_any:
                    context["array_accels_lowered"] = True
                    self._restore_array_run_acceleration()
                self.error_occurred_signal.emit(
                    'Print Array Error',
                    'Failed to lower acceleration before starting the print array',
                )
                return False
            queued_any = True

        context["array_accels_lowered"] = True
        context["array_accels_restored"] = False
        return True

    def _restore_array_run_acceleration(self, on_restored=None):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            if callable(on_restored):
                on_restored()
            return True

        if not context.get("array_accels_lowered") or context.get("array_accels_restored"):
            if callable(on_restored):
                on_restored()
            return True

        restore_accels = tuple(
            context.get("pause_departure_restore_accels")
            or (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)
        )
        if len(restore_accels) < 3:
            restore_accels = (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)

        context["array_accels_restored"] = True
        for axis_idx, accel_value in enumerate(restore_accels[:3]):
            handler = on_restored if axis_idx == 2 else None
            if self.set_axis_accel(axis_idx, int(accel_value), handler=handler) is False:
                self.error_occurred_signal.emit(
                    'Print Array Warning',
                    'Failed to restore acceleration after the print array; check the Speed Profiles tab before the next run.',
                )
                if callable(on_restored):
                    on_restored()
                return False
        return True

    def _array_post_well_expected_volume(self, target_droplets):
        context = getattr(self, "_array_context", None) or {}
        expected_volume = context.get("expected_volume")
        droplet_volume = context.get("droplet_volume")
        if expected_volume is None or droplet_volume is None:
            return None
        return float(expected_volume) - int(target_droplets or 0) * float(droplet_volume) / 1000.0

    def _get_next_unplanned_array_well(self, context):
        stock_id = context.get("stock_id")
        planned = context.get("planned_well_ids", set())
        for well in self._get_array_remaining_wells(stock_id):
            if well.well_id not in planned:
                return well
        return None

    @staticmethod
    def _normalize_integral_machine_coordinates(coordinates, label):
        """Normalize trusted derived coordinates without accepting truncation."""
        if not isinstance(coordinates, dict) or set(coordinates) != {"X", "Y", "Z"}:
            raise ConfigurationSafetyError(
                f"{label} must contain exactly X, Y, and Z coordinates."
            )

        normalized = {}
        for axis in ("X", "Y", "Z"):
            value = coordinates[axis]
            if isinstance(value, (bool, np.bool_)):
                raise ConfigurationSafetyError(
                    f"{label} {axis} coordinate must be an integer."
                )
            if isinstance(value, (int, np.integer)):
                normalized[axis] = int(value)
                continue
            if isinstance(value, (float, np.floating)):
                numeric = float(value)
                if math.isfinite(numeric) and numeric.is_integer():
                    normalized[axis] = int(value)
                    continue
            raise ConfigurationSafetyError(
                f"{label} {axis} coordinate must be an integer."
            )
        return normalized

    def _get_normalized_array_well_coordinates(self, well):
        well_id = str(getattr(well, "well_id", "unknown") or "unknown")
        getter = getattr(well, "get_coordinates", None)
        coordinates = getter() if callable(getter) else None
        return self._normalize_integral_machine_coordinates(
            coordinates,
            f"Well {well_id}",
        )

    def _validate_array_preflight_endpoint(self, coordinates):
        guard = getattr(self, "configuration_safety_guard", None)
        if guard is not None:
            guard.validate_endpoint(coordinates)
        return coordinates

    def _preflight_array_well_targets(self, stock_id):
        """Validate every remaining array endpoint before queuing hardware work."""
        wells = self._get_array_remaining_wells(stock_id)
        preview_context = {
            "row_start_overshoot_steps": int(
                getattr(self, "_array_row_start_overshoot_steps", ARRAY_ROW_START_OVERSHOOT_STEPS)
            ),
            "last_planned_row_num": None,
            "last_planned_col": None,
        }
        plate_authorized = False

        for well in wells:
            well_id = str(getattr(well, "well_id", "unknown") or "unknown")
            try:
                well_coordinates = self._get_normalized_array_well_coordinates(well)
                self._validate_array_preflight_endpoint(well_coordinates)
            except (ConfigurationSafetyError, TypeError, ValueError) as exc:
                return {
                    "ok": False,
                    "code": "well_endpoint_invalid",
                    "well_id": well_id,
                    "message": (
                        f"Well {well_id} cannot be printed because {exc} "
                        "No machine commands were queued."
                    ),
                    "reported": False,
                }

            # Plate authorization is identical for every well because it is bound
            # to the same verified calibration document. Check it once here and
            # retain the per-well runtime check as a defense against later changes.
            if not plate_authorized:
                if not self._authorize_active_plate_derived_target(
                    well_coordinates,
                    "print_array_preflight",
                ):
                    return {
                        "ok": False,
                        "code": "plate_target_not_authorized",
                        "well_id": well_id,
                        "message": (
                            "The active plate calibration is not authorized for printing. "
                            "No machine commands were queued."
                        ),
                        "reported": True,
                    }
                plate_authorized = True

            overshoot_coordinates = self._get_array_row_start_overshoot_coords(
                preview_context,
                well,
                well_coordinates,
            )
            if overshoot_coordinates is not None:
                try:
                    overshoot_coordinates = self._normalize_integral_machine_coordinates(
                        overshoot_coordinates,
                        f"Row-entry approach for well {well_id}",
                    )
                    self._validate_array_preflight_endpoint(overshoot_coordinates)
                except (ConfigurationSafetyError, TypeError, ValueError) as exc:
                    return {
                        "ok": False,
                        "code": "row_entry_endpoint_invalid",
                        "well_id": well_id,
                        "message": (
                            f"The row-entry approach for well {well_id} cannot be used "
                            f"because {exc} No machine commands were queued."
                        ),
                        "reported": False,
                    }

            self._record_last_planned_array_well(preview_context, well)

        return {
            "ok": bool(wells),
            "code": "ok" if wells else "no_remaining_wells",
            "well_count": len(wells),
            "message": "" if wells else "No wells remain for the loaded reagent.",
            "reported": False,
        }

    def _get_array_well_row_col(self, well):
        try:
            return int(well.row_num), int(well.col)
        except Exception:
            return None, None

    def _get_well_xy_direction(self, target_coords, neighbor_coords, *, invert=False):
        try:
            target_x = float(target_coords['X'])
            target_y = float(target_coords['Y'])
            neighbor_x = float(neighbor_coords['X'])
            neighbor_y = float(neighbor_coords['Y'])
        except Exception:
            return None

        dx = neighbor_x - target_x
        dy = neighbor_y - target_y
        if invert:
            dx = -dx
            dy = -dy

        length = math.hypot(dx, dy)
        if length <= 0:
            return None
        return dx / length, dy / length

    def _get_array_row_start_overshoot_coords(self, context, well, target_coords):
        try:
            overshoot_steps = int(context.get("row_start_overshoot_steps") or 0)
        except Exception:
            overshoot_steps = 0
        if overshoot_steps <= 0:
            return None

        row_num, col = self._get_array_well_row_col(well)
        last_row_num = context.get("last_planned_row_num")
        if row_num is None or col is None or last_row_num is None:
            return None
        try:
            if row_num <= int(last_row_num):
                return None
        except Exception:
            return None

        row_label = getattr(well, "row", None)
        if not row_label:
            return None

        well_plate = getattr(self.model, "well_plate", None)
        get_well = getattr(well_plate, "get_well", None)
        if not callable(get_well):
            return None

        direction = None
        right_neighbor = get_well(f"{row_label}{col + 1}")
        if right_neighbor is not None:
            right_coords = right_neighbor.get_coordinates()
            if isinstance(right_coords, dict):
                direction = self._get_well_xy_direction(target_coords, right_coords)

        if direction is None and col > 1:
            left_neighbor = get_well(f"{row_label}{col - 1}")
            if left_neighbor is not None:
                left_coords = left_neighbor.get_coordinates()
                if isinstance(left_coords, dict):
                    direction = self._get_well_xy_direction(target_coords, left_coords, invert=True)

        if direction is None:
            return None

        unit_x, unit_y = direction
        try:
            target_x = float(target_coords['X'])
            target_y = float(target_coords['Y'])
            target_z = target_coords['Z']
        except Exception:
            return None

        return {
            'X': int(round(target_x - unit_x * overshoot_steps, 0)),
            'Y': int(round(target_y - unit_y * overshoot_steps, 0)),
            'Z': target_z,
        }

    def _record_last_planned_array_well(self, context, well):
        row_num, col = self._get_array_well_row_col(well)
        context["last_planned_row_num"] = row_num
        context["last_planned_col"] = col

    def _update_current_array_barrier(self):
        context = getattr(self, "_array_context", None) or {}
        queued_wells = list(context.get("queued_wells") or [])
        context["current_barrier_seq32"] = queued_wells[0]["dispense_seq32"] if queued_wells else None

    def _queue_next_array_well(self):
        context = getattr(self, "_array_context", None) or {}
        stock_id = context.get("stock_id")
        well = self._get_next_unplanned_array_well(context)
        if well is None:
            return False

        target_droplets = int(well.get_remaining_droplets(stock_id) or 0)
        if target_droplets <= 0:
            return False

        try:
            well_coords = self._get_normalized_array_well_coordinates(well)
        except (ConfigurationSafetyError, TypeError, ValueError) as exc:
            self.error_occurred_signal.emit(
                'Print Array Error',
                f'Well {well.well_id} has invalid coordinates: {exc}',
            )
            self._complete_array_finalize("hard_abort")
            return False

        if not self._authorize_active_plate_derived_target(
            well_coords, "print_array_well"
        ):
            self._complete_array_finalize("hard_abort")
            return False

        apply_pause_departure_safeguards = bool(context.get("pause_departure_pending"))
        pause_departure_settle_ms = max(0, int(context.get("pause_departure_settle_ms") or 0))

        overshoot_coords = self._get_array_row_start_overshoot_coords(context, well, well_coords)
        if overshoot_coords is not None:
            if self.set_absolute_coordinates(overshoot_coords['X'], overshoot_coords['Y'], overshoot_coords['Z'], override=True) is False:
                self.error_occurred_signal.emit('Print Array Error', f'Failed to queue row-entry approach for well {well.well_id}')
                self._complete_array_finalize("hard_abort")
                return False

        if self.set_absolute_coordinates(well_coords['X'], well_coords['Y'], well_coords['Z'], override=True) is False:
            self.error_occurred_signal.emit('Print Array Error', f'Failed to move to well {well.well_id}')
            self._complete_array_finalize("hard_abort")
            return False

        if apply_pause_departure_safeguards and pause_departure_settle_ms > 0:
            if self.machine.wait_ms(pause_departure_settle_ms) is False:
                self.error_occurred_signal.emit('Print Array Error', f'Failed to queue settle delay before printing well {well.well_id}')
                self._complete_array_finalize("hard_abort")
                return False

        context["pause_departure_pending"] = False

        print(f'Printing {target_droplets} droplets to well {well.well_id}')
        execution_intent_id = None
        experiment_model = self.model.experiment_model
        durable_checkpoint = getattr(
            experiment_model, "uses_durable_execution_checkpoint", None
        )
        if callable(durable_checkpoint) and durable_checkpoint():
            printer_head = self.model.rack_model.get_gripper_printer_head()
            try:
                execution_intent_id = experiment_model.begin_execution_print_intent(
                    well_id=well.well_id,
                    stock_id=stock_id,
                    commanded_droplets=target_droplets,
                    printer_head_id=str(getattr(printer_head, "printer_head_id", None) or ""),
                )
            except Exception as exc:
                experiment_model.set_execution_plan_sync_error(exc)
                self.error_occurred_signal.emit(
                    'Print Array Error',
                    f'Printing did not start for well {well.well_id} because its saved '
                    'progress record could not be created.',
                )
                print(f"Could not create saved progress record for {well.well_id}: {exc}")
                self._complete_array_finalize("hard_abort")
                return False
        dispense_command = self.print_droplets(
            target_droplets,
            expected_volume=context.get("expected_volume"),
            handler=self._handle_array_well_complete,
            kwargs={
                'well_id': well.well_id,
                'stock_id': stock_id,
                'target_droplets': target_droplets,
                'update_volume': context.get("update_volume", False),
                'execution_intent_id': execution_intent_id,
            },
        )
        if dispense_command is None:
            self.error_occurred_signal.emit('Print Array Error', f'Failed to queue dispense for well {well.well_id}')
            self._complete_array_finalize("hard_abort")
            return False

        if execution_intent_id is not None:
            try:
                experiment_model.attach_execution_print_command(
                    execution_intent_id,
                    int(getattr(dispense_command, "command_number", 0) or 0),
                )
            except Exception as exc:
                setter = getattr(
                    experiment_model, "set_execution_plan_sync_error", None
                )
                if callable(setter):
                    setter(exc)
                self.error_occurred_signal.emit(
                    'Saved Progress Error',
                    'The dispense was queued, but the app could not save enough progress '
                    'information to continue safely. Printing has stopped.',
                )
                print(f"Could not attach saved progress to queued dispense: {exc}")
                self._complete_array_finalize("hard_abort")
                return False

        context.setdefault("planned_well_ids", set()).add(well.well_id)
        context.setdefault("queued_wells", []).append(
            {
                "well_id": well.well_id,
                "target_droplets": target_droplets,
                "dispense_seq32": int(getattr(dispense_command, "command_number", 0) or 0),
                "execution_intent_id": execution_intent_id,
            }
        )
        self._record_last_planned_array_well(context, well)
        self._update_current_array_barrier()
        return True

    def _fill_array_lookahead(self):
        context = getattr(self, "_array_context", None) or {}
        if context.get("finalize_reason") is not None:
            return False

        queued_wells = context.setdefault("queued_wells", [])
        lookahead_wells = int(context.get("lookahead_wells", 1) or 1)
        added_any = False
        while len(queued_wells) < lookahead_wells:
            if self.get_array_run_state() == "stop_requested":
                break

            if queued_wells and context.get("update_volume"):
                post_well_expected = self._array_post_well_expected_volume(queued_wells[-1]["target_droplets"])
                if post_well_expected is not None and post_well_expected < 10:
                    break

            if not self._queue_next_array_well():
                break
            queued_wells = context.setdefault("queued_wells", [])
            added_any = True

        self._update_current_array_barrier()
        return added_any

    def _pop_completed_array_well(self, well_id):
        context = getattr(self, "_array_context", None) or {}
        queued_wells = list(context.get("queued_wells") or [])
        removed = None
        remaining = []
        for info in queued_wells:
            if removed is None and info.get("well_id") == well_id:
                removed = info
            else:
                remaining.append(info)
        context["queued_wells"] = remaining
        if removed is not None:
            context.setdefault("planned_well_ids", set()).discard(well_id)
        self._update_current_array_barrier()
        return removed

    def _handle_array_well_complete(
        self,
        well_id=None,
        stock_id=None,
        target_droplets=None,
        update_volume=False,
        execution_intent_id=None,
    ):
        context = getattr(self, "_array_context", None) or {}
        self._pop_completed_array_well(well_id)
        progress_saved = self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
            execution_intent_id=execution_intent_id,
        )
        if progress_saved is False:
            self._complete_array_finalize("hard_abort")
            return

        if context.get("update_volume") and context.get("expected_volume") is not None and context.get("droplet_volume") is not None:
            context["expected_volume"] -= int(target_droplets or 0) * float(context["droplet_volume"]) / 1000.0

        stock_id = context.get("stock_id", stock_id)
        remaining_wells = self._get_array_remaining_wells(stock_id)
        if not remaining_wells and not context.get("queued_wells"):
            if (
                self.get_array_run_state() == "stop_requested"
                and context.get("soft_stop_origin") == "immediate_pause"
            ):
                # The watermark status that follows this completion owns the
                # one transport resume and final park sequence.
                context["soft_stop_pending"] = True
            else:
                self._enqueue_array_finalize("completed")
        elif self.get_array_run_state() == "stop_requested":
            context["soft_stop_pending"] = True
            self._maybe_complete_array_soft_stop_after_catchup()
        elif context.get("update_volume") and context.get("expected_volume") is not None and context.get("expected_volume") < 10:
            self._enqueue_array_finalize("refill_required")
        else:
            self._fill_array_lookahead()

    def _enqueue_array_finalize(self, reason):
        reason = str(reason or "completed")
        context = getattr(self, "_array_context", None)
        if context is not None:
            if context.get("finalize_reason") is not None:
                return False
            context["finalize_reason"] = reason

        if reason == "hard_abort":
            self._complete_array_finalize(reason)
            return False

        self._queue_array_profile_disable_once(clear_on_failure=True)

        def _finish_after_park():
            self._complete_array_finalize(reason)

        if self._queue_pause_park_sequence(on_complete=_finish_after_park) is False:
            dock_reason = "soft_stop_park_failed" if reason == "soft_stop" else "array_park_failed"
            self._mark_evap_plate_dock_check_required(dock_reason)
            self._complete_array_finalize(reason)
            return False
        return True

    def _queue_array_profile_disable_once(self, *, clear_on_failure=False):
        """Queue one profile teardown for the active array, with CLEAR fallback."""
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("print_profile_disable_queued"):
            return True
        # Older/restored contexts predate this marker and represent an active
        # array; a newly-created context explicitly starts it as False.
        if context.get("print_profile_enable_queued", True) is False:
            return True

        context["print_profile_disable_queued"] = True
        try:
            queued = self.disable_print_profile()
        except Exception:
            queued = False
        if queued is not False:
            return True

        if clear_on_failure and not context.get("array_clear_fallback_requested"):
            context["array_clear_fallback_requested"] = True
            try:
                self._clear_machine_and_model_command_queues(
                    reason="array_queue_clear",
                )
            except Exception:
                pass
        return False

    def _complete_array_finalize(self, reason):
        reason = str(reason or "completed")
        self._queue_array_profile_disable_once(clear_on_failure=reason == "hard_abort")
        if reason == "hard_abort":
            context = getattr(self, "_array_context", None)
            if isinstance(context, dict) and not context.get("array_clear_fallback_requested"):
                context["array_clear_fallback_requested"] = True
                try:
                    self._clear_machine_and_model_command_queues(
                        reason="array_queue_clear",
                    )
                except Exception:
                    pass
            self._mark_evap_plate_dock_check_required("array_hard_abort")
        context = getattr(self, "_array_context", None)
        if isinstance(context, dict) and context.get("array_finalize_after_accel_restore"):
            return
        if isinstance(context, dict) and context.get("skip_array_accel_restore"):
            self._finish_array_finalize(reason)
            return
        if isinstance(context, dict):
            context["array_finalize_after_accel_restore"] = reason

        def _finish_finalize():
            self._finish_array_finalize(reason)

        self._restore_array_run_acceleration(on_restored=_finish_finalize)

    def _finish_array_finalize(self, reason):
        reason = str(reason or "completed")
        try:
            audit_details = self._build_print_array_snapshot(getattr(self, "_array_context", None))
        except Exception:
            audit_details = {}
        audit_details["finalize_reason"] = reason
        experiment_model = getattr(self.model, "experiment_model", None)
        try:
            if reason == "completed":
                completer = getattr(experiment_model, "try_complete_execution_plan", None)
                if callable(completer):
                    terminal_plan = completer(reason="all_frozen_targets_satisfied")
                    if terminal_plan is not None:
                        audit_details["terminal_plan_revision"] = terminal_plan.plan_revision
                        audit_details["terminal_plan_state"] = terminal_plan.state.value
            elif reason == "hard_abort":
                transition = getattr(experiment_model, "transition_execution_plan_terminal", None)
                plan_getter = getattr(experiment_model, "get_execution_plan_snapshot", None)
                plan = plan_getter() if callable(plan_getter) else None
                if callable(transition) and plan is not None and getattr(plan.state, "value", None) == "active":
                    terminal_plan = transition("aborted", "controller_hard_abort")
                    audit_details["terminal_plan_revision"] = terminal_plan.plan_revision
                    audit_details["terminal_plan_state"] = terminal_plan.state.value
        except Exception as exc:
            audit_details["terminal_transition_error"] = str(exc)
            self.error_occurred_signal.emit(
                "Experiment Progress Error",
                "Printing stopped, but the experiment could not be marked complete. "
                "Review the saved progress before printing again.",
            )
            print(f"Could not synchronize final experiment state: {exc}")
        self._invalidate_paused_array_soft_stop_attempt(
            getattr(self, "_array_context", None)
        )
        self._array_context = None

        if reason in {"soft_stop", "refill_required"}:
            self._set_array_run_state("resume_ready")
        else:
            self._set_array_run_state("idle")
        audit_details["array_state"] = self.get_array_run_state()

        if reason == "completed":
            self._record_print_array_audit_event(
                "print_array_completed",
                "Print array completed",
                details=audit_details,
            )
        elif reason == "soft_stop":
            self._record_print_array_audit_event(
                "print_array_paused",
                "Print array paused",
                details=audit_details,
            )
        elif reason == "refill_required":
            self._record_print_array_audit_event(
                "print_array_refill_required",
                "Print array paused for printer head refill",
                details=audit_details,
                level="warning",
            )
        else:
            self._record_print_array_audit_event(
                "print_array_aborted",
                "Print array aborted",
                details=audit_details,
                level="error",
            )

        if reason == "completed":
            print('---Printing complete---')
            self._emit_optional("array_complete")
        elif reason == "soft_stop":
            print('---Array soft stop complete---')
            self._emit_optional("update_slots_signal")
        elif reason == "refill_required":
            print('---Must reload printer head---')
            self._emit_optional("update_slots_signal")
            self.error_occurred_signal.emit('Error', 'Printer head needs to be reloaded')
        elif reason == "hard_abort":
            print('---Array run aborted---')


    def well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )

    def last_well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )
        self._enqueue_array_finalize("completed")

    def refill_printer_head_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )
        self._enqueue_array_finalize("refill_required")

    def reset_single_array(self):
        """Resets the droplet count for all wells in the well plate for the currently loaded stock solution."""
        experiment_model = getattr(self.model, "experiment_model", None)
        can_reset = getattr(experiment_model, "can_reset_array_progress", None)
        if callable(can_reset) and not can_reset():
            message = (
                "Recorded dispense counts are physical progress and cannot be reset in "
                "place. Create an editable copy and finalize it as a new experiment instead."
            )
            self.error_occurred_signal.emit("Cannot reset recorded experiment", message)
            return False
        active_printer_head = self.model.rack_model.get_gripper_printer_head()
        if active_printer_head is None:
            self.error_occurred_signal.emit("Cannot reset array", "No printer head is loaded.")
            return False
        stock_id = active_printer_head.get_stock_id()
        try:
            remaining_before = len(self._get_array_remaining_wells(stock_id))
        except Exception:
            remaining_before = None
        self.model.well_plate.reset_all_wells_for_stock(stock_id)
        self.model.experiment_model.create_progress_file()
        progress_path = getattr(self.model.experiment_model, "progress_file_path", None)
        self._record_print_array_audit_event(
            "print_array_reset",
            f"Print array reset for {stock_id}",
            details={
                "reset_scope": "single_stock",
                "stock_id": stock_id,
                "affected_well_count": self._count_audit_assigned_wells(),
                "remaining_well_count_before_reset": remaining_before,
                "progress_file_path": progress_path,
            },
            level="warning",
        )
        return True

    def reset_all_arrays(self):
        """Resets the droplet count for all wells in the well plate for all stock solutions."""
        experiment_model = getattr(self.model, "experiment_model", None)
        can_reset = getattr(experiment_model, "can_reset_array_progress", None)
        if callable(can_reset) and not can_reset():
            message = (
                "Recorded dispense counts are physical progress and cannot be reset in "
                "place. Create an editable copy and finalize it as a new experiment instead."
            )
            self.error_occurred_signal.emit("Cannot reset recorded experiment", message)
            return False
        self.model.well_plate.reset_all_wells()
        self.model.experiment_model.create_progress_file()
        self.update_slots_signal.emit()
        progress_path = getattr(self.model.experiment_model, "progress_file_path", None)
        self._record_print_array_audit_event(
            "print_arrays_reset_all",
            "All print arrays reset",
            details={
                "reset_scope": "all_stocks",
                "affected_well_count": self._count_audit_assigned_wells(),
                "progress_file_path": progress_path,
            },
            level="warning",
        )
        return True

    def enter_print_mode(self):
        """Enter print mode."""
        self.machine.enter_print_mode()

    def exit_print_mode(self):
        """Exit print mode."""
        self.machine.exit_print_mode()

    def get_print_array_imaging_calibration_preflight(self):
        """Return imaging-calibration readiness for the loaded printer head."""
        profile_name = str(getattr(getattr(self, "profile", None), "name", "") or "").lower()
        if profile_name == "legacy":
            return {"ok": True, "code": "ok", "message": "", "record": None}

        try:
            printer_head = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            printer_head = None
        if printer_head is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "No printer head is loaded.",
                "record": None,
            }

        validator = getattr(
            getattr(self.model, "experiment_model", None),
            "validate_applied_imaging_calibration_for_print",
            None,
        )
        if not callable(validator):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model cannot confirm the applied imaging calibration.",
                "record": None,
            }

        validation = validator(
            printer_head=printer_head,
            machine_model=self.model.machine_model,
        )
        if not isinstance(validation, dict):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model returned an invalid imaging calibration result.",
                "record": None,
            }
        validation.setdefault("code", "ok" if validation.get("ok") else "validation_failed")
        validation.setdefault("message", "")
        validation.setdefault("record", None)
        return validation

    def get_print_array_refuel_check_preflight(self):
        """Return manual refuel-check readiness for the loaded printer head."""
        profile_name = str(getattr(getattr(self, "profile", None), "name", "") or "").lower()
        if profile_name == "legacy":
            return {"ok": True, "code": "not_required", "message": "", "record": None}

        try:
            printer_head = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            printer_head = None
        if printer_head is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "No printer head is loaded.",
                "record": None,
            }

        validator = getattr(
            getattr(self.model, "experiment_model", None),
            "validate_manual_refuel_check_for_print",
            None,
        )
        if not callable(validator):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model cannot confirm the manual refuel check.",
                "record": None,
            }

        validation = validator(
            printer_head=printer_head,
            machine_model=self.model.machine_model,
        )
        if not isinstance(validation, dict):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model returned an invalid manual refuel check result.",
                "record": None,
            }
        validation.setdefault("code", "ok" if validation.get("ok") else "validation_failed")
        validation.setdefault("message", "")
        validation.setdefault("record", None)
        return validation

    def record_manual_refuel_check_outcome(self, status, source, **kwargs):
        """Record an operator manual-refuel-check outcome for the loaded printer head."""
        try:
            printer_head = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            printer_head = None
        if printer_head is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "No printer head is loaded.",
                "record": None,
            }

        recorder = getattr(
            getattr(self.model, "experiment_model", None),
            "record_manual_refuel_check_outcome",
            None,
        )
        if not callable(recorder):
            return {
                "ok": False,
                "code": "recording_unavailable",
                "message": "Experiment model cannot record the manual refuel check.",
                "record": None,
            }

        try:
            return recorder(
                status=status,
                source=source,
                printer_head=printer_head,
                machine_model=self.model.machine_model,
                **kwargs,
            )
        except Exception as exc:
            return {
                "ok": False,
                "code": "recording_failed",
                "message": f"Could not record manual refuel check: {exc}",
                "record": None,
            }

    def mark_manual_refuel_check_deferred(self, source="post_apply_prompt"):
        return self.record_manual_refuel_check_outcome("deferred", source)

    def record_manual_refuel_check_bypass(self, source="print_array_preflight", reason="operator_bypass"):
        return self.record_manual_refuel_check_outcome(
            "bypassed",
            source,
            bypass_reason=reason,
        )

    def apply_applied_imaging_calibration_print_settings(self, record):
        """Apply PW and pressure from an applied imaging calibration record."""
        record = dict(record or {})
        try:
            pw_us = int(round(float(record.get("pw_us"))))
            pressure_psi = float(record.get("pressure_psi"))
        except Exception:
            return {
                "ok": False,
                "message": "Applied imaging calibration is missing usable PW or pressure settings.",
            }

        try:
            self.set_print_pulse_width(pw_us, manual=True)
            self.set_absolute_print_pressure(pressure_psi, manual=True)
        except Exception as exc:
            return {"ok": False, "message": f"Could not apply calibration settings: {exc}"}

        return {
            "ok": True,
            "message": (
                f"Set print pulse width to {pw_us} us and print pressure to "
                f"{pressure_psi:.3f} psi."
            ),
            "pw_us": pw_us,
            "pressure_psi": pressure_psi,
        }

    def _get_evap_plate_dock_check_reasons(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        getter = getattr(machine_model, "get_evap_plate_dock_check_reasons", None)
        if callable(getter):
            try:
                return sorted({str(reason) for reason in (getter() or []) if str(reason)})
            except Exception:
                pass

        reasons = set(getattr(machine_model, "_evap_plate_dock_check_reasons", set()) or set())
        if bool(getattr(machine_model, "evap_plate_dock_check_required_after_reset", False)):
            reasons.add("after_board_reset")
        return sorted(str(reason) for reason in reasons if str(reason))

    def _mark_evap_plate_dock_check_required(self, reason):
        reason = str(reason or "").strip()
        if not reason:
            return
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        marker = getattr(machine_model, "mark_evap_plate_dock_check_required", None)
        if callable(marker):
            marker(reason)
            return

        reasons = set(getattr(machine_model, "_evap_plate_dock_check_reasons", set()) or set())
        reasons.add(reason)
        setattr(machine_model, "_evap_plate_dock_check_reasons", reasons)
        if reason == "after_board_reset":
            setattr(machine_model, "evap_plate_dock_check_required_after_reset", True)

    def _clear_evap_plate_dock_check_required(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        clearer = getattr(machine_model, "clear_evap_plate_dock_check_required", None)
        if callable(clearer):
            clearer()
            return
        setattr(machine_model, "_evap_plate_dock_check_reasons", set())
        setattr(machine_model, "evap_plate_dock_check_required_after_reset", False)

    def get_evap_plate_dock_check_context(self, request_kind=None):
        """Return whether the operator must confirm the evaporation plate dock state."""
        kind = str(request_kind or "").strip().lower()
        if kind in {"resume_ready", "resume print", "resume_print"}:
            kind = "resume"
        elif kind not in {"start", "resume"}:
            kind = "resume" if self.get_array_run_state() == "resume_ready" else "start"

        reasons = []
        progress_status = None

        if kind == "start":
            experiment_model = getattr(getattr(self, "model", None), "experiment_model", None)
            get_status = getattr(experiment_model, "get_progress_status", None)
            if callable(get_status):
                try:
                    progress_status = dict(get_status() or {})
                except Exception as exc:
                    progress_status = {"error": str(exc) or exc.__class__.__name__}
                if not bool(progress_status.get("has_printed_progress", False)):
                    reasons.append("first_experiment_print")

        persistent_reasons = self._get_evap_plate_dock_check_reasons()
        reasons.extend(reason for reason in persistent_reasons if reason not in reasons)

        required = bool(reasons)
        message_parts = []
        if "first_experiment_print" in reasons:
            message_parts.append(
                "This is the first print array for the current experiment."
            )
        if "after_board_reset" in reasons:
            message_parts.append(
                "A board reset occurred since the last print array start or resume. "
                "Homing does not move the evaporation plate back to the dock."
            )
        if "array_hard_abort" in reasons:
            message_parts.append(
                "The previous print array was aborted before the evaporation plate could be confirmed parked."
            )
        if "soft_stop_clear_unconfirmed" in reasons:
            message_parts.append(
                "The previous soft stop could not confirm that queued motion was cleared, so the evaporation plate position is uncertain."
            )
        if "soft_stop_park_failed" in reasons:
            message_parts.append(
                "The previous soft stop could not complete its evaporation plate parking move."
            )
        if "array_park_failed" in reasons:
            message_parts.append(
                "The previous print array could not complete its evaporation plate parking move."
            )
        if "transport_fault" in reasons:
            message_parts.append(
                "A command transport fault interrupted the previous print array before parking was confirmed."
            )
        if "machine_disconnect" in reasons:
            message_parts.append(
                "The machine disconnected during the previous print array before parking was confirmed."
            )
        if required and not message_parts:
            message_parts.append(
                "A previous operation left the evaporation plate position uncertain."
            )
        elif not message_parts:
            message_parts.append("The evaporation plate dock check is not required.")
        message_parts.append(
            "Confirm the evaporation plate is seated in the dock position and the "
            "plate travel area is clear before continuing."
        )

        return {
            "required": required,
            "reasons": reasons,
            "title": "Evaporation Plate Dock Check",
            "message": "\n\n".join(message_parts),
            "request_kind": kind,
            "progress_status": progress_status,
        }
    
    def print_array(
        self,
        *,
        imaging_calibration_override=False,
        settings_mismatch_override=False,
        evap_plate_dock_confirmed=False,
        manual_refuel_check_bypass=False,
    ):
        '''
        Iterates through all wells with an assigned reaction and prints the 
        required number of droplets for the currently loaded printer head.
        '''
        experiment_model = getattr(self.model, "experiment_model", None)
        read_only_view_getter = getattr(
            self.model, "is_read_only_experiment_view_active", None
        )
        if callable(read_only_view_getter) and read_only_view_getter():
            message = (
                "This experiment is open read-only. It cannot be used for printing."
            )
            self.error_occurred_signal.emit("Error", message)
            print(f"Cannot print: {message}")
            return
        finalization_error_getter = getattr(
            experiment_model, "get_execution_plan_finalization_error", None
        )
        if callable(finalization_error_getter) and finalization_error_getter():
            message = (
                "This experiment was not finalized successfully. Printing is unavailable "
                "until it is finalized again or reset."
            )
            self.error_occurred_signal.emit('Error', message)
            print(f'Cannot print: {message}')
            return
        sync_error_getter = getattr(
            experiment_model, "get_execution_plan_sync_error", None
        )
        lock_plan = getattr(experiment_model, "lock_execution_plan", None)
        if (
            callable(sync_error_getter)
            and sync_error_getter()
            and not callable(lock_plan)
        ):
            message = (
                "The saved experiment data is incomplete. Printing is unavailable until "
                "the previous operation succeeds or the experiment is reset."
            )
            self.error_occurred_signal.emit('Error', message)
            print(f'Cannot print: {message}')
            return
        read_only_getter = getattr(experiment_model, "is_read_only_legacy_execution", None)
        if callable(read_only_getter) and read_only_getter():
            message = (
                "This older experiment is open view-only. It cannot be used for printing."
            )
            self.error_occurred_signal.emit('Error', message)
            print(f'Cannot print: {message}')
            return
        source_getter = getattr(experiment_model, "get_execution_plan_source", None)
        runtime_active_getter = getattr(
            experiment_model, "is_authoritative_execution_runtime_active", None
        )
        authoritative_runtime_active = bool(
            callable(runtime_active_getter) and runtime_active_getter()
        )
        if (
            callable(source_getter)
            and source_getter() == "persisted_execution_plan"
            and not authoritative_runtime_active
        ):
            message = (
                "This experiment is open for viewing but has not been loaded for printing. "
                "Select Load Experiment in the Experiment Editor first."
            )
            self.error_occurred_signal.emit('Error', message)
            print(f'Cannot print: {message}')
            return
        starting_state = self.get_array_run_state()
        if starting_state in {"running", "stop_requested"}:
            print('Cannot print: Array runner is already active')
            return

        if not self.check_if_all_completed():
            print('Cannot print: command queue is not empty')
            return

        if not self.model.well_plate.check_calibration_applied():
            self.error_occurred_signal.emit('Error','Calibration has not been applied to this plate')
            print('Cannot print: Calibration has not been applied')
            return
        
        if self.model.rack_model.get_gripper_info() == None:
            self.error_occurred_signal.emit('Error','No printer head is loaded')
            print('Cannot print: No printer head is loaded')
            return

        loaded_array = self.get_loaded_array_control_state()
        loaded_array_state = str(loaded_array.get("state") or "unavailable")
        if loaded_array_state in {"complete", "no_array"}:
            print(
                "Cannot print: "
                + (
                    "The loaded reagent array is already complete"
                    if loaded_array_state == "complete"
                    else "The loaded reagent has no assigned array"
                )
            )
            return
        if loaded_array_state not in {"not_started", "in_progress"}:
            message = str(
                loaded_array.get("error")
                or "The loaded reagent array status could not be determined."
            )
            self.error_occurred_signal.emit('Error', message)
            print(f'Cannot print: {message}')
            return
        request_kind = (
            "resume" if loaded_array_state == "in_progress" else "start"
        )

        authoritative_preflight = getattr(
            experiment_model, "validate_authoritative_print_context", None
        )
        if callable(authoritative_preflight):
            validation = authoritative_preflight(
                self.model.rack_model.get_gripper_printer_head()
            )
            if not bool(validation.get("ok")):
                technical_message = str(
                    validation.get("message")
                    or "The saved experiment does not match the loaded printer head."
                )
                message = (
                    "The loaded printer head or its saved calibration does not match this "
                    "experiment. Printing is unavailable."
                )
                self.error_occurred_signal.emit("Error", message)
                print(f"Cannot print: {technical_message}")
                return
        
        if not self.model.machine_model.regulating_print_pressure:
            self.error_occurred_signal.emit('Error','Pressure regulation is not enabled')
            print('Cannot print: Pressure regulation is not enabled')
            return

        validation = self.get_print_array_imaging_calibration_preflight()
        if not bool(validation.get("ok")):
            code = str(validation.get("code") or "")
            imaging_override_ok = (
                bool(imaging_calibration_override)
                and code in {"missing_record", "stale_design_volume"}
            )
            settings_override_ok = (
                bool(settings_mismatch_override)
                and code in {"pulse_width_mismatch", "pressure_mismatch"}
            )
            if not (imaging_override_ok or settings_override_ok):
                message = str(
                    validation.get("message")
                    or "No applied imaging calibration was found for the loaded printer head."
                )
                self.error_occurred_signal.emit('Error', message)
                print(f'Cannot print: {message}')
                return
            print(f"Print array imaging calibration override accepted: {code}")

        refuel_validation = self.get_print_array_refuel_check_preflight()
        if not bool(refuel_validation.get("ok")):
            code = str(refuel_validation.get("code") or "")
            bypass_ok = (
                bool(manual_refuel_check_bypass)
                and code in PROMPTABLE_MANUAL_REFUEL_CHECK_CODES
            )
            if not bypass_ok:
                message = str(
                    refuel_validation.get("message")
                    or "A passed manual refuel check is required before stream printing."
                )
                self.error_occurred_signal.emit('Error', message)
                print(f'Cannot print: {message}')
                return
            print(f"Print array manual refuel check bypass accepted: {code}")

        dock_check = self.get_evap_plate_dock_check_context(
            request_kind="resume" if starting_state == "resume_ready" else "start"
        )
        persistent_dock_reasons = [
            reason
            for reason in (dock_check.get("reasons") or [])
            if reason != "first_experiment_print"
        ]
        if bool(dock_check.get("required")) and not bool(evap_plate_dock_confirmed):
            message = str(
                dock_check.get("message")
                or "Confirm the evaporation plate is in the dock position before continuing."
            )
            self.error_occurred_signal.emit("Evaporation Plate Dock Check Required", message)
            print("Cannot print: evaporation plate dock confirmation is required")
            return

        current_head = self.model.rack_model.get_gripper_printer_head()
        current_stock_id = current_head.get_stock_id()
        endpoint_preflight = self._preflight_array_well_targets(current_stock_id)
        if not bool(endpoint_preflight.get("ok")):
            message = str(
                endpoint_preflight.get("message")
                or "The print-array endpoints could not be validated."
            )
            if not bool(endpoint_preflight.get("reported")):
                self.error_occurred_signal.emit(
                    "Print Array Preflight Failed",
                    message,
                )
            self._record_print_array_audit_event(
                "print_array_preflight_rejected",
                "Print array preflight rejected",
                details={
                    "request_kind": request_kind,
                    "preflight_code": endpoint_preflight.get("code"),
                    "well_id": endpoint_preflight.get("well_id"),
                    "machine_commands_queued": False,
                },
                level="error",
            )
            print(f"Cannot print: {message}")
            return

        if callable(lock_plan):
            try:
                stock_id = current_stock_id
                printer_head_id = str(
                    getattr(current_head, "printer_head_id", None) or ""
                )
                checkpoint_enabled = getattr(
                    experiment_model, "uses_durable_execution_checkpoint", None
                )
                pass_preparer = getattr(
                    experiment_model,
                    "prepare_authoritative_print_pass",
                    None,
                )
                if (
                    callable(pass_preparer)
                    and callable(checkpoint_enabled)
                    and checkpoint_enabled()
                ):
                    pass_preparer(
                        stock_id=stock_id,
                        printer_head_id=printer_head_id,
                    )
                else:
                    binding = getattr(
                        experiment_model, "ensure_execution_printer_head_binding", None
                    )
                    if (
                        callable(binding)
                        and experiment_model.get_execution_plan_snapshot() is not None
                    ):
                        binding(
                            stock_id=stock_id,
                            printer_head_id=printer_head_id,
                        )
                    else:
                        lock_plan("printing_started")
                    if callable(checkpoint_enabled) and checkpoint_enabled():
                        experiment_model.ensure_execution_resume_checkpoint()
            except Exception as exc:
                message = (
                    "Printing did not start because the experiment could not be saved in "
                    "its locked state. See the application logs for details."
                )
                print(f"Could not lock experiment before printing: {exc}")
                self.error_occurred_signal.emit("Error", message)
                print(f"Cannot print: {message}")
                return

        transport_resumed = False
        if starting_state == "resume_ready" and self.model.machine_model.transport_paused:
            self.resume_commands()
            transport_resumed = True

        if not self._start_array_run_context():
            print('Cannot print: No remaining droplets for the loaded stock')
            return
        if bool(evap_plate_dock_confirmed) and persistent_dock_reasons:
            self._clear_evap_plate_dock_check_required()
        self._record_print_array_audit_event(
            "print_array_requested",
            "Print array request accepted",
            details={
                "request_kind": request_kind,
                "imaging_calibration_override": bool(imaging_calibration_override),
                "settings_mismatch_override": bool(settings_mismatch_override),
                "evap_plate_dock_confirmed": bool(evap_plate_dock_confirmed),
                "evap_plate_dock_check_reasons": list(dock_check.get("reasons") or []),
            },
        )
        if request_kind == "resume":
            self._record_print_array_audit_event(
                "print_array_resumed",
                "Print array resumed",
                details={"transport_resumed": transport_resumed},
            )
        
        if self.close_gripper() is False:
            self.error_occurred_signal.emit(
                'Print Array Error',
                'Failed to queue the initial gripper close command',
            )
            self._complete_array_finalize("hard_abort")
            return
        # self.wait_command()

        self.move_to_location('pause',z_offset=-5000)
        self.move_to_location('pause', ignore_safe_height=True)
        if not self._apply_array_run_acceleration():
            self._complete_array_finalize("hard_abort")
            return
        # self.machine.change_acceleration(16000)
        # self.enter_print_mode()
        if self.enable_print_profile(deferred_gripper_refresh=True) is False:
            self.error_occurred_signal.emit(
                'Print Array Error',
                'Failed to enable the print-array pressure and gripper profile',
            )
            self._complete_array_finalize("hard_abort")
            return
        self._array_context["print_profile_enable_queued"] = True

        self._set_array_run_state("running")
        lookahead_added = self._fill_array_lookahead()
        if self.get_array_run_state() == "running":
            self._record_print_array_audit_event(
                "print_array_started",
                "Print array started",
                details={"lookahead_added": bool(lookahead_added)},
            )
            
    def enable_print_profile(self, *, deferred_gripper_refresh=False):
        """Enable the print profile."""
        return self.machine.enable_print_profile(
            deferred_gripper_refresh=deferred_gripper_refresh
        )

    def disable_print_profile(self):
        """Disable the print profile."""
        return self.machine.disable_print_profile()
    
    def start_refuel_camera(self):
        if self._reject_physical_action("refuel camera start") is not None:
            return
        self.machine.start_refuel_camera()
        try:
            self.machine.refuel_led_on()
        except Exception:
            try:
                self.machine.refuel_led_off()
            except Exception:
                pass
            try:
                self.machine.stop_refuel_camera()
            except Exception:
                pass
            raise

    def _build_refuel_capture_context(self):
        machine_model = getattr(self.model, "machine_model", None)
        context = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "monotonic_s": time.monotonic(),
            "print_pressure": None,
            "refuel_pressure": None,
            "print_pulse_width": None,
            "refuel_pulse_width": None,
            "location": "",
        }
        if machine_model is None:
            return context

        getters = (
            ("print_pressure", "get_current_print_pressure"),
            ("refuel_pressure", "get_current_refuel_pressure"),
            ("print_pulse_width", "get_print_pulse_width"),
            ("refuel_pulse_width", "get_refuel_pulse_width"),
            ("location", "get_current_location"),
        )
        for key, getter_name in getters:
            getter = getattr(machine_model, getter_name, None)
            if callable(getter):
                try:
                    context[key] = getter()
                except Exception:
                    pass
        return context

    def capture_refuel_image(self):
        if self._reject_physical_action("refuel camera capture") is not None:
            return None
        frame, _context = self.capture_refuel_image_with_context(analyze=True)
        return frame

    def capture_refuel_image_with_context(self, *, analyze=True, context_overrides=None):
        blocked = self._reject_physical_action("refuel camera capture")
        if blocked is not None:
            return None, {
                "analysis_started": False,
                "frame_signature_available": False,
                "blocked_reason": blocked,
            }
        capture_start = time.perf_counter()
        frame = self.machine.capture_refuel_image()
        capture_duration_ms = float((time.perf_counter() - capture_start) * 1000.0)
        context = self._build_refuel_capture_context()
        context["refuel_monitor_capture_duration_ms"] = capture_duration_ms
        if context_overrides:
            context.update(dict(context_overrides))
        refuel_model = getattr(getattr(self, "model", None), "refuel_camera_model", None)
        if frame is None:
            context["analysis_started"] = False
            context["frame_signature_available"] = False
            return None, context
        signature_builder = getattr(refuel_model, "build_refuel_frame_signature", None)
        if callable(signature_builder):
            signature_start = time.perf_counter()
            try:
                context.update(signature_builder(frame, update_previous=True))
            except Exception:
                context["frame_signature_available"] = False
                context["frame_signature_duration_ms"] = float((time.perf_counter() - signature_start) * 1000.0)
        else:
            context["frame_signature_available"] = False
        if context.get("refuel_monitor_tick_index") is not None:
            capture_counter = getattr(refuel_model, "record_refuel_monitor_frame_captured", None)
            if callable(capture_counter):
                try:
                    context["captured_frame_count"] = capture_counter()
                except Exception:
                    pass
        if analyze:
            context["analysis_started"] = bool(refuel_model.start_analysis(frame, context=context))
        else:
            context["analysis_started"] = False
        return frame, context

    def get_refuel_capture_context(self):
        return self._build_refuel_capture_context()

    def run_refuel_balance_burst(self, droplet_count, settle_ms, on_complete=None, on_error=None):
        if not self.machine.check_if_all_completed():
            msg = "Cannot start refuel burst: command queue is not empty."
            if callable(on_error):
                on_error(msg)
            return False
        if not self.model.machine_model.regulating_print_pressure:
            msg = "Cannot start refuel burst: print pressure regulation is not enabled."
            if callable(on_error):
                on_error(msg)
            return False

        droplet_count = max(1, int(droplet_count))
        settle_ms = max(1, int(settle_ms))

        def _burst_complete_handler():
            if callable(on_complete):
                on_complete(self._build_refuel_capture_context())

        ok_print = self.machine.print_droplets(droplet_count, manual=True)
        if ok_print is False:
            msg = "Failed to enqueue refuel balance print burst."
            if callable(on_error):
                on_error(msg)
            return False
        self._record_refuel_ejection_event(
            droplet_count,
            source="Controller.run_refuel_balance_burst",
            event_kind="refuel_balance_burst_queued",
            count_kind="commanded",
            payload={"manual": True, "settle_ms": settle_ms},
        )

        ok_wait = self.machine.wait_ms(settle_ms, handler=_burst_complete_handler, manual=True)
        if ok_wait is False:
            msg = "Failed to enqueue refuel balance settle delay."
            if callable(on_error):
                on_error(msg)
            return False

        return True

    def stop_refuel_camera(self):
        if self._reject_physical_action("refuel camera stop") is not None:
            return
        stop_error = None
        try:
            self.machine.stop_refuel_camera()
        except Exception as exc:
            stop_error = exc

        try:
            self.machine.refuel_led_off()
        except Exception:
            raise

        if stop_error is not None:
            raise stop_error

    def start_droplet_camera(self):
        if self._reject_physical_action("droplet camera start") is not None:
            return
        self.machine.start_droplet_camera()

    def _ensure_capture_coordinator(self):
        coordinator = getattr(self, "capture_coordinator", None)
        if coordinator is None:
            coordinator = CaptureCoordinator()
            self.capture_coordinator = coordinator
        if (
            bool(self.__dict__.get("pending_capture_active", False))
            and not bool(getattr(coordinator, "pending_active", False))
        ):
            request_id = self.__dict__.get("pending_capture_request_id") or uuid.uuid4().hex
            started = self.__dict__.get("pending_capture_started_monotonic")
            coordinator.adopt_active_request(
                request_id,
                context=self.__dict__.get("pending_capture_context"),
                source=CaptureSource.CONTROLLER,
                created_at_monotonic=started,
                callback=self.__dict__.get("pending_capture_callback"),
                started_monotonic=started,
                recovery_attempted=bool(self.__dict__.get("pending_capture_recovery_attempted", False)),
                throughput_mode=bool(self.__dict__.get("pending_capture_throughput_mode", False)),
            )
        self._sync_legacy_pending_capture_fields(coordinator)
        return coordinator

    def _capture_pending_snapshot(self):
        coordinator = self._ensure_capture_coordinator()
        snapshot = coordinator.pending_snapshot()
        self._sync_legacy_pending_capture_fields(coordinator)
        return snapshot

    def _pending_capture_active(self):
        return bool(self._capture_pending_snapshot().get("active"))

    def _pending_capture_request_id(self):
        return self._capture_pending_snapshot().get("request_id")

    @staticmethod
    def _identity_int_or_none(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _capture_expected_identity_metadata(self, *, request_id, capture_context, state, queued_monotonic_ns):
        state = dict(state or {}) if isinstance(state, dict) else {}
        return {
            "expected_generation": self._identity_int_or_none(state.get("generation")),
            "expected_backend_id": state.get("backend_id"),
            "queued_machine_request_id": state.get("request_id") or request_id,
            "queued_machine_cap_id": self._identity_int_or_none(state.get("cap_id")),
            "queued_machine_state": dict(state),
            "queued_monotonic_ns": int(queued_monotonic_ns),
            "capture_context": capture_context,
        }

    def _record_expected_capture_identity(self, *, request_id, capture_context, queued_monotonic_ns):
        state = self._get_droplet_capture_state()
        metadata = self._capture_expected_identity_metadata(
            request_id=request_id,
            capture_context=capture_context,
            state=state,
            queued_monotonic_ns=queued_monotonic_ns,
        )
        try:
            coordinator = self._ensure_capture_coordinator()
            coordinator.update_active_request_metadata(metadata)
            self._sync_legacy_pending_capture_fields(coordinator)
        except Exception:
            pass
        return metadata

    def _capture_completion_identity_mismatch(self, payload, pending_snapshot):
        if not bool(pending_snapshot.get("active")):
            return "no_active_pending_capture"
        request_id = payload.get("request_id")
        expected_request_id = pending_snapshot.get("request_id")
        if str(request_id) != str(expected_request_id):
            return "request_id_mismatch"

        request = pending_snapshot.get("request")
        request_metadata = {}
        if request is not None:
            try:
                request_metadata = dict(getattr(request, "metadata", {}) or {})
            except Exception:
                request_metadata = {}
        expected_generation = self._identity_int_or_none(request_metadata.get("expected_generation"))
        if expected_generation is not None:
            payload_generation = self._identity_int_or_none(payload.get("generation"))
            if payload_generation is None:
                return "missing_generation"
            if payload_generation != expected_generation:
                return "generation_mismatch"
        expected_backend_id = request_metadata.get("expected_backend_id")
        payload_backend_id = payload.get("backend_id")
        if expected_backend_id not in (None, "") and payload_backend_id not in (None, ""):
            if str(payload_backend_id) != str(expected_backend_id):
                return "backend_id_mismatch"
        return None

    def _capture_completion_identity_metadata(self, *, payload, pending_snapshot, mismatch_reason):
        request = pending_snapshot.get("request")
        request_metadata = {}
        if request is not None:
            try:
                request_metadata = dict(getattr(request, "metadata", {}) or {})
            except Exception:
                request_metadata = {}
        return {
            "mismatch_reason": str(mismatch_reason),
            "request_id": payload.get("request_id"),
            "expected_request_id": pending_snapshot.get("request_id"),
            "status": payload.get("status"),
            "generation": payload.get("generation"),
            "expected_generation": request_metadata.get("expected_generation"),
            "backend_id": payload.get("backend_id"),
            "expected_backend_id": request_metadata.get("expected_backend_id"),
            "cap_id": payload.get("cap_id"),
            "capture_context": payload.get("capture_context"),
            "expected_capture_context": pending_snapshot.get("context"),
            "state": self._get_droplet_capture_state(),
        }

    @staticmethod
    def _normalized_flash_safety_state(state=None):
        data = dict(state or {}) if isinstance(state, dict) else {}
        return {
            "flash_session_armed": bool(data.get("flash_session_armed", False)),
            "flash_fault_latched": bool(data.get("flash_fault_latched", False)),
            "flash_fault_reason": str(data.get("flash_fault_reason", "") or ""),
        }

    def _get_model_flash_safety_state(self):
        state = {
            "flash_session_armed": False,
            "flash_fault_latched": False,
            "flash_fault_reason": "",
        }
        cam = getattr(self.model, "droplet_camera_model", None)
        armed_getter = getattr(cam, "get_flash_session_armed", None)
        fault_getter = getattr(cam, "get_flash_fault_latched", None)
        reason_getter = getattr(cam, "get_flash_fault_reason", None)
        if callable(armed_getter):
            state["flash_session_armed"] = bool(armed_getter())
        else:
            state["flash_session_armed"] = bool(getattr(cam, "flash_session_armed", False))
        if callable(fault_getter):
            state["flash_fault_latched"] = bool(fault_getter())
        else:
            state["flash_fault_latched"] = bool(getattr(cam, "flash_fault_latched", False))
        if callable(reason_getter):
            state["flash_fault_reason"] = str(reason_getter() or "")
        else:
            state["flash_fault_reason"] = str(getattr(cam, "flash_fault_reason", "") or "")
        return self._normalized_flash_safety_state(state)

    def _get_machine_flash_safety_state(self):
        getter = getattr(self.machine, "get_flash_safety_state", None)
        if callable(getter):
            return self._normalized_flash_safety_state(getter())
        return self._normalized_flash_safety_state({})

    def _get_flash_safety_state(self):
        errors = {}
        try:
            model_state = self._get_model_flash_safety_state()
        except Exception as exc:
            model_state = self._normalized_flash_safety_state({})
            errors["model_flash_state_error"] = str(exc)
        try:
            machine_state = self._get_machine_flash_safety_state()
        except Exception as exc:
            machine_state = self._normalized_flash_safety_state({})
            errors["machine_flash_state_error"] = str(exc)

        fault_sources = []
        if model_state.get("flash_fault_latched"):
            fault_sources.append("model")
        if machine_state.get("flash_fault_latched"):
            fault_sources.append("machine")
        armed_sources = []
        if model_state.get("flash_session_armed"):
            armed_sources.append("model")
        if machine_state.get("flash_session_armed"):
            armed_sources.append("machine")

        fault_latched = bool(fault_sources)
        fault_reason = ""
        if fault_latched:
            fault_reason = (
                str(machine_state.get("flash_fault_reason") or "")
                or str(model_state.get("flash_fault_reason") or "")
            )
        normalized = {
            "flash_session_armed": bool(armed_sources) and not fault_latched,
            "flash_fault_latched": fault_latched,
            "flash_fault_reason": fault_reason,
            "model_flash_state": dict(model_state),
            "machine_flash_state": dict(machine_state),
            "flash_fault_source": ",".join(fault_sources),
            "flash_armed_source": ",".join(armed_sources),
        }
        normalized.update(errors)
        return normalized

    def _classify_flash_safety_state(self, state):
        state = dict(state or {})
        if bool(state.get("flash_fault_latched", False)):
            metadata = {
                "flash_fault_latched": True,
                "flash_fault_reason": str(state.get("flash_fault_reason", "") or ""),
                "flash_fault_source": str(state.get("flash_fault_source", "") or ""),
                "flash_safety_state": dict(state),
            }
            return CaptureStatus.FIRMWARE_FLASH_LATCHED, "firmware_flash_latched", metadata
        return None

    def _process_flash_preflight_events(self, poll_ms):
        try:
            app = QtCore.QCoreApplication.instance()
        except Exception:
            app = None
        if app is not None:
            try:
                app.processEvents(QtCore.QEventLoop.AllEvents, max(1, int(poll_ms)))
                return
            except Exception:
                pass
        time.sleep(max(0.0, float(poll_ms) / 1000.0))

    def _flash_preflight_failure_result(
        self,
        *,
        request_id,
        callback,
        capture_context,
        status,
        reason,
        state,
        recovery_attempted=False,
    ):
        reason = str(reason or "flash_disarmed")
        status = status if isinstance(status, CaptureStatus) else CaptureStatus(status)
        metadata = {
            "request_id": request_id,
            "capture_context": capture_context,
            "rejection_reason": reason,
            "rejection_state": dict(state or {}),
            "flash_fault_reason": str((state or {}).get("flash_fault_reason", "") or ""),
            "flash_fault_source": str((state or {}).get("flash_fault_source", "") or ""),
            "recovery_attempted": bool(recovery_attempted),
        }
        self.last_capture_queue_rejection_reason = reason
        self.last_capture_queue_rejection_state = dict(state or {})
        self.record_droplet_capture_performance_marker(
            "flash_preflight_failed",
            {
                "request_id": request_id,
                "capture_context": capture_context,
                "status": status.value,
                "reason": reason,
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        self._record_active_calibration_event(
            "capture_flash_preflight_failed",
            dict(metadata),
            level="warning",
        )
        self._clear_pending_capture(callback=callback, capture_context=capture_context)
        if callback is not None:
            try:
                setattr(callback, "_capture_rejection_reason", reason)
                setattr(callback, "_capture_rejection_state", dict(state or {}))
            except Exception:
                pass
            self._attach_capture_callback_result_metadata(
                callback,
                request_id=request_id,
                status=status,
                metadata=metadata,
            )
            try:
                callback(None)
            except Exception as exc:
                print(f"Callback raised after flash preflight failure: {exc}")
        return CaptureResult.failure(
            request_id,
            status,
            metadata=metadata,
            reason=reason,
            source=CaptureSource.CONTROLLER,
        )

    def _run_flash_session_preflight(
        self,
        *,
        request_id,
        callback,
        capture_context,
        recovery_attempted=False,
    ):
        coordinator = self._ensure_capture_coordinator()
        monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
        started = monotonic_fn()
        self.record_droplet_capture_performance_marker(
            "flash_preflight_started",
            {
                "request_id": request_id,
                "capture_context": capture_context,
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        coordinator.begin_flash_preflight(
            request_id,
            context=capture_context,
            started_monotonic=started,
            metadata={
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        timeout_ms = max(0, int(getattr(self, "flash_session_preflight_timeout_ms", 500)))
        poll_ms = max(1, int(getattr(self, "flash_session_preflight_poll_ms", 25)))
        deadline = time.monotonic() + (float(timeout_ms) / 1000.0)

        while True:
            pending = coordinator.pending_snapshot()
            if (not bool(pending.get("active"))) or str(pending.get("request_id")) != str(request_id):
                state = self._get_flash_safety_state()
                self.record_droplet_capture_performance_marker(
                    "flash_preflight_cancelled",
                    {
                        "request_id": request_id,
                        "capture_context": capture_context,
                        "reason": "capture_cancelled",
                    },
                )
                return CaptureResult.cancelled(
                    request_id,
                    metadata={
                        "capture_context": capture_context,
                        "rejection_reason": "capture_cancelled",
                        "rejection_state": state,
                    },
                    reason="capture_cancelled",
                    source=CaptureSource.CONTROLLER,
                )

            state = self._get_flash_safety_state()
            flash_block = self._classify_flash_safety_state(state)
            if flash_block is not None:
                status, reason, block_metadata = flash_block
                failure_state = dict(state)
                failure_state.update(block_metadata)
                return self._flash_preflight_failure_result(
                    request_id=request_id,
                    callback=callback,
                    capture_context=capture_context,
                    status=status,
                    reason=reason,
                    state=failure_state,
                    recovery_attempted=recovery_attempted,
                )
            if bool(state.get("flash_session_armed", False)):
                session = coordinator.arm_flash_session(
                    request_id,
                    context=capture_context,
                    armed_monotonic=monotonic_fn(),
                    metadata={"flash_safety_state": state},
                )
                self._record_active_calibration_event(
                    "capture_flash_preflight_armed",
                    {
                        "request_id": request_id,
                        "capture_context": capture_context,
                        "session_id": None if session is None else session.session_id,
                        "state": state,
                    },
                )
                self.record_droplet_capture_performance_marker(
                    "flash_preflight_armed",
                    {
                        "request_id": request_id,
                        "capture_context": capture_context,
                        "session_id": None if session is None else session.session_id,
                    },
                )
                return True

            if timeout_ms <= 0 or time.monotonic() >= deadline:
                return self._flash_preflight_failure_result(
                    request_id=request_id,
                    callback=callback,
                    capture_context=capture_context,
                    status=CaptureStatus.FLASH_DISARMED,
                    reason="flash_disarmed",
                    state=state,
                    recovery_attempted=recovery_attempted,
                )
            self._process_flash_preflight_events(min(poll_ms, max(1, int((deadline - time.monotonic()) * 1000))))

    def get_droplet_capture_ui_state(self):
        coordinator = self._ensure_capture_coordinator()
        snapshot = coordinator.pending_snapshot()
        flash_snapshot = coordinator.flash_session_snapshot()
        flash_state = self._get_flash_safety_state()
        self._sync_legacy_pending_capture_fields(coordinator)
        last_result = getattr(coordinator, "last_result", None)
        last_status = getattr(last_result, "status", None)
        if last_status is not None:
            last_status = getattr(last_status, "value", last_status)
        return {
            "pending_active": bool(snapshot.get("active")),
            "pending_request_id": snapshot.get("request_id"),
            "pending_context": snapshot.get("context"),
            "pending_started_monotonic": snapshot.get("started_monotonic"),
            "pending_recovery_attempted": bool(snapshot.get("recovery_attempted", False)),
            "pending_throughput_mode": bool(snapshot.get("throughput_mode", False)),
            "coordinator_state": getattr(getattr(coordinator, "state", None), "value", getattr(coordinator, "state", None)),
            "last_result_status": last_status,
            "last_result_reason": "" if last_result is None else str(getattr(last_result, "reason", "") or ""),
            "last_result_stale": False if last_result is None else bool(getattr(last_result, "stale", False)),
            "last_result_dirty_shutdown": False if last_result is None else bool(getattr(last_result, "dirty_shutdown", False)),
            "dirty_shutdown": bool(getattr(self, "droplet_imager_dirty_shutdown", False)),
            "flash_session_armed": bool(flash_snapshot.get("armed")),
            "flash_session_request_id": flash_snapshot.get("request_id"),
            "flash_session_context": flash_snapshot.get("context"),
            "flash_preflight_active": bool(flash_snapshot.get("preflight_active")),
            "flash_fault_latched": bool(flash_state.get("flash_fault_latched", False)),
            "flash_fault_reason": str(flash_state.get("flash_fault_reason", "") or ""),
            "flash_fault_status": (
                CaptureStatus.FIRMWARE_FLASH_LATCHED.value
                if bool(flash_state.get("flash_fault_latched", False))
                else ""
            ),
        }

    def _sync_legacy_pending_capture_fields(self, coordinator=None):
        if coordinator is None:
            coordinator = getattr(self, "capture_coordinator", None)
        if coordinator is None:
            snapshot = {
                "active": False,
                "request_id": None,
                "callback": None,
                "context": None,
                "started_monotonic": None,
                "recovery_attempted": False,
                "throughput_mode": False,
            }
        else:
            snapshot = coordinator.pending_snapshot()
        self.pending_capture_callback = snapshot.get("callback")
        self.pending_capture_context = snapshot.get("context")
        self.pending_capture_active = bool(snapshot.get("active"))
        self.pending_capture_request_id = snapshot.get("request_id")
        self.pending_capture_started_monotonic = snapshot.get("started_monotonic")
        self.pending_capture_recovery_attempted = bool(snapshot.get("recovery_attempted", False))
        self.pending_capture_throughput_mode = bool(snapshot.get("throughput_mode", False))

    def mark_droplet_imager_force_close(self, reason="imager_force_close"):
        self.droplet_imager_dirty_shutdown = True
        coordinator = self._ensure_capture_coordinator()
        snapshot = coordinator.pending_snapshot()
        metadata = {
            "reason": str(reason or "imager_force_close"),
            "pending_context": snapshot.get("context"),
            "pending_request_id": snapshot.get("request_id"),
        }
        detach_result = coordinator.detach_pending_for_force_close(
            reason=str(reason or "imager_force_close"),
            metadata=metadata,
        )
        if detach_result is not None:
            self._stop_pending_capture_guard()
        self._sync_legacy_pending_capture_fields(coordinator)
        return {
            "dirty_shutdown": True,
            "detached": detach_result is not None,
            "result_status": None if detach_result is None else detach_result.status.value,
            "reason": str(reason or "imager_force_close"),
        }

    def _record_capture_coordinator_success(self, request_id, frame, *, metadata=None, reason=""):
        if request_id is None:
            return
        try:
            coordinator = self._ensure_capture_coordinator()
            pending_before = coordinator.pending_snapshot()
            if frame is None:
                coordinator.complete_failure(
                    request_id,
                    status=CaptureStatus.INTERNAL_ERROR,
                    metadata=metadata,
                    reason=reason or "capture_completed_without_frame",
                )
                self._sync_legacy_pending_capture_fields(coordinator)
                if bool(pending_before.get("active")) and str(pending_before.get("request_id")) == str(request_id):
                    self.record_droplet_capture_performance_marker(
                        "controller_pending_cleared",
                        {
                            "request_id": request_id,
                            "capture_context": pending_before.get("context"),
                            "terminal_status": CaptureStatus.INTERNAL_ERROR.value,
                        },
                    )
                return
            coordinator.complete_success(request_id, frame, metadata=metadata, reason=reason)
            self._sync_legacy_pending_capture_fields(coordinator)
            if bool(pending_before.get("active")) and str(pending_before.get("request_id")) == str(request_id):
                self.record_droplet_capture_performance_marker(
                    "controller_pending_cleared",
                    {
                        "request_id": request_id,
                        "capture_context": pending_before.get("context"),
                        "terminal_status": CaptureStatus.SUCCESS.value,
                    },
                )
        except Exception:
            pass

    def _record_capture_coordinator_failure(
        self,
        request_id,
        *,
        status=CaptureStatus.INTERNAL_ERROR,
        metadata=None,
        reason="",
        retryable=False,
        recoverable=False,
    ):
        if request_id is None:
            return
        try:
            coordinator = self._ensure_capture_coordinator()
            pending_before = coordinator.pending_snapshot()
            coordinator.complete_failure(
                request_id,
                status=status,
                metadata=metadata,
                reason=reason,
                retryable=retryable,
                recoverable=recoverable,
            )
            self._sync_legacy_pending_capture_fields(coordinator)
            if bool(pending_before.get("active")) and str(pending_before.get("request_id")) == str(request_id):
                result_status = getattr(status, "value", status)
                self.record_droplet_capture_performance_marker(
                    "controller_pending_cleared",
                    {
                        "request_id": request_id,
                        "capture_context": pending_before.get("context"),
                        "terminal_status": result_status,
                    },
                )
        except Exception:
            pass

    def _record_capture_coordinator_stale(self, request_id, *, metadata=None, reason="stale_completion_ignored"):
        try:
            coordinator = self._ensure_capture_coordinator()
            coordinator.record_stale_completion(
                request_id,
                metadata=metadata,
                reason=reason,
            )
            self._sync_legacy_pending_capture_fields(coordinator)
        except Exception:
            pass

    def _record_capture_coordinator_cancelled(self, *, metadata=None, reason="capture_cancelled"):
        try:
            coordinator = self._ensure_capture_coordinator()
            pending_before = coordinator.pending_snapshot()
            result = coordinator.cancel_pending(
                metadata=metadata,
                reason=reason,
            )
            self._sync_legacy_pending_capture_fields(coordinator)
            if result is not None and bool(pending_before.get("active")):
                self.record_droplet_capture_performance_marker(
                    "controller_pending_cleared",
                    {
                        "request_id": pending_before.get("request_id"),
                        "capture_context": pending_before.get("context"),
                        "terminal_status": CaptureStatus.CANCELLED.value,
                    },
                )
            return result
        except Exception:
            return None

    def capture_droplet_image(self, callback=None, *, throughput_mode=False, capture_context=None):
        """
        Initiates a non-blocking image capture. If a callback is provided,
        it will be invoked with the captured frame once the capture completes.
        """
        if self._reject_physical_action("droplet camera capture") is not None:
            self._notify_capture_callback_failed(callback)
            return False
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None
        self.record_droplet_capture_performance_marker(
            "controller_capture_requested",
            {
                "capture_context": capture_context,
                "throughput_mode": bool(throughput_mode),
                "callback_present": callback is not None,
            },
        )
        pending_snapshot = self._capture_pending_snapshot()
        if bool(pending_snapshot.get("active")):
            state = self._get_droplet_capture_state()
            self.last_capture_queue_rejection_reason = "controller_pending"
            self.last_capture_queue_rejection_state = state
            self.record_droplet_capture_performance_marker(
                "controller_capture_rejected",
                {
                    "reason": "controller_pending",
                    "pending_request_id": pending_snapshot.get("request_id"),
                    "capture_context": capture_context,
                    "throughput_mode": bool(throughput_mode),
                },
            )
            print(
                "[Camera] capture rejected: reason=controller_pending "
                f"pending_request_id={pending_snapshot.get('request_id')} state={state}"
            )
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {
                    "reason": "controller_pending",
                    "pending_request_id": pending_snapshot.get("request_id"),
                    "state": state,
                },
                level="warning",
            )
            self._notify_capture_callback_failed(callback)
            return False
        if capture_context is not None and pending_snapshot.get("context") is not None:
            state = self._get_droplet_capture_state()
            self.last_capture_queue_rejection_reason = "context_pending"
            self.last_capture_queue_rejection_state = state
            self.record_droplet_capture_performance_marker(
                "controller_capture_rejected",
                {
                    "reason": "context_pending",
                    "pending_request_id": pending_snapshot.get("request_id"),
                    "capture_context": capture_context,
                    "throughput_mode": bool(throughput_mode),
                },
            )
            print(f"[Camera] capture rejected: reason=context_pending state={state}")
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {"reason": "context_pending", "capture_context": capture_context, "state": state},
                level="warning",
            )
            self._notify_capture_callback_failed(callback)
            return False
        if callback is not None:
            if pending_snapshot.get("callback") is not None:
                state = self._get_droplet_capture_state()
                self.last_capture_queue_rejection_reason = "callback_pending"
                self.last_capture_queue_rejection_state = state
                self.record_droplet_capture_performance_marker(
                    "controller_capture_rejected",
                    {
                        "reason": "callback_pending",
                        "pending_request_id": pending_snapshot.get("request_id"),
                        "capture_context": capture_context,
                        "throughput_mode": bool(throughput_mode),
                    },
                )
                print(f"[Camera] capture rejected: reason=callback_pending state={state}")
                self._record_active_calibration_event(
                    "capture_queue_rejected",
                    {"reason": "callback_pending", "state": state},
                    level="warning",
                )
                self._notify_capture_callback_failed(callback)
                return False
        monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
        coordinator = self._ensure_capture_coordinator()
        outcome = coordinator.request_capture(
            context=capture_context,
            source=CaptureSource.CONTROLLER,
            created_at_monotonic=monotonic_fn(),
            metadata={"throughput_mode": bool(throughput_mode), "recovery_attempted": False},
            callback=callback,
            recovery_attempted=False,
            throughput_mode=throughput_mode,
            delegate=lambda request: self._queue_capture_request(
                callback=callback,
                throughput_mode=throughput_mode,
                capture_context=capture_context,
                recovery_attempted=False,
                capture_request_id=request.request_id,
            ),
        )
        return bool(outcome.accepted)

    def _queue_capture_request(
        self,
        *,
        callback=None,
        throughput_mode=False,
        capture_context=None,
        recovery_attempted=False,
        capture_request_id=None,
    ):
        capture_request_id = str(capture_request_id or uuid.uuid4().hex)
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None
        monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
        started_monotonic = monotonic_fn()
        coordinator = self._ensure_capture_coordinator()
        coordinator.adopt_active_request(
            capture_request_id,
            context=capture_context,
            source=CaptureSource.CONTROLLER,
            created_at_monotonic=started_monotonic,
            callback=callback,
            started_monotonic=started_monotonic,
            recovery_attempted=bool(recovery_attempted),
            throughput_mode=bool(throughput_mode),
            metadata={
                "throughput_mode": bool(throughput_mode),
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        self._sync_legacy_pending_capture_fields(coordinator)
        self.record_droplet_capture_performance_marker(
            "controller_pending_set",
            {
                "request_id": capture_request_id,
                "capture_context": capture_context,
                "throughput_mode": bool(throughput_mode),
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        preflight_result = self._run_flash_session_preflight(
            request_id=capture_request_id,
            callback=callback,
            capture_context=capture_context,
            recovery_attempted=recovery_attempted,
        )
        if isinstance(preflight_result, CaptureResult):
            self.record_droplet_capture_performance_marker(
                "controller_capture_rejected",
                {
                    "request_id": capture_request_id,
                    "capture_context": capture_context,
                    "throughput_mode": bool(throughput_mode),
                    "recovery_attempted": bool(recovery_attempted),
                    "status": getattr(getattr(preflight_result, "status", None), "value", getattr(preflight_result, "status", None)),
                    "reason": str(getattr(preflight_result, "reason", "") or ""),
                },
            )
            return preflight_result
        self._sync_legacy_pending_capture_fields(coordinator)
        try:
            capture_method = self.machine.capture_droplet_image
            accepts_request_id = True
            try:
                signature = inspect.signature(capture_method)
                accepts_request_id = (
                    "capture_request_id" in signature.parameters
                    or any(
                        param.kind == inspect.Parameter.VAR_KEYWORD
                        for param in signature.parameters.values()
                    )
                )
                accepts_context = (
                    "capture_context" in signature.parameters
                    or any(
                        param.kind == inspect.Parameter.VAR_KEYWORD
                        for param in signature.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                accepts_request_id = True
                accepts_context = True
            if accepts_request_id:
                kwargs = {
                    "throughput_mode": throughput_mode,
                    "capture_request_id": capture_request_id,
                }
                if accepts_context:
                    kwargs["capture_context"] = capture_context
                queued = capture_method(**kwargs)
            else:
                queued = capture_method(throughput_mode=throughput_mode)
        except Exception:
            self.record_droplet_capture_performance_marker(
                "machine_capture_exception",
                {
                    "request_id": capture_request_id,
                    "capture_context": capture_context,
                    "throughput_mode": bool(throughput_mode),
                    "recovery_attempted": bool(recovery_attempted),
                },
            )
            self._clear_pending_capture(callback=callback, capture_context=capture_context)
            raise
        if queued is False:
            state = self._get_droplet_capture_state()
            reason = self._classify_capture_queue_rejection(state)
            self.last_capture_queue_rejection_reason = reason
            self.last_capture_queue_rejection_state = state
            print(
                f"[Camera] capture rejected by machine request_id={capture_request_id} "
                f"reason={reason} state={state}"
            )
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {
                    "request_id": capture_request_id,
                    "reason": reason,
                    "state": state,
                    "capture_context": capture_context,
                    "recovery_attempted": bool(recovery_attempted),
                },
                level="warning",
            )
            self.record_droplet_capture_performance_marker(
                "machine_capture_rejected",
                {
                    "request_id": capture_request_id,
                    "reason": reason,
                    "state": state,
                    "capture_context": capture_context,
                    "throughput_mode": bool(throughput_mode),
                    "recovery_attempted": bool(recovery_attempted),
                },
            )
            self._clear_pending_capture(callback=callback, capture_context=capture_context)
            self._notify_capture_callback_failed(callback)
            coordinator.disarm_flash_session(
                reason=reason,
                request_id=capture_request_id,
                metadata={
                    "state": state,
                    "capture_context": capture_context,
                    "recovery_attempted": bool(recovery_attempted),
                },
            )
            return False
        queued_monotonic_ns = time.monotonic_ns()
        expected_identity = self._record_expected_capture_identity(
            request_id=capture_request_id,
            capture_context=capture_context,
            queued_monotonic_ns=queued_monotonic_ns,
        )
        self._sync_legacy_pending_capture_fields(coordinator)
        self._start_pending_capture_guard(throughput_mode=throughput_mode)
        print(
            f"[Camera] capture request queued request_id={capture_request_id} "
            f"throughput_mode={bool(throughput_mode)} recovery_attempted={bool(recovery_attempted)}"
        )
        self._record_active_calibration_event(
            "capture_request_queued",
            {
                "request_id": capture_request_id,
                "capture_context": capture_context,
                "throughput_mode": bool(throughput_mode),
                "recovery_attempted": bool(recovery_attempted),
                "expected_generation": expected_identity.get("expected_generation"),
                "expected_backend_id": expected_identity.get("expected_backend_id"),
                "queued_monotonic_ns": expected_identity.get("queued_monotonic_ns"),
            },
        )
        self.record_droplet_capture_performance_marker(
            "machine_capture_queued",
            {
                "request_id": capture_request_id,
                "capture_context": capture_context,
                "throughput_mode": bool(throughput_mode),
                "recovery_attempted": bool(recovery_attempted),
                "expected_generation": expected_identity.get("expected_generation"),
                "expected_backend_id": expected_identity.get("expected_backend_id"),
                "queued_monotonic_ns": expected_identity.get("queued_monotonic_ns"),
            },
        )
        return True

    def stop_droplet_camera(self):
        self.machine.stop_droplet_camera()

    def start_read_camera(self):
        self.machine.start_read_camera()

    def stop_read_camera(self):
        self.machine.stop_read_camera()

    def set_flash_duration(self, duration,callback=None, trace_metadata=None):
        return self.machine.set_flash_duration(duration, handler=callback, trace_metadata=trace_metadata)

    def set_flash_delay(self, delay,callback=None, trace_metadata=None):
        return self.machine.set_flash_delay(delay, handler=callback, trace_metadata=trace_metadata)

    def set_imaging_droplets(self, num_droplets, callback=None, trace_metadata=None):
        return self.machine.set_imaging_droplets(num_droplets,handler=callback, trace_metadata=trace_metadata)

    def set_exposure_time(self, exposure_time,callback=None, trace_metadata=None):
        result = self.machine.set_exposure_time(exposure_time,handler=callback, trace_metadata=trace_metadata)
        self.model.droplet_camera_model.update_exposure_time(exposure_time)
        return result

    def set_droplet_capture_profile(self, profile_name: str):
        return self.machine.set_droplet_capture_profile(profile_name)

    def get_droplet_capture_profile(self):
        getter = getattr(self.machine, "get_droplet_capture_profile", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return "default"
        return "default"

    def get_droplet_capture_profile_state(self):
        getter = getattr(self.machine, "get_droplet_capture_profile_state", None)
        if callable(getter):
            try:
                state = getter()
                if isinstance(state, dict):
                    return dict(state)
            except Exception:
                pass
        profile = self.get_droplet_capture_profile()
        return {
            "requested_profile": profile,
            "effective_profile": profile,
            "fallback_active": False,
            "fallback_reason": None,
            "fallback_error": None,
        }

    def set_command_dispatch_interval(self, interval_ms: int):
        self.machine.set_execution_interval_ms(interval_ms)

    def set_save_directory(self, directory):
        self.model.droplet_camera_model.set_save_directory(directory)      

    def _calibration_capture_context_from_callback(self, callback):
        if callback is None:
            return None
        capture_diag_id = str(getattr(callback, "_capture_diag_id", "") or "")
        calibration_process = str(getattr(callback, "_capture_calibration_process", "") or "")
        calibration_phase = str(getattr(callback, "_capture_calibration_phase", "") or "")
        if not (capture_diag_id or calibration_process or calibration_phase):
            return None
        context = {
            "kind": "calibration_capture",
            "capture_diag_id": capture_diag_id,
            "calibration_run_id": getattr(callback, "_capture_calibration_run_id", None),
            "calibration_run_index": getattr(callback, "_capture_calibration_run_index", None),
            "calibration_process_instance_id": getattr(callback, "_capture_calibration_process_instance_id", None),
            "calibration_process_instance_index": getattr(callback, "_capture_calibration_process_instance_index", None),
            "calibration_process": calibration_process,
            "calibration_phase": calibration_phase,
            "stage_text": str(getattr(callback, "_capture_stage_text", "") or ""),
            "set_attr": str(getattr(callback, "_capture_set_attr", "") or ""),
            "capture_role": str(getattr(callback, "_capture_role", "") or ""),
            "attempt": getattr(callback, "_capture_attempt", None),
            "attempts_total": getattr(callback, "_capture_attempts_total", None),
        }
        return {key: value for key, value in context.items() if value not in (None, "")}

    def handle_capture_request(self, callback):
        # protect against overlapping requests
        self.capture_droplet_image(
            callback=callback,
            capture_context=self._calibration_capture_context_from_callback(callback),
        )

    def _capture_callback_status_for_reason(self, reason):
        reason = str(reason or "")
        if reason in {
            "controller_pending",
            "callback_pending",
            "context_pending",
            "camera_worker_active",
            "camera_capture_active",
        }:
            return CaptureStatus.BUSY
        if reason in {"machine_rejected", "queue_rejected"}:
            return CaptureStatus.QUEUE_REJECTED
        if reason in {"camera_backend_unavailable", "camera_backend_unsupported", "camera_not_started"}:
            return CaptureStatus.BACKEND_UNAVAILABLE
        if reason == "capture_cancelled":
            return CaptureStatus.CANCELLED
        if reason == "flash_disarmed":
            return CaptureStatus.FLASH_DISARMED
        if reason == "flash_fault":
            return CaptureStatus.FIRMWARE_FLASH_LATCHED
        if reason == "firmware_flash_fault":
            return CaptureStatus.FIRMWARE_FLASH_FAULT
        if reason == "firmware_flash_latched":
            return CaptureStatus.FIRMWARE_FLASH_LATCHED
        return CaptureStatus.INTERNAL_ERROR

    def _attach_capture_callback_result_metadata(
        self,
        callback,
        *,
        request_id=None,
        status=None,
        metadata=None,
    ):
        if callback is None:
            return
        try:
            if request_id is not None:
                setattr(callback, "_capture_request_id", str(request_id))
            if status is not None:
                status_value = status.value if isinstance(status, CaptureStatus) else str(status)
                setattr(callback, "_capture_result_status", status_value)
            if metadata is not None:
                setattr(callback, "_capture_result_metadata", dict(metadata or {}))
        except Exception:
            pass

    def _notify_capture_callback_failed(self, callback):
        if callback is None:
            return
        reason = self.last_capture_queue_rejection_reason
        state = self.last_capture_queue_rejection_state
        try:
            setattr(callback, "_capture_rejection_reason", reason)
            setattr(callback, "_capture_rejection_state", state)
        except Exception:
            pass
        self._attach_capture_callback_result_metadata(
            callback,
            status=self._capture_callback_status_for_reason(reason),
            metadata={"rejection_reason": reason, "rejection_state": state},
        )
        try:
            callback(None)
        except Exception as e:
            print(f"Callback raised after capture request failure: {e}")

    def _ensure_pending_capture_guard_timer(self):
        timer = getattr(self, "pending_capture_guard_timer", None)
        if timer is not None:
            return timer
        timer_factory = getattr(self, "_timer_factory", None)
        if not callable(timer_factory):
            return None
        try:
            timer = timer_factory(self)
            if hasattr(timer, "setSingleShot"):
                timer.setSingleShot(True)
            timer.timeout.connect(self._on_pending_capture_timeout)
        except Exception as e:
            print(f"[Camera] could not create pending capture guard timer: {e}")
            return None
        self.pending_capture_guard_timer = timer
        return timer

    def _start_pending_capture_guard(self, *, throughput_mode=False):
        timer = self._ensure_pending_capture_guard_timer()
        if timer is None:
            return
        timeout_ms = (
            int(getattr(self, "pending_capture_throughput_timeout_ms", 1_500))
            if throughput_mode else
            int(getattr(self, "pending_capture_timeout_ms", 8_000))
        )
        timeout_ms = max(1, timeout_ms)
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timer.setInterval(timeout_ms)
            timer.start()
        except TypeError:
            timer.start(timeout_ms)

    def _stop_pending_capture_guard(self):
        timer = getattr(self, "pending_capture_guard_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    def _clear_pending_capture(self, *, callback=None, capture_context=None):
        coordinator = self._ensure_capture_coordinator()
        before = coordinator.pending_snapshot()
        cleared = coordinator.clear_pending(callback=callback, context=capture_context)
        if cleared or (callback is None and capture_context is None):
            self._stop_pending_capture_guard()
        self._sync_legacy_pending_capture_fields(coordinator)
        if cleared and bool(before.get("active")):
            self.record_droplet_capture_performance_marker(
                "controller_pending_cleared",
                {
                    "request_id": before.get("request_id"),
                    "capture_context": before.get("context"),
                    "clear_callback_filtered": callback is not None,
                    "clear_context_filtered": capture_context is not None,
                },
            )
        return cleared

    def cancel_pending_droplet_capture(self, reason, *, emit_capture_failed: bool = True, recover: bool = True):
        pending_snapshot = self._capture_pending_snapshot()
        request_id = pending_snapshot.get("request_id")
        capture_context = pending_snapshot.get("context")
        callback = pending_snapshot.get("callback")
        state_before = self._get_droplet_capture_state()
        result = {
            "cancelled": False,
            "request_id": request_id,
            "capture_context": capture_context,
            "reason": str(reason or "capture_cancelled"),
            "state_before": state_before,
            "recovery_result": None,
            "state_after": None,
        }
        if not bool(pending_snapshot.get("active")):
            result["reason"] = "no_pending_capture"
            result["state_after"] = self._get_droplet_capture_state()
            return result

        cancel_reason = str(reason or "capture_cancelled")
        message = f"Droplet capture cancelled: {cancel_reason}"
        self._record_active_calibration_event(
            "capture_cancel_requested",
            {
                "request_id": request_id,
                "capture_context": capture_context,
                "reason": cancel_reason,
                "state": state_before,
            },
            level="warning",
        )

        recovery_result = {"ok": False, "ready_for_retry": False, "reason": "recovery_skipped"}
        if recover:
            recovery_result = self._recover_current_droplet_capture(
                request_id,
                reason=f"capture_cancelled reason={cancel_reason} request_id={request_id}",
            )
        result["recovery_result"] = dict(recovery_result or {})
        state_after = self._get_droplet_capture_state()

        self.last_capture_queue_rejection_reason = "capture_cancelled"
        self.last_capture_queue_rejection_state = state_before
        cancel_result = self._record_capture_coordinator_cancelled(
            metadata={
                "capture_context": capture_context,
                "state_before": state_before,
                "state_after": state_after,
                "recovery_result": dict(recovery_result or {}),
            },
            reason=cancel_reason,
        )
        if cancel_result is None:
            self._clear_pending_capture()
        else:
            self._stop_pending_capture_guard()
            self._sync_legacy_pending_capture_fields()

        self.record_droplet_capture_performance_marker(
            "controller_capture_cancelled",
            {
                "request_id": request_id,
                "capture_context": capture_context,
                "reason": cancel_reason,
                "state_before": state_before,
                "state_after": state_after,
                "recovery_result": dict(recovery_result or {}),
            },
        )

        if callback is not None:
            try:
                setattr(callback, "_capture_rejection_reason", "capture_cancelled")
                setattr(callback, "_capture_rejection_state", state_before)
                setattr(callback, "_capture_cancel_reason", cancel_reason)
            except Exception:
                pass
            self._attach_capture_callback_result_metadata(
                callback,
                request_id=request_id,
                status=CaptureStatus.CANCELLED,
                metadata={
                    "capture_context": capture_context,
                    "rejection_reason": "capture_cancelled",
                    "cancel_reason": cancel_reason,
                    "rejection_state": state_before,
                    "recovery_result": dict(recovery_result or {}),
                },
            )
            try:
                callback(None)
            except Exception as exc:
                print(f"Callback raised after capture cancellation: {exc}")

        result.update(
            {
                "cancelled": True,
                "state_after": state_after,
            }
        )
        recovery_ok = bool((recovery_result or {}).get("ok"))
        if recover:
            self._record_active_calibration_event(
                "capture_cancel_recovered" if recovery_ok else "capture_cancel_failed",
                {
                    "request_id": request_id,
                    "capture_context": capture_context,
                    "reason": cancel_reason,
                    "recovery_result": dict(recovery_result or {}),
                    "state": state_after,
                },
                level="info" if recovery_ok else "warning",
            )
        else:
            self._record_active_calibration_event(
                "capture_cancel_recovery_skipped",
                {
                    "request_id": request_id,
                    "capture_context": capture_context,
                    "reason": cancel_reason,
                    "state": state_after,
                },
                level="warning",
            )

        if emit_capture_failed:
            try:
                self.model.calibration_manager.captureFailed.emit(message)
            except Exception:
                pass
        return result

    def _fail_pending_capture(self, msg: str, *, emit_capture_failed: bool = True):
        pending_snapshot = self._capture_pending_snapshot()
        cb = pending_snapshot.get("callback")
        request_id = pending_snapshot.get("request_id")
        self._record_active_calibration_event(
            "capture_failed",
            {"request_id": request_id, "message": str(msg), "state": self._get_droplet_capture_state()},
            level="warning",
        )
        self._record_capture_coordinator_failure(
            request_id,
            status=CaptureStatus.INTERNAL_ERROR,
            metadata={"message": str(msg), "state": self._get_droplet_capture_state()},
            reason=str(msg),
        )
        self.record_droplet_capture_performance_marker(
            "controller_capture_failed",
            {
                "request_id": request_id,
                "capture_context": pending_snapshot.get("context"),
                "message": str(msg),
                "state": self._get_droplet_capture_state(),
            },
        )
        self._clear_pending_capture()
        if cb:
            self._attach_capture_callback_result_metadata(
                cb,
                request_id=request_id,
                status=CaptureStatus.INTERNAL_ERROR,
                metadata={"message": str(msg), "state": self._get_droplet_capture_state()},
            )
            try:
                cb(None)
            except Exception as e:
                print(f"Callback raised after capture failure: {e}")
        if emit_capture_failed:
            try:
                self.model.calibration_manager.captureFailed.emit(msg)
            except Exception:
                pass

    def _on_pending_capture_timeout(self):
        pending_snapshot = self._capture_pending_snapshot()
        if not bool(pending_snapshot.get("active")):
            return
        request_id = pending_snapshot.get("request_id")
        recovery_attempted = bool(pending_snapshot.get("recovery_attempted", False))
        started = pending_snapshot.get("started_monotonic")
        elapsed_s = None
        if started is not None:
            try:
                monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
                elapsed_s = max(0.0, float(monotonic_fn()) - float(started))
            except Exception:
                elapsed_s = None
        suffix = "" if elapsed_s is None else f" after {elapsed_s:.1f}s"
        msg = f"Droplet capture timed out in controller{suffix}; releasing pending request."
        print(f"[Camera] {msg}")
        self._record_active_calibration_event(
            "capture_controller_timeout",
            {
                "request_id": request_id,
                "elapsed_s": elapsed_s,
                "recovery_attempted": recovery_attempted,
                "state": self._get_droplet_capture_state(),
            },
            level="warning",
        )
        if not recovery_attempted:
            callback = pending_snapshot.get("callback")
            capture_context = pending_snapshot.get("context")
            throughput_mode = bool(pending_snapshot.get("throughput_mode", False))
            recovery_result = self._recover_current_droplet_capture(
                request_id,
                reason=f"controller_timeout request_id={request_id}",
            )
            recovery_ok = bool(recovery_result.get("ok"))
            ready_for_retry = bool(recovery_result.get("ready_for_retry", recovery_ok))
            if recovery_ok and ready_for_retry:
                self._clear_pending_capture()
                requeued = self._queue_capture_request(
                    callback=callback,
                    throughput_mode=throughput_mode,
                    capture_context=capture_context,
                    recovery_attempted=True,
                )
                if requeued is True:
                    return
                msg = "Droplet capture recovery completed, but retry capture could not be queued."
                try:
                    self.model.calibration_manager.captureFailed.emit(msg)
                except Exception:
                    pass
                return
            self._record_active_calibration_event(
                "capture_retry_suppressed_after_recovery",
                {
                    "request_id": request_id,
                    "result": dict(recovery_result or {}),
                    "message": msg,
                },
                level="warning",
            )
            self._fail_pending_capture(msg)
            return
        self._recover_current_droplet_capture(
            request_id,
            reason=f"second_controller_timeout request_id={request_id}",
        )
        self._fail_pending_capture(msg)

    def _recover_current_droplet_capture(self, request_id, *, reason):
        self._record_active_calibration_event(
            "camera_recovery_started",
            {"request_id": request_id, "reason": str(reason)},
            level="warning",
        )
        recovery_result = {"ok": False, "ready_for_retry": False, "reason": "recovery_not_available"}
        try:
            recover = getattr(self.machine, "recover_droplet_capture", None)
            if callable(recover):
                recovery_result = recover(reason=str(reason))
        except Exception as exc:
            recovery_result = {"ok": False, "ready_for_retry": False, "reason": str(exc)}
        if not isinstance(recovery_result, dict):
            recovery_result = {
                "ok": False,
                "ready_for_retry": False,
                "reason": f"invalid_recovery_result:{type(recovery_result).__name__}",
            }
        recovery_ok = bool(recovery_result.get("ok"))
        self._record_active_calibration_event(
            "camera_recovery_completed" if recovery_ok else "camera_recovery_failed",
            {
                "request_id": request_id,
                "result": dict(recovery_result or {}),
                "state": self._get_droplet_capture_state(),
            },
            level="info" if recovery_ok else "warning",
        )
        return dict(recovery_result or {})

    def _get_droplet_capture_state(self):
        try:
            getter = getattr(self.machine, "get_droplet_capture_state", None)
            if callable(getter):
                return dict(getter() or {})
            camera = getattr(self.machine, "droplet_camera", None)
            getter = getattr(camera, "get_capture_state", None)
            if callable(getter):
                return dict(getter() or {})
        except Exception as exc:
            return {"state_error": str(exc)}
        return {}

    @staticmethod
    def _classify_capture_queue_rejection(state):
        state = dict(state or {})
        if state.get("worker_active"):
            return "camera_worker_active"
        if state.get("cap_active"):
            return "camera_capture_active"
        if state.get("camera_started") is False:
            return "camera_not_started"
        backend_error = str(state.get("backend_error") or "")
        if "gpio_edge_fd_unavailable" in backend_error:
            return "camera_backend_unsupported"
        if backend_error or state.get("backend_available") is False:
            return "camera_backend_unavailable"
        if state.get("flash_fault"):
            return "flash_fault"
        return "machine_rejected"

    def _ensure_droplet_capture_performance_diagnostics(self):
        diagnostics = getattr(self, "_droplet_capture_performance_diagnostics", None)
        if diagnostics is None:
            diagnostics = DropletCapturePerformanceDiagnostics()
            self._droplet_capture_performance_diagnostics = diagnostics
        return diagnostics

    def set_droplet_capture_performance_diagnostics_enabled(self, enabled):
        diagnostics = self._ensure_droplet_capture_performance_diagnostics()
        enabled = diagnostics.set_enabled(bool(enabled))
        self._connect_calibration_capture_performance_diagnostics()
        manager = getattr(getattr(self, "model", None), "calibration_manager", None)
        setter = getattr(manager, "set_capture_performance_diagnostics_enabled", None)
        if callable(setter):
            try:
                setter(enabled)
            except Exception:
                pass
        self._set_droplet_camera_performance_diagnostics_enabled(enabled)
        bridge_status = self._calibration_capture_performance_bridge_status()
        self.record_droplet_capture_performance_marker(
            "diagnostics_enabled",
            {
                "enabled": bool(enabled),
                "max_events": int(getattr(diagnostics, "max_events", 0) or 0),
                **bridge_status,
            },
        )
        self.record_droplet_capture_performance_marker(
            "calibration_diagnostics_bridge_status",
            {
                "enabled": bool(enabled),
                "max_events": int(getattr(diagnostics, "max_events", 0) or 0),
                **bridge_status,
            },
        )
        return enabled

    def is_droplet_capture_performance_diagnostics_enabled(self):
        diagnostics = self._ensure_droplet_capture_performance_diagnostics()
        return bool(diagnostics.enabled)

    def record_droplet_capture_performance_marker(self, event_kind, payload=None):
        diagnostics = getattr(self, "_droplet_capture_performance_diagnostics", None)
        if diagnostics is None or not bool(getattr(diagnostics, "enabled", False)):
            return None
        return diagnostics.record(event_kind, payload if isinstance(payload, dict) else {})

    def _droplet_capture_runtime_summaries(self, runtime_summaries=None):
        summaries = dict(runtime_summaries or {})
        getter = getattr(
            getattr(self, "machine", None),
            "get_status_delivery_diagnostics",
            None,
        )
        if callable(getter):
            try:
                summaries.setdefault("machine_status_delivery", getter())
            except Exception:
                pass
        return summaries

    def build_droplet_capture_performance_snapshot(
        self,
        reason="manual_export",
        runtime_summaries=None,
    ):
        diagnostics = self._ensure_droplet_capture_performance_diagnostics()
        return diagnostics.build_snapshot(
            reason=reason,
            runtime_summaries=self._droplet_capture_runtime_summaries(runtime_summaries),
        )

    def _default_droplet_capture_performance_snapshot_dir(self):
        experiment_model = getattr(getattr(self, "model", None), "experiment_model", None)
        experiment_path = getattr(experiment_model, "experiment_dir_path", None)
        base = Path(str(experiment_path)) if experiment_path else Path.cwd()
        return base / "calibration_recordings" / "droplet_capture_performance"

    def write_droplet_capture_performance_snapshot(
        self,
        directory=None,
        reason="manual_export",
        runtime_summaries=None,
    ):
        diagnostics = self._ensure_droplet_capture_performance_diagnostics()
        out_dir = Path(directory) if directory is not None else self._default_droplet_capture_performance_snapshot_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"droplet_capture_performance_{stamp}_{uuid.uuid4().hex[:8]}.json"
        previous_path = diagnostics.last_snapshot_path
        diagnostics.last_snapshot_path = str(path)
        snapshot = diagnostics.build_snapshot(
            reason=reason,
            runtime_summaries=self._droplet_capture_runtime_summaries(runtime_summaries),
        )
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2)
                handle.write("\n")
        except Exception:
            diagnostics.last_snapshot_path = previous_path
            raise
        return path

    def _record_active_calibration_event(self, event_type, payload=None, *, level="info"):
        try:
            active = getattr(self.model.calibration_manager, "activeCalibration", None)
            recorder = getattr(active, "_record_event", None)
            if callable(recorder):
                recorder(str(event_type), payload or {}, level=level)
                return
            manager = getattr(self.model, "calibration_manager", None)
            record_process_event = getattr(manager, "record_process_event", None)
            if callable(record_process_event):
                record_process_event(str(event_type), payload or {}, level=level)
        except Exception:
            pass

    def _on_camera_capture_phase(self, payload):
        data = dict(payload or {}) if isinstance(payload, dict) else {"payload": payload}
        level = str(data.get("level") or "info")
        self.record_droplet_capture_performance_marker("camera_phase", data)
        level_text = level.strip().lower()
        if level_text in {"warning", "warn", "error", "critical", "exception"}:
            self._record_active_calibration_event("camera_capture_phase", data, level=level)

    def _emit_active_calibration_error(self, message: str):
        """
        Route runtime errors through the active calibration process when available.
        This ensures CalibrationManager receives the error via its normal process wiring.
        """
        msg = str(message)
        try:
            active = getattr(self.model.calibration_manager, "activeCalibration", None)
            if active is not None and hasattr(active, "calibrationError"):
                active.calibrationError.emit(msg)
                return
        except Exception:
            pass
        try:
            manager_error = getattr(self.model.calibration_manager, "calibrationError", None)
            if manager_error is not None and hasattr(manager_error, "emit"):
                manager_error.emit(msg)
        except Exception:
            pass

    def _is_flash_fault_latched(self) -> bool:
        cam = getattr(self.model, "droplet_camera_model", None)
        getter = getattr(cam, "get_flash_fault_latched", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return bool(getattr(cam, "flash_fault_latched", False))

    def _flash_fault_reason_text(self) -> str:
        cam = getattr(self.model, "droplet_camera_model", None)
        getter = getattr(cam, "get_flash_fault_reason_display", None)
        if callable(getter):
            try:
                reason = str(getter() or "").strip()
                if reason:
                    return reason
            except Exception:
                pass
        raw = str(getattr(cam, "flash_fault_reason", "") or "").strip().replace("_", " ")
        return raw or "Flash safety fault latched."

    def _handle_blocked_capture(self, callback=None):
        message = (
            "Droplet capture blocked because the flash safety latch is active. "
            f"{self._flash_fault_reason_text()}. Close and reopen the imager after PE8 is low."
        )
        print(f"[Camera] capture blocked: {message}")
        if callback is not None:
            state = self._get_droplet_capture_state()
            try:
                setattr(callback, "_capture_rejection_reason", "flash_fault")
                setattr(callback, "_capture_rejection_state", state)
            except Exception:
                pass
            self._attach_capture_callback_result_metadata(
                callback,
                status=CaptureStatus.FIRMWARE_FLASH_LATCHED,
                metadata={
                    "rejection_reason": "flash_fault",
                    "rejection_state": state,
                    "message": message,
                },
            )
            try:
                callback(None)
            except Exception as exc:
                print(f"Callback raised after blocked capture: {exc}")
        self._emit_active_calibration_error(message)

    @staticmethod
    def _coerce_xyz_position_dict(position):
        if not isinstance(position, dict):
            return None
        out = {}
        for axis in ("X", "Y", "Z"):
            try:
                out[axis] = int(position[axis])
            except (KeyError, TypeError, ValueError):
                return None
        return out

    def _build_droplet_capture_save_metadata(self, capture_context=None):
        metadata = {
            "position_source": "controller_expected_position",
            "position_recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if capture_context is not None:
            metadata["capture_context"] = str(capture_context)

        expected = self._coerce_xyz_position_dict(getattr(self, "expected_position", None))
        if expected is not None:
            metadata["controller_expected_position"] = expected
            metadata["X_position"] = expected["X"]
            metadata["Y_position"] = expected["Y"]
            metadata["Z_position"] = expected["Z"]

        machine_position = None
        try:
            getter = getattr(getattr(self.model, "machine_model", None), "get_current_position_dict", None)
            if callable(getter):
                machine_position = self._coerce_xyz_position_dict(getter())
        except Exception:
            machine_position = None
        if machine_position is not None:
            metadata["machine_position"] = machine_position

        try:
            metadata["commands_idle_at_frame"] = bool(self.check_if_all_completed())
        except Exception:
            metadata["commands_idle_at_frame"] = None

        return metadata

    def handle_move_request(self, move_vector, callback):
        # Perform the move command then call the callback.
        try:
            dX, dY, dZ = move_vector
            ok = self.set_relative_coordinates(dX, dY, dZ, manual=False, handler=callback)
            if ok is False:
                self._emit_active_calibration_error(
                    f"Relative move rejected by safety guard: ({dX}, {dY}, {dZ})"
                )
                return
            print('Controller: Move request handled')
        except Exception as e:
            self._emit_active_calibration_error(f"Relative move failed: {e}")

    def handle_absolute_move_request(self, target_position, callback):
        # Perform the move command then call the callback.
        try:
            if type(target_position) == tuple or type(target_position) == list:
                target = {'X': target_position[0], 'Y': target_position[1], 'Z': target_position[2]}
            else:
                target = target_position.copy()
            ok = self.set_absolute_coordinates(
                target['X'],
                target['Y'],
                target['Z'],
                manual=False,
                handler=callback
            )
            if ok is False:
                self._emit_active_calibration_error(
                    f"Absolute move rejected by safety guard: ({target['X']}, {target['Y']}, {target['Z']})"
                )
                return
            print('Controller: Move request handled')
        except Exception as e:
            self._emit_active_calibration_error(f"Absolute move failed: {e}")

    # def handle_droplet_change_request(self, num_droplets,callback):
    #     self.set_imaging_droplets(num_droplets,callback=callback)
    def intermediate_callback(self):
        """
        A simple callback function that can be used to handle intermediate results.
        This is just a placeholder and can be customized as needed.
        """
        print(f'Intermediate result')

    def handle_settings_change_request(self, settings, callback):
        # Update the settings in the model and machine.
        settings = dict(settings or {})
        num_settings = len(settings)
        request_id = getattr(callback, "_settings_request_id", None)
        request_context = getattr(callback, "_settings_context", "")
        requested_settings = dict(getattr(callback, "_settings_requested_settings", settings) or {})
        request_created_monotonic_ns = getattr(callback, "_settings_created_monotonic_ns", None)
        timeout_ms = getattr(callback, "_settings_guard_timeout_ms", None)
        bind_callback = getattr(callback, "_settings_bind_callback", None)
        bound_commands = []
        completion_command_number = None

        if request_id and hasattr(self.machine, "get_settings_trace_snapshot"):
            def _trace_provider():
                timed_out_monotonic_ns = getattr(callback, "_settings_timed_out_monotonic_ns", None)
                return self.machine.get_settings_trace_snapshot(
                    str(request_id),
                    timed_out_monotonic_ns=timed_out_monotonic_ns,
                )

            try:
                setattr(callback, "_settings_trace_provider", _trace_provider)
            except Exception:
                pass

        current_call_back = self.intermediate_callback  # Default callback for intermediate settings.
        for i, (key, value) in enumerate(settings.items()):
            if i == num_settings - 1:
                current_call_back = callback
            trace_metadata = None
            if request_id:
                trace_metadata = {
                    "request_id": str(request_id),
                    "settings_context": str(request_context or ""),
                    "setting_key": str(key),
                    "requested_value": value,
                    "setting_index": int(i),
                    "settings_count": int(num_settings),
                    "request_created_monotonic_ns": request_created_monotonic_ns,
                }
            queued_command = None
            command_type = None
            if key == 'num_droplets':
                command_type = "SET_IMAGE_DROPLETS"
                queued_command = self.set_imaging_droplets(value,callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'flash_duration':
                command_type = "SET_WIDTH_F"
                queued_command = self.set_flash_duration(value, callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'flash_delay':
                command_type = "SET_DELAY_F"
                queued_command = self.set_flash_delay(value, callback=current_call_back, trace_metadata=trace_metadata)
                print(f'--Setting flash delay: {value}')
            elif key == 'exposure_time':
                command_type = "SET_EXPOSURE_TIME"
                queued_command = self.set_exposure_time(value, callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'print_pulse_width':
                command_type = "SET_WIDTH_P"
                queued_command = self.set_print_pulse_width(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'refuel_pulse_width':
                command_type = "SET_WIDTH_R"
                queued_command = self.set_refuel_pulse_width(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'print_pressure':
                print(f'--Setting print pressure: {value}')
                command_type = "ABSOLUTE_PRESSURE_P"
                queued_command = self.set_absolute_print_pressure(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'refuel_pressure':
                command_type = "ABSOLUTE_PRESSURE_R"
                queued_command = self.set_absolute_refuel_pressure(value, handler=current_call_back, trace_metadata=trace_metadata)
            else:
                print(f'Unknown setting: {key}')
            if request_id:
                command_number = getattr(queued_command, "command_number", None)
                command_type = str(getattr(queued_command, "command_type", command_type or "") or "")
                bound_commands.append(
                    {
                        "command_number": None if command_number is None else int(command_number),
                        "command_type": command_type,
                        "setting_key": str(key),
                        "requested_value": value,
                    }
                )
                if i == num_settings - 1:
                    completion_command_number = None if command_number is None else int(command_number)

        if request_id:
            binding_payload = {
                "request_id": str(request_id),
                "context": str(request_context or ""),
                "settings": dict(requested_settings),
                "timeout_ms": timeout_ms,
                "request_created_monotonic_ns": request_created_monotonic_ns,
                "commands": bound_commands,
                "completion_command_number": completion_command_number,
            }
            register = getattr(self.machine, "register_settings_trace_binding", None)
            if callable(register):
                register(binding_payload)
            if callable(bind_callback):
                bind_callback(binding_payload)

    @QtCore.Slot()
    def _on_image_captured(self):
        """
        This slot is called when the droplet camera emits its image_captured_signal.
        It retrieves the latest frame, updates the model (and view), and if a
        callback is waiting, calls it.
        """
        frame = self.machine.droplet_camera.get_latest_frame()

        cap_info = None
        try:
            cap_info = self.machine.droplet_camera.get_last_capture_result()
        except Exception:
            cap_info = None

        self._complete_pending_capture_success(frame, cap_info=cap_info)

    @QtCore.Slot(object)
    def _on_capture_completed_payload(self, payload):
        payload = dict(payload or {}) if isinstance(payload, dict) else {"status": "failed", "error": str(payload)}
        camera_summary = payload.pop("capture_performance_summary", None)
        if isinstance(camera_summary, dict):
            summary_event = dict(camera_summary)
            summary_event.setdefault("capture_context", payload.get("capture_context"))
            self.record_droplet_capture_performance_marker("camera_capture_summary", summary_event)
        request_id = payload.get("request_id")
        status = str(payload.get("status") or "").lower()
        controller_received_ns = time.monotonic_ns()
        queued_ns = payload.get("queued_monotonic_ns")
        worker_started_ns = payload.get("worker_started_monotonic_ns")
        worker_completed_ns = payload.get("worker_completed_monotonic_ns")
        self.record_droplet_capture_performance_marker(
            "controller_completion_received",
            {
                "request_id": request_id,
                "status": status,
                "cap_id": payload.get("cap_id"),
                "generation": payload.get("generation"),
                "backend_id": payload.get("backend_id"),
                "capture_context": payload.get("capture_context"),
                "queued_monotonic_ns": queued_ns,
                "worker_started_monotonic_ns": worker_started_ns,
                "worker_completed_monotonic_ns": worker_completed_ns,
                "controller_received_monotonic_ns": controller_received_ns,
                "queue_to_worker_start_ms": DropletCapturePerformanceDiagnostics._delta_ms(
                    queued_ns,
                    worker_started_ns,
                ),
                "worker_duration_ms": DropletCapturePerformanceDiagnostics._delta_ms(
                    worker_started_ns,
                    worker_completed_ns,
                ),
                "worker_complete_to_controller_ms": DropletCapturePerformanceDiagnostics._delta_ms(
                    worker_completed_ns,
                    controller_received_ns,
                ),
            },
        )
        pending_snapshot = self._capture_pending_snapshot()
        expected_request_id = pending_snapshot.get("request_id")
        mismatch_reason = self._capture_completion_identity_mismatch(payload, pending_snapshot)
        if mismatch_reason is not None:
            stale_metadata = self._capture_completion_identity_metadata(
                payload=payload,
                pending_snapshot=pending_snapshot,
                mismatch_reason=mismatch_reason,
            )
            print(
                "[Camera] stale capture completion ignored "
                f"request_id={request_id} expected={expected_request_id} "
                f"status={payload.get('status')} reason={mismatch_reason}"
            )
            self._record_active_calibration_event(
                "capture_stale_completion_ignored",
                stale_metadata,
                level="warning",
            )
            self._record_capture_coordinator_stale(
                request_id,
                metadata=stale_metadata,
                reason=str(mismatch_reason),
            )
            self.record_droplet_capture_performance_marker(
                "controller_completion_stale",
                {
                    "request_id": request_id,
                    "expected_request_id": expected_request_id,
                    "status": status,
                    "reason": str(mismatch_reason),
                    "cap_id": payload.get("cap_id"),
                    "generation": payload.get("generation"),
                    "backend_id": payload.get("backend_id"),
                },
            )
            return

        if status == "stale" or bool(payload.get("stale", False)):
            stale_metadata = self._capture_completion_identity_metadata(
                payload=payload,
                pending_snapshot=pending_snapshot,
                mismatch_reason="worker_marked_stale",
            )
            self._record_active_calibration_event(
                "capture_stale_completion_ignored",
                stale_metadata,
                level="warning",
            )
            self._record_capture_coordinator_stale(
                request_id,
                metadata=stale_metadata,
                reason="worker_marked_stale",
            )
            self.record_droplet_capture_performance_marker(
                "controller_completion_stale",
                {
                    "request_id": request_id,
                    "expected_request_id": expected_request_id,
                    "status": status,
                    "reason": "worker_marked_stale",
                    "cap_id": payload.get("cap_id"),
                    "generation": payload.get("generation"),
                    "backend_id": payload.get("backend_id"),
                },
            )
            return
        if status == "success" and payload.get("frame") is not None:
            capture_info = dict(payload.get("capture_info") or {})
            capture_info.setdefault("request_id", request_id)
            capture_info.setdefault("cap_id", payload.get("cap_id"))
            capture_info.setdefault("generation", payload.get("generation"))
            capture_info.setdefault("backend_id", payload.get("backend_id"))
            capture_info.setdefault("capture_context", payload.get("capture_context"))
            for key in ("queued_monotonic_ns", "worker_started_monotonic_ns", "worker_completed_monotonic_ns"):
                if key in payload:
                    capture_info.setdefault(key, payload.get(key))
            self._complete_pending_capture_success(payload.get("frame"), cap_info=capture_info)
            return

        msg = str(
            payload.get("error")
            or payload.get("reason")
            or payload.get("stale_reason")
            or "Droplet capture failed."
        )
        print(
            f"[Camera] capture failed request_id={request_id} status={status} "
            f"cap_id={payload.get('cap_id')} reason={msg}"
        )
        self._fail_pending_capture(msg)

    def _complete_pending_capture_success(self, frame, *, cap_info=None):
        pending_snapshot = self._capture_pending_snapshot()
        request_id = pending_snapshot.get("request_id")
        capture_context = pending_snapshot.get("context")
        save_metadata = self._build_droplet_capture_save_metadata(capture_context=capture_context)

        callback = pending_snapshot.get("callback")
        diagnostics_enabled = self.is_droplet_capture_performance_diagnostics_enabled()
        model_update_started_ns = time.monotonic_ns() if diagnostics_enabled else None

        # Update the model and/or view (assuming your model has such a method)
        try:
            self.model.droplet_camera_model.update_image(frame, capture_info=cap_info, save_metadata=save_metadata)
            model_update_duration_ms = DropletCapturePerformanceDiagnostics._delta_ms(
                model_update_started_ns,
                time.monotonic_ns() if diagnostics_enabled else None,
            )
            self.record_droplet_capture_performance_marker(
                "model_image_updated",
                {
                    "request_id": request_id,
                    "capture_context": capture_context,
                    "cap_id": (cap_info or {}).get("cap_id") if isinstance(cap_info, dict) else None,
                    "generation": (cap_info or {}).get("generation") if isinstance(cap_info, dict) else None,
                    "backend_id": (cap_info or {}).get("backend_id") if isinstance(cap_info, dict) else None,
                    "duration_ms": model_update_duration_ms,
                },
            )
            droplet_count = self._current_imaging_droplet_count()
            if droplet_count > 0:
                self._record_refuel_ejection_event(
                    droplet_count,
                    source="Controller.droplet_capture_completed",
                    event_kind="capture_completed",
                    count_kind="observed",
                    payload={
                        "request_id": request_id,
                        "capture_context": capture_context,
                        "cap_id": (cap_info or {}).get("cap_id") if isinstance(cap_info, dict) else None,
                    },
                )
        finally:
            self._record_active_calibration_event(
                "capture_completed",
                {
                    "request_id": request_id,
                    "cap_id": (cap_info or {}).get("cap_id") if isinstance(cap_info, dict) else None,
                    "capture_context": capture_context,
                    "state": self._get_droplet_capture_state(),
                },
            )
            metadata = dict(cap_info or {}) if isinstance(cap_info, dict) else {}
            metadata.setdefault("capture_context", capture_context)
            self._record_capture_coordinator_success(
                request_id,
                frame,
                metadata=metadata,
                reason=str(metadata.get("reason") or "capture_completed"),
            )
            self._clear_pending_capture()
        
        # If a callback was set for the capture, call it.
        if callback:
            self._attach_capture_callback_result_metadata(
                callback,
                request_id=request_id,
                status=CaptureStatus.SUCCESS,
                metadata=metadata,
            )
            callback_started_ns = time.monotonic_ns() if diagnostics_enabled else None
            try:
                callback(frame)
            finally:
                if diagnostics_enabled and isinstance(capture_context, dict) and str(
                    capture_context.get("kind") or ""
                ) == "calibration_capture":
                    self.record_droplet_capture_performance_marker(
                        "calibration_callback_handled",
                        {
                            "request_id": request_id,
                            "capture_context": capture_context,
                            "duration_ms": DropletCapturePerformanceDiagnostics._delta_ms(
                                callback_started_ns,
                                time.monotonic_ns(),
                            ),
                        },
                    )

    @QtCore.Slot(str)
    def _on_capture_failed(self, msg: str):
        print(f"[Camera] capture failed: {msg}")
        self._fail_pending_capture(str(msg))

    def set_start_pressure(self, pressure):
        self.model.calibration_manager.set_start_pressure(pressure)

    def set_num_pressure_tests(self, num_tests):
        self.model.calibration_manager.set_num_pressure_tests(num_tests)

    def start_head_prime_calibration(self):
        # Tell the Model to start the head priming calibration.
        self.model.calibration_manager.start_head_prime_calibration()

    def start_nozzle_calibration(self):
        # Tell the Model to start the nozzle position calibration.
        self.model.calibration_manager.start_nozzle_calibration()

    def start_nozzle_focus_calibration(self):
        # Tell the Model to start the nozzle focus calibration.
        self.model.calibration_manager.start_nozzle_focus_calibration()

    def start_droplet_emergence_calibration(self):
        # Tell the Model to start the droplet emergence calibration.
        self.model.calibration_manager.start_droplet_emergence_calibration()

    # def start_pressure_calibration(self):
    #     # Tell the Model to start the pressure calibration.
    #     self.model.calibration_manager.start_pressure_calibration()

    # def start_trajectory_calibration(self):
    #     # Tell the Model to start the trajectory calibration.
    #     self.model.calibration_manager.start_trajectory_calibration()

    def start_pressure_scan_calibration(self):
        self.model.calibration_manager.start_pressure_scan_calibration()

    def start_conservative_pressure_scan_calibration(self):
        self.model.calibration_manager.start_conservative_pressure_scan_calibration()

    def start_prebreakup_morphology_calibration(
        self,
        *,
        start_pressure: float | None = None,
        pressure_step_psi: float = 0.03,
        prebreakup_lead_us: int = 600,
        fixed_prebreakup_delay_us: int | None = None,
        auto_scout_delay: bool = True,
        replicates_per_pressure: int = 3,
    ):
        self.model.calibration_manager.start_prebreakup_morphology_calibration(
            start_pressure=start_pressure,
            pressure_step_psi=pressure_step_psi,
            prebreakup_lead_us=prebreakup_lead_us,
            fixed_prebreakup_delay_us=fixed_prebreakup_delay_us,
            auto_scout_delay=auto_scout_delay,
            replicates_per_pressure=replicates_per_pressure,
        )

    def start_prebreakup_dataset_acquisition(
        self,
        *,
        plan_path: str | None = None,
        pressure_psi: float | None = None,
        pulse_width_us: int | None = None,
        delay_start_offset_us: int = 100,
        delay_stop_offset_us: int = 2200,
        delay_step_us: int = 50,
        replicates_per_delay: int = 2,
        analyze_frames: bool = False,
        save_overlays: bool = False,
    ):
        self.model.calibration_manager.start_prebreakup_dataset_acquisition(
            plan_path=plan_path,
            pressure_psi=pressure_psi,
            pulse_width_us=pulse_width_us,
            delay_start_offset_us=delay_start_offset_us,
            delay_stop_offset_us=delay_stop_offset_us,
            delay_step_us=delay_step_us,
            replicates_per_delay=replicates_per_delay,
            analyze_frames=analyze_frames,
            save_overlays=save_overlays,
        )

    def start_pressure_sweep_characterization(self):
        return self.model.calibration_manager.start_pressure_sweep_characterization()

    def start_droplet_recheck_characterization(self, selected_summary_row):
        return self.model.calibration_manager.start_droplet_recheck_characterization(selected_summary_row)
    
    def start_droplet_timecourse_process(self):
        self.model.calibration_manager.start_droplet_timecourse_process()

    def start_online_stream_calibration(self):
        return self.model.calibration_manager.start_online_stream_calibration()

    def apply_online_stream_tail_start_override(self, tail_start_delay_from_emergence_us: int):
        return self.model.calibration_manager.apply_online_stream_tail_start_override(
            tail_start_delay_from_emergence_us,
        )

    def start_droplet_calibration_sequence(self, *, pressure_scan_mode: str = "band"):
        return self.model.calibration_manager.start_droplet_calibration_sequence(
            pressure_scan_mode=pressure_scan_mode,
        )

    def start_stream_calibration_sequence(self):
        return self.model.calibration_manager.start_stream_calibration_sequence()

    def start_stream_gravimetric_capture(self, starting_mass_mg, rep_override=None, notes="", capture_mode="timecourse"):
        return self.model.calibration_manager.start_stream_gravimetric_capture(
            starting_mass_mg,
            rep_override=rep_override,
            notes=notes,
            capture_mode=capture_mode,
        )

    def _begin_calibration_gripper_close_sequence(
        self,
        *,
        state_getter,
        begin_refresh,
        mark_settling,
        mark_refreshed,
        report_failure,
    ):
        result = begin_refresh()
        if isinstance(result, tuple) and result and (result[0] is False):
            return result

        state = state_getter()
        expected_session_id = str(state.get("session_id") or "")

        def _is_matching_refresh_session():
            current = state_getter()
            return (
                str(current.get("status") or "") == "refreshing_gripper"
                and str(current.get("session_id") or "") == expected_session_id
            )

        def _report_failure_if_current(message):
            if _is_matching_refresh_session():
                report_failure(message)

        def _after_gripper_settle():
            if _is_matching_refresh_session():
                mark_refreshed(expected_session_id)

        def _after_gripper_refresh():
            if not _is_matching_refresh_session():
                return
            settling_result = mark_settling(
                expected_session_id,
                self.CALIBRATION_GRIPPER_SETTLE_MS,
            )
            if (
                isinstance(settling_result, tuple)
                and settling_result
                and settling_result[0] is False
            ):
                return
            try:
                wait_ok = self.machine.wait_ms(
                    self.CALIBRATION_GRIPPER_SETTLE_MS,
                    handler=_after_gripper_settle,
                )
            except Exception as exc:
                message = f"Failed to enqueue the gripper cooldown wait: {exc}"
                _report_failure_if_current(message)
                return
            if wait_ok is False:
                message = "Failed to enqueue the gripper cooldown wait."
                _report_failure_if_current(message)

        try:
            refresh_ok = self.close_gripper(handler=_after_gripper_refresh)
        except Exception as exc:
            message = f"Failed to enqueue the initial gripper close pulse: {exc}"
            _report_failure_if_current(message)
            return False, message
        if refresh_ok is False:
            message = "Failed to enqueue the initial gripper close pulse."
            _report_failure_if_current(message)
            return False, message
        return True, ""

    def begin_stream_calibration_sequence_gripper_preamble(self):
        manager = self.model.calibration_manager
        return self._begin_calibration_gripper_close_sequence(
            state_getter=manager.get_stream_calibration_sequence_state,
            begin_refresh=manager.begin_stream_calibration_sequence_gripper_refresh,
            mark_settling=manager.mark_stream_calibration_sequence_gripper_settling,
            mark_refreshed=manager.mark_stream_calibration_sequence_gripper_refreshed,
            report_failure=manager.report_stream_calibration_sequence_gripper_preamble_failure,
        )

    def begin_droplet_calibration_sequence_gripper_preamble(self):
        manager = self.model.calibration_manager
        return self._begin_calibration_gripper_close_sequence(
            state_getter=manager.get_droplet_calibration_sequence_state,
            begin_refresh=manager.begin_droplet_calibration_sequence_gripper_refresh,
            mark_settling=manager.mark_droplet_calibration_sequence_gripper_settling,
            mark_refreshed=manager.mark_droplet_calibration_sequence_gripper_refreshed,
            report_failure=manager.report_droplet_calibration_sequence_gripper_preamble_failure,
        )

    def finalize_stream_gravimetric_capture(self, ending_mass_mg, rep_override=None, notes=""):
        return self.model.calibration_manager.finalize_stream_gravimetric_capture(
            ending_mass_mg,
            rep_override=rep_override,
            notes=notes,
        )

    def discard_stream_gravimetric_capture(self, reason="operator_discarded"):
        state = self.model.calibration_manager.get_stream_gravimetric_capture_state()
        status = str(state.get("status") or "")
        if status in {
            "awaiting_starting_balance_mass",
            "awaiting_starting_balance_confirmation",
        }:
            return self.abandon_stream_gravimetric_starting_mass(reason=reason)
        if status in {
            "awaiting_ending_balance_ready",
            "awaiting_ending_balance_mass",
            "awaiting_ending_balance_confirmation",
        }:
            self._retire_stream_gravimetric_balance_request(phase="ending")
        return self.model.calibration_manager.discard_stream_gravimetric_capture(
            reason=reason,
        )

    def begin_stream_gravimetric_starting_loading_move(self):
        return self.model.calibration_manager.begin_stream_gravimetric_starting_loading_move()

    def on_stream_gravimetric_starting_loading_reached(self):
        return self.model.calibration_manager.mark_stream_gravimetric_starting_loading_reached()

    def begin_stream_gravimetric_starting_camera_return(self):
        return self.model.calibration_manager.begin_stream_gravimetric_starting_camera_return()

    def on_stream_gravimetric_starting_camera_reached(self):
        return self.model.calibration_manager.mark_stream_gravimetric_starting_camera_reached()

    def confirm_stream_gravimetric_starting_return_ready(self):
        if not self._stream_gravimetric_machine_queue_empty():
            return False, "Wait for the machine command queue before returning to the camera."
        return self.model.calibration_manager.confirm_stream_gravimetric_starting_return_ready()

    def begin_stream_gravimetric_capture_loading_move(self):
        return self.model.calibration_manager.begin_stream_gravimetric_capture_loading_move()

    def on_stream_gravimetric_capture_loading_reached(self):
        state = self.model.calibration_manager.get_stream_gravimetric_capture_state()
        use_balance_ending = bool(
            self.experimental_balance_enabled
            and self.experimental_balance_stream_opt_in
            and str(state.get("mass_source") or "") == "veritas_balance"
            and self._experimental_balance_is_streaming()
        )
        return self.model.calibration_manager.mark_stream_gravimetric_capture_loading_reached(
            use_balance_ending=use_balance_ending,
        )

    def begin_stream_gravimetric_capture_camera_return(self):
        return self.model.calibration_manager.begin_stream_gravimetric_capture_camera_return()

    def on_stream_gravimetric_capture_camera_reached(self):
        return self.model.calibration_manager.mark_stream_gravimetric_capture_camera_reached()

    def report_stream_gravimetric_capture_move_failure(self, target, error_message=""):
        return self.model.calibration_manager.report_stream_gravimetric_capture_move_failure(
            target=target,
            error_message=error_message,
        )

    # def start_pressure_scan_calibration(self):
    #     # Tell the Model to start the pressure scan calibration.
    #     self.model.calibration_manager.start_pressure_scan_calibration()

    def start_trajectory_calibration(self):
        # Tell the Model to start the trajectory calibration.
        self.model.calibration_manager.start_trajectory_calibration()

    def start_pressure_trajectory_calibration(self):
        # Tell the Model to start the pressure trajectory calibration.
        self.model.calibration_manager.start_pressure_trajectory_calibration()

    def start_droplet_search_calibration(self):
        # Tell the Model to start the droplet search calibration.
        self.model.calibration_manager.start_droplet_search_calibration()

    def start_droplet_characterization_calibration(self):
        # Tell the Model to start the droplet characterization calibration.
        return self.model.calibration_manager.start_manual_droplet_characterization()

    def start_all_calibrations(self):
        # Tell the Model to start all calibrations.
        self.model.calibration_manager.add_all_calibrations_to_queue()

    def stop_calibration(self):
        # Tell the Model to stop the calibration.
        self.cancel_pending_droplet_capture("calibration_stop", emit_capture_failed=True, recover=True)
        self.model.calibration_manager.stop()

    def start_flash(self):
        self.machine.start_flash()

    def stop_flash(self):
        self.machine.stop_flash()

    def center_nozzle_in_camera(self,position=None,callback=None):
        centered_nozzle_position = self.model.calibration_manager.get_nozzle_center()
        # Create a copy of the centered nozzle position
        target_position = centered_nozzle_position.copy()
        if target_position is None:
            print('Nozzle center not found')
            return
        if position == 'top':
            current = self.model.droplet_camera_model.get_center_in_pixels()
            print(f'-Current center in pixels: {current}')
            move_vector = self.model.droplet_camera_model.calculate_move_to_top_center(current,offset=150)
            print(f'-Move vector to top center: {move_vector}')
            dX, dY, dZ = move_vector
            target_position['X'] += dX
            target_position['Y'] += dY
            target_position['Z'] += dZ
        print(f'-Centering nozzle at position: {target_position}')
        self.set_absolute_coordinates(target_position['X'],target_position['Y'],target_position['Z'],handler=callback)

    # --------------------------
    # Legacy commands
    # --------------------------
    def update_balance_prediction_models(self, target_volume: float):
        """Called by MassCalibrationDialog.handle_model_change(...)"""
        if not self.balance or self.profile.name != "legacy":
            return
        pred_path = self.model.calibration_model.get_selected_model_path()
        res_path  = self.model.calibration_model.get_selected_resistance_model_path()
        if pred_path and res_path:
            self.balance.update_prediction_models(pred_path, res_path, target_volume)
    
    # def start_mass_stabilization_timer(self):
    #     from PySide6 import QtCore
    #     QtCore.QTimer.singleShot(2000, self.model.calibration_model.check_for_final_mass)

    # def print_calibration_droplets(self, droplets, manual=False, pulse_width=None):
    #     """Used by MassCalibrationDialog when initial mass is captured."""
    #     if pulse_width is None:
    #         pulse_width = int(getattr(self.model.machine_model, "pulse_width", 0) or 0)

    #     # ensure controller/machine uses that pulse width
    #     if pulse_width:
    #         self.set_print_pulse_width(pulse_width, manual=False)

    #     # if virtual balance is running, enqueue a simulated droplet event
    #     if self.balance and getattr(self.balance, "simulate", False):
    #         self.machine.balance_droplets.append([int(droplets), int(pulse_width)])

    #     # print droplets; when finished, wait then allow final mass capture
    #     self.machine.print_droplets(int(droplets), handler=self.start_mass_stabilization_timer, kwargs={}, manual=manual)


    # -------------------------
    # Preprogrammed sequences
    # -------------------------
    def start_preprogrammed_sequence(self, seq_id: str, delay_s: float = 0.0, **params):
        """
        Start a named sequence after a delay with countdown shown in UI.
        During countdown, TX is hard-paused (Machine.set_sequence_pause(True)).
        """
        if seq_id not in getattr(self, "_sequence_builders", {}):
            self.sequence_error.emit(f"Unknown sequence: {seq_id}")
            return

        if self._seq_state in ("countdown", "running"):
            self.sequence_error.emit("A sequence is already in progress.")
            return

        # Basic safety checks
        try:
            if not self.model.machine_model.is_connected():
                self.sequence_error.emit("Machine is not connected.")
                return
        except Exception:
            # If your model API differs, you can remove this check
            pass

        if not self.machine.check_if_all_completed():
            self.sequence_error.emit("Cannot start: command queue is not empty.")
            return

        delay_s = max(0.0, float(delay_s))
        self._seq_id = seq_id
        self._seq_params = dict(params)

        # Hard-pause TX during countdown so nothing can move early
        self.machine.set_sequence_pause(True)

        if delay_s <= 0.0:
            self.sequence_countdown_s.emit(0.0)
            self._begin_sequence()
            return

        self._seq_deadline_monotonic = self._monotonic_fn() + delay_s
        self._seq_state = "countdown"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_countdown_s.emit(delay_s)
        self._seq_timer.start()

    def cancel_preprogrammed_sequence(self):
        """Cancels only the countdown stage (does not try to stop an already-running queue)."""
        if self._seq_state != "countdown":
            return
        self._seq_timer.stop()
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_countdown_s.emit(0.0)
        self._seq_id = None
        self._seq_params = {}
        self.machine.set_sequence_pause(False)

    def _on_seq_tick(self):
        remaining = self._seq_deadline_monotonic - self._monotonic_fn()
        if remaining <= 0:
            self._seq_timer.stop()
            self.sequence_countdown_s.emit(0.0)
            self._begin_sequence()
            return
        self.sequence_countdown_s.emit(remaining)

    def _begin_sequence(self):
        # Re-check queue: if anything got queued during countdown, abort
        if not self.machine.check_if_all_completed():
            self._abort_sequence("Queue became non-empty during countdown; aborting.")
            return
        
        self.update_expected_with_current()

        seq_id = self._seq_id
        builder = self._sequence_builders.get(seq_id)
        if builder is None:
            self._abort_sequence(f"Unknown sequence: {seq_id}")
            return

        self._seq_state = "running"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_started.emit(seq_id)

        # Keep TX paused while we enqueue the whole block
        self.machine.set_sequence_pause(True)

        try:
            builder()  # enqueue commands using controller/machine methods
        except Exception as e:
            self._abort_sequence(f"Sequence build failed: {e}")
            return
        finally:
            # Ensure TX is resumed even if builder raises (abort handles state too)
            pass

        # Resume TX and nudge sender
        self.machine.set_sequence_pause(False)
        try:
            self.machine.send_next_command()
        except Exception:
            pass

        # If a sequence enqueued nothing (edge case), complete immediately
        if self.machine.check_if_all_completed():
            self._finish_sequence()

    def _abort_sequence(self, msg: str):
        self._seq_timer.stop()
        self.machine.set_sequence_pause(False)
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_error.emit(msg)
        self._seq_id = None
        self._seq_params = {}
        self.sequence_countdown_s.emit(0.0)

    def _finish_sequence(self):
        seq_id = self._seq_id
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        if seq_id:
            self.sequence_completed.emit(seq_id)
        self._seq_id = None
        self._seq_params = {}
        self.sequence_countdown_s.emit(0.0)

    def _on_commands_completed_for_sequence(self):
        """Called whenever the queue drains; if we’re running a sequence, mark it done."""
        if self._seq_state == "running":
            self._finish_sequence()

    # -------------------------
    # Example sequence builders
    # -------------------------

    def _seq_pickup_slot_imager_return(self):
        """
        Pick up a head from a slot, move to imager, return to same slot.
        NOTE: Adjust location names if yours differ.
        """
        slot_1based = int(self._seq_params.get("slot", 1))
        slot = max(1, min(slot_1based, 4)) - 1

        # These calls enqueue many commands:
        self.pick_up_printer_head(slot)
        self.move_to_location("camera")      # <-- change if your imager location is named differently
        self.drop_off_printer_head(slot)

    def _seq_led_on_wait_off(self):
        """
        Turn LEDs on, wait N seconds (firmware WAIT), then off.
        """
        on_s = float(self._seq_params.get("on_s", 5.0))
        on_ms = max(1, int(on_s * 1000))

        self.machine.LED_on()
        self.machine.wait_ms(on_ms)
        self.machine.LED_off()

    def _seq_imager_plate_imager(self):
        """
        Move from imager to plate and back.
        NOTE: Adjust location names if yours differ.
        """
        self.move_to_location("camera")   # imager
        self.move_to_location("plate")    # plate
        self.move_to_location("camera")   # back

    def _seq_snake_grid_droplet_print(self):
        """
        Prints a snake-pattern grid of droplets starting at the current position.

        Pattern:
        - For each row:
            - print droplets at current position
            - move in Y between columns (direction alternates each row)
            - at end of row, move +X to next row (no Y reset; snake continues)

        Params expected in self._seq_params:
        rows (int)      : number of rows (X direction)
        cols (int)      : number of columns (Y direction)
        step (int)      : relative move in "steps" between spots (applied to both X and Y)
        droplets (int)  : number of droplets to print at each spot
        """
        rows = int(self._seq_params.get("rows", 1))
        cols = int(self._seq_params.get("cols", 1))
        step = int(self._seq_params.get("step", 0))
        droplets = int(self._seq_params.get("droplets", 1))

        # basic sanitation
        rows = max(1, rows)
        cols = max(1, cols)
        droplets = max(1, droplets)
        # allow step = 0 (prints all on same spot), but clamp negatives
        step = max(0, step)

        for r in range(rows):
            direction = +1 if (r % 2 == 0) else -1  # snake direction along Y

            for c in range(cols):
                # Print droplets at this grid point
                self.print_droplets(droplets)

                # Move to next column (Y) unless we're at end of the row
                if c < (cols - 1):
                    dy = direction * step
                    if dy != 0:
                        self.set_relative_Y(dy)

            # Move to next row (X) unless we're at last row
            if r < (rows - 1):
                if step != 0:
                    self.set_relative_X(step)

    def _seq_droplet_walk_y(self):
        """
        Demo sequence: Print increasing droplet counts while stepping +Y.

        Default behavior:
        spot 1: 1 droplet
        move +Y (step)
        spot 2: 2 droplets
        move +Y (step)
        spot 3: 3 droplets
        ...

        Params in self._seq_params:
        n_spots (int)        : number of spots along the line (>=1)
        step_y (int)         : relative Y move between spots, in steps (>=0)
        start_droplets (int) : droplets at first spot (>=1), default 1
        inc_droplets (int)   : increment each spot (>=0), default 1
        """
        n_spots = int(self._seq_params.get("n_spots", 5))
        step_y = int(self._seq_params.get("step_y", 50))
        start = int(self._seq_params.get("start_droplets", 1))
        inc = int(self._seq_params.get("inc_droplets", 1))

        n_spots = max(1, n_spots)
        step_y = max(0, step_y)
        start = max(1, start)
        inc = max(0, inc)

        droplets = start

        for i in range(n_spots):
            self.print_droplets(droplets)

            if i < (n_spots - 1) and step_y != 0:
                self.set_relative_Y(step_y)

            droplets += inc

    def _seq_bridge_and_pull_y(self):
        """
        Bridge & Pull demo in Y.

        Steps:
        1) Print payload droplets at current position.
        2) Move +Y by separation_steps.
        3) Print target droplets.
        4) Print 1-droplet bridge spots from target toward payload:
                (move -Y by bridge_spacing_steps, print 1 droplet) repeated.

        Params in self._seq_params:
        payload_droplets (int)       : droplets at payload position
        target_droplets (int)        : droplets at target position
        separation_steps (int)       : +Y distance between payload and target
        bridge_spacing_steps (int)   : spacing between bridge droplets (printed from target toward payload)
        """
        payload = int(self._seq_params.get("payload_droplets", 5))
        target = int(self._seq_params.get("target_droplets", 10))
        separation = int(self._seq_params.get("separation_steps", 200))
        bridge_spacing = int(self._seq_params.get("bridge_spacing_steps", 50))

        payload = max(1, payload)
        target = max(1, target)
        separation = max(0, separation)
        bridge_spacing = max(1, bridge_spacing)  # must be >=1 to avoid infinite loops

        # 1) Payload at start position
        self.print_droplets(payload)

        # 2) Move to target position (+Y)
        if separation != 0:
            self.set_relative_Y(separation)

        # 3) Target droplet
        self.print_droplets(target)

        # 4) Bridge droplets from target toward payload.
        #    Compute how many bridge points to place so that the last bridge point is within
        #    one bridge_spacing of the payload (or closer), without necessarily printing on top of payload.
        if separation == 0:
            return

        n_bridge = max(0, int(math.ceil(separation / bridge_spacing)) - 1)

        for _ in range(n_bridge):
            self.set_relative_Y(-bridge_spacing)
            self.print_droplets(1)

    def _seq_bridge_pull_y_3step(self):
        """
        3-step Bridge & Pull demo in +Y.

        Workflow:
        - Print initial payload once at the current position.
        - For i in {1..3}:
            - Move +Y by separation_i
            - Print target_i droplets
            - Print bridge droplets from target toward payload (move -Y in steps of bridge_spacing_i, print 1 droplet each)
            - Return to the target position (so the next step starts from "where the droplet likely moved")

        Params in self._seq_params:
        payload_droplets (int)

        step1_target_droplets (int)
        step1_separation_steps (int)
        step1_bridge_spacing_steps (int)

        step2_target_droplets (int)
        step2_separation_steps (int)
        step2_bridge_spacing_steps (int)

        step3_target_droplets (int)
        step3_separation_steps (int)
        step3_bridge_spacing_steps (int)
        """

        def _bridge_pull_one_step(separation: int, target_droplets: int, bridge_spacing: int):
            """
            Executes one bridge & pull step starting from the current payload position.
            After this returns, the head is positioned back at the target location (payload advanced).
            """
            separation = max(0, int(separation))
            target_droplets = max(1, int(target_droplets))
            bridge_spacing = max(1, int(bridge_spacing))  # avoid infinite loop

            # Move to target position (+Y)
            if separation != 0:
                self.set_relative_Y(separation)

            # Print target droplet cluster
            self.print_droplets(target_droplets)

            # If no separation, nothing to bridge
            if separation == 0:
                return

            # Number of bridge points so the last bridge is within <= bridge_spacing of payload
            n_bridge = max(0, int(math.ceil(separation / bridge_spacing)) - 1)

            # Print bridging droplets from target back toward payload
            for _ in range(n_bridge):
                self.set_relative_Y(-bridge_spacing)
                self.print_droplets(1)

            # Return to target position (so next step starts from expected "moved" droplet location)
            if n_bridge > 0:
                self.set_relative_Y(n_bridge * bridge_spacing)

        payload = max(1, int(self._seq_params.get("payload_droplets", 5)))
        self.print_droplets(payload)

        # Step 1
        _bridge_pull_one_step(
            separation=self._seq_params.get("step1_separation_steps", 200),
            target_droplets=self._seq_params.get("step1_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step1_bridge_spacing_steps", 50),
        )

        # Step 2
        _bridge_pull_one_step(
            separation=self._seq_params.get("step2_separation_steps", 200),
            target_droplets=self._seq_params.get("step2_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step2_bridge_spacing_steps", 50),
        )

        # Step 3
        _bridge_pull_one_step(
            separation=self._seq_params.get("step3_separation_steps", 200),
            target_droplets=self._seq_params.get("step3_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step3_bridge_spacing_steps", 50),
        )

