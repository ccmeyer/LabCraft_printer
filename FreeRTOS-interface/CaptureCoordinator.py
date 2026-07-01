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


@dataclass(frozen=True)
class CapturePendingState:
    request: CaptureRequest
    callback: object | None = None
    context: str | None = None
    started_monotonic: float | None = None
    recovery_attempted: bool = False
    throughput_mode: bool = False


class CaptureCoordinator:
    def __init__(self):
        self.state = CaptureCoordinatorState.IDLE
        self.active_request: CaptureRequest | None = None
        self.pending: CapturePendingState | None = None
        self.last_result: CaptureResult | None = None

    @property
    def is_active(self) -> bool:
        return (self.pending is not None or self.active_request is not None) and self.state != CaptureCoordinatorState.IDLE

    @property
    def pending_active(self) -> bool:
        return self.pending is not None

    @property
    def pending_request_id(self) -> str | None:
        return None if self.pending is None else self.pending.request.request_id

    @property
    def pending_callback(self):
        return None if self.pending is None else self.pending.callback

    @property
    def pending_context(self) -> str | None:
        return None if self.pending is None else self.pending.context

    @property
    def pending_started_monotonic(self) -> float | None:
        return None if self.pending is None else self.pending.started_monotonic

    @property
    def pending_recovery_attempted(self) -> bool:
        return False if self.pending is None else bool(self.pending.recovery_attempted)

    @property
    def pending_throughput_mode(self) -> bool:
        return False if self.pending is None else bool(self.pending.throughput_mode)

    def reset(self):
        self.state = CaptureCoordinatorState.IDLE
        self.active_request = None
        self.pending = None

    def request_capture(
        self,
        *,
        context: str | None = None,
        source: CaptureSource | str = CaptureSource.CONTROLLER,
        created_at_monotonic: float | None = None,
        metadata: dict | None = None,
        callback=None,
        started_monotonic: float | None = None,
        recovery_attempted: bool = False,
        throughput_mode: bool = False,
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
            if self.pending is None or self.pending.request.request_id != request.request_id:
                self.begin_pending(
                    request,
                    callback=callback,
                    context=context,
                    started_monotonic=started_monotonic,
                    recovery_attempted=recovery_attempted,
                    throughput_mode=throughput_mode,
                )
            else:
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
        callback=None,
        started_monotonic: float | None = None,
        recovery_attempted: bool = False,
        throughput_mode: bool = False,
    ) -> CaptureRequest:
        request = CaptureRequest(
            request_id=str(request_id),
            context=context,
            source=source,
            created_at_monotonic=created_at_monotonic if created_at_monotonic is not None else time.monotonic(),
            metadata=metadata,
        )
        self.begin_pending(
            request,
            callback=callback,
            context=context,
            started_monotonic=started_monotonic,
            recovery_attempted=recovery_attempted,
            throughput_mode=throughput_mode,
        )
        return request

    def begin_pending(
        self,
        request: CaptureRequest,
        *,
        callback=None,
        context: str | None = None,
        started_monotonic: float | None = None,
        recovery_attempted: bool = False,
        throughput_mode: bool = False,
    ) -> CapturePendingState:
        pending = CapturePendingState(
            request=request,
            callback=callback,
            context=request.context if context is None else str(context),
            started_monotonic=(
                request.created_at_monotonic
                if started_monotonic is None
                else float(started_monotonic)
            ),
            recovery_attempted=bool(recovery_attempted),
            throughput_mode=bool(throughput_mode),
        )
        self.active_request = request
        self.pending = pending
        self.state = CaptureCoordinatorState.CAPTURING
        return pending

    def clear_pending(self, *, callback=None, context: str | None = None) -> bool:
        if self.pending is None:
            if callback is None and context is None:
                self.reset()
            return False
        if callback is not None and self.pending.callback is not callback:
            return False
        if context is not None and self.pending.context != str(context):
            return False
        self.reset()
        return True

    def cancel_pending(
        self,
        *,
        reason: str = "capture_cancelled",
        metadata: dict | None = None,
    ) -> CaptureResult | None:
        if self.pending is None:
            return None
        request_id = self.pending.request.request_id
        result = CaptureResult.cancelled(
            request_id,
            metadata=metadata,
            reason=reason,
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        self.reset()
        return result

    def detach_pending_for_force_close(
        self,
        *,
        reason: str = "detached_force_close",
        metadata: dict | None = None,
    ) -> CaptureResult | None:
        if self.pending is None:
            return None
        request_id = self.pending.request.request_id
        result = CaptureResult.detached_force_close(
            request_id,
            metadata=metadata,
            reason=reason,
            source=CaptureSource.COORDINATOR,
        )
        self.last_result = result
        self.reset()
        return result

    def pending_snapshot(self) -> dict:
        pending = self.pending
        if pending is None:
            return {
                "active": False,
                "request": None,
                "request_id": None,
                "callback": None,
                "context": None,
                "started_monotonic": None,
                "recovery_attempted": False,
                "throughput_mode": False,
            }
        return {
            "active": True,
            "request": pending.request,
            "request_id": pending.request.request_id,
            "callback": pending.callback,
            "context": pending.context,
            "started_monotonic": pending.started_monotonic,
            "recovery_attempted": bool(pending.recovery_attempted),
            "throughput_mode": bool(pending.throughput_mode),
        }

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
