import json
from pathlib import Path

import pytest

from CalibrationMemoryAggregator import CalibrationMemoryAggregator
from CalibrationMemoryStore import CalibrationMemoryStore


def _make_context(
    *,
    reagent_id="water",
    reagent_family="aqueous",
    stock_id="Water_0.00_--",
    printer_head_id="nozzle_100um_h01",
    head_type_id="nozzle_100um",
    nominal_nozzle_diameter_um=100.0,
    identity_quality=None,
    reagent_display_name="Water",
):
    return {
        "reagent_id": reagent_id,
        "reagent_display_name": reagent_display_name,
        "reagent_family": reagent_family,
        "stock_id": stock_id,
        "printer_head_id": printer_head_id,
        "head_type_id": head_type_id,
        "nominal_nozzle_diameter_um": nominal_nozzle_diameter_um,
        "nozzle_diameter_um": nominal_nozzle_diameter_um,
        "identity_quality": identity_quality
        or {
            "reagent_id": "explicit",
            "stock_id": "explicit" if stock_id else "unknown",
            "printer_head_id": "explicit" if printer_head_id and not str(printer_head_id).startswith("gripper_slot_") else "inferred",
            "head_type_id": "explicit" if head_type_id else "unknown",
            "nominal_nozzle_diameter_um": "explicit" if nominal_nozzle_diameter_um is not None else "unknown",
        },
        "identity_sources": {},
        "profile_name": "test-profile",
        "experiment_dir": "C:/tmp/exp",
        "calibration_file_path": "C:/tmp/exp/calibration.json",
    }


def _phase_result(result, *, settings=None, timestamp="2026-03-06T18:05:00Z"):
    entry = {
        "step_count": 1,
        "latest_timestamp": timestamp,
        "latest_settings": dict(settings or {}),
        "latest_meta": {},
    }
    if result is not None:
        entry["latest_result"] = dict(result)
    return entry


def _seed_completed_run(
    store,
    tmp_path,
    run_id,
    context,
    *,
    droplet_search=None,
    pressure_scan=None,
    pressure_trajectory=None,
    pressure_sweep_summary=None,
    authoritative_steps=None,
    ended_at="2026-03-06T18:10:00Z",
):
    paths = store.create_run(run_id, context=context, notes="seeded")
    process_results = {}
    phase_counts = {}
    if droplet_search is not None:
        process_results["droplet_search"] = _phase_result(
            droplet_search,
            settings={"print_width": droplet_search.get("print_pulse_width_us"), "print_pressure": droplet_search.get("pressure")},
        )
        phase_counts["droplet_search"] = 1
    if pressure_scan is not None:
        process_results["pressure_scan"] = _phase_result(
            pressure_scan,
            settings={"print_width": pressure_scan.get("pulse_width_us")},
        )
        phase_counts["pressure_scan"] = 1
    if pressure_trajectory is not None:
        process_results["pressure_trajectory"] = _phase_result(
            pressure_trajectory,
            settings={"print_width": droplet_search.get("print_pulse_width_us") if droplet_search else None},
        )
        phase_counts["pressure_trajectory"] = 1
    if pressure_sweep_summary is not None:
        process_results["pressure_sweep_characterization"] = _phase_result(
            pressure_sweep_summary,
            settings={"print_width": pressure_sweep_summary.get("print_pulse_width_us", 1500)},
        )
        phase_counts["pressure_sweep_characterization"] = 1

    authoritative_refs = {}
    if authoritative_steps is not None:
        calibration_path = tmp_path / f"{run_id}_calibration.json"
        calibration_payload = {
            "schema_version": 1,
            "runs": [
                {
                    "run_id": run_id,
                    "steps": authoritative_steps,
                }
            ],
        }
        calibration_path.write_text(json.dumps(calibration_payload), encoding="utf-8")
        authoritative_refs = {
            "calibration_json_path": str(calibration_path),
            "calibration_run_id": run_id,
            "calibration_run_index": 0,
        }

    store.write_run_summary(
        run_id,
        {
            "context": context,
            "run_status": "completed",
            "run_timing": {
                "started_at_utc": "2026-03-06T18:00:00Z",
                "ended_at_utc": ended_at,
            },
            "notes": "seeded",
            "phase_counts": phase_counts,
            "process_results": process_results,
            "artifact_refs": {},
            "source_refs": paths,
            "authoritative_refs": authoritative_refs,
            "last_updated_at_utc": ended_at,
        },
    )


def test_aggregator_builds_exact_pair_memory_and_selects_nearest_pulse(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    context = _make_context()

    _seed_completed_run(
        store,
        tmp_path,
        "run_a",
        context,
        droplet_search={
            "pressure": 1.60,
            "mean_volume": 9.9,
            "cv_volume_percent": 4.2,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4300,
        },
        pressure_scan={
            "pulse_width_us": 1500,
            "primary_band": [1.45, 1.75],
            "delay_us": 4300,
        },
        pressure_trajectory={
            "trajectory_pressure_band": [1.50, 1.70],
            "emergence_time_us": 4300,
        },
        ended_at="2026-03-06T18:10:00Z",
    )
    _seed_completed_run(
        store,
        tmp_path,
        "run_b",
        context,
        droplet_search={
            "pressure": 1.64,
            "mean_volume": 10.0,
            "cv_volume_percent": 4.0,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4310,
        },
        pressure_scan={
            "pulse_width_us": 1500,
            "primary_band": [1.46, 1.76],
            "delay_us": 4310,
        },
        pressure_trajectory={
            "trajectory_pressure_band": [1.51, 1.69],
            "emergence_time_us": 4310,
        },
        ended_at="2026-03-06T18:11:00Z",
    )
    _seed_completed_run(
        store,
        tmp_path,
        "run_c",
        context,
        droplet_search={
            "pressure": 1.72,
            "mean_volume": 10.5,
            "cv_volume_percent": 4.8,
            "valid": True,
            "print_pulse_width_us": 1700,
            "delay_us": 4400,
        },
        pressure_scan={
            "pulse_width_us": 1700,
            "primary_band": [1.58, 1.84],
            "delay_us": 4400,
        },
        pressure_trajectory={
            "trajectory_pressure_band": [1.60, 1.80],
            "emergence_time_us": 4400,
        },
        ended_at="2026-03-06T18:12:00Z",
    )

    result = store.refresh_derived_memory()
    assert result["entry_counts"]["pair_memory"] == 1

    pair_memory = json.loads(Path(result["pair_memory_path"]).read_text(encoding="utf-8"))
    entry = pair_memory["entries"][0]
    assert entry["entry_key"] == "water::nozzle_100um_h01"
    assert sorted(entry["per_pulse_width"].keys()) == ["1500", "1700"]
    assert entry["per_pulse_width"]["1500"]["recommended_pressure_psi"] == pytest.approx(1.62)

    exact_prior = store.get_best_prior(context, target_pulse_width_us=1500)
    assert exact_prior["aggregation_level"] == CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR
    assert exact_prior["match_type"] == "exact"
    assert exact_prior["pulse_match_type"] == "exact"
    assert exact_prior["recommended_pressure_psi"] == pytest.approx(1.62)

    nearest_prior = store.get_best_prior(context, target_pulse_width_us=1600)
    assert nearest_prior["aggregation_level"] == CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR
    assert nearest_prior["match_type"] == "near_exact"
    assert nearest_prior["pulse_match_type"] == "nearest"
    assert nearest_prior["pulse_width_us"] == 1500


def test_exact_pair_requires_explicit_identity_and_grouped_fallback_works(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    grouped_context = _make_context(
        printer_head_id="gripper_slot_2",
        identity_quality={
            "reagent_id": "explicit",
            "stock_id": "explicit",
            "printer_head_id": "inferred",
            "head_type_id": "explicit",
            "nominal_nozzle_diameter_um": "explicit",
        },
    )
    query_context = _make_context(printer_head_id="nozzle_100um_h04")

    _seed_completed_run(
        store,
        tmp_path,
        "grouped_run",
        grouped_context,
        droplet_search={
            "pressure": 1.58,
            "mean_volume": 10.2,
            "cv_volume_percent": 5.1,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4320,
        },
        pressure_scan={
            "pulse_width_us": 1500,
            "primary_band": [1.44, 1.72],
            "delay_us": 4320,
        },
    )

    result = store.refresh_derived_memory()
    pair_memory = json.loads(Path(result["pair_memory_path"]).read_text(encoding="utf-8"))
    assert pair_memory["entry_count"] == 0

    prior = store.get_best_prior(query_context, target_pulse_width_us=1500)
    assert prior["aggregation_level"] == CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE
    assert prior["match_type"] == "grouped"
    assert prior["recommended_pressure_psi"] == pytest.approx(1.58)


def test_backward_compatible_legacy_identity_can_feed_lower_confidence_grouping(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    legacy_context = {
        "reagent_id": "water",
        "display_name": "Water",
        "reagent_family": "aqueous",
        "head_type_id": "nozzle_100um",
        "nozzle_diameter_um": 100.0,
        "identity_quality": {
            "reagent_id": "derived",
            "printer_head_id": "missing",
            "head_type_id": "derived",
        },
    }
    query_context = _make_context(
        reagent_id="glycerol_25pct",
        reagent_family="aqueous_glycerol",
        stock_id="Gly25_0.25",
        printer_head_id="nozzle_100um_h05",
    )
    authoritative_steps = {
        "pressure_sweep_characterization": [
            {
                "timestamp": "2026-03-06T18:20:00Z",
                "settings": {"print_width": 1500},
                "result": {
                    "pressures": [
                        {
                            "pressure": 1.40,
                            "mean_volume": 9.5,
                            "cv_volume_percent": 6.0,
                            "valid": True,
                        },
                        {
                            "pressure": 1.60,
                            "mean_volume": 10.1,
                            "cv_volume_percent": 5.5,
                            "valid": True,
                        },
                    ],
                    "sphere_delay_us": 4350,
                },
            }
        ]
    }

    _seed_completed_run(
        store,
        tmp_path,
        "legacy_run",
        legacy_context,
        pressure_sweep_summary={"pressures": []},
        authoritative_steps=authoritative_steps,
        ended_at="2026-03-06T18:21:00Z",
    )

    result = store.refresh_derived_memory()
    pair_memory = json.loads(Path(result["pair_memory_path"]).read_text(encoding="utf-8"))
    head_type_memory = json.loads(Path(result["head_type_memory_path"]).read_text(encoding="utf-8"))

    assert pair_memory["entry_count"] == 0
    assert head_type_memory["entry_count"] == 1
    bucket = head_type_memory["entries"][0]["per_pulse_width"]["1500"]
    assert bucket["recommended_pressure_psi"] == pytest.approx(1.60)
    assert bucket["identity_quality_summary"]["head_type_id"]["inferred"] == 1

    prior = store.get_best_prior(query_context, target_pulse_width_us=1500)
    assert prior["aggregation_level"] == CalibrationMemoryAggregator.AGGREGATION_LEVEL_HEAD_TYPE_ONLY
    assert prior["match_type"] == "weak_fallback"


def test_rebuild_is_deterministic_and_exact_pair_confidence_beats_head_type_only(tmp_path):
    store = CalibrationMemoryStore(root_dir=str(tmp_path / "CalibrationMemory"))
    exact_context = _make_context(printer_head_id="nozzle_100um_h02")
    weak_context = _make_context(
        reagent_id="glycerol_50pct",
        reagent_family="aqueous_glycerol",
        stock_id="Gly50_0.50",
        printer_head_id="gripper_slot_4",
        identity_quality={
            "reagent_id": "inferred",
            "stock_id": "explicit",
            "printer_head_id": "inferred",
            "head_type_id": "explicit",
            "nominal_nozzle_diameter_um": "explicit",
        },
    )

    _seed_completed_run(
        store,
        tmp_path,
        "exact_1",
        exact_context,
        droplet_search={
            "pressure": 1.63,
            "mean_volume": 10.0,
            "cv_volume_percent": 3.8,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4300,
        },
        pressure_scan={"pulse_width_us": 1500, "primary_band": [1.49, 1.75], "delay_us": 4300},
        ended_at="2026-03-06T18:10:00Z",
    )
    _seed_completed_run(
        store,
        tmp_path,
        "exact_2",
        exact_context,
        droplet_search={
            "pressure": 1.61,
            "mean_volume": 10.1,
            "cv_volume_percent": 4.1,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4310,
        },
        pressure_scan={"pulse_width_us": 1500, "primary_band": [1.48, 1.74], "delay_us": 4310},
        ended_at="2026-03-06T18:11:00Z",
    )
    _seed_completed_run(
        store,
        tmp_path,
        "weak_1",
        weak_context,
        droplet_search={
            "pressure": 1.70,
            "mean_volume": 10.8,
            "cv_volume_percent": 7.5,
            "valid": True,
            "print_pulse_width_us": 1500,
            "delay_us": 4400,
        },
        ended_at="2026-03-06T18:12:00Z",
    )

    result_a = store.refresh_derived_memory()
    pair_memory_a = Path(result_a["pair_memory_path"]).read_text(encoding="utf-8")
    head_type_memory_a = Path(result_a["head_type_memory_path"]).read_text(encoding="utf-8")
    recommendation_index_a = Path(result_a["recommendation_index_path"]).read_text(encoding="utf-8")

    result_b = store.refresh_derived_memory()
    assert Path(result_b["pair_memory_path"]).read_text(encoding="utf-8") == pair_memory_a
    assert Path(result_b["head_type_memory_path"]).read_text(encoding="utf-8") == head_type_memory_a
    assert Path(result_b["recommendation_index_path"]).read_text(encoding="utf-8") == recommendation_index_a

    pair_memory = json.loads(pair_memory_a)
    head_type_memory = json.loads(head_type_memory_a)
    pair_confidence = pair_memory["entries"][0]["per_pulse_width"]["1500"]["recommendation_confidence"]
    head_type_confidence = head_type_memory["entries"][0]["per_pulse_width"]["1500"]["recommendation_confidence"]
    assert pair_confidence > head_type_confidence
