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


CommandOutputCallback = Callable[[str], None]
CommandRunner = Callable[[PlateReaderAnalysisCommand, CommandOutputCallback], int]


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
        if isinstance(config, PlateReaderAnalysisConfig):
            self.config = config
        else:
            self.config = PlateReaderAnalysisConfig(**dict(config))
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
        experiment_dir = Path(self.config.experiment_dir).expanduser()
        plate_reader_file = Path(self.config.plate_reader_file).expanduser()
        key_file = Path(self.config.key_file).expanduser() if self.config.key_file is not None else experiment_dir / "concentration_key.csv"
        output_dir = Path(self.config.output_dir).expanduser() if self.config.output_dir is not None else experiment_dir / "plate_reader_analysis"

        if not experiment_dir.exists() or not experiment_dir.is_dir():
            raise ValueError(f"Experiment directory does not exist or is not a directory: {experiment_dir}")
        if not plate_reader_file.exists() or not plate_reader_file.is_file():
            raise ValueError(f"Plate-reader file does not exist or is not a file: {plate_reader_file}")
        if not key_file.exists() or not key_file.is_file():
            raise ValueError(f"Concentration key does not exist or is not a file: {key_file}")

        return {
            "experiment_dir": experiment_dir,
            "plate_reader_file": plate_reader_file,
            "key_file": key_file,
            "output_dir": output_dir,
        }

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
        candidate = raw_dir / source.name
        if not candidate.exists() or self._same_file(source, candidate):
            return candidate
        for suffix in range(2, 1000):
            candidate = raw_dir / f"{source.stem}_{suffix}{source.suffix}"
            if not candidate.exists() or self._same_file(source, candidate):
                return candidate
        raise RuntimeError(f"Could not choose a unique raw plate-reader filename for {source.name}")

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        try:
            return left.exists() and right.exists() and left.samefile(right)
        except OSError:
            return False

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
