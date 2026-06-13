from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6 import QtCore


@dataclass(frozen=True)
class PlateReaderAnalysisConfig:
    experiment_dir: str | Path
    plate_reader_file: str | Path
    key_file: str | Path | None = None
    output_dir: str | Path | None = None
    endpoint_last_n: int = 3


@dataclass(frozen=True)
class PlateReaderAnalysisCommand:
    step: str
    command: list[str]
    cwd: Path


@dataclass(frozen=True)
class PlateReaderAnalysisPreviewResult:
    ok: bool
    message: str
    errors: list[str]
    warnings: list[str]
    summary: dict[str, object]
    paths: dict[str, str]

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": bool(self.ok),
            "message": self.message,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "summary": dict(self.summary),
            "paths": dict(self.paths),
        }


CommandOutputCallback = Callable[[str], None]
CommandRunner = Callable[[PlateReaderAnalysisCommand, CommandOutputCallback], int]


def coerce_plate_reader_analysis_config(config: PlateReaderAnalysisConfig | dict) -> PlateReaderAnalysisConfig:
    if isinstance(config, PlateReaderAnalysisConfig):
        return config
    return PlateReaderAnalysisConfig(**dict(config))


def resolve_plate_reader_analysis_paths(config: PlateReaderAnalysisConfig | dict) -> dict[str, Path]:
    resolved = coerce_plate_reader_analysis_config(config)
    experiment_dir = Path(resolved.experiment_dir).expanduser()
    plate_reader_file = Path(resolved.plate_reader_file).expanduser()
    key_file = Path(resolved.key_file).expanduser() if resolved.key_file is not None else experiment_dir / "concentration_key.csv"
    output_dir = Path(resolved.output_dir).expanduser() if resolved.output_dir is not None else experiment_dir / "plate_reader_analysis"
    return {
        "experiment_dir": experiment_dir,
        "plate_reader_file": plate_reader_file,
        "key_file": key_file,
        "output_dir": output_dir,
    }


def validate_plate_reader_analysis_paths(paths: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    if not paths["experiment_dir"].exists() or not paths["experiment_dir"].is_dir():
        errors.append(f"Experiment directory does not exist or is not a directory: {paths['experiment_dir']}")
    if not paths["plate_reader_file"].exists() or not paths["plate_reader_file"].is_file():
        errors.append(f"Plate-reader file does not exist or is not a file: {paths['plate_reader_file']}")
    if not paths["key_file"].exists() or not paths["key_file"].is_file():
        errors.append(f"Concentration key does not exist or is not a file: {paths['key_file']}")
    return errors


def same_file(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError:
        return False


def next_raw_plate_reader_destination(source: Path, raw_dir: Path) -> Path:
    candidate = raw_dir / source.name
    if not candidate.exists() or same_file(source, candidate):
        return candidate
    for suffix in range(2, 1000):
        candidate = raw_dir / f"{source.stem}_{suffix}{source.suffix}"
        if not candidate.exists() or same_file(source, candidate):
            return candidate
    raise RuntimeError(f"Could not choose a unique raw plate-reader filename for {source.name}")


def plate_reader_analysis_output_paths(paths: dict[str, Path]) -> dict[str, Path]:
    copied_plate = next_raw_plate_reader_destination(
        paths["plate_reader_file"],
        paths["experiment_dir"] / "raw_plate_reader",
    )
    return {
        "copied_plate_reader_file": copied_plate,
        "merged_csv": paths["experiment_dir"] / f"{copied_plate.stem}_merged_tidy.csv",
        "manifest_json": paths["output_dir"] / "analysis_manifest.json",
        "report_html": paths["output_dir"] / "analysis_report.html",
    }


def _format_preview_values(values: list[str], *, limit: int = 12) -> str:
    if not values:
        return ""
    shown = values[:limit]
    suffix = f", ... ({len(values) - limit} more)" if len(values) > limit else ""
    return ", ".join(shown) + suffix


def build_plate_reader_analysis_preview(config: PlateReaderAnalysisConfig | dict) -> PlateReaderAnalysisPreviewResult:
    paths = resolve_plate_reader_analysis_paths(config)
    output_paths: dict[str, Path] = {}
    errors = validate_plate_reader_analysis_paths(paths)
    warnings: list[str] = []

    if not errors:
        output_paths = plate_reader_analysis_output_paths(paths)
        if output_paths["merged_csv"].exists():
            warnings.append(f"Merged tidy CSV already exists and may be overwritten: {output_paths['merged_csv']}")
        if paths["output_dir"].exists():
            warnings.append(f"Analysis output directory already exists and may be updated: {paths['output_dir']}")

    all_paths = {**paths, **output_paths}
    path_payload = {key: str(value) for key, value in all_paths.items()}

    if errors:
        return PlateReaderAnalysisPreviewResult(
            ok=False,
            message="Validation preview failed.",
            errors=errors,
            warnings=warnings,
            summary={},
            paths=path_payload,
        )

    try:
        from tools.data_analysis import associate_plate_reader_and_key as association
        from tools.data_analysis import plate_reader_analysis as analysis

        merged_df, filter_result, merge_summary = association.build_merged_tidy_data(
            paths["plate_reader_file"],
            paths["key_file"],
        )
        prepared_df, condition_columns = analysis.prepare_analysis_dataframe(merged_df)
    except Exception as exc:
        return PlateReaderAnalysisPreviewResult(
            ok=False,
            message="Validation preview failed.",
            errors=[f"Could not parse and associate plate-reader data: {exc}"],
            warnings=warnings,
            summary={},
            paths=path_payload,
        )

    keyed_measured_wells = list(merge_summary.keyed_wells)
    unkeyed_measured_wells = list(merge_summary.unkeyed_measured_wells)
    missing_key_wells = list(merge_summary.missing_key_wells)
    key_wells = sorted(set(keyed_measured_wells) | set(missing_key_wells))
    measured_wells = sorted(merged_df["well"].dropna().astype(str).unique())
    fluorophores = sorted(merged_df["fluorophore"].dropna().astype(str).unique())
    time_seconds = merged_df["time_seconds"].dropna()
    time_minutes = merged_df["time_minutes"].dropna()
    has_timecourse = bool(analysis.has_timecourse_data(merged_df))
    composition_count = int(
        prepared_df.loc[prepared_df["condition_id"] != "unkeyed", "condition_id"].dropna().nunique()
    )

    if not keyed_measured_wells:
        errors.append("No measured wells matched the concentration key.")
    if unkeyed_measured_wells:
        warnings.append(
            f"{len(unkeyed_measured_wells)} measured well(s) are not present in the concentration key: "
            f"{_format_preview_values(unkeyed_measured_wells)}"
        )
    if missing_key_wells:
        warnings.append(
            f"{len(missing_key_wells)} keyed well(s) have no measured RFU data: "
            f"{_format_preview_values(missing_key_wells)}"
        )
    if filter_result.dropped_timepoints:
        warnings.append(f"{len(filter_result.dropped_timepoints)} incomplete timepoint(s) will be dropped before analysis.")
    if not has_timecourse:
        warnings.append("Endpoint-only data detected; timecourse plots will be skipped.")

    summary = {
        "row_count": int(len(merged_df)),
        "measured_well_count": int(len(measured_wells)),
        "key_well_count": int(len(key_wells)),
        "keyed_measured_well_count": int(len(keyed_measured_wells)),
        "unkeyed_measured_well_count": int(len(unkeyed_measured_wells)),
        "missing_key_well_count": int(len(missing_key_wells)),
        "measured_wells": measured_wells,
        "keyed_measured_wells": keyed_measured_wells,
        "unkeyed_measured_wells": unkeyed_measured_wells,
        "missing_key_wells": missing_key_wells,
        "fluorophores": fluorophores,
        "fluorophore_count": int(len(fluorophores)),
        "timepoint_count": int(time_seconds.nunique()),
        "time_seconds_min": float(time_seconds.min()) if not time_seconds.empty else None,
        "time_seconds_max": float(time_seconds.max()) if not time_seconds.empty else None,
        "time_minutes_min": float(time_minutes.min()) if not time_minutes.empty else None,
        "time_minutes_max": float(time_minutes.max()) if not time_minutes.empty else None,
        "has_timecourse_data": has_timecourse,
        "condition_columns": list(condition_columns),
        "composition_count": composition_count,
        "dropped_timepoint_count": int(len(filter_result.dropped_timepoints)),
    }
    ok = not errors
    return PlateReaderAnalysisPreviewResult(
        ok=ok,
        message="Validation preview passed." if ok else "Validation preview failed.",
        errors=errors,
        warnings=warnings,
        summary=summary,
        paths=path_payload,
    )


class PlateReaderAnalysisPreviewWorker(QtCore.QThread):
    stage = QtCore.Signal(str)
    run_finished = QtCore.Signal(bool, str, object)

    def __init__(self, config: PlateReaderAnalysisConfig | dict, parent=None):
        super().__init__(parent)
        self.config = coerce_plate_reader_analysis_config(config)

    def run(self) -> None:
        self.stage.emit("Validating plate-reader inputs")
        result = build_plate_reader_analysis_preview(self.config)
        self.stage.emit("Preview ready" if result.ok else "Preview failed")
        self.run_finished.emit(bool(result.ok), result.message, result)


class PlateReaderAnalysisWorker(QtCore.QThread):
    stage = QtCore.Signal(str)
    output = QtCore.Signal(str)
    run_finished = QtCore.Signal(bool, str, object)

    ANALYSIS_PROGRESS_PREFIX = "[analysis] "

    def __init__(
        self,
        config: PlateReaderAnalysisConfig | dict,
        *,
        repo_root: str | Path | None = None,
        command_runner: CommandRunner | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = coerce_plate_reader_analysis_config(config)
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
        self._command_runner = command_runner
        self._active_process: subprocess.Popen | None = None
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        proc = self._active_process
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception as exc:
            self.output.emit(f"Failed to terminate plate-reader analysis process: {exc}")

    def run(self) -> None:
        try:
            payload = self._run_analysis()
        except Exception as exc:
            self.stage.emit("Failed")
            self.run_finished.emit(False, f"Plate reader analysis failed: {exc}", {})
            return

        ok = bool(payload.pop("_ok"))
        message = str(payload.pop("_message"))
        self.stage.emit("Finished" if ok else "Failed")
        self.run_finished.emit(ok, message, payload)

    def _run_analysis(self) -> dict[str, object]:
        self.stage.emit("Preparing plate reader analysis")
        paths = self._prepare_paths()
        self.output.emit(f"Experiment directory: {paths['experiment_dir']}")
        self.output.emit(f"Plate-reader file: {paths['plate_reader_file']}")
        self.output.emit(f"Concentration key: {paths['key_file']}")

        copied_plate = self._copy_plate_reader_file(
            paths["plate_reader_file"],
            paths["experiment_dir"] / "raw_plate_reader",
        )
        paths["copied_plate_reader_file"] = copied_plate
        paths["merged_csv"] = paths["experiment_dir"] / f"{copied_plate.stem}_merged_tidy.csv"
        paths["manifest_json"] = paths["output_dir"] / "analysis_manifest.json"
        paths["report_html"] = paths["output_dir"] / "analysis_report.html"

        payload = self._payload(paths)
        returncodes: dict[str, int | None] = {"associate": None, "analyze": None}
        payload["command_returncodes"] = returncodes

        associate_command = self._association_command(paths)
        self.stage.emit("Associating plate reader data with concentration key")
        returncodes["associate"] = self._run_command(associate_command)
        if returncodes["associate"] != 0:
            payload["_ok"] = False
            payload["_message"] = f"Plate reader association failed with return code {returncodes['associate']}."
            return payload

        analysis_command = self._analysis_command(paths)
        self.stage.emit("Running plate reader analysis")
        returncodes["analyze"] = self._run_command(analysis_command)
        if returncodes["analyze"] != 0:
            payload["_ok"] = False
            payload["_message"] = f"Plate reader analysis failed with return code {returncodes['analyze']}."
            return payload

        missing = [
            label
            for label, path in [
                ("analysis manifest", paths["manifest_json"]),
                ("analysis report", paths["report_html"]),
            ]
            if not path.exists()
        ]
        if missing:
            payload["_ok"] = False
            payload["_message"] = "Plate reader analysis finished but did not create " + ", ".join(missing) + "."
            return payload

        payload["_ok"] = True
        payload["_message"] = f"Plate reader analysis completed: {paths['report_html']}"
        return payload

    def _prepare_paths(self) -> dict[str, Path]:
        paths = resolve_plate_reader_analysis_paths(self.config)
        errors = validate_plate_reader_analysis_paths(paths)
        if errors:
            raise ValueError(errors[0])
        return paths

    def _copy_plate_reader_file(self, source: Path, raw_dir: Path) -> Path:
        raw_dir.mkdir(parents=True, exist_ok=True)
        destination = self._next_raw_destination(source, raw_dir)
        if self._same_file(source, destination):
            self.output.emit(f"Using existing raw plate-reader file: {destination}")
            return destination
        shutil.copy2(source, destination)
        self.output.emit(f"Copied raw plate-reader file to: {destination}")
        return destination

    def _next_raw_destination(self, source: Path, raw_dir: Path) -> Path:
        return next_raw_plate_reader_destination(source, raw_dir)

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        return same_file(left, right)

    def _association_command(self, paths: dict[str, Path]) -> PlateReaderAnalysisCommand:
        command = [
            sys.executable,
            str(Path("tools") / "data_analysis" / "associate_plate_reader_and_key.py"),
            str(paths["experiment_dir"]),
            "--plate-file",
            str(paths["copied_plate_reader_file"]),
            "--key-file",
            str(paths["key_file"]),
            "--output",
            str(paths["merged_csv"]),
        ]
        return PlateReaderAnalysisCommand(step="associate", command=command, cwd=self.repo_root)

    def _analysis_command(self, paths: dict[str, Path]) -> PlateReaderAnalysisCommand:
        command = [
            sys.executable,
            str(Path("tools") / "data_analysis" / "analyze_plate_reader.py"),
            "--merged-csv",
            str(paths["merged_csv"]),
            "--output-dir",
            str(paths["output_dir"]),
            "--endpoint-last-n",
            str(int(self.config.endpoint_last_n)),
        ]
        return PlateReaderAnalysisCommand(step="analyze", command=command, cwd=self.repo_root)

    def _run_command(self, command: PlateReaderAnalysisCommand) -> int:
        self.output.emit(" ".join(command.command))
        if self._command_runner is not None:
            return int(self._command_runner(command, self._handle_output_line))
        return self._run_subprocess(command)

    def _run_subprocess(self, command: PlateReaderAnalysisCommand) -> int:
        if self._cancel_requested:
            return 130
        try:
            proc = subprocess.Popen(
                command.command,
                cwd=str(command.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self.output.emit(f"Failed to launch {command.step} command: {exc}")
            return 3

        self._active_process = proc
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    self._handle_output_line(line.rstrip())
            return int(proc.wait())
        finally:
            self._active_process = None

    def _handle_output_line(self, line: str) -> None:
        text = str(line)
        self.output.emit(text)
        if text.startswith(self.ANALYSIS_PROGRESS_PREFIX):
            self.stage.emit(text[len(self.ANALYSIS_PROGRESS_PREFIX) :])

    @staticmethod
    def _payload(paths: dict[str, Path]) -> dict[str, object]:
        return {
            "experiment_dir": str(paths["experiment_dir"]),
            "plate_reader_file": str(paths["plate_reader_file"]),
            "copied_plate_reader_file": str(paths["copied_plate_reader_file"]),
            "key_file": str(paths["key_file"]),
            "merged_csv": str(paths["merged_csv"]),
            "output_dir": str(paths["output_dir"]),
            "manifest_json": str(paths["manifest_json"]),
            "report_html": str(paths["report_html"]),
        }
