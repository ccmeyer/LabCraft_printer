from __future__ import annotations

import csv
from pathlib import Path

import pytest

from PlateReaderAnalysisRunner import (
    PlateReaderAnalysisConfig,
    PlateReaderAnalysisPreviewResult,
    PlateReaderAnalysisPreviewWorker,
    PlateReaderAnalysisWorker,
    build_plate_reader_analysis_preview,
)


def _make_experiment(tmp_path: Path) -> tuple[Path, Path, Path]:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    key_file = experiment_dir / "concentration_key.csv"
    key_file.write_text("Well ID,DNA_mM\nA1,1\n", encoding="utf-8")
    plate_file = tmp_path / "plate_reader.txt"
    plate_file.write_text("raw plate reader export\n", encoding="utf-8")
    return experiment_dir, key_file, plate_file


def _write_preview_plate_export(path: Path) -> None:
    rows = [
        ["##BLOCKS= 1"],
        ["Plate:", "Plate1", "1.3", "502 540", "Manual"],
        ["Time", "Temperature(C)", "A1", "A2", "A3"],
        ["00:00:00", "37", "10", "20", "30"],
        ["00:01:00", "37", "11", "21", "31"],
        ["00:02:00", "37", "12", "22", "32"],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)


def _write_endpoint_plate_export(path: Path) -> None:
    metadata_row = [""] * 33
    for index, value in {
        0: "Plate:",
        1: "Plate#1",
        3: "PlateFormat",
        4: "Endpoint",
        5: "Fluorescence",
        16: "509",
        19: "384",
        20: "488",
    }.items():
        metadata_row[index] = value
    rows = [
        ["##BLOCKS= 1"],
        metadata_row,
        ["", "Temperature(C)", "1", "2"],
        ["", "23.5", "100", "200"],
        ["", "", "300", "400"],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)


def _write_preview_key(path: Path, *, zero_overlap: bool = False) -> None:
    lines = (
        ["Well ID,DNA_mM", "B1,1.0", "B2,2.0"]
        if zero_overlap
        else ["Well ID,DNA_mM", "A1,1.0", "A2,2.0", "A4,4.0"]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_worker(worker: PlateReaderAnalysisWorker) -> tuple[tuple[bool, str, object], list[str], list[str]]:
    stages: list[str] = []
    outputs: list[str] = []
    finished: list[tuple[bool, str, object]] = []

    worker.stage.connect(stages.append)
    worker.output.connect(outputs.append)
    worker.run_finished.connect(lambda ok, message, payload: finished.append((ok, message, payload)))

    worker.run()

    assert len(finished) == 1
    return finished[0], stages, outputs


def _run_preview_worker(worker: PlateReaderAnalysisPreviewWorker) -> tuple[tuple[bool, str, object], list[str]]:
    stages: list[str] = []
    finished: list[tuple[bool, str, object]] = []
    worker.stage.connect(stages.append)
    worker.run_finished.connect(lambda ok, message, payload: finished.append((ok, message, payload)))

    worker.run()

    assert len(finished) == 1
    return finished[0], stages


def _option_value(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def _successful_fake_runner(invocations: list, *, emit_progress: bool = True):
    def _run(command, emit):
        invocations.append(command)
        emit(f"{command.step} command output")
        if command.step == "associate":
            merged_csv = Path(_option_value(command.command, "--output"))
            merged_csv.write_text("well,fluorophore,time_seconds,time_minutes,rfu\n", encoding="utf-8")
            return 0
        if command.step == "analyze":
            output_dir = Path(_option_value(command.command, "--output-dir"))
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "analysis_manifest.json").write_text("{}", encoding="utf-8")
            (output_dir / "analysis_report.html").write_text("<html></html>", encoding="utf-8")
            if emit_progress:
                emit("[analysis] Writing endpoint summaries")
            return 0
        raise AssertionError(f"Unexpected command step: {command.step}")

    return _run


def test_preview_builder_summarizes_timecourse_inputs_without_writing_files(tmp_path):
    experiment_dir = tmp_path / "experiment"
    plate_file = tmp_path / "reader.txt"
    key_file = experiment_dir / "concentration_key.csv"
    experiment_dir.mkdir()
    _write_preview_plate_export(plate_file)
    _write_preview_key(key_file)

    result = build_plate_reader_analysis_preview(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    )

    assert isinstance(result, PlateReaderAnalysisPreviewResult)
    assert result.ok is True
    assert result.errors == []
    assert result.summary["measured_well_count"] == 3
    assert result.summary["key_well_count"] == 3
    assert result.summary["keyed_measured_well_count"] == 2
    assert result.summary["unkeyed_measured_well_count"] == 1
    assert result.summary["missing_key_well_count"] == 1
    assert result.summary["fluorophores"] == ["502_540"]
    assert result.summary["timepoint_count"] == 3
    assert result.summary["has_timecourse_data"] is True
    assert result.summary["condition_columns"] == ["DNA_mM"]
    assert result.summary["composition_count"] == 2
    assert Path(result.paths["copied_plate_reader_file"]) == experiment_dir / "raw_plate_reader" / plate_file.name
    assert Path(result.paths["merged_csv"]) == experiment_dir / "reader_merged_tidy.csv"
    assert Path(result.paths["output_dir"]) == experiment_dir / "plate_reader_analysis"
    assert not (experiment_dir / "raw_plate_reader").exists()
    assert not Path(result.paths["merged_csv"]).exists()
    assert any("measured well(s) are not present" in warning for warning in result.warnings)
    assert any("keyed well(s) have no measured RFU data" in warning for warning in result.warnings)


def test_preview_worker_emits_stage_and_result(tmp_path):
    experiment_dir = tmp_path / "experiment"
    plate_file = tmp_path / "reader.txt"
    key_file = experiment_dir / "concentration_key.csv"
    experiment_dir.mkdir()
    _write_preview_plate_export(plate_file)
    _write_preview_key(key_file)
    worker = PlateReaderAnalysisPreviewWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    )

    (ok, message, payload), stages = _run_preview_worker(worker)

    assert ok is True
    assert "passed" in message
    assert isinstance(payload, PlateReaderAnalysisPreviewResult)
    assert payload.summary["keyed_measured_well_count"] == 2
    assert stages == ["Validating plate-reader inputs", "Preview ready"]


def test_preview_endpoint_only_data_sets_timecourse_warning(tmp_path):
    experiment_dir = tmp_path / "experiment"
    plate_file = tmp_path / "endpoint.txt"
    key_file = experiment_dir / "concentration_key.csv"
    experiment_dir.mkdir()
    _write_endpoint_plate_export(plate_file)
    key_file.write_text("Well ID,DNA_mM\nA1,1.0\nA2,2.0\nB1,3.0\nB2,4.0\n", encoding="utf-8")

    result = build_plate_reader_analysis_preview(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    )

    assert result.ok is True
    assert result.summary["has_timecourse_data"] is False
    assert result.summary["timepoint_count"] == 1
    assert any("Endpoint-only data detected" in warning for warning in result.warnings)


def test_preview_missing_inputs_are_blocking_and_do_not_write_files(tmp_path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    result = build_plate_reader_analysis_preview(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=tmp_path / "missing.txt")
    )

    assert result.ok is False
    assert any("Plate-reader file" in error for error in result.errors)
    assert any("Concentration key" in error for error in result.errors)
    assert not (experiment_dir / "raw_plate_reader").exists()


def test_preview_zero_keyed_measured_wells_is_blocking(tmp_path):
    experiment_dir = tmp_path / "experiment"
    plate_file = tmp_path / "reader.txt"
    key_file = experiment_dir / "concentration_key.csv"
    experiment_dir.mkdir()
    _write_preview_plate_export(plate_file)
    _write_preview_key(key_file, zero_overlap=True)

    result = build_plate_reader_analysis_preview(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    )

    assert result.ok is False
    assert "No measured wells matched the concentration key." in result.errors
    assert result.summary["keyed_measured_well_count"] == 0


def test_preview_existing_outputs_are_warnings_not_errors(tmp_path):
    experiment_dir = tmp_path / "experiment"
    plate_file = tmp_path / "reader.txt"
    key_file = experiment_dir / "concentration_key.csv"
    output_dir = experiment_dir / "plate_reader_analysis"
    experiment_dir.mkdir()
    output_dir.mkdir()
    _write_preview_plate_export(plate_file)
    _write_preview_key(key_file)
    (experiment_dir / "reader_merged_tidy.csv").write_text("old\n", encoding="utf-8")

    result = build_plate_reader_analysis_preview(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    )

    assert result.ok is True
    assert result.errors == []
    assert any("Merged tidy CSV already exists" in warning for warning in result.warnings)
    assert any("Analysis output directory already exists" in warning for warning in result.warnings)


def test_successful_run_copies_plate_file_runs_commands_and_returns_package_paths(tmp_path):
    experiment_dir, key_file, plate_file = _make_experiment(tmp_path)
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    (ok, message, payload), stages, outputs = _run_worker(worker)

    assert ok is True
    assert "completed" in message
    copied_plate = Path(payload["copied_plate_reader_file"])
    merged_csv = Path(payload["merged_csv"])
    output_dir = Path(payload["output_dir"])
    assert copied_plate == experiment_dir / "raw_plate_reader" / plate_file.name
    assert copied_plate.read_text(encoding="utf-8") == plate_file.read_text(encoding="utf-8")
    assert merged_csv == experiment_dir / f"{plate_file.stem}_merged_tidy.csv"
    assert output_dir == experiment_dir / "plate_reader_analysis"
    assert Path(payload["manifest_json"]) == output_dir / "analysis_manifest.json"
    assert Path(payload["report_html"]) == output_dir / "analysis_report.html"
    assert payload["command_returncodes"] == {"associate": 0, "analyze": 0}

    assert [command.step for command in invocations] == ["associate", "analyze"]
    associate_command = invocations[0].command
    analysis_command = invocations[1].command
    assert Path(associate_command[2]) == experiment_dir
    assert Path(_option_value(associate_command, "--plate-file")) == copied_plate
    assert Path(_option_value(associate_command, "--key-file")) == key_file
    assert Path(_option_value(associate_command, "--output")) == merged_csv
    assert Path(_option_value(analysis_command, "--merged-csv")) == merged_csv
    assert Path(_option_value(analysis_command, "--output-dir")) == output_dir
    assert _option_value(analysis_command, "--endpoint-last-n") == "3"

    assert "Preparing plate reader analysis" in stages
    assert "Associating plate reader data with concentration key" in stages
    assert "Running plate reader analysis" in stages
    assert "Writing endpoint summaries" in stages
    assert "Finished" in stages
    assert any("Copied raw plate-reader file" in line for line in outputs)
    assert any("associate command output" in line for line in outputs)


def test_explicit_output_dir_and_endpoint_last_n_are_passed_to_analysis_command(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    output_dir = tmp_path / "custom_analysis"
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(
            experiment_dir=experiment_dir,
            plate_reader_file=plate_file,
            output_dir=output_dir,
            endpoint_last_n=5,
        ),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    (ok, _, payload), _, _ = _run_worker(worker)

    assert ok is True
    analysis_command = invocations[1].command
    assert Path(_option_value(analysis_command, "--output-dir")) == output_dir
    assert _option_value(analysis_command, "--endpoint-last-n") == "5"
    assert Path(payload["output_dir"]) == output_dir


def test_existing_raw_filename_collision_uses_numeric_suffix(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    raw_dir = experiment_dir / "raw_plate_reader"
    raw_dir.mkdir()
    existing = raw_dir / plate_file.name
    existing.write_text("different file\n", encoding="utf-8")
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    (ok, _, payload), _, _ = _run_worker(worker)

    assert ok is True
    copied_plate = Path(payload["copied_plate_reader_file"])
    assert copied_plate == raw_dir / "plate_reader_2.txt"
    assert copied_plate.read_text(encoding="utf-8") == plate_file.read_text(encoding="utf-8")
    assert Path(_option_value(invocations[0].command, "--plate-file")) == copied_plate


def test_missing_plate_reader_file_fails_before_commands(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    plate_file.unlink()
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert "Plate-reader file" in message
    assert payload == {}
    assert invocations == []


def test_missing_concentration_key_fails_before_commands(tmp_path):
    experiment_dir, key_file, plate_file = _make_experiment(tmp_path)
    key_file.unlink()
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert "Concentration key" in message
    assert payload == {}
    assert invocations == []


def test_association_failure_prevents_analysis_command(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    invocations = []

    def fake_runner(command, emit):
        invocations.append(command)
        emit("association failed")
        return 7

    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=fake_runner,
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert "association failed with return code 7" in message
    assert [command.step for command in invocations] == ["associate"]
    assert payload["command_returncodes"] == {"associate": 7, "analyze": None}


def test_analysis_failure_reports_return_code_and_paths(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    invocations = []

    def fake_runner(command, emit):
        invocations.append(command)
        if command.step == "associate":
            Path(_option_value(command.command, "--output")).write_text("merged\n", encoding="utf-8")
            return 0
        return 9

    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=fake_runner,
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert "analysis failed with return code 9" in message
    assert [command.step for command in invocations] == ["associate", "analyze"]
    assert payload["command_returncodes"] == {"associate": 0, "analyze": 9}
    assert Path(payload["merged_csv"]).name == "plate_reader_merged_tidy.csv"


def test_success_without_manifest_or_report_is_failure(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)

    def fake_runner(command, emit):
        if command.step == "associate":
            Path(_option_value(command.command, "--output")).write_text("merged\n", encoding="utf-8")
        return 0

    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=fake_runner,
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert "did not create" in message
    assert "analysis manifest" in message
    assert "analysis report" in message
    assert payload["command_returncodes"] == {"associate": 0, "analyze": 0}


def test_analysis_progress_lines_are_bridged_to_stage_signal(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner([], emit_progress=True),
    )

    (ok, _, _), stages, outputs = _run_worker(worker)

    assert ok is True
    assert "Writing endpoint summaries" in stages
    assert "[analysis] Writing endpoint summaries" in outputs


def test_explicit_missing_key_file_fails_before_commands(tmp_path):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    missing_key = tmp_path / "missing_key.csv"
    invocations = []
    worker = PlateReaderAnalysisWorker(
        PlateReaderAnalysisConfig(
            experiment_dir=experiment_dir,
            plate_reader_file=plate_file,
            key_file=missing_key,
        ),
        repo_root=tmp_path,
        command_runner=_successful_fake_runner(invocations),
    )

    ok, message, payload = _run_worker(worker)[0]

    assert ok is False
    assert str(missing_key) in message
    assert payload == {}
    assert invocations == []


@pytest.mark.parametrize("config_as_dict", [False, True])
def test_worker_accepts_config_dataclass_or_dict(tmp_path, config_as_dict):
    experiment_dir, _, plate_file = _make_experiment(tmp_path)
    config = PlateReaderAnalysisConfig(experiment_dir=experiment_dir, plate_reader_file=plate_file)
    worker_config = config.__dict__ if config_as_dict else config
    worker = PlateReaderAnalysisWorker(
        worker_config,
        repo_root=tmp_path,
        command_runner=_successful_fake_runner([]),
    )

    ok, _, _ = _run_worker(worker)[0]

    assert ok is True
