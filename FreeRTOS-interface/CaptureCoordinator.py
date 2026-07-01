from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable
import time
import uuid

from CaptureTypes import CaptureRequest, CaptureResult, CaptureSource, CaptureStatus


class CaptureCoordinatorState(str, Enum):
    IDLE = "idle"
    REQUESTING = "requesting"
    CAPTURING = "capturing"


@dataclass(frozen=True)
class CaptureCoordinatorOutcome:
    accepted: bool
    request: CaptureRequest
    result: CaptureResult | None = None


class CaptureCoordinator:
    def __init__(self):
        self.state = CaptureCoordinatorState.IDLE
        self.active_request: CaptureRequest | None = None
        self.last_result: CaptureResult | None = None

    @property
    def is_active(self) -> bool:
        return self.active_request is not None and self.state != CaptureCoordinatorState.IDLE

    def reset(self):
        self.state = CaptureCoordinatorState.IDLE
        self.active_request = None

    def request_capture(
        self,
        *,
        context: str | None = None,
        source: CaptureSource | str = CaptureSource.CONTROLLER,
        created_at_monotonic: float | None = None,
        metadata: dict | None = None,
        delegate: Callable[[CaptureRequest], bool] | None = None,
    ) -> CaptureCoordinatorOutcome:
        request = self._make_request(
            context=context,
            source=source,
            created_at_monotonic=created_at_monotonic,
            metadata=metadata,
        )
        if self.is_active:
            result = CaptureResult.failure(
                request.request_id,
                CaptureStatus.BUSY,
                metadata={"active_request_id": self.active_request.request_id if self.active_request else None},
                reason="capture_already_active",
                retryable=True,
                source=CaptureSource.COORDINATOR,
            )
            self.last_result = result
            return CaptureCoordinatorOutcome(False, request, result)

        self.state = CaptureCoordinatorState.REQUESTING
        self.active_request = request
        try:
            accepted = True if delegate is None else bool(delegate(request))
        except Exception as exc:
            result = CaptureResult.failure(
                request.request_id,
                CaptureStatus.INTERNAL_ERROR,
                metadata={"exception_type": type(exc).__name__},
                reason=str(exc) or "capture_delegate_exception",
                source=CaptureSource.COORDINATOR,
            )
            self.last_result = result
            self.reset()
            raise

        if accepted:
            self.state = CaptureCoordinatorState.CAPTURING
            return CaptureCoordinatorOutcome(True, request, None)

        result = CaptureResult.failure(
            request.request_id,
            CaptureStatus.QUEUE_REJECTED,
            reason="capture_delegate_rejected",
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        self.reset()
        return CaptureCoordinatorOutcome(False, request, result)

    def adopt_active_request(
        self,
        request_id: str,
        *,
        context: str | None = None,
        source: CaptureSource | str = CaptureSource.CONTROLLER,
        created_at_monotonic: float | None = None,
        metadata: dict | None = None,
    ) -> CaptureRequest:
        request = CaptureRequest(
            request_id=str(request_id),
            context=context,
            source=source,
            created_at_monotonic=created_at_monotonic if created_at_monotonic is not None else time.monotonic(),
            metadata=metadata,
        )
        self.active_request = request
        self.state = CaptureCoordinatorState.CAPTURING
        return request

    def complete_success(
        self,
        request_id: str,
        frame,
        *,
        metadata: dict | None = None,
        reason: str = "",
    ) -> CaptureResult:
        if not self._matches_active_request(request_id):
            return self.record_stale_completion(request_id, metadata=metadata)
        result = CaptureResult.success(
            str(request_id),
            frame,
            metadata=metadata,
            reason=reason,
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        self.reset()
        return result

    def complete_failure(
        self,
        request_id: str,
        *,
        status: CaptureStatus | str = CaptureStatus.INTERNAL_ERROR,
        metadata: dict | None = None,
        reason: str = "",
        retryable: bool = False,
        recoverable: bool = False,
    ) -> CaptureResult:
        if not self._matches_active_request(request_id):
            return self.record_stale_completion(request_id, metadata=metadata)
        result = CaptureResult.failure(
            str(request_id),
            status,
            metadata=metadata,
            reason=reason,
            retryable=retryable,
            recoverable=recoverable,
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        self.reset()
        return result

    def record_stale_completion(
        self,
        request_id: str | None,
        *,
        metadata: dict | None = None,
        reason: str = "stale_completion_ignored",
    ) -> CaptureResult:
        stale_request_id = str(request_id or "unknown_stale_request")
        result = CaptureResult.stale_ignored(
            stale_request_id,
            metadata=metadata,
            reason=reason,
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        return result

    def _make_request(
        self,
        *,
        context: str | None,
        source: CaptureSource | str,
        created_at_monotonic: float | None,
        metadata: dict | None,
    ) -> CaptureRequest:
        return CaptureRequest(
            request_id=uuid.uuid4().hex,
            context=None if context is None else str(context),
            source=source,
            created_at_monotonic=created_at_monotonic if created_at_monotonic is not None else time.monotonic(),
            metadata=metadata,
        )

    def _matches_active_request(self, request_id) -> bool:
        if not self.is_active or self.active_request is None:
            return False
        return str(request_id) == str(self.active_request.request_id)
