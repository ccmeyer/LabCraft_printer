"""Pure protocol and stability primitives for the Veritas HPB-625i.

The module intentionally has no Qt, serial-port, application, machine, or
firmware dependencies.  Transport ownership belongs to ``BalanceService`` in
a later implementation slice.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from enum import Enum
from typing import Iterable


NANOSECONDS_PER_SECOND = 1_000_000_000
HPB_PAYLOAD_BYTES = 13
HPB_TERMINATOR = b"\r\n"
HPB_UNIT = "mg"
HPB_STABLE_FIELD = "S"
HPB_UNSTABLE_FIELD = " "


class FrameEventKind(str, Enum):
    FRAME = "frame"
    REJECTED = "rejected"


class FrameRejectReason(str, Enum):
    BUFFER_OVERFLOW = "buffer_overflow"
    INCOMPLETE_FRAME = "incomplete_frame"


@dataclass(frozen=True)
class FrameEvent:
    kind: FrameEventKind
    payload: bytes
    rejection_reason: FrameRejectReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes):
            raise TypeError("FrameEvent payload must be bytes")
        if self.kind is FrameEventKind.FRAME:
            if self.rejection_reason is not None:
                raise ValueError("frame event cannot have a rejection reason")
        elif self.kind is FrameEventKind.REJECTED:
            if self.rejection_reason is None:
                raise ValueError("rejected frame event requires a reason")
        else:  # defensive if constructed with a non-enum value
            raise ValueError(f"unsupported frame event kind: {self.kind!r}")

    @classmethod
    def frame(cls, payload: bytes) -> "FrameEvent":
        return cls(FrameEventKind.FRAME, bytes(payload))

    @classmethod
    def rejected(
        cls, payload: bytes, reason: FrameRejectReason
    ) -> "FrameEvent":
        return cls(FrameEventKind.REJECTED, bytes(payload), reason)


class CrlfFramer:
    """Bounded CR/LF framer that recovers after oversized input."""

    def __init__(self, max_buffer_bytes: int = 256):
        if isinstance(max_buffer_bytes, bool) or int(max_buffer_bytes) <= 0:
            raise ValueError("max_buffer_bytes must be a positive integer")
        self.max_buffer_bytes = int(max_buffer_bytes)
        self._buffer = bytearray()
        self._discarding = False
        self._discard_previous_was_cr = False

    @property
    def buffered_byte_count(self) -> int:
        return len(self._buffer)

    @property
    def discarding_oversized_frame(self) -> bool:
        return self._discarding

    def reset(self) -> None:
        self._buffer.clear()
        self._discarding = False
        self._discard_previous_was_cr = False

    def feed(self, data: bytes | bytearray | memoryview) -> tuple[FrameEvent, ...]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("framer input must be bytes-like")
        events: list[FrameEvent] = []
        for value in bytes(data):
            if self._discarding:
                if self._discard_previous_was_cr and value == 0x0A:
                    self._discarding = False
                    self._discard_previous_was_cr = False
                else:
                    self._discard_previous_was_cr = value == 0x0D
                continue

            self._buffer.append(value)
            if self._buffer.endswith(HPB_TERMINATOR):
                events.append(FrameEvent.frame(bytes(self._buffer[:-2])))
                self._buffer.clear()
                continue

            if len(self._buffer) > self.max_buffer_bytes:
                preview = bytes(self._buffer[: self.max_buffer_bytes])
                overflow_value_was_cr = value == 0x0D
                self._buffer.clear()
                self._discarding = True
                self._discard_previous_was_cr = overflow_value_was_cr
                events.append(
                    FrameEvent.rejected(preview, FrameRejectReason.BUFFER_OVERFLOW)
                )
        return tuple(events)

    def flush_incomplete(self) -> FrameEvent | None:
        if self._discarding:
            self.reset()
            return None
        if not self._buffer:
            return None
        payload = bytes(self._buffer)
        self._buffer.clear()
        return FrameEvent.rejected(payload, FrameRejectReason.INCOMPLETE_FRAME)


class RecordRejectReason(str, Enum):
    EMPTY_FRAME = "empty_frame"
    WRONG_LENGTH = "wrong_length"
    NON_ASCII = "non_ascii"
    INVALID_SIGN = "invalid_sign"
    INVALID_SEPARATOR = "invalid_separator"
    UNSUPPORTED_UNIT = "unsupported_unit"
    INVALID_STABILITY = "invalid_stability"
    INVALID_MAGNITUDE = "invalid_magnitude"
    NON_FINITE = "non_finite"
    NON_WEIGHING_STATUS = "non_weighing_status"


@dataclass(frozen=True)
class RecordRejection:
    reason: RecordRejectReason
    raw_frame: bytes
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.raw_frame, bytes):
            raise TypeError("RecordRejection raw_frame must be bytes")


@dataclass(frozen=True)
class BalanceReading:
    timestamp_ns: int
    display_value: Decimal
    mass_mg: Decimal
    reported_unit: str
    raw_stability: str
    device_stable: bool
    raw_frame: bytes

    def __post_init__(self) -> None:
        _validate_timestamp(self.timestamp_ns, "BalanceReading timestamp_ns")
        if not isinstance(self.display_value, Decimal) or not self.display_value.is_finite():
            raise ValueError("BalanceReading display_value must be a finite Decimal")
        if not isinstance(self.mass_mg, Decimal) or not self.mass_mg.is_finite():
            raise ValueError("BalanceReading mass_mg must be a finite Decimal")
        if self.reported_unit != HPB_UNIT:
            raise ValueError("BalanceReading reported_unit must be mg")
        if self.raw_stability not in (HPB_STABLE_FIELD, HPB_UNSTABLE_FIELD):
            raise ValueError("BalanceReading raw_stability is invalid")
        if self.device_stable is not (self.raw_stability == HPB_STABLE_FIELD):
            raise ValueError("BalanceReading stability fields disagree")
        if not isinstance(self.raw_frame, bytes):
            raise TypeError("BalanceReading raw_frame must be bytes")


@dataclass(frozen=True)
class BalanceParseResult:
    reading: BalanceReading | None = None
    rejection: RecordRejection | None = None

    def __post_init__(self) -> None:
        if (self.reading is None) == (self.rejection is None):
            raise ValueError("parse result requires exactly one of reading or rejection")

    @property
    def accepted(self) -> bool:
        return self.reading is not None


_MAGNITUDE_PATTERN = re.compile(rb" *[0-9]{1,5}\.[0-9]{2}")
_NON_FINITE_TEXT = frozenset({b"nan", b"inf", b"infinity"})


def _validate_timestamp(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")


def _rejected(
    reason: RecordRejectReason, raw_frame: bytes, detail: str = ""
) -> BalanceParseResult:
    return BalanceParseResult(
        rejection=RecordRejection(reason=reason, raw_frame=raw_frame, detail=detail)
    )


def parse_hpb_record(
    frame: bytes | bytearray | memoryview, timestamp_ns: int
) -> BalanceParseResult:
    """Parse one terminator-free HPB payload without raising for device data."""
    _validate_timestamp(timestamp_ns, "timestamp_ns")
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise TypeError("frame must be bytes-like")
    raw = bytes(frame)
    if not raw:
        return _rejected(RecordRejectReason.EMPTY_FRAME, raw)
    if len(raw) != HPB_PAYLOAD_BYTES:
        return _rejected(
            RecordRejectReason.WRONG_LENGTH,
            raw,
            f"expected {HPB_PAYLOAD_BYTES} bytes, received {len(raw)}",
        )
    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        return _rejected(RecordRejectReason.NON_ASCII, raw)

    sign = raw[0:1]
    if sign not in (b" ", b"-"):
        return _rejected(RecordRejectReason.INVALID_SIGN, raw)
    if raw[9:10] != b" ":
        return _rejected(RecordRejectReason.INVALID_SEPARATOR, raw)
    if raw[10:12] != b"mg":
        return _rejected(
            RecordRejectReason.UNSUPPORTED_UNIT,
            raw,
            raw[10:12].decode("ascii", errors="replace"),
        )
    stability = raw[12:13]
    if stability not in (b"S", b" "):
        return _rejected(RecordRejectReason.INVALID_STABILITY, raw)

    magnitude_field = raw[1:9]
    normalized_magnitude = magnitude_field.strip().lower()
    if normalized_magnitude in _NON_FINITE_TEXT:
        return _rejected(RecordRejectReason.NON_FINITE, raw)
    if not _MAGNITUDE_PATTERN.fullmatch(magnitude_field):
        if any(
            (ord("A") <= value <= ord("Z")) or (ord("a") <= value <= ord("z"))
            for value in magnitude_field
        ):
            return _rejected(RecordRejectReason.NON_WEIGHING_STATUS, raw)
        return _rejected(RecordRejectReason.INVALID_MAGNITUDE, raw)

    try:
        magnitude = Decimal(magnitude_field.decode("ascii").strip())
    except InvalidOperation:
        return _rejected(RecordRejectReason.INVALID_MAGNITUDE, raw)
    if not magnitude.is_finite():
        return _rejected(RecordRejectReason.NON_FINITE, raw)
    value = -magnitude if sign == b"-" else magnitude
    stable = stability == b"S"
    reading = BalanceReading(
        timestamp_ns=timestamp_ns,
        display_value=value,
        mass_mg=value,
        reported_unit=HPB_UNIT,
        raw_stability=stability.decode("ascii"),
        device_stable=stable,
        raw_frame=raw,
    )
    return BalanceParseResult(reading=reading)


class StableMassPhase(str, Enum):
    STARTING = "starting"
    ENDING = "ending"


class StableMassOutcome(str, Enum):
    STABLE = "stable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


class StableMassFailureReason(str, Enum):
    NONE = "none"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SAMPLE_LIMIT_EXCEEDED = "sample_limit_exceeded"


def _as_decimal(value: Decimal | int | float | str, label: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be a finite decimal")
    return result


@dataclass(frozen=True)
class StabilityPolicy:
    ignore_period_ns: int = NANOSECONDS_PER_SECOND
    minimum_window_ns: int = 3 * NANOSECONDS_PER_SECOND
    minimum_samples: int = 10
    maximum_span_mg: Decimal = Decimal("0.03")
    maximum_absolute_slope_mg_per_second: Decimal = Decimal("0.01")
    timeout_ns: int = 30 * NANOSECONDS_PER_SECOND
    require_every_sample_device_stable: bool = True
    maximum_retained_samples: int = 512
    display_resolution_mg: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        for name in ("ignore_period_ns", "minimum_window_ns", "timeout_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.minimum_window_ns <= 0:
            raise ValueError("minimum_window_ns must be positive")
        if self.timeout_ns <= self.ignore_period_ns + self.minimum_window_ns:
            raise ValueError("timeout must exceed ignore period plus minimum window")
        if isinstance(self.minimum_samples, bool) or int(self.minimum_samples) <= 0:
            raise ValueError("minimum_samples must be positive")
        if (
            isinstance(self.maximum_retained_samples, bool)
            or int(self.maximum_retained_samples) <= 0
        ):
            raise ValueError("maximum_retained_samples must be positive")
        if self.maximum_retained_samples < self.minimum_samples:
            raise ValueError("maximum_retained_samples cannot be below minimum_samples")
        span = _as_decimal(self.maximum_span_mg, "maximum_span_mg")
        slope = _as_decimal(
            self.maximum_absolute_slope_mg_per_second,
            "maximum_absolute_slope_mg_per_second",
        )
        resolution = _as_decimal(self.display_resolution_mg, "display_resolution_mg")
        if span < 0 or slope < 0 or resolution <= 0:
            raise ValueError("stability mass thresholds must be nonnegative and resolution positive")
        object.__setattr__(self, "maximum_span_mg", span)
        object.__setattr__(self, "maximum_absolute_slope_mg_per_second", slope)
        object.__setattr__(self, "display_resolution_mg", resolution)
        object.__setattr__(self, "minimum_samples", int(self.minimum_samples))
        object.__setattr__(
            self, "maximum_retained_samples", int(self.maximum_retained_samples)
        )
        object.__setattr__(
            self,
            "require_every_sample_device_stable",
            bool(self.require_every_sample_device_stable),
        )


@dataclass(frozen=True)
class StableMassRequest:
    request_id: str
    stream_session_id: str
    phase: StableMassPhase
    started_monotonic_ns: int
    policy: StabilityPolicy = StabilityPolicy()

    def __post_init__(self) -> None:
        if not str(self.request_id).strip():
            raise ValueError("StableMassRequest requires request_id")
        if not str(self.stream_session_id).strip():
            raise ValueError("StableMassRequest requires stream_session_id")
        phase = self.phase if isinstance(self.phase, StableMassPhase) else StableMassPhase(self.phase)
        _validate_timestamp(self.started_monotonic_ns, "started_monotonic_ns")
        if not isinstance(self.policy, StabilityPolicy):
            raise TypeError("policy must be StabilityPolicy")
        object.__setattr__(self, "request_id", str(self.request_id))
        object.__setattr__(self, "stream_session_id", str(self.stream_session_id))
        object.__setattr__(self, "phase", phase)


@dataclass(frozen=True)
class StabilityEvidence:
    sample_count: int
    window_started_ns: int
    window_ended_ns: int
    window_duration_ns: int
    mean_mass_mg_unrounded: Decimal
    quantized_mean_mass_mg: Decimal
    minimum_mass_mg: Decimal
    maximum_mass_mg: Decimal
    span_mg: Decimal
    population_standard_deviation_mg: Decimal
    fitted_slope_mg_per_second: Decimal
    device_stable_sample_count: int
    device_unstable_sample_count: int
    all_device_stable: bool


@dataclass(frozen=True)
class StableMassResult:
    request_id: str
    stream_session_id: str
    phase: StableMassPhase
    outcome: StableMassOutcome
    completed_monotonic_ns: int
    stable_mass_mg: Decimal | None
    evidence: StabilityEvidence | None
    failure_reason: StableMassFailureReason
    detail: str
    total_readings_seen: int
    total_stable_readings: int
    total_unstable_readings: int

    def __post_init__(self) -> None:
        _validate_timestamp(self.completed_monotonic_ns, "completed_monotonic_ns")
        if self.outcome is StableMassOutcome.STABLE:
            if self.stable_mass_mg is None or self.evidence is None:
                raise ValueError("stable result requires mass and evidence")
            if self.failure_reason is not StableMassFailureReason.NONE:
                raise ValueError("stable result cannot have a failure reason")
        else:
            if self.stable_mass_mg is not None:
                raise ValueError("non-stable result cannot carry stable mass")
            if self.failure_reason is StableMassFailureReason.NONE:
                raise ValueError("non-stable result requires a failure reason")


def _quantized_mean(mean: Decimal, resolution: Decimal) -> Decimal:
    value = mean.quantize(resolution, rounding=ROUND_HALF_EVEN)
    return abs(value) if value == 0 else value


def _calculate_evidence(
    samples: Iterable[BalanceReading], policy: StabilityPolicy
) -> StabilityEvidence:
    values = tuple(samples)
    if not values:
        raise ValueError("stability evidence requires at least one sample")
    with localcontext() as context:
        context.prec = 28
        count = len(values)
        masses = tuple(sample.mass_mg for sample in values)
        mean = sum(masses, Decimal(0)) / Decimal(count)
        minimum = min(masses)
        maximum = max(masses)
        span = maximum - minimum
        variance = sum((mass - mean) ** 2 for mass in masses) / Decimal(count)
        standard_deviation = variance.sqrt()

        origin_ns = values[0].timestamp_ns
        times = tuple(
            Decimal(sample.timestamp_ns - origin_ns) / Decimal(NANOSECONDS_PER_SECOND)
            for sample in values
        )
        time_mean = sum(times, Decimal(0)) / Decimal(count)
        denominator = sum((value - time_mean) ** 2 for value in times)
        if denominator == 0:
            slope = Decimal(0)
        else:
            slope = sum(
                (time_value - time_mean) * (mass - mean)
                for time_value, mass in zip(times, masses)
            ) / denominator

        stable_count = sum(1 for sample in values if sample.device_stable)
        unstable_count = count - stable_count
        return StabilityEvidence(
            sample_count=count,
            window_started_ns=values[0].timestamp_ns,
            window_ended_ns=values[-1].timestamp_ns,
            window_duration_ns=values[-1].timestamp_ns - values[0].timestamp_ns,
            mean_mass_mg_unrounded=mean,
            quantized_mean_mass_mg=_quantized_mean(mean, policy.display_resolution_mg),
            minimum_mass_mg=minimum,
            maximum_mass_mg=maximum,
            span_mg=span,
            population_standard_deviation_mg=standard_deviation,
            fitted_slope_mg_per_second=slope,
            device_stable_sample_count=stable_count,
            device_unstable_sample_count=unstable_count,
            all_device_stable=unstable_count == 0,
        )


class StabilityDetector:
    """Pure, single-request stability detector with terminal idempotency."""

    def __init__(self, request: StableMassRequest):
        if not isinstance(request, StableMassRequest):
            raise TypeError("request must be StableMassRequest")
        self.request = request
        self._samples: deque[BalanceReading] = deque()
        self._terminal_result: StableMassResult | None = None
        self._last_reading_timestamp_ns: int | None = None
        self._latest_evidence: StabilityEvidence | None = None
        self._total_readings_seen = 0
        self._total_stable_readings = 0
        self._total_unstable_readings = 0

    @property
    def terminal_result(self) -> StableMassResult | None:
        return self._terminal_result

    @property
    def latest_evidence(self) -> StabilityEvidence | None:
        return self._latest_evidence

    @property
    def retained_sample_count(self) -> int:
        return len(self._samples)

    def _result(
        self,
        *,
        outcome: StableMassOutcome,
        completed_ns: int,
        failure_reason: StableMassFailureReason,
        stable_mass_mg: Decimal | None = None,
        evidence: StabilityEvidence | None = None,
        detail: str = "",
    ) -> StableMassResult:
        result = StableMassResult(
            request_id=self.request.request_id,
            stream_session_id=self.request.stream_session_id,
            phase=self.request.phase,
            outcome=outcome,
            completed_monotonic_ns=completed_ns,
            stable_mass_mg=stable_mass_mg,
            evidence=evidence,
            failure_reason=failure_reason,
            detail=str(detail),
            total_readings_seen=self._total_readings_seen,
            total_stable_readings=self._total_stable_readings,
            total_unstable_readings=self._total_unstable_readings,
        )
        self._terminal_result = result
        return result

    def _timeout(self, now_ns: int) -> StableMassResult:
        return self._result(
            outcome=StableMassOutcome.TIMEOUT,
            completed_ns=now_ns,
            failure_reason=StableMassFailureReason.TIMEOUT,
            evidence=self._latest_evidence,
            detail="stable mass request deadline reached",
        )

    def add_reading(self, reading: BalanceReading) -> StableMassResult | None:
        if self._terminal_result is not None:
            return self._terminal_result
        if not isinstance(reading, BalanceReading):
            raise TypeError("reading must be BalanceReading")
        if reading.timestamp_ns < self.request.started_monotonic_ns:
            raise ValueError("reading timestamp predates the request")
        if (
            self._last_reading_timestamp_ns is not None
            and reading.timestamp_ns < self._last_reading_timestamp_ns
        ):
            raise ValueError("reading timestamps must be nondecreasing")
        self._last_reading_timestamp_ns = reading.timestamp_ns

        deadline_ns = self.request.started_monotonic_ns + self.request.policy.timeout_ns
        if reading.timestamp_ns >= deadline_ns:
            return self._timeout(reading.timestamp_ns)

        self._total_readings_seen += 1
        if reading.device_stable:
            self._total_stable_readings += 1
        else:
            self._total_unstable_readings += 1

        ignore_until_ns = (
            self.request.started_monotonic_ns + self.request.policy.ignore_period_ns
        )
        if reading.timestamp_ns < ignore_until_ns:
            return None

        if (
            self.request.policy.require_every_sample_device_stable
            and not reading.device_stable
        ):
            self._samples.clear()
            return None

        self._samples.append(reading)
        cutoff_ns = reading.timestamp_ns - self.request.policy.minimum_window_ns
        while (
            len(self._samples) >= 2
            and self._samples[1].timestamp_ns <= cutoff_ns
        ):
            self._samples.popleft()

        if len(self._samples) > self.request.policy.maximum_retained_samples:
            return self._result(
                outcome=StableMassOutcome.ERROR,
                completed_ns=reading.timestamp_ns,
                failure_reason=StableMassFailureReason.SAMPLE_LIMIT_EXCEEDED,
                evidence=self._latest_evidence,
                detail="retained stability sample limit exceeded",
            )

        evidence = _calculate_evidence(self._samples, self.request.policy)
        self._latest_evidence = evidence
        if evidence.sample_count < self.request.policy.minimum_samples:
            return None
        if evidence.window_duration_ns < self.request.policy.minimum_window_ns:
            return None
        if evidence.span_mg > self.request.policy.maximum_span_mg:
            return None
        if (
            abs(evidence.fitted_slope_mg_per_second)
            > self.request.policy.maximum_absolute_slope_mg_per_second
        ):
            return None
        if (
            self.request.policy.require_every_sample_device_stable
            and not evidence.all_device_stable
        ):
            return None
        return self._result(
            outcome=StableMassOutcome.STABLE,
            completed_ns=reading.timestamp_ns,
            failure_reason=StableMassFailureReason.NONE,
            stable_mass_mg=evidence.quantized_mean_mass_mg,
            evidence=evidence,
        )

    def poll(self, now_ns: int) -> StableMassResult | None:
        if self._terminal_result is not None:
            return self._terminal_result
        _validate_timestamp(now_ns, "now_ns")
        if now_ns < self.request.started_monotonic_ns:
            raise ValueError("poll timestamp predates the request")
        deadline_ns = self.request.started_monotonic_ns + self.request.policy.timeout_ns
        if now_ns >= deadline_ns:
            return self._timeout(now_ns)
        return None

    def cancel(self, now_ns: int) -> StableMassResult:
        if self._terminal_result is not None:
            return self._terminal_result
        _validate_timestamp(now_ns, "now_ns")
        if now_ns < self.request.started_monotonic_ns:
            raise ValueError("cancellation timestamp predates the request")
        return self._result(
            outcome=StableMassOutcome.CANCELLED,
            completed_ns=now_ns,
            failure_reason=StableMassFailureReason.CANCELLED,
            evidence=self._latest_evidence,
            detail="stable mass request cancelled",
        )


__all__ = [
    "BalanceParseResult",
    "BalanceReading",
    "CrlfFramer",
    "FrameEvent",
    "FrameEventKind",
    "FrameRejectReason",
    "HPB_PAYLOAD_BYTES",
    "RecordRejection",
    "RecordRejectReason",
    "StabilityDetector",
    "StabilityEvidence",
    "StabilityPolicy",
    "StableMassFailureReason",
    "StableMassOutcome",
    "StableMassPhase",
    "StableMassRequest",
    "StableMassResult",
    "parse_hpb_record",
]
