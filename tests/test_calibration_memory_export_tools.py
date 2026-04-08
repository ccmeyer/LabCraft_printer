import csv
import json
from pathlib import Path

from CalibrationMemoryStore import CalibrationMemoryStore
from tools import calibration_memory_analysis as cma


def _make_context(
    *,
    reagent_id="water",
    stock_id="Water_0.00_--",
    stock_display_name="Water",
    reagent_display_name="Water",
    reagent_family="aqueous",
    printer_head_id="nozzle_100um_h01",
    printer_head_display_name="100 um H01",
    head_type_id="nozzle_100um",
    head_type_display_name="100 um",
    nominal_nozzle_diameter_um=100.0,
    identity_quality=None,
):
    return {
        "reagent_id": reagent_id,
        "reagent_display_name": reagent_display_name,
        "reagent_family": reagent_family,
        "stock_id": stock_id,
        "stock_display_name": stock_display_name,
        "stock_concentration": "0.00",
        "stock_units": "--",
        "printer_head_id": printer_head_id,
        "printer_head_display_name": printer_head_display_name,
        "head_type_id": head_type_id,
        "head_type_display_name": head_type_display_name,
        "nominal_nozzle_diameter_um": nominal_nozzle_diameter_um,
        "nozzle_diameter_um": nominal_nozzle_diameter_um,
        "profile_name": "test-profile",
        "experiment_dir": "C:/tmp/experiment",
        "calibration_file_path": "C:/tmp/experiment/calibration.json",
        "identity_quality": identity_quality
        or {
            "stock_id": "explicit",
            "reagent_id": "explicit",
            "printer_head_id": "explicit",
            "head_type_id": "explicit",
            "nominal_nozzle_diameter_um": "explicit",
            "nozzle_diameter_um": "explicit",
        },
    }


def _write_summary_run(
    store,
    *,
    run_id,
    context,
    started_at,
    ended_at,
    pressure,
    pulse_width_us,
    mean_volume,
    cv_pct,
    ui_recommendation=None,
):
    paths = store.create_run(run_id, context=context, notes=f"notes-{run_id}")
    summary = {
        "context": context,
        "run_status": "completed" if ended_at else "in_progress",
        "run_timing": {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
        },
        "notes": f"notes-{run_id}",
        "phase_counts": {
            "droplet_search": 1,
            "pressure_scan": 1,
        },
        "process_results": {
            "droplet_search": {
                "step_count": 1,
                "latest_settings": {"print_width": pulse_width_us, "print_pressure": pressure},
                "latest_result": {
                    "pressure": pressure,
                    "mean_volume": mean_volume,
                    "cv_volume_percent": cv_pct,
                    "valid": True,
                    "print_pulse_width_us": pulse_width_us,
                    "delay_us": 4300,
                },
            },
            "pressure_scan": {
                "step_count": 1,
                "latest_settings": {"print_width": pulse_width_us},
                "latest_result": {
                    "pulse_width_us": pulse_width_us,
                    "primary_band": [pressure - 0.1, pressure + 0.1],
                    "delay_us": 4300,
                },
            },
        },
        "artifact_refs": {
            "camera_capture_root": "C:/tmp/captures",
            "camera_active_save_dir": f"C:/tmp/captures/{run_id}",
            "calibration_json_path": "C:/tmp/experiment/calibration.json",
        },
        "source_refs": paths,
        "authoritative_refs": {
            "calibration_json_path": "C:/tmp/experiment/calibration.json",
        },
        "prior_application_mode": "advisory",
        "prior_lookup_performed": True,
        "prior_candidate_found": True,
        "prior_qualified": True,
        "prior_applied": False,
        "prior_candidate": {
            "aggregation_level": "exact_pair",
            "pulse_width_us": pulse_width_us,
            "recommended_pressure_psi": pressure,
            "expected_mean_volume_nL": mean_volume,
            "expected_cv_pct": cv_pct,
            "contributing_runs": 2,
            "source_run_ids": ["seed-a", "seed-b"],
            "recommendation_confidence_adjusted": 0.88,
            "pulse_match_type": "exact",
            "match_type": "exact",
        },
        "prior_seed_values": {
            "start_pressure_psi": pressure,
            "seed_source": "recommended_pressure_psi",
            "seed_single_droplet_band_psi": [pressure - 0.1, pressure + 0.1],
            "seed_expected_mean_volume_nL": mean_volume,
            "seed_expected_cv_pct": cv_pct,
            "seed_pulse_width_us": pulse_width_us,
        },
        "prior_usefulness_summary": {
            "usefulness_signal": "inconclusive",
            "steps_until_first_single": 2,
            "first_single_pressure_psi": pressure,
            "first_single_seed_error_psi": 0.0,
            "seed_inside_actual_single_band": True,
            "actual_vs_prior_pressure_error_psi": 0.0,
            "actual_vs_prior_volume_error_nL": 0.0,
        },
        "ui_recommendation": ui_recommendation or {},
        "last_updated_at_utc": ended_at or started_at,
    }
    summary["derived_metrics"] = store.aggregator.extract_run_features(summary)
    store.write_run_summary(run_id, summary)
    return paths


def _append_observation(store, run_id, context, *, ts_utc, phase, observation_type, payload):
    store.append_observation(
        run_id,
        {
            "ts_utc": ts_utc,
            "phase": phase,
            "observation_type": observation_type,
            "context": context,
            "settings": {
                "print_width": 1500,
                "print_pressure": 1.6,
                "flash_delay": 4300,
                "flash_duration": 1000,
                "num_droplets": 1,
                "exposure_time": 30000,
                "current_position": {"X": 1, "Y": 2, "Z": 3},
            },
            "machine": {"position": {"X": 1, "Y": 2, "Z": 3}},
            "payload": payload,
            "artifact_refs": {"camera_active_save_dir": f"C:/tmp/captures/{run_id}"},
        },
    )


def test_run_summary_export_flattens_rows_and_orders_deterministically(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    context_a = _make_context(printer_head_id="nozzle_100um_h01")
    context_b = _make_context(
        reagent_id="glycerol_25pct",
        stock_id="Gly25_0.25_v1",
        stock_display_name="25% glycerol",
        reagent_display_name="25% glycerol",
        printer_head_id="nozzle_120um_h02",
        printer_head_display_name="120 um H02",
        head_type_id="nozzle_120um",
        head_type_display_name="120 um",
        nominal_nozzle_diameter_um=120.0,
    )

    _write_summary_run(
        store,
        run_id="run_b",
        context=context_b,
        started_at="2026-03-07T10:02:00Z",
        ended_at="2026-03-07T10:05:00Z",
        pressure=1.85,
        pulse_width_us=1700,
        mean_volume=12.2,
        cv_pct=5.4,
    )
    _write_summary_run(
        store,
        run_id="run_a",
        context=context_a,
        started_at="2026-03-07T10:00:00Z",
        ended_at="2026-03-07T10:04:00Z",
        pressure=1.60,
        pulse_width_us=1500,
        mean_volume=9.9,
        cv_pct=4.2,
        ui_recommendation={
            "shown": True,
            "shown_count": 1,
            "applied": True,
            "apply_count": 1,
            "aggregation_level": "exact_pair",
            "confidence": 0.88,
            "manual_apply_allowed": True,
            "manual_apply_reason": "qualified",
            "target_pulse_width_us": 1500,
            "target_volume_nl": 10.0,
        },
    )

    rows, errors = cma.build_run_summary_export_rows(store.root_dir)

    assert errors == []
    assert [row["run_id"] for row in rows] == ["run_a", "run_b"]
    assert rows[0]["recommended_pressure_psi"] == 1.6
    assert rows[0]["expected_mean_volume_nL"] == 9.9
    assert rows[0]["ui_recommendation_applied"] is True
    assert rows[1]["reagent_id"] == "glycerol_25pct"

    export_path = tmp_path / "summaries.csv"
    result = cma.export_run_summaries_csv(store.root_dir, export_path)
    assert result["row_count"] == 2
    with export_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        csv_rows = list(reader)
    assert reader.fieldnames == cma.RUN_SUMMARY_COLUMNS
    assert [row["run_id"] for row in csv_rows] == ["run_a", "run_b"]


def test_observation_export_flattens_rows_and_applies_filters(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    context = _make_context()
    _write_summary_run(
        store,
        run_id="run_obs",
        context=context,
        started_at="2026-03-07T10:00:00Z",
        ended_at="2026-03-07T10:04:00Z",
        pressure=1.61,
        pulse_width_us=1500,
        mean_volume=10.0,
        cv_pct=4.1,
    )
    _append_observation(
        store,
        "run_obs",
        context,
        ts_utc="2026-03-07T10:00:30Z",
        phase="droplet_search",
        observation_type="process_analysis",
        payload={"kind": "characterization_frame", "mean_volume": 10.0, "cv_volume_percent": 4.1, "valid": True},
    )
    _append_observation(
        store,
        "run_obs",
        context,
        ts_utc="2026-03-07T10:00:40Z",
        phase="calibration_memory",
        observation_type="ui_recommendation_applied",
        payload={
            "action": "applied",
            "prior": {"aggregation_level": "exact_pair", "pulse_width_us": 1500, "recommendation_confidence_adjusted": 0.88},
            "extra": {"seeded_start_pressure_psi": 1.61, "seeded_pulse_width_us": 1500},
        },
    )

    rows, errors = cma.build_observation_export_rows(
        store.root_dir,
        observation_types=["process_analysis"],
        phases=["droplet_search"],
        completed_only=True,
    )

    assert errors == []
    assert len(rows) == 1
    row = rows[0]
    assert row["observation_type"] == "process_analysis"
    assert row["payload_kind"] == "characterization_frame"
    assert row["payload_mean_volume_nL"] == 10.0
    assert row["payload_cv_pct"] == 4.1
    assert row["reagent_id"] == "water"

    export_path = tmp_path / "observations.csv"
    result = cma.export_observations_csv(
        store.root_dir,
        export_path,
        observation_types=["ui_recommendation_applied"],
    )
    assert result["row_count"] == 1
    with export_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        csv_rows = list(reader)
    assert csv_rows[0]["payload_action"] == "applied"
    assert csv_rows[0]["payload_aggregation_level"] == "exact_pair"


def test_export_handles_missing_optional_fields_and_legacy_identity(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    legacy_context = _make_context(
        reagent_id="water",
        printer_head_id=None,
        head_type_id="nozzle_100um",
        printer_head_display_name=None,
        identity_quality={
            "stock_id": "explicit",
            "reagent_id": "derived",
            "printer_head_id": "unknown",
            "head_type_id": "derived",
        },
    )
    paths = store.create_run("legacy_run", context=legacy_context, notes="legacy")
    summary = {
        "context": legacy_context,
        "run_status": "completed",
        "run_timing": {
            "started_at_utc": "2026-03-07T11:00:00Z",
            "ended_at_utc": "2026-03-07T11:05:00Z",
        },
        "notes": "legacy",
        "phase_counts": {},
        "process_results": {},
        "artifact_refs": {},
        "source_refs": paths,
        "authoritative_refs": {},
        "last_updated_at_utc": "2026-03-07T11:05:00Z",
    }
    store.write_run_summary("legacy_run", summary)

    rows, errors = cma.build_run_summary_export_rows(store.root_dir)

    assert errors == []
    legacy_row = next(row for row in rows if row["run_id"] == "legacy_run")
    assert legacy_row["printer_head_id"] is None
    assert legacy_row["pulse_width_us"] is None
    assert legacy_row["prior_candidate_confidence"] is None
    assert legacy_row["identity_quality_printer_head_id"] == "unknown"


def test_run_summary_export_includes_online_stream_fields(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    context = _make_context()
    paths = store.create_run("stream_run", context=context, notes="online stream")
    summary = {
        "context": context,
        "run_status": "completed",
        "run_timing": {
            "started_at_utc": "2026-04-01T09:00:00Z",
            "ended_at_utc": "2026-04-01T09:05:00Z",
        },
        "notes": "online stream",
        "phase_counts": {"online_stream_calibration": 1},
        "process_results": {
            "online_stream_calibration": {
                "step_count": 1,
                "latest_settings": {"print_width": 1500, "print_pressure": 1.61},
                "latest_result": {
                    "condition": {
                        "print_pressure_psi": 1.61,
                        "print_pulse_width_us": 1500,
                        "emergence_time_us": 3200,
                    },
                    "priors": {
                        "source": "calibration_memory",
                        "condition_match": "exact",
                        "aggregation_level": "exact_pair",
                        "applied_flow_start_offset_us": 700,
                        "applied_tail_start_offset_us": 3950,
                    },
                    "flow_phase": {
                        "status": "captured",
                        "plan": {
                            "delay_offsets_from_emergence_us": [
                                700,
                                757,
                                814,
                                871,
                                928,
                                985,
                                1042,
                                1099,
                                1156,
                                1213,
                                1270,
                                1327,
                                1384,
                                1441,
                                1498,
                            ],
                            "point_count": 15,
                        },
                        "fit_status": "ok",
                        "flow_rate_nl_per_us": 0.0187,
                        "flow_fit_delay_start_from_emergence_us": 700,
                    },
                    "tail_phase": {
                        "status": "captured",
                        "plan": {"coarse_start_offset_us": 3950, "coarse_step_us": 100},
                        "tail_start_delay_from_emergence_us": 3950,
                    },
                    "predicted_stream_duration_us": 3950,
                    "predicted_volume_nl": 72.6,
                },
            }
        },
        "artifact_refs": {},
        "source_refs": paths,
        "authoritative_refs": {},
        "online_stream_prior_candidate_found": True,
        "online_stream_prior_fallback_reason": None,
        "online_stream_prior_applied_prior": {
            "source": "calibration_memory",
            "condition_match": "exact",
            "aggregation_level": "exact_pair",
        },
        "last_updated_at_utc": "2026-04-01T09:05:00Z",
    }
    summary["derived_metrics"] = store.aggregator.extract_run_features(summary)
    store.write_run_summary("stream_run", summary)

    rows, errors = cma.build_run_summary_export_rows(store.root_dir)

    assert errors == []
    row = next(item for item in rows if item["run_id"] == "stream_run")
    assert row["online_stream_flow_rate_nl_per_us"] == 0.0187
    assert row["online_stream_flow_fit_status"] == "ok"
    assert row["online_stream_tail_status"] == "captured"
    assert row["online_stream_tail_start_delay_from_emergence_us"] == 3950
    assert row["online_stream_predicted_volume_nl"] == 72.6
    assert row["online_stream_print_pressure_psi"] == 1.61
    assert row["online_stream_prior_source"] == "calibration_memory"
    assert row["online_stream_prior_aggregation_level"] == "exact_pair"
    assert row["online_stream_prior_candidate_found"] is True


def test_trend_tables_and_audit_report_stay_deterministic(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    water_context = _make_context()
    glycerol_context = _make_context(
        reagent_id="glycerol_50pct",
        stock_id="Gly50_0.50_v1",
        stock_display_name="50% glycerol",
        reagent_display_name="50% glycerol",
        reagent_family="aqueous",
        printer_head_id="nozzle_80um_h03",
        printer_head_display_name="80 um H03",
        head_type_id="nozzle_80um",
        head_type_display_name="80 um",
        nominal_nozzle_diameter_um=80.0,
    )

    _write_summary_run(
        store,
        run_id="trend_a",
        context=water_context,
        started_at="2026-03-07T12:00:00Z",
        ended_at="2026-03-07T12:05:00Z",
        pressure=1.58,
        pulse_width_us=1500,
        mean_volume=9.8,
        cv_pct=4.0,
    )
    _write_summary_run(
        store,
        run_id="trend_b",
        context=glycerol_context,
        started_at="2026-03-07T12:10:00Z",
        ended_at="2026-03-07T12:15:00Z",
        pressure=2.02,
        pulse_width_us=1700,
        mean_volume=12.8,
        cv_pct=5.8,
    )
    _append_observation(
        store,
        "trend_a",
        water_context,
        ts_utc="2026-03-07T12:01:00Z",
        phase="droplet_search",
        observation_type="process_event",
        payload={"reason": "seeded_start"},
    )

    trend_result = cma.write_trend_tables(store.root_dir, out_dir=tmp_path / "plots", reagent_ids=["water", "glycerol_50pct"])
    assert trend_result["table_row_counts"]["volume_vs_pressure"] == 2
    assert Path(trend_result["table_paths"]["volume_vs_pressure"]).exists()

    audit = cma.build_dataset_audit(store.root_dir)
    assert audit["counts"]["run_summaries"] == 2
    assert audit["observation_type_counts"]["process_event"] == 1
    assert audit["derived_snapshot_counts"]["recommendation_index"] is not None
    assert audit["derived_snapshot_counts"]["recommendation_index"] >= 2
    assert audit["dataset_readiness"]["exact_pair_analysis"]["sufficient"] is False

    rendered = cma.render_dataset_audit_markdown(audit)
    assert "Calibration Memory Dataset Audit" in rendered
    assert "Exact-pair analysis" in rendered
