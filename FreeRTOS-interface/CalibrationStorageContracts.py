"""Milestone 3 process result and capture-retention contracts.

This module intentionally contains no Qt or hardware imports.  It is the
single inventory used by CalibrationManager to reject undeclared production
processes before they start.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Mapping

from CalibrationRecordingStore import CaptureRetentionPolicy


SUMMARY_PROJECTION_SCHEMA_NAME = "labcraft.calibration_recording.summary_projection"
SUMMARY_PROJECTION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CalibrationProcessStorageContract:
    result_kind: str
    terminal_adapter: str
    minimum_capture_policy: CaptureRetentionPolicy = CaptureRetentionPolicy.STRUCTURED_ONLY
    application_eligible: bool = False


_CONTRACTS = {
    "HeadPrimeCalibrationProcess": CalibrationProcessStorageContract(
        "operational", "operational"
    ),
    "NozzlePositionCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "nozzle_position"
    ),
    "NozzleFocusCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "DropletEmergenceCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "PressureCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "PreBreakupMorphologyCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "PreBreakupDatasetAcquisitionProcess": CalibrationProcessStorageContract(
        "dataset", "dataset_manifest", CaptureRetentionPolicy.FULL
    ),
    "PressureBandCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "TrajectoryCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "PressureTrajectoryCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "final_calibration"
    ),
    "DropletSearchCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "characterization", application_eligible=True
    ),
    "PressureSweepCharacterizationProcess": CalibrationProcessStorageContract(
        "calibration", "characterization", application_eligible=True
    ),
    "OnlineStreamCalibrationProcess": CalibrationProcessStorageContract(
        "calibration", "characterization", application_eligible=True
    ),
    "DropletTimecourseProcess": CalibrationProcessStorageContract(
        "dataset", "dataset_manifest", CaptureRetentionPolicy.FULL
    ),
}

PRODUCTION_PROCESS_NAMES = frozenset(_CONTRACTS)


def process_storage_contract(process: Any) -> CalibrationProcessStorageContract:
    """Resolve an explicit contract or fail before the process can start."""

    if isinstance(process, str):
        process_name = process
        declared_kind = None
    elif isinstance(process, type):
        process_name = process.__name__
        declared_kind = getattr(process, "calibration_storage_result_kind", None)
    else:
        process_name = type(process).__name__
        declared_kind = getattr(process, "calibration_storage_result_kind", None)
    if declared_kind is not None:
        minimum = CaptureRetentionPolicy.parse(
            getattr(process, "calibration_storage_minimum_capture_policy", "structured_only")
        )
        return CalibrationProcessStorageContract(
            str(declared_kind),
            "process_method",
            minimum,
            bool(getattr(process, "calibration_storage_application_eligible", False)),
        )
    try:
        return _CONTRACTS[str(process_name)]
    except KeyError as exc:
        raise ValueError(
            f"Calibration process {process_name!r} has no canonical storage contract"
        ) from exc


_RESULT_FIELD_ALLOWLIST = frozenset(
    {
        "pressure",
        "pressure_psi",
        "pulse_width",
        "pulse_width_us",
        "print_pulse_width_us",
        "mean_nL",
        "mean_volume_nl",
        "predicted_volume_nl",
        "printing_mode",
        "valid",
        "invalid_reason",
        "flash_delay",
        "best_focus",
        "frame_count",
        "condition_count",
        "completed_condition_count",
        "dataset_run_id",
        "action",
        "captured",
        "area",
        "selected_pressure_psi",
        "valid_fit_count",
        "emergence_time_us",
        "start_delay_us",
        "step_us",
        "window_us",
    }
)


def _bounded_result_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload, Mapping) else None
    source = result if isinstance(result, Mapping) else {}
    return {key: source[key] for key in _RESULT_FIELD_ALLOWLIST if key in source}


def _dataset_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload, Mapping) else None
    source = result if isinstance(result, Mapping) else {}
    manifest = _bounded_result_fields(payload)
    frames = source.get("frames")
    if "frame_count" not in manifest and isinstance(frames, list):
        manifest["frame_count"] = len(frames)
    conditions = source.get("conditions")
    if "condition_count" not in manifest and isinstance(conditions, list):
        manifest["condition_count"] = len(conditions)
    relative_refs = {}
    for key, value in source.items():
        if not str(key).endswith(("_relpath", "_manifest")) or not isinstance(value, str):
            continue
        path = PurePath(value)
        if not path.is_absolute() and ".." not in path.parts:
            relative_refs[str(key)] = value
    if relative_refs:
        manifest["relative_references"] = relative_refs
    return manifest


def _nozzle_position_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload, Mapping) else None
    source = result if isinstance(result, Mapping) else {}
    bounded = {
        axis: int(source[axis])
        for axis in ("X", "Y", "Z")
        if isinstance(source.get(axis), (int, float))
    }
    for key in ("flash_delay", "measurement_count"):
        if isinstance(source.get(key), (int, float)):
            bounded[key] = source[key]
    nozzle_px = source.get("nozzle_center_px")
    if (
        isinstance(nozzle_px, (list, tuple))
        and len(nozzle_px) == 2
        and all(isinstance(value, (int, float)) for value in nozzle_px)
    ):
        bounded["nozzle_center_px"] = [int(value) for value in nozzle_px]
    return bounded


def _first(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _xyz_list(value: Any) -> list[int] | None:
    try:
        if isinstance(value, Mapping):
            values = (value["X"], value["Y"], value["Z"])
        else:
            values = tuple(value)
        if len(values) < 3:
            return None
        return [int(round(float(values[0]))), int(round(float(values[1]))), int(round(float(values[2])))]
    except (KeyError, TypeError, ValueError):
        return None


def _characterization_base_row(
    payload: Mapping[str, Any],
    legacy_source: Mapping[str, Any],
    *,
    process_run_id: str | None,
    update_id: str | None,
    update_index: int | None,
    update_payload_sha256: str | None,
) -> dict[str, Any]:
    return {
        **dict(legacy_source or {}),
        "process_run_id": process_run_id,
        "update_id": update_id,
        "update_index": update_index,
        "update_payload_sha256": update_payload_sha256,
        "timestamp": payload.get("timestamp"),
    }


def materialize_characterization_rows(
    payload: Mapping[str, Any],
    legacy_source: Mapping[str, Any] | None = None,
    *,
    process_run_id: str | None = None,
    update_id: str | None = None,
    update_index: int | None = None,
    update_payload_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Create bounded UI/application rows from one canonical or legacy update."""

    payload = dict(payload or {})
    source = dict(legacy_source or {})
    phase_key = str(
        source.get("source_phase_key") or payload.get("phase") or ""
    ).strip()
    result = dict(payload.get("result") or {})
    settings = dict(payload.get("settings") or {})
    base = _characterization_base_row(
        payload,
        source,
        process_run_id=process_run_id,
        update_id=update_id,
        update_index=update_index,
        update_payload_sha256=update_payload_sha256,
    )
    rows: list[dict[str, Any]] = []

    if phase_key in {"pressure_sweep_characterization", "droplet_recheck", "droplet_search"}:
        pressures = list(result.get("pressures") or [])
        if not pressures and phase_key in {"pressure_sweep_characterization", "droplet_search"}:
            pressures = [result]
        phase = {
            "pressure_sweep_characterization": "sweep",
            "droplet_recheck": "recheck",
            "droplet_search": "search",
        }[phase_key]
        for pressure_ordinal, pressure in enumerate(pressures):
            if not isinstance(pressure, Mapping):
                continue
            pressure = dict(pressure)
            pw_us = _first(
                settings.get("print_width"),
                settings.get("print_pulse_width"),
                result.get("print_pulse_width_us"),
                pressure.get("print_pulse_width_us"),
            )
            pressure_psi = _first(
                pressure.get("pressure"), pressure.get("pressure_psi"),
                settings.get("print_pressure"), result.get("pressure"), result.get("pressure_psi")
            )
            mean_nl = _first(
                pressure.get("mean_volume"),
                pressure.get("mean_nL"),
                result.get("mean_volume"),
                result.get("mean_nL"),
            )
            if phase_key == "droplet_search" and (
                pw_us is None or pressure_psi is None or mean_nl is None
            ):
                continue
            valid = pressure.get("valid", result.get("valid", True))
            target = _xyz_list(
                _first(pressure.get("mean_position_machine"), pressure.get("nominal_target_xyz"))
            )
            row = {
                **base,
                "row_ordinal": len(rows),
                "source_phase_key": phase_key,
                "source_pressure_index": (
                    pressure_ordinal if result.get("pressures") else source.get("source_pressure_index")
                ),
                "phase": phase,
                "pw_us": pw_us,
                "pressure_psi": pressure_psi,
                "delay_us": _first(pressure.get("delay_us"), result.get("delay_us")),
                "target_xyz": target,
                "mean_position_machine": pressure.get("mean_position_machine"),
                "nominal_delay_us": pressure.get("nominal_delay_us"),
                "nominal_target_xyz": pressure.get("nominal_target_xyz"),
                "targeting_mode": _first(pressure.get("targeting_mode"), result.get("targeting_mode")),
                "vec_steps_per_s": pressure.get("vec_steps_per_s"),
                "vx_px_per_us": _first(pressure.get("vx_px_per_us"), pressure.get("vx")),
                "vy_px_per_us": _first(pressure.get("vy_px_per_us"), pressure.get("vy")),
                "nozzle_center_px": _first(result.get("nozzle_center_px"), pressure.get("nozzle_center_px")),
                "nozzle_center_machine": _first(result.get("nozzle_center_machine"), pressure.get("nozzle_center_machine")),
                "emergence_time_us": _first(result.get("emergence_time_us"), pressure.get("emergence_time_us")),
                "manual_current": bool(pressure.get("manual_current", result.get("manual_current", False))),
                "mean_nL": mean_nl,
                "cv_pct": _first(pressure.get("cv_volume_percent"), result.get("cv_volume_percent")),
                "valid": bool(valid),
                "invalid_reason": None if valid else _first(pressure.get("invalid_reason"), result.get("invalid_reason"), "invalid"),
                "printing_mode": "droplet",
            }
            for key in (
                "recheck_source", "reference_mean_volume_nL", "volume_delta_nL",
                "volume_delta_percent", "quality_warning", "quality_warnings",
                "circularity_warning", "circularity_min", "circularity_mean",
                "circularity_warning_threshold",
            ):
                value = _first(pressure.get(key), result.get(key))
                if value is not None:
                    row[key] = value
            rows.append(row)
        return rows

    if phase_key == "online_stream_calibration":
        tail = dict(result.get("tail_phase") or {})
        flow = dict(result.get("flow_phase") or {})
        terminal = bool(
            result.get("predicted_volume_nl") is not None
            or result.get("predicted_stream_duration_us") is not None
            or (tail.get("status") and str(tail.get("status")).lower() != "not_run")
        )
        if not terminal:
            return []
        condition = dict(result.get("condition") or {})
        volume = result.get("predicted_volume_nl")
        try:
            volume = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            volume = None
        tail_status = str(tail.get("status") or "")
        valid = bool(volume is not None and volume > 0 and tail_status.lower() == "captured")
        warnings = result.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = [warnings]
        return [{
            **base,
            "row_ordinal": 0,
            "source_phase_key": phase_key,
            "source_pressure_index": None,
            "phase": "stream",
            "pw_us": _first(condition.get("print_pulse_width_us"), settings.get("print_width")),
            "pressure_psi": _first(condition.get("print_pressure_psi"), settings.get("print_pressure")),
            "mean_nL": volume,
            "cv_pct": None,
            "valid": valid,
            "invalid_reason": None if valid else _first(tail.get("termination_reason"), tail.get("status"), flow.get("fit_status"), warnings[0] if warnings else None, "predicted_volume_unavailable"),
            "printing_mode": "stream",
            "predicted_stream_duration_us": result.get("predicted_stream_duration_us"),
            "flow_fit_status": flow.get("fit_status"),
            "tail_phase_status": tail.get("status"),
            "warnings": [str(item) for item in warnings if str(item or "").strip()],
        }]
    return []


def build_terminal_summary(
    process: Any,
    contract: CalibrationProcessStorageContract,
    run: Any,
    outcome: str,
) -> dict[str, Any]:
    """Build a bounded result projection without duplicating update payloads."""

    custom = getattr(process, "build_calibration_storage_summary_projection", None)
    if contract.terminal_adapter == "process_method" and callable(custom):
        return dict(custom(run, str(outcome)) or {})

    updates = list(getattr(run, "updates", ()) or ())
    selected_updates = (
        updates
        if contract.terminal_adapter == "characterization"
        else updates[-1:]
    )
    rows = []
    for update in selected_updates:
        legacy = dict(update.get("legacy_source") or {})
        payload = dict(update.get("payload") or {})
        if contract.terminal_adapter == "characterization":
            rows.extend(materialize_characterization_rows(
                payload,
                legacy,
                process_run_id=str(run.process_run_id),
                update_id=str(update.get("update_id") or ""),
                update_index=int(update.get("update_index") or 0),
                update_payload_sha256=str(update.get("payload_sha256") or ""),
            ))
        else:
            row = {
                **legacy,
                "process_run_id": str(run.process_run_id),
                "update_id": str(update.get("update_id") or ""),
                "update_index": int(update.get("update_index") or 0),
                "update_payload_sha256": str(update.get("payload_sha256") or ""),
                "timestamp": payload.get("timestamp"),
                **_bounded_result_fields(payload),
            }
            if contract.terminal_adapter == "nozzle_position":
                row["nozzle_position"] = _nozzle_position_result(payload)
            rows.append(row)

    identity = dict(getattr(run, "identity", {}) or {})
    stable_identity = identity.get("identity_quality") == "stable"
    eligible = bool(
        str(outcome) == "completed"
        and contract.result_kind == "calibration"
        and contract.application_eligible
        and stable_identity
        and rows
    )
    projection = {
        "schema_name": SUMMARY_PROJECTION_SCHEMA_NAME,
        "schema_version": SUMMARY_PROJECTION_SCHEMA_VERSION,
        "adapter": contract.terminal_adapter,
        "application_eligible": eligible,
        "status": "eligible" if eligible else "not_applicable",
        "row_count": len(rows),
        "rows": rows,
    }
    if contract.result_kind == "dataset":
        final_payload = dict(updates[-1].get("payload") or {}) if updates else {}
        projection["dataset_manifest"] = _dataset_manifest(final_payload)
    return projection


__all__ = [
    "CalibrationProcessStorageContract",
    "PRODUCTION_PROCESS_NAMES",
    "SUMMARY_PROJECTION_SCHEMA_NAME",
    "SUMMARY_PROJECTION_SCHEMA_VERSION",
    "build_terminal_summary",
    "materialize_characterization_rows",
    "process_storage_contract",
]
