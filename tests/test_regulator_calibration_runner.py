from datetime import datetime, timezone
from pathlib import Path

import pytest

import RegulatorProfiles as rp
from RegulatorCalibrationRunner import (
    RegulatorCalibrationError,
    build_selftest_command,
    collect_trace_files,
    prepare_regulator_calibration_run,
    write_run_metadata,
)


def _now():
    return datetime(2026, 5, 29, 19, 0, 0, tzinfo=timezone.utc)


def _config(**overrides):
    config = {
        "profile_id": "stream_default",
        "mode": "stream",
        "trace_case_id": 2102,
        "operator": "operator",
        "printer_head_id": "head-1",
        "printer_head_type": "stream-head",
        "reagent_id": "water",
        "calibrated_head_confirmed": True,
    }
    config.update(overrides)
    return config


def _prepared(tmp_path, **overrides):
    return prepare_regulator_calibration_run(
        _config(**overrides),
        profile_document=rp.factory_default_document(),
        output_root=tmp_path,
        now_fn=_now,
        id_factory=lambda: "abc12345",
    )


def test_prepare_run_maps_fixed_trace_case_conditions(tmp_path):
    prepared = _prepared(tmp_path, trace_case_id=2104)

    assert prepared.run_id == "regopt_20260529_190000_abc12345"
    assert prepared.session_id == "session_20260529_190000_abc12345"
    assert prepared.trace_case.channels == ("print", "refuel")
    assert prepared.conditions == {
        "printer_head_id": "head-1",
        "printer_head_type": "stream-head",
        "reagent_id": "water",
        "print_pressure_psi": 1.0,
        "print_pulse_width_us": 1300,
        "refuel_pressure_psi": 0.5,
        "refuel_pulse_width_us": 3000,
        "frequency_hz": 20,
        "pulse_count": 10,
        "channel": "both",
    }
    assert prepared.metadata["baseline_profile"]["firmware_baseline_source"] == "internal_stage2_snapshot"
    assert prepared.metadata["candidate_profile_id"] == "stream_default"


def test_prepare_rejects_missing_confirmation_and_condition_overrides(tmp_path):
    with pytest.raises(RegulatorCalibrationError, match="calibrated printer head"):
        _prepared(tmp_path, calibrated_head_confirmed=False)

    with pytest.raises(RegulatorCalibrationError, match="unsupported condition overrides"):
        _prepared(tmp_path, print_pressure_psi=2.0)


def test_prepare_rejects_missing_profile_and_mode_mismatch(tmp_path):
    with pytest.raises(RegulatorCalibrationError, match="does not exist"):
        _prepared(tmp_path, profile_id="missing")

    with pytest.raises(RegulatorCalibrationError, match="does not match selected mode"):
        _prepared(tmp_path, profile_id="stream_default", mode="droplet")


def test_metadata_and_trace_file_collection(tmp_path):
    prepared = _prepared(tmp_path)
    trace_path = prepared.run_dir / "raw_selftest_trace_2102.json"
    trace_path.write_text("{}", encoding="utf-8")

    metadata = write_run_metadata(
        prepared,
        status="completed",
        restored_previous_profile=True,
        error_message="",
    )

    assert collect_trace_files(prepared) == ["raw_selftest_trace_2102.json"]
    assert metadata["outputs"]["trace_files"] == ["raw_selftest_trace_2102.json"]
    assert metadata["outcome"] == {
        "status": "completed",
        "restored_previous_profile": True,
        "error_message": "",
    }
    assert (prepared.run_dir / "run_meta.json").exists()


def test_build_selftest_command_uses_existing_pressure_trace_selector(tmp_path):
    prepared = _prepared(tmp_path, trace_case_id=2103)

    command = build_selftest_command(
        prepared,
        port="COM7",
        baud=230400,
        run_selftest_path=Path("tools/run_selftest.py"),
        python_executable="python-under-test",
        timeout_ms=45000,
    )

    assert command[:2] == ("python-under-test", "tools\\run_selftest.py") or command[:2] == (
        "python-under-test",
        "tools/run_selftest.py",
    )
    assert "--pressure-trace" in command
    assert command[command.index("--pressure-trace-test") + 1] == "2103"
    assert command[command.index("--profile") + 1] == "FULL"
    assert command[command.index("--port") + 1] == "COM7"
    assert command[command.index("--baud") + 1] == "230400"
    assert command[command.index("--timeout-ms") + 1] == "45000"
