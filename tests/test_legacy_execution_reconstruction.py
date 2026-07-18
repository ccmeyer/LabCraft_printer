import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ExecutionPlan import ExecutionPlanState
from LegacyExecutionPlan import (
    LegacyExecutionClassification,
    inspect_legacy_execution,
    reconstruct_legacy_execution,
)
from Model import CURRENT_PROFILE, ExperimentModel


PURE_VOLUME_NL = 143.59278258103592
UTP_VOLUME_NL = 10.5
HISTORICAL_NONFILL_NL = 2559.9845212965747


def _design(*, applied=True, include_exact_volumes=True, uploaded=False):
    pure_option = {
        "name": "PURE MM",
        "targets": [1.0],
        "units": "x",
        "printing_mode": "stream",
        "forced_stock_conc": 1.11,
    }
    utp_option = {
        "name": "UTP (dil)",
        "targets": [10000.0],
        "units": "nM",
        "printing_mode": "droplet",
        "forced_stock_conc": 95000.0,
    }
    if include_exact_volumes:
        pure_option["droplet_nL"] = PURE_VOLUME_NL
        pure_option["intended_droplet_nL"] = 60.0
        utp_option["droplet_nL"] = UTP_VOLUME_NL
    payload = {
        "metadata": {
            "name": "legacy-synthetic",
            "replicates": 1,
            "target_reaction_volume_nL": 2500.0,
            "printed_volume_tolerance_nL": 50.0,
            "final_reaction_volume_nL": 2500.0,
            "fill_reagent_name": "Water",
            "fill_printing_mode": "droplet",
            "fill_droplet_volume_nL": 10.0,
            "plate_name": "test-plate",
            "plate_rows": 8,
            "plate_columns": 12,
        },
        "factors": [
            {"name": "PURE MM", "kind": "additive", "options": [pure_option]},
            {"name": "UTP", "kind": "choice", "options": [utp_option]},
        ],
        "applied_imaging_calibrations": {
            "schema_version": 1,
            "records": (
                {
                    "pure-record": {
                        "stock_id": "PURE MM_1.11_x",
                        "printer_head_id": "head-pure",
                        "applied_design_volume_nL": 143.6,
                        "recorded_at": "2026-01-02T00:00:00Z",
                    },
                    "utp-record": {
                        "stock_id": "UTP (dil)_95000.00_nM",
                        "printer_head_id": "head-utp",
                        "applied_design_volume_nL": 10.4,
                        "recorded_at": "2026-01-02T00:01:00Z",
                    },
                }
                if applied
                else {}
            ),
        },
    }
    if uploaded:
        payload["uploaded_design"] = {
            "reactions": [
                [
                    {"factor": "PURE MM", "option": None, "target": 1.0},
                    {"factor": "UTP", "option": "UTP (dil)", "target": 10000.0},
                ]
            ],
            "csv_filename": "missing-upload.csv",
            "well_ids": ["A1"],
        }
    return payload


def _progress(*, pure_target=16, utp_target=25, added=True):
    return {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                "PURE MM_1.11_x": {
                    "target_droplets": pure_target,
                    "added_droplets": pure_target if added else 0,
                },
                "UTP (dil)_95000.00_nM": {
                    "target_droplets": utp_target,
                    "added_droplets": utp_target if added else 0,
                },
            },
            "completed": bool(added),
        },
        "__plate__": {
            "schema_version": 1,
            "name": "test-plate",
            "rows": 8,
            "columns": 12,
        },
    }


def _write_folder(
    directory: Path,
    *,
    design=None,
    progress=None,
    key_pure=16,
    key_utp=25,
    audit_events=None,
):
    directory.mkdir()
    design = _design() if design is None else design
    (directory / "experiment_design.json").write_text(
        json.dumps(design, indent=2), encoding="utf-8"
    )
    if progress is not None:
        (directory / "progress.json").write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )
    if key_pure is not None:
        (directory / "key.csv").write_text(
            "Well ID,PURE MM_1.11_x_143.6nL,UTP (dil)_95000.00_nM_10.4nL\n"
            f"A1,{float(key_pure):.1f},{float(key_utp):.1f}\n",
            encoding="utf-8",
        )
    if audit_events:
        (directory / "experiment_audit.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in audit_events),
            encoding="utf-8",
        )
    (directory / "concentration_key.csv").write_text(
        "Well ID,PURE MM_x\nA1,1\n", encoding="utf-8"
    )
    return design


def _directory_snapshot(directory: Path):
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _issue_codes(result):
    return {issue.code for issue in result.issues}


def test_recorded_execution_reconstructs_without_optimizer_or_writes(tmp_path, monkeypatch):
    directory = tmp_path / "recorded"
    progress = _progress()
    _write_folder(directory, progress=progress)
    before = _directory_snapshot(directory)

    model = ExperimentModel(prof=CURRENT_PROFILE)
    optimize = Mock(side_effect=AssertionError("recorded load must not optimize"))
    monkeypatch.setattr(model, "optimize_stock_solutions", optimize)

    result = model.load_experiment(str(directory / "experiment_design.json"), str(directory))

    assert result.classification is LegacyExecutionClassification.RECORDED_EXECUTION
    assert result.plan is not None
    assert result.plan.state is ExecutionPlanState.COMPLETED
    assert result.plan.plan_revision == 1
    assert model.is_read_only_legacy_execution() is True
    assert optimize.call_count == 0
    assert model.get_worst_nonfill_volume_nL() == pytest.approx(HISTORICAL_NONFILL_NL)
    assert len(model.get_reactions_dataframe()) == 1
    rows = model.get_stock_table_rows(include_fill=True)
    pure = next(row for row in rows if row["factor_name"] == "PURE MM")
    utp = next(row for row in rows if row["option_name"] == "UTP (dil)")
    assert pure["droplet_volume_nL"] == PURE_VOLUME_NL
    assert pure["total_droplets"] == 16
    assert utp["droplet_volume_nL"] == UTP_VOLUME_NL
    assert utp["total_droplets"] == 25
    assert model.progress_data == progress
    assert model.experiment_dir_path == str(directory)
    assert model.concentration_key_file_path == str(directory / "concentration_key.csv")
    assert _directory_snapshot(directory) == before
    assert not (directory / "execution_plan.json").exists()


def test_progress_targets_win_over_key_with_visible_warning(tmp_path):
    directory = tmp_path / "mismatch"
    design = _write_folder(directory, progress=_progress(), key_utp=24)

    result = reconstruct_legacy_execution(directory, design)

    assert result.plan is not None
    assert "progress_key_target_mismatch" in _issue_codes(result)
    well = result.plan.wells[0]
    assert {item.stock_id: item.target_dispenses for item in well.dispenses}[
        "UTP (dil)_95000.00_nM"
    ] == 25


def test_calibration_only_execution_uses_key_and_is_read_only(tmp_path):
    directory = tmp_path / "calibration-only"
    design = _write_folder(directory, progress={}, key_utp=25)

    result = reconstruct_legacy_execution(directory, design)

    assert result.classification is LegacyExecutionClassification.RECORDED_EXECUTION
    assert result.plan is not None
    assert result.plan.state is ExecutionPlanState.ACTIVE
    assert "reaction_ids_reconstructed" in _issue_codes(result)
    assert result.plan.wells[0].reaction_id == "legacy_A1"


def test_audit_only_execution_evidence_is_detected(tmp_path):
    directory = tmp_path / "audit-only"
    design = _design(applied=False)
    audit = [
        {
            "event_type": "print_array_started",
            "timestamp_utc": "2026-01-03T00:00:00Z",
        }
    ]
    _write_folder(directory, design=design, progress={}, audit_events=audit)

    inspected = inspect_legacy_execution(directory, design)
    result = reconstruct_legacy_execution(directory, design)

    assert inspected.classification is LegacyExecutionClassification.RECORDED_EXECUTION
    assert result.plan is not None
    assert result.plan.lock_reason == "legacy_printing_started"


def test_incomplete_execution_uses_latest_terminal_abort_state(tmp_path):
    directory = tmp_path / "aborted"
    design = _design(applied=False)
    audit = [
        {"event_type": "print_array_aborted", "timestamp_utc": "2026-01-03T00:00:00Z"},
        {"event_type": "print_array_requested", "timestamp_utc": "2026-01-03T00:01:00Z"},
    ]
    _write_folder(
        directory,
        design=design,
        progress=_progress(added=False),
        audit_events=audit,
    )

    result = reconstruct_legacy_execution(directory, design)

    assert result.plan.state is ExecutionPlanState.ABORTED


def test_populated_key_alone_remains_an_unrun_design(tmp_path):
    directory = tmp_path / "key-only-unrun"
    design = _design(applied=False)
    _write_folder(directory, design=design, progress=None)

    result = inspect_legacy_execution(directory, design)

    assert result.classification is LegacyExecutionClassification.UNRUN_DESIGN


def test_exact_design_volume_wins_over_key_and_calibration_rounding(tmp_path):
    directory = tmp_path / "exact-volume"
    design = _write_folder(directory, progress=_progress())

    result = reconstruct_legacy_execution(directory, design)

    stocks = {stock.stock_id: stock for stock in result.plan.stocks}
    assert stocks["PURE MM_1.11_x"].effective_volume_nL == PURE_VOLUME_NL
    assert stocks["UTP (dil)_95000.00_nM"].effective_volume_nL == UTP_VOLUME_NL
    assert "dispense_volume_from_key_header" not in _issue_codes(result)


def test_stock_ids_allow_reagent_names_with_underscores(tmp_path):
    directory = tmp_path / "underscored-reagent"
    design = _design()
    design["factors"][0]["name"] = "PURE_MM"
    design["factors"][0]["options"][0]["name"] = "PURE_MM"
    design["applied_imaging_calibrations"]["records"]["pure-record"]["stock_id"] = (
        "PURE_MM_1.11_x"
    )
    progress = _progress()
    pure_counts = progress["A1"]["reagents"].pop("PURE MM_1.11_x")
    progress["A1"]["reagents"]["PURE_MM_1.11_x"] = pure_counts
    _write_folder(directory, design=design, progress=progress, key_pure=None)

    result = reconstruct_legacy_execution(directory, design)

    assert result.plan is not None
    pure = next(stock for stock in result.plan.stocks if stock.stock_id == "PURE_MM_1.11_x")
    assert pure.reagent_name == "PURE_MM"
    assert pure.factor_name == "PURE_MM"


def test_rounded_key_fallback_emits_provenance_warnings(tmp_path):
    directory = tmp_path / "rounded-fallback"
    design = _design(include_exact_volumes=False)
    _write_folder(directory, design=design, progress=_progress())

    result = reconstruct_legacy_execution(directory, design)

    assert result.plan is not None
    assert "dispense_volume_from_key_header" in _issue_codes(result)
    stocks = {stock.stock_id: stock for stock in result.plan.stocks}
    assert stocks["PURE MM_1.11_x"].effective_volume_nL == pytest.approx(143.6)
    assert stocks["UTP (dil)_95000.00_nM"].effective_volume_nL == pytest.approx(10.4)


def test_fatal_recorded_reconstruction_stays_read_only_and_never_optimizes(
    tmp_path, monkeypatch
):
    directory = tmp_path / "fatal"
    design = _design()
    bad_progress = _progress()
    bad_progress["A1"]["reagents"] = {"not-a-stock-id": {"target_droplets": 1, "added_droplets": 1}}
    _write_folder(directory, design=design, progress=bad_progress, key_pure=None)

    model = ExperimentModel(prof=CURRENT_PROFILE)
    optimize = Mock(side_effect=AssertionError("fatal recorded load must not optimize"))
    monkeypatch.setattr(model, "optimize_stock_solutions", optimize)

    result = model.load_experiment(str(directory / "experiment_design.json"), str(directory))

    assert result.classification is LegacyExecutionClassification.RECORDED_EXECUTION
    assert result.plan is None
    assert result.has_fatal_issues
    assert model.is_read_only_legacy_execution() is True
    assert model.get_stock_table_rows() == []
    assert optimize.call_count == 0


def test_unreadable_progress_is_fatal_and_cannot_fall_back_to_optimization(
    tmp_path, monkeypatch
):
    directory = tmp_path / "unreadable-progress"
    design = _design(applied=False)
    _write_folder(directory, design=design, progress=None)
    (directory / "progress.json").write_text("{not valid json", encoding="utf-8")

    model = ExperimentModel(prof=CURRENT_PROFILE)
    optimize = Mock(side_effect=AssertionError("corrupt progress must not optimize"))
    monkeypatch.setattr(model, "optimize_stock_solutions", optimize)

    result = model.load_experiment(str(directory / "experiment_design.json"), str(directory))

    assert result.classification is LegacyExecutionClassification.RECORDED_EXECUTION
    assert result.plan is None
    assert "progress_unreadable" in _issue_codes(result)
    assert model.is_read_only_legacy_execution() is True
    optimize.assert_not_called()


def test_unreadable_key_is_only_a_warning_when_progress_is_authoritative(tmp_path):
    directory = tmp_path / "bad-key-cross-check"
    design = _write_folder(directory, progress=_progress())
    (directory / "key.csv").write_text("not a valid legacy key\n", encoding="utf-8")

    result = reconstruct_legacy_execution(directory, design)

    assert result.plan is not None
    assert "key_unreadable" in _issue_codes(result)
    assert not result.has_fatal_issues


def test_unrun_design_keeps_in_memory_generation_and_does_not_materialize_upload(
    tmp_path, monkeypatch
):
    directory = tmp_path / "unrun"
    design = _design(applied=False, uploaded=True)
    _write_folder(directory, design=design, progress=None, key_pure=None)
    before = _directory_snapshot(directory)

    model = ExperimentModel(prof=CURRENT_PROFILE)
    optimize = Mock(return_value={"best": {"ok": True}})
    generate = Mock()
    materialize = Mock(side_effect=AssertionError("load must not write an upload CSV"))
    monkeypatch.setattr(model, "optimize_stock_solutions", optimize)
    monkeypatch.setattr(model, "generate_experiment", generate)
    monkeypatch.setattr(model, "_materialize_uploaded_design_csv", materialize)

    result = model.load_experiment(str(directory / "experiment_design.json"), str(directory))

    assert result.classification is LegacyExecutionClassification.UNRUN_DESIGN
    assert model.is_read_only_legacy_execution() is False
    optimize.assert_called_once()
    generate.assert_called_once()
    materialize.assert_not_called()
    assert _directory_snapshot(directory) == before


def test_plan_id_is_independent_of_folder_and_added_counts(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    design_one = _write_folder(first, progress=_progress(added=False))
    design_two = _write_folder(second, progress=_progress(added=True))

    first_result = reconstruct_legacy_execution(first, design_one)
    second_result = reconstruct_legacy_execution(second, design_two)

    assert first_result.plan.plan_id == second_result.plan.plan_id


def test_read_only_model_rejects_optimizer_saves_and_calibration_changes(tmp_path):
    directory = tmp_path / "guards"
    _write_folder(directory, progress=_progress())
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.load_experiment(str(directory / "experiment_design.json"), str(directory))

    assert model.get_plan_for_key(("PURE MM", None)) is None
    assert model.optimize_stock_solutions()["read_only"] is True
    with pytest.raises(RuntimeError, match="read-only"):
        model.save_experiment()
    with pytest.raises(RuntimeError, match="read-only"):
        model.apply_droplet_volume_for_option("PURE MM", None, 144.0)
    with pytest.raises(RuntimeError, match="read-only"):
        model.apply_fill_droplet_volume(11.0)
