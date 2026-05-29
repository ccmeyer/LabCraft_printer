import pytest

import RegulatorProfiles as rp
from RegulatorSweepBuilder import (
    MAX_SWEEP_CANDIDATES,
    RegulatorSweepError,
    prepare_regulator_sweep,
    sweepable_field_choices,
    write_sweep_artifacts,
)


def _config(**overrides):
    config = {
        "mode": "stream",
        "baseline_profile_id": "stream_default",
        "trace_case_id": 2102,
        "mutated_channel": "print",
        "calibrated_head_confirmed": True,
        "sweep_strategy": "one_at_a_time",
        "sweep_fields": [
            {"field_path": "recovery.active_ticks", "values": "3,4"},
            {"field_path": "slew.max_hz_delta_up_per_loop", "values": [800]},
        ],
    }
    config.update(overrides)
    return config


def test_sweepable_field_choices_are_bounded_integer_fields():
    choices = sweepable_field_choices()

    paths = {choice["field_path"] for choice in choices}
    assert "recovery.active_ticks" in paths
    assert "slew.max_hz_delta_up_per_loop" in paths
    assert "ready.ready_tol_raw" in paths
    assert not any("allow_extend" in path for path in paths)


def test_one_at_a_time_sweep_generates_valid_session_scoped_profiles(tmp_path):
    prepared = prepare_regulator_sweep(
        _config(operator="operator"),
        profile_document=rp.factory_default_document(),
    )

    assert prepared.candidate_profile_ids == [
        "stream_default_sweep_001",
        "stream_default_sweep_002",
        "stream_default_sweep_003",
    ]
    assert prepared.manifest["strategy"] == "one_at_a_time"
    assert prepared.manifest["mutated_channel"] == "print"
    first = prepared.candidate_profiles["stream_default_sweep_001"]
    assert first["source"]["kind"] == "calibration_candidate"
    assert first["source"]["operator"] == "operator"
    assert first["print"]["recovery"]["active_ticks"] == 3
    assert first["print"]["slew"]["max_hz_delta_up_per_loop"] == 600
    assert prepared.profile_document["active_profiles"]["stream"] == "stream_default"
    assert "stream_default_sweep_001" in prepared.profile_document["profiles"]

    sweep_block = write_sweep_artifacts(prepared, tmp_path)
    assert (tmp_path / "sweep_manifest.json").exists()
    assert (tmp_path / "sweep_profiles.json").exists()
    assert sweep_block["generated_profile_count"] == 3
    assert sweep_block["sweep_manifest_json"] == "sweep_manifest.json"


def test_grid_sweep_is_deterministic_and_limited():
    prepared = prepare_regulator_sweep(
        _config(
            sweep_strategy="grid",
            sweep_fields=[
                {"field_path": "recovery.active_ticks", "values": [3, 4]},
                {"field_path": "slew.max_hz_delta_up_per_loop", "values": [800, 900]},
            ],
        ),
        profile_document=rp.factory_default_document(),
    )

    assert prepared.candidate_profile_ids == [
        "stream_default_sweep_001",
        "stream_default_sweep_002",
        "stream_default_sweep_003",
        "stream_default_sweep_004",
    ]
    assert prepared.candidate_changes[0]["changes"] == [
        {
            "channel": "print",
            "field_path": "recovery.active_ticks",
            "baseline_value": 2,
            "value": 3,
        },
        {
            "channel": "print",
            "field_path": "slew.max_hz_delta_up_per_loop",
            "baseline_value": 600,
            "value": 800,
        },
    ]

    with pytest.raises(RegulatorSweepError, match=f"1 to {MAX_SWEEP_CANDIDATES}"):
        prepare_regulator_sweep(
            _config(
                sweep_strategy="grid",
                sweep_fields=[
                    {"field_path": "recovery.active_ticks", "values": [3, 4, 5, 6]},
                    {"field_path": "slew.max_hz_delta_up_per_loop", "values": [800, 900, 1000, 1100]},
                ],
            ),
            profile_document=rp.factory_default_document(),
        )


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"calibrated_head_confirmed": False}, "calibrated printer head"),
        ({"baseline_profile_id": "missing"}, "does not exist"),
        ({"mode": "droplet"}, "mode does not match"),
        ({"trace_case_id": 2103}, "mutated_channel"),
        ({"sweep_fields": [{"field_path": "source.kind", "values": [1]}]}, "not sweepable"),
        ({"sweep_fields": [{"field_path": "recovery.active_ticks", "values": ["bad"]}]}, "integers"),
        ({"sweep_fields": [{"field_path": "recovery.active_ticks", "values": [99]}]}, "outside"),
        ({"sweep_fields": [{"field_path": "recovery.active_ticks", "values": [2]}]}, "matches the baseline"),
        (
            {
                "sweep_fields": [
                    {"field_path": "recovery.active_ticks", "values": [3]},
                    {"field_path": "recovery.active_ticks", "values": [4]},
                ]
            },
            "duplicate sweep field",
        ),
    ],
)
def test_invalid_sweep_configs_fail_closed(overrides, match):
    with pytest.raises(RegulatorSweepError, match=match):
        prepare_regulator_sweep(
            _config(**overrides),
            profile_document=rp.factory_default_document(),
        )


def test_custom_trace_requires_matching_sweep_channel():
    config = _config(
        trace_case_id=2110,
        trace_channel="refuel",
        trace_pressure_psi=0.8,
        trace_pulse_us=3000,
        trace_pulse_count=5,
        trace_frequency_hz=20,
        mutated_channel="print",
    )

    with pytest.raises(RegulatorSweepError, match="mutated_channel"):
        prepare_regulator_sweep(config, profile_document=rp.factory_default_document())
