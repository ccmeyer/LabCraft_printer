#!/usr/bin/env python3
"""Receive-only serial characterization probe for the Veritas HPB-625i.

This tool deliberately has no dependency on the LabCraft application.  It
enumerates an explicitly selected USB serial adapter and records raw read
boundaries without transmitting any bytes to the balance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, TextIO

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - exercised by CLI environments
    serial = None
    list_ports = None


SCHEMA_NAME = "labcraft.veritas_balance_probe"
SCHEMA_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path("verification_reports/veritas_balance_probe")
DEFAULT_BAUD = 9600
READ_TIMEOUT_SECONDS = 0.1
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
MAX_DURATION_SECONDS = 3600.0
VID_PID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")
SCENARIOS = (
    "stable_zero",
    "stable_loaded",
    "disturb_recover",
    "natural_drift",
    "negative_after_manual_tare",
    "remove_replace",
    "fragmented_read",
    "disconnect",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _json_dump_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _jsonl_write(handle: TextIO, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()


def _real_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _by_id_paths(by_id_root: Path = Path("/dev/serial/by-id")) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}
    if not by_id_root.is_dir():
        return paths
    for candidate in sorted(by_id_root.iterdir(), key=lambda item: item.name):
        try:
            target = _real_path(str(candidate))
        except OSError:
            continue
        paths.setdefault(target, []).append(str(candidate))
    return paths


def _linux_driver(device: str) -> str | None:
    if platform.system() != "Linux":
        return None
    tty_name = Path(_real_path(device)).name
    driver_link = Path("/sys/class/tty") / tty_name / "device" / "driver"
    try:
        return driver_link.resolve(strict=True).name
    except OSError:
        return None


def describe_ports(
    port_entries: Iterable[Any] | None = None,
    *,
    by_id_root: Path = Path("/dev/serial/by-id"),
) -> list[dict[str, Any]]:
    """Return JSON-safe serial-port descriptions without opening any port."""
    if port_entries is None:
        if list_ports is None:
            raise RuntimeError("pyserial is required; install requirements.txt")
        port_entries = list_ports.comports()

    aliases = _by_id_paths(by_id_root)
    descriptions: list[dict[str, Any]] = []
    for entry in port_entries:
        device = str(getattr(entry, "device", ""))
        if not device:
            continue
        vid = getattr(entry, "vid", None)
        pid = getattr(entry, "pid", None)
        descriptions.append(
            {
                "device": device,
                "resolved_device": _real_path(device),
                "by_id_paths": aliases.get(_real_path(device), []),
                "name": getattr(entry, "name", None),
                "description": getattr(entry, "description", None),
                "hwid": getattr(entry, "hwid", None),
                "vid": f"{vid:04x}" if isinstance(vid, int) else None,
                "pid": f"{pid:04x}" if isinstance(pid, int) else None,
                "vid_pid": (
                    f"{vid:04x}:{pid:04x}"
                    if isinstance(vid, int) and isinstance(pid, int)
                    else None
                ),
                "serial_number": getattr(entry, "serial_number", None),
                "manufacturer": getattr(entry, "manufacturer", None),
                "product": getattr(entry, "product", None),
                "location": getattr(entry, "location", None),
                "interface": getattr(entry, "interface", None),
                "driver": _linux_driver(device),
            }
        )
    return sorted(descriptions, key=lambda item: item["device"])


def find_selected_port(
    requested_port: str,
    expected_vid_pid: str,
    descriptions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve an explicit device/alias and enforce its observed USB identity."""
    if not VID_PID_RE.fullmatch(expected_vid_pid):
        raise ValueError("--expect-vid-pid must use four-digit hex VID:PID")
    requested_real = _real_path(requested_port)
    matches = [
        item
        for item in descriptions
        if requested_port == item["device"]
        or requested_port in item["by_id_paths"]
        or requested_real == item["resolved_device"]
    ]
    if len(matches) != 1:
        raise ValueError(
            f"explicit port {requested_port!r} did not resolve to exactly one listed device"
        )
    selected = matches[0]
    observed = selected.get("vid_pid")
    if observed is None:
        raise ValueError(f"selected port {requested_port!r} has no USB VID:PID metadata")
    if observed.lower() != expected_vid_pid.lower():
        raise ValueError(
            f"selected port identity mismatch: expected {expected_vid_pid.lower()}, "
            f"observed {observed.lower()}"
        )
    return selected


def _marker_worker(
    stream: TextIO,
    marker_queue: queue.Queue[tuple[int, str]],
    stop_event: threading.Event,
    monotonic_ns: Callable[[], int],
    started_ns: int,
) -> None:
    while not stop_event.is_set():
        try:
            line = stream.readline()
        except (OSError, ValueError):
            return
        if line == "":
            return
        text = line.rstrip("\r\n")
        if text and not stop_event.is_set():
            marker_queue.put((max(0, monotonic_ns() - started_ns), text))


def _drain_markers(
    marker_queue: queue.Queue[tuple[int, str]],
    marker_handle: TextIO,
    next_sequence: int,
) -> int:
    while True:
        try:
            elapsed_ns, text = marker_queue.get_nowait()
        except queue.Empty:
            return next_sequence
        _jsonl_write(
            marker_handle,
            {"sequence": next_sequence, "elapsed_ns": elapsed_ns, "text": text},
        )
        next_sequence += 1


def _new_run_directory(output_root: Path, scenario: str, started: datetime) -> Path:
    stamp = started.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = output_root / f"{stamp}_{scenario}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def capture_serial(
    *,
    port: str,
    expected_vid_pid: str,
    scenario: str,
    duration_seconds: float,
    baud: int = DEFAULT_BAUD,
    read_size: int = 64,
    display_reading: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    marker_stream: TextIO | None = None,
    port_entries: Iterable[Any] | None = None,
    serial_factory: Callable[..., Any] | None = None,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_now: Callable[[], datetime] = _utc_now,
    max_capture_bytes: int = MAX_CAPTURE_BYTES,
) -> tuple[int, Path | None]:
    """Capture raw serial reads and return ``(exit_code, run_directory)``."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unsupported scenario: {scenario}")
    if not (0.0 < duration_seconds <= MAX_DURATION_SECONDS):
        raise ValueError(f"duration must be > 0 and <= {MAX_DURATION_SECONDS:g} seconds")
    if baud not in (1200, 2400, 4800, 9600):
        raise ValueError("baud must be one of 1200, 2400, 4800, or 9600")
    if not (1 <= read_size <= 65536):
        raise ValueError("read size must be between 1 and 65536 bytes")
    if max_capture_bytes <= 0:
        raise ValueError("maximum capture bytes must be positive")

    descriptions = describe_ports(port_entries)
    selected = find_selected_port(port, expected_vid_pid, descriptions)
    if serial_factory is None:
        if serial is None or not hasattr(serial, "Serial"):
            raise RuntimeError("pyserial is required; install requirements.txt")
        serial_factory = serial.Serial

    started_utc = utc_now()
    started_ns = monotonic_ns()
    run_dir = _new_run_directory(Path(output_root), scenario, started_utc)
    run_path = run_dir / "run.json"
    chunks_path = run_dir / "chunks.jsonl"
    markers_path = run_dir / "markers.jsonl"
    manifest: dict[str, Any] = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "balance_model": "Veritas HPB-625i",
        "scenario": scenario,
        "display_reading_at_start": display_reading,
        "started_at_utc": _utc_text(started_utc),
        "ended_at_utc": None,
        "started_monotonic_ns": started_ns,
        "duration_requested_seconds": duration_seconds,
        "duration_observed_ns": None,
        "adapter": selected,
        "requested_port": port,
        "serial_settings": {
            "baud": baud,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "read_timeout_seconds": READ_TIMEOUT_SECONDS,
            "xonxoff": False,
            "rtscts": False,
            "dsrdtr": False,
            "read_size": read_size,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "limits": {"maximum_capture_bytes": max_capture_bytes},
        "outcome": "starting",
        "error": None,
        "byte_count": 0,
        "chunk_count": 0,
        "marker_count": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }
    _json_dump_atomic(run_path, manifest)

    digest = hashlib.sha256()
    byte_count = 0
    chunk_sequence = 0
    marker_sequence = 0
    serial_handle = None
    exit_code = 3
    outcome = "open_error"
    error: str | None = None
    marker_queue: queue.Queue[tuple[int, str]] = queue.Queue()
    marker_stop = threading.Event()
    marker_thread: threading.Thread | None = None

    try:
        serial_handle = serial_factory(
            port=port,
            baudrate=baud,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=READ_TIMEOUT_SECONDS,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        if marker_stream is not None:
            marker_thread = threading.Thread(
                target=_marker_worker,
                args=(marker_stream, marker_queue, marker_stop, monotonic_ns, started_ns),
                name="veritas-balance-marker-reader",
                daemon=True,
            )
            marker_thread.start()

        deadline_ns = started_ns + int(duration_seconds * 1_000_000_000)
        with chunks_path.open("w", encoding="utf-8", newline="\n") as chunks_handle, markers_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as markers_handle:
            while monotonic_ns() < deadline_ns:
                marker_sequence = _drain_markers(
                    marker_queue, markers_handle, marker_sequence
                )
                remaining = max_capture_bytes - byte_count
                if remaining <= 0:
                    outcome = "maximum_bytes_reached"
                    exit_code = 3
                    break
                data = serial_handle.read(min(read_size, remaining))
                if not isinstance(data, (bytes, bytearray)):
                    raise TypeError("serial read returned a non-bytes value")
                if not data:
                    continue
                raw = bytes(data)
                elapsed_ns = max(0, monotonic_ns() - started_ns)
                _jsonl_write(
                    chunks_handle,
                    {
                        "sequence": chunk_sequence,
                        "elapsed_ns": elapsed_ns,
                        "byte_count": len(raw),
                        "data_hex": raw.hex(),
                    },
                )
                digest.update(raw)
                byte_count += len(raw)
                chunk_sequence += 1
            else:
                if byte_count:
                    outcome = "scheduled_capture_complete"
                    exit_code = 0
                else:
                    outcome = "scheduled_capture_complete_no_data"
                    exit_code = 2
            marker_stop.set()
            if marker_thread is not None:
                marker_thread.join(timeout=0.05)
            marker_sequence = _drain_markers(
                marker_queue, markers_handle, marker_sequence
            )
    except KeyboardInterrupt:
        outcome = "operator_interrupted"
        exit_code = 130
    except Exception as exc:  # serial backends use platform-specific subclasses
        outcome = "serial_error" if serial_handle is not None else "open_error"
        error = f"{type(exc).__name__}: {exc}"
        exit_code = 3
    finally:
        marker_stop.set()
        if marker_thread is not None:
            marker_thread.join(timeout=0.05)
        if serial_handle is not None:
            try:
                serial_handle.close()
            except Exception as exc:
                if exit_code in (0, 2):
                    outcome = "close_error"
                    error = f"{type(exc).__name__}: {exc}"
                    exit_code = 3

        ended_ns = monotonic_ns()
        manifest.update(
            {
                "ended_at_utc": _utc_text(utc_now()),
                "duration_observed_ns": max(0, ended_ns - started_ns),
                "outcome": outcome,
                "error": error,
                "byte_count": byte_count,
                "chunk_count": chunk_sequence,
                "marker_count": marker_sequence,
                "sha256": digest.hexdigest(),
            }
        )
        _json_dump_atomic(run_path, manifest)
        chunks_path.touch(exist_ok=True)
        markers_path.touch(exist_ok=True)

    return exit_code, run_dir


def _print_ports(descriptions: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(descriptions, indent=2, sort_keys=True))
        return
    if not descriptions:
        print("No serial ports found.")
        return
    for item in descriptions:
        identity = item["vid_pid"] or "unknown VID:PID"
        print(f"{item['device']}  {identity}  {item['description'] or ''}".rstrip())
        for alias in item["by_id_paths"]:
            print(f"  by-id: {alias}")
        if item["driver"]:
            print(f"  driver: {item['driver']}")
        if item["serial_number"]:
            print(f"  usb serial: {item['serial_number']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Receive-only HPB-625i serial characterization probe. "
            "The tool never sends balance commands."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ports_parser = subparsers.add_parser(
        "ports", help="list serial ports without opening them"
    )
    ports_parser.add_argument("--json", action="store_true", help="emit JSON")

    capture_parser = subparsers.add_parser(
        "capture", help="capture raw receive boundaries from one explicit port"
    )
    capture_parser.add_argument("--port", required=True, help="exact device or by-id path")
    capture_parser.add_argument(
        "--expect-vid-pid",
        required=True,
        help="USB identity reported by the ports command, such as 067b:2303",
    )
    capture_parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    capture_parser.add_argument("--duration", required=True, type=float)
    capture_parser.add_argument(
        "--baud", type=int, default=DEFAULT_BAUD, choices=(1200, 2400, 4800, 9600)
    )
    capture_parser.add_argument("--read-size", type=int, default=64)
    capture_parser.add_argument("--display-reading")
    capture_parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ports":
            _print_ports(describe_ports(), args.json)
            return 0

        print(
            "Capture is receive-only. Type an observation and press Enter to add "
            "a timestamped marker.",
            file=sys.stderr,
        )
        exit_code, run_dir = capture_serial(
            port=args.port,
            expected_vid_pid=args.expect_vid_pid,
            scenario=args.scenario,
            duration_seconds=args.duration,
            baud=args.baud,
            read_size=args.read_size,
            display_reading=args.display_reading,
            output_root=args.output_root,
            marker_stream=sys.stdin,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Balance probe setup failed: {exc}", file=sys.stderr)
        return 3
    print(run_dir)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
