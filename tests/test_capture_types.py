from __future__ import annotations

import ast
from pathlib import Path

import pytest

import CaptureTypes
from CaptureTypes import CaptureRequest, CaptureResult, CaptureSource, CaptureStatus


def test_capture_status_values_match_contract():
    assert {status.value for status in CaptureStatus} == {
        "success",
        "cancelled",
        "timeout",
        "busy",
        "queue_rejected",
        "backend_unavailable",
        "recovery_succeeded",
        "recovery_failed",
        "flash_disarmed",
        "firmware_flash_fault",
        "firmware_flash_latched",
        "firmware_flash_missed",
        "flash_not_observed",
        "stale_ignored",
        "detached_force_close",
        "internal_error",
    }


def test_capture_source_values_are_stable():
    assert {source.value for source in CaptureSource} == {
        "ui",
        "calibration",
        "diagnostic",
        "internal_retry",
        "controller",
        "coordinator",
        "machine",
        "camera",
        "firmware",
    }


def test_capture_types_module_has_no_hardware_or_qt_imports():
    source = Path(CaptureTypes.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])

    assert imports <= {"__future__", "dataclasses", "enum", "typing"}


def test_capture_request_stores_copied_policy_and_metadata_fields():
    timeout_policy = {"guard_ms": 8000}
    cancellation_policy = {"recover": True}
    retry_policy = {"attempts": 3}
    metadata = {"phase": "nozzle_position"}

    request = CaptureRequest(
        request_id="req-1",
        context="calibration:nozzle_position",
        source="calibration",
        created_at_monotonic=123.45,
        timeout_policy=timeout_policy,
        cancellation_policy=cancellation_policy,
        retry_policy=retry_policy,
        metadata=metadata,
    )

    timeout_policy["guard_ms"] = 1
    cancellation_policy["recover"] = False
    retry_policy["attempts"] = 0
    metadata["phase"] = "mutated"

    assert request.request_id == "req-1"
    assert request.context == "calibration:nozzle_position"
    assert request.source is CaptureSource.CALIBRATION
    assert request.created_at_monotonic == pytest.approx(123.45)
    assert request.timeout_policy == {"guard_ms": 8000}
    assert request.cancellation_policy == {"recover": True}
    assert request.retry_policy == {"attempts": 3}
    assert request.metadata == {"phase": "nozzle_position"}


def test_capture_request_requires_request_id():
    with pytest.raises(ValueError, match="request_id"):
        CaptureRequest(request_id="")


def test_success_requires_frame_and_round_trips_to_legacy_frame():
    frame = object()

    result = CaptureResult.success(
        "req-2",
        frame,
        metadata={"cap_id": 42},
        reason="threshold",
        source="camera",
    )

    assert result.status is CaptureStatus.SUCCESS
    assert result.source is CaptureSource.CAMERA
    assert result.frame is frame
    assert result.metadata == {"cap_id": 42}
    assert result.reason == "threshold"
    assert result.to_legacy_frame() is frame
    assert result.caller_notifiable is True


def test_success_rejects_missing_frame():
    with pytest.raises(ValueError, match="requires a frame"):
        CaptureResult.success("req-3", None)


def test_failure_returns_none_to_legacy_frame():
    result = CaptureResult.failure(
        "req-4",
        CaptureStatus.TIMEOUT,
        reason="guard_timeout",
        retryable=True,
        recoverable=True,
    )

    assert result.status is CaptureStatus.TIMEOUT
    assert result.reason == "guard_timeout"
    assert result.retryable is True
    assert result.recoverable is True
    assert result.to_legacy_frame() is None


def test_non_success_result_rejects_frame():
    with pytest.raises(ValueError, match="non-success"):
        CaptureResult("req-5", CaptureStatus.TIMEOUT, frame=object())


def test_cancelled_result_is_terminal_and_legacy_compatible():
    result = CaptureResult.cancelled("req-6", reason="stop_button")

    assert result.status is CaptureStatus.CANCELLED
    assert result.reason == "stop_button"
    assert result.retryable is False
    assert result.recoverable is False
    assert result.to_legacy_frame() is None
    assert result.caller_notifiable is True


def test_retryable_failures_require_explicit_opt_in():
    default_timeout = CaptureResult.failure("req-7", CaptureStatus.TIMEOUT)
    retry_timeout = CaptureResult.failure("req-8", "timeout", retryable=True)
    retry_busy = CaptureResult.failure("req-9", CaptureStatus.BUSY, retryable=True)

    assert default_timeout.retryable is False
    assert retry_timeout.retryable is True
    assert retry_busy.retryable is True


@pytest.mark.parametrize(
    "status",
    [
        CaptureStatus.CANCELLED,
        CaptureStatus.FIRMWARE_FLASH_FAULT,
        CaptureStatus.FIRMWARE_FLASH_LATCHED,
        CaptureStatus.DETACHED_FORCE_CLOSE,
    ],
)
def test_forbidden_retry_statuses_raise(status):
    with pytest.raises(ValueError, match="retryable"):
        CaptureResult.failure("req-10", status, retryable=True)


def test_stale_ignored_is_diagnostic_and_not_caller_notifiable():
    result = CaptureResult.stale_ignored(
        "req-stale",
        metadata={"late_request_id": "req-old"},
        reason="late_worker_completion",
    )

    assert result.status is CaptureStatus.STALE_IGNORED
    assert result.stale is True
    assert result.caller_notifiable is False
    assert result.to_legacy_frame() is None
    assert result.metadata == {"late_request_id": "req-old"}


def test_stale_flag_is_only_valid_for_stale_ignored():
    with pytest.raises(ValueError, match="stale=True"):
        CaptureResult("req-11", CaptureStatus.TIMEOUT, stale=True)


def test_detached_force_close_sets_dirty_shutdown_and_is_not_retryable():
    result = CaptureResult.detached_force_close("req-detached", reason="force_close")

    assert result.status is CaptureStatus.DETACHED_FORCE_CLOSE
    assert result.dirty_shutdown is True
    assert result.retryable is False
    assert result.to_legacy_frame() is None


def test_dirty_shutdown_is_only_valid_for_detached_force_close():
    with pytest.raises(ValueError, match="dirty_shutdown=True"):
        CaptureResult("req-12", CaptureStatus.TIMEOUT, dirty_shutdown=True)


def test_from_legacy_frame_maps_frame_to_success_and_none_to_failure():
    frame = object()

    success = CaptureResult.from_legacy_frame("req-13", frame, reason="legacy_success")
    failure = CaptureResult.from_legacy_frame(
        "req-14",
        None,
        failure_status=CaptureStatus.BACKEND_UNAVAILABLE,
        reason="legacy_none",
        recoverable=True,
    )

    assert success.status is CaptureStatus.SUCCESS
    assert success.to_legacy_frame() is frame
    assert failure.status is CaptureStatus.BACKEND_UNAVAILABLE
    assert failure.reason == "legacy_none"
    assert failure.recoverable is True
    assert failure.to_legacy_frame() is None


def test_failure_helper_rejects_success_status():
    with pytest.raises(ValueError, match="CaptureResult.success"):
        CaptureResult.failure("req-15", CaptureStatus.SUCCESS)


def test_capture_result_requires_request_id():
    with pytest.raises(ValueError, match="request_id"):
        CaptureResult.failure("", CaptureStatus.INTERNAL_ERROR)
