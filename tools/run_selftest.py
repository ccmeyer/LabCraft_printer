#!/usr/bin/env python3
import argparse
from collections import deque
import csv
import json
import os
import re
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
CMD_RESUME = 0xF1
CMD_HELLO_ACK = 0xF4
CMD_GOODBYE = 0xF5
CMD_BYE_ACK = 0xF6
CMD_BYE_DONE = 0xF8
CMD_RESET_REPORT = 0xF9
CMD_SELFTEST_START = 0xFA
CMD_SELFTEST_RESULT = 0xFB
CMD_SELFTEST_DONE = 0xFC
CMD_SELFTEST_ABORT = 0xFD
CMD_QUEUE_ACK = 0xFE
CMD_GRIPPER_OPEN = 0x10
CMD_GRIPPER_OFF = 0x12
SELFTEST_EVENT_PREFIX = "SELFTEST_EVENT "

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
TAG_ACK_RESULT = 0x11
TAG_EXPECTED_SEQ32 = 0x12
TAG_CAPABILITIES = 0x13
TAG_TRACE_CHANNEL = 0x40
TAG_TRACE_PRESSURE_MPSI = 0x41
TAG_TRACE_PULSE_US = 0x42
TAG_TRACE_PULSE_COUNT = 0x43
TAG_TRACE_FREQUENCY_HZ = 0x44
TAG_RESET_SEQ32 = 0x10
TAG_RESET_CAUSE = 0x11
TAG_RESET_FLAGS = 0x12
TAG_RESET_LAST_FAULT = 0x13
TAG_RESET_LAST_TASK = 0x14
TAG_RESET_BOOT_COUNT = 0x15
TAG_RESET_FAULT_COUNT = 0x16
TAG_RESET_WATCHDOG_COUNT = 0x17
TAG_RESET_WATCHDOG_STICKY_CT = 0x18
TAG_RESET_WATCHDOG_RAW_SR = 0x19
TAG_RESET_UPTIME_MS = 0x1A
TAG_RESET_BOOT_STAGE = 0x1B
TAG_RESET_RECOVERY_BOOT = 0x1C
TAG_RESET_FAULT_STAGE = 0x1D
TAG_RESET_WATCHDOG_LATE_TASK = 0x1E
TAG_RESET_ACTIVE_COMMAND = 0x1F
TAG_RESET_REG_CONTEXT = 0x22
TAG_RESET_FAULT_CONTEXT = 0x23

ACK_RESULT_ACCEPTED = 1
ACK_RESULT_DUPLICATE = 2
ACK_RESULT_GAP = 3
ACK_RESULT_BUSY = 4
ACK_RESULT_WATERMARK_SET = 5
ACK_RESULT_WATERMARK_REJECTED = 6

TRANSPORT_CAP_QUEUE_ACK = 1 << 0
TRANSPORT_CAP_SESSION_SEQ_PERSIST = 1 << 3
SELFTEST_TRANSPORT_CAPS = TRANSPORT_CAP_QUEUE_ACK | TRANSPORT_CAP_SESSION_SEQ_PERSIST

TRACE_KIND_SAMPLES = 1
TRACE_KIND_EVENTS = 2
TRACE_FORMAT_SAMPLE_V1 = 1
TRACE_FORMAT_EVENT_V1 = 2
CUSTOM_PRESSURE_TRACE_TEST_ID = 2110
TRACE_PRESSURE_MPSI_MIN = 100
TRACE_PRESSURE_MPSI_MAX = 2500
TRACE_PULSE_US_MIN = 100
TRACE_PULSE_US_MAX = 10000
TRACE_PULSE_COUNT_MIN = 1
TRACE_PULSE_COUNT_MAX = 100
TRACE_FREQUENCY_HZ_MIN = 1
TRACE_FREQUENCY_HZ_MAX = 50
TRACE_MAX_PULSE_WINDOW_MS = 10000
TRACE_CHANNEL_CODES = {"print": 0, "refuel": 1}


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


def _validated_custom_trace_config(args: argparse.Namespace) -> dict | None:
    if not bool(getattr(args, "pressure_trace_custom", False)):
        return None

    channel = str(getattr(args, "trace_channel", "") or "").strip().lower()
    if channel not in TRACE_CHANNEL_CODES:
        raise ValueError("custom pressure trace requires --trace-channel print|refuel")

    def required_int(name: str, label: str) -> int:
        value = getattr(args, name, None)
        if value is None:
            raise ValueError(f"custom pressure trace requires --{label}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"--{label} must be an integer") from exc

    pressure_psi = getattr(args, "trace_pressure_psi", None)
    if pressure_psi is None:
        raise ValueError("custom pressure trace requires --trace-pressure-psi")
    try:
        pressure_mpsi = int(round(float(pressure_psi) * 1000.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("--trace-pressure-psi must be numeric") from exc

    pulse_us = required_int("trace_pulse_us", "trace-pulse-us")
    pulse_count = required_int("trace_pulse_count", "trace-pulse-count")
    frequency_hz = required_int("trace_frequency_hz", "trace-frequency-hz")

    if not (TRACE_PRESSURE_MPSI_MIN <= pressure_mpsi <= TRACE_PRESSURE_MPSI_MAX):
        raise ValueError(
            f"--trace-pressure-psi must be between {TRACE_PRESSURE_MPSI_MIN / 1000:g} "
            f"and {TRACE_PRESSURE_MPSI_MAX / 1000:g}"
        )
    if not (TRACE_PULSE_US_MIN <= pulse_us <= TRACE_PULSE_US_MAX):
        raise ValueError(f"--trace-pulse-us must be between {TRACE_PULSE_US_MIN} and {TRACE_PULSE_US_MAX}")
    if not (TRACE_PULSE_COUNT_MIN <= pulse_count <= TRACE_PULSE_COUNT_MAX):
        raise ValueError(f"--trace-pulse-count must be between {TRACE_PULSE_COUNT_MIN} and {TRACE_PULSE_COUNT_MAX}")
    if not (TRACE_FREQUENCY_HZ_MIN <= frequency_hz <= TRACE_FREQUENCY_HZ_MAX):
        raise ValueError(f"--trace-frequency-hz must be between {TRACE_FREQUENCY_HZ_MIN} and {TRACE_FREQUENCY_HZ_MAX}")
    period_us = 1_000_000 // frequency_hz
    if pulse_us >= period_us:
        raise ValueError("--trace-pulse-us must be shorter than the pulse period")
    planned_window_ms = (pulse_count * 1000 + frequency_hz - 1) // frequency_hz
    if planned_window_ms > TRACE_MAX_PULSE_WINDOW_MS:
        raise ValueError(f"custom pressure trace pulse window must be <= {TRACE_MAX_PULSE_WINDOW_MS} ms")

    return {
        "channel": channel,
        "channel_code": TRACE_CHANNEL_CODES[channel],
        "pressure_mpsi": pressure_mpsi,
        "pulse_us": pulse_us,
        "pulse_count": pulse_count,
        "frequency_hz": frequency_hz,
    }


def _custom_trace_tlvs(config: dict | None) -> bytes:
    if not config:
        return b""
    tlvs = bytes([TAG_TRACE_CHANNEL, 1, int(config["channel_code"])])
    tlvs += bytes([TAG_TRACE_PRESSURE_MPSI, 2]) + int(config["pressure_mpsi"]).to_bytes(2, "little")
    tlvs += bytes([TAG_TRACE_PULSE_US, 2]) + int(config["pulse_us"]).to_bytes(2, "little")
    tlvs += bytes([TAG_TRACE_PULSE_COUNT, 2]) + int(config["pulse_count"]).to_bytes(2, "little")
    tlvs += bytes([TAG_TRACE_FREQUENCY_HZ, 2]) + int(config["frequency_hz"]).to_bytes(2, "little")
    return tlvs


def decode_ack_result(code: int | None) -> str | None:
    if code is None:
        return None
    names = {
        ACK_RESULT_ACCEPTED: "accepted",
        ACK_RESULT_DUPLICATE: "duplicate",
        ACK_RESULT_GAP: "gap",
        ACK_RESULT_BUSY: "busy",
        ACK_RESULT_WATERMARK_SET: "watermark_set",
        ACK_RESULT_WATERMARK_REJECTED: "watermark_rejected",
    }
    return names.get(int(code), f"unknown_{int(code)}")


def _tlv_u32(tlv: dict[int, bytes], tag: int) -> int | None:
    raw = tlv.get(tag)
    if raw is None or len(raw) != 4:
        return None
    return int.from_bytes(raw, "little")


def _tlv_u8(tlv: dict[int, bytes], tag: int) -> int | None:
    raw = tlv.get(tag)
    if raw is None or len(raw) != 1:
        return None
    return raw[0]

REGULATOR_TELEMETRY_AGE_UNKNOWN = 0xFFFFFFFF
REGULATOR_RESET_CONTEXT_WIRE_SIZE = 30
FAULT_CONTEXT_V1_WIRE_SIZE = 112
FAULT_CONTEXT_WIRE_SIZE = 132
CRASH_FAULT_NAMES = {
    0: "none", 1: "hardfault", 2: "memmanage", 3: "busfault", 4: "usagefault",
    5: "nmi", 6: "stack_overflow", 7: "assert", 8: "error_handler", 9: "wdt",
}
CRASH_TASK_NAMES = {
    0: "none", 1: "boot", 2: "orchestrator", 3: "status", 4: "pressure",
    5: "print_regulator", 6: "refuel_regulator", 7: "home_x", 8: "home_y",
    9: "home_z", 10: "home_print_regulator", 11: "home_refuel_regulator",
    12: "printer", 13: "gripper", 14: "led", 15: "led_fade", 16: "log_stats",
    17: "heartbeat", 18: "watchdog", 19: "idle", 20: "timer",
}
HOME_PHASE_NAMES = {
    0: "idle", 1: "initial_check", 2: "coarse_seek", 3: "release",
    4: "fine_seek", 5: "final_backoff", 6: "succeeded", 7: "canceled", 8: "failed",
}
HOME_CHECKPOINT_NAMES = {
    0: "idle", 1: "phase_entry", 2: "before_event_clear", 3: "before_move",
    4: "waiting_for_move", 5: "after_move", 6: "before_limit_sample",
    7: "after_limit_sample", 8: "finishing",
}
REGULATOR_TELEMETRY_FLAGS = {
    0x0001: ("active", "active"),
    0x0002: ("homing", "homing"),
    0x0004: ("resetting", "resetting"),
    0x0008: ("motion_hold", "motion_hold"),
    0x0010: ("quiet", "quiet"),
    0x0020: ("stepping", "stepping"),
    0x0040: ("inactive_hold", "inactive_hold"),
    0x0080: ("motion_hold_wdg", "motion_hold_wdg"),
    0x0100: ("recovery_hold", "recovery_hold"),
}
REGULATOR_TELEMETRY_EVENTS = {
    0: "none",
    1: "start",
    2: "pause",
    3: "motion_hold_enter",
    4: "motion_hold_exit",
    5: "home_begin",
    6: "home_end_ok",
    7: "home_end_fail",
    8: "reset_begin",
    9: "reset_end_ok",
    10: "reset_end_fail",
    11: "quiet_begin",
    12: "quiet_end",
    13: "inner_limit",
    14: "step_limit",
    15: "safety_home",
}


def _regulator_age(value: int | None) -> int | None:
    if value is None or value == REGULATOR_TELEMETRY_AGE_UNKNOWN:
        return None
    return value


def _decode_regulator_flags(flags: int) -> dict:
    flags = int(flags or 0)
    result = {"raw": flags, "names": []}
    for bit, (key, name) in REGULATOR_TELEMETRY_FLAGS.items():
        enabled = bool(flags & bit)
        result[key] = enabled
        if enabled:
            result["names"].append(name)
    return result


def _decode_regulator_channel(flags, watchdog_enabled, watchdog_age_ms, last_event, last_event_age_ms):
    event = int(last_event or 0)
    decoded = _decode_regulator_flags(flags)
    decoded.update(
        {
            "watchdog_enabled": bool(watchdog_enabled),
            "watchdog_age_ms": _regulator_age(watchdog_age_ms),
            "last_event": event,
            "last_event_name": REGULATOR_TELEMETRY_EVENTS.get(event, f"event_{event}"),
            "last_event_age_ms": _regulator_age(last_event_age_ms),
        }
    )
    return decoded


def decode_regulator_context(raw: bytes | None) -> dict | None:
    if raw is None:
        return None
    if len(raw) != REGULATOR_RESET_CONTEXT_WIRE_SIZE:
        return {"valid": False, "error": "bad_length", "raw_length": len(raw)}
    version, valid = raw[0], raw[1]
    p_flags = int.from_bytes(raw[2:4], "little")
    r_flags = int.from_bytes(raw[4:6], "little")
    p_wdg_enabled, r_wdg_enabled = raw[6], raw[7]
    p_wdg_age_ms = int.from_bytes(raw[8:12], "little")
    r_wdg_age_ms = int.from_bytes(raw[12:16], "little")
    p_last_event, r_last_event = raw[16], raw[17]
    p_last_event_age_ms = int.from_bytes(raw[18:22], "little")
    r_last_event_age_ms = int.from_bytes(raw[22:26], "little")
    snapshot_tick_ms = int.from_bytes(raw[26:30], "little")
    return {
        "version": version,
        "valid": bool(valid),
        "snapshot_tick_ms": snapshot_tick_ms,
        "print": _decode_regulator_channel(
            p_flags, p_wdg_enabled, p_wdg_age_ms, p_last_event, p_last_event_age_ms
        ),
        "refuel": _decode_regulator_channel(
            r_flags, r_wdg_enabled, r_wdg_age_ms, r_last_event, r_last_event_age_ms
        ),
    }


def _plausible_fault_pc(pc: int) -> bool:
    address = int(pc) & ~1
    return (0x08000000 <= address < 0x08060000) or (0x20000000 <= address < 0x20020000)


def _decode_fault_context_v1(raw: bytes) -> dict:
    header = struct.unpack_from("<10BH", raw, 0)
    register_names = (
        "exc_return", "active_sp", "msp", "psp", "task_stack_low", "task_stack_high",
        "r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr", "cfsr", "hfsr",
        "dfsr", "afsr", "shcsr", "mmfar", "bfar", "control", "basepri", "primask",
        "faultmask",
    )
    flags = header[1]
    task_id = header[3]
    result = {
        "version": header[0],
        "flags": flags,
        "core_frame_valid": bool(flags & 0x01),
        "extended_fpu_frame": bool(flags & 0x02),
        "task_stack_matched": bool(flags & 0x04),
        "mmfar_valid": bool(flags & 0x08),
        "bfar_valid": bool(flags & 0x10),
        "handler_mode": bool(flags & 0x20),
        "stack_pointer_valid": bool(flags & 0x40),
        "fault_kind": header[2],
        "fault_kind_name": CRASH_FAULT_NAMES.get(header[2], f"fault_{header[2]}"),
        "task_id": task_id,
        "task_name": CRASH_TASK_NAMES.get(task_id, f"task_{task_id}"),
        "active_command": header[4],
        "home_phases": {
            axis: {"value": value, "name": HOME_PHASE_NAMES.get(value, f"phase_{value}")}
            for axis, value in zip(("x", "y", "z", "p", "r"), header[5:10])
        },
        "home_checkpoints": None,
        "ipsr": header[10],
    }
    result.update(zip(register_names, struct.unpack_from("<25I", raw, 12)))
    result["core_frame_flag_valid"] = result["core_frame_valid"]
    result["pc_executable"] = _plausible_fault_pc(result["pc"])
    result["xpsr_thumb"] = bool(result["xpsr"] & (1 << 24))
    result["core_frame_valid"] = bool(
        result["core_frame_flag_valid"] and result["pc_executable"] and result["xpsr_thumb"]
    )
    return result


def _decode_fault_context_v2(raw: bytes) -> dict:
    version, fault_kind, task_id, active_command = struct.unpack_from("<4B", raw, 0)
    flags = struct.unpack_from("<H", raw, 4)[0]
    phase_values = raw[6:11]
    checkpoint_values = raw[11:16]
    control, basepri, primask, faultmask = raw[16:20]
    register_names = (
        "exc_return", "active_sp", "msp", "psp", "task_stack_low", "task_stack_high",
        "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9",
        "r10", "r11", "r12", "lr", "pc", "xpsr", "cfsr", "hfsr", "mmfar",
        "bfar", "fpccr", "fpcar",
    )
    values = struct.unpack_from("<28I", raw, 20)
    result = {
        "version": version,
        "flags": flags,
        "core_frame_valid": bool(flags & 0x001),
        "extended_fpu_frame": bool(flags & 0x002),
        "task_stack_matched": bool(flags & 0x004),
        "mmfar_valid": bool(flags & 0x008),
        "bfar_valid": bool(flags & 0x010),
        "handler_mode": bool(flags & 0x020),
        "stack_pointer_valid": bool(flags & 0x040),
        "callee_saved_valid": bool(flags & 0x080),
        "fp_status_valid": bool(flags & 0x100),
        "pc_executable": bool(flags & 0x200),
        "xpsr_thumb": bool(flags & 0x400),
        "checkpoints_valid": bool(flags & 0x800),
        "fault_kind": fault_kind,
        "fault_kind_name": CRASH_FAULT_NAMES.get(fault_kind, f"fault_{fault_kind}"),
        "task_id": task_id,
        "task_name": CRASH_TASK_NAMES.get(task_id, f"task_{task_id}"),
        "active_command": active_command,
        "home_phases": {
            axis: {"value": value, "name": HOME_PHASE_NAMES.get(value, f"phase_{value}")}
            for axis, value in zip(("x", "y", "z", "p", "r"), phase_values)
        },
        "home_checkpoints": {
            axis: {"value": value, "name": HOME_CHECKPOINT_NAMES.get(value, f"checkpoint_{value}")}
            for axis, value in zip(("x", "y", "z", "p", "r"), checkpoint_values)
        },
        "control": control,
        "basepri": basepri,
        "primask": primask,
        "faultmask": faultmask,
    }
    result.update(zip(register_names, values))
    result["ipsr"] = result["xpsr"] & 0x1FF
    result["core_frame_flag_valid"] = result["core_frame_valid"]
    result["core_frame_valid"] = bool(
        result["core_frame_flag_valid"]
        and result["pc_executable"]
        and result["xpsr_thumb"]
        and _plausible_fault_pc(result["pc"])
        and bool(result["xpsr"] & (1 << 24))
    )
    return result


def decode_fault_context(raw: bytes | None) -> dict | None:
    if raw is None or not raw:
        return None
    if raw[0] == 1 and len(raw) == FAULT_CONTEXT_V1_WIRE_SIZE:
        return _decode_fault_context_v1(raw)
    if raw[0] == 2 and len(raw) == FAULT_CONTEXT_WIRE_SIZE:
        return _decode_fault_context_v2(raw)
    return None


def decode_reset_report(tlv: dict[int, bytes]) -> dict:
    return {
        "reset_seq32": _tlv_u32(tlv, TAG_RESET_SEQ32),
        "reset_cause": _tlv_u8(tlv, TAG_RESET_CAUSE),
        "reset_flags": _tlv_u32(tlv, TAG_RESET_FLAGS),
        "last_fault": _tlv_u8(tlv, TAG_RESET_LAST_FAULT),
        "last_task": _tlv_u8(tlv, TAG_RESET_LAST_TASK),
        "boot_count": _tlv_u32(tlv, TAG_RESET_BOOT_COUNT),
        "fault_count": _tlv_u32(tlv, TAG_RESET_FAULT_COUNT),
        "watchdog_count": _tlv_u32(tlv, TAG_RESET_WATCHDOG_COUNT),
        "watchdog_sticky_count": _tlv_u32(tlv, TAG_RESET_WATCHDOG_STICKY_CT),
        "watchdog_raw_sr": _tlv_u32(tlv, TAG_RESET_WATCHDOG_RAW_SR),
        "uptime_ms": _tlv_u32(tlv, TAG_RESET_UPTIME_MS),
        "boot_stage": _tlv_u8(tlv, TAG_RESET_BOOT_STAGE),
        "recovery_boot": _tlv_u8(tlv, TAG_RESET_RECOVERY_BOOT),
        "fault_stage": _tlv_u8(tlv, TAG_RESET_FAULT_STAGE),
        "watchdog_late_task": _tlv_u8(tlv, TAG_RESET_WATCHDOG_LATE_TASK),
        "active_command": _tlv_u8(tlv, TAG_RESET_ACTIVE_COMMAND),
        "regulator_context": decode_regulator_context(tlv.get(TAG_RESET_REG_CONTEXT)),
        "fault_context": decode_fault_context(tlv.get(TAG_RESET_FAULT_CONTEXT)),
    }


def supports_selftest_transport(capabilities: int | None) -> bool:
    if capabilities is None:
        return False
    return (int(capabilities) & SELFTEST_TRANSPORT_CAPS) == SELFTEST_TRANSPORT_CAPS


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
        10: "valve_sequence",
        11: "motor_position",
        12: "valve_gap",
        13: "valve_previous_width",
        14: "valve_interval",
        15: "gripper_timing",
        16: "gripper_refresh_count",
    }
    rows = []
    for off in range(0, len(payload), size):
        chunk = payload[off : off + size]
        if len(chunk) != size:
            break
        dt_ms, event_type, _reserved, value0, value1 = struct.unpack(fmt, chunk)
        row = {
            "dt_ms": dt_ms,
            "event_type": event_type,
            "event_name": names.get(event_type, f"unknown_{event_type}"),
            "value0": value0,
            "value1": value1,
        }
        if event_type == 11:
            raw_i32 = value0 | (value1 << 16)
            if raw_i32 >= 0x80000000:
                raw_i32 -= 0x100000000
            row["value_i32"] = raw_i32
        rows.append(row)
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


def _read_completed_frames(serial_port, reader: FrameReader, inbox: deque, size: int) -> int:
    chunk = serial_port.read(size)
    for value in chunk:
        frame = reader.feed(value)
        if frame and len(frame) >= 2:
            inbox.append(frame)
    return len(chunk)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _emit_selftest_event(args, payload: dict) -> None:
    if not bool(getattr(args, "progress_jsonl", False)):
        return
    event = {"schema": "selftest_event_v1", **dict(payload)}
    event.setdefault("timestamp", now_iso())
    print(f"{SELFTEST_EVENT_PREFIX}{json.dumps(event, sort_keys=True, separators=(',', ':'))}", flush=True)


def _operator_prompt_message(stage: str) -> str:
    if stage == "evap_plate_confirm":
        return (
            "The machine is at the 384-well plate start with Z homed/up. "
            "Position the evaporation plate, confirm the area is clear, then continue."
        )
    if stage == "coord_x_limit_press":
        return (
            "With the XY motors disabled and stationary, manually press and hold the X limit switch, "
            "then continue. Keep the switch held until the next prompt."
        )
    if stage == "coord_x_limit_release":
        return "Release the X limit switch, confirm it is fully released, then continue."
    if stage == "coord_y_limit_press":
        return (
            "With the XY motors disabled and stationary, manually press and hold the Y limit switch, "
            "then continue. Keep the switch held until the next prompt."
        )
    if stage == "coord_y_limit_release":
        return "Release the Y limit switch, confirm it is fully released, then continue."
    if stage == "normal_route_envelope_clear":
        return (
            "Confirm both limit switches are released, remove all hands, and verify the complete "
            "XY and Z motion envelope is clear before homing and motion begin."
        )
    if stage == "coordinated_xy_performance_fixture_clear":
        return (
            "Confirm the pressure_closed_loop_v1 fixture is installed and rated for the 1-2 psi test, "
            "both pressure paths are closed-loop and safe, and the complete XY/Z motion envelope is "
            "clear. Remove all hands before the automatic homing and 5-40 kHz motion sequence begins."
        )
    if stage == "coordinated_xy_camera_transition_envelope_clear":
        return (
            "Confirm both limit switches are released and the complete XY/Z motion envelope is clear. "
            "Remove all hands before automatic homing, one 40 kHz camera-ratio round trip, and the "
            "immediate bounded X home begin."
        )
    if stage in {
        "coordinated_xy_40khz_envelope_clear",
        "coordinated_xy_single_irq_envelope_clear",
    }:
        return (
            "Confirm both limit switches are released and the complete XY/Z motion envelope is clear. "
            "Remove all hands before automatic homing, the ten-move 40 kHz Milestone 6 geometry row, "
            "and its bounded post-row X/Y reference homes begin."
        )
    if stage in {
        "coordinated_xy_mres3_20khz_envelope_clear",
        "coordinated_xy_mres3_rearm_envelope_clear",
        "coordinated_xy_mres3_conditional_rearm_envelope_clear",
        "coordinated_xy_production_mres3_envelope_clear",
    }:
        return (
            "Confirm both limit switches are released, the gantry is square, and the complete "
            "XY/Z motion envelope is clear. Remove all hands before the logical-unit MRES=3 "
            "homes, ten-move row (20 kHz native step cycles), and bounded post-row X/Y homes begin."
        )
    return "Confirm the operator-gated self-test step is ready to continue."


def _is_operator_prompt_stage(stage: str) -> bool:
    return stage in {
        "evap_plate_confirm",
        "coord_x_limit_press",
        "coord_x_limit_release",
        "coord_y_limit_press",
        "coord_y_limit_release",
        "normal_route_envelope_clear",
        "coordinated_xy_performance_fixture_clear",
        "coordinated_xy_camera_transition_envelope_clear",
        "coordinated_xy_40khz_envelope_clear",
        "coordinated_xy_single_irq_envelope_clear",
        "coordinated_xy_mres3_20khz_envelope_clear",
        "coordinated_xy_mres3_rearm_envelope_clear",
        "coordinated_xy_mres3_conditional_rearm_envelope_clear",
        "coordinated_xy_production_mres3_envelope_clear",
    }


def _read_operator_prompt_response(args, message: str) -> bool:
    prompt = "" if bool(getattr(args, "progress_jsonl", False)) else f"{message}\nType Enter/continue to continue, or abort to cancel: "
    try:
        response = input(prompt)
    except EOFError:
        return False
    text = str(response or "").strip().lower()
    if text in ("", "c", "continue", "y", "yes"):
        return True
    if text in ("a", "abort", "cancel", "n", "no", "stop"):
        return False
    return False


def _effective_status_only_timeout_ms(args, coordinated_xy_performance_suite: bool) -> int:
    configured = getattr(args, "status_only_timeout_ms", None)
    if configured is None:
        configured = 60000 if coordinated_xy_performance_suite else 5000
    return max(1000, int(configured))


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


def _slug_trace_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "")).strip("._-")
    return slug or "trace"


def _trace_artifact_path(
    base_out: str,
    test_id: int,
    *,
    trace_name: str | None = None,
    canonical_name: str | None = None,
) -> str:
    base = os.path.splitext(base_out)[0]
    if trace_name and trace_name != canonical_name:
        return f"{base}_trace_{test_id}_{_slug_trace_name(trace_name)}.json"
    return f"{base}_trace_{test_id}.json"


def _camera_benchmark_artifact_path(base_out: str) -> str:
    base = os.path.splitext(base_out)[0]
    return f"{base}_camera_benchmark.json"


def _resolve_camera_benchmark_order(mode: str, requested_order: str) -> str:
    mode_norm = str(mode or "flash_only").strip().lower()
    if mode_norm not in ("flash_only", "print_then_flash", "coordinated_flash"):
        mode_norm = "flash_only"
    order_norm = str(requested_order or "auto").strip().lower()
    if order_norm not in ("auto", "pre_selftest", "post_selftest"):
        order_norm = "auto"
    if order_norm == "auto":
        return "post_selftest" if mode_norm in ("print_then_flash", "coordinated_flash") else "pre_selftest"
    return order_norm


def _camera_benchmark_payload_pass(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("status") != "ok":
        return False
    init_diag = payload.get("init_diag") or {}
    if not isinstance(init_diag, dict) or not bool(init_diag.get("config_match", False)):
        return False
    summary = payload.get("summary") or {}
    if not isinstance(summary, dict):
        return False
    requested = summary.get("requested_cycles")
    if requested is None:
        config = payload.get("config") or {}
        requested = config.get("cycles") if isinstance(config, dict) else None
    try:
        requested_i = int(requested)
    except (TypeError, ValueError):
        return False
    if requested_i <= 0:
        return False
    for key in (
        "completed_cycles",
        "ack_seen_cycles",
        "frame_selected_cycles",
        "flash_detected_cycles",
        "success_cycles",
    ):
        try:
            if int(summary.get(key)) != requested_i:
                return False
        except (TypeError, ValueError):
            return False
    if payload.get("mode") == "coordinated_flash":
        coordinated_diag = payload.get("coordinated_diag") or {}
        if not isinstance(coordinated_diag, dict):
            return False
        if not bool(coordinated_diag.get("overlap_window_satisfied", False)):
            return False
    return True


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
    start_seq32: int = 1,
) -> tuple[bool, bool, int]:
    bench_artifact = _camera_benchmark_artifact_path(args.out)
    try:
        from camera_flash_benchmark import BenchmarkConfig, run_camera_flash_benchmark

        mode = str(mode or "flash_only").strip().lower()
        if mode not in ("flash_only", "print_then_flash", "coordinated_flash"):
            mode = "flash_only"
        effective_droplets = (
            max(1, int(getattr(args, "camera_benchmark_num_droplets", 1)))
            if mode in ("print_then_flash", "coordinated_flash")
            else 0
        )

        bench_cfg = BenchmarkConfig(
            cycles=max(1, int(getattr(args, "camera_benchmark_cycles", 100))),
            exposure_us=max(1, int(getattr(args, "camera_benchmark_exposure_us", 16500))),
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
            warmup_cycles=max(0, int(getattr(args, "camera_benchmark_warmup_cycles", 1))),
            min_trigger_period_ms=max(0, int(getattr(args, "camera_benchmark_min_trigger_period_ms", 0))),
            early_abort_consecutive_edge_timeouts=max(
                0, int(getattr(args, "camera_benchmark_early_abort_consecutive_edge_timeouts", 5))
            ),
            coordinated_gripper_refresh_ms=max(
                1000, int(getattr(args, "camera_benchmark_coordinated_gripper_refresh_ms", 5000))
            ),
            coordinated_gripper_pulse_ms=max(
                1, int(getattr(args, "camera_benchmark_coordinated_gripper_pulse_ms", 500))
            ),
        )
        bench_payload = run_camera_flash_benchmark(
            ser,
            build_control_fn,
            run_id=run_id,
            config=bench_cfg,
            start_seq32=start_seq32,
        )
        try:
            next_seq32 = int(bench_payload.get("next_seq32", start_seq32))
        except (TypeError, ValueError, AttributeError):
            next_seq32 = int(start_seq32)
        bench_pass = _camera_benchmark_payload_pass(bench_payload)
        write_json_atomic(bench_artifact, bench_payload)
        host_checks.append(
            {
                "name": "camera_flash_benchmark",
                "pass": bench_pass,
                "details": {
                    "status": bench_payload.get("status", "ok"),
                    "artifact": bench_artifact,
                    "phase": phase,
                    "mode": mode,
                    "requested_order": str(requested_order),
                    "resolved_order": str(phase),
                    "start_seq32": int(start_seq32),
                    "next_seq32": int(next_seq32),
                    "summary": bench_payload.get("summary", {}),
                    "classification": bench_payload.get("classification", {}),
                    "early_abort": bench_payload.get("early_abort", {}),
                    "warmup_summary": bench_payload.get("warmup_summary", {}),
                    "preflight": bench_payload.get("preflight", {}),
                    "init_diag": bench_payload.get("init_diag", {}),
                    "coordinated_diag": bench_payload.get("coordinated_diag", {}),
                    "status_snapshot_delta": bench_payload.get("status_snapshot_delta", {}),
                },
                "timestamp": now_iso(),
            }
        )
        print(f"Wrote camera benchmark artifact: {bench_artifact}")
        return False, not bench_pass, next_seq32
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
        return False, False, int(start_seq32)
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
        return True, False, int(start_seq32)


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
    try:
        custom_trace_config = _validated_custom_trace_config(args)
    except ValueError as exc:
        print(f"Invalid custom pressure trace request: {exc}")
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
    camera_benchmark_failed = False
    next_seq32 = 1
    startup_reset_report = None
    reset_report_details = None
    with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
        reader = FrameReader()
        frame_inbox = deque()

        def write_report_and_return(rc: int) -> int:
            report = {
                "run_id": run_id,
                "profile": profile,
                "started_at": started_at,
                "finished_at": now_iso(),
                "aborted": aborted,
                "summary": summary,
                "results": results,
                "host_checks": host_checks,
                "startup_reset_report": startup_reset_report,
                "reset_report": reset_report_details,
            }
            write_json_atomic(args.out, report)
            print(f"Wrote self-test report: {args.out}")
            return rc

        # HELLO handshake. Retry until the target is actually up so startup
        # latency after DFU does not cause us to lose both HELLO and START.
        hello_seq8 = 1

        def capture_startup_reset_report(frame: bytes) -> bool:
            nonlocal startup_reset_report
            if frame[0] != CMD_RESET_REPORT or frame[1] != hello_seq8:
                return False
            details = decode_reset_report(parse_tlvs(frame[2:]))
            if details.get("reset_seq32") != run_id:
                return False
            if startup_reset_report is None:
                startup_reset_report = details
                _emit_selftest_event(
                    args,
                    {
                        "event": "selftest_startup_reset_report",
                        "reset_report": details,
                    },
                )
            return True

        hello_timeout_ms = int(args.hello_timeout_ms)
        hello_retry_ms = int(args.hello_retry_ms)
        hello_window_s = hello_timeout_ms / 1000.0
        hello_deadline = time.monotonic() + hello_window_s
        next_hello_send = 0.0
        got_hello_ack = False
        hello_retries_sent = 0
        observed_uart_bytes = 0
        hello_ack_capabilities = None
        hello_deferred_frames = deque()
        while time.monotonic() < hello_deadline:
            now = time.monotonic()
            if now >= next_hello_send:
                ser.write(build_control(CMD_HELLO, hello_seq8, run_id))
                hello_retries_sent += 1
                next_hello_send = now + (hello_retry_ms / 1000.0)
            observed_uart_bytes += _read_completed_frames(
                ser, reader, frame_inbox, 128
            )
            while frame_inbox:
                frame = frame_inbox.popleft()
                if frame[0] == CMD_HELLO_ACK and frame[1] == hello_seq8:
                    hello_tlv = parse_tlvs(frame[2:])
                    hello_ack_capabilities = _tlv_u32(hello_tlv, TAG_CAPABILITIES)
                    got_hello_ack = True
                elif not capture_startup_reset_report(frame):
                    hello_deferred_frames.append(frame)
            if got_hello_ack:
                break
        frame_inbox.extend(hello_deferred_frames)
        use_selftest_transport = supports_selftest_transport(hello_ack_capabilities)
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
                    "capabilities": hello_ack_capabilities,
                    "supports_selftest_transport": use_selftest_transport,
                },
                "timestamp": now_iso(),
            }
        )
        if not got_hello_ack:
            print("No HELLO_ACK before self-test start.")
            if args.fast_fail_on_missing_hello:
                aborted = True
                return write_report_and_return(3)

        bench_mode = str(getattr(args, "camera_benchmark_mode", "flash_only") or "flash_only").strip().lower()
        if bench_mode not in ("flash_only", "print_then_flash", "coordinated_flash"):
            bench_mode = "flash_only"
        requested_bench_order = str(getattr(args, "camera_benchmark_order", "auto") or "auto").strip().lower()
        bench_order = _resolve_camera_benchmark_order(bench_mode, requested_bench_order)
        run_benchmark = bool(getattr(args, "camera_benchmark", False))
        if run_benchmark and bench_order == "pre_selftest":
            bench_runtime_error, bench_failed, next_seq32 = _run_camera_benchmark_phase(
                args,
                ser=ser,
                run_id=run_id,
                host_checks=host_checks,
                build_control_fn=build_control,
                phase="pre_selftest",
                mode=bench_mode,
                requested_order=requested_bench_order,
                start_seq32=next_seq32,
            )
            camera_benchmark_runtime_error = bench_runtime_error or camera_benchmark_runtime_error
            camera_benchmark_failed = bench_failed or camera_benchmark_failed

        profile_val = profile_map[profile]
        # Mirror profile into TAG_P1 so current firmware decode can branch without
        # changing CommCodec TLV parsing rules. TAG_PROFILE remains authoritative.
        tlvs = bytes([TAG_P1, 1, profile_val])
        pressure_trace_requested = bool(getattr(args, "pressure_trace", False) or custom_trace_config is not None)
        tlvs += bytes([TAG_P2, 1, 1 if pressure_trace_requested else 0])
        pressure_trace_test = getattr(args, "pressure_trace_test", None)
        pressure_sweep_suite = getattr(args, "pressure_sweep_suite", None)
        gripper_seal_suite = bool(getattr(args, "gripper_seal_suite", False))
        gripper_seal_stress_suite = bool(getattr(args, "gripper_seal_stress_suite", False))
        xy_motion_suite = bool(getattr(args, "xy_motion_suite", False))
        motion_timing_suite = bool(getattr(args, "motion_timing_suite", False))
        motion_envelope_suite = bool(getattr(args, "motion_envelope_suite", False))
        profile_lut_benchmark = bool(getattr(args, "profile_lut_benchmark", False))
        coordinated_xy_executor_suite = bool(getattr(args, "coordinated_xy_executor_suite", False))
        normal_xy_route_suite = bool(getattr(args, "normal_xy_route_suite", False))
        selftest_scheduler_no_yield_suite = bool(
            getattr(args, "selftest_scheduler_no_yield_suite", False)
        )
        selftest_scheduler_cooperative_suite = bool(
            getattr(args, "selftest_scheduler_cooperative_suite", False)
        )
        coordinated_xy_performance_suite = bool(
            getattr(args, "coordinated_xy_performance_suite", False)
        )
        coordinated_xy_40khz_suite = bool(
            getattr(args, "coordinated_xy_40khz_suite", False)
        )
        coordinated_xy_status_sync_suite = bool(
            getattr(args, "coordinated_xy_status_sync_suite", False)
        )
        coordinated_xy_single_irq_suite = bool(
            getattr(args, "coordinated_xy_single_irq_suite", False)
        )
        coordinated_xy_mres3_20khz_suite = bool(
            getattr(args, "coordinated_xy_mres3_20khz_suite", False)
        )
        coordinated_xy_mres3_rearm_suite = bool(
            getattr(args, "coordinated_xy_mres3_rearm_suite", False)
        )
        coordinated_xy_mres3_conditional_rearm_suite = bool(
            getattr(args, "coordinated_xy_mres3_conditional_rearm_suite", False)
        )
        coordinated_xy_production_mres3_suite = bool(
            getattr(args, "coordinated_xy_production_mres3_suite", False)
        )
        coordinated_xy_x_direction_suite = bool(
            getattr(args, "coordinated_xy_x_direction_suite", False)
        )
        coordinated_xy_camera_transition_suite = bool(
            getattr(args, "coordinated_xy_camera_transition_suite", False)
        )
        coordinated_xy_performance_diagnostic = bool(
            coordinated_xy_performance_suite
            or coordinated_xy_40khz_suite
            or coordinated_xy_status_sync_suite
            or coordinated_xy_single_irq_suite
            or coordinated_xy_mres3_20khz_suite
            or coordinated_xy_mres3_rearm_suite
            or coordinated_xy_mres3_conditional_rearm_suite
            or coordinated_xy_production_mres3_suite
            or coordinated_xy_x_direction_suite
            or coordinated_xy_camera_transition_suite
        )
        status_cadence_diagnostic = bool(
            coordinated_xy_performance_diagnostic
            or selftest_scheduler_cooperative_suite
        )
        pressure_regulator_suite = bool(getattr(args, "pressure_regulator_suite", False))
        refuel_vacuum_suite = bool(getattr(args, "refuel_vacuum_suite", False))
        valve_characterization_suite = bool(getattr(args, "valve_characterization_suite", False))
        valve_gap_sweep_suite = bool(getattr(args, "valve_gap_sweep_suite", False))
        selector = 1039 if selftest_scheduler_no_yield_suite else 1038 if selftest_scheduler_cooperative_suite else 2599 if gripper_seal_stress_suite else 2498 if valve_gap_sweep_suite else 2499 if valve_characterization_suite else 2298 if refuel_vacuum_suite else 2299 if pressure_regulator_suite else 2097 if coordinated_xy_production_mres3_suite else 2086 if coordinated_xy_mres3_conditional_rearm_suite else 2084 if coordinated_xy_mres3_rearm_suite else 2085 if coordinated_xy_mres3_20khz_suite else 2075 if coordinated_xy_single_irq_suite else 2076 if coordinated_xy_status_sync_suite else 2077 if coordinated_xy_40khz_suite else 2078 if coordinated_xy_camera_transition_suite else 2079 if coordinated_xy_x_direction_suite else 2069 if coordinated_xy_performance_suite else 2059 if normal_xy_route_suite else 2049 if coordinated_xy_executor_suite else 2039 if profile_lut_benchmark else 2029 if motion_timing_suite else 2019 if motion_envelope_suite else 2009 if xy_motion_suite else 2500 if gripper_seal_suite else (
            pressure_sweep_suite if pressure_sweep_suite is not None else (
                CUSTOM_PRESSURE_TRACE_TEST_ID if custom_trace_config is not None else pressure_trace_test
            )
        )
        if selector is not None:
            tlvs += bytes([TAG_P3, 2]) + int(selector).to_bytes(2, "little")
        tlvs += _custom_trace_tlvs(custom_trace_config)
        tlvs += bytes([TAG_PROFILE, 1, profile_val])
        tlvs += bytes([TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
        tlvs += bytes([TAG_TIMEOUT_MS, 4]) + effective_timeout_ms.to_bytes(4, "little")
        selftest_seq32 = next_seq32 if use_selftest_transport else run_id
        ser.write(build_control(CMD_SELFTEST_START, 2, selftest_seq32, tlvs))

        if use_selftest_transport:
            start_ack_timeout_ms = 2000
            ack_deadline = time.monotonic() + (start_ack_timeout_ms / 1000.0)
            start_ack_pass = False
            start_ack_details = {
                "transport_mode": "queue_ack",
                "seq8": 2,
                "seq32": selftest_seq32,
                "run_id": run_id,
                "timeout_ms": start_ack_timeout_ms,
            }
            start_ack_deferred_frames = deque()
            while time.monotonic() < ack_deadline and not start_ack_pass:
                if not frame_inbox:
                    _read_completed_frames(ser, reader, frame_inbox, 128)
                while frame_inbox and not start_ack_pass:
                    frame = frame_inbox.popleft()
                    if capture_startup_reset_report(frame):
                        continue
                    cmd = frame[0]
                    seq8 = frame[1]
                    tlv = parse_tlvs(frame[2:])
                    if cmd != CMD_QUEUE_ACK or seq8 != 2:
                        start_ack_details["observed_cmd"] = cmd
                        start_ack_details["observed_seq8"] = seq8
                        start_ack_deferred_frames.append(frame)
                        continue
                    ack_seq32 = _tlv_u32(tlv, TAG_SEQ32)
                    ack_result_code = _tlv_u8(tlv, TAG_ACK_RESULT)
                    ack_result = decode_ack_result(ack_result_code)
                    expected_seq32 = _tlv_u32(tlv, TAG_EXPECTED_SEQ32)
                    start_ack_details["observed_cmd"] = cmd
                    start_ack_details["observed_seq8"] = seq8
                    start_ack_details["observed_seq32"] = ack_seq32
                    start_ack_details["ack_result"] = ack_result
                    start_ack_details["expected_seq32"] = expected_seq32
                    if ack_seq32 != selftest_seq32:
                        continue
                    if ack_result_code is None:
                        start_ack_details["reason"] = "malformed_ack"
                        break
                    if ack_result_code in (ACK_RESULT_ACCEPTED, ACK_RESULT_DUPLICATE):
                        start_ack_pass = True
                        start_ack_details["reason"] = "ok"
                        break
                    start_ack_details["reason"] = ack_result or "rejected"
                    break
                if start_ack_details.get("reason") in ("malformed_ack", "gap", "busy", "watermark_set", "watermark_rejected") or (
                    start_ack_details.get("ack_result") not in (None, "accepted", "duplicate")
                    and start_ack_details.get("observed_seq32") == selftest_seq32
                ):
                    break
            frame_inbox.extendleft(reversed(start_ack_deferred_frames))
            if not start_ack_pass and "reason" not in start_ack_details:
                start_ack_details["reason"] = "timeout"
            host_checks.append(
                {
                    "name": "selftest_start_ack",
                    "pass": start_ack_pass,
                    "details": start_ack_details,
                    "timestamp": now_iso(),
                }
            )
            if not start_ack_pass:
                aborted = True
                print(
                    "Failed to receive an accepting CMD_QUEUE_ACK for CMD_SELFTEST_START "
                    f"({start_ack_details.get('reason')})."
                )
                return write_report_and_return(3)
        else:
            host_checks.append(
                {
                    "name": "selftest_start_ack",
                    "pass": True,
                    "details": {
                        "transport_mode": "legacy",
                        "seq8": 2,
                        "seq32": selftest_seq32,
                        "run_id": run_id,
                        "skipped": "capabilities_missing",
                    },
                    "timestamp": now_iso(),
                }
            )

        hard_deadline = time.monotonic() + (effective_timeout_ms / 1000.0)
        progress_timeout_ms = max(1000, int(getattr(args, "progress_timeout_ms", 15000)))
        activity_timeout_ms = max(progress_timeout_ms, int(getattr(args, "activity_timeout_ms", 60000)))
        idle_deadline = time.monotonic() + (progress_timeout_ms / 1000.0)
        activity_deadline = time.monotonic() + (activity_timeout_ms / 1000.0)
        done_seen = False
        timeout_reason = "hard_timeout"
        progress_count = 0
        last_progress = {}
        operator_prompted_stages: set[str] = set()
        operator_control_seq8 = 4
        recent_frames = deque(maxlen=64)
        frame_counts: dict[int, int] = {}
        total_rx_bytes = 0
        last_valid_frame_monotonic = time.monotonic()
        last_rx_byte_monotonic = time.monotonic()
        last_selftest_frame_monotonic = time.monotonic()
        status_only_timeout_ms = _effective_status_only_timeout_ms(
            args, status_cadence_diagnostic
        )
        status_frames_since_selftest = 0
        last_status_frame_monotonic = None
        status_gap_max_ms = 0
        status_gap_samples = 0
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
            if not frame_inbox:
                bytes_read = _read_completed_frames(ser, reader, frame_inbox, 256)
                if bytes_read == 0:
                    continue
                total_rx_bytes += bytes_read
            last_rx_byte_monotonic = now
            idle_deadline = now + (progress_timeout_ms / 1000.0)
            activity_deadline = now + (activity_timeout_ms / 1000.0)
            while frame_inbox:
                frame = frame_inbox.popleft()
                last_valid_frame_monotonic = now
                cmd = frame[0]
                body = frame[2:]
                tlv = parse_tlvs(body)
                frame_counts[cmd] = frame_counts.get(cmd, 0) + 1
                frame_snapshot = {"ts": now_iso(), "cmd": cmd}
                idle_deadline = now + (progress_timeout_ms / 1000.0)
                if cmd == 0x02:
                    status_frames_since_selftest += 1
                    if last_status_frame_monotonic is not None:
                        status_gap_ms = int(max(0.0, (now - last_status_frame_monotonic) * 1000.0))
                        status_gap_max_ms = max(status_gap_max_ms, status_gap_ms)
                        status_gap_samples += 1
                    last_status_frame_monotonic = now
                    if (
                        selftest_frames_seen > 0
                        and (now - last_selftest_frame_monotonic) >= (status_only_timeout_ms / 1000.0)
                        and status_frames_since_selftest >= 50
                    ):
                        timeout_reason = "status_only_after_selftest"
                        done_seen = False
                        break

                if cmd == CMD_QUEUE_ACK:
                    frame_snapshot["ack_result"] = decode_ack_result(_tlv_u8(tlv, TAG_ACK_RESULT))
                    frame_snapshot["ack_seq32"] = _tlv_u32(tlv, TAG_SEQ32)
                    frame_snapshot["expected_seq32"] = _tlv_u32(tlv, TAG_EXPECTED_SEQ32)
                    recent_frames.append(frame_snapshot)
                    continue

                if cmd == CMD_RESET_REPORT:
                    if capture_startup_reset_report(frame):
                        frame_snapshot.update(startup_reset_report or {})
                        frame_snapshot["startup"] = True
                        recent_frames.append(frame_snapshot)
                        continue
                    reset_report_details = decode_reset_report(tlv)
                    frame_snapshot.update(reset_report_details)
                    recent_frames.append(frame_snapshot)
                    _emit_selftest_event(
                        args,
                        {
                            "event": "selftest_reset_report",
                            "reset_report": reset_report_details,
                        },
                    )
                    timeout_reason = "mcu_reset_report_seen"
                    done_seen = False
                    break

                if cmd == CMD_SELFTEST_RESULT:
                    # Status is enabled only within a measured motion window for
                    # motion timing diagnostics. Do not count the intentional
                    # pause between result rows as a status-frame gap.
                    last_status_frame_monotonic = None
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
                        stage = str(last_progress.get("stage", ""))
                        frame_snapshot["progress"] = True
                        frame_snapshot["stage"] = stage
                        recent_frames.append(frame_snapshot)
                        _emit_selftest_event(
                            args,
                            {
                                "event": "selftest_progress",
                                "test_id": test_id,
                                "name": name,
                                "pass": passed,
                                "stage": str(last_progress.get("stage", "")),
                                "metrics": dict(last_progress),
                            },
                        )
                        if _is_operator_prompt_stage(stage) and stage not in operator_prompted_stages:
                            operator_prompted_stages.add(stage)
                            prompt_message = _operator_prompt_message(stage)
                            _emit_selftest_event(
                                args,
                                {
                                    "event": "selftest_operator_prompt",
                                    "stage": stage,
                                    "message": prompt_message,
                                },
                            )
                            prompt_started = time.monotonic()
                            accepted = _read_operator_prompt_response(args, prompt_message)
                            prompt_finished = time.monotonic()
                            paused_s = max(0.0, prompt_finished - prompt_started)
                            hard_deadline += paused_s
                            idle_deadline = prompt_finished + (progress_timeout_ms / 1000.0)
                            activity_deadline = prompt_finished + (activity_timeout_ms / 1000.0)
                            operator_cmd = CMD_RESUME if accepted else CMD_SELFTEST_ABORT
                            ser.write(build_control(operator_cmd, operator_control_seq8 & 0xFF, selftest_seq32))
                            operator_control_seq8 = (operator_control_seq8 + 1) & 0xFF
                            _emit_selftest_event(
                                args,
                                {
                                    "event": "selftest_operator_prompt_response",
                                    "stage": stage,
                                    "accepted": bool(accepted),
                                },
                            )
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
                        key = (test_id, name, trace_kind, trace_format)
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
                    metrics = parse_metrics(metrics_raw)
                    timestamp = now_iso()
                    result = {
                        "test_id": test_id,
                        "name": name,
                        "pass": passed,
                        "metrics": metrics,
                        "timestamp": timestamp,
                    }
                    results.append(result)
                    _emit_selftest_event(
                        args,
                        {
                            "event": "selftest_result",
                            "timestamp": timestamp,
                            "test_id": test_id,
                            "name": name,
                            "pass": passed,
                            "metrics": metrics,
                        },
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
                    _emit_selftest_event(
                        args,
                        {
                            "event": "selftest_done",
                            "run_id": done_run,
                            "summary": dict(summary),
                            "aborted": aborted,
                        },
                    )
                    done_seen = True
                    break
            if done_seen:
                break
            if timeout_reason in ("status_only_after_selftest", "mcu_reset_report_seen"):
                break

        if not done_seen:
            _emit_selftest_event(
                args,
                {
                    "event": "selftest_timeout",
                    "reason": timeout_reason,
                    "selftest_frames_seen": selftest_frames_seen,
                    "status_frames_since_selftest": status_frames_since_selftest,
                },
            )
            print(f"Timed out waiting for CMD_SELFTEST_DONE ({timeout_reason}).")
            timeout_abort_sent = False
            timeout_abort_error = None
            if timeout_reason != "mcu_reset_report_seen":
                try:
                    # A host watchdog timeout must actively stop a diagnostic;
                    # closing the serial port alone leaves the MCU test running.
                    ser.write(build_control(CMD_SELFTEST_ABORT, 0x7D, run_id))
                    timeout_abort_sent = True
                    print("Sent CMD_SELFTEST_ABORT after host timeout.")
                except Exception as exc:
                    timeout_abort_error = str(exc)
                    print(f"Failed to send CMD_SELFTEST_ABORT after host timeout: {exc}")
            host_checks.append(
                {
                    "name": "selftest_timeout_abort",
                    "pass": timeout_abort_sent or timeout_reason == "mcu_reset_report_seen",
                    "details": {
                        "reason": timeout_reason,
                        "sent": timeout_abort_sent,
                        "error": timeout_abort_error,
                    },
                    "timestamp": now_iso(),
                }
            )
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
            bench_runtime_error, bench_failed, _post_next_seq32 = _run_camera_benchmark_phase(
                args,
                ser=ser,
                run_id=run_id,
                host_checks=host_checks,
                build_control_fn=build_control,
                phase="post_selftest",
                mode=bench_mode,
                requested_order=requested_bench_order,
                start_seq32=1,
            )
            camera_benchmark_runtime_error = bench_runtime_error or camera_benchmark_runtime_error
            camera_benchmark_failed = bench_failed or camera_benchmark_failed

        skip_goodbye = bool(getattr(args, "skip_goodbye", False) or gripper_seal_suite or gripper_seal_stress_suite)
        if done_seen and not skip_goodbye:
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
        elif done_seen:
            host_checks.append(
                {
                    "name": "goodbye_skipped",
                    "pass": True,
                    "details": {"reason": "operator_gated_gripper_teardown" if (gripper_seal_suite or gripper_seal_stress_suite) else "requested"},
                    "timestamp": now_iso(),
                }
            )

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
                    "status_gap_max_ms": status_gap_max_ms,
                    "status_gap_samples": status_gap_samples,
                    "selftest_frames_seen": selftest_frames_seen,
                    "startup_reset_report": startup_reset_report,
                    "reset_report": reset_report_details,
                    "last_valid_frame_age_ms": int(max(0.0, (time.monotonic() - last_valid_frame_monotonic) * 1000.0)),
                    "last_rx_byte_age_ms": int(max(0.0, (time.monotonic() - last_rx_byte_monotonic) * 1000.0)),
                    "last_selftest_frame_age_ms": int(max(0.0, (time.monotonic() - last_selftest_frame_monotonic) * 1000.0)),
                    "timeout_reason": None if done_seen else timeout_reason,
                },
                "timestamp": now_iso(),
            }
        )
        if status_cadence_diagnostic:
            host_checks.append(
                {
                    "name": (
                        "selftest_scheduler_status_cadence"
                        if selftest_scheduler_cooperative_suite
                        else "coordinated_xy_status_cadence"
                    ),
                    "pass": bool(
                        done_seen
                        and status_gap_samples > 0
                        and status_gap_max_ms < 500
                    ),
                    "details": {
                        "status_gap_max_ms": status_gap_max_ms,
                        "status_gap_samples": status_gap_samples,
                        "limit_ms_exclusive": 500,
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
            "startup_reset_report": startup_reset_report,
            "reset_report": reset_report_details,
        }
        write_json_atomic(args.out, report)
        if trace_chunks:
            result_name_by_id = {int(r["test_id"]): str(r.get("name") or "") for r in results}
            for (test_id, _trace_name, trace_kind, trace_format), info in trace_chunks.items():
                parts = info["parts"]
                ordered = b"".join(parts[i] for i in sorted(parts))
                existing_path = _trace_artifact_path(
                    args.out,
                    test_id,
                    trace_name=info["name"],
                    canonical_name=result_name_by_id.get(test_id),
                )
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
        elif camera_benchmark_failed and rc == 0:
            rc = 2
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
    p.add_argument(
        "--status-only-timeout-ms",
        type=int,
        default=None,
        help=(
            "Abort after this many milliseconds of status-only traffic "
            "(default: 60000 for the coordinated XY performance suite, 5000 otherwise)."
        ),
    )
    p.add_argument("--progress-jsonl", action="store_true", help="Emit structured SELFTEST_EVENT JSONL progress lines.")
    p.add_argument("--hello-timeout-ms", type=int, default=8000)
    p.add_argument("--hello-retry-ms", type=int, default=250)
    p.add_argument("--fast-fail-on-missing-hello", action="store_true")
    p.add_argument("--camera-benchmark", action="store_true")
    p.add_argument("--camera-benchmark-cycles", type=int, default=100)
    p.add_argument("--camera-benchmark-exposure-us", type=int, default=16500)
    p.add_argument("--camera-benchmark-flash-delay-us", type=int, default=5000)
    p.add_argument("--camera-benchmark-flash-width-us", type=int, default=1000)
    p.add_argument("--camera-benchmark-num-droplets", type=int, default=1)
    p.add_argument("--camera-benchmark-warmup-cycles", type=int, default=1)
    p.add_argument("--camera-benchmark-min-trigger-period-ms", type=int, default=0)
    p.add_argument("--camera-benchmark-early-abort-consecutive-edge-timeouts", type=int, default=5)
    p.add_argument("--camera-benchmark-coordinated-gripper-refresh-ms", type=int, default=5000)
    p.add_argument("--camera-benchmark-coordinated-gripper-pulse-ms", type=int, default=500)
    p.add_argument("--camera-benchmark-order", choices=("auto", "pre_selftest", "post_selftest"), default="auto")
    p.add_argument("--camera-benchmark-mode", choices=("flash_only", "print_then_flash", "coordinated_flash"), default="flash_only")
    p.add_argument("--camera-benchmark-preflight-pressure-timeout-ms", type=int, default=1000)
    p.add_argument("--camera-benchmark-attempt-timeout-ms", type=int, default=250)
    p.add_argument("--camera-benchmark-max-new-frames", type=int, default=6)
    p.add_argument("--pressure-trace", action="store_true")
    selector_group = p.add_mutually_exclusive_group()
    selector_group.add_argument("--pressure-trace-test", type=int, choices=(2101, 2102, 2103, 2104))
    selector_group.add_argument("--pressure-trace-custom", action="store_true")
    selector_group.add_argument("--pressure-sweep-suite", type=int, choices=(2301, 2302, 2303, 2304))
    selector_group.add_argument("--pressure-regulator-suite", action="store_true")
    selector_group.add_argument("--refuel-vacuum-suite", action="store_true")
    selector_group.add_argument("--xy-motion-suite", action="store_true")
    selector_group.add_argument("--motion-timing-suite", action="store_true")
    selector_group.add_argument("--motion-envelope-suite", action="store_true")
    selector_group.add_argument("--profile-lut-benchmark", action="store_true")
    selector_group.add_argument("--coordinated-xy-executor-suite", action="store_true")
    selector_group.add_argument("--normal-xy-route-suite", action="store_true")
    selector_group.add_argument("--selftest-scheduler-no-yield-suite", action="store_true")
    selector_group.add_argument("--selftest-scheduler-cooperative-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-performance-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-40khz-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-status-sync-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-single-irq-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-mres3-20khz-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-mres3-rearm-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-mres3-conditional-rearm-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-production-mres3-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-x-direction-suite", action="store_true")
    selector_group.add_argument("--coordinated-xy-camera-transition-suite", action="store_true")
    selector_group.add_argument("--gripper-seal-suite", action="store_true")
    selector_group.add_argument("--gripper-seal-stress-suite", action="store_true")
    selector_group.add_argument("--valve-characterization-suite", action="store_true")
    selector_group.add_argument("--valve-gap-sweep-suite", action="store_true")
    p.add_argument("--trace-channel", choices=("print", "refuel"))
    p.add_argument("--trace-pressure-psi", type=float)
    p.add_argument("--trace-pulse-us", type=int)
    p.add_argument("--trace-pulse-count", type=int)
    p.add_argument("--trace-frequency-hz", type=int)
    p.add_argument("--skip-goodbye", action="store_true")
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
