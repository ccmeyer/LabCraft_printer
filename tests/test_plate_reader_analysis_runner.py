from __future__ import annotations

from pathlib import Path

import pytest

from PlateReaderAnalysisRunner import (
    PlateReaderAnalysisConfig,
    PlateReaderAnalysisWorker,
)


def _make_experiment(tmp_path: Path) -> tuple[Path, Path, Path]:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    key_file = experiment_dir / "concentration_key.csv"
    key_file.write_text("Well ID,DNA_mM\nA1,1\n", encoding="utf-8")
    plate_file = tmp_path / "plate_reader.txt"
    plate_file.write_text("raw plate reader export\n", encoding="utf-8")
    return experiment_dir, key_file, plate_file


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
