import json

import pytest

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as mod


def _accepted_frame(
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    *,
    volume_nl: float,
    width_px: float,
):
    return online_cal_mod.build_online_stream_frame_row(
        phase="flow_rate",
        status="accepted",
        delay_us=delay_us,
        delay_from_emergence_us=delay_from_emergence_us,
        replicate_index=replicate_index,
        qc={"measurement_qc_pass": True},
        image_ref={"capture_id": f"cap_{delay_us}_{replicate_index}"},
        warnings=[],
        attached_width_px=width_px,
        visible_volume_nl=volume_nl,
        attached_bottom_clearance_px=150,
        min_accepted_fluid_distance_from_bottom_px=150,
        accepted_component_count=1,
        accepted_detached_component_count=0,
        detached_near_bottom_warning=False,
        attached_bottom_guard_hit=False,
    )


def _accepted_measurement(
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    *,
    volume_nl: float,
    width_px: float,
):
    return online_cal_mod.build_online_stream_measurement_row(
        phase="flow_rate",
        delay_us=delay_us,
        delay_from_emergence_us=delay_from_emergence_us,
        replicate_index=replicate_index,
        width_px=width_px,
        visible_volume_nl=volume_nl,
        qc_pass=True,
        image_ref={"capture_id": f"cap_{delay_us}_{replicate_index}"},
    )


def _delay_block(
    delay_us: int,
    delay_from_emergence_us: int,
    volumes: list[float],
    widths: list[float] | None = None,
):
    widths = list(widths or [74.0 for _ in volumes])
    frame_rows = []
    measurements = []
    for replicate_index, (volume_nl, width_px) in enumerate(zip(volumes, widths), start=1):
        frame_rows.append(
            _accepted_frame(
                delay_us,
                delay_from_emergence_us,
                replicate_index,
                volume_nl=volume_nl,
                width_px=width_px,
            )
        )
        measurements.append(
            _accepted_measurement(
                delay_us,
                delay_from_emergence_us,
                replicate_index,
                volume_nl=volume_nl,
                width_px=width_px,
            )
        )
    return measurements, online_cal_mod.summarize_online_stream_flow_delay(frame_rows)


def _delay_schedule(count: int, *, start_us: int = 650, step_us: int = 200) -> list[int]:
    return [start_us + (offset * step_us) for offset in range(count)]


def _flow_dataset_from_blocks(blocks: list[tuple[int, list[float], list[float] | None]]):
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volumes, widths in blocks:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            volumes,
            widths,
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)
    return measurements, delay_summaries


def test_fit_online_stream_flow_phase_returns_expected_rate_above_minimum_delay_count():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(13):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append(
            (
                delay_from_emergence_us,
                [volume_nl, volume_nl + 0.1, volume_nl - 0.1],
                None,
            )
        )
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "ok"
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.02, rel=0.02)
    assert result["flow_fit_point_count"] == 13
    assert result["steady_width_baseline_px"] == 74.0


def test_fit_online_stream_flow_phase_uses_per_delay_medians_at_minimum_delay_count():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(12):
        volume_nl = 0.05 * delay_from_emergence_us
        volumes = [volume_nl]
        if delay_from_emergence_us == 850:
            volumes = [volume_nl, volume_nl + 180.0, volume_nl]
        blocks.append((delay_from_emergence_us, volumes, [74.0 for _ in volumes]))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "warning_min_points_only"
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.05, rel=0.05)


def test_fit_online_stream_flow_phase_warns_when_only_twelve_delays_are_available():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(12):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "warning_min_points_only"
    assert result["flow_fit_point_count"] == 12
    assert "flow_fit_min_points_only" in result["warnings"]


def test_fit_online_stream_flow_phase_returns_unresolved_for_eleven_delays():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(11):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "unresolved_insufficient_delays"
    assert result["accepted_delay_point_count"] == 11
    assert result["flow_rate_nl_per_us"] is None
    assert "insufficient_accepted_delays" in result["warnings"]


def test_fit_online_stream_flow_phase_prunes_one_isolated_interior_outlier():
    blocks = []
    outlier_delay_from_emergence_us = _delay_schedule(13)[6]
    for delay_from_emergence_us in _delay_schedule(13):
        volume_nl = (0.02 * delay_from_emergence_us) - 1.0
        if delay_from_emergence_us == outlier_delay_from_emergence_us:
            volume_nl += 18.0
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "warning_min_points_only"
    assert result["flow_fit_outlier_prune_status"] == "dropped_isolated_point"
    assert result["flow_fit_dropped_outlier_delay_from_emergence_us"] == outlier_delay_from_emergence_us
    assert result["flow_fit_point_count"] == 12
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.02, rel=0.05)
    assert "flow_fit_outlier_pruned" in result["warnings"]


def test_fit_online_stream_flow_phase_does_not_prune_endpoint_outlier():
    blocks = []
    schedule = _delay_schedule(13)
    for delay_from_emergence_us in schedule:
        volume_nl = (0.02 * delay_from_emergence_us) - 1.0
        if delay_from_emergence_us == schedule[0]:
            volume_nl += 18.0
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["flow_fit_outlier_prune_status"] != "dropped_isolated_point"
    assert result["flow_fit_point_count"] == 13


def test_fit_online_stream_flow_phase_width_baseline_uses_all_measurements():
    blocks = []
    widths = [70.0, 71.0, 72.0, 73.0, 74.0, 75.0, 77.0, 78.0, 79.0, 80.0, 81.0, 82.0]
    for delay_from_emergence_us, width_px in zip(_delay_schedule(12), widths):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append((delay_from_emergence_us, [volume_nl], [width_px]))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["steady_width_baseline_px"] == 76.0


def test_fit_online_stream_flow_phase_is_json_serializable():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(12):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    encoded = json.dumps(
        mod.fit_online_stream_flow_phase(
            measurements=measurements,
            delay_summaries=delay_summaries,
        )
    )

    assert isinstance(encoded, str)
    assert "warning_min_points_only" in encoded


def test_fit_online_stream_flow_phase_applies_conservative_settling_aware_late12_rule():
    blocks = []
    delays = _delay_schedule(15, step_us=100)
    volumes = [
        12.0,
        14.0,
        16.0,
        18.0,
        20.0,
        22.0,
        22.7,
        23.4,
        24.1,
        24.8,
        28.0,
        31.2,
        34.4,
        37.6,
        40.8,
    ]
    for delay_from_emergence_us, volume_nl in zip(delays, volumes):
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    default_result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )
    disabled_result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
        quality_policy={"settling_aware_fit_enabled": False},
    )

    assert default_result["settling_aware_fit_enabled"] is True
    assert default_result["settling_aware_fit_applied"] is True
    assert default_result["settling_aware_fit_rule_name"] == "conservative_frontloaded_late12"
    assert default_result["flow_fit_point_count"] == 12
    assert default_result["flow_fit_delay_start_from_emergence_us"] == 950
    assert default_result["flow_rate_nl_per_us"] > disabled_result["flow_rate_nl_per_us"]
    assert default_result["settling_aware_fit_early_vs_late_pct"] > 2.0
    assert default_result["settling_aware_fit_mid_dev"] < 0.0
    assert "flow_fit_settling_aware_late12_applied" in default_result["warnings"]

    assert disabled_result["settling_aware_fit_enabled"] is False
    assert disabled_result["settling_aware_fit_applied"] is False
    assert disabled_result["flow_fit_point_count"] == 14


def test_fit_online_stream_flow_phase_leaves_linear_trace_on_global_fit_when_rule_enabled():
    blocks = []
    for delay_from_emergence_us in _delay_schedule(13):
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        blocks.append((delay_from_emergence_us, [volume_nl], None))
    measurements, delay_summaries = _flow_dataset_from_blocks(blocks)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["settling_aware_fit_enabled"] is True
    assert result["settling_aware_fit_applied"] is False
    assert result["flow_fit_point_count"] == 13
