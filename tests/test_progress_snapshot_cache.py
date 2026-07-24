from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
for candidate in (REPO_ROOT, UI_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from Model import ExperimentModel
from tools.virtual_workflows.progress_snapshot import (
    ProgressSnapshotObserver,
    non_durable_progress_samples,
)


def test_progress_serializer_preserves_json_dump_indent_four_bytes():
    model = ExperimentModel.__new__(ExperimentModel)
    payload = {
        "A1": {
            "reaction_id": "rxn-1",
            "reagents": {
                "stock-1": {
                    "target_droplets": 3,
                    "added_droplets": 1,
                }
            },
            "completed": False,
        },
        "__plate__": {
            "name": "shallow-384_well_plate",
            "rows": 16,
            "columns": 24,
            "schema_version": 1,
        },
    }
    expected = io.StringIO()
    json.dump(
        payload,
        expected,
        indent=4,
        default=model.convert_to_serializable,
    )

    assert model._serialize_progress_payload(payload) == expected.getvalue()


def test_progress_observer_records_boundaries_and_restores_methods():
    class FakeExperiment:
        def _build_progress_payload_from_runtime(self):
            return {"A1": {}}

        def _serialize_progress_payload(self, payload):
            return json.dumps(payload, indent=4)

        def _atomic_write_progress_text(self, serialized):
            return len(serialized)

    experiment = FakeExperiment()
    originals = {
        name: getattr(experiment, name)
        for name in (
            "_build_progress_payload_from_runtime",
            "_serialize_progress_payload",
            "_atomic_write_progress_text",
        )
    }
    observer = ProgressSnapshotObserver(experiment)
    with observer.installed():
        payload = experiment._build_progress_payload_from_runtime()
        serialized = experiment._serialize_progress_payload(payload)
        experiment._atomic_write_progress_text(serialized)
        assert not observer.snapshot()["observer_restored"]

    snapshot = observer.snapshot()
    assert snapshot["mode_counts"] == {
        "full_rebuild": 1,
        "cached_update": 0,
    }
    assert len(snapshot["duration_samples_ms"]["serialization"]) == 1
    assert len(snapshot["duration_samples_ms"]["atomic_write"]) == 1
    assert snapshot["serialized_size_bytes"] == [len(serialized.encode("utf-8"))]
    assert snapshot["observer_restored"]
    for name, original in originals.items():
        assert getattr(experiment, name) == original


def test_progress_observer_restores_after_failure():
    experiment = SimpleNamespace(
        _serialize_progress_payload=lambda _payload: (_ for _ in ()).throw(
            RuntimeError("serialize failed")
        )
    )
    original = experiment._serialize_progress_payload
    observer = ProgressSnapshotObserver(experiment)

    with pytest.raises(RuntimeError, match="serialize failed"):
        with observer.installed():
            experiment._serialize_progress_payload({})

    assert experiment._serialize_progress_payload is original
    assert observer.snapshot()["observer_restored"]
    assert len(observer.snapshot()["duration_samples_ms"]["serialization"]) == 1


def test_non_durable_progress_samples_require_aligned_calls():
    assert non_durable_progress_samples(
        [10.0, 20.0],
        [2.0, 3.0],
        [1.0, 2.0],
    ) == [7.0, 15.0]
    with pytest.raises(ValueError, match="matching counts"):
        non_durable_progress_samples([1.0], [], [0.1])
