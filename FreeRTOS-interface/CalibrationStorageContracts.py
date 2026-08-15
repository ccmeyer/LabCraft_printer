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
        row = {
            **legacy,
            "process_run_id": str(run.process_run_id),
            "update_id": str(update.get("update_id") or ""),
            "update_index": int(update.get("update_index") or 0),
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
    "build_terminal_summary",
    "process_storage_contract",
]
