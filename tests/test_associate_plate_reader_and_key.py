from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pandas as pd

from tools.data_analysis import associate_plate_reader_and_key as mod


def _write_plate_export(path: Path, *, incomplete_final: bool = True) -> None:
    rows = [
        ["##BLOCKS= 1"],
        ["Plate:", "Plate1", "1.3", "502 540", "Manual", "460 515"],
        ["Time", "Temperature(°C)", "A1", "A2", "A3", "A4"],
        ["00:00:00", "37", "10", "20", "30", ""],
        ["00:01:00", "37", "11", "21", "31", ""],
        ["00:02:00", "37", "12", "22", "32", ""],
        [],
        ["00:00:00", "37", "100", "200", "300", ""],
        ["00:01:00", "37", "101", "201", "301", ""],
        ["00:02:00", "37", "102", "202", "" if incomplete_final else "302", ""],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerows(rows)


def _write_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "Well ID,DNA_mM,Mg_mM,Water_--,Diluent_--",
                "A1,1.0,5.0,10,20",
                "A2,2.0,6.0,11,21",
                "A4,4.0,8.0,12,22",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _make_experiment(
    tmp_path: Path,
    *,
    name: str = "ExperimentA-20260429_180300",
    incomplete_final: bool = True,
) -> tuple[Path, Path, Path]:
    exp_dir = tmp_path / name
    plate = exp_dir / "ExperimentA_data.xls"
    key = exp_dir / "concentration_key.csv"
    _write_plate_export(plate, incomplete_final=incomplete_final)
    _write_key(key)
    return exp_dir, plate, key


def _read_output(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def test_experiment_directory_discovers_inputs_and_writes_tidy_output(tmp_path, capsys):
    exp_dir, _plate, _key = _make_experiment(tmp_path)

    assert mod.main([str(exp_dir)]) == 0

    out = exp_dir / "ExperimentA_data_merged_tidy.csv"
    df = _read_output(out)
    assert len(df) == 12
    assert set(df["time"]) == {"00:00:00", "00:01:00"}
    assert set(df["fluorophore"]) == {"502_540", "460_515"}
    assert "time_seconds" in df.columns
    assert "time_minutes" in df.columns
    assert "excitation_nm" in df.columns
    assert "emission_nm" in df.columns

    captured = capsys.readouterr()
    assert "Dropped incomplete timepoints" in captured.out
    assert "00:02:00" in captured.out


def test_bare_experiment_name_resolves_under_default_experiments_dir(tmp_path, monkeypatch):
    experiments_root = tmp_path / "Experiments"
    exp_dir, _plate, _key = _make_experiment(experiments_root, name="Mg_DNA_screen-20260429_180300")
    monkeypatch.setattr(mod, "DEFAULT_EXPERIMENTS_DIR", experiments_root)

    assert mod.main(["Mg_DNA_screen-20260429_180300"]) == 0

    out = exp_dir / "ExperimentA_data_merged_tidy.csv"
    df = _read_output(out)
    assert len(df) == 12


def test_wildcard_experiment_name_resolves_single_match(tmp_path, monkeypatch):
    experiments_root = tmp_path / "Experiments"
    exp_dir, _plate, _key = _make_experiment(experiments_root, name="Mg_DNA_screen-20260429_180300")
    monkeypatch.setattr(mod, "DEFAULT_EXPERIMENTS_DIR", experiments_root)

    assert mod.main(["Mg_DNA_screen*"]) == 0

    out = exp_dir / "ExperimentA_data_merged_tidy.csv"
    assert out.exists()


def test_wildcard_experiment_name_lists_multiple_matches_and_exits(tmp_path, monkeypatch, capsys):
    experiments_root = tmp_path / "Experiments"
    _make_experiment(experiments_root, name="Mg_DNA_screen-20260429_180300")
    _make_experiment(experiments_root, name="Mg_DNA_screen-20260430_120000")
    monkeypatch.setattr(mod, "DEFAULT_EXPERIMENTS_DIR", experiments_root)

    assert mod.main(["Mg_DNA_screen*"]) == 1

    captured = capsys.readouterr()
    assert "Multiple experiment directories matched" in captured.err
    assert "Mg_DNA_screen-20260429_180300" in captured.err
    assert "Mg_DNA_screen-20260430_120000" in captured.err
    assert "complete experiment directory name" in captured.err


def test_explicit_plate_key_and_output_options_work(tmp_path):
    exp_dir, plate, key = _make_experiment(tmp_path)
    out = exp_dir / "custom.csv"

    assert mod.main(["--plate-file", str(plate), "--key-file", str(key), "--output", str(out)]) == 0

    df = _read_output(out)
    assert len(df) == 12
    assert set(df["well"]) == {"A1", "A2", "A3"}


def test_diluent_columns_are_dropped_and_concentration_columns_are_preserved(tmp_path):
    _exp_dir, plate, key = _make_experiment(tmp_path)

    merged, _filter_result, _summary = mod.build_merged_tidy_data(plate, key)

    assert "DNA_mM" in merged.columns
    assert "Mg_mM" in merged.columns
    assert "Water_--" not in merged.columns
    assert "Diluent_--" not in merged.columns


def test_keyed_and_unkeyed_wells_are_retained_with_is_keyed(tmp_path):
    _exp_dir, plate, key = _make_experiment(tmp_path)

    merged, _filter_result, summary = mod.build_merged_tidy_data(plate, key)

    keyed_by_well = merged.groupby("well")["is_keyed"].first().to_dict()
    assert keyed_by_well == {"A1": True, "A2": True, "A3": False}
    assert summary.keyed_wells == ["A1", "A2"]
    assert summary.unkeyed_measured_wells == ["A3"]
    assert summary.missing_key_wells == ["A4"]
    assert merged.loc[merged["well"] == "A3", ["DNA_mM", "Mg_mM"]].isna().all().all()


def test_incomplete_final_timepoint_is_dropped_from_all_fluorophores(tmp_path):
    _exp_dir, plate, key = _make_experiment(tmp_path)

    merged, filter_result, _summary = mod.build_merged_tidy_data(plate, key)

    assert [item["time"] for item in filter_result.dropped_timepoints] == ["00:02:00"]
    assert set(merged["time"]) == {"00:00:00", "00:01:00"}
    assert merged.groupby("fluorophore")["time"].nunique().to_dict() == {
        "460_515": 2,
        "502_540": 2,
    }


def test_multiple_matching_plate_exports_fail_with_useful_error(tmp_path, capsys):
    exp_dir, _plate, _key = _make_experiment(tmp_path)
    _write_plate_export(exp_dir / "Second_data.xls")

    assert mod.main([str(exp_dir)]) == 1

    captured = capsys.readouterr()
    assert "Multiple plate-reader data files were found" in captured.err
    assert "--plate-file" in captured.err


def test_legacy_wrapper_delegates_to_new_tool_with_legacy_args(tmp_path):
    _exp_dir, plate, key = _make_experiment(tmp_path)
    out = tmp_path / "legacy.csv"
    wrapper_path = Path("FreeRTOS-interface/Experiments/associate_plate_reader_and_key.py")
    spec = importlib.util.spec_from_file_location("legacy_plate_assoc", wrapper_path)
    assert spec is not None
    legacy = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(legacy)

    assert legacy.main([str(plate), str(key), "-o", str(out)]) == 0

    df = _read_output(out)
    assert len(df) == 12
    assert set(df["well"]) == {"A1", "A2", "A3"}
