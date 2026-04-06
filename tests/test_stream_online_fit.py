import json

import pytest

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as mod


def _accepted_frame(delay_us: int, delay_from_emergence_us: int, replicate_index: int, *, volume_nl: float, width_px: float):
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


def _accepted_measurement(delay_us: int, delay_from_emergence_us: int, replicate_index: int, *, volume_nl: float, width_px: float):
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


def _delay_block(delay_us: int, delay_from_emergence_us: int, volumes: list[float], widths: list[float] | None = None):
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


def test_fit_online_stream_flow_phase_returns_expected_rate_for_linear_sparse_schedule():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us in [650, 850, 1050, 1250, 1450]:
        delay_us = 3200 + delay_from_emergence_us
        volume_nl = (0.02 * delay_from_emergence_us) + 1.5
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl, volume_nl + 0.1, volume_nl - 0.1],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "ok"
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.02, rel=0.02)
    assert result["flow_fit_point_count"] == 5
    assert result["steady_width_baseline_px"] == 74.0


def test_fit_online_stream_flow_phase_uses_per_delay_medians_not_raw_measurement_weighting():
    measurements = []
    delay_summaries = []
    blocks = [
        (3850, 650, [10.0], [74.0]),
        (4050, 850, [20.0, 200.0, 20.0], [74.0, 74.0, 74.0]),
        (4250, 1050, [30.0], [74.0]),
    ]
    for delay_us, delay_from_emergence_us, volumes, widths in blocks:
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            volumes,
            widths,
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "warning_min_points_only"
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.05, rel=0.05)


def test_fit_online_stream_flow_phase_warns_when_only_three_delays_are_available():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volume_nl in [(650, 12.0), (850, 16.0), (1050, 20.0)]:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "warning_min_points_only"
    assert "flow_fit_min_points_only" in result["warnings"]


def test_fit_online_stream_flow_phase_returns_unresolved_for_fewer_than_three_delays():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volume_nl in [(650, 12.0), (850, 16.0)]:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["fit_status"] == "unresolved_insufficient_delays"
    assert result["flow_rate_nl_per_us"] is None
    assert "insufficient_accepted_delays" in result["warnings"]


def test_fit_online_stream_flow_phase_prunes_one_isolated_interior_outlier():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volume_nl in [
        (650, 12.0),
        (850, 16.0),
        (1050, 40.0),
        (1250, 24.0),
        (1450, 28.0),
    ]:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["flow_fit_outlier_prune_status"] == "dropped_isolated_point"
    assert result["flow_fit_dropped_outlier_delay_from_emergence_us"] == 1050
    assert result["flow_rate_nl_per_us"] == pytest.approx(0.02, rel=0.05)
    assert "flow_fit_outlier_pruned" in result["warnings"]


def test_fit_online_stream_flow_phase_does_not_prune_endpoint_outlier():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volume_nl in [
        (650, 45.0),
        (850, 16.0),
        (1050, 20.0),
        (1250, 24.0),
        (1450, 28.0),
    ]:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["flow_fit_outlier_prune_status"] != "dropped_isolated_point"
    assert result["flow_fit_point_count"] == 5


def test_fit_online_stream_flow_phase_width_baseline_uses_all_measurements():
    measurements = []
    delay_summaries = []
    blocks = [
        (3850, 650, [12.0, 12.1], [70.0, 74.0]),
        (4050, 850, [16.0, 16.1], [76.0, 78.0]),
        (4250, 1050, [20.0], [80.0]),
    ]
    for delay_us, delay_from_emergence_us, volumes, widths in blocks:
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            volumes,
            widths,
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    result = mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )

    assert result["steady_width_baseline_px"] == 76.0


def test_fit_online_stream_flow_phase_is_json_serializable():
    measurements = []
    delay_summaries = []
    for delay_from_emergence_us, volume_nl in [(650, 12.0), (850, 16.0), (1050, 20.0)]:
        delay_us = 3200 + delay_from_emergence_us
        block_measurements, delay_summary = _delay_block(
            delay_us,
            delay_from_emergence_us,
            [volume_nl],
        )
        measurements.extend(block_measurements)
        delay_summaries.append(delay_summary)

    encoded = json.dumps(
        mod.fit_online_stream_flow_phase(
            measurements=measurements,
            delay_summaries=delay_summaries,
        )
    )

    assert isinstance(encoded, str)
    assert "warning_min_points_only" in encoded
