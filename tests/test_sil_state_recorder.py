import json

import pytest

from tools.sil import state_recorder as recorder_module
from tools.sil.state_recorder import (
    EVENT_SCHEMA_ID,
    SNAPSHOT_SCHEMA_ID,
    STATE_SCHEMA_VERSION,
    StateRecorder,
    StateRecorderConfigV1,
    StateRecorderError,
    normalize_state_value,
)


def _recorder(tmp_path, **config_overrides):
    return StateRecorder(
        session_root=tmp_path,
        session_id="session-1",
        application_session_id="app-1",
        config=StateRecorderConfigV1(**config_overrides),
    )


@pytest.mark.parametrize(
    "field",
    [
        "in_memory_event_limit",
        "flush_every_events",
        "max_changed_fields",
        "max_string_chars",
        "max_collection_entries",
        "max_depth",
    ],
)
def test_recorder_config_requires_positive_integer_limits(field):
    with pytest.raises(ValueError, match=field):
        StateRecorderConfigV1(**{field: 0})
    with pytest.raises(ValueError, match=field):
        StateRecorderConfigV1(**{field: True})


def test_normalization_is_json_safe_bounded_and_reports_truncation():
    config = StateRecorderConfigV1(
        max_string_chars=4,
        max_collection_entries=2,
        max_depth=2,
    )
    normalized, truncation = normalize_state_value(
        {
            "long": "abcdefgh",
            "many": [1, 2, 3],
            "nested": {"a": {"b": "too-deep"}},
            "not_finite": float("inf"),
            "unknown": object(),
        },
        config,
    )

    json.dumps(normalized)
    assert len(normalized) == 2
    assert truncation["collections"] >= 1
    assert truncation["entries_dropped"] >= 1

    focused, focused_truncation = normalize_state_value(
        ["abcdefgh", float("nan"), object(), {"a": {"b": 1}}],
        StateRecorderConfigV1(
            max_string_chars=4,
            max_collection_entries=10,
            max_depth=2,
        ),
    )
    assert focused[:3] == ["abcd", None, "<obj"]
    assert focused[3] == {"a": "<max-depth>"}
    assert focused_truncation == {
        "strings": 2,
        "characters_dropped": 8,
        "collections": 0,
        "entries_dropped": 0,
        "depth": 1,
        "non_finite_numbers": 1,
        "unsupported_values": 1,
    }


def test_recorder_writes_ordered_schema_events_and_bounded_memory(tmp_path):
    recorder = _recorder(
        tmp_path,
        in_memory_event_limit=3,
        max_changed_fields=2,
        max_string_chars=5,
    )
    assert recorder.healthy
    action_id = recorder.begin_action("connect", payload={"port": "SIMULATED"})
    event = recorder.record_event(
        "state_changed",
        source_layer="simulator",
        before={"a": 1, "b": 2, "c": 3},
        after={"a": 2, "b": 2, "c": 3},
        payload={"message": "abcdefgh"},
        correlation={"action_id": action_id, "command_id": "command-1"},
        simulated_elapsed_ms=12,
    )
    recorder.complete_action(action_id, action_kind="connect")
    snapshot = recorder.record_snapshot(
        {"simulator": {"status": "connected"}},
        reason="manual",
        correlation={"action_id": action_id},
    )

    assert event["schema_id"] == EVENT_SCHEMA_ID
    assert event["schema_version"] == STATE_SCHEMA_VERSION
    assert event["event_sequence"] == 3
    assert len(event["before"]) == 2
    assert event["payload"]["message"] == "abcde"
    assert event["truncation"]["characters_dropped"] >= 3
    assert snapshot["schema_id"] == SNAPSHOT_SCHEMA_ID
    assert snapshot["schema_version"] == STATE_SCHEMA_VERSION
    assert snapshot["correlation"]["snapshot_id"] == "snapshot-000001"
    assert snapshot["correlation"]["action_id"] == action_id
    assert json.loads(recorder.latest_snapshot_path.read_text(encoding="utf-8")) == snapshot

    health = recorder.health_snapshot()
    assert health["event_count"] == 5
    assert health["retained_memory_count"] == 3
    assert health["evicted_memory_count"] == 2
    assert sum(health["evicted_by_kind"].values()) == 2
    assert [item["event_sequence"] for item in recorder.memory_tail()] == [3, 4, 5]

    assert recorder.close()
    assert recorder.close()
    lines = [
        json.loads(line)
        for line in recorder.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [item["event_sequence"] for item in lines] == list(range(1, 7))
    assert lines[0]["event_kind"] == "recorder_started"
    assert lines[-1]["event_kind"] == "recorder_stopped"
    assert recorder.health_snapshot()["status"] == "closed"


def test_snapshot_replace_failure_is_single_attempt_and_preserves_evidence(
    tmp_path,
    monkeypatch,
):
    failures = []
    recorder = StateRecorder(
        session_root=tmp_path,
        session_id="session-1",
        application_session_id="app-1",
        on_failure=failures.append,
    )
    application_state = {"connected": True, "pressure": 17}
    replace_attempts = []

    def fail_replace(source, destination):
        replace_attempts.append((source, destination))
        raise PermissionError("simulated replace denial")

    monkeypatch.setattr(recorder_module.os, "replace", fail_replace)
    with pytest.raises(StateRecorderError, match="snapshot write failed"):
        recorder.record_snapshot(
            {"application": dict(application_state)},
            reason="failure-test",
        )

    assert application_state == {"connected": True, "pressure": 17}
    assert len(replace_attempts) == 1
    assert recorder.failed
    assert failures == [recorder.health_snapshot()["failure"]]
    assert list(recorder.artifact_dir.glob(".latest_snapshot_*.tmp"))
    with pytest.raises(StateRecorderError, match="snapshot write failed"):
        recorder.record_event("must_not_retry", source_layer="test")
    assert len(replace_attempts) == 1
    assert not recorder.close()


def test_artifacts_are_contained_and_application_session_directories_are_unique(
    tmp_path,
):
    first = _recorder(tmp_path)
    try:
        assert tmp_path.resolve() in first.artifact_dir.parents
        duplicate = StateRecorder(
            session_root=tmp_path,
            session_id="session-1",
            application_session_id="app-1",
        )
        assert duplicate.failed
        with pytest.raises(StateRecorderError, match="initialization failed"):
            duplicate.record_event("unreachable", source_layer="test")
        assert duplicate.events_path.read_text(encoding="utf-8")
    finally:
        assert first.close()
