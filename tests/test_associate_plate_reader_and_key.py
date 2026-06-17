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


def _write_single_channel_plate_export(path: Path) -> None:
    rows = [
        ["##BLOCKS= 1"],
        [
            "Plate:",
            "Plate1",
            "1.3",
            "TimeFormat",
            "Kinetic",
            "Fluorescence",
            "FALSE",
            "Raw",
            "FALSE",
            "3",
            "600",
            "60",
            "",
            "",
            "",
            "1",
            "510 ",
            "1",
            "5",
            "384",
            "485 ",
            "Manual",
            "",
            "",
            "",
            "10",
            "High",
            "",
            "",
            "1",
            "16",
            "485 ",
            "",
            "",
        ],
        ["Time", "Temperature(C)", "A1", "A2", "A3"],
        ["00:00:00", "37", "10", "20", ""],
        ["00:01:00", "37", "11", "21", ""],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerows(rows)


def _write_repeated_label_first_block_plate_export(path: Path) -> None:
    rows = [
        ["##BLOCKS= 1"],
        [
            "Plate:",
            "Plate1",
            "1.3",
            "TimeFormat",
            "Kinetic",
            "Fluorescence",
            "FALSE",
            "Raw",
            "FALSE",
            "2",
            "600",
            "60",
            "",
            "",
            "",
            "2",
            "502 540 ",
            "1",
            "6",
            "384",
            "460 515 ",
            "Manual",
            "",
            "",
            "",
            "10",
            "High",
            "",
            "",
            "1",
            "16",
            "460 515 ",
        ],
        ["Time", "Temperature(C)", "A1", "A2", "A3"],
        ["00:00:00", "37", "10", "20", ""],
        ["00:01:00", "37", "11", "21", ""],
        [],
        ["00:00:00", "37", "100", "200", ""],
        ["00:01:00", "37", "101", "201", ""],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerows(rows)


def _matrix_timepoint_rows(time: str, temperature: str, values: tuple[int, int, int, int]) -> list[list[str]]:
    a1, a2, b1, b2 = values
    rows = [
        [time, temperature, str(a1), str(a2), ""],
        ["", "", str(b1), str(b2), ""],
    ]
    rows.extend([["", "", "", "", ""] for _ in range(14)])
    return rows


def _write_matrix_plate_export(path: Path) -> None:
    metadata_row = [""] * 33
    metadata_values = {
        0: "Plate:",
        1: "Plate1",
        2: "1.3",
        3: "PlateFormat",
        4: "Kinetic",
        5: "Fluorescence",
        6: "TRUE",
        7: "Raw",
        8: "FALSE",
        9: "37",
        10: "600",
        11: "300",
        15: "1",
        16: "509 ",
        17: "1",
        18: "5",
        19: "384",
        20: "488 ",
        21: "Automatic",
        22: "495 ",
        25: "6",
        26: "Medium",
        29: "1",
        30: "16",
    }
    for index, value in metadata_values.items():
        metadata_row[index] = value

    rows = [
        ["##BLOCKS= 1"],
        metadata_row,
        ["", "Temperature(C)", "1", "2", "3"],
    ]
    rows.extend(_matrix_timepoint_rows("00:00:00", "36.5", (10, 20, 30, 40)))
    rows.append([])
    rows.extend(_matrix_timepoint_rows("00:05:00", "37.0", (11, 21, 31, 41)))
    rows.extend([[], ["~End"]])

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-16", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerows(rows)


def _write_compact_time_matrix_plate_export(path: Path) -> None:
    metadata_row = [""] * 33
    metadata_values = {
        0: "Plate:",
        1: "Plate#1",
        2: "1.3",
        3: "PlateFormat",
        4: "Kinetic",
        5: "Fluorescence",
        6: "TRUE",
        7: "Raw",
        8: "FALSE",
        9: "3",
        10: "3600",
        11: "120",
        15: "1",
        16: "590",
        17: "1",
        18: "24",
        19: "384",
        20: "560",
        21: "Manual",
        22: "570",
        25: "6",
        26: "Medium",
        29: "1",
        30: "16",
        32: "None",
    }
    for index, value in metadata_values.items():
        metadata_row[index] = value

    rows = [
        ["##BLOCKS= 1"],
        metadata_row,
        ["Time(hh:mm:ss)", "Temperature(¡C)", "1", "2", "3"],
    ]
    rows.extend(_matrix_timepoint_rows("0:00", "37.0", (10, 20, 30, 40)))
    rows.extend(_matrix_timepoint_rows("2:00", "37.1", (11, 21, 31, 41)))
    rows.extend(_matrix_timepoint_rows("1:00:00", "37.2", (12, 22, 32, 42)))
    rows.extend([["~End"]])

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp1252", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerows(rows)


def _write_endpoint_matrix_plate_export(path: Path) -> None:
    metadata_row = [""] * 33
    metadata_values = {
        0: "Plate:",
        1: "Plate#1",
        2: "1.3",
        3: "PlateFormat",
        4: "Endpoint",
        5: "Fluorescence",
        6: "TRUE",
        7: "Raw",
        8: "FALSE",
        9: "1",
        15: "1",
        16: "585",
        17: "1",
        18: "24",
        19: "384",
        20: "560",
        21: "Manual",
        22: "570",
        25: "6",
        26: "Medium",
        29: "1",
        30: "16",
        32: "None",
    }
    for index, value in metadata_values.items():
        metadata_row[index] = value

    rows = [
        ["##BLOCKS= 1"],
        metadata_row,
        ["", "Temperature(¡C)", "1", "2", "3"],
        ["", "23.50", "100.5", "200.5", ""],
        ["", "", "300.5", "400.5", ""],
        ["", "", "", "500.5", ""],
        [],
        ["~End"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp1252", newline="") as handle:
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


def _write_matrix_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "Well ID,DNA_mM,Water_--",
                "A1,1.0,10",
                "A2,2.0,11",
                "B1,3.0,12",
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


def test_single_channel_export_with_split_ex_em_metadata_is_parsed(tmp_path):
    exp_dir = tmp_path / "SingleChannel-20260501_195912"
    plate = exp_dir / "SingleChannel_data.xls"
    key = exp_dir / "concentration_key.csv"
    _write_single_channel_plate_export(plate)
    _write_key(key)

    merged, filter_result, summary = mod.build_merged_tidy_data(plate, key)

    assert len(merged) == 4
    assert filter_result.dropped_timepoints == []
    assert set(merged["fluorophore"]) == {"485_510"}
    assert set(merged["excitation_nm"]) == {485}
    assert set(merged["emission_nm"]) == {510}
    assert merged.groupby("fluorophore")["time"].nunique().to_dict() == {"485_510": 2}
    assert summary.keyed_wells == ["A1", "A2"]
    assert summary.missing_key_wells == ["A4"]


def test_split_emission_excitation_metadata_defines_kinetic_block_labels(tmp_path):
    exp_dir = tmp_path / "RepeatedFirstChannel-20260616_201900"
    plate = exp_dir / "RepeatedFirstChannel_data.xls"
    key = exp_dir / "concentration_key.csv"
    _write_repeated_label_first_block_plate_export(plate)
    _write_key(key)

    merged, filter_result, summary = mod.build_merged_tidy_data(plate, key)

    assert len(merged) == 8
    assert filter_result.dropped_timepoints == []
    assert set(merged["fluorophore"]) == {"460_502", "515_540"}
    first_block_a1 = merged.loc[
        (merged["well"] == "A1")
        & (merged["fluorophore"] == "460_502")
        & (merged["time"] == "00:00:00")
    ].iloc[0]
    second_block_a1 = merged.loc[
        (merged["well"] == "A1")
        & (merged["fluorophore"] == "515_540")
        & (merged["time"] == "00:00:00")
    ].iloc[0]
    assert first_block_a1["rfu"] == 10
    assert second_block_a1["rfu"] == 100
    assert summary.keyed_wells == ["A1", "A2"]


def test_matrix_txt_export_discovers_inputs_and_maps_plate_rows(tmp_path):
    exp_dir = tmp_path / "MatrixReader-20260602_135844"
    plate = exp_dir / "MatrixReader_LabCraft.txt"
    key = exp_dir / "concentration_key.csv"
    _write_matrix_plate_export(plate)
    _write_matrix_key(key)

    assert mod.main([str(exp_dir)]) == 0

    out = exp_dir / "MatrixReader_LabCraft_merged_tidy.csv"
    df = _read_output(out)
    assert len(df) == 8
    assert set(df["well"]) == {"A1", "A2", "B1", "B2"}
    assert set(df["fluorophore"]) == {"488_509"}
    assert set(df["excitation_nm"]) == {488}
    assert set(df["emission_nm"]) == {509}
    assert "Water_--" not in df.columns

    b2_final = df.loc[(df["well"] == "B2") & (df["time"] == "00:05:00")].iloc[0]
    assert b2_final["rfu"] == 41
    assert b2_final["temperature_c"] == 37.0
    assert not bool(b2_final["is_keyed"])


def test_compact_time_matrix_txt_export_normalizes_time_values(tmp_path):
    exp_dir = tmp_path / "CompactTimeReader-20260605_215910"
    plate = exp_dir / "LabCraft-260605-HEM_data.txt"
    key = exp_dir / "concentration_key.csv"
    _write_compact_time_matrix_plate_export(plate)
    _write_matrix_key(key)

    assert mod.main([str(exp_dir)]) == 0

    out = exp_dir / "LabCraft-260605-HEM_data_merged_tidy.csv"
    df = _read_output(out)
    assert len(df) == 12
    assert set(df["well"]) == {"A1", "A2", "B1", "B2"}
    assert set(df["fluorophore"]) == {"560_590"}
    assert set(df["excitation_nm"]) == {560}
    assert set(df["emission_nm"]) == {590}
    assert sorted(df["time"].unique()) == ["00:00:00", "00:02:00", "01:00:00"]
    assert set(df["time_seconds"]) == {0.0, 120.0, 3600.0}
    assert set(df["time_minutes"]) == {0.0, 2.0, 60.0}

    b2_hour = df.loc[(df["well"] == "B2") & (df["time"] == "01:00:00")].iloc[0]
    assert b2_hour["rfu"] == 42
    assert b2_hour["temperature_c"] == 37.2
    assert not bool(b2_hour["is_keyed"])


def test_endpoint_matrix_txt_export_discovers_inputs_and_maps_single_endpoint(tmp_path):
    exp_dir = tmp_path / "EndpointReader-20260603_162039"
    plate = exp_dir / "Data 06-03-26-162039_medium pmt 560ex 585em.txt"
    key = exp_dir / "concentration_key.csv"
    _write_endpoint_matrix_plate_export(plate)
    _write_matrix_key(key)

    assert mod.main([str(exp_dir)]) == 0

    out = exp_dir / "Data 06-03-26-162039_medium pmt 560ex 585em_merged_tidy.csv"
    df = _read_output(out)
    assert len(df) == 5
    assert set(df["well"]) == {"A1", "A2", "B1", "B2", "C2"}
    assert set(df["time"]) == {"00:00:00"}
    assert set(df["time_seconds"]) == {0.0}
    assert set(df["time_minutes"]) == {0.0}
    assert set(df["fluorophore"]) == {"560_585"}
    assert set(df["excitation_nm"]) == {560}
    assert set(df["emission_nm"]) == {585}

    c2 = df.loc[df["well"] == "C2"].iloc[0]
    assert c2["rfu"] == 500.5
    assert c2["temperature_c"] == 23.5
    assert not bool(c2["is_keyed"])


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
