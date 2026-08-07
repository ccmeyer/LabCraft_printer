import ast
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from BalanceProtocol import (
    BalanceReading,
    CrlfFramer,
    FrameEventKind,
    FrameRejectReason,
    RecordRejectReason,
    StabilityDetector,
    StabilityPolicy,
    StableMassFailureReason,
    StableMassOutcome,
    StableMassPhase,
    StableMassRequest,
    parse_hpb_record,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "FreeRTOS-interface" / "BalanceProtocol.py"
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "veritas_balance"
    / "hpb625i_serial_samples_v1.json"
)
NS = 1_000_000_000


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _reading(mass, timestamp_ns, stable=True):
    mass = Decimal(str(mass))
    stability = "S" if stable else " "
    return BalanceReading(
        timestamp_ns=int(timestamp_ns),
        display_value=mass,
        mass_mg=mass,
        reported_unit="mg",
        raw_stability=stability,
        device_stable=stable,
        raw_frame=b"synthetic",
    )


def _request(*, started_ns=0, policy=None):
    return StableMassRequest(
        request_id="request-1",
        stream_session_id="session-1",
        phase=StableMassPhase.STARTING,
        started_monotonic_ns=started_ns,
        policy=policy or StabilityPolicy(),
    )


def _feed(detector, samples):
    result = None
    for sample in samples:
        result = detector.add_reading(sample)
        if result is not None:
            break
    return result


def test_every_physical_fixture_excerpt_replays_to_expected_frames_and_readings():
    fixture = _fixture()
    assert fixture["status"] == "verified_physical_capture"

    for capture in fixture["captures"]:
        framer = CrlfFramer()
        events = []
        raw = b""
        for chunk_hex in capture["chunks_hex"]:
            chunk = bytes.fromhex(chunk_hex)
            raw += chunk
            events.extend(framer.feed(chunk))

        assert hashlib.sha256(raw).hexdigest() == capture["excerpt_sha256"]
        assert all(event.kind is FrameEventKind.FRAME for event in events)
        assert [event.payload.decode("ascii") for event in events] == capture[
            "expected_payloads_ascii"
        ]

        rejected_indexes = set(capture["expected_rejected_payload_indexes"])
        readings = []
        for index, event in enumerate(events):
            parsed = parse_hpb_record(event.payload, timestamp_ns=index)
            if index in rejected_indexes:
                assert parsed.accepted is False
                assert parsed.rejection.reason is RecordRejectReason.WRONG_LENGTH
            else:
                assert parsed.accepted is True
                readings.append(
                    [format(parsed.reading.mass_mg, "f"), parsed.reading.device_stable]
                )
        assert readings == capture["expected_readings"]

        incomplete = framer.flush_incomplete()
        expected_tail = capture["expected_remaining_tail_ascii"]
        if expected_tail:
            assert incomplete.kind is FrameEventKind.REJECTED
            assert incomplete.rejection_reason is FrameRejectReason.INCOMPLETE_FRAME
            assert incomplete.payload.decode("ascii") == expected_tail
        else:
            assert incomplete is None


def test_framer_handles_split_terminators_combined_and_empty_frames():
    framer = CrlfFramer()
    assert framer.feed(b"\r") == ()
    events = framer.feed(b"\nabc\r\n\r\npartial")
    assert [event.payload for event in events] == [b"", b"abc", b""]
    assert framer.buffered_byte_count == len(b"partial")
    incomplete = framer.flush_incomplete()
    assert incomplete.payload == b"partial"
    assert incomplete.rejection_reason is FrameRejectReason.INCOMPLETE_FRAME
    assert framer.buffered_byte_count == 0


def test_framer_overflow_is_bounded_and_recovers_at_next_delimiter():
    framer = CrlfFramer(max_buffer_bytes=8)
    events = framer.feed(b"123456789discarded\r\nvalid\r\n")
    assert len(events) == 2
    assert events[0].kind is FrameEventKind.REJECTED
    assert events[0].rejection_reason is FrameRejectReason.BUFFER_OVERFLOW
    assert events[0].payload == b"12345678"
    assert events[1].kind is FrameEventKind.FRAME
    assert events[1].payload == b"valid"
    assert framer.buffered_byte_count == 0
    assert framer.discarding_oversized_frame is False


def test_framer_reset_and_input_validation():
    framer = CrlfFramer()
    framer.feed(memoryview(b"partial"))
    framer.reset()
    assert framer.buffered_byte_count == 0
    assert framer.flush_incomplete() is None
    with pytest.raises(TypeError):
        framer.feed("not bytes")
    with pytest.raises(ValueError):
        CrlfFramer(0)


@pytest.mark.parametrize(
    ("frame", "mass", "stable"),
    [
        (b"     0.00 mgS", Decimal("0.00"), True),
        (b"  1540.57 mgS", Decimal("1540.57"), True),
        (b"- 1540.57 mg ", Decimal("-1540.57"), False),
        (b" 62000.00 mgS", Decimal("62000.00"), True),
    ],
)
def test_parser_accepts_exact_mg_records(frame, mass, stable):
    result = parse_hpb_record(frame, timestamp_ns=123)
    assert result.accepted is True
    assert result.rejection is None
    assert result.reading.timestamp_ns == 123
    assert result.reading.display_value == mass
    assert result.reading.mass_mg == mass
    assert result.reading.reported_unit == "mg"
    assert result.reading.device_stable is stable
    assert result.reading.raw_stability == ("S" if stable else " ")
    assert result.reading.raw_frame == frame


def _changed(base, start, replacement):
    value = bytearray(base)
    value[start : start + len(replacement)] = replacement
    return bytes(value)


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (b"", RecordRejectReason.EMPTY_FRAME),
        (b"short", RecordRejectReason.WRONG_LENGTH),
        (_changed(b"     0.00 mgS", 1, b"\xff"), RecordRejectReason.NON_ASCII),
        (_changed(b"     0.00 mgS", 0, b"+"), RecordRejectReason.INVALID_SIGN),
        (_changed(b"     0.00 mgS", 9, b"_"), RecordRejectReason.INVALID_SEPARATOR),
        (_changed(b"     0.00 mgS", 10, b" g"), RecordRejectReason.UNSUPPORTED_UNIT),
        (_changed(b"     0.00 mgS", 10, b"oz"), RecordRejectReason.UNSUPPORTED_UNIT),
        (_changed(b"     0.00 mgS", 12, b"U"), RecordRejectReason.INVALID_STABILITY),
        (_changed(b"     0.00 mgS", 1, b"  12,345"), RecordRejectReason.INVALID_MAGNITUDE),
        (_changed(b"     0.00 mgS", 1, b"  12.345"), RecordRejectReason.INVALID_MAGNITUDE),
        (_changed(b"     0.00 mgS", 1, b"     NaN"), RecordRejectReason.NON_FINITE),
        (_changed(b"     0.00 mgS", 1, b"      OL"), RecordRejectReason.NON_WEIGHING_STATUS),
    ],
)
def test_parser_returns_typed_rejections(frame, reason):
    result = parse_hpb_record(frame, timestamp_ns=0)
    assert result.accepted is False
    assert result.reading is None
    assert result.rejection.reason is reason
    assert result.rejection.raw_frame == frame


def test_parser_rejects_invalid_caller_inputs():
    with pytest.raises(ValueError):
        parse_hpb_record(b"     0.00 mgS", timestamp_ns=-1)
    with pytest.raises(TypeError):
        parse_hpb_record("     0.00 mgS", timestamp_ns=0)


def test_default_policy_accepts_constant_mass_at_first_eligible_window():
    detector = StabilityDetector(_request())
    samples = [
        _reading("1540.57", NS + index * 150_000_000)
        for index in range(21)
    ]
    assert all(detector.add_reading(sample) is None for sample in samples[:-1])
    result = detector.add_reading(samples[-1])

    assert result.outcome is StableMassOutcome.STABLE
    assert result.completed_monotonic_ns == 4 * NS
    assert result.stable_mass_mg == Decimal("1540.57")
    assert result.evidence.sample_count == 21
    assert result.evidence.window_duration_ns == 3 * NS
    assert result.evidence.span_mg == Decimal("0.00")
    assert result.evidence.population_standard_deviation_mg == 0
    assert result.evidence.fitted_slope_mg_per_second == 0
    assert result.evidence.all_device_stable is True


def test_ignore_period_and_equal_timestamps_cannot_satisfy_duration():
    detector = StabilityDetector(_request())
    for _ in range(20):
        assert detector.add_reading(_reading("1.00", NS - 1)) is None
    for _ in range(20):
        assert detector.add_reading(_reading("1.00", NS)) is None
    assert detector.retained_sample_count == 20
    assert detector.latest_evidence.window_duration_ns == 0


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        ("0.00", "0.03", StableMassOutcome.STABLE),
        ("0.00", "0.04", None),
    ],
)
def test_span_threshold_is_inclusive(low, high, expected):
    policy = StabilityPolicy(
        ignore_period_ns=0,
        minimum_window_ns=NS,
        minimum_samples=2,
        maximum_absolute_slope_mg_per_second=Decimal("1"),
        timeout_ns=5 * NS,
    )
    detector = StabilityDetector(_request(policy=policy))
    assert detector.add_reading(_reading(low, 0)) is None
    result = detector.add_reading(_reading(high, NS))
    assert (result.outcome if result else None) is expected


@pytest.mark.parametrize(
    ("ending_mass", "expected"),
    [
        ("0.01", StableMassOutcome.STABLE),
        ("0.02", None),
    ],
)
def test_slope_threshold_is_inclusive(ending_mass, expected):
    policy = StabilityPolicy(
        ignore_period_ns=0,
        minimum_window_ns=NS,
        minimum_samples=2,
        maximum_span_mg=Decimal("1"),
        timeout_ns=5 * NS,
    )
    detector = StabilityDetector(_request(policy=policy))
    detector.add_reading(_reading("0.00", 0))
    result = detector.add_reading(_reading(ending_mass, NS))
    assert (result.outcome if result else None) is expected


def test_quantized_mean_uses_half_even_and_keeps_unrounded_evidence():
    policy = StabilityPolicy(
        ignore_period_ns=0,
        minimum_window_ns=NS,
        minimum_samples=6,
        maximum_absolute_slope_mg_per_second=Decimal("1"),
        timeout_ns=5 * NS,
    )
    detector = StabilityDetector(_request(policy=policy))
    masses = ["1.00", "1.01"] * 3
    result = _feed(
        detector,
        [_reading(mass, index * 200_000_000) for index, mass in enumerate(masses)],
    )
    assert result.evidence.mean_mass_mg_unrounded == Decimal("1.005")
    assert result.evidence.population_standard_deviation_mg == Decimal("0.005")
    assert result.stable_mass_mg == Decimal("1.00")

    detector = StabilityDetector(_request(policy=policy))
    masses = ["1.01", "1.02"] * 3
    result = _feed(
        detector,
        [_reading(mass, index * 200_000_000) for index, mass in enumerate(masses)],
    )
    assert result.evidence.mean_mass_mg_unrounded == Decimal("1.015")
    assert result.stable_mass_mg == Decimal("1.02")


def test_unstable_status_resets_window_and_requires_new_clean_duration():
    detector = StabilityDetector(_request())
    for index in range(11):
        assert detector.add_reading(_reading("10.00", NS + index * 150_000_000)) is None
    assert detector.add_reading(_reading("10.00", 2_600_000_000, stable=False)) is None
    assert detector.retained_sample_count == 0

    for index in range(20):
        assert detector.add_reading(
            _reading("10.00", 2_750_000_000 + index * 150_000_000)
        ) is None
    result = detector.add_reading(_reading("10.00", 5_750_000_000))
    assert result.outcome is StableMassOutcome.STABLE
    assert result.total_unstable_readings == 1
    assert result.evidence.all_device_stable is True


def test_numeric_drift_is_rejected_even_when_device_reports_stable_then_recovers():
    detector = StabilityDetector(_request())
    timestamp = NS
    for index in range(30):
        result = detector.add_reading(
            _reading(Decimal("20.00") + Decimal(index) * Decimal("0.01"), timestamp)
        )
        assert result is None
        timestamp += 150_000_000

    settled_mass = Decimal("20.29")
    result = None
    while result is None and timestamp < 10 * NS:
        result = detector.add_reading(_reading(settled_mass, timestamp))
        timestamp += 150_000_000
    assert result.outcome is StableMassOutcome.STABLE
    assert result.stable_mass_mg == settled_mass


def test_quiet_unstable_values_never_succeed_until_device_stable_window_rebuilds():
    detector = StabilityDetector(_request())
    timestamp = NS
    for _ in range(30):
        assert detector.add_reading(_reading("5.00", timestamp, stable=False)) is None
        timestamp += 150_000_000
    assert detector.retained_sample_count == 0

    result = None
    while result is None:
        result = detector.add_reading(_reading("5.00", timestamp, stable=True))
        timestamp += 150_000_000
    assert result.outcome is StableMassOutcome.STABLE
    assert result.total_unstable_readings == 30


def test_timeout_retains_evidence_and_is_terminal_idempotent():
    detector = StabilityDetector(_request())
    detector.add_reading(_reading("1.00", NS))
    result = detector.poll(30 * NS)
    assert result.outcome is StableMassOutcome.TIMEOUT
    assert result.failure_reason is StableMassFailureReason.TIMEOUT
    assert result.evidence is not None
    assert detector.poll(31 * NS) is result
    assert detector.cancel(31 * NS) is result
    assert detector.add_reading(_reading("1.00", 31 * NS)) is result


def test_reading_at_deadline_times_out_without_becoming_a_sample():
    detector = StabilityDetector(_request())
    result = detector.add_reading(_reading("1.00", 30 * NS))
    assert result.outcome is StableMassOutcome.TIMEOUT
    assert result.total_readings_seen == 0


def test_cancellation_retains_latest_evidence_and_identity():
    request = StableMassRequest(
        request_id="ending-request",
        stream_session_id="stream-session",
        phase=StableMassPhase.ENDING,
        started_monotonic_ns=10,
    )
    detector = StabilityDetector(request)
    detector.add_reading(_reading("1.00", NS + 10))
    result = detector.cancel(2 * NS)
    assert result.outcome is StableMassOutcome.CANCELLED
    assert result.failure_reason is StableMassFailureReason.CANCELLED
    assert result.request_id == "ending-request"
    assert result.stream_session_id == "stream-session"
    assert result.phase is StableMassPhase.ENDING
    assert result.evidence is not None
    assert detector.cancel(3 * NS) is result


@pytest.mark.parametrize(
    "failure_reason",
    (
        StableMassFailureReason.TRANSPORT_ERROR,
        StableMassFailureReason.SERVICE_ERROR,
    ),
)
def test_external_failure_retains_evidence_counts_and_is_terminal(
    failure_reason,
):
    detector = StabilityDetector(_request())
    detector.add_reading(_reading("1.00", NS))

    result = detector.fail(2 * NS, failure_reason, "source failed")

    assert result.outcome is StableMassOutcome.ERROR
    assert result.failure_reason is failure_reason
    assert result.detail == "source failed"
    assert result.evidence is not None
    assert result.total_readings_seen == 1
    assert detector.fail(3 * NS, StableMassFailureReason.SERVICE_ERROR, "late") is result
    assert detector.cancel(3 * NS) is result


def test_external_failure_validates_reason_and_timestamp():
    detector = StabilityDetector(_request(started_ns=100))
    with pytest.raises(ValueError, match="predates"):
        detector.fail(99, StableMassFailureReason.TRANSPORT_ERROR, "read failed")
    with pytest.raises(ValueError, match="failure_reason"):
        detector.fail(100, StableMassFailureReason.TIMEOUT, "wrong reason")


def test_sample_limit_returns_typed_error():
    policy = StabilityPolicy(
        ignore_period_ns=0,
        minimum_window_ns=3 * NS,
        minimum_samples=10,
        timeout_ns=10 * NS,
        maximum_retained_samples=10,
    )
    detector = StabilityDetector(_request(policy=policy))
    for _ in range(10):
        assert detector.add_reading(_reading("1.00", 0)) is None
    result = detector.add_reading(_reading("1.00", 0))
    assert result.outcome is StableMassOutcome.ERROR
    assert result.failure_reason is StableMassFailureReason.SAMPLE_LIMIT_EXCEEDED
    assert detector.add_reading(_reading("1.00", 0)) is result


def test_out_of_order_and_pre_request_timestamps_are_rejected():
    detector = StabilityDetector(_request(started_ns=100))
    with pytest.raises(ValueError, match="predates"):
        detector.add_reading(_reading("1.00", 99))
    detector.add_reading(_reading("1.00", 200))
    with pytest.raises(ValueError, match="nondecreasing"):
        detector.add_reading(_reading("1.00", 199))
    with pytest.raises(ValueError, match="predates"):
        detector.poll(99)


def test_request_policy_and_reading_invariants_are_validated():
    with pytest.raises(ValueError):
        _request(policy=StabilityPolicy(minimum_samples=0))
    with pytest.raises(ValueError):
        StabilityPolicy(timeout_ns=4 * NS, ignore_period_ns=NS, minimum_window_ns=3 * NS)
    with pytest.raises(ValueError):
        StableMassRequest("", "session", StableMassPhase.STARTING, 0)
    with pytest.raises(ValueError):
        BalanceReading(0, Decimal("1"), Decimal("1"), "g", "S", True, b"")
    with pytest.raises(ValueError):
        BalanceReading(0, Decimal("1"), Decimal("1"), "mg", "S", False, b"")


def test_module_is_pure_and_has_no_hardware_or_application_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {
            "PySide6",
            "serial",
            "Controller",
            "Model",
            "Machine_FreeRTOS",
            "ApplicationComposition",
            "legacy",
            "cv2",
            "firmware",
        }
    )
