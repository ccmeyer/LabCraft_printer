"""Reviewed fixture loader/materializer for historical conversion SIL."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
INTERFACE_ROOT = REPO_ROOT / "FreeRTOS-interface"
if str(INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERFACE_ROOT))

from CalibrationRecordingStore import CalibrationRecordingStore  # noqa: E402
from CalibrationStorageContracts import (  # noqa: E402
    build_terminal_summary,
    process_storage_contract,
)


FIXTURE_PATH = (
    REPO_ROOT
    / "tools"
    / "virtual_workflows"
    / "fixtures"
    / "calibration_history_conversion_contract_v1.json"
)
SCHEMA_ID = "labcraft.calibration_history_conversion_fixture"
SCHEMA_VERSION = 1

PHASE_PROCESS = {
    "nozzle_position": "NozzlePositionCalibrationProcess",
    "nozzle_focus": "NozzleFocusCalibrationProcess",
    "droplet_emergence": "DropletEmergenceCalibrationProcess",
    "pressure_calibration": "PressureCalibrationProcess",
    "pressure_scan": "PressureBandCalibrationProcess",
    "trajectory": "TrajectoryCalibrationProcess",
    "pressure_sweep_characterization": "PressureSweepCharacterizationProcess",
    "droplet_recheck": "PressureSweepCharacterizationProcess",
    "droplet_search": "DropletSearchCalibrationProcess",
    "online_stream_calibration": "OnlineStreamCalibrationProcess",
}


def load_fixture(path: str | Path = FIXTURE_PATH) -> dict[str, Any]:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    validate_fixture(value)
    return value


def validate_fixture(value: Mapping[str, Any]) -> None:
    if value.get("schema_id") != SCHEMA_ID or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("historical conversion fixture schema is invalid")
    cases = list(value.get("cases") or ())
    if not cases:
        raise ValueError("historical conversion fixture must contain cases")
    ids = [str(case.get("case_id") or "") for case in cases]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("historical conversion case IDs must be unique")
    if {str(case.get("evidence")) for case in cases} - {
        "none", "unique", "ambiguous", "already_canonical"
    }:
        raise ValueError("historical conversion evidence mode is invalid")
    if not isinstance(value.get("expected_counts"), Mapping):
        raise ValueError("historical conversion expected counts are missing")


def _payload(case: Mapping[str, Any], identity: Mapping[str, Any], ordinal: int):
    phase = str(case["phase"])
    timestamp = f"2025-01-02T03:{ordinal:02d}:00Z"
    return {
        "timestamp": timestamp,
        "settings": {"print_width": 1400, "print_pressure": 1.2},
        "meta": {
            "run_id": f"sil-migration-session-{ordinal:02d}",
            **dict(identity),
        },
        "phase": phase,
        "result": dict(case.get("result") or {}),
    }


def _diagnostic_recording(
    experiment_dir: Path,
    *,
    process_name: str,
    phase: str,
    payload: Mapping[str, Any],
    run_id: str,
) -> None:
    run_dir = experiment_dir / "calibration_recordings" / process_name / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_id,
                "process_name": process_name,
                "phase_name": phase,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "analysis.jsonl").write_text(
        json.dumps(
            {"kind": "calibration_data_updated", "phase": phase, "payload": payload},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def materialize_fixture(
    experiment_dir: str | Path,
    fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = dict(fixture or load_fixture())
    validate_fixture(value)
    root = Path(experiment_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    identity = dict(value["identity"])
    runs: list[dict[str, Any]] = []
    for ordinal, case in enumerate(value["cases"], 1):
        case = dict(case)
        phase = str(case["phase"])
        outcome = str(case["outcome"])
        process_name = PHASE_PROCESS.get(phase)
        payload = _payload(case, identity, ordinal)
        session_id = str(payload["meta"]["run_id"])
        if case["evidence"] == "already_canonical":
            assert process_name is not None
            store = CalibrationRecordingStore(root, clock=lambda: payload["timestamp"])
            contract = process_storage_contract(process_name)
            handle = store.start_run(
                calibration_session_id=session_id,
                process_name=process_name,
                phase_name=phase,
                result_kind=contract.result_kind,
                identity=identity,
                process_run_id=f"natural_existing_{ordinal:02d}",
            )
            update = store.append_update(
                handle,
                payload,
                phase_name=phase,
                recorded_at_utc=payload["timestamp"],
                legacy_source={
                    "source_run_id": session_id,
                    "source_phase_key": phase,
                    "source_step_index": 0,
                },
                include_legacy_reference=True,
            )
            payload = dict(update.document["payload"])
            store.record_parity(handle, update_id=update.update_id, legacy_payload=payload)
            summary = build_terminal_summary(process_name, contract, handle, outcome)
            store.finalize_run(handle, outcome=outcome, summary_projection=summary)
        runs.append(
            {
                "run_id": session_id,
                "started_at": payload["timestamp"],
                "ended_at": payload["timestamp"],
                "outcome": outcome,
                **identity,
                "steps": {phase: [payload]},
            }
        )
        if case["evidence"] in {"unique", "ambiguous"}:
            assert process_name is not None
            count = 2 if case["evidence"] == "ambiguous" else 1
            for evidence_ordinal in range(1, count + 1):
                _diagnostic_recording(
                    root,
                    process_name=process_name,
                    phase=phase,
                    payload=payload,
                    run_id=f"historical_{case['case_id']}_{evidence_ordinal}",
                )
    calibration_path = root / "calibration.json"
    calibration_path.write_text(
        json.dumps({"schema_version": 1, "runs": runs}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {
        "experiment_dir": str(root),
        "calibration_path": str(calibration_path),
        "fixture_id": value["fixture_id"],
        "expected_counts": dict(value["expected_counts"]),
    }


__all__ = [
    "FIXTURE_PATH",
    "PHASE_PROCESS",
    "SCHEMA_ID",
    "SCHEMA_VERSION",
    "load_fixture",
    "materialize_fixture",
    "validate_fixture",
]
