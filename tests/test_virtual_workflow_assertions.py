from __future__ import annotations

from tools.virtual_workflows.assertions import (
    AssertionResult,
    ExecutionLifecycleExpectation,
    cleanup_assertion,
    editor_artifacts_cleanup_assertion,
    evaluate_assertion,
    multi_stock_artifacts_assertion,
)

import pytest


def test_assertion_result_rejects_ambiguous_decision():
    try:
        AssertionResult("a", "b", "unknown", (), {})
    except ValueError as exc:
        assert "pass, fail, or incomplete" in str(exc)
    else:
        raise AssertionError("ambiguous assertion decision was accepted")


def test_execution_lifecycle_expectation_rejects_ambiguous_identity_sets():
    with pytest.raises(ValueError, match="well IDs must be unique"):
        ExecutionLifecycleExpectation({}, ("A1", "A1"), ("stock-1",))
    with pytest.raises(ValueError, match="stock IDs must be unique"):
        ExecutionLifecycleExpectation({}, ("A1",), ("stock-1", "stock-1"))


def test_evaluate_assertion_records_pass_fail_and_incomplete():
    passed = evaluate_assertion("pass", "ready", ("ui",), lambda: (True, {"x": 1}))
    failed = evaluate_assertion("fail", "ready", ("model",), lambda: (False, {"x": 0}))

    def unavailable():
        raise LookupError("missing evidence")

    incomplete = evaluate_assertion("incomplete", "ready", (), unavailable)

    assert passed.decision == "pass"
    assert failed.decision == "fail"
    assert failed.message
    assert incomplete.decision == "incomplete"
    assert incomplete.evidence == {"exception_type": "LookupError"}


def test_cleanup_assertion_requires_close_and_removed_lock():
    assert cleanup_assertion(
        {"evidence": {"close_succeeded": True, "session_lock_present": False}}
    ).decision == "pass"
    assert cleanup_assertion(
        {"evidence": {"close_succeeded": True, "session_lock_present": True}}
    ).decision == "fail"


def test_editor_artifact_assertion_requires_exact_nonempty_screenshots_and_cleanup(
    tmp_path,
):
    screenshot = tmp_path / "finalized.png"
    screenshot.write_bytes(b"png")
    teardown = {
        "evidence": {"close_succeeded": True, "session_lock_present": False}
    }

    assert editor_artifacts_cleanup_assertion(
        screenshots={"finalized": screenshot},
        required_screenshots={"finalized"},
        teardown=teardown,
    ).decision == "pass"
    assert editor_artifacts_cleanup_assertion(
        screenshots={"finalized": screenshot},
        required_screenshots={"finalized", "validated"},
        teardown=teardown,
    ).decision == "fail"


def test_multi_stock_artifacts_require_exact_screenshots_and_removed_lock(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    result = multi_stock_artifacts_assertion(
        screenshots={"first": first, "second": second},
        required_screenshots={"first", "second"},
        teardown={
            "evidence": {
                "close_succeeded": True,
                "session_lock_present": False,
            }
        },
    )
    assert result.decision == "pass"
