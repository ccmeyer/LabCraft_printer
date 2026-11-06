from __future__ import annotations

import pytest

from tests.tecan_fixtures import tecan_endpoint_rows, tecan_kinetic_rows, write_tecan_workbook
from tools.data_analysis import associate_plate_reader_and_key as association
from tools.data_analysis.tecan_plate_reader import list_tecan_measurement_sheets, worksheet_output_token


@pytest.mark.parametrize("shared_strings", [False, True])
def test_kinetic_xlsx_preserves_wells_fractional_seconds_temperature_and_channel(tmp_path, shared_strings):
    path = write_tecan_workbook(tmp_path / "reader.xlsx", shared_strings=shared_strings)
    dataframe = association.parse_plate_reader(path)
    assert len(dataframe) == 8
    assert set(dataframe["well"]) == {"A1", "A2"}
    assert dataframe.loc[dataframe["well"] == "A1", "time_seconds"].tolist() == [0, 300, 600, 900.1]
    final = dataframe.iloc[-1]
    assert final["time"] == "00:15:00.1"
    assert final["time_minutes"] == pytest.approx(900.1 / 60)
    assert final["temperature_c"] == 37.2
    assert final["rfu"] == 410
    assert final["fluorophore"] == "485_535"
    assert final["excitation_nm"] == 485
    assert final["emission_nm"] == 535
    assert dataframe.attrs["source_sheet"] == "gain 100 actual data"
    assert dataframe.attrs["gain"] == 100
    assert "gain" not in dataframe.columns
    assert list_tecan_measurement_sheets(path) == ["gain 100 actual data"]


def test_endpoint_xlsx_maps_explicit_plate_rows_and_columns(tmp_path):
    rows = tecan_endpoint_rows()
    rows[7] = ["<>", 2, 1]
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {"endpoint": rows})
    dataframe = association.parse_plate_reader(path)
    assert len(dataframe) == 4
    assert dataframe.set_index("well")["rfu"].to_dict() == {"A1": 200, "A2": 100, "B1": 400, "B2": 300}
    assert set(dataframe["time_seconds"]) == {0}
    assert set(dataframe["time"]) == {"00:00:00"}
    assert set(dataframe["temperature_c"]) == {37.1}
    assert dataframe.attrs["measurement_kind"] == "endpoint"


def test_multiple_measurements_require_exact_sheet_selection(tmp_path):
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {
        "gain 100 actual data": tecan_kinetic_rows(), "AUtogain endpoint": tecan_endpoint_rows(), "Sheet1": [],
    })
    with pytest.raises(ValueError, match="Multiple Tecan.*--sheet"):
        association.parse_plate_reader(path)
    with pytest.raises(ValueError, match="not a Tecan measurement sheet"):
        association.parse_plate_reader(path, sheet_name="Sheet1")
    dataframe = association.parse_plate_reader(path, sheet_name="AUtogain endpoint")
    assert len(dataframe) == 4
    assert dataframe.attrs["gain"] == 108


@pytest.mark.parametrize("layout", ["kinetic", "endpoint"])
@pytest.mark.parametrize("bad_value, message", [("OVER", "Over-range.*lower-gain"), (None, "Missing or nonnumeric"), ("NaN", "Non-finite"), ("=1+2", "Missing or nonnumeric"), ("#VALUE!", "Missing or nonnumeric")])
def test_invalid_measurements_fail_with_well_context(tmp_path, layout, bad_value, message):
    rows = tecan_kinetic_rows() if layout == "kinetic" else tecan_endpoint_rows()
    rows[9 if layout == "kinetic" else 8][1] = bad_value
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {"test": rows})
    with pytest.raises(ValueError, match=message) as failure:
        association.parse_plate_reader(path)
    assert "well A1" in str(failure.value)


@pytest.mark.parametrize("change, message", [
    (lambda r: r[7].__setitem__(2, 0), "duplicate times"),
    (lambda r: r[7].__setitem__(2, -1), "nonnegative and strictly increasing"),
    (lambda r: r[7].__setitem__(2, 5000), "nonnegative and strictly increasing"),
    (lambda r: r[7].__setitem__(2, None), "blank time/plate-column headers"),
    (lambda r: r[8].__setitem__(0, "unknown"), "temperature row"),
    (lambda r: r[10].__setitem__(0, "A1"), "Duplicate Tecan"),
    (lambda r: r[10].__setitem__(0, "Q1"), "Unexpected Tecan"),
    (lambda r: r[9].append(500), "without a time"),
    (lambda r: r[3].__setitem__(4, 485.5), "integer nanometers"),
    (lambda r: r[2].__setitem__(4, "Absorbance"), "expected fluorescence"),
    (lambda r: r[5].__setitem__(4, -1), "gain must be nonnegative"),
    (lambda r: r.append(["Time [s]", 0]), "exactly one kinetic table"),
])
def test_malformed_kinetic_tables_fail_instead_of_misassigning_data(tmp_path, change, message):
    rows = tecan_kinetic_rows()
    change(rows)
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {"test": rows})
    with pytest.raises(ValueError, match=message):
        association.parse_plate_reader(path)


@pytest.mark.parametrize("columns", [[1, 1], [0, 25], [1.5, 2]])
def test_invalid_endpoint_columns_are_rejected(tmp_path, columns):
    rows = tecan_endpoint_rows()
    rows[7] = ["<>", *columns]
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {"endpoint": rows})
    with pytest.raises(ValueError, match="duplicate times/plate columns|integers from 1 to 24"):
        association.parse_plate_reader(path)


@pytest.mark.parametrize("endpoint", [False, True])
def test_xlsx_discovery_and_cli_merge_preserve_the_key_contract(tmp_path, endpoint):
    rows = tecan_endpoint_rows() if endpoint else tecan_kinetic_rows()
    sheet = "endpoint" if endpoint else "gain 100 actual data"
    path = write_tecan_workbook(tmp_path / "reader.xlsx", {sheet: rows, "Sheet1": []})
    key = tmp_path / "concentration_key.csv"
    key.write_text("Well ID,DNA_nM,Water_--\nA1,5,1\nA2,5,1\n", encoding="utf-8")
    assert association.discover_plate_file(tmp_path) == path
    assert association.main([str(tmp_path), "--sheet", sheet]) == 0
    output = tmp_path / association.default_output_path(path, sheet).name
    assert output.exists()
    dataframe, filtered, summary = association.build_merged_tidy_data(path, key, sheet_name=sheet)
    assert filtered.dropped_timepoints == []
    assert summary.keyed_wells == ["A1", "A2"]
    assert summary.unkeyed_measured_wells == (["B1", "B2"] if endpoint else [])
    assert "Water_--" not in dataframe.columns
    assert dataframe.attrs["source_sheet"] == sheet


def test_sheet_output_names_cannot_collide_or_escape_directories():
    assert worksheet_output_token("a b") != worksheet_output_token("a_b")
    assert "/" not in worksheet_output_token("../../a")


def test_analysis_cli_can_build_fresh_input_without_the_new_optional_sheet_argument(tmp_path):
    from tools.data_analysis.analyze_plate_reader import build_merged_tidy_csv

    write_tecan_workbook(tmp_path / "reader.xlsx")
    (tmp_path / "concentration_key.csv").write_text("Well ID,DNA_nM\nA1,5\nA2,5\n", encoding="utf-8")
    assert build_merged_tidy_csv(tmp_path).exists()


def test_invalid_workbook_and_non_workbook_sheet_selection_are_rejected(tmp_path):
    path = tmp_path / "invalid.xlsx"
    path.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read Tecan XLSX"):
        association.parse_plate_reader(path)
    assert not association.is_plate_reader_export_candidate(path)
    with pytest.raises(ValueError, match="only supported for Tecan"):
        association.parse_plate_reader(tmp_path / "reader.txt", sheet_name="sheet")
