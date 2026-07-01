from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class CaptureStatus(str, Enum):
    SUCCESS = "success"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    BUSY = "busy"
    QUEUE_REJECTED = "queue_rejected"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_FAILED = "recovery_failed"
    FLASH_DISARMED = "flash_disarmed"
    FIRMWARE_FLASH_FAULT = "firmware_flash_fault"
    FIRMWARE_FLASH_LATCHED = "firmware_flash_latched"
    FIRMWARE_FLASH_MISSED = "firmware_flash_missed"
    FLASH_NOT_OBSERVED = "flash_not_observed"
    STALE_IGNORED = "stale_ignored"
    DETACHED_FORCE_CLOSE = "detached_force_close"
    INTERNAL_ERROR = "internal_error"


class CaptureSource(str, Enum):
    UI = "ui"
    CALIBRATION = "calibration"
    DIAGNOSTIC = "diagnostic"
    INTERNAL_RETRY = "internal_retry"
    CONTROLLER = "controller"
    COORDINATOR = "coordinator"
    MACHINE = "machine"
    CAMERA = "camera"
    FIRMWARE = "firmware"


NON_RETRYABLE_STATUSES = frozenset(
    {
        CaptureStatus.CANCELLED,
        CaptureStatus.FIRMWARE_FLASH_FAULT,
        CaptureStatus.FIRMWARE_FLASH_LATCHED,
        CaptureStatus.DETACHED_FORCE_CLOSE,
    }
)


def _as_status(status: CaptureStatus | str) -> CaptureStatus:
    if isinstance(status, CaptureStatus):
        return status
    return CaptureStatus(str(status))


def _as_source(source: CaptureSource | str) -> CaptureSource:
    if isinstance(source, CaptureSource):
        return source
    return CaptureSource(str(source))


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class CaptureRequest:
    request_id: str
    context: str | None = None
    source: CaptureSource | str = CaptureSource.CONTROLLER
    created_at_monotonic: float | None = None
    timeout_policy: Mapping[str, Any] | None = field(default_factory=dict)
    cancellation_policy: Mapping[str, Any] | None = field(default_factory=dict)
    retry_policy: Mapping[str, Any] | None = field(default_factory=dict)
    metadata: Mapping[str, Any] | None = field(default_factory=dict)

    def __post_init__(self):
        if not self.request_id:
            raise ValueError("CaptureRequest requires request_id")
        object.__setattr__(self, "source", _as_source(self.source))
        object.__setattr__(self, "timeout_policy", _copy_mapping(self.timeout_policy))
        object.__setattr__(self, "cancellation_policy", _copy_mapping(self.cancellation_policy))
        object.__setattr__(self, "retry_policy", _copy_mapping(self.retry_policy))
        object.__setattr__(self, "metadata", _copy_mapping(self.metadata))


@dataclass(frozen=True)
class CaptureResult:
    request_id: str
    status: CaptureStatus | str
    frame: Any = None
    metadata: Mapping[str, Any] | None = field(default_factory=dict)
    reason: str = ""
    retryable: bool = False
    recoverable: bool = False
    source: CaptureSource | str = CaptureSource.COORDINATOR
    stale: bool = False
    dirty_shutdown: bool = False

    def __post_init__(self):
        if not self.request_id:
            raise ValueError("CaptureResult requires request_id")

        status = _as_status(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source", _as_source(self.source))
        object.__setattr__(self, "metadata", _copy_mapping(self.metadata))
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(self, "retryable", bool(self.retryable))
        object.__setattr__(self, "recoverable", bool(self.recoverable))
        object.__setattr__(self, "stale", bool(self.stale))
        object.__setattr__(self, "dirty_shutdown", bool(self.dirty_shutdown))

        if status == CaptureStatus.SUCCESS:
            if self.frame is None:
                raise ValueError("success CaptureResult requires a frame")
            if self.retryable:
                raise ValueError("success CaptureResult cannot be retryable")
            if self.stale:
                raise ValueError("success CaptureResult cannot be stale")
            if self.dirty_shutdown:
                raise ValueError("success CaptureResult cannot be dirty_shutdown")
            return

        if self.frame is not None:
            raise ValueError("non-success CaptureResult cannot carry a frame")
        if self.retryable and status in NON_RETRYABLE_STATUSES:
            raise ValueError(f"{status.value} CaptureResult cannot be retryable")
        if self.stale and status != CaptureStatus.STALE_IGNORED:
            raise ValueError("stale=True is only valid with stale_ignored")
        if self.dirty_shutdown and status != CaptureStatus.DETACHED_FORCE_CLOSE:
            raise ValueError("dirty_shutdown=True is only valid with detached_force_close")

    @property
    def caller_notifiable(self) -> bool:
        return self.status != CaptureStatus.STALE_IGNORED

    @classmethod
    def success(
        cls,
        request_id: str,
        frame: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "",
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        return cls(
            request_id=request_id,
            status=CaptureStatus.SUCCESS,
            frame=frame,
            metadata=metadata,
            reason=reason,
            source=source,
        )

    @classmethod
    def failure(
        cls,
        request_id: str,
        status: CaptureStatus | str,
        *,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "",
        retryable: bool = False,
        recoverable: bool = False,
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        status = _as_status(status)
        if status == CaptureStatus.SUCCESS:
            raise ValueError("use CaptureResult.success for success results")
        return cls(
            request_id=request_id,
            status=status,
            metadata=metadata,
            reason=reason,
            retryable=retryable,
            recoverable=recoverable,
            source=source,
        )

    @classmethod
    def cancelled(
        cls,
        request_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "capture_cancelled",
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        return cls.failure(
            request_id,
            CaptureStatus.CANCELLED,
            metadata=metadata,
            reason=reason,
            retryable=False,
            recoverable=False,
            source=source,
        )

    @classmethod
    def stale_ignored(
        cls,
        request_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "stale_completion_ignored",
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        return cls(
            request_id=request_id,
            status=CaptureStatus.STALE_IGNORED,
            metadata=metadata,
            reason=reason,
            source=source,
            stale=True,
        )

    @classmethod
    def detached_force_close(
        cls,
        request_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "detached_force_close",
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        return cls(
            request_id=request_id,
            status=CaptureStatus.DETACHED_FORCE_CLOSE,
            metadata=metadata,
            reason=reason,
            source=source,
            dirty_shutdown=True,
        )

    @classmethod
    def from_legacy_frame(
        cls,
        request_id: str,
        frame: Any,
        *,
        failure_status: CaptureStatus | str = CaptureStatus.INTERNAL_ERROR,
        metadata: Mapping[str, Any] | None = None,
        reason: str = "",
        retryable: bool = False,
        recoverable: bool = False,
        source: CaptureSource | str = CaptureSource.COORDINATOR,
    ) -> "CaptureResult":
        if frame is not None:
            return cls.success(
                request_id,
                frame,
                metadata=metadata,
                reason=reason,
                source=source,
            )
        return cls.failure(
            request_id,
            failure_status,
            metadata=metadata,
            reason=reason,
            retryable=retryable,
            recoverable=recoverable,
            source=source,
        )

    def to_legacy_frame(self) -> Any:
        if self.status == CaptureStatus.SUCCESS:
            return self.frame
        return None
