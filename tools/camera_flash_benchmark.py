import math
import glob
import os
import statistics
import subprocess
import time
from collections import Counter, deque
from dataclasses import dataclass


CMD_INIT_FLASH = 0xC0
CMD_STOP_FLASH = 0xC1
CMD_SET_FLASH_DURATION = 0xC2
CMD_SET_FLASH_DELAY = 0xC3
CMD_SET_IMAGING_DROPLETS = 0xC4
CMD_STATUS = 0x02
CMD_QUEUE_ACK = 0xFE
CMD_ENABLE_MOTORS = 0x08
CMD_GRIPPER_OPEN = 0x10
CMD_GRIPPER_OFF = 0x12
CMD_HOME_XY = 0x43
CMD_HOME_PR_BOTH = 0x44
CMD_SET_GRIPPER_PARAMS = 0x62
CMD_PR_PRINT = 0xE0
CMD_PR_REFUEL = 0xE1
CMD_P_REG_START = 0xE8
CMD_R_REG_START = 0xEA
CMD_P_REG_STOP = 0xE9
CMD_R_REG_STOP = 0xEB

TAG_FLASH_NUM = 0x60
TAG_FLASH_WIDTH = 0x61
TAG_FLASH_DELAY = 0x62
TAG_FLASH_DROPS = 0x63
TAG_EXT_COUNT = 0x64
TAG_P1 = 0x01
TAG_P2 = 0x02
TAG_P3 = 0x03
TAG_SEQ32 = 0x10
TAG_ACK_RESULT = 0x11
TAG_EXPECTED_SEQ32 = 0x12
TAG_PRINT_P = 0x12
TAG_REFUEL_P = 0x13
TAG_TAR_PRINT_P = 0x14
TAG_TAR_REFUEL_P = 0x15
TAG_ACTIVE_P = 0x40
TAG_ACTIVE_R = 0x41
TAG_GRIP_PULSE = 0x80
TAG_GRIP_REFRESH = 0x81

ACK_RESULT_ACCEPTED = 1
ACK_RESULT_DUPLICATE = 2
ACK_RESULT_GAP = 3
ACK_RESULT_BUSY = 4
ACK_RESULT_WATERMARK_SET = 5
ACK_RESULT_WATERMARK_REJECTED = 6

SAFE_FLASH_WIDTH_MIN_NS = 100
SAFE_FLASH_WIDTH_MAX_NS = 5000
MACHINE_READY_TIMEOUT_MS_MIN = 15000
QUEUE_ACK_TIMEOUT_MS = 500
QUEUE_ACK_MAX_RETRIES = 3
HOME_FAST_HZ = 30000
HOME_SLOW_HZ = 3000
HOME_BACKOFF_STEPS = 400
PRESSURE_FSS = 13107
PRESSURE_PSI_OFFSET = 1638
PRESSURE_PSI_MAX = 15
COORDINATED_PRESSURE_PSI_DEFAULT = 0.6
COORDINATED_GRIPPER_REFRESH_MS_DEFAULT = 5000
COORDINATED_GRIPPER_PULSE_MS_DEFAULT = 500


@dataclass
class BenchmarkConfig:
    cycles: int = 100
    exposure_us: int = 20000
    flash_delay_us: int = 5000
    flash_width_us: int = 1000
    num_droplets: int = 1
    attempt_timeout_ms: int = 250
    max_new_frames: int = 6
    trigger_pin_bcm: int = 17
    flash_ack_pin_bcm: int = 22
    k_sigma: float = 4.0
    min_delta: float = 25.0
    threshold_cap: float = 150.0
    baseline_frames: int = 4
    trigger_settle_ms: int = 2
    post_cycle_settle_ms: int = 1
    trigger_retries: int = 1
    mode: str = "flash_only"
    run_order: str = "pre_selftest"
    preflight_pressure_timeout_ms: int = 1000
    warmup_cycles: int = 1
    min_trigger_period_ms: int = 0
    early_abort_consecutive_edge_timeouts: int = 5
    coordinated_pressure_psi: float = COORDINATED_PRESSURE_PSI_DEFAULT
    coordinated_gripper_refresh_ms: int = COORDINATED_GRIPPER_REFRESH_MS_DEFAULT
    coordinated_gripper_pulse_ms: int = COORDINATED_GRIPPER_PULSE_MS_DEFAULT


def _safe_percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    try:
        q = max(0.0, min(100.0, float(pct)))
        idx = (q / 100.0) * (len(values) - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return float(values[lo])
        frac = idx - lo
        return float(values[lo] * (1.0 - frac) + values[hi] * frac)
    except Exception:
        return None


def summarize_cycles(cycles: list[dict], requested_cycles: int, started_ns: int, finished_ns: int) -> dict:
    by_reason = Counter(str(c.get("reason", "unknown")) for c in cycles)
    completed = [c for c in cycles if bool(c.get("completed", False))]
    ack_seen = [
        c
        for c in completed
        if bool(c.get("ack_seen_bool", False)) or isinstance(c.get("trigger_to_ack_ms"), (int, float))
    ]
    frame_selected = [
        c
        for c in completed
        if bool(c.get("frame_selected_bool", False)) or isinstance(c.get("trigger_to_frame_ms"), (int, float))
    ]
    threshold_hits = [c for c in completed if str(c.get("reason", "")) == "threshold"]
    flash_detected = [
        c
        for c in completed
        if bool(c.get("flash_detected_bool", False)) or str(c.get("reason", "")) == "threshold"
    ]
    fallback_hits = [c for c in completed if str(c.get("reason", "")) == "fallback"]
    last_resort_hits = [c for c in completed if str(c.get("reason", "")) == "last_resort"]
    ack_level_high = [c for c in completed if bool(c.get("ack_level_high_seen_bool", False))]

    elapsed_s = max(0.0, (finished_ns - started_ns) / 1_000_000_000.0)
    effective_fps = (len(completed) / elapsed_s) if elapsed_s > 0 else 0.0

    def _durations(key: str) -> list[float]:
        vals = []
        for c in completed:
            v = c.get(key)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        vals.sort()
        return vals

    summary = {
        "requested_cycles": int(requested_cycles),
        "completed_cycles": len(completed),
        "success_cycles": len(flash_detected),
        "success_rate": (len(flash_detected) / len(completed)) if completed else 0.0,
        "ack_seen_cycles": len(ack_seen),
        "frame_selected_cycles": len(frame_selected),
        "flash_detected_cycles": len(flash_detected),
        "threshold_cycles": len(threshold_hits),
        "fallback_cycles": len(fallback_hits),
        "last_resort_cycles": len(last_resort_hits),
        "ack_level_high_seen_cycles": len(ack_level_high),
        "elapsed_s": elapsed_s,
        "effective_fps": effective_fps,
        "reason_distribution": dict(by_reason),
        "timeout_count": int(by_reason.get("edge_timeout", 0)),
        "error_count": int(by_reason.get("error", 0)),
        "durations_ms": {},
    }

    for key in (
        "trigger_to_ack_ms",
        "ack_to_arm_ms",
        "arm_to_frame_ms",
        "trigger_to_frame_ms",
        "cycle_total_ms",
    ):
        vals = _durations(key)
        if not vals:
            summary["durations_ms"][key] = {"count": 0, "p50": None, "p90": None, "p99": None, "mean": None}
            continue
        summary["durations_ms"][key] = {
            "count": len(vals),
            "p50": _safe_percentile(vals, 50),
            "p90": _safe_percentile(vals, 90),
            "p99": _safe_percentile(vals, 99),
            "mean": float(statistics.mean(vals)),
        }
    return summary


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_capture_outcomes(cycles: list[dict], requested_cycles: int, status_delta: dict | None = None) -> dict:
    completed = [c for c in cycles if bool(c.get("completed", False))]
    ack_seen = [
        c
        for c in completed
        if bool(c.get("ack_seen_bool", False)) or isinstance(c.get("trigger_to_ack_ms"), (int, float))
    ]
    frame_selected = [
        c
        for c in completed
        if bool(c.get("frame_selected_bool", False)) or isinstance(c.get("trigger_to_frame_ms"), (int, float))
    ]
    flash_detected = [
        c
        for c in completed
        if bool(c.get("flash_detected_bool", False)) or str(c.get("reason", "")) == "threshold"
    ]
    edge_timeout = [c for c in completed if str(c.get("reason", "")) == "edge_timeout"]
    camera_detection_miss = [
        c
        for c in ack_seen
        if bool(c.get("frame_selected_bool", False)) and not bool(c.get("flash_detected_bool", False))
    ]
    camera_frame_miss = [c for c in ack_seen if not bool(c.get("frame_selected_bool", False))]

    status_delta = status_delta or {}
    ext_delta = _int_or_none(status_delta.get("ext_count_delta"))
    flash_delta = _int_or_none(status_delta.get("flash_num_delta"))
    firmware_flash_success = flash_delta if flash_delta is not None else len(ack_seen)
    missed_flash = (
        max(0, int(ext_delta) - int(flash_delta))
        if ext_delta is not None and flash_delta is not None
        else len(edge_timeout)
    )
    trigger_not_observed = (
        max(0, len(completed) - int(ext_delta))
        if ext_delta is not None
        else None
    )

    def _indices(rows: list[dict]) -> list[int]:
        out = []
        for row in rows:
            idx = row.get("cycle_index")
            if isinstance(idx, int):
                out.append(idx)
        return out

    return {
        "requested_cycles": int(requested_cycles),
        "completed_cycles": len(completed),
        "pi_trigger_attempt_cycles": len(completed),
        "firmware_trigger_observed_cycles": ext_delta,
        "firmware_flash_success_cycles": firmware_flash_success,
        "missed_flash_cycles": missed_flash,
        "trigger_attempt_not_observed_cycles": trigger_not_observed,
        "ack_seen_cycles": len(ack_seen),
        "camera_frame_selected_cycles": len(frame_selected),
        "camera_flash_detected_cycles": len(flash_detected),
        "camera_detection_miss_cycles": len(camera_detection_miss),
        "camera_frame_miss_cycles": len(camera_frame_miss),
        "edge_timeout_cycles": len(edge_timeout),
        "camera_detection_miss_indices": _indices(camera_detection_miss),
        "edge_timeout_indices": _indices(edge_timeout),
        "status_counter_source": "status_delta"
        if ext_delta is not None or flash_delta is not None
        else "cycle_flags",
    }


def _gpiofind(name: str) -> tuple[str, int]:
    out = subprocess.check_output(["gpiofind", name], text=True).strip()
    chip, off = out.split()
    return chip, int(off)


def _open_chip(chip_name: str):
    import gpiod

    tried = []
    for name in (chip_name, f"/dev/{chip_name}" if not chip_name.startswith("/dev/") else None):
        if not name:
            continue
        tried.append(name)
        try:
            return gpiod.Chip(name)
        except FileNotFoundError:
            continue
    available = " ".join(sorted(glob.glob("/dev/gpiochip*"))) or "<none>"
    raise FileNotFoundError(f"Could not open GPIO chip {chip_name!r}. Tried {tried}. Available chips: {available}")


def _make_output_line(chip_name: str, offset: int, initial: int = 0):
    import gpiod

    is_v2 = hasattr(gpiod, "line")

    if is_v2:
        chip = _open_chip(chip_name)
        ls = gpiod.LineSettings()
        Direction = gpiod.line.Direction
        Value = gpiod.line.Value
        ls.direction = Direction.OUTPUT
        ls.output_value = Value.ACTIVE if initial else Value.INACTIVE
        req = chip.request_lines(consumer="camera_bench_out", config={offset: ls})

        class OutV2:
            def set_value(self, val: int):
                req.set_values({offset: Value.ACTIVE if int(val) else Value.INACTIVE})

            def read_value(self):
                try:
                    vals = req.get_values([offset])
                    if isinstance(vals, dict):
                        v = vals.get(offset, 0)
                    elif isinstance(vals, (list, tuple)):
                        v = vals[0] if vals else 0
                    else:
                        v = vals
                    if hasattr(v, "value"):
                        return int(v.value)
                    return int(v)
                except Exception:
                    return None

            def release(self):
                req.release()
                try:
                    chip.close()
                except Exception:
                    pass

        return OutV2()

    chip = _open_chip(chip_name)
    line = chip.get_line(offset)
    line.request(consumer="camera_bench_out", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[initial])

    class OutV1:
        def set_value(self, val: int):
            line.set_value(int(val))

        def read_value(self):
            try:
                return int(line.get_value())
            except Exception:
                return None

        def release(self):
            line.release()
            chip.close()

    return OutV1()


def _make_rising_edge_input(chip_name: str, offset: int):
    import gpiod
    is_v2 = hasattr(gpiod, "line")

    if is_v2:
        chip = _open_chip(chip_name)
        ls = gpiod.LineSettings()
        Direction = gpiod.line.Direction
        Edge = gpiod.line.Edge
        Bias = getattr(gpiod.line, "Bias", None)
        ls.direction = Direction.INPUT
        ls.edge_detection = Edge.RISING
        if Bias is not None:
            try:
                ls.bias = Bias.PULL_DOWN
            except Exception:
                pass
        req = chip.request_lines(consumer="camera_bench_in", config={offset: ls})

        class InV2:
            def event_wait(self, timeout_s: float) -> bool:
                return req.wait_edge_events(float(timeout_s))

            def event_consume(self):
                _ = req.read_edge_events()

            def read_value(self):
                try:
                    vals = req.get_values([offset])
                    if isinstance(vals, dict):
                        v = vals.get(offset, 0)
                    elif isinstance(vals, (list, tuple)):
                        v = vals[0] if vals else 0
                    else:
                        v = vals
                    if hasattr(v, "value"):
                        return int(v.value)
                    return int(v)
                except Exception:
                    try:
                        v = req.get_value(offset)
                        if hasattr(v, "value"):
                            return int(v.value)
                        return int(v)
                    except Exception:
                        return None

            def release(self):
                req.release()
                chip.close()

        return InV2()

    chip = _open_chip(chip_name)
    line = chip.get_line(offset)
    flags = 0
    if hasattr(gpiod, "LINE_REQ_FLAG_BIAS_PULL_DOWN"):
        flags |= gpiod.LINE_REQ_FLAG_BIAS_PULL_DOWN
    line.request(consumer="camera_bench_in", type=gpiod.LINE_REQ_EV_RISING_EDGE, flags=flags)

    class InV1:
        def event_wait(self, timeout_s: float) -> bool:
            secs = int(max(0.0, float(timeout_s)))
            nsecs = int(max(0.0, float(timeout_s) - secs) * 1_000_000_000)
            return line.event_wait(secs, nsecs)

        def event_consume(self):
            _ = line.event_read()

        def read_value(self):
            try:
                return int(line.get_value())
            except Exception:
                return None

        def release(self):
            line.release()
            chip.close()

    return InV1()


def _baseline_before_ns(buf: deque, cutoff_ns: int, n: int) -> tuple[float, float]:
    import numpy as np

    vals = []
    for _arr, _md, t_done_ns, mean in reversed(buf):
        if t_done_ns < cutoff_ns:
            vals.append(float(mean))
            if len(vals) >= n:
                break
    if len(vals) < 2:
        tail = [float(item[3]) for item in list(buf)[-n:]]
        vals = tail if tail else [0.0, 0.0]
    arr = np.array(vals, dtype=float)
    return float(np.mean(arr)), float(np.std(arr))


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
            crc &= 0xFFFF
    return crc


def _parse_tlvs(payload: bytes) -> dict[int, bytes]:
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


def _tlv_u32(tlv: dict[int, bytes], tag: int) -> int | None:
    raw = tlv.get(tag)
    if raw is None or len(raw) != 4:
        return None
    return int.from_bytes(raw, "little")


def _tlv_u8(tlv: dict[int, bytes], tag: int) -> int | None:
    raw = tlv.get(tag)
    if raw is None or len(raw) != 1:
        return None
    return int(raw[0])


def _decode_ack_result(code: int | None) -> str | None:
    if code is None:
        return None
    return {
        ACK_RESULT_ACCEPTED: "accepted",
        ACK_RESULT_DUPLICATE: "duplicate",
        ACK_RESULT_GAP: "gap",
        ACK_RESULT_BUSY: "busy",
        ACK_RESULT_WATERMARK_SET: "watermark_set",
        ACK_RESULT_WATERMARK_REJECTED: "watermark_rejected",
    }.get(int(code), f"unknown_{int(code)}")


def _read_queue_ack(ser, *, seq8: int, seq32: int, timeout_ms: int = QUEUE_ACK_TIMEOUT_MS) -> dict:
    deadline = time.monotonic() + (max(1, int(timeout_ms)) / 1000.0)
    state = 0
    expected_len = 0
    buf = bytearray()
    observed = []
    while time.monotonic() < deadline:
        chunk = ser.read(1)
        if not chunk:
            continue
        for b in chunk:
            if state == 0:
                if b == 0xAA:
                    state = 1
                continue
            if state == 1:
                expected_len = int(b)
                buf.clear()
                state = 2
                continue

            buf.append(b)
            if len(buf) < expected_len + 2:
                continue
            payload = bytes(buf[:expected_len])
            rec_crc = int(buf[expected_len]) | (int(buf[expected_len + 1]) << 8)
            state = 0
            buf.clear()
            if _crc16(payload) != rec_crc or len(payload) < 2:
                continue
            cmd = int(payload[0])
            observed_seq8 = int(payload[1])
            if cmd != CMD_QUEUE_ACK:
                observed.append({"cmd": cmd, "seq8": observed_seq8})
                continue
            tlv = _parse_tlvs(payload[2:])
            observed_seq32 = _tlv_u32(tlv, TAG_SEQ32)
            ack_result_code = _tlv_u8(tlv, TAG_ACK_RESULT)
            ack = {
                "cmd": cmd,
                "seq8": observed_seq8,
                "seq32": observed_seq32,
                "expected_seq8": int(seq8) & 0xFF,
                "expected_seq32": int(seq32),
                "ack_result": _decode_ack_result(ack_result_code),
                "ack_result_code": ack_result_code,
                "expected_seq32_from_mcu": _tlv_u32(tlv, TAG_EXPECTED_SEQ32),
            }
            if observed_seq32 != int(seq32):
                observed.append(dict(ack))
                continue
            if observed_seq8 != (int(seq8) & 0xFF):
                ack["seq8_mismatch"] = True
            if observed:
                ack["observed_ignored"] = observed
            return ack
    return {
        "seq8": int(seq8) & 0xFF,
        "seq32": int(seq32),
        "expected_seq32": int(seq32),
        "ack_result": "timeout",
        "ack_result_code": None,
        "timeout_ms": int(timeout_ms),
        "observed_ignored": observed,
    }


def _command_tlvs(*, p1: int | None = None, p2: int | None = None, p3: int | None = None) -> bytes:
    tlv = b""
    if p1 is not None:
        tlv += bytes([TAG_P1, 4]) + int(p1).to_bytes(4, "little", signed=False)
    if p2 is not None:
        tlv += bytes([TAG_P2, 4]) + int(p2).to_bytes(4, "little", signed=False)
    if p3 is not None:
        tlv += bytes([TAG_P3, 4]) + int(p3).to_bytes(4, "little", signed=False)
    return tlv


def _send_queued_command(
    ser,
    build_control_fn,
    *,
    name: str,
    cmd: int,
    seq32: int,
    p1: int | None = None,
    p2: int | None = None,
    p3: int | None = None,
    ack_timeout_ms: int = QUEUE_ACK_TIMEOUT_MS,
    max_retries: int = QUEUE_ACK_MAX_RETRIES,
) -> dict:
    seq32 = int(seq32)
    seq8 = seq32 & 0xFF
    tlvs = _command_tlvs(p1=p1, p2=p2, p3=p3)
    attempts = []
    for attempt_index in range(1, max(1, int(max_retries)) + 1):
        sent_ns = time.monotonic_ns()
        ser.write(build_control_fn(int(cmd), seq8, seq32, tlvs))
        ack = _read_queue_ack(ser, seq8=seq8, seq32=seq32, timeout_ms=ack_timeout_ms)
        ack["attempt_index"] = int(attempt_index)
        ack["sent_ns"] = int(sent_ns)
        attempts.append(ack)
        result = str(ack.get("ack_result") or "")
        if result == "accepted" or (result == "duplicate" and attempt_index > 1):
            return {
                "ok": True,
                "name": str(name),
                "cmd": int(cmd),
                "seq8": seq8,
                "seq32": seq32,
                "ack_result": result,
                "attempts": attempts,
            }
        if result == "busy" and attempt_index < max(1, int(max_retries)):
            continue
        if result == "timeout" and attempt_index < max(1, int(max_retries)):
            continue
        reason = result or "malformed_ack"
        if result == "duplicate":
            reason = "duplicate_without_retry"
        return {
            "ok": False,
            "name": str(name),
            "cmd": int(cmd),
            "seq8": seq8,
            "seq32": seq32,
            "reason": reason,
            "ack_result": result,
            "attempts": attempts,
        }
    return {
        "ok": False,
        "name": str(name),
        "cmd": int(cmd),
        "seq8": seq8,
        "seq32": seq32,
        "reason": "retry_exhausted",
        "attempts": attempts,
    }


def _status_snapshot_from_serial(ser, *, sample_ms: int = 250) -> dict:
    deadline = time.monotonic() + (max(1, int(sample_ms)) / 1000.0)
    state = 0
    expected_len = 0
    buf = bytearray()
    latest = {
        "flash_num": None,
        "flash_width_ns": None,
        "flash_delay_us": None,
        "imaging_droplets": None,
        "ext_count": None,
        "print_pressure": None,
        "refuel_pressure": None,
        "print_target": None,
        "refuel_target": None,
        "print_active": None,
        "refuel_active": None,
        "grip_pulse_ms": None,
        "grip_refresh_ms": None,
        "status_frames_seen": 0,
    }
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if not chunk:
            continue
        for b in chunk:
            if state == 0:
                if b == 0xAA:
                    state = 1
                continue
            if state == 1:
                expected_len = int(b)
                buf.clear()
                state = 2
                continue

            buf.append(b)
            if len(buf) < expected_len + 2:
                continue
            payload = bytes(buf[:expected_len])
            rec_crc = int(buf[expected_len]) | (int(buf[expected_len + 1]) << 8)
            state = 0
            buf.clear()
            if _crc16(payload) != rec_crc or len(payload) < 2:
                continue
            if payload[0] != CMD_STATUS:
                continue
            latest["status_frames_seen"] += 1
            # Status frames are `CMD_STATUS` followed directly by TLVs (no seq byte).
            tlv = _parse_tlvs(payload[1:])
            if TAG_FLASH_NUM in tlv and len(tlv[TAG_FLASH_NUM]) == 4:
                latest["flash_num"] = int.from_bytes(tlv[TAG_FLASH_NUM], "little")
            if TAG_EXT_COUNT in tlv and len(tlv[TAG_EXT_COUNT]) == 4:
                latest["ext_count"] = int.from_bytes(tlv[TAG_EXT_COUNT], "little")
            if TAG_FLASH_WIDTH in tlv and len(tlv[TAG_FLASH_WIDTH]) == 4:
                latest["flash_width_ns"] = int.from_bytes(tlv[TAG_FLASH_WIDTH], "little")
            if TAG_FLASH_DELAY in tlv and len(tlv[TAG_FLASH_DELAY]) == 4:
                latest["flash_delay_us"] = int.from_bytes(tlv[TAG_FLASH_DELAY], "little")
            if TAG_FLASH_DROPS in tlv and len(tlv[TAG_FLASH_DROPS]) in (2, 4):
                latest["imaging_droplets"] = int.from_bytes(tlv[TAG_FLASH_DROPS], "little")
            if TAG_PRINT_P in tlv and len(tlv[TAG_PRINT_P]) == 2:
                latest["print_pressure"] = int.from_bytes(tlv[TAG_PRINT_P], "little")
            if TAG_REFUEL_P in tlv and len(tlv[TAG_REFUEL_P]) == 2:
                latest["refuel_pressure"] = int.from_bytes(tlv[TAG_REFUEL_P], "little")
            if TAG_TAR_PRINT_P in tlv and len(tlv[TAG_TAR_PRINT_P]) == 2:
                latest["print_target"] = int.from_bytes(tlv[TAG_TAR_PRINT_P], "little")
            if TAG_TAR_REFUEL_P in tlv and len(tlv[TAG_TAR_REFUEL_P]) == 2:
                latest["refuel_target"] = int.from_bytes(tlv[TAG_TAR_REFUEL_P], "little")
            if TAG_ACTIVE_P in tlv and len(tlv[TAG_ACTIVE_P]) == 2:
                latest["print_active"] = int.from_bytes(tlv[TAG_ACTIVE_P], "little")
            if TAG_ACTIVE_R in tlv and len(tlv[TAG_ACTIVE_R]) == 2:
                latest["refuel_active"] = int.from_bytes(tlv[TAG_ACTIVE_R], "little")
            if TAG_GRIP_PULSE in tlv and len(tlv[TAG_GRIP_PULSE]) == 4:
                latest["grip_pulse_ms"] = int.from_bytes(tlv[TAG_GRIP_PULSE], "little")
            if TAG_GRIP_REFRESH in tlv and len(tlv[TAG_GRIP_REFRESH]) == 4:
                latest["grip_refresh_ms"] = int.from_bytes(tlv[TAG_GRIP_REFRESH], "little")
    return latest


def _pressure_raw_from_psi(psi: float) -> int:
    return int(round((float(psi) / PRESSURE_PSI_MAX) * PRESSURE_FSS + PRESSURE_PSI_OFFSET, 0))


def _is_pressure_ready(status: dict) -> bool:
    p_active = status.get("print_active")
    p = status.get("print_pressure")
    p_t = status.get("print_target")
    if not isinstance(p_active, int) or not isinstance(p, int) or not isinstance(p_t, int):
        return False
    if p_active == 0:
        return False
    if abs(int(p) - int(p_t)) > 50:
        return False
    r_active = status.get("refuel_active")
    r = status.get("refuel_pressure")
    r_t = status.get("refuel_target")
    if isinstance(r_active, int) and r_active != 0:
        if not isinstance(r, int) or not isinstance(r_t, int):
            return False
        if abs(int(r) - int(r_t)) > 50:
            return False
    return True


def _pressure_preflight(ser, timeout_ms: int) -> tuple[bool, dict]:
    deadline = time.monotonic() + (max(1, int(timeout_ms)) / 1000.0)
    latest = {}
    while time.monotonic() < deadline:
        latest = _status_snapshot_from_serial(ser, sample_ms=120)
        if int(latest.get("status_frames_seen", 0)) <= 0:
            continue
        if _is_pressure_ready(latest):
            return True, latest
    return False, latest


def _machine_ready_preflight(ser, build_control_fn, *, start_seq32: int, timeout_ms: int) -> tuple[int, dict]:
    started_ns = time.monotonic_ns()
    timeout_ms = max(MACHINE_READY_TIMEOUT_MS_MIN, int(timeout_ms))
    status_before = _status_snapshot_from_serial(ser, sample_ms=250)
    phases = []
    next_seq32 = int(start_seq32)

    def _mark_phase(
        name: str,
        cmd: int,
        *,
        p1: int | None = None,
        p2: int | None = None,
        p3: int | None = None,
    ):
        nonlocal next_seq32
        t0 = time.monotonic_ns()
        ack = _send_queued_command(
            ser,
            build_control_fn,
            name=name,
            cmd=cmd,
            seq32=next_seq32,
            p1=p1,
            p2=p2,
            p3=p3,
        )
        t1 = time.monotonic_ns()
        if ack.get("ok"):
            next_seq32 += 1
        phases.append(
            {
                "name": name,
                "cmd": int(cmd),
                "sent_ns": int(t1),
                "duration_ms": (t1 - t0) / 1_000_000.0,
                "ack": ack,
            }
        )
        return bool(ack.get("ok"))

    if not _mark_phase("enable_motors", CMD_ENABLE_MOTORS):
        ok = False
        status_ready = status_before
        reason = "command_setup_failed"
    elif not _mark_phase(
        "home_xy",
        CMD_HOME_XY,
        p1=HOME_FAST_HZ,
        p2=HOME_SLOW_HZ,
        p3=HOME_BACKOFF_STEPS,
    ):
        ok = False
        status_ready = status_before
        reason = "command_setup_failed"
    elif not _mark_phase(
        "home_pressure_regs",
        CMD_HOME_PR_BOTH,
        p1=HOME_FAST_HZ,
        p2=HOME_SLOW_HZ,
        p3=HOME_BACKOFF_STEPS,
    ):
        ok = False
        status_ready = status_before
        reason = "command_setup_failed"
    elif not _mark_phase("start_print_reg", CMD_P_REG_START):
        ok = False
        status_ready = status_before
        reason = "command_setup_failed"
    elif not _mark_phase("start_refuel_reg", CMD_R_REG_START):
        ok = False
        status_ready = status_before
        reason = "command_setup_failed"
    else:
        ok, status_ready = _pressure_preflight(ser, timeout_ms)
        reason = None if ok else "pressure_not_ready_timeout"
    finished_ns = time.monotonic_ns()
    return (
        next_seq32,
        {
            "required": True,
            "pass": bool(ok),
            "reason": reason,
            "timeout_ms": int(timeout_ms),
            "started_ns": int(started_ns),
            "finished_ns": int(finished_ns),
            "total_ms": (finished_ns - started_ns) / 1_000_000.0,
            "status_before": status_before,
            "status_after": status_ready,
            "phases": phases,
        },
    )


def _coordinated_flash_preflight(
    ser,
    build_control_fn,
    *,
    start_seq32: int,
    timeout_ms: int,
    pressure_psi: float,
    gripper_refresh_ms: int,
    gripper_pulse_ms: int,
) -> tuple[int, dict]:
    started_ns = time.monotonic_ns()
    timeout_ms = max(MACHINE_READY_TIMEOUT_MS_MIN, int(timeout_ms))
    status_before = _status_snapshot_from_serial(ser, sample_ms=250)
    phases = []
    next_seq32 = int(start_seq32)
    pressure_raw = _pressure_raw_from_psi(pressure_psi)
    gripper_refresh_ms = max(1000, int(gripper_refresh_ms))
    gripper_pulse_ms = max(1, int(gripper_pulse_ms))

    def _mark_phase(
        name: str,
        cmd: int,
        *,
        p1: int | None = None,
        p2: int | None = None,
        p3: int | None = None,
    ) -> bool:
        nonlocal next_seq32
        t0 = time.monotonic_ns()
        ack = _send_queued_command(
            ser,
            build_control_fn,
            name=name,
            cmd=cmd,
            seq32=next_seq32,
            p1=p1,
            p2=p2,
            p3=p3,
        )
        t1 = time.monotonic_ns()
        if ack.get("ok"):
            next_seq32 += 1
        phases.append(
            {
                "name": name,
                "cmd": int(cmd),
                "sent_ns": int(t1),
                "duration_ms": (t1 - t0) / 1_000_000.0,
                "ack": ack,
            }
        )
        return bool(ack.get("ok"))

    setup_steps = (
        ("enable_motors", CMD_ENABLE_MOTORS, None, None, None),
        ("home_xy", CMD_HOME_XY, HOME_FAST_HZ, HOME_SLOW_HZ, HOME_BACKOFF_STEPS),
        ("home_pressure_regs", CMD_HOME_PR_BOTH, HOME_FAST_HZ, HOME_SLOW_HZ, HOME_BACKOFF_STEPS),
        ("set_print_pressure", CMD_PR_PRINT, pressure_raw, None, None),
        ("set_refuel_pressure", CMD_PR_REFUEL, pressure_raw, None, None),
        ("start_print_reg", CMD_P_REG_START, None, None, None),
        ("start_refuel_reg", CMD_R_REG_START, None, None, None),
    )
    status_ready = status_before
    reason = None
    ok = True
    for name, cmd, p1, p2, p3 in setup_steps:
        if not _mark_phase(name, cmd, p1=p1, p2=p2, p3=p3):
            ok = False
            reason = "command_setup_failed"
            break

    if ok:
        ok, status_ready = _pressure_preflight(ser, timeout_ms)
        reason = None if ok else "pressure_not_ready_timeout"

    gripper_snapshot = _status_snapshot_from_serial(ser, sample_ms=250) if ok else {}
    prior_grip_refresh = gripper_snapshot.get("grip_refresh_ms")
    prior_grip_pulse = gripper_snapshot.get("grip_pulse_ms")
    applied_grip_pulse = int(gripper_pulse_ms)
    gripper_wait_finished_ns = None
    status_after_gripper = {}
    if ok:
        if not _mark_phase(
            "set_gripper_params",
            CMD_SET_GRIPPER_PARAMS,
            p1=gripper_refresh_ms,
            p2=applied_grip_pulse,
        ):
            ok = False
            reason = "command_setup_failed"
        elif not _mark_phase("open_gripper", CMD_GRIPPER_OPEN):
            ok = False
            reason = "command_setup_failed"
        else:
            time.sleep((applied_grip_pulse + 300) / 1000.0)
            gripper_wait_finished_ns = time.monotonic_ns()
            status_after_gripper = _status_snapshot_from_serial(ser, sample_ms=250)
            observed_refresh = status_after_gripper.get("grip_refresh_ms")
            observed_pulse = status_after_gripper.get("grip_pulse_ms")
            if isinstance(observed_refresh, int) and observed_refresh != gripper_refresh_ms:
                ok = False
                reason = "gripper_config_mismatch"
            elif isinstance(observed_pulse, int) and observed_pulse != applied_grip_pulse:
                ok = False
                reason = "gripper_config_mismatch"

    finished_ns = time.monotonic_ns()
    return (
        next_seq32,
        {
            "required": True,
            "pass": bool(ok),
            "reason": reason,
            "timeout_ms": int(timeout_ms),
            "started_ns": int(started_ns),
            "finished_ns": int(finished_ns),
            "total_ms": (finished_ns - started_ns) / 1_000_000.0,
            "status_before": status_before,
            "status_after_pressure": status_ready,
            "status_after_gripper": status_after_gripper,
            "phases": phases,
            "pressure": {
                "target_psi": float(pressure_psi),
                "target_raw": int(pressure_raw),
                "status_ready": status_ready,
            },
            "gripper": {
                "prior_refresh_ms": prior_grip_refresh,
                "prior_pulse_ms": prior_grip_pulse,
                "configured_refresh_ms": int(gripper_refresh_ms),
                "configured_pulse_ms": int(applied_grip_pulse),
                "open_wait_finished_ns": gripper_wait_finished_ns,
            },
        },
    )


def _wait_for_ack_with_level_probe(ack, timeout_s: float) -> tuple[bool, bool]:
    deadline = time.monotonic() + max(0.001, float(timeout_s))
    level_high_seen = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if ack.event_wait(min(0.002, max(0.0001, remaining))):
            ack.event_consume()
            return True, level_high_seen
        v = ack.read_value() if hasattr(ack, "read_value") else None
        if isinstance(v, int) and v != 0:
            level_high_seen = True
    return False, level_high_seen


def run_camera_flash_benchmark(
    ser,
    build_control_fn,
    *,
    run_id: int,
    config: BenchmarkConfig,
    start_seq32: int = 1,
) -> dict:
    mode = str(getattr(config, "mode", "flash_only") or "flash_only").strip().lower()
    run_order = str(getattr(config, "run_order", "pre_selftest") or "pre_selftest").strip().lower()
    if mode not in ("flash_only", "print_then_flash", "coordinated_flash"):
        mode = "flash_only"
    if run_order not in ("pre_selftest", "post_selftest"):
        run_order = "pre_selftest"
    next_seq32 = int(start_seq32)
    trig = None
    ack = None
    camera = None
    did_start_pressure_regs = False
    cleanup_diag = []
    cleanup_done = False
    coordinated_diag = {"required": mode == "coordinated_flash"}
    safe_flash_width = max(SAFE_FLASH_WIDTH_MIN_NS, min(SAFE_FLASH_WIDTH_MAX_NS, int(config.flash_width_us)))
    effective_droplets = 0 if mode == "flash_only" else max(1, int(config.num_droplets))
    preflight_timeout_ms = max(50, int(getattr(config, "preflight_pressure_timeout_ms", 1000)))
    min_trigger_period_ms = max(0, int(getattr(config, "min_trigger_period_ms", 0)))
    early_abort_consecutive_edge_timeouts = max(
        0, int(getattr(config, "early_abort_consecutive_edge_timeouts", 5))
    )

    def _config_payload(timeout_ms: int) -> dict:
        return {
            "cycles": int(config.cycles),
            "exposure_us": int(config.exposure_us),
            "flash_delay_us": int(config.flash_delay_us),
            "flash_width_us": int(config.flash_width_us),
            "safe_flash_width_ns_applied": int(safe_flash_width),
            "num_droplets": int(config.num_droplets),
            "effective_num_droplets": int(effective_droplets),
            "attempt_timeout_ms": int(config.attempt_timeout_ms),
            "max_new_frames": int(config.max_new_frames),
            "trigger_pin_bcm": int(config.trigger_pin_bcm),
            "flash_ack_pin_bcm": int(config.flash_ack_pin_bcm),
            "trigger_settle_ms": int(config.trigger_settle_ms),
            "post_cycle_settle_ms": int(config.post_cycle_settle_ms),
            "trigger_retries": int(config.trigger_retries),
            "mode": mode,
            "run_order": run_order,
            "preflight_pressure_timeout_ms": int(timeout_ms),
            "warmup_cycles": max(0, int(getattr(config, "warmup_cycles", 1))),
            "min_trigger_period_ms": int(min_trigger_period_ms),
            "early_abort_consecutive_edge_timeouts": int(early_abort_consecutive_edge_timeouts),
            "coordinated_pressure_psi": float(getattr(config, "coordinated_pressure_psi", COORDINATED_PRESSURE_PSI_DEFAULT)),
            "coordinated_gripper_refresh_ms": int(
                getattr(config, "coordinated_gripper_refresh_ms", COORDINATED_GRIPPER_REFRESH_MS_DEFAULT)
            ),
            "coordinated_gripper_pulse_ms": int(
                getattr(config, "coordinated_gripper_pulse_ms", COORDINATED_GRIPPER_PULSE_MS_DEFAULT)
            ),
        }

    def _zero_summary(reason: str, started_ns: int, finished_ns: int) -> dict:
        summary = summarize_cycles([], config.cycles, started_ns, finished_ns)
        summary["reason_distribution"] = {str(reason): int(max(1, int(config.cycles)))}
        summary["completed_cycles"] = 0
        summary["success_cycles"] = 0
        summary["ack_seen_cycles"] = 0
        summary["frame_selected_cycles"] = 0
        summary["flash_detected_cycles"] = 0
        summary["success_rate"] = 0.0
        return summary

    def _setup_failed_payload(
        *,
        reason: str,
        preflight: dict,
        init_diag: dict,
        status_snapshot: dict | None = None,
        failed_command: dict | None = None,
    ) -> dict:
        started_ns = time.monotonic_ns()
        finished_ns = started_ns
        diag = dict(init_diag)
        diag.setdefault("config_match", False)
        if failed_command is not None:
            diag["failed_command"] = failed_command
        return {
            "status": "setup_failed",
            "setup_failure_reason": str(reason),
            "mode": mode,
            "run_order": run_order,
            "next_seq32": int(next_seq32),
            "started_ns": started_ns,
            "finished_ns": finished_ns,
            "elapsed_ms": (finished_ns - started_ns) / 1_000_000.0,
            "config": _config_payload(preflight_timeout_ms),
            "preflight": preflight,
            "init_diag": diag,
            "status_snapshot_pre": status_snapshot or {},
            "status_snapshot_post": {},
            "status_snapshot_delta": {"ext_count_delta": None, "flash_num_delta": None},
            "summary": _zero_summary("setup_failed", started_ns, finished_ns),
            "classification": classify_capture_outcomes([], int(config.cycles), {}),
            "early_abort": {"triggered": False, "reason": None},
            "cycles": [],
            "warmup_count": 0,
            "warmup_cycles": [],
            "warmup_summary": summarize_cycles([], 0, started_ns, finished_ns),
            "coordinated_diag": coordinated_diag,
            "cleanup": cleanup_diag,
        }

    def _queue_cleanup_command(
        name: str,
        cmd: int,
        *,
        p1: int | None = None,
        p2: int | None = None,
        p3: int | None = None,
    ) -> dict:
        nonlocal next_seq32
        diag = _send_queued_command(
            ser,
            build_control_fn,
            name=name,
            cmd=cmd,
            seq32=next_seq32,
            p1=p1,
            p2=p2,
            p3=p3,
            ack_timeout_ms=QUEUE_ACK_TIMEOUT_MS,
            max_retries=1,
        )
        if diag.get("ok"):
            next_seq32 += 1
        cleanup_diag.append(diag)
        return diag

    def _run_coordinated_cleanup():
        nonlocal cleanup_done
        if cleanup_done or mode != "coordinated_flash":
            return
        cleanup_done = True
        gripper = ((coordinated_diag.get("preflight") or {}).get("gripper") or {})
        prior_refresh = gripper.get("prior_refresh_ms")
        prior_pulse = gripper.get("prior_pulse_ms")
        if isinstance(prior_refresh, int) and isinstance(prior_pulse, int):
            try:
                _queue_cleanup_command(
                    "restore_gripper_params",
                    CMD_SET_GRIPPER_PARAMS,
                    p1=prior_refresh,
                    p2=prior_pulse,
                )
            except Exception as exc:
                cleanup_diag.append({"ok": False, "name": "restore_gripper_params", "reason": str(exc)})
        for name, cmd in (
            ("gripper_off", CMD_GRIPPER_OFF),
            ("stop_print_reg", CMD_P_REG_STOP),
            ("stop_refuel_reg", CMD_R_REG_STOP),
            ("stop_flash", CMD_STOP_FLASH),
        ):
            try:
                _queue_cleanup_command(name, cmd)
            except Exception as exc:
                cleanup_diag.append({"ok": False, "name": name, "reason": str(exc)})

    def _finalize_payload(payload: dict) -> dict:
        if mode == "coordinated_flash":
            _run_coordinated_cleanup()
        payload["cleanup"] = cleanup_diag
        payload["next_seq32"] = int(next_seq32)
        return payload

    try:
        preflight = {"required": mode in ("print_then_flash", "coordinated_flash"), "pass": True, "timeout_ms": 0, "status": {}}
        if mode == "print_then_flash":
            timeout_ms = max(
                MACHINE_READY_TIMEOUT_MS_MIN, int(getattr(config, "preflight_pressure_timeout_ms", 1000))
            )
            preflight_timeout_ms = timeout_ms
            next_seq32, preflight = _machine_ready_preflight(
                ser,
                build_control_fn,
                start_seq32=next_seq32,
                timeout_ms=timeout_ms,
            )
            did_start_pressure_regs = True
            if not bool(preflight.get("pass", False)):
                if preflight.get("reason") == "command_setup_failed":
                    return _finalize_payload(_setup_failed_payload(
                        reason="command_ack_failed",
                        preflight=preflight,
                        init_diag={"config_match": False, "setup_acks": [], "preflight": preflight},
                    ))
                started_ns = time.monotonic_ns()
                finished_ns = started_ns
                cycles = []
                summary = _zero_summary("skipped_not_pressure_ready", started_ns, finished_ns)
                return _finalize_payload({
                    "status": "skipped_not_pressure_ready",
                    "mode": mode,
                    "run_order": run_order,
                    "next_seq32": int(next_seq32),
                    "started_ns": started_ns,
                    "finished_ns": finished_ns,
                    "elapsed_ms": (finished_ns - started_ns) / 1_000_000.0,
                    "config": _config_payload(timeout_ms),
                    "preflight": preflight,
                    "init_diag": {},
                    "status_snapshot_pre": {},
                    "status_snapshot_post": {},
                    "status_snapshot_delta": {"ext_count_delta": None, "flash_num_delta": None},
                    "summary": summary,
                    "classification": classify_capture_outcomes([], int(config.cycles), {}),
                    "early_abort": {"triggered": False, "reason": None},
                    "cycles": cycles,
                    "warmup_count": 0,
                    "warmup_cycles": [],
                    "warmup_summary": summarize_cycles([], 0, started_ns, finished_ns),
                    "coordinated_diag": coordinated_diag,
                    "cleanup": cleanup_diag,
                })
        elif mode == "coordinated_flash":
            timeout_ms = max(
                MACHINE_READY_TIMEOUT_MS_MIN, int(getattr(config, "preflight_pressure_timeout_ms", 1000))
            )
            preflight_timeout_ms = timeout_ms
            next_seq32, preflight = _coordinated_flash_preflight(
                ser,
                build_control_fn,
                start_seq32=next_seq32,
                timeout_ms=timeout_ms,
                pressure_psi=float(getattr(config, "coordinated_pressure_psi", COORDINATED_PRESSURE_PSI_DEFAULT)),
                gripper_refresh_ms=int(
                    getattr(config, "coordinated_gripper_refresh_ms", COORDINATED_GRIPPER_REFRESH_MS_DEFAULT)
                ),
                gripper_pulse_ms=int(
                    getattr(config, "coordinated_gripper_pulse_ms", COORDINATED_GRIPPER_PULSE_MS_DEFAULT)
                ),
            )
            did_start_pressure_regs = True
            coordinated_diag["preflight"] = preflight
            if not bool(preflight.get("pass", False)):
                return _finalize_payload(_setup_failed_payload(
                    reason=str(preflight.get("reason") or "coordinated_preflight_failed"),
                    preflight=preflight,
                    init_diag={"config_match": False, "setup_acks": [], "preflight": preflight},
                    status_snapshot=(preflight.get("status_after_gripper") or preflight.get("status_after_pressure") or {}),
                ))

        # Apply fixed imaging settings once (fixed-settings benchmark path).
        setup_acks = []
        for name, cmd, p1 in (
            ("init_flash", CMD_INIT_FLASH, None),
            ("flash_duration", CMD_SET_FLASH_DURATION, int(safe_flash_width)),
            ("flash_delay", CMD_SET_FLASH_DELAY, int(config.flash_delay_us)),
            ("imaging_droplets", CMD_SET_IMAGING_DROPLETS, int(effective_droplets)),
        ):
            ack_diag = _send_queued_command(
                ser,
                build_control_fn,
                name=name,
                cmd=cmd,
                seq32=next_seq32,
                p1=p1,
            )
            setup_acks.append(ack_diag)
            if not bool(ack_diag.get("ok", False)):
                return _finalize_payload(_setup_failed_payload(
                    reason="command_ack_failed",
                    preflight=preflight,
                    init_diag={"config_match": False, "setup_acks": setup_acks},
                    failed_command=ack_diag,
                ))
            next_seq32 += 1

        init_status = _status_snapshot_from_serial(ser, sample_ms=250)
        init_diag = {
            "status_frames_seen": int(init_status.get("status_frames_seen", 0)),
            "observed_flash_delay_us": init_status.get("flash_delay_us"),
            "observed_flash_width_ns": init_status.get("flash_width_ns"),
            "observed_imaging_droplets": init_status.get("imaging_droplets"),
            "setup_acks": setup_acks,
            "config_match": (
                init_status.get("flash_delay_us") == int(config.flash_delay_us)
                and init_status.get("flash_width_ns") == int(safe_flash_width)
                and init_status.get("imaging_droplets") == int(effective_droplets)
            )
            if int(init_status.get("status_frames_seen", 0)) > 0
            else False,
        }
        if not bool(init_diag.get("config_match", False)):
            return _finalize_payload(_setup_failed_payload(
                reason="config_mismatch",
                preflight=preflight,
                init_diag=init_diag,
                status_snapshot=init_status,
            ))

        import numpy as np
        from picamera2 import Picamera2

        trigger_chip, trigger_offset = _gpiofind(f"GPIO{config.trigger_pin_bcm}")
        ack_chip, ack_offset = _gpiofind(f"GPIO{config.flash_ack_pin_bcm}")
        trig = _make_output_line(trigger_chip, trigger_offset, initial=0)
        ack = _make_rising_edge_input(ack_chip, ack_offset)
        camera = Picamera2(1)
        vid_cfg = camera.create_video_configuration(
            main={"size": camera.sensor_resolution, "format": "RGB888"},
            buffer_count=3,
        )
        camera.configure(vid_cfg)
        camera.set_controls(
            {
                "FrameDurationLimits": (int(config.exposure_us), int(config.exposure_us)),
                "ExposureTime": int(config.exposure_us),
                "AeEnable": False,
                "AwbEnable": False,
                "AnalogueGain": 1.0,
            }
        )
        camera.start()

        buf = deque(maxlen=16)  # (arr, md, t_done_ns, mean)
        timeout_s = max(0.001, float(config.attempt_timeout_ms) / 1000.0)
        max_new_frames = max(1, int(config.max_new_frames))
        min_trigger_period_ns = int(min_trigger_period_ms) * 1_000_000
        last_trigger_start_ns = None

        def _capture_cycle(cycle_idx: int, phase: str) -> dict:
            row = {
                "cycle_index": int(cycle_idx),
                "phase": str(phase),
                "attempt_index": 1,
                "completed": False,
            }
            t_cycle_start = time.monotonic_ns()
            row["t_cycle_start"] = t_cycle_start

            retries = max(1, int(config.trigger_retries))
            t_trigger_high = None
            t_ack_edge = None
            ack_level_high_seen = False
            for attempt_idx in range(1, retries + 1):
                row["attempt_index"] = attempt_idx

                # Ensure clean LOW level before a fresh trigger edge.
                trig.set_value(0)
                row["t_trigger_set_low"] = time.monotonic_ns()
                row["trigger_level_after_set_low"] = trig.read_value() if hasattr(trig, "read_value") else None
                settle_ms = max(0, int(config.trigger_settle_ms))
                if settle_ms > 0:
                    time.sleep(settle_ms / 1000.0)

                # Drain stale ack edges.
                while ack.event_wait(0.0):
                    ack.event_consume()
                row["ack_level_before_wait"] = ack.read_value() if hasattr(ack, "read_value") else None

                trig.set_value(1)
                row["t_trigger_set_high"] = time.monotonic_ns()
                row["trigger_level_after_set_high"] = trig.read_value() if hasattr(trig, "read_value") else None
                t_trigger_high = time.monotonic_ns()
                row["t_trigger_high"] = t_trigger_high

                t_wait_start = time.monotonic_ns()
                edge_seen, level_seen = _wait_for_ack_with_level_probe(ack, timeout_s)
                t_wait_end = time.monotonic_ns()
                row["edge_wait_ms"] = (t_wait_end - t_wait_start) / 1_000_000.0
                row["ack_level_after_wait"] = ack.read_value() if hasattr(ack, "read_value") else None
                ack_level_high_seen = ack_level_high_seen or bool(level_seen)
                if edge_seen:
                    t_ack_edge = time.monotonic_ns()
                    row["t_ack_edge"] = t_ack_edge
                    break

            if t_ack_edge is None or t_trigger_high is None:
                trig.set_value(0)
                row["t_trigger_set_low_final"] = time.monotonic_ns()
                row["trigger_level_after_set_low_final"] = trig.read_value() if hasattr(trig, "read_value") else None
                t_cycle_end = time.monotonic_ns()
                timeout_subreason = "no_edge_no_level"
                if bool(ack_level_high_seen):
                    timeout_subreason = "level_seen_no_edge"
                elif isinstance(row.get("ack_level_after_wait"), int) and int(row.get("ack_level_after_wait")) != 0:
                    timeout_subreason = "line_high_no_edge"
                row.update(
                    {
                        "reason": "edge_timeout",
                        "edge_timeout_subreason": timeout_subreason,
                        "success_bool": False,
                        "ack_seen_bool": False,
                        "ack_level_high_seen_bool": bool(ack_level_high_seen),
                        "frame_selected_bool": False,
                        "flash_detected_bool": False,
                        "completed": True,
                        "t_cycle_end": t_cycle_end,
                        "cycle_total_ms": (t_cycle_end - t_cycle_start) / 1_000_000.0,
                    }
                )
                post_ms = max(0, int(config.post_cycle_settle_ms))
                if post_ms > 0:
                    time.sleep(post_ms / 1000.0)
                return row

            trig.set_value(0)
            row["t_trigger_set_low_after_ack"] = time.monotonic_ns()
            row["trigger_level_after_set_low_after_ack"] = trig.read_value() if hasattr(trig, "read_value") else None
            t_arm_gate = time.monotonic_ns()
            row["t_arm_gate"] = t_arm_gate

            base_mean, base_std = _baseline_before_ns(buf, t_arm_gate, config.baseline_frames)
            threshold = base_mean + config.k_sigma * max(base_std, 1.0) + config.min_delta
            threshold = min(threshold, config.threshold_cap)

            cap_deadline = time.monotonic() + timeout_s
            cap_seen = 0
            chosen = None
            brightest = None
            reason = "last_resort"

            while True:
                req = camera.capture_request()
                if req is None:
                    continue
                t_done_ns = time.monotonic_ns()
                try:
                    md = req.get_metadata()
                    arr = req.make_array("main")
                finally:
                    req.release()

                mean = float(np.mean(arr))
                buf.append((arr, md, t_done_ns, mean))

                if t_done_ns <= t_arm_gate:
                    if time.monotonic() > cap_deadline:
                        chosen = (arr, md, t_done_ns, mean)
                        reason = "last_resort"
                        break
                    continue

                cap_seen += 1
                if brightest is None or mean > brightest[3]:
                    brightest = (arr, md, t_done_ns, mean)
                if mean >= threshold:
                    chosen = (arr, md, t_done_ns, mean)
                    reason = "threshold"
                    break
                if cap_seen >= max_new_frames or time.monotonic() > cap_deadline:
                    if brightest is not None:
                        chosen = brightest
                        reason = "fallback"
                    else:
                        chosen = (arr, md, t_done_ns, mean)
                        reason = "last_resort"
                    break

            t_cycle_end = time.monotonic_ns()
            t_selected = int(chosen[2]) if chosen is not None else t_cycle_end
            selected_mean = float(chosen[3]) if chosen is not None else None
            flash_detected = reason == "threshold"

            row.update(
                {
                    "completed": True,
                    "reason": reason,
                    "threshold": float(threshold),
                    "selected_mean": selected_mean,
                    "post_arm_frames_seen": int(cap_seen),
                    "success_bool": bool(flash_detected),
                    "ack_seen_bool": True,
                    "ack_level_high_seen_bool": bool(ack_level_high_seen),
                    "frame_selected_bool": bool(chosen is not None),
                    "flash_detected_bool": bool(flash_detected),
                    "t_selected_frame_done": t_selected,
                    "t_cycle_end": t_cycle_end,
                    "trigger_to_ack_ms": (t_ack_edge - t_trigger_high) / 1_000_000.0,
                    "ack_to_arm_ms": (t_arm_gate - t_ack_edge) / 1_000_000.0,
                    "arm_to_frame_ms": (t_selected - t_arm_gate) / 1_000_000.0,
                    "trigger_to_frame_ms": (t_selected - t_trigger_high) / 1_000_000.0,
                    "cycle_total_ms": (t_cycle_end - t_cycle_start) / 1_000_000.0,
                }
            )
            post_ms = max(0, int(config.post_cycle_settle_ms))
            if post_ms > 0:
                time.sleep(post_ms / 1000.0)
            return row

        def _capture_cycle_with_rate_limit(cycle_idx: int, phase: str) -> dict:
            nonlocal last_trigger_start_ns
            previous_start_ns = last_trigger_start_ns
            waited_ms = 0.0
            if previous_start_ns is not None and min_trigger_period_ns > 0:
                now_ns = time.monotonic_ns()
                earliest_ns = int(previous_start_ns) + min_trigger_period_ns
                if now_ns < earliest_ns:
                    wait_ns = earliest_ns - now_ns
                    waited_ms = wait_ns / 1_000_000.0
                    time.sleep(wait_ns / 1_000_000_000.0)
            row = _capture_cycle(cycle_idx, phase)
            start_ns = row.get("t_cycle_start")
            if isinstance(start_ns, int):
                last_trigger_start_ns = start_ns
            else:
                last_trigger_start_ns = time.monotonic_ns()
            row["min_trigger_period_ms"] = int(min_trigger_period_ms)
            row["trigger_period_wait_ms"] = float(waited_ms)
            row["previous_trigger_start_delta_ms"] = (
                (int(last_trigger_start_ns) - int(previous_start_ns)) / 1_000_000.0
                if previous_start_ns is not None
                else None
            )
            return row

        warmup_count = max(0, int(getattr(config, "warmup_cycles", 1)))
        warmup_started_ns = time.monotonic_ns()
        warmup_results = [_capture_cycle_with_rate_limit(i, "warmup") for i in range(warmup_count)]
        warmup_finished_ns = time.monotonic_ns()
        warmup_summary = summarize_cycles(warmup_results, warmup_count, warmup_started_ns, warmup_finished_ns)

        results = []
        early_abort = {"triggered": False, "reason": None}
        consecutive_edge_timeouts = 0
        status_pre = _status_snapshot_from_serial(ser, sample_ms=250)
        started_ns = time.monotonic_ns()
        for cycle_idx in range(max(1, int(config.cycles))):
            row = _capture_cycle_with_rate_limit(cycle_idx, "counted")
            results.append(row)
            if str(row.get("reason", "")) == "edge_timeout":
                consecutive_edge_timeouts += 1
            else:
                consecutive_edge_timeouts = 0
            if (
                early_abort_consecutive_edge_timeouts > 0
                and consecutive_edge_timeouts >= early_abort_consecutive_edge_timeouts
            ):
                early_abort = {
                    "triggered": True,
                    "reason": "consecutive_edge_timeouts",
                    "after_completed_cycles": len(results),
                    "consecutive_edge_timeouts": int(consecutive_edge_timeouts),
                    "threshold": int(early_abort_consecutive_edge_timeouts),
                }
                break

        finished_ns = time.monotonic_ns()
        status_post = _status_snapshot_from_serial(ser, sample_ms=250)
        summary = summarize_cycles(results, config.cycles, started_ns, finished_ns)
        ext_pre = status_pre.get("ext_count")
        ext_post = status_post.get("ext_count")
        flash_pre = status_pre.get("flash_num")
        flash_post = status_post.get("flash_num")
        status_delta = {
            "ext_count_delta": (int(ext_post) - int(ext_pre)) if isinstance(ext_pre, int) and isinstance(ext_post, int) else None,
            "flash_num_delta": (int(flash_post) - int(flash_pre)) if isinstance(flash_pre, int) and isinstance(flash_post, int) else None,
        }
        classification = classify_capture_outcomes(results, int(config.cycles), status_delta)
        if mode == "coordinated_flash":
            gripper = ((coordinated_diag.get("preflight") or {}).get("gripper") or {})
            open_wait_finished_ns = gripper.get("open_wait_finished_ns")
            refresh_ms = gripper.get("configured_refresh_ms")
            overlap_window_satisfied = False
            if isinstance(open_wait_finished_ns, int) and isinstance(refresh_ms, int):
                overlap_window_satisfied = (finished_ns - open_wait_finished_ns) >= int(refresh_ms) * 1_000_000
            coordinated_diag["counted_elapsed_ms"] = (finished_ns - started_ns) / 1_000_000.0
            coordinated_diag["total_elapsed_ms"] = (finished_ns - ((coordinated_diag.get("preflight") or {}).get("started_ns") or started_ns)) / 1_000_000.0
            coordinated_diag["overlap_window_satisfied"] = bool(overlap_window_satisfied)

        return _finalize_payload({
            "status": "ok",
            "mode": mode,
            "run_order": run_order,
            "next_seq32": int(next_seq32),
            "started_ns": started_ns,
            "finished_ns": finished_ns,
            "elapsed_ms": (finished_ns - started_ns) / 1_000_000.0,
            "config": _config_payload(preflight_timeout_ms),
            "preflight": preflight,
            "init_diag": init_diag,
            "status_snapshot_pre": status_pre,
            "status_snapshot_post": status_post,
            "status_snapshot_delta": status_delta,
            "summary": summary,
            "classification": classification,
            "early_abort": early_abort,
            "cycles": results,
            "warmup_count": int(warmup_count),
            "warmup_cycles": warmup_results,
            "warmup_summary": warmup_summary,
            "coordinated_diag": coordinated_diag,
            "cleanup": cleanup_diag,
        })
    finally:
        if mode == "coordinated_flash":
            try:
                _run_coordinated_cleanup()
            except Exception:
                pass
        try:
            # Prevent benchmark setup from perturbing later selftest memory headroom.
            ser.write(build_control_fn(CMD_STOP_FLASH, 0x6F, run_id))
        except Exception:
            pass
        if mode == "print_then_flash" and did_start_pressure_regs:
            try:
                ser.write(build_control_fn(CMD_P_REG_STOP, 0x70, run_id))
            except Exception:
                pass
            try:
                ser.write(build_control_fn(CMD_R_REG_STOP, 0x71, run_id))
            except Exception:
                pass
        try:
            if trig is not None:
                trig.set_value(0)
        except Exception:
            pass
        try:
            if ack is not None:
                ack.release()
        except Exception:
            pass
        try:
            if trig is not None:
                trig.release()
        except Exception:
            pass
        if camera is not None:
            try:
                camera.stop()
                camera.close()
            except Exception:
                pass
