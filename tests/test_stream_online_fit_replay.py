import csv
import importlib
import sys
from pathlib import Path

import pytest

from tools.stream_analysis import online_fit as online_fit_mod
from tests.stream_online_replay_helpers import build_adaptive_flow_replay_inputs
from tests.stream_online_replay_helpers import to_float as _to_float
from tests.stream_online_replay_helpers import to_int as _to_int


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Stream_characterization-20260327_225650"
)
SUMMARY_CSV = EXPERIMENT_ROOT / "analysis" / "stream_characterization" / "experiment_summary.csv"


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))

def _build_sparse_replay_inputs(run_id: str):
    phase_features_path = (
        EXPERIMENT_ROOT
        / "analysis"
        / "stream_characterization"
        / "runs"
        / run_id
        / "stage_05_fit"
        / "phase_features.csv"
    )
    if not phase_features_path.exists():
        return None

    rows_by_delay = {}
    for row in _read_csv_rows(phase_features_path):
        delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if delay_from_emergence_us is not None and delay_from_emergence_us not in rows_by_delay:
            rows_by_delay[delay_from_emergence_us] = row

    return build_adaptive_flow_replay_inputs(
        rows_by_delay,
        fit_module=online_fit_mod,
        capture_id_prefix=run_id,
    )


def test_sparse_online_flow_fit_replay_matches_dense_offline_rates():
    if not SUMMARY_CSV.exists():
        pytest.skip("Archived stream-analysis experiment summary is not available.")

    for module_name in ("scipy", "scipy.optimize", "scipy.signal", "scipy.stats", "scipy.ndimage"):
        sys.modules.pop(module_name, None)
    pytest.importorskip("scipy.stats")
    fit_module = importlib.reload(online_fit_mod)
    errors = []
    for row in _read_csv_rows(SUMMARY_CSV):
        if str(row.get("analysis_source_mode") or "") != "raw":
            continue
        if str(row.get("steady_fit_status") or "") != "ok":
            continue
        gold_rate = _to_float(row.get("steady_rate_nl_per_us"))
        run_id = str(row.get("run_id") or "").strip()
        if not run_id or gold_rate in (None, 0.0):
            continue
        replay_inputs = _build_sparse_replay_inputs(run_id)
        if replay_inputs is None:
            continue
        measurements, delay_summaries = replay_inputs
        result = fit_module.fit_online_stream_flow_phase(
            measurements=measurements,
            delay_summaries=delay_summaries,
        )
        fitted_rate = _to_float(result.get("flow_rate_nl_per_us"))
        if fitted_rate is None:
            continue
        errors.append(abs(float(fitted_rate) - float(gold_rate)) / abs(float(gold_rate)))

    assert len(errors) >= 10
    sorted_errors = sorted(float(value) for value in errors)
    median_error = sorted_errors[len(sorted_errors) // 2]
    worst_error = max(sorted_errors)

    assert median_error <= 0.02
    assert worst_error <= 0.05
