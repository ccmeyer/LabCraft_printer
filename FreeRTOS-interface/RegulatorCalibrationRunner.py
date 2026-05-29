from __future__ import annotations

import copy
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

    def conditions(self) -> dict[str, Any]:
        return {
            "print_pressure_psi": self.print_pressure_psi,
            "print_pulse_width_us": self.print_pulse_width_us,
            "refuel_pressure_psi": self.refuel_pressure_psi,
            "refuel_pulse_width_us": self.refuel_pulse_width_us,
            "frequency_hz": self.frequency_hz,
            "pulse_count": self.pulse_count,
            "channel": self.channel_label,
        }


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
    candidate_profile: dict[str, Any]
    baseline_profile: dict[str, Any]
    operator: str
    conditions: dict[str, Any]
    metadata: dict[str, Any]


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


def _trace_case_from_config(config: dict[str, Any]) -> RegulatorTraceCase:
    try:
        trace_case_id = int(config.get("trace_case_id"))
    except (TypeError, ValueError):
        raise RegulatorCalibrationError("trace_case_id must be one of the supported pressure trace cases")
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

    trace_case = _trace_case_from_config(config)
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
    run_dir = Path(output_root) / session_id / f"run_{_timestamp(now)}_{suffix}"
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
        candidate_profile=copy.deepcopy(candidate_profile),
        baseline_profile=baseline_profile,
        operator=metadata["operator"],
        conditions=conditions,
        metadata=metadata,
    )


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
        "--pressure-trace-test",
        str(prepared.trace_case.test_id),
        "--progress-jsonl",
        "--out",
        str(prepared.raw_selftest_path),
    ]
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(int(timeout_ms))])
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
