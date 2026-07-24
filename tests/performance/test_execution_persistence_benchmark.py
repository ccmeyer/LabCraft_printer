import json
import builtins
import io
import os
import time
from pathlib import Path

import pytest

from tools import characterize_execution_persistence as benchmark
from tools.virtual_workflows.report import validate_report_v1


pytestmark = pytest.mark.virtual_workflow


def _spec(*, wells=4, stocks=1, workload_id="execution_persistence_slice2_test"):
    return benchmark.WorkloadSpec(
        plate_name="shallow-384_well_plate",
        plate_rows=16,
        plate_columns=24,
        well_ids=tuple(f"A{index}" for index in range(1, wells + 1)),
        stock_count=stocks,
        workload_id=workload_id,
    )


def _synthetic_result(values, run_index):
    values = list(values)
    count = len(values)
    return {
        "duration_ms": sum(values),
        "process_cpu_ms": sum(values) / 2,
        "samples_ms": {
            phase: list(values) if phase == "well_total" else [1.0] * count
            for phase in benchmark.PHASE_NAMES
        },
        "phase_statistics_ms": {
            phase: benchmark._distribution(
                list(values) if phase == "well_total" else [1.0] * count
            )
            for phase in benchmark.PHASE_NAMES
        },
        "quartile_growth": benchmark._quartile_growth(values),
        "file_size_samples_bytes": {
            "progress.json": [100 + index for index in range(count + 1)],
            "execution_resume.json": [
                200 + (index * 10) for index in range(count + 1)
            ],
        },
        "resume_checkpoint_samples": {
            "size_bytes_by_phase": {
                "after_begin": [600] * count,
                "after_attach": [610] * count,
                "after_complete": [500] * count,
            },
            "retained_intents_by_phase": {
                "after_begin": [1] * count,
                "after_attach": [1] * count,
                "after_complete": [0] * count,
            },
        },
        "durable_io_samples_ms": {
            "fsync": {"write_progress": [1.0] * count},
            "atomic_replace": {"write_progress": [0.5] * count},
        },
        "validation": {
            "checkpoint_state": "clean",
            "intent_count": count,
            "observed_completed_intent_count": count,
            "checkpoint_retained_intent_count": 0,
            "checkpoint_pending_intent_count": 0,
            "checkpoint_max_observed_intent_count": 1,
            "authoritative_bundle_valid": True,
            "targets_match_progress": True,
            "file_sizes_bytes": {
                "progress.json": 100 + count,
                "execution_resume.json": 200 + (count * 10),
            },
        },
        "run_index": run_index,
    }


@pytest.mark.parametrize("stock_count", [1, 2])
def test_reduced_workloads_capture_real_durable_io_and_file_growth(
    tmp_path,
    stock_count,
):
    spec = _spec(stocks=stock_count)
    original_fsync = os.fsync
    original_replace = os.replace
    original_builtin_open = builtins.open
    original_io_open = io.open

    result = benchmark._execute_workload(spec, tmp_path / f"experiment-{stock_count}")

    assert os.fsync is original_fsync
    assert os.replace is original_replace
    assert builtins.open is original_builtin_open
    assert io.open is original_io_open
    assert result["validation"]["checkpoint_state"] == "clean"
    assert result["validation"]["intent_count"] == spec.completion_count
    assert result["validation"]["observed_completed_intent_count"] == (
        spec.completion_count
    )
    assert result["validation"]["checkpoint_retained_intent_count"] == 0
    assert result["validation"]["checkpoint_pending_intent_count"] == 0
    assert result["validation"]["checkpoint_max_observed_intent_count"] == 1
    assert result["validation"]["authoritative_bundle_valid"] is True
    assert result["validation"]["targets_match_progress"] is True

    for phase in benchmark.PHASE_NAMES:
        assert len(result["samples_ms"][phase]) == spec.completion_count

    for name, samples in result["file_size_samples_bytes"].items():
        assert len(samples) == spec.completion_count + 1
        assert samples[-1] == result["validation"]["file_sizes_bytes"][name]
    assert len(set(result["file_size_samples_bytes"]["execution_resume.json"])) == 1

    checkpoint_samples = result["resume_checkpoint_samples"]
    assert checkpoint_samples["retained_intents_by_phase"] == {
        "after_begin": [1] * spec.completion_count,
        "after_attach": [1] * spec.completion_count,
        "after_complete": [0] * spec.completion_count,
    }
    assert max(checkpoint_samples["size_bytes_by_phase"]["after_begin"]) > (
        checkpoint_samples["size_bytes_by_phase"]["after_complete"][-1]
    )

    durable_io = result["durable_io_samples_ms"]
    for operation in ("fsync", "atomic_replace"):
        total_calls = sum(
            len(samples) for samples in durable_io[operation].values()
        )
        assert total_calls == spec.completion_count * 4
        assert set(durable_io[operation]) == {
            "attach_sequence",
            "begin_intent",
            "complete_intent",
            "write_progress",
        }
    assert result["authoritative_read_opens"] == {
        "by_phase": {},
        "by_path": {},
        "total_count": 0,
        "observer_restored": True,
    }
    snapshot = result["progress_snapshot"]
    assert snapshot["mode_counts"] == {
        "full_rebuild": 0,
        "cached_update": spec.completion_count,
    }
    assert len(snapshot["duration_samples_ms"]["serialization"]) == (
        spec.completion_count
    )
    assert len(snapshot["duration_samples_ms"]["atomic_write"]) == (
        spec.completion_count
    )
    assert len(snapshot["serialized_size_bytes"]) == spec.completion_count
    assert len(snapshot["non_durable_write_samples_ms"]) == (
        spec.completion_count
    )
    assert snapshot["observer_restored"] is True


def test_io_observer_restores_original_functions_after_failure():
    observer = benchmark.PersistenceIoObserver()
    original_fsync = os.fsync
    original_replace = os.replace
    original_builtin_open = builtins.open
    original_io_open = io.open

    with pytest.raises(RuntimeError, match="injected observer failure"):
        with observer.installed():
            raise RuntimeError("injected observer failure")

    assert os.fsync is original_fsync
    assert os.replace is original_replace
    assert builtins.open is original_builtin_open
    assert io.open is original_io_open


def test_io_observer_attributes_real_reads_within_selected_root(tmp_path):
    observed_path = tmp_path / "execution_resume.json"
    observed_path.write_text('{"ok": true}\n', encoding="utf-8")
    outside_path = Path(__file__)
    observer = benchmark.PersistenceIoObserver(tmp_path)

    with observer.installed(), observer.phase("checkpoint_read"):
        assert json.loads(observed_path.read_text(encoding="utf-8")) == {"ok": True}
        outside_path.read_text(encoding="utf-8")

    snapshot = observer.read_snapshot()
    assert snapshot["total_count"] == 1
    assert snapshot["by_path"] == {
        "execution_resume.json": {
            "count": 1,
            "observed_file_size_bytes": observed_path.stat().st_size,
        }
    }
    assert snapshot["by_phase"]["checkpoint_read"] == snapshot["by_path"]
    assert snapshot["observer_restored"] is True


def test_quartile_growth_is_computed_within_each_run():
    first = _synthetic_result([1, 1, 2, 2, 2, 2, 4, 4], 1)
    second = _synthetic_result([10, 10, 12, 12, 12, 12, 20, 20], 2)

    values = benchmark._aggregate_metrics([first, second], _spec(wells=8))[
        "persistence"
    ]["values"]

    rows = values["well_total_growth_by_run"]
    assert [row["last_to_first_mean_ratio"] for row in rows] == [4.0, 2.0]
    assert [row["last_minus_first_mean_ms"] for row in rows] == [3.0, 10.0]
    assert values["well_total_growth_ratio"]["p50"] == 3.0
    assert values["well_total_growth_delta_ms"]["p50"] == 6.5
    assert values["well_total_first_quartile_ms"]["count"] == 4
    assert values["well_total_last_quartile_ms"]["count"] == 4
    assert values["resume_checkpoint_bounds"]["peak_retained_intent_count"] == 1
    assert values["resume_checkpoint_bounds"]["final_retained_intent_count"] == 0


def test_synthetic_no_growth_remains_informational_pass():
    measured = [
        _synthetic_result([20.0] * 8, 1),
        _synthetic_result([21.0] * 8, 2),
        _synthetic_result([19.0] * 8, 3),
    ]

    assessment = benchmark._aggregate_metrics(measured, _spec(wells=8))[
        "persistence"
    ]["values"]["growth_assessment"]

    assert assessment["candidate_regression"] is False
    assert assessment["classification_effect"] == "pass"


def test_last_quartile_delay_produces_warning_without_failure(tmp_path):
    spec = _spec(wells=8, workload_id="execution_persistence_warning_test")

    def delay_last_quartile(phase, completion_index, completion_count):
        if (
            phase == "complete_intent"
            and completion_index > completion_count * 3 // 4
        ):
            time.sleep(0.25)

    exit_code, report_path = benchmark.run_characterization(
        output_root=tmp_path / "reports",
        warmup_runs=0,
        measured_runs=1,
        keep_workload_artifacts="never",
        spec=spec,
        operation_hook=delay_last_quartile,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report_v1(report)
    assessment = report["metrics"]["persistence"]["values"]["growth_assessment"]

    assert exit_code == 0
    assert report_path.parent.parent.name == spec.workload_id
    assert report["classification"]["status"] == "warning"
    assert report["classification"]["threshold_maturity"] == "informational"
    assert assessment["candidate_regression"] is True
    assert assessment["observed_median_ratio"] > 1.25
    assert assessment["observed_median_delta_ms"] > 10.0
