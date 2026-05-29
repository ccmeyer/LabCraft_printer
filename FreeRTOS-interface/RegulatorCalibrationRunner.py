from __future__ import annotations

import copy
import random
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore

from RegulatorProfiles import (
    MODES,
    RegulatorProfileError,
    validate_document,
    validate_profile,
    write_json_atomic,
)


class RegulatorCalibrationError(ValueError):
    pass


class RegulatorCalibrationBatchError(ValueError):
    pass


@dataclass(frozen=True)
class RegulatorTraceCase:
    test_id: int
    name: str
    channels: tuple[str, ...]
    channel_label: str
    pulse_count: int
    frequency_hz: int
    print_pressure_psi: float | None
    print_pulse_width_us: int | None
    refuel_pressure_psi: float | None
    refuel_pulse_width_us: int | None
    custom: bool = False
    pressure_mpsi: int | None = None

    def conditions(self) -> dict[str, Any]:
        conditions = {
            "print_pressure_psi": self.print_pressure_psi,
            "print_pulse_width_us": self.print_pulse_width_us,
            "refuel_pressure_psi": self.refuel_pressure_psi,
            "refuel_pulse_width_us": self.refuel_pulse_width_us,
            "frequency_hz": self.frequency_hz,
            "pulse_count": self.pulse_count,
            "channel": self.channel_label,
        }
        if self.custom:
            conditions["trace_recipe"] = "custom"
            conditions["pressure_mpsi"] = self.pressure_mpsi
        return conditions


CUSTOM_TRACE_CASE_ID = 2110
CUSTOM_TRACE_NAME = "pressure_recovery_trace_custom"
CUSTOM_TRACE_PRESSURE_MPSI_MIN = 100
CUSTOM_TRACE_PRESSURE_MPSI_MAX = 2500
CUSTOM_TRACE_PULSE_US_MIN = 100
CUSTOM_TRACE_PULSE_US_MAX = 10000
CUSTOM_TRACE_PULSE_COUNT_MIN = 1
CUSTOM_TRACE_PULSE_COUNT_MAX = 100
CUSTOM_TRACE_FREQUENCY_HZ_MIN = 1
CUSTOM_TRACE_FREQUENCY_HZ_MAX = 50
CUSTOM_TRACE_MAX_PULSE_WINDOW_MS = 10000
CUSTOM_TRACE_CHANNELS = frozenset({"print", "refuel"})
SERIAL_HANDOFF_MODE_SOFT = "soft"
SERIAL_HANDOFF_MODE_FULL_DISCONNECT = "full_disconnect"
SERIAL_HANDOFF_MODES = frozenset({SERIAL_HANDOFF_MODE_SOFT, SERIAL_HANDOFF_MODE_FULL_DISCONNECT})


TRACE_CASES: dict[int, RegulatorTraceCase] = {
    2101: RegulatorTraceCase(
        test_id=2101,
        name="pressure_recovery_trace_print_single",
        channels=("print",),
        channel_label="print",
        pulse_count=1,
        frequency_hz=20,
        print_pressure_psi=1.0,
        print_pulse_width_us=1300,
        refuel_pressure_psi=None,
        refuel_pulse_width_us=None,
    ),
    2102: RegulatorTraceCase(
        test_id=2102,
        name="pressure_recovery_trace_print_repeated",
        channels=("print",),
        channel_label="print",
        pulse_count=10,
        frequency_hz=20,
        print_pressure_psi=1.0,
        print_pulse_width_us=1300,
        refuel_pressure_psi=None,
        refuel_pulse_width_us=None,
    ),
    2103: RegulatorTraceCase(
        test_id=2103,
        name="pressure_recovery_trace_refuel_repeated",
        channels=("refuel",),
        channel_label="refuel",
        pulse_count=10,
        frequency_hz=20,
        print_pressure_psi=None,
        print_pulse_width_us=None,
        refuel_pressure_psi=0.5,
        refuel_pulse_width_us=3000,
    ),
    2104: RegulatorTraceCase(
        test_id=2104,
        name="pressure_recovery_trace_dual_interleaved",
        channels=("print", "refuel"),
        channel_label="both",
        pulse_count=10,
        frequency_hz=20,
        print_pressure_psi=1.0,
        print_pulse_width_us=1300,
        refuel_pressure_psi=0.5,
        refuel_pulse_width_us=3000,
    ),
}


CONDITION_OVERRIDE_FIELDS = frozenset(
    {
        "print_pressure_psi",
        "print_pulse_width_us",
        "refuel_pressure_psi",
        "refuel_pulse_width_us",
        "frequency_hz",
        "pulse_count",
        "channel",
        "trace_channel",
        "trace_pressure_psi",
        "trace_pressure_mpsi",
        "trace_pulse_us",
        "trace_pulse_count",
        "trace_frequency_hz",
    }
)


@dataclass
class PreparedRegulatorCalibrationRun:
    run_id: str
    session_id: str
    run_dir: Path
    raw_selftest_path: Path
    trace_case: RegulatorTraceCase
    profile_id: str
    mode: str
    serial_handoff_mode: str
    candidate_profile: dict[str, Any]
    baseline_profile: dict[str, Any]
    operator: str
    conditions: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class PreparedRegulatorCalibrationBatch:
    session_id: str
    session_dir: Path
    manifest_path: Path
    mode: str
    serial_handoff_mode: str
    trace_case: RegulatorTraceCase
    baseline_profile_id: str
    candidate_profile_ids: list[str]
    repeat_count: int
    order_strategy: str
    random_seed: int | None
    conditions: dict[str, Any]
    runs: list[dict[str, Any]]
    manifest: dict[str, Any]
    output_root: Path


def trace_case_choices() -> list[dict[str, Any]]:
    return [
        {
            "test_id": case.test_id,
            "name": case.name,
            "channels": case.channels,
            "pulse_count": case.pulse_count,
            "frequency_hz": case.frequency_hz,
            "print_pressure_psi": case.print_pressure_psi,
            "print_pulse_width_us": case.print_pulse_width_us,
            "refuel_pressure_psi": case.refuel_pressure_psi,
            "refuel_pulse_width_us": case.refuel_pulse_width_us,
        }
        for case in TRACE_CASES.values()
    ]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d_%H%M%S")


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _string_or_empty(value: Any) -> str:
    return str(value or "").strip()


def _bool_from_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def serial_handoff_mode_from_config(config: dict[str, Any]) -> str:
    mode = _string_or_empty(config.get("serial_handoff_mode") or SERIAL_HANDOFF_MODE_SOFT).lower()
    if mode not in SERIAL_HANDOFF_MODES:
        allowed = ", ".join(sorted(SERIAL_HANDOFF_MODES))
        raise RegulatorCalibrationError(f"serial_handoff_mode must be one of {allowed}")
    return mode


def _int_field(config: dict[str, Any], key: str, label: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or value is None:
        raise RegulatorCalibrationError(f"{label} is required")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RegulatorCalibrationError(f"{label} must be an integer") from exc


def _custom_pressure_mpsi(config: dict[str, Any]) -> int:
    if "trace_pressure_mpsi" in config:
        return _int_field(config, "trace_pressure_mpsi", "trace_pressure_mpsi")
    value = config.get("trace_pressure_psi")
    if isinstance(value, bool) or value is None:
        raise RegulatorCalibrationError("trace_pressure_psi is required")
    try:
        return int(round(float(value) * 1000.0))
    except (TypeError, ValueError) as exc:
        raise RegulatorCalibrationError("trace_pressure_psi must be numeric") from exc


def custom_trace_case_from_config(config: dict[str, Any]) -> RegulatorTraceCase:
    channel = _string_or_empty(config.get("trace_channel")).lower()
    if channel not in CUSTOM_TRACE_CHANNELS:
        raise RegulatorCalibrationError("trace_channel must be print or refuel")
    pressure_mpsi = _custom_pressure_mpsi(config)
    pulse_us = _int_field(config, "trace_pulse_us", "trace_pulse_us")
    pulse_count = _int_field(config, "trace_pulse_count", "trace_pulse_count")
    frequency_hz = _int_field(config, "trace_frequency_hz", "trace_frequency_hz")

    if not (CUSTOM_TRACE_PRESSURE_MPSI_MIN <= pressure_mpsi <= CUSTOM_TRACE_PRESSURE_MPSI_MAX):
        raise RegulatorCalibrationError("trace pressure must be between 0.1 and 2.5 psi")
    if not (CUSTOM_TRACE_PULSE_US_MIN <= pulse_us <= CUSTOM_TRACE_PULSE_US_MAX):
        raise RegulatorCalibrationError(
            f"trace_pulse_us must be between {CUSTOM_TRACE_PULSE_US_MIN} and {CUSTOM_TRACE_PULSE_US_MAX}"
        )
    if not (CUSTOM_TRACE_PULSE_COUNT_MIN <= pulse_count <= CUSTOM_TRACE_PULSE_COUNT_MAX):
        raise RegulatorCalibrationError(
            f"trace_pulse_count must be between {CUSTOM_TRACE_PULSE_COUNT_MIN} and {CUSTOM_TRACE_PULSE_COUNT_MAX}"
        )
    if not (CUSTOM_TRACE_FREQUENCY_HZ_MIN <= frequency_hz <= CUSTOM_TRACE_FREQUENCY_HZ_MAX):
        raise RegulatorCalibrationError(
            f"trace_frequency_hz must be between {CUSTOM_TRACE_FREQUENCY_HZ_MIN} and {CUSTOM_TRACE_FREQUENCY_HZ_MAX}"
        )
    if pulse_us >= (1_000_000 // frequency_hz):
        raise RegulatorCalibrationError("trace_pulse_us must be shorter than the pulse period")
    planned_window_ms = (pulse_count * 1000 + frequency_hz - 1) // frequency_hz
    if planned_window_ms > CUSTOM_TRACE_MAX_PULSE_WINDOW_MS:
        raise RegulatorCalibrationError(
            f"custom trace pulse window must be no more than {CUSTOM_TRACE_MAX_PULSE_WINDOW_MS} ms"
        )

    pressure_psi = pressure_mpsi / 1000.0
    return RegulatorTraceCase(
        test_id=CUSTOM_TRACE_CASE_ID,
        name=CUSTOM_TRACE_NAME,
        channels=(channel,),
        channel_label=channel,
        pulse_count=pulse_count,
        frequency_hz=frequency_hz,
        print_pressure_psi=pressure_psi if channel == "print" else None,
        print_pulse_width_us=pulse_us if channel == "print" else None,
        refuel_pressure_psi=pressure_psi if channel == "refuel" else None,
        refuel_pulse_width_us=pulse_us if channel == "refuel" else None,
        custom=True,
        pressure_mpsi=pressure_mpsi,
    )


def _trace_case_from_config(config: dict[str, Any]) -> RegulatorTraceCase:
    try:
        trace_case_id = int(config.get("trace_case_id"))
    except (TypeError, ValueError):
        raise RegulatorCalibrationError("trace_case_id must be one of the supported pressure trace cases")
    if trace_case_id == CUSTOM_TRACE_CASE_ID:
        return custom_trace_case_from_config(config)
    case = TRACE_CASES.get(trace_case_id)
    if case is None:
        raise RegulatorCalibrationError("trace_case_id must be one of the supported pressure trace cases")
    return case


def _reject_condition_overrides(config: dict[str, Any]) -> None:
    provided = sorted(field for field in CONDITION_OVERRIDE_FIELDS if field in config)
    if provided:
        raise RegulatorCalibrationError(
            "Stage 4 uses fixed firmware pressure-trace recipes; remove unsupported condition overrides: "
            + ", ".join(provided)
        )


def _profile_document_from_store_or_payload(profile_document: dict[str, Any] | None) -> dict[str, Any]:
    if profile_document is None:
        raise RegulatorCalibrationError("regulator profile document is not loaded")
    try:
        return validate_document(profile_document)
    except RegulatorProfileError as exc:
        raise RegulatorCalibrationError(str(exc)) from exc


def prepare_regulator_calibration_run(
    config: dict[str, Any],
    *,
    profile_document: dict[str, Any] | None,
    output_root: str | Path,
    now_fn: Callable[[], datetime] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> PreparedRegulatorCalibrationRun:
    config = dict(config or {})
    if not bool(config.get("calibrated_head_confirmed")):
        raise RegulatorCalibrationError("Confirm that a calibrated printer head is installed before starting.")
    serial_handoff_mode = serial_handoff_mode_from_config(config)
    trace_case = _trace_case_from_config(config)
    if not trace_case.custom:
        _reject_condition_overrides(config)

    document = _profile_document_from_store_or_payload(profile_document)
    profile_id = _string_or_empty(config.get("profile_id"))
    if not profile_id:
        raise RegulatorCalibrationError("profile_id is required")
    profiles = document.get("profiles", {})
    if profile_id not in profiles:
        raise RegulatorCalibrationError(f"profile {profile_id} does not exist")
    candidate_profile = validate_profile(profiles[profile_id], profile_id=profile_id)

    requested_mode = _string_or_empty(config.get("mode")) or str(candidate_profile.get("mode") or "")
    requested_mode = requested_mode.lower()
    if requested_mode not in MODES:
        raise RegulatorCalibrationError(f"mode must be one of {sorted(MODES)}")
    if candidate_profile.get("mode") != requested_mode:
        raise RegulatorCalibrationError(
            f"profile {profile_id} mode {candidate_profile.get('mode')} does not match selected mode {requested_mode}"
        )

    active_profile_id = document.get("active_profiles", {}).get(requested_mode)
    active_profile = None
    if active_profile_id:
        active_profile = document.get("profiles", {}).get(active_profile_id)
    baseline_profile = {
        "firmware_baseline_source": "internal_stage2_snapshot",
        "active_profile_id": active_profile_id,
        "active_profile": copy.deepcopy(active_profile),
    }

    now = (now_fn or _now_utc)()
    suffix = (id_factory or _short_id)()
    session_id = _string_or_empty(config.get("session_id")) or f"session_{_timestamp(now)}_{suffix}"
    run_id = _string_or_empty(config.get("run_id")) or f"regopt_{_timestamp(now)}_{suffix}"
    run_dir_name = _string_or_empty(config.get("run_dir_name")) or f"run_{_timestamp(now)}_{suffix}"
    run_dir = Path(output_root) / session_id / run_dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_selftest_path = run_dir / "raw_selftest.json"

    conditions = {
        "printer_head_id": _string_or_empty(config.get("printer_head_id")),
        "printer_head_type": _string_or_empty(config.get("printer_head_type")),
        "reagent_id": _string_or_empty(config.get("reagent_id")),
        **trace_case.conditions(),
    }

    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "created_at_utc": _iso_utc(now),
        "operator": _string_or_empty(config.get("operator")),
        "mode": requested_mode,
        "serial_handoff_mode": serial_handoff_mode,
        "candidate_profile_id": profile_id,
        "candidate_profile": copy.deepcopy(candidate_profile),
        "baseline_profile": baseline_profile,
        "conditions": conditions,
        "outputs": {
            "trace_files": [],
            "analysis_json": None,
            "summary_csv": None,
            "plots": [],
        },
        "outcome": {
            "status": "failed",
            "restored_previous_profile": False,
            "error_message": "Run metadata initialized before calibration completed.",
        },
    }

    return PreparedRegulatorCalibrationRun(
        run_id=run_id,
        session_id=session_id,
        run_dir=run_dir,
        raw_selftest_path=raw_selftest_path,
        trace_case=trace_case,
        profile_id=profile_id,
        mode=requested_mode,
        serial_handoff_mode=serial_handoff_mode,
        candidate_profile=copy.deepcopy(candidate_profile),
        baseline_profile=baseline_profile,
        operator=metadata["operator"],
        conditions=conditions,
        metadata=metadata,
    )


def _candidate_profile_ids(config: dict[str, Any]) -> list[str]:
    raw = (
        config.get("candidate_profile_ids")
        or config.get("profile_ids")
        or config.get("candidate_profiles")
        or []
    )
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace(";", ",").split(",")]
    if not isinstance(raw, (list, tuple)):
        raise RegulatorCalibrationBatchError("candidate_profile_ids must be a list of profile IDs")
    ids = [_string_or_empty(item) for item in raw]
    ids = [item for item in ids if item]
    if len(ids) != len(set(ids)):
        raise RegulatorCalibrationBatchError("candidate_profile_ids must not contain duplicates")
    return ids


def _batch_schedule_candidates(
    candidate_profile_ids: list[str],
    repeat_count: int,
    order_strategy: str,
    random_seed: int | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if order_strategy == "grouped":
        for profile_id in candidate_profile_ids:
            for repeat_index in range(1, repeat_count + 1):
                entries.append({"role": "candidate", "profile_id": profile_id, "repeat_index": repeat_index})
    else:
        for repeat_index in range(1, repeat_count + 1):
            for profile_id in candidate_profile_ids:
                entries.append({"role": "candidate", "profile_id": profile_id, "repeat_index": repeat_index})
    if order_strategy == "randomized":
        rng = random.Random(random_seed)
        rng.shuffle(entries)
    return entries


def prepare_regulator_calibration_batch(
    config: dict[str, Any],
    *,
    profile_document: dict[str, Any] | None,
    output_root: str | Path,
    now_fn: Callable[[], datetime] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> PreparedRegulatorCalibrationBatch:
    config = dict(config or {})
    if not bool(config.get("calibrated_head_confirmed")):
        raise RegulatorCalibrationBatchError("Confirm that a calibrated printer head is installed before starting.")
    try:
        serial_handoff_mode = serial_handoff_mode_from_config(config)
    except RegulatorCalibrationError as exc:
        raise RegulatorCalibrationBatchError(str(exc)) from exc
    try:
        trace_case = _trace_case_from_config(config)
    except RegulatorCalibrationError as exc:
        raise RegulatorCalibrationBatchError(str(exc)) from exc
    if not trace_case.custom:
        try:
            _reject_condition_overrides(config)
        except RegulatorCalibrationError as exc:
            raise RegulatorCalibrationBatchError(str(exc)) from exc

    try:
        document = _profile_document_from_store_or_payload(profile_document)
    except RegulatorCalibrationError as exc:
        raise RegulatorCalibrationBatchError(str(exc)) from exc
    mode = _string_or_empty(config.get("mode")).lower()
    if mode not in {"droplet", "stream"}:
        raise RegulatorCalibrationBatchError("batch mode must be droplet or stream")
    profiles = document.get("profiles", {})
    candidate_profile_ids = _candidate_profile_ids(config)
    if not (1 <= len(candidate_profile_ids) <= 12):
        raise RegulatorCalibrationBatchError("candidate_profile_ids must contain 1 to 12 profiles")

    baseline_profile_id = _string_or_empty(config.get("baseline_profile_id")) or _string_or_empty(
        document.get("active_profiles", {}).get(mode)
    )
    if not baseline_profile_id:
        raise RegulatorCalibrationBatchError(f"active baseline profile for {mode} is required")
    all_profile_ids = [baseline_profile_id, *candidate_profile_ids]
    for profile_id in all_profile_ids:
        if profile_id not in profiles:
            raise RegulatorCalibrationBatchError(f"profile {profile_id} does not exist")
        profile = validate_profile(profiles[profile_id], profile_id=profile_id)
        if profile.get("mode") != mode:
            raise RegulatorCalibrationBatchError(f"profile {profile_id} mode {profile.get('mode')} does not match batch mode {mode}")

    try:
        repeat_count = int(config.get("repeat_count", 1))
    except (TypeError, ValueError):
        raise RegulatorCalibrationBatchError("repeat_count must be an integer")
    if not (1 <= repeat_count <= 5):
        raise RegulatorCalibrationBatchError("repeat_count must be between 1 and 5")

    order_strategy = _string_or_empty(config.get("order_strategy") or "alternating").lower()
    if order_strategy not in {"alternating", "grouped", "randomized"}:
        raise RegulatorCalibrationBatchError("order_strategy must be alternating, grouped, or randomized")
    random_seed = None
    if order_strategy == "randomized":
        seed_value = config.get("random_seed")
        try:
            random_seed = int(seed_value) if seed_value is not None and str(seed_value).strip() != "" else random.randrange(1, 2**31)
        except (TypeError, ValueError):
            raise RegulatorCalibrationBatchError("random_seed must be an integer")

    include_baseline_before = _bool_from_config(config, "baseline_before", True)
    include_baseline_after = _bool_from_config(config, "baseline_after", True)
    scheduled: list[dict[str, Any]] = []
    if include_baseline_before:
        scheduled.append({"role": "baseline_before", "profile_id": baseline_profile_id, "repeat_index": 0})
    scheduled.extend(_batch_schedule_candidates(candidate_profile_ids, repeat_count, order_strategy, random_seed))
    if include_baseline_after:
        scheduled.append({"role": "baseline_after", "profile_id": baseline_profile_id, "repeat_index": 0})
    if len(scheduled) > 50:
        raise RegulatorCalibrationBatchError("batch schedule must contain no more than 50 runs")

    now = (now_fn or _now_utc)()
    suffix = (id_factory or _short_id)()
    session_id = _string_or_empty(config.get("session_id")) or f"session_{_timestamp(now)}_{suffix}"
    output_root = Path(output_root)
    session_dir = output_root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    conditions = {
        "printer_head_id": _string_or_empty(config.get("printer_head_id")),
        "printer_head_type": _string_or_empty(config.get("printer_head_type")),
        "reagent_id": _string_or_empty(config.get("reagent_id")),
        **trace_case.conditions(),
    }

    runs: list[dict[str, Any]] = []
    for order_index, item in enumerate(scheduled, start=1):
        run_suffix = (id_factory or _short_id)()
        run_id = f"regopt_{_timestamp(now)}_{run_suffix}"
        run_dir_name = f"run_{_timestamp(now)}_{run_suffix}"
        run_dir = session_dir / run_dir_name
        runs.append(
            {
                "order_index": order_index,
                "role": item["role"],
                "profile_id": item["profile_id"],
                "mode": mode,
                "repeat_index": int(item["repeat_index"]),
                "trace_case_id": trace_case.test_id,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "run_dir_name": run_dir_name,
                "run_meta_path": str(run_dir / "run_meta.json"),
                "status": "pending",
                "message": "",
            }
        )

    manifest = {
        "schema_version": 1,
        "session_id": session_id,
        "created_at_utc": _iso_utc(now),
        "operator": _string_or_empty(config.get("operator")),
        "mode": mode,
        "serial_handoff_mode": serial_handoff_mode,
        "trace_case_id": trace_case.test_id,
        "conditions": conditions,
        "baseline_profile_id": baseline_profile_id,
        "candidate_profile_ids": list(candidate_profile_ids),
        "repeat_count": repeat_count,
        "order_strategy": order_strategy,
        "random_seed": random_seed,
        "runs": copy.deepcopy(runs),
        "analysis": {
            "output_dir": None,
            "candidate_ranking_json": None,
            "candidate_ranking_csv": None,
            "all_pulses_csv": None,
            "error_message": "",
        },
        "outcome": {
            "status": "pending",
            "completed_run_count": 0,
            "total_run_count": len(runs),
            "error_message": "",
        },
    }
    prepared = PreparedRegulatorCalibrationBatch(
        session_id=session_id,
        session_dir=session_dir,
        manifest_path=session_dir / "session_manifest.json",
        mode=mode,
        serial_handoff_mode=serial_handoff_mode,
        trace_case=trace_case,
        baseline_profile_id=baseline_profile_id,
        candidate_profile_ids=list(candidate_profile_ids),
        repeat_count=repeat_count,
        order_strategy=order_strategy,
        random_seed=random_seed,
        conditions=conditions,
        runs=runs,
        manifest=manifest,
        output_root=output_root,
    )
    write_batch_manifest(prepared)
    return prepared


def write_batch_manifest(
    prepared_batch: PreparedRegulatorCalibrationBatch,
    *,
    runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    status: str | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    if status is not None and status not in {"pending", "running", "completed", "failed", "canceled", "analysis_failed"}:
        raise RegulatorCalibrationBatchError(f"invalid batch status {status}")
    manifest = copy.deepcopy(prepared_batch.manifest)
    if runs is not None:
        manifest["runs"] = copy.deepcopy(runs)
    if analysis is not None:
        merged = dict(manifest.get("analysis", {}))
        merged.update(copy.deepcopy(analysis))
        manifest["analysis"] = merged
    if status is not None:
        completed = sum(1 for run in manifest.get("runs", []) if run.get("status") == "completed")
        manifest["outcome"] = {
            "status": status,
            "completed_run_count": completed,
            "total_run_count": len(manifest.get("runs", [])),
            "error_message": str(error_message or ""),
        }
    write_json_atomic(prepared_batch.manifest_path, manifest)
    prepared_batch.manifest = copy.deepcopy(manifest)
    prepared_batch.runs = copy.deepcopy(manifest.get("runs", []))
    return manifest


def batch_run_configs(prepared_batch: PreparedRegulatorCalibrationBatch) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    base = {
        "mode": prepared_batch.mode,
        "serial_handoff_mode": prepared_batch.serial_handoff_mode,
        "trace_case_id": prepared_batch.trace_case.test_id,
        "operator": prepared_batch.manifest.get("operator", ""),
        "printer_head_id": prepared_batch.conditions.get("printer_head_id", ""),
        "printer_head_type": prepared_batch.conditions.get("printer_head_type", ""),
        "reagent_id": prepared_batch.conditions.get("reagent_id", ""),
        "calibrated_head_confirmed": True,
        "session_id": prepared_batch.session_id,
        "output_root": str(prepared_batch.output_root),
        "_batch_run": True,
    }
    if prepared_batch.trace_case.custom:
        channel = prepared_batch.trace_case.channel_label
        pulse_us = (
            prepared_batch.trace_case.print_pulse_width_us
            if channel == "print"
            else prepared_batch.trace_case.refuel_pulse_width_us
        )
        base.update(
            {
                "trace_channel": channel,
                "trace_pressure_mpsi": prepared_batch.trace_case.pressure_mpsi,
                "trace_pulse_us": pulse_us,
                "trace_pulse_count": prepared_batch.trace_case.pulse_count,
                "trace_frequency_hz": prepared_batch.trace_case.frequency_hz,
            }
        )
    for run in prepared_batch.runs:
        config = dict(base)
        config.update(
            {
                "profile_id": run["profile_id"],
                "run_id": run["run_id"],
                "run_dir_name": run["run_dir_name"],
                "batch_order_index": run["order_index"],
                "batch_role": run["role"],
                "batch_repeat_index": run["repeat_index"],
            }
        )
        configs.append(config)
    return configs


def relative_to_run_dir(prepared: PreparedRegulatorCalibrationRun, path: str | Path | None) -> str | None:
    if path is None:
        return None
    path = Path(path)
    try:
        return str(path.relative_to(prepared.run_dir))
    except ValueError:
        return str(path)


def collect_trace_files(prepared: PreparedRegulatorCalibrationRun) -> list[str]:
    stem = prepared.raw_selftest_path.stem
    traces = sorted(prepared.run_dir.glob(f"{stem}_trace_*.json"))
    return [relative_to_run_dir(prepared, path) or str(path) for path in traces]


def write_run_metadata(
    prepared: PreparedRegulatorCalibrationRun,
    *,
    status: str,
    restored_previous_profile: bool,
    error_message: str = "",
    trace_files: list[str] | None = None,
    analysis_json: str | Path | None = None,
    summary_csv: str | Path | None = None,
    plots: list[str | Path] | None = None,
) -> dict[str, Any]:
    if status not in {"completed", "canceled", "failed", "restore_failed"}:
        raise RegulatorCalibrationError(f"invalid run status {status}")
    metadata = copy.deepcopy(prepared.metadata)
    outputs = metadata.setdefault("outputs", {})
    outputs["trace_files"] = list(trace_files if trace_files is not None else collect_trace_files(prepared))
    outputs["analysis_json"] = relative_to_run_dir(prepared, analysis_json)
    outputs["summary_csv"] = relative_to_run_dir(prepared, summary_csv)
    outputs["plots"] = [relative_to_run_dir(prepared, path) for path in list(plots or [])]
    metadata["outcome"] = {
        "status": status,
        "restored_previous_profile": bool(restored_previous_profile),
        "error_message": str(error_message or ""),
    }
    write_json_atomic(prepared.run_dir / "run_meta.json", metadata)
    prepared.metadata = copy.deepcopy(metadata)
    return metadata


def build_selftest_command(
    prepared: PreparedRegulatorCalibrationRun,
    *,
    port: str,
    baud: int = 115200,
    run_selftest_path: str | Path,
    python_executable: str | None = None,
    timeout_ms: int | None = None,
    skip_goodbye: bool = False,
) -> tuple[str, ...]:
    command = [
        python_executable or sys.executable,
        str(run_selftest_path),
        "--port",
        str(port),
        "--baud",
        str(int(baud)),
        "--profile",
        "FULL",
        "--pressure-trace",
        "--progress-jsonl",
        "--out",
        str(prepared.raw_selftest_path),
    ]
    if prepared.trace_case.custom:
        channel = prepared.trace_case.channel_label
        pulse_us = (
            prepared.trace_case.print_pulse_width_us
            if channel == "print"
            else prepared.trace_case.refuel_pulse_width_us
        )
        command.extend(
            [
                "--pressure-trace-custom",
                "--trace-channel",
                channel,
                "--trace-pressure-psi",
                f"{(prepared.trace_case.pressure_mpsi or 0) / 1000.0:g}",
                "--trace-pulse-us",
                str(int(pulse_us or 0)),
                "--trace-pulse-count",
                str(int(prepared.trace_case.pulse_count)),
                "--trace-frequency-hz",
                str(int(prepared.trace_case.frequency_hz)),
            ]
        )
    else:
        command.extend(["--pressure-trace-test", str(prepared.trace_case.test_id)])
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(int(timeout_ms))])
    if skip_goodbye:
        command.append("--skip-goodbye")
    return tuple(command)


class RegulatorTraceProcessWorker(QtCore.QThread):
    stage = QtCore.Signal(str)
    output = QtCore.Signal(str)
    run_finished = QtCore.Signal(bool, str, object)

    SELFTEST_EVENT_PREFIX = "SELFTEST_EVENT "

    def __init__(
        self,
        prepared: PreparedRegulatorCalibrationRun,
        *,
        port: str,
        baud: int = 115200,
        repo_root: str | Path,
        run_selftest_path: str | Path,
        timeout_ms: int | None = None,
        skip_goodbye: bool = False,
        invoker: Callable[[tuple[str, ...], Path], int] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.prepared = prepared
        self.port = str(port)
        self.baud = int(baud)
        self.repo_root = Path(repo_root)
        self.run_selftest_path = Path(run_selftest_path)
        self.timeout_ms = timeout_ms
        self.skip_goodbye = bool(skip_goodbye)
        self.invoker = invoker
        self._cancel_requested = False
        self._process: subprocess.Popen | None = None

    def cancel(self):
        self._cancel_requested = True
        if self._process is not None:
            self.output.emit("Cancel requested; waiting for the active pressure-trace run to exit before restore.")

    def run(self):
        if self._cancel_requested:
            self.run_finished.emit(
                False,
                "Regulator calibration canceled before trace capture.",
                self._payload(returncode=None),
            )
            return

        command = build_selftest_command(
            self.prepared,
            port=self.port,
            baud=self.baud,
            run_selftest_path=self.run_selftest_path,
            timeout_ms=self.timeout_ms,
            skip_goodbye=self.skip_goodbye,
        )
        self.stage.emit("Running pressure trace")
        self.output.emit(" ".join(command))
        try:
            if self.invoker is not None:
                returncode = int(self.invoker(command, self.repo_root))
            else:
                returncode = self._run_subprocess(command)
        except Exception as exc:
            self.stage.emit("Pressure trace failed")
            self.run_finished.emit(False, f"Pressure trace failed: {exc}", self._payload(returncode=3))
            return

        payload = self._payload(returncode=returncode)
        if self._cancel_requested:
            self.stage.emit("Pressure trace canceled")
            self.run_finished.emit(False, "Regulator calibration canceled after trace capture.", payload)
            return
        ok = returncode == 0
        self.stage.emit("Pressure trace finished" if ok else "Pressure trace failed")
        self.run_finished.emit(ok, "Pressure trace completed." if ok else "Pressure trace failed.", payload)

    def _run_subprocess(self, command: tuple[str, ...]) -> int:
        self._process = subprocess.Popen(
            [str(item) for item in command],
            cwd=str(self.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            if self._process.stdout is not None:
                for line in self._process.stdout:
                    self._handle_output_line(line.rstrip())
            return int(self._process.wait())
        finally:
            self._process = None

    def _handle_output_line(self, line: str) -> None:
        text = str(line)
        if text.startswith(self.SELFTEST_EVENT_PREFIX):
            self.output.emit(text)
            return
        self.output.emit(text)

    def _payload(self, *, returncode: int | None) -> dict[str, Any]:
        return {
            "returncode": returncode,
            "run_dir": str(self.prepared.run_dir),
            "raw_selftest_path": str(self.prepared.raw_selftest_path),
            "trace_files": collect_trace_files(self.prepared),
            "trace_case_id": self.prepared.trace_case.test_id,
            "trace_case_name": self.prepared.trace_case.name,
        }
