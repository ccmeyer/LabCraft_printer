#!/usr/bin/env python3
import argparse
from collections import deque
import csv
import json
import os
import struct
import tempfile
import time
from datetime import datetime, timezone

try:
    import serial
except ImportError:
    serial = None


START_BYTE = 0xAA

TAG_P1 = 0x01
CMD_HELLO = 0xF3
CMD_HELLO_ACK = 0xF4
CMD_GOODBYE = 0xF5
CMD_BYE_ACK = 0xF6
CMD_BYE_DONE = 0xF8
CMD_SELFTEST_START = 0xFA
CMD_SELFTEST_RESULT = 0xFB
CMD_SELFTEST_DONE = 0xFC
CMD_SELFTEST_ABORT = 0xFD

TAG_PROFILE = 0x20
TAG_RUN_ID = 0x21
TAG_TIMEOUT_MS = 0x22
TAG_TEST_ID = 0x30
TAG_NAME = 0x31
TAG_PASS = 0x32
TAG_METRICS = 0x33
TAG_TS_MS = 0x34
TAG_TOTAL = 0x35
TAG_PASSED = 0x36
TAG_FAILED = 0x37
TAG_ABORTED = 0x38
TAG_TRACE_KIND = 0x39
TAG_TRACE_CHUNK_INDEX = 0x3A
TAG_TRACE_CHUNK_TOTAL = 0x3B
TAG_TRACE_FORMAT = 0x3C
TAG_TRACE_PAYLOAD = 0x3D
TAG_SEQ32 = 0x10
TAG_P2 = 0x02
TAG_P3 = 0x03

TRACE_KIND_SAMPLES = 1
TRACE_KIND_EVENTS = 2
TRACE_FORMAT_SAMPLE_V1 = 1
TRACE_FORMAT_EVENT_V1 = 2


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
            crc &= 0xFFFF
    return crc


def frame_payload(payload: bytes) -> bytes:
    c = crc16(payload)
    return bytes([START_BYTE, len(payload)]) + payload + bytes([c & 0xFF, (c >> 8) & 0xFF])


def build_control(cmd: int, seq8: int, seq32: int, tlvs: bytes = b"") -> bytes:
    payload = bytes([cmd, seq8, TAG_SEQ32, 4]) + seq32.to_bytes(4, "little") + tlvs
    return frame_payload(payload)


def parse_tlvs(payload: bytes) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    i = 0
    while i + 1 < len(payload):
        tag = payload[i]
        ln = payload[i + 1]
        i += 2
        if i + ln > len(payload):
            break
        out[tag] = payload[i : i + ln]
        i += ln
    return out


def parse_metrics(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        return {}
    # Try JSON first if firmware emits it later.
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    out = {}
    for part in raw.replace(",", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
            continue
        try:
            out[k] = int(v, 10)
            continue
        except Exception:
            pass
        try:
            out[k] = float(v)
            continue
        except Exception:
            pass
        out[k] = v
    return out


def decode_pressure_trace_samples_v1(payload: bytes) -> list[dict]:
    fmt = "<HHHHHhhHHBB"
    size = struct.calcsize(fmt)
    rows = []
    for off in range(0, len(payload), size):
        chunk = payload[off : off + size]
        if len(chunk) != size:
            break
        (
            dt_ms,
            raw_pressure,
            control_pressure,
            avg_pressure,
            target,
            error,
            derror,
            requested_hz,
            applied_hz,
            flags,
            ff_boost_div16,
        ) = struct.unpack(fmt, chunk)
        rows.append(
            {
                "dt_ms": dt_ms,
                "raw_pressure": raw_pressure,
                "control_pressure": control_pressure,
                "avg_pressure": avg_pressure,
                "target": target,
                "error": error,
                "derror": derror,
                "requested_hz": requested_hz,
                "applied_hz": applied_hz,
                "flags": flags,
                "ff_boost_hz": ff_boost_div16 * 16,
            }
        )
    return rows


def decode_pressure_trace_events_v1(payload: bytes) -> list[dict]:
    fmt = "<HBBHH"
    size = struct.calcsize(fmt)
    names = {
        0: "trace_start",
        1: "trace_stop",
        2: "pulse_start",
        3: "pulse_end",
        4: "quiet_start",
        5: "quiet_end",
        6: "recovery_start",
        7: "recovery_end",
        8: "ready_enter",
        9: "ready_exit",
    }
    rows = []
    for off in range(0, len(payload), size):
        chunk = payload[off : off + size]
        if len(chunk) != size:
            break
        dt_ms, event_type, _reserved, value0, value1 = struct.unpack(fmt, chunk)
        rows.append(
            {
                "dt_ms": dt_ms,
                "event_type": event_type,
                "event_name": names.get(event_type, f"unknown_{event_type}"),
                "value0": value0,
                "value1": value1,
            }
        )
    return rows


def decode_trace_payload(trace_kind: int, trace_format: int, payload: bytes) -> list[dict]:
    if trace_kind == TRACE_KIND_SAMPLES and trace_format == TRACE_FORMAT_SAMPLE_V1:
        return decode_pressure_trace_samples_v1(payload)
    if trace_kind == TRACE_KIND_EVENTS and trace_format == TRACE_FORMAT_EVENT_V1:
        return decode_pressure_trace_events_v1(payload)
    return []


class FrameReader:
    WAIT_START = 0
    WAIT_LEN = 1
    WAIT_DATA = 2

    def __init__(self) -> None:
        self.state = self.WAIT_START
        self.length = 0
        self.buf = bytearray()

    def feed(self, b: int):
        if self.state == self.WAIT_START:
            if b == START_BYTE:
                self.state = self.WAIT_LEN
            return None
        if self.state == self.WAIT_LEN:
            self.length = b
            self.buf.clear()
            self.state = self.WAIT_DATA
            return None

        self.buf.append(b)
        if len(self.buf) < self.length + 2:
            return None

        payload = bytes(self.buf[: self.length])
        rec_crc = self.buf[self.length] | (self.buf[self.length + 1] << 8)
        self.state = self.WAIT_START
        self.buf.clear()
        if crc16(payload) != rec_crc:
            return None
        return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".selftest_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _trace_artifact_path(base_out: str, test_id: int) -> str:
    base = os.path.splitext(base_out)[0]
    return f"{base}_trace_{test_id}.json"


def _camera_benchmark_artifact_path(base_out: str) -> str:
    base = os.path.splitext(base_out)[0]
    return f"{base}_camera_benchmark.json"


def _resolve_camera_benchmark_order(mode: str, requested_order: str) -> str:
    mode_norm = str(mode or "flash_only").strip().lower()
    if mode_norm not in ("flash_only", "print_then_flash"):
        mode_norm = "flash_only"
    order_norm = str(requested_order or "auto").strip().lower()
    if order_norm not in ("auto", "pre_selftest", "post_selftest"):
        order_norm = "auto"
    if order_norm == "auto":
        return "post_selftest" if mode_norm == "print_then_flash" else "pre_selftest"
    return order_norm


def _run_camera_benchmark_phase(
    args: argparse.Namespace,
    *,
    ser,
    run_id: int,
    host_checks: list,
    build_control_fn,
    phase: str,
    mode: str,
    requested_order: str,
) -> bool:
    bench_artifact = _camera_benchmark_artifact_path(args.out)
    try:
        from camera_flash_benchmark import BenchmarkConfig, run_camera_flash_benchmark

        mode = str(mode or "flash_only").strip().lower()
        if mode not in ("flash_only", "print_then_flash"):
            mode = "flash_only"
        effective_droplets = (
            max(1, int(getattr(args, "camera_benchmark_num_droplets", 1)))
            if mode == "print_then_flash"
            else 0
        )

        bench_cfg = BenchmarkConfig(
            cycles=max(1, int(getattr(args, "camera_benchmark_cycles", 100))),
            exposure_us=max(1, int(getattr(args, "camera_benchmark_exposure_us", 20000))),
            flash_delay_us=max(0, int(getattr(args, "camera_benchmark_flash_delay_us", 5000))),
            flash_width_us=max(1, int(getattr(args, "camera_benchmark_flash_width_us", 1000))),
            num_droplets=effective_droplets,
            attempt_timeout_ms=max(1, int(getattr(args, "camera_benchmark_attempt_timeout_ms", 250))),
            max_new_frames=max(1, int(getattr(args, "camera_benchmark_max_new_frames", 6))),
            mode=mode,
            run_order=phase,
            preflight_pressure_timeout_ms=max(
                50, int(getattr(args, "camera_benchmark_preflight_pressure_timeout_ms", 1000))
            ),
        )
        bench_payload = run_camera_flash_benchmark(
            ser,
            build_control_fn,
            run_id=run_id,
            config=bench_cfg,
        )
        write_json_atomic(bench_artifact, bench_payload)
        host_checks.append(
            {
                "name": "camera_flash_benchmark",
                "pass": True,
                "details": {
                    "status": bench_payload.get("status", "ok"),
                    "artifact": bench_artifact,
                    "phase": phase,
                    "mode": mode,
                    "requested_order": str(requested_order),
                    "resolved_order": str(phase),
                    "summary": bench_payload.get("summary", {}),
                    "preflight": bench_payload.get("preflight", {}),
                    "init_diag": bench_payload.get("init_diag", {}),
                    "status_snapshot_delta": bench_payload.get("status_snapshot_delta", {}),
                },
                "timestamp": now_iso(),
            }
        )
        print(f"Wrote camera benchmark artifact: {bench_artifact}")
        return False
    except ImportError as e:
        host_checks.append(
            {
                "name": "camera_flash_benchmark",
                "pass": True,
                "details": {
                    "status": "skipped_missing_dependency",
                    "artifact": bench_artifact,
                    "phase": phase,
                    "mode": str(mode),
                    "requested_order": str(requested_order),
                    "resolved_order": str(phase),
                    "error": str(e),
                },
                "timestamp": now_iso(),
            }
        )
        print(f"Skipping camera benchmark due to missing dependency: {e}")
        return False
    except Exception as e:
        host_checks.append(
            {
                "name": "camera_flash_benchmark",
                "pass": False,
                "details": {
                    "status": "error",
                    "artifact": bench_artifact,
                    "phase": phase,
                    "mode": str(mode),
                    "requested_order": str(requested_order),
                    "resolved_order": str(phase),
                    "error": str(e),
                },
                "timestamp": now_iso(),
            }
        )
        print(f"Camera benchmark failed: {e}")
        return True


def _write_sweep_artifacts(base_out: str, run_id: int, results: list[dict]) -> tuple[str, str] | tuple[None, None]:
    combo_rows = []
    suite_summary = None
    suite_id = None
    for row in results:
        metrics = row.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        if {"suite", "param", "scenario"}.issubset(metrics.keys()):
            sid = int(metrics.get("suite", 0))
            suite_id = sid if suite_id is None else suite_id
            if suite_id != sid:
                continue
            combo_rows.append(row)
            continue
        if {"suite", "combos", "pass_combo_count", "best_param", "best_score", "worst_score", "trace_exported_count"}.issubset(metrics.keys()):
            sid = int(metrics.get("suite", 0))
            suite_id = sid if suite_id is None else suite_id
            if suite_id != sid:
                continue
            suite_summary = row

    if not combo_rows or suite_id is None:
        return None, None

    combos = []
    for row in combo_rows:
        metrics = dict(row["metrics"])
        score = int(metrics.get("score", 0))
        if score == 0:
            score = (
                1000 * int(metrics.get("ready_miss", 0))
                + 4 * int(metrics.get("slip_w", 0))
                + 2 * int(metrics.get("rec_w", 0))
                + int(metrics.get("over", 0))
                + int(metrics.get("under", 0))
                + int(metrics.get("zero", 0))
            )
        trace_path = _trace_artifact_path(base_out, int(row["test_id"]))
        trace_file = trace_path if os.path.exists(trace_path) else None
        combos.append(
            {
                "test_id": int(row["test_id"]),
                "name": row.get("name"),
                "pass": bool(row.get("pass", False)),
                "suite": int(metrics.get("suite", 0)),
                "param": int(metrics.get("param", 0)),
                "scenario": int(metrics.get("scenario", 0)),
                "mode": int(metrics.get("mode", 0)),
                "target_raw": int(metrics.get("target_raw", 0)),
                "pulse_us": int(metrics.get("pulse_us", 0)),
                "droplets": int(metrics.get("droplets", 0)),
                "hz": int(metrics.get("hz", 0)),
                "base": int(metrics.get("base", 0)),
                "min": int(metrics.get("min", 0)),
                "max": int(metrics.get("max", 0)),
                "under": int(metrics.get("under", 0)),
                "over": int(metrics.get("over", 0)),
                "rec_w": int(metrics.get("rec_w", 0)),
                "rec_m": int(metrics.get("rec_m", 0)),
                "ready_miss": int(metrics.get("ready_miss", 0)),
                "slip_w": int(metrics.get("slip_w", 0)),
                "slip_m": int(metrics.get("slip_m", 0)),
                "zero": int(metrics.get("zero", 0)),
                "rejects": int(metrics.get("rejects", 0)),
                "sc": int(metrics.get("sc", 0)),
                "ec": int(metrics.get("ec", 0)),
                "trace": int(metrics.get("trace", 0)),
                "score": score,
                "trace_file": trace_file,
            }
        )

    combos.sort(key=lambda r: (r["score"], r["ready_miss"], r["slip_w"], r["test_id"]))

    summary_metrics = {}
    if suite_summary and isinstance(suite_summary.get("metrics"), dict):
        summary_metrics = dict(suite_summary["metrics"])
    else:
        summary_metrics = {
            "suite": suite_id,
            "combos": len(combos),
            "pass_combo_count": sum(1 for c in combos if c["pass"]),
            "best_param": combos[0]["param"] if combos else 0,
            "best_score": combos[0]["score"] if combos else 0,
            "worst_score": combos[-1]["score"] if combos else 0,
            "trace_exported_count": sum(1 for c in combos if c["trace"] == 1),
        }

    payload = {
        "run_id": run_id,
        "suite_id": int(summary_metrics.get("suite", suite_id)),
        "summary": summary_metrics,
        "combos": combos,
    }

    base = os.path.splitext(base_out)[0]
    json_path = f"{base}_pressure_sweep_s{payload['suite_id']}.json"
    csv_path = f"{base}_pressure_sweep_s{payload['suite_id']}.csv"
    write_json_atomic(json_path, payload)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "test_id",
                "name",
                "pass",
                "suite",
                "param",
                "scenario",
                "mode",
                "target_raw",
                "pulse_us",
                "droplets",
                "hz",
                "base",
                "min",
                "max",
                "under",
                "over",
                "rec_w",
                "rec_m",
                "ready_miss",
                "slip_w",
                "slip_m",
                "zero",
                "rejects",
                "sc",
                "ec",
                "trace",
                "score",
                "trace_file",
            ],
        )
        writer.writeheader()
        for row in combos:
            writer.writerow(row)

    return json_path, csv_path


def run(args: argparse.Namespace) -> int:
    if serial is None:
        print("Missing dependency: pyserial (import serial failed).")
        return 3

    profile = args.profile.upper()
    profile_map = {"SAFE": 0, "FULL": 1}
    if profile not in profile_map:
        print(f"Unsupported profile '{profile}'. Supported profiles: SAFE, FULL.")
        return 3

    run_id = int(time.time() * 1000) & 0xFFFFFFFF
    effective_timeout_ms = int(args.timeout_ms)
    if profile == "FULL" and effective_timeout_ms < 90000:
        effective_timeout_ms = 90000
    started_at = now_iso()
    results = []
    host_checks = []
    trace_chunks: dict[tuple[int, int, int], dict] = {}
    summary = {"total": 0, "passed": 0, "failed": 0}
    aborted = False

    camera_benchmark_runtime_error = False
    with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
        reader = FrameReader()

        # HELLO handshake. Retry until the target is actually up so startup
        # latency after DFU does not cause us to lose both HELLO and START.
        hello_seq8 = 1
        hello_timeout_ms = int(args.hello_timeout_ms)
        hello_retry_ms = int(args.hello_retry_ms)
        hello_window_s = hello_timeout_ms / 1000.0
        hello_deadline = time.monotonic() + hello_window_s
        next_hello_send = 0.0
        got_hello_ack = False
        hello_retries_sent = 0
        observed_uart_bytes = 0
        while time.monotonic() < hello_deadline:
            now = time.monotonic()
            if now >= next_hello_send:
                ser.write(build_control(CMD_HELLO, hello_seq8, run_id))
                hello_retries_sent += 1
                next_hello_send = now + (hello_retry_ms / 1000.0)
            chunk = ser.read(128)
            observed_uart_bytes += len(chunk)
            for v in chunk:
                frame = reader.feed(v)
                if not frame or len(frame) < 2:
                    continue
                if frame[0] == CMD_HELLO_ACK and frame[1] == hello_seq8:
                    got_hello_ack = True
                    break
            if got_hello_ack:
                break
        host_checks.append(
            {
                "name": "hello_ack",
                "pass": got_hello_ack,
                "details": {
                    "seq8": hello_seq8,
                    "run_id": run_id,
                    "timeout_ms": hello_timeout_ms,
                    "retry_ms": hello_retry_ms,
                    "retries_sent": hello_retries_sent,
                    "observed_uart_bytes": observed_uart_bytes,
                    "fast_fail_on_missing_hello": bool(args.fast_fail_on_missing_hello),
                },
                "timestamp": now_iso(),
            }
        )
        if not got_hello_ack:
            print("No HELLO_ACK before self-test start.")
            if args.fast_fail_on_missing_hello:
                aborted = True
                report = {
                    "run_id": run_id,
                    "profile": profile,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                    "aborted": aborted,
                    "summary": summary,
                    "results": results,
                    "host_checks": host_checks,
                }
                write_json_atomic(args.out, report)
                print(f"Wrote self-test report: {args.out}")
                return 3

        bench_mode = str(getattr(args, "camera_benchmark_mode", "flash_only") or "flash_only").strip().lower()
        if bench_mode not in ("flash_only", "print_then_flash"):
            bench_mode = "flash_only"
        requested_bench_order = str(getattr(args, "camera_benchmark_order", "auto") or "auto").strip().lower()
        bench_order = _resolve_camera_benchmark_order(bench_mode, requested_bench_order)
        run_benchmark = bool(getattr(args, "camera_benchmark", False))
        if run_benchmark and bench_order == "pre_selftest":
            camera_benchmark_runtime_error = _run_camera_benchmark_phase(
                args,
                ser=ser,
                run_id=run_id,
                host_checks=host_checks,
                build_control_fn=build_control,
                phase="pre_selftest",
                mode=bench_mode,
                requested_order=requested_bench_order,
            )

        profile_val = profile_map[profile]
        # Mirror profile into TAG_P1 so current firmware decode can branch without
        # changing CommCodec TLV parsing rules. TAG_PROFILE remains authoritative.
        tlvs = bytes([TAG_P1, 1, profile_val])
        tlvs += bytes([TAG_P2, 1, 1 if getattr(args, "pressure_trace", False) else 0])
        pressure_trace_test = getattr(args, "pressure_trace_test", None)
        pressure_sweep_suite = getattr(args, "pressure_sweep_suite", None)
        selector = pressure_sweep_suite if pressure_sweep_suite is not None else pressure_trace_test
        if selector is not None:
            tlvs += bytes([TAG_P3, 2]) + int(selector).to_bytes(2, "little")
        tlvs += bytes([TAG_PROFILE, 1, profile_val])
        tlvs += bytes([TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
        tlvs += bytes([TAG_TIMEOUT_MS, 4]) + effective_timeout_ms.to_bytes(4, "little")
        ser.write(build_control(CMD_SELFTEST_START, 2, run_id, tlvs))

        hard_deadline = time.monotonic() + (effective_timeout_ms / 1000.0)
        progress_timeout_ms = max(1000, int(getattr(args, "progress_timeout_ms", 15000)))
        activity_timeout_ms = max(progress_timeout_ms, int(getattr(args, "activity_timeout_ms", 60000)))
        idle_deadline = time.monotonic() + (progress_timeout_ms / 1000.0)
        activity_deadline = time.monotonic() + (activity_timeout_ms / 1000.0)
        done_seen = False
        timeout_reason = "hard_timeout"
        progress_count = 0
        last_progress = {}
        recent_frames = deque(maxlen=64)
        frame_counts: dict[int, int] = {}
        total_rx_bytes = 0
        last_valid_frame_monotonic = time.monotonic()
        last_rx_byte_monotonic = time.monotonic()
        last_selftest_frame_monotonic = time.monotonic()
        status_only_timeout_ms = max(1000, int(getattr(args, "status_only_timeout_ms", 5000)))
        status_frames_since_selftest = 0
        selftest_frames_seen = 0
        while True:
            now = time.monotonic()
            if now >= hard_deadline:
                timeout_reason = "hard_timeout"
                break
            if now >= activity_deadline:
                timeout_reason = "activity_timeout"
                break
            if now >= idle_deadline:
                timeout_reason = "progress_timeout"
                break
            chunk = ser.read(256)
            if not chunk:
                continue
            total_rx_bytes += len(chunk)
            last_rx_byte_monotonic = now
            idle_deadline = now + (progress_timeout_ms / 1000.0)
            activity_deadline = now + (activity_timeout_ms / 1000.0)
            for v in chunk:
                frame = reader.feed(v)
                if not frame or len(frame) < 2:
                    continue
                last_valid_frame_monotonic = now
                cmd = frame[0]
                body = frame[2:]
                tlv = parse_tlvs(body)
                frame_counts[cmd] = frame_counts.get(cmd, 0) + 1
                frame_snapshot = {"ts": now_iso(), "cmd": cmd}
                idle_deadline = now + (progress_timeout_ms / 1000.0)
                if cmd == 0x02:
                    status_frames_since_selftest += 1
                    if (
                        selftest_frames_seen > 0
                        and (now - last_selftest_frame_monotonic) >= (status_only_timeout_ms / 1000.0)
                        and status_frames_since_selftest >= 50
                    ):
                        timeout_reason = "status_only_after_selftest"
                        done_seen = False
                        break

                if cmd == CMD_SELFTEST_RESULT:
                    selftest_frames_seen += 1
                    last_selftest_frame_monotonic = now
                    status_frames_since_selftest = 0
                    test_id = int.from_bytes(tlv.get(TAG_TEST_ID, b"\x00\x00"), "little")
                    name = tlv.get(TAG_NAME, b"").decode("utf-8", errors="replace")
                    passed = bool(tlv.get(TAG_PASS, b"\x00")[0] if tlv.get(TAG_PASS) else 0)
                    frame_snapshot["test_id"] = test_id
                    frame_snapshot["name"] = name
                    if test_id == 0 and name == "selftest_progress":
                        progress_count += 1
                        metrics_raw = tlv.get(TAG_METRICS, b"").decode("utf-8", errors="replace")
                        last_progress = parse_metrics(metrics_raw)
                        frame_snapshot["progress"] = True
                        frame_snapshot["stage"] = str(last_progress.get("stage", ""))
                        recent_frames.append(frame_snapshot)
                        continue
                    if TAG_TRACE_KIND in tlv:
                        trace_kind = int.from_bytes(tlv.get(TAG_TRACE_KIND, b"\x00"), "little")
                        trace_format = int.from_bytes(tlv.get(TAG_TRACE_FORMAT, b"\x00"), "little")
                        chunk_index = int.from_bytes(tlv.get(TAG_TRACE_CHUNK_INDEX, b"\x00\x00"), "little")
                        chunk_total = int.from_bytes(tlv.get(TAG_TRACE_CHUNK_TOTAL, b"\x00\x00"), "little")
                        payload_raw = tlv.get(TAG_TRACE_PAYLOAD, b"")
                        frame_snapshot["trace_kind"] = trace_kind
                        frame_snapshot["trace_chunk_index"] = chunk_index
                        frame_snapshot["trace_chunk_total"] = chunk_total
                        key = (test_id, trace_kind, trace_format)
                        slot = trace_chunks.setdefault(
                            key,
                            {
                                "name": name,
                                "pass": passed,
                                "chunk_total": chunk_total,
                                "parts": {},
                            },
                        )
                        slot["parts"][chunk_index] = payload_raw
                        recent_frames.append(frame_snapshot)
                        continue
                    metrics_raw = tlv.get(TAG_METRICS, b"").decode("utf-8", errors="replace")
                    results.append(
                        {
                            "test_id": test_id,
                            "name": name,
                            "pass": passed,
                            "metrics": parse_metrics(metrics_raw),
                            "timestamp": now_iso(),
                        }
                    )
                    recent_frames.append(frame_snapshot)
                    continue

                if cmd == CMD_SELFTEST_DONE:
                    selftest_frames_seen += 1
                    last_selftest_frame_monotonic = now
                    status_frames_since_selftest = 0
                    done_run = int.from_bytes(tlv.get(TAG_RUN_ID, b"\x00\x00\x00\x00"), "little")
                    frame_snapshot["run_id"] = done_run
                    recent_frames.append(frame_snapshot)
                    if done_run != run_id:
                        continue
                    summary = {
                        "total": int.from_bytes(tlv.get(TAG_TOTAL, b"\x00\x00"), "little"),
                        "passed": int.from_bytes(tlv.get(TAG_PASSED, b"\x00\x00"), "little"),
                        "failed": int.from_bytes(tlv.get(TAG_FAILED, b"\x00\x00"), "little"),
                    }
                    aborted = bool(tlv.get(TAG_ABORTED, b"\x00")[0] if tlv.get(TAG_ABORTED) else 0)
                    done_seen = True
                    break
            if done_seen:
                break
            if timeout_reason == "status_only_after_selftest":
                break

        if not done_seen:
            print(f"Timed out waiting for CMD_SELFTEST_DONE ({timeout_reason}).")
            aborted = True
            rc = 3
        elif aborted:
            rc = 3
        elif summary["failed"] > 0:
            rc = 2
        else:
            rc = 0

        if done_seen and run_benchmark and bench_order == "post_selftest":
            # selftest_done path leaves status paused, so re-HELLO before post-selftest benchmark.
            hello_seq8_bench = 0x0E
            ser.write(build_control(CMD_HELLO, hello_seq8_bench, run_id))
            hello_resume_deadline = time.monotonic() + 1.5
            got_resume_hello = False
            while time.monotonic() < hello_resume_deadline:
                chunk = ser.read(64)
                for v in chunk:
                    frame = reader.feed(v)
                    if not frame or len(frame) < 2:
                        continue
                    if frame[0] == CMD_HELLO_ACK and frame[1] == hello_seq8_bench:
                        got_resume_hello = True
                        break
                if got_resume_hello:
                    break
            host_checks.append(
                {
                    "name": "camera_flash_benchmark_hello_resume",
                    "pass": got_resume_hello,
                    "details": {"seq8": hello_seq8_bench, "timeout_ms": 1500},
                    "timestamp": now_iso(),
                }
            )
            camera_benchmark_runtime_error = _run_camera_benchmark_phase(
                args,
                ser=ser,
                run_id=run_id,
                host_checks=host_checks,
                build_control_fn=build_control,
                phase="post_selftest",
                mode=bench_mode,
                requested_order=requested_bench_order,
            ) or camera_benchmark_runtime_error

        if done_seen:
            goodbye_seq8 = 3
            ser.write(build_control(CMD_GOODBYE, goodbye_seq8, run_id))

            # Wait for BYE_ACK first.
            bye_ack_timeout_ms = 2000
            ack_deadline = time.monotonic() + (bye_ack_timeout_ms / 1000.0)
            got_bye_ack = False
            ack_details = {
                "seq8": goodbye_seq8,
                "run_id": run_id,
                "timeout_ms": bye_ack_timeout_ms,
            }
            while time.monotonic() < ack_deadline and not got_bye_ack:
                chunk = ser.read(128)
                for v in chunk:
                    frame = reader.feed(v)
                    if not frame or len(frame) < 2:
                        continue
                    cmd = frame[0]
                    seq8 = frame[1]
                    if cmd == CMD_BYE_ACK and seq8 == goodbye_seq8:
                        got_bye_ack = True
                        break
                    ack_details["observed_cmd"] = cmd
                    ack_details["observed_seq8"] = seq8

            if got_bye_ack:
                print("GOODBYE ACK received.")
            else:
                print("Timed out waiting for GOODBYE ACK.")
            host_checks.append(
                {
                    "name": "goodbye_ack",
                    "pass": got_bye_ack,
                    "details": ack_details,
                    "timestamp": now_iso(),
                }
            )

            # Wait for BYE_DONE only after BYE_ACK succeeds.
            bye_done_timeout_ms = 5000
            got_bye_done = False
            done_details = {
                "seq8": goodbye_seq8,
                "run_id": run_id,
                "timeout_ms": bye_done_timeout_ms,
            }
            if got_bye_ack:
                done_deadline = time.monotonic() + (bye_done_timeout_ms / 1000.0)
                while time.monotonic() < done_deadline and not got_bye_done:
                    chunk = ser.read(128)
                    for v in chunk:
                        frame = reader.feed(v)
                        if not frame or len(frame) < 2:
                            continue
                        cmd = frame[0]
                        seq8 = frame[1]
                        if cmd != CMD_BYE_DONE:
                            done_details["observed_cmd"] = cmd
                            done_details["observed_seq8"] = seq8
                            continue
                        if seq8 != goodbye_seq8:
                            done_details["observed_cmd"] = cmd
                            done_details["observed_seq8"] = seq8
                            continue
                        tlv = parse_tlvs(frame[2:])
                        seq32 = None
                        if TAG_SEQ32 in tlv and len(tlv[TAG_SEQ32]) == 4:
                            seq32 = int.from_bytes(tlv[TAG_SEQ32], "little")
                            done_details["observed_seq32"] = seq32
                            if seq32 != run_id:
                                continue
                        got_bye_done = True
                        break
            else:
                done_details["skipped"] = "BYE_ACK not received"

            if got_bye_done:
                print("GOODBYE DONE received.")
            else:
                print("Timed out waiting for GOODBYE DONE.")
            host_checks.append(
                {
                    "name": "goodbye_done",
                    "pass": got_bye_done,
                    "details": done_details,
                    "timestamp": now_iso(),
                }
            )

            if not got_bye_ack:
                rc = 3
            elif not got_bye_done:
                rc = 3

        host_checks.append(
            {
                "name": "selftest_progress_watchdog",
                "pass": done_seen,
                "details": {
                    "progress_count": progress_count,
                    "last_progress": last_progress,
                    "recent_frames": list(recent_frames),
                    "frame_counts": {str(k): v for k, v in sorted(frame_counts.items())},
                    "progress_timeout_ms": progress_timeout_ms,
                    "activity_timeout_ms": activity_timeout_ms,
                    "status_only_timeout_ms": status_only_timeout_ms,
                    "effective_timeout_ms": effective_timeout_ms,
                    "total_rx_bytes": total_rx_bytes,
                    "status_frames_since_selftest": status_frames_since_selftest,
                    "selftest_frames_seen": selftest_frames_seen,
                    "last_valid_frame_age_ms": int(max(0.0, (time.monotonic() - last_valid_frame_monotonic) * 1000.0)),
                    "last_rx_byte_age_ms": int(max(0.0, (time.monotonic() - last_rx_byte_monotonic) * 1000.0)),
                    "last_selftest_frame_age_ms": int(max(0.0, (time.monotonic() - last_selftest_frame_monotonic) * 1000.0)),
                    "timeout_reason": None if done_seen else timeout_reason,
                },
                "timestamp": now_iso(),
            }
        )

        report = {
            "run_id": run_id,
            "profile": profile,
            "started_at": started_at,
            "finished_at": now_iso(),
            "aborted": aborted,
            "summary": summary,
            "results": results,
            "host_checks": host_checks,
        }
        write_json_atomic(args.out, report)
        if trace_chunks:
            base = os.path.splitext(args.out)[0]
            for (test_id, trace_kind, trace_format), info in trace_chunks.items():
                parts = info["parts"]
                ordered = b"".join(parts[i] for i in sorted(parts))
                existing_path = _trace_artifact_path(args.out, test_id)
                payload = {}
                if os.path.exists(existing_path):
                    with open(existing_path, "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                payload.setdefault("run_id", run_id)
                payload.setdefault("test_id", test_id)
                payload.setdefault("name", info["name"])
                payload.setdefault("summary", next((r["metrics"] for r in results if r["test_id"] == test_id), {}))
                if trace_kind == TRACE_KIND_SAMPLES:
                    payload["samples"] = decode_trace_payload(trace_kind, trace_format, ordered)
                elif trace_kind == TRACE_KIND_EVENTS:
                    payload["events"] = decode_trace_payload(trace_kind, trace_format, ordered)
                write_json_atomic(existing_path, payload)
        sweep_json, sweep_csv = _write_sweep_artifacts(args.out, run_id, results)
        if sweep_json and sweep_csv:
            print(f"Wrote sweep artifacts: {sweep_json} | {sweep_csv}")
        if camera_benchmark_runtime_error:
            rc = 3
        print(f"Wrote self-test report: {args.out}")
        return rc


def main() -> int:
    p = argparse.ArgumentParser(description="Run LabCraft firmware self-test and write JSON report.")
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--profile", default="SAFE")
    p.add_argument("--timeout-ms", type=int, default=30000)
    p.add_argument("--progress-timeout-ms", type=int, default=15000)
    p.add_argument("--activity-timeout-ms", type=int, default=60000)
    p.add_argument("--status-only-timeout-ms", type=int, default=5000)
    p.add_argument("--hello-timeout-ms", type=int, default=8000)
    p.add_argument("--hello-retry-ms", type=int, default=250)
    p.add_argument("--fast-fail-on-missing-hello", action="store_true")
    p.add_argument("--camera-benchmark", action="store_true")
    p.add_argument("--camera-benchmark-cycles", type=int, default=100)
    p.add_argument("--camera-benchmark-exposure-us", type=int, default=20000)
    p.add_argument("--camera-benchmark-flash-delay-us", type=int, default=5000)
    p.add_argument("--camera-benchmark-flash-width-us", type=int, default=1000)
    p.add_argument("--camera-benchmark-num-droplets", type=int, default=1)
    p.add_argument("--camera-benchmark-order", choices=("auto", "pre_selftest", "post_selftest"), default="auto")
    p.add_argument("--camera-benchmark-mode", choices=("flash_only", "print_then_flash"), default="flash_only")
    p.add_argument("--camera-benchmark-preflight-pressure-timeout-ms", type=int, default=1000)
    p.add_argument("--camera-benchmark-attempt-timeout-ms", type=int, default=250)
    p.add_argument("--camera-benchmark-max-new-frames", type=int, default=6)
    p.add_argument("--pressure-trace", action="store_true")
    selector_group = p.add_mutually_exclusive_group()
    selector_group.add_argument("--pressure-trace-test", type=int, choices=(2101, 2102, 2103, 2104))
    selector_group.add_argument("--pressure-sweep-suite", type=int, choices=(2301, 2302, 2303, 2304))
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted.")
        return 3
    except Exception as e:
        print(f"Self-test runner error: {e}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
