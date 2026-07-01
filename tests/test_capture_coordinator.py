from __future__ import annotations

import ast
from pathlib import Path

import pytest

import CaptureCoordinator
from CaptureCoordinator import CaptureCoordinatorState, CaptureCoordinator as Coordinator
from CaptureTypes import CaptureRequest, CaptureStatus


def test_capture_coordinator_module_has_no_hardware_or_qt_imports():
    source = Path(CaptureCoordinator.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])

    assert imports <= {"__future__", "dataclasses", "enum", "typing", "time", "uuid", "CaptureTypes"}


def test_coordinator_starts_idle():
    coordinator = Coordinator()

    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False
    assert coordinator.pending_snapshot()["active"] is False
    assert coordinator.last_result is None
    assert coordinator.is_active is False


def test_begin_pending_exposes_pending_capture_state():
    coordinator = Coordinator()
    callback = object()
    request = CaptureRequest(
        request_id="request-1",
        context="calibration",
        source="controller",
        created_at_monotonic=10.0,
        metadata={"phase": "focus"},
    )

    pending = coordinator.begin_pending(
        request,
        callback=callback,
        context="calibration",
        started_monotonic=12.5,
        recovery_attempted=True,
        throughput_mode=True,
    )

    assert pending.request == request
    assert coordinator.pending_active is True
    assert coordinator.pending_request_id == "request-1"
    assert coordinator.pending_callback is callback
    assert coordinator.pending_context == "calibration"
    assert coordinator.pending_started_monotonic == pytest.approx(12.5)
    assert coordinator.pending_recovery_attempted is True
    assert coordinator.pending_throughput_mode is True
    assert coordinator.pending_snapshot() == {
        "active": True,
        "request": request,
        "request_id": "request-1",
        "callback": callback,
        "context": "calibration",
        "started_monotonic": 12.5,
        "recovery_attempted": True,
        "throughput_mode": True,
    }
    assert coordinator.state is CaptureCoordinatorState.CAPTURING
    assert coordinator.active_request == request


def test_clear_pending_clears_canonical_state_and_returns_idle():
    coordinator = Coordinator()
    callback = object()
    request = CaptureRequest(request_id="request-1", context="ctx", source="controller")
    coordinator.begin_pending(request, callback=callback, context="ctx")

    assert coordinator.clear_pending(callback=callback, context="ctx") is True

    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False


def test_clear_pending_preserves_state_when_callback_or_context_do_not_match():
    coordinator = Coordinator()
    callback = object()
    request = CaptureRequest(request_id="request-1", context="ctx", source="controller")
    coordinator.begin_pending(request, callback=callback, context="ctx")

    assert coordinator.clear_pending(callback=object()) is False
    assert coordinator.pending_request_id == "request-1"
    assert coordinator.clear_pending(context="other") is False
    assert coordinator.pending_request_id == "request-1"


def test_request_capture_transitions_requesting_before_delegate_and_capturing_after_accept():
    coordinator = Coordinator()
    observed_states = []

    def delegate(request):
        observed_states.append((coordinator.state, coordinator.active_request))
        return True

    outcome = coordinator.request_capture(
        context="unit_context",
        created_at_monotonic=123.0,
        metadata={"phase": "unit"},
        delegate=delegate,
    )

    assert observed_states == [(CaptureCoordinatorState.REQUESTING, outcome.request)]
    assert outcome.accepted is True
    assert outcome.result is None
    assert coordinator.state is CaptureCoordinatorState.CAPTURING
    assert coordinator.active_request == outcome.request
    assert coordinator.pending_request_id == outcome.request.request_id
    assert coordinator.pending_context == "unit_context"
    assert coordinator.pending_started_monotonic == pytest.approx(123.0)
    assert coordinator.active_request.context == "unit_context"
    assert coordinator.active_request.metadata == {"phase": "unit"}
    assert coordinator.active_request.created_at_monotonic == pytest.approx(123.0)


def test_delegate_rejection_records_queue_rejected_and_clears_active_state():
    coordinator = Coordinator()

    outcome = coordinator.request_capture(delegate=lambda _request: False)

    assert outcome.accepted is False
    assert outcome.result.status is CaptureStatus.QUEUE_REJECTED
    assert coordinator.last_result == outcome.result
    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False
    assert coordinator.is_active is False


def test_second_request_while_active_records_busy_and_preserves_first_request():
    coordinator = Coordinator()
    first = coordinator.request_capture(delegate=lambda _request: True)

    second = coordinator.request_capture(delegate=lambda _request: True)

    assert first.accepted is True
    assert second.accepted is False
    assert second.result.status is CaptureStatus.BUSY
    assert second.result.retryable is True
    assert coordinator.active_request == first.request
    assert coordinator.state is CaptureCoordinatorState.CAPTURING


def test_delegate_exception_records_internal_error_clears_state_and_reraises():
    coordinator = Coordinator()

    def delegate(_request):
        raise RuntimeError("delegate exploded")

    with pytest.raises(RuntimeError, match="delegate exploded"):
        coordinator.request_capture(delegate=delegate)

    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False
    assert coordinator.last_result.status is CaptureStatus.INTERNAL_ERROR
    assert coordinator.last_result.reason == "delegate exploded"


def test_matching_success_records_success_and_clears_active_state():
    coordinator = Coordinator()
    outcome = coordinator.request_capture(delegate=lambda _request: True)
    frame = object()

    result = coordinator.complete_success(
        outcome.request.request_id,
        frame,
        metadata={"cap_id": 123},
        reason="threshold",
    )

    assert result.status is CaptureStatus.SUCCESS
    assert result.frame is frame
    assert result.metadata == {"cap_id": 123}
    assert result.reason == "threshold"
    assert coordinator.last_result == result
    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False


def test_matching_failure_records_failure_and_clears_active_state():
    coordinator = Coordinator()
    outcome = coordinator.request_capture(delegate=lambda _request: True)

    result = coordinator.complete_failure(
        outcome.request.request_id,
        status=CaptureStatus.TIMEOUT,
        reason="guard_timeout",
        retryable=True,
        recoverable=True,
    )

    assert result.status is CaptureStatus.TIMEOUT
    assert result.reason == "guard_timeout"
    assert result.retryable is True
    assert result.recoverable is True
    assert coordinator.last_result == result
    assert coordinator.state is CaptureCoordinatorState.IDLE
    assert coordinator.active_request is None
    assert coordinator.pending_active is False


def test_mismatched_completion_records_stale_and_preserves_active_state():
    coordinator = Coordinator()
    active = coordinator.request_capture(delegate=lambda _request: True)

    result = coordinator.complete_success(
        "old-request",
        object(),
        metadata={"generation": 1},
    )

    assert result.status is CaptureStatus.STALE_IGNORED
    assert result.stale is True
    assert result.metadata == {"generation": 1}
    assert coordinator.last_result == result
    assert coordinator.active_request == active.request
    assert coordinator.pending_request_id == active.request.request_id
    assert coordinator.state is CaptureCoordinatorState.CAPTURING


def test_adopt_active_request_replaces_request_id_for_legacy_requeue():
    coordinator = Coordinator()
    original = coordinator.request_capture(context="original", delegate=lambda _request: True)
    callback = object()

    adopted = coordinator.adopt_active_request(
        "retry-request",
        context="retry",
        created_at_monotonic=200.5,
        callback=callback,
        started_monotonic=201.5,
        recovery_attempted=True,
        throughput_mode=True,
        metadata={"recovery_attempted": True},
    )

    assert original.request.request_id != adopted.request_id
    assert adopted.request_id == "retry-request"
    assert adopted.context == "retry"
    assert adopted.created_at_monotonic == pytest.approx(200.5)
    assert adopted.metadata == {"recovery_attempted": True}
    assert coordinator.active_request == adopted
    assert coordinator.pending_request_id == "retry-request"
    assert coordinator.pending_callback is callback
    assert coordinator.pending_context == "retry"
    assert coordinator.pending_started_monotonic == pytest.approx(201.5)
    assert coordinator.pending_recovery_attempted is True
    assert coordinator.pending_throughput_mode is True
    assert coordinator.state is CaptureCoordinatorState.CAPTURING
