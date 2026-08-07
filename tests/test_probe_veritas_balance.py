import ast
import hashlib
import importlib.util
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "probe_veritas_balance.py"
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "veritas_balance"
    / "hpb625i_serial_samples_v1.json"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("probe_veritas_balance_test", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_tool()


class FakeClock:
    def __init__(self):
        self.now_ns = 1_000_000_000

    def __call__(self):
        return self.now_ns

    def advance(self, nanoseconds=100_000_000):
        self.now_ns += nanoseconds


class FakeSerial:
    """Receive-only fake: intentionally does not implement write()."""

    def __init__(self, clock, reads):
        self.clock = clock
        self.reads = list(reads)
        self.read_sizes = []
        self.closed = False

    def read(self, size):
        self.read_sizes.append(size)
        self.clock.advance()
        value = self.reads.pop(0) if self.reads else b""
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, handle=None, error=None):
        self.handle = handle
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.handle


def _port(vid=0x067B, pid=0x2303, device="/dev/ttyUSB9"):
    return SimpleNamespace(
        device=device,
        name=Path(device).name,
        description="Prolific USB-to-Serial Comm Port",
        hwid=f"USB VID:PID={vid:04X}:{pid:04X}",
        vid=vid,
        pid=pid,
        serial_number="TEST-SERIAL",
        manufacturer="Prolific",
        product="USB-Serial Controller",
        location="1-1",
        interface=None,
    )


def _capture(tmp_path, reads, **overrides):
    clock = overrides.pop("clock", FakeClock())
    handle = overrides.pop("handle", FakeSerial(clock, reads))
    factory = overrides.pop("factory", FakeFactory(handle=handle))
    kwargs = {
        "port": "/dev/ttyUSB9",
        "expected_vid_pid": "067b:2303",
        "scenario": "stable_loaded",
        "duration_seconds": 0.21,
        "display_reading": "1.23456 g",
        "output_root": tmp_path,
        "port_entries": [_port()],
        "serial_factory": factory,
        "monotonic_ns": clock,
        "utc_now": lambda: datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    result = probe.capture_serial(**kwargs)
    return result, handle, factory


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_capture_requires_explicit_port_and_usb_identity():
    parser = probe.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["capture", "--scenario", "stable_zero", "--duration", "1"]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "capture",
                "--port",
                "/dev/ttyUSB9",
                "--scenario",
                "stable_zero",
                "--duration",
                "1",
            ]
        )


def test_identity_mismatch_is_rejected_before_open(tmp_path):
    factory = FakeFactory(handle=object())
    with pytest.raises(ValueError, match="identity mismatch"):
        probe.capture_serial(
            port="/dev/ttyUSB9",
            expected_vid_pid="10c4:ea60",
            scenario="stable_zero",
            duration_seconds=1,
            output_root=tmp_path,
            port_entries=[_port()],
            serial_factory=factory,
        )
    assert factory.calls == []
    assert list(tmp_path.iterdir()) == []


def test_ports_command_lists_without_opening(monkeypatch, capsys):
    class FakeListPorts:
        @staticmethod
        def comports():
            return [_port()]

    class MustNotOpen:
        def __call__(self, **_kwargs):
            raise AssertionError("ports command opened a serial port")

    monkeypatch.setattr(probe, "list_ports", FakeListPorts())
    monkeypatch.setattr(probe, "serial", SimpleNamespace(Serial=MustNotOpen()))
    assert probe.main(["ports", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["vid_pid"] == "067b:2303"


def test_capture_preserves_chunks_markers_hash_and_settings(tmp_path):
    chunks = [b"+  1.23456 g S\r\n+  1.23457 g S\r\n", b"partial"]
    (result, handle, factory) = _capture(
        tmp_path,
        chunks,
        marker_stream=io.StringIO("display stable icon on\nsample untouched\n"),
    )
    exit_code, run_dir = result

    assert exit_code == 0
    assert run_dir is not None
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows = _read_jsonl(run_dir / "chunks.jsonl")
    markers = _read_jsonl(run_dir / "markers.jsonl")
    combined = b"".join(chunks)

    assert [row["data_hex"] for row in rows] == [chunk.hex() for chunk in chunks]
    assert [row["byte_count"] for row in rows] == [len(chunk) for chunk in chunks]
    assert rows[0]["elapsed_ns"] <= rows[1]["elapsed_ns"]
    assert manifest["sha256"] == hashlib.sha256(combined).hexdigest()
    assert manifest["byte_count"] == len(combined)
    assert manifest["chunk_count"] == 2
    assert manifest["marker_count"] == 2
    assert [marker["text"] for marker in markers] == [
        "display stable icon on",
        "sample untouched",
    ]
    assert manifest["outcome"] == "scheduled_capture_complete"
    assert factory.calls == [
        {
            "port": "/dev/ttyUSB9",
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "timeout": 0.1,
            "xonxoff": False,
            "rtscts": False,
            "dsrdtr": False,
        }
    ]
    assert handle.closed is True
    assert not hasattr(handle, "write")


def test_empty_capture_returns_two_and_creates_empty_artifacts(tmp_path):
    (result, handle, _factory) = _capture(tmp_path, [])
    exit_code, run_dir = result
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert exit_code == 2
    assert manifest["outcome"] == "scheduled_capture_complete_no_data"
    assert manifest["sha256"] == hashlib.sha256(b"").hexdigest()
    assert (run_dir / "chunks.jsonl").read_bytes() == b""
    assert (run_dir / "markers.jsonl").read_bytes() == b""
    assert handle.closed is True


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_outcome"),
    [
        (OSError("adapter unplugged"), 3, "serial_error"),
        (KeyboardInterrupt(), 130, "operator_interrupted"),
    ],
)
def test_disconnect_and_interrupt_finalize_partial_evidence(
    tmp_path, failure, expected_code, expected_outcome
):
    (result, handle, _factory) = _capture(tmp_path, [b"first", failure])
    exit_code, run_dir = result
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert exit_code == expected_code
    assert manifest["outcome"] == expected_outcome
    assert manifest["byte_count"] == 5
    assert _read_jsonl(run_dir / "chunks.jsonl")[0]["data_hex"] == b"first".hex()
    assert handle.closed is True


def test_open_error_still_finalizes_all_artifacts(tmp_path):
    clock = FakeClock()
    factory = FakeFactory(error=OSError("busy"))
    (result, _handle, _factory) = _capture(
        tmp_path, [], clock=clock, handle=None, factory=factory
    )
    exit_code, run_dir = result
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert exit_code == 3
    assert manifest["outcome"] == "open_error"
    assert "busy" in manifest["error"]
    assert (run_dir / "chunks.jsonl").exists()
    assert (run_dir / "markers.jsonl").exists()


def test_capture_honors_byte_bound_without_splitting_requested_limit(tmp_path):
    (result, handle, _factory) = _capture(
        tmp_path,
        [b"abc"],
        max_capture_bytes=3,
        duration_seconds=1,
    )
    exit_code, run_dir = result
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    assert exit_code == 3
    assert handle.read_sizes[0] == 3
    assert manifest["outcome"] == "maximum_bytes_reached"
    assert manifest["byte_count"] == 3


def test_argument_and_capture_limits_are_validated(tmp_path):
    with pytest.raises(ValueError, match="duration"):
        probe.capture_serial(
            port="/dev/ttyUSB9",
            expected_vid_pid="067b:2303",
            scenario="stable_zero",
            duration_seconds=0,
            output_root=tmp_path,
            port_entries=[_port()],
            serial_factory=FakeFactory(),
        )
    with pytest.raises(ValueError, match="read size"):
        probe.capture_serial(
            port="/dev/ttyUSB9",
            expected_vid_pid="067b:2303",
            scenario="stable_zero",
            duration_seconds=1,
            read_size=0,
            output_root=tmp_path,
            port_entries=[_port()],
            serial_factory=FakeFactory(),
        )


def test_tool_is_isolated_from_application_and_qt_imports():
    source = TOOL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots.isdisjoint(
        {"PySide6", "Controller", "Model", "Machine_FreeRTOS", "BalanceService"}
    )


def test_physical_fixture_preserves_golden_bytes_and_expected_readings():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "labcraft.veritas_balance_fixture"
    assert payload["schema_version"] == 1
    assert payload["status"] == "verified_physical_capture"
    assert payload["operator_markers"]["used_for_protocol_or_threshold_results"] is False
    assert payload["record_contract"]["stability"] == {
        "offset": 12,
        "width": 1,
        "stable": "S",
        "unstable": " ",
    }

    captures = {capture["id"]: capture for capture in payload["captures"]}
    assert set(captures) == {
        "stream_start_mid_record",
        "stable_loaded",
        "unstable_removal_transition",
        "negative_status_transition",
        "fragmented_stable_loaded",
        "stream_end_mid_record",
        "disconnect_at_record_boundary",
    }

    for capture in captures.values():
        assert len(capture["source_run_sha256"]) == 64
        raw = b"".join(bytes.fromhex(chunk) for chunk in capture["chunks_hex"])
        assert hashlib.sha256(raw).hexdigest() == capture["excerpt_sha256"]
        segments = raw.split(b"\r\n")
        assert [part.decode("ascii") for part in segments[:-1]] == capture[
            "expected_payloads_ascii"
        ]
        assert segments[-1].decode("ascii") == capture["expected_remaining_tail_ascii"]

        rejected = set(capture["expected_rejected_payload_indexes"])
        readings = []
        for index, record in enumerate(capture["expected_payloads_ascii"]):
            if index in rejected:
                continue
            assert len(record) == 13
            assert record[9:12] == " mg"
            magnitude = Decimal(record[1:9].strip())
            mass_mg = -magnitude if record[0] == "-" else magnitude
            readings.append([format(mass_mg, "f"), record[12] == "S"])
        assert readings == capture["expected_readings"]

    fragmented = captures["fragmented_stable_loaded"]
    assert all(len(bytes.fromhex(chunk)) == 3 for chunk in fragmented["chunks_hex"])
    assert captures["stream_start_mid_record"]["expected_rejected_payload_indexes"] == [0]
    assert captures["stream_end_mid_record"]["expected_remaining_tail_ascii"]
    assert captures["disconnect_at_record_boundary"]["source_run_outcome"] == "serial_error"
