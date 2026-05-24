import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ExperimentAuditLog import ExperimentAuditLog


class _Clock:
    def __init__(self, start):
        self.current = start

    def __call__(self):
        value = self.current
        self.current = self.current + timedelta(seconds=5)
        return value


class _JsonObject:
    def __json__(self):
        return {"custom": "json"}


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_writes_required_jsonl_fields_with_deterministic_values(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    clock = _Clock(datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc))
    ids = iter(["event-1"])
    log = ExperimentAuditLog(
        audit_path=audit_path,
        clock=clock,
        uuid_factory=lambda: next(ids),
    )

    event = log.record(
        "experiment_initialized",
        "Experiment initialized",
        details={"stock_id": "stock-1"},
        context={"operator": "test"},
    )

    assert event is not None
    assert event["schema_version"] == 1
    assert event["event_id"] == "event-1"
    assert event["timestamp_utc"] == "2026-05-24T12:00:00Z"
    assert event["elapsed_s"] == 0.0
    assert event["event_type"] == "experiment_initialized"
    assert event["level"] == "info"
    assert event["summary"] == "Experiment initialized"
    assert event["details"] == {"stock_id": "stock-1"}
    assert event["context"] == {"operator": "test"}
    assert _read_jsonl(audit_path) == [event]


def test_multiple_records_append_without_rewriting_first_event(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    clock = _Clock(datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc))
    ids = iter(["event-1", "event-2"])
    log = ExperimentAuditLog(audit_path=audit_path, clock=clock, uuid_factory=lambda: next(ids))

    first = log.record("first_event", "First")
    second = log.record("second_event", "Second")

    rows = _read_jsonl(audit_path)
    assert rows == [first, second]
    assert rows[0]["event_id"] == "event-1"
    assert rows[1]["event_id"] == "event-2"
    assert rows[0]["elapsed_s"] == 0.0
    assert rows[1]["elapsed_s"] == 5.0


def test_explicit_audit_path_creates_parent_directory(tmp_path):
    audit_path = tmp_path / "nested" / "audit" / "experiment_audit.jsonl"
    log = ExperimentAuditLog(audit_path=audit_path)

    event = log.record("path_test", "Created parent directory")

    assert event is not None
    assert audit_path.exists()
    assert log.get_audit_path() == str(audit_path.resolve())


def test_model_derived_path_writes_to_experiment_directory(tmp_path):
    experiment_dir = tmp_path / "experiment"
    model = SimpleNamespace(
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(experiment_dir),
            experiment_file_path=str(experiment_dir / "experiment_design.json"),
            progress_file_path=str(experiment_dir / "progress.json"),
            calibration_file_path=str(experiment_dir / "calibration.json"),
            metadata={"name": "Audit Test"},
        )
    )
    log = ExperimentAuditLog(model=model)

    event = log.record("model_path", "Used experiment directory")

    audit_path = experiment_dir / "experiment_audit.jsonl"
    assert event is not None
    assert audit_path.exists()
    assert log.get_audit_path() == str(audit_path.resolve())
    row = _read_jsonl(audit_path)[0]
    assert row["context"]["experiment_name"] == "Audit Test"
    assert row["context"]["experiment_dir"] == str(experiment_dir)
    assert row["context"]["progress_file_path"] == str(experiment_dir / "progress.json")


def test_missing_experiment_directory_returns_none_and_records_last_error():
    model = SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=None))
    log = ExperimentAuditLog(model=model)

    assert log.record("missing_path", "No path") is None
    assert "No experiment audit path" in log.get_last_error()


def test_non_json_values_are_safely_normalized(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    custom_path = tmp_path / "artifact.txt"
    log = ExperimentAuditLog(audit_path=audit_path)

    event = log.record(
        "normalization",
        "Normalized values",
        details={
            "path": custom_path,
            "custom": _JsonObject(),
            "items": {_JsonObject(), custom_path},
        },
        context={"source_path": custom_path},
    )

    row = _read_jsonl(audit_path)[0]
    assert event == row
    assert row["details"]["path"] == str(custom_path)
    assert row["details"]["custom"] == {"custom": "json"}
    assert {"custom": "json"} in row["details"]["items"]
    assert str(custom_path) in row["details"]["items"]
    assert row["context"]["source_path"] == str(custom_path)


def test_level_normalization_preserves_known_levels_and_defaults_unknown(tmp_path):
    audit_path = tmp_path / "experiment_audit.jsonl"
    log = ExperimentAuditLog(audit_path=audit_path)

    log.record("warn", "Warning", level="warning")
    log.record("err", "Error", level="ERROR")
    log.record("odd", "Unknown", level="debug")

    rows = _read_jsonl(audit_path)
    assert [row["level"] for row in rows] == ["warning", "error", "info"]


def test_write_failure_returns_none_and_preserves_existing_file(tmp_path, monkeypatch):
    audit_path = tmp_path / "experiment_audit.jsonl"
    audit_path.write_text(json.dumps({"event_id": "existing"}) + "\n", encoding="utf-8")
    log = ExperimentAuditLog(audit_path=audit_path)

    def _boom(*args, **kwargs):
        raise OSError("simulated append failure")

    with monkeypatch.context() as patched:
        patched.setattr(Path, "open", _boom)
        assert log.record("write_failure", "Will fail") is None
        assert "simulated append failure" in log.get_last_error()
    assert _read_jsonl(audit_path) == [{"event_id": "existing"}]
