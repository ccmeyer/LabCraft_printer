from __future__ import annotations

import json

import pandas as pd
import pytest

from tools.data_analysis.analysis_settings import (
    expand_well_ranges, load_settings, normalize_settings, save_settings, settings_from_design,
)
from tools.data_analysis import plate_reader_analysis as analysis


def measurement_rows(*, endpoint=False):
    rows = []
    for well, mm, dna, signal in (("A1", .994, 1.242, 10), ("A2", .997, 1.245, 12), ("N1", .996, 1.244, 10000)):
        for channel in ("485_535", "560_585"):
            for time in ([0] if endpoint else [0, 300]):
                rows.append({"well": well, "time": "00:00:00" if not time else "00:05:00", "time_seconds": time,
                             "time_minutes": time / 60, "temperature_c": 37., "is_keyed": True,
                             "fluorophore": channel, "rfu": signal + time / 300,
                             "MM_mM": mm, "DNA_nM": dna})
    return pd.DataFrame(rows)


def reviewed_settings():
    return normalize_settings({"nominal_targets": {"MM_mM": [1], "DNA_nM": [1.25]},
                               "excluded_wells": {"N1": "Reagent missing; head ran out"}})


@pytest.mark.parametrize("endpoint", [False, True])
def test_nominal_grouping_and_exclusions_precede_all_statistics_without_mutating_sources(endpoint):
    raw = measurement_rows(endpoint=endpoint)
    original = raw.copy(deep=True)
    prepared, columns, review, audit = analysis.prepare_reviewed_analysis_dataframe(raw, reviewed_settings())
    pd.testing.assert_frame_equal(raw, original)
    assert set(prepared.well) == {"A1", "A2"}
    assert prepared.condition_id.nunique() == 1
    assert analysis.varying_condition_columns(prepared, columns) == []
    assert review["included_keyed_well_count"] == 2
    assert review["replicate_counts"][0]["included_replicates"] == 2
    excluded = audit.set_index("well").loc["N1"]
    assert excluded.is_manually_excluded
    assert excluded.calculated_MM_mM == .996
    assert excluded.analysis_MM_mM == 1
    assert "ran out" in excluded.exclusion_reason
    endpoint_frame = analysis.compute_endpoint_by_well(prepared, columns, endpoint_last_n=1)
    assert set(endpoint_frame.well) == {"A1", "A2"}
    assert endpoint_frame.condition_endpoint_n.eq(2).all()
    assert endpoint_frame.condition_endpoint_mean_rfu.eq(11 if endpoint else 12).all()
    assert not endpoint_frame.is_endpoint_outlier.any()


@pytest.mark.parametrize("value, levels, message", [
    (.8, [1], "No intended level"),
    (1., [.99, 1.01], "Ambiguous intended levels"),
    (float("nan"), [1], "Missing or non-finite"),
    (.001, [0], "No intended level"),
])
def test_unmatched_ambiguous_missing_and_nonzero_control_values_are_blocking(value, levels, message):
    raw = measurement_rows()
    raw["MM_mM"] = value
    settings = normalize_settings({"nominal_targets": {"MM_mM": levels}})
    with pytest.raises(ValueError, match=message):
        analysis.prepare_reviewed_analysis_dataframe(raw, settings)


def test_unknown_targets_and_unknown_excluded_wells_are_not_silently_ignored():
    with pytest.raises(ValueError, match="do not match concentration-key"):
        analysis.prepare_reviewed_analysis_dataframe(measurement_rows(), {"nominal_targets": {"typo": [1]}})
    with pytest.raises(ValueError, match="no measurements: N2"):
        analysis.prepare_reviewed_analysis_dataframe(measurement_rows(), {"excluded_wells": {"N2": "missing"}})
    with pytest.raises(ValueError, match="no keyed measured wells"):
        analysis.prepare_reviewed_analysis_dataframe(measurement_rows(), {"excluded_wells": {w: "missing" for w in ("A1", "A2", "N1")}})


def test_zero_replicate_conditions_remain_visible_in_review():
    raw = measurement_rows()
    raw.loc[raw.well == "N1", "DNA_nM"] = 5
    prepared, _, review, _ = analysis.prepare_reviewed_analysis_dataframe(raw, {"excluded_wells": {"N1": "missing"}})
    assert "N1" not in set(prepared.well)
    assert len(review["conditions_without_usable_wells"]) == 1
    assert any(row["included_replicates"] == 0 for row in review["replicate_counts"])


def test_rectangular_well_selection_is_bounded_and_explicit():
    assert len(expand_well_ranges("N1:P4")) == 12
    assert expand_well_ranges("n1:n4, O1:O4; P1:P4") == expand_well_ranges("N1:P4")
    assert expand_well_ranges("A1 A1 A2") == ["A1", "A2"]
    for text in ("N0:P4", "N1:P25", "P4:N1", "N-P", "A1:Q1"):
        with pytest.raises(ValueError):
            expand_well_ranges(text)


def test_settings_roundtrip_and_failed_replacement_preserve_original(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    settings = reviewed_settings()
    save_settings(path, settings)
    assert load_settings(path) == settings
    before = path.read_bytes()
    def fail_replace(*_args):
        raise OSError("disk unavailable")
    monkeypatch.setattr("tools.data_analysis.analysis_settings.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        save_settings(path, normalize_settings())
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_unknown_schema_is_retained_and_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version":"future_version"}')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        save_settings(path, reviewed_settings())
    assert path.read_bytes() == before


@pytest.mark.parametrize("text", ["null", "[]", "true"])
def test_non_object_saved_settings_are_not_treated_as_defaults(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="JSON object"):
        load_settings(path)
    with pytest.raises(ValueError, match="JSON object"):
        save_settings(path, reviewed_settings())
    assert path.read_text() == text


def test_load_design_records_declared_levels_and_source_hash(tmp_path):
    path = tmp_path / "experiment_design.json"
    path.write_text(json.dumps({"factors": [
        {"kind": "additive", "options": [{"name": "MM", "units": "mM", "targets": [1]}]},
        {"kind": "choice", "options": [{"name": "DNA", "units": "nM", "targets": [1.25, 2.5, 5]}]},
    ]}))
    settings = settings_from_design(path)
    assert settings["nominal_targets"] == {"MM_mM": [1], "DNA_nM": [1.25, 2.5, 5]}
    assert len(settings["target_source"]["sha256"]) == 64
    assert settings["target_source"]["file"] == str(path.resolve())


@pytest.mark.parametrize("raw", [
    {"nominal_targets": {"DNA": [1, 1]}}, {"nominal_targets": {"DNA": [float("inf")]}},
    {"target_tolerance_percent": -1}, {"target_tolerance_percent": float("nan")},
    {"excluded_wells": {"N1": ""}}, {"excluded_wells": {"Q1": "missing"}},
])
def test_invalid_settings_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_settings(raw)


@pytest.mark.analysis_pipeline
@pytest.mark.parametrize("endpoint", [False, True])
def test_full_report_retains_raw_exclusions_settings_and_correct_replicate_counts(tmp_path, endpoint):
    raw = measurement_rows(endpoint=endpoint)
    merged = tmp_path / "merged.csv"
    raw.to_csv(merged, index=False)
    result = analysis.analyze_merged_tidy_csv(merged, tmp_path / "analysis", analysis_settings=reviewed_settings())
    assert pd.read_csv(result.composition_summary_csv).replicate_count.eq(2).all()
    assert set(pd.read_csv(result.endpoint_csv).well) == {"A1", "A2"}
    pd.testing.assert_frame_equal(pd.read_csv(merged), pd.read_csv(result.output_dir / "raw_measurements.csv"))
    assert set(pd.read_csv(result.output_dir / "manual_exclusions.csv").well) == {"N1"}
    assert (result.output_dir / "manually_excluded_wells.png").exists()
    manifest = json.loads(result.manifest_json.read_text())
    assert manifest["analysis_review"]["excluded_well_count"] == 1
    assert load_settings(result.output_dir / "analysis_settings.json") == reviewed_settings()
    report = result.report_html.read_text()
    assert "Reagent missing; head ran out" in report
    assert "Calculated concentration range" in report
    assert "Included replicates" in report
