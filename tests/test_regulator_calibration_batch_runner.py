from datetime import datetime, timezone

import pytest

import RegulatorProfiles as rp
from RegulatorCalibrationRunner import (
    RegulatorCalibrationBatchError,
    batch_run_configs,
    prepare_regulator_calibration_batch,
    write_batch_manifest,
)


def _now():
    return datetime(2026, 5, 29, 20, 0, 0, tzinfo=timezone.utc)


def _ids():
    values = iter(["sess", "r1", "r2", "r3", "r4", "r5", "r6", "r7"])
    return lambda: next(values)


def _document():
    document = rp.factory_default_document()
    stream = document["profiles"]["stream_default"]
    for profile_id in ("stream_candidate_a", "stream_candidate_b"):
        candidate = rp.validate_profile({**stream, "profile_id": profile_id, "description": profile_id})
        document["profiles"][profile_id] = candidate
    return rp.validate_document(document)


def _config(**overrides):
    config = {
        "mode": "stream",
        "trace_case_id": 2102,
        "candidate_profile_ids": ["stream_candidate_a", "stream_candidate_b"],
        "repeat_count": 2,
        "order_strategy": "alternating",
        "operator": "operator",
        "printer_head_id": "head-1",
        "printer_head_type": "stream-head",
        "reagent_id": "water",
        "calibrated_head_confirmed": True,
    }
    config.update(overrides)
    return config


def test_prepare_batch_manifest_with_baselines_and_alternating_repeats(tmp_path):
    prepared = prepare_regulator_calibration_batch(
        _config(),
        profile_document=_document(),
        output_root=tmp_path,
        now_fn=_now,
        id_factory=_ids(),
    )

    assert prepared.session_id == "session_20260529_200000_sess"
    assert prepared.manifest_path.exists()
    assert prepared.serial_handoff_mode == "soft"
    assert prepared.manifest["serial_handoff_mode"] == "soft"
    assert [run["role"] for run in prepared.runs] == [
        "baseline_before",
        "candidate",
        "candidate",
        "candidate",
        "candidate",
        "baseline_after",
    ]
    assert [run["profile_id"] for run in prepared.runs] == [
        "stream_default",
        "stream_candidate_a",
        "stream_candidate_b",
        "stream_candidate_a",
        "stream_candidate_b",
        "stream_default",
    ]
    assert [run["repeat_index"] for run in prepared.runs] == [0, 1, 1, 2, 2, 0]

    configs = batch_run_configs(prepared)
    assert configs[0]["profile_id"] == "stream_default"
    assert configs[0]["session_id"] == prepared.session_id
    assert configs[0]["_batch_run"] is True
    assert configs[0]["serial_handoff_mode"] == "soft"
    assert configs[1]["batch_role"] == "candidate"

    fallback = prepare_regulator_calibration_batch(
        _config(repeat_count=1, serial_handoff_mode="full_disconnect"),
        profile_document=_document(),
        output_root=tmp_path / "fallback",
        now_fn=_now,
        id_factory=_ids(),
    )
    assert fallback.serial_handoff_mode == "full_disconnect"
    assert fallback.manifest["serial_handoff_mode"] == "full_disconnect"
    assert batch_run_configs(fallback)[0]["serial_handoff_mode"] == "full_disconnect"


def test_grouped_and_seeded_randomized_ordering_are_deterministic(tmp_path):
    grouped = prepare_regulator_calibration_batch(
        _config(order_strategy="grouped", baseline_before=False, baseline_after=False),
        profile_document=_document(),
        output_root=tmp_path / "grouped",
        now_fn=_now,
        id_factory=_ids(),
    )
    assert [(run["profile_id"], run["repeat_index"]) for run in grouped.runs] == [
        ("stream_candidate_a", 1),
        ("stream_candidate_a", 2),
        ("stream_candidate_b", 1),
        ("stream_candidate_b", 2),
    ]

    first = prepare_regulator_calibration_batch(
        _config(order_strategy="randomized", random_seed=42, baseline_before=False, baseline_after=False),
        profile_document=_document(),
        output_root=tmp_path / "random_a",
        now_fn=_now,
        id_factory=_ids(),
    )
    second = prepare_regulator_calibration_batch(
        _config(order_strategy="randomized", random_seed=42, baseline_before=False, baseline_after=False),
        profile_document=_document(),
        output_root=tmp_path / "random_b",
        now_fn=_now,
        id_factory=_ids(),
    )
    assert [(run["profile_id"], run["repeat_index"]) for run in first.runs] == [
        (run["profile_id"], run["repeat_index"]) for run in second.runs
    ]
    assert first.random_seed == 42


def test_prepare_batch_with_shared_custom_trace_recipe(tmp_path):
    prepared = prepare_regulator_calibration_batch(
        _config(
            trace_case_id=2110,
            trace_channel="print",
            trace_pressure_psi=1.2,
            trace_pulse_us=1500,
            trace_pulse_count=12,
            trace_frequency_hz=20,
            repeat_count=1,
        ),
        profile_document=_document(),
        output_root=tmp_path,
        now_fn=_now,
        id_factory=_ids(),
    )

    assert prepared.trace_case.custom is True
    assert prepared.manifest["trace_case_id"] == 2110
    assert prepared.manifest["conditions"]["trace_recipe"] == "custom"
    assert prepared.manifest["conditions"]["pressure_mpsi"] == 1200
    configs = batch_run_configs(prepared)
    assert all(config["trace_case_id"] == 2110 for config in configs)
    assert all(config["trace_pressure_mpsi"] == 1200 for config in configs)
    assert all(config["trace_pulse_us"] == 1500 for config in configs)


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"calibrated_head_confirmed": False}, "calibrated printer head"),
        ({"candidate_profile_ids": ["missing"]}, "does not exist"),
        ({"candidate_profile_ids": ["droplet_default"]}, "does not match batch mode"),
        ({"trace_case_id": 9999}, "trace_case_id"),
        ({"repeat_count": 0}, "between 1 and 5"),
        ({"order_strategy": "unknown"}, "order_strategy"),
        ({"candidate_profile_ids": []}, "1 to 12"),
        ({"serial_handoff_mode": "unsupported"}, "serial_handoff_mode"),
    ],
)
def test_prepare_batch_rejects_invalid_configs(tmp_path, overrides, match):
    with pytest.raises(RegulatorCalibrationBatchError, match=match):
        prepare_regulator_calibration_batch(
            _config(**overrides),
            profile_document=_document(),
            output_root=tmp_path,
            now_fn=_now,
            id_factory=_ids(),
        )


def test_prepare_batch_rejects_too_many_total_runs(tmp_path):
    document = _document()
    stream = document["profiles"]["stream_default"]
    candidates = []
    for idx in range(12):
        profile_id = f"stream_candidate_{idx}"
        candidate = rp.validate_profile({**stream, "profile_id": profile_id, "description": profile_id})
        document["profiles"][profile_id] = candidate
        candidates.append(profile_id)
    document = rp.validate_document(document)

    with pytest.raises(RegulatorCalibrationBatchError, match="no more than 50"):
        prepare_regulator_calibration_batch(
            _config(candidate_profile_ids=candidates, repeat_count=5),
            profile_document=document,
            output_root=tmp_path,
            now_fn=_now,
        )


def test_write_batch_manifest_preserves_runs_and_records_analysis(tmp_path):
    prepared = prepare_regulator_calibration_batch(
        _config(repeat_count=1),
        profile_document=_document(),
        output_root=tmp_path,
        now_fn=_now,
        id_factory=_ids(),
    )
    runs = list(prepared.runs)
    runs[0] = dict(runs[0], status="completed")

    manifest = write_batch_manifest(
        prepared,
        runs=runs,
        analysis={"candidate_ranking_csv": "analysis/candidate_ranking.csv"},
        status="completed",
    )

    assert manifest["runs"][0]["status"] == "completed"
    assert manifest["analysis"]["candidate_ranking_csv"] == "analysis/candidate_ranking.csv"
    assert manifest["outcome"]["status"] == "completed"
