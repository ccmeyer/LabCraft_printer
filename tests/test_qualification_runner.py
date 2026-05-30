import json
from pathlib import Path
from types import SimpleNamespace

from tools.qualification import cli
from tools.qualification import runner as qualification_runner
from tools.qualification.runner import DEFAULT_MANIFEST_REF, default_gripper_control, run_qualification


def _raw_selftest():
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [{"test_id": 1001, "name": "comm_crc_known_vector", "pass": True, "metrics": {"crc": 1}}],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_gripper_selftest():
    return {
        "run_id": 5678,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:05:00Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": [
            {
                "test_id": 2501,
                "name": "gripper_seal_closed_decay_factory",
                "pass": True,
                "metrics": {
                    "target_psi_milli": 1000,
                    "target_raw": 2512,
                    "valve_drive": "diagnostic_one_pulse",
                    "pulse_ms": 2000,
                    "tick_us": 100,
                    "bursts": 1,
                    "head_valve_mode": "both",
                    "reg_vent": 0,
                    "reg_pause": 1,
                    "grip": 1,
                    "refresh": 0,
                    "p_drop": 20,
                    "r_drop": 25,
                    "drop_raw": 25,
                    "timeout": 0,
                },
            },
            {
                "test_id": 2502,
                "name": "gripper_seal_hold_duration_factory",
                "pass": True,
                "metrics": {"target_raw": 2512, "valve_drive": "diagnostic_one_pulse", "pulse_ms": 2000, "tick_us": 100, "bursts": 6, "head_valve_mode": "both", "reg_vent": 0, "reg_pause": 1, "seal_ms": 60000, "drop_raw": 30, "timeout": 0},
            },
            {
                "test_id": 2503,
                "name": "gripper_seal_repeatability_factory",
                "pass": True,
                "metrics": {"valve_drive": "diagnostic_one_pulse", "pulse_ms": 2000, "tick_us": 100, "bursts": 3, "reg_pause": 1, "repeat_span_raw": 12, "seal_ms_min": 5000, "timeout": 0},
            },
        ],
        "host_checks": [
            {"name": "hello_ack", "pass": True, "details": {"seq8": 1}},
            {"name": "goodbye_skipped", "pass": True, "details": {"reason": "operator_gated_gripper_teardown"}},
        ],
    }


def _raw_gripper_stress_selftest():
    return {
        "run_id": 5680,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:15:00Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": [
            {
                "test_id": 2510,
                "name": "gripper_static_pressure_matrix_factory",
                "pass": True,
                "metrics": {"pulse_ms": 2000, "pulses": 30, "cond": 3, "reps": 5, "ready": 0, "timeout": 0, "focus": 1, "trace": 1, "sc": 96, "stride": 5, "sample_ms": 25},
            },
            {
                "test_id": 2511,
                "name": "gripper_refresh_hold_3psi_factory",
                "pass": True,
                "metrics": {"psi": 3000, "refresh_ms": 30000, "pulse_int": 10000, "ready": 0, "timeout": 0, "focus": 1, "trace": 1, "sc": 48, "stride": 5, "sample_ms": 25},
            },
            {
                "test_id": 2512,
                "name": "gripper_motion_raster_3psi_factory",
                "pass": True,
                "metrics": {"psi": 3000, "z_home_to": 0, "xy_home_to": 0, "move_to": 0, "guard": 0, "bound": 0, "park_x": 500, "park_y": 500, "park_to": 0, "ready": 0, "timeout": 0, "focus": 1, "trace": 1, "sc": 64, "stride": 5, "sample_ms": 25},
            },
            {
                "test_id": 2513,
                "name": "gripper_post_motion_seal_compare_factory",
                "pass": True,
                "metrics": {"psi": 3000, "ready": 0, "timeout": 0, "focus": 1, "trace": 1, "sc": 24, "stride": 5, "sample_ms": 25},
            },
        ],
        "host_checks": [
            {"name": "hello_ack", "pass": True, "details": {"seq8": 1}},
            {"name": "goodbye_skipped", "pass": True, "details": {"reason": "operator_gated_gripper_teardown"}},
        ],
    }


def _raw_xy_motion_selftest():
    return {
        "run_id": 9012,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:03:00Z",
        "aborted": False,
        "summary": {"total": 2, "passed": 2, "failed": 0},
        "results": [
            {
                "test_id": 2010,
                "name": "motion_xy_long_travel_factory",
                "pass": True,
                "metrics": {
                    "rep": 3,
                    "pts": 5,
                    "xmax": 44000,
                    "ymax": 34000,
                    "dx": 43900,
                    "dy": 33500,
                    "x_span": 2,
                    "y_span": 3,
                    "x_drift": 2,
                    "y_drift": 3,
                    "x_ret": 0,
                    "y_ret": 0,
                    "ret_err": 0,
                    "move_to": 0,
                    "home_to": 0,
                    "guard": 0,
                    "bound": 0,
                },
            },
            {
                "test_id": 2011,
                "name": "motion_xy_raster_repeatability_factory",
                "pass": True,
                "metrics": {
                    "rep": 2,
                    "rows": 8,
                    "cols": 12,
                    "step": 400,
                    "moves": 194,
                    "xmax": 7400,
                    "ymax": 3800,
                    "dx": 4400,
                    "dy": 2800,
                    "x_span": 1,
                    "y_span": 2,
                    "x_drift": 1,
                    "y_drift": 2,
                    "x_ret": 0,
                    "y_ret": 0,
                    "ret_err": 0,
                    "move_to": 0,
                    "home_to": 0,
                    "guard": 0,
                    "bound": 0,
                },
            },
        ],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_motion_envelope_selftest():
    metric_common = {
        "rep": 3,
        "ref": 2,
        "pts": 5,
        "xmax": 44000,
        "ymax": 34000,
        "dx": 43900,
        "dy": 33500,
        "x_span": 2,
        "y_span": 3,
        "x_drift": 2,
        "y_drift": 3,
        "x_ret": 0,
        "y_ret": 0,
        "ret_err": 0,
        "move_to": 0,
        "home_to": 0,
        "guard": 0,
        "bound": 0,
    }
    return {
        "run_id": 3456,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:07:00Z",
        "aborted": False,
        "summary": {"total": 5, "passed": 5, "failed": 0},
        "results": [
            {"test_id": 2012, "name": "motion_xy_reverse_travel_factory", "pass": True, "metrics": metric_common},
            {"test_id": 2013, "name": "motion_xy_diagonal_factory", "pass": True, "metrics": metric_common},
            {
                "test_id": 2014,
                "name": "motion_384_plate_raster_factory",
                "pass": True,
                "metrics": {
                    **metric_common,
                    "rep": 1,
                    "rows": 16,
                    "cols": 24,
                    "moves": 385,
                },
            },
            {
                "test_id": 2015,
                "name": "motion_z_long_travel_factory",
                "pass": True,
                "metrics": {
                    "rep": 3,
                    "ref": 2,
                    "anchor_x": 43000,
                    "anchor_y": 13000,
                    "xy_to": 0,
                    "zmax": 80000,
                    "dz": 79900,
                    "z_span": 2,
                    "z_drift": 2,
                    "z_ret": 0,
                    "ret_err": 0,
                    "move_to": 0,
                    "home_to": 0,
                    "guard": 0,
                    "bound": 0,
                },
            },
            {
                "test_id": 2016,
                "name": "motion_limit_triggered_home_fact",
                "pass": True,
                "metrics": {
                    "axis": "xyz",
                    "offset": 200,
                    "x_span": 2,
                    "y_span": 2,
                    "z_span": 2,
                    "x_drift": 2,
                    "y_drift": 2,
                    "z_drift": 2,
                    "move_to": 0,
                    "home_to": 0,
                    "limit_start": 0,
                },
            },
        ],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_pressure_regulator_selftest():
    guard_ok = {
        "guard": 0,
        "home_to": 0,
        "motor_abs_max": 24000,
        "motor_delta_max": 5000,
        "max_jump": 874,
        "slew": 1,
        "cap_hz": 16000,
    }
    return {
        "run_id": 7890,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:04:00Z",
        "aborted": False,
        "summary": {"total": 10, "passed": 10, "failed": 0},
        "results": [
            {
                "test_id": 2210,
                "name": "pressure_sensor_idle_stability_factory",
                "pass": True,
                "metrics": {
                    "dur_ms": 10000,
                    "p_mean": 1640,
                    "r_mean": 1642,
                    "p_span": 4,
                    "r_span": 5,
                    "p_drift": 1,
                    "r_drift": 1,
                    "p_rej": 0,
                    "r_rej": 0,
                    "p_fault": 0,
                    "r_fault": 0,
                    "timeout": 0,
                },
            },
            {
                "test_id": 2211,
                "name": "pressure_regulator_home_repeatability_factory",
                "pass": True,
                "metrics": {
                    "rep": 3,
                    "p_n": 3,
                    "r_n": 3,
                    "p_span": 2,
                    "r_span": 2,
                    "p_drift": 1,
                    "r_drift": 1,
                    "p_move_to": 0,
                    "r_move_to": 0,
                    "p_home_to": 0,
                    "r_home_to": 0,
                },
            },
            {"test_id": 2212, "name": "pressure_hold_leak_print_factory", "pass": True, "metrics": {"ch": "p", "target_raw": 3386, "hold_ms": 15000, "slope_raw_min": 0, "corr_steps": 10, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2213, "name": "pressure_hold_leak_refuel_factory", "pass": True, "metrics": {"ch": "r", "target_raw": 3386, "hold_ms": 15000, "slope_raw_min": 0, "corr_steps": 10, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2214, "name": "pressure_target_cycle_print_factory", "pass": True, "metrics": {"ch": "p", "settle_max_ms": 500, "err_max": 4, "low_dn_span": 8, "high_up_span": 8, "over": 2, "under": 3, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2215, "name": "pressure_target_cycle_refuel_factory", "pass": True, "metrics": {"ch": "r", "settle_max_ms": 500, "err_max": 5, "low_dn_span": 8, "high_up_span": 8, "over": 2, "under": 3, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2216, "name": "pressure_motor_hysteresis_print_factory", "pass": True, "metrics": {"ch": "p", "target_raw": 3386, "below_span": 8, "above_span": 7, "hyst_span": 4, "err_max": 4, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2217, "name": "pressure_motor_hysteresis_refuel_factory", "pass": True, "metrics": {"ch": "r", "target_raw": 3386, "below_span": 8, "above_span": 7, "hyst_span": 4, "err_max": 5, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2218, "name": "pressure_step_ladder_print_factory", "pass": True, "metrics": {"ch": "p", "raw1": 2512, "raw2": 3386, "raw3": 4259, "settle_max_ms": 500, "err_max": 4, "over": 2, "under": 3, "ready_miss": 0, "timeout": 0, **guard_ok}},
            {"test_id": 2219, "name": "pressure_step_ladder_refuel_factory", "pass": True, "metrics": {"ch": "r", "raw1": 2512, "raw2": 3386, "raw3": 4259, "settle_max_ms": 500, "err_max": 5, "over": 2, "under": 3, "ready_miss": 0, "timeout": 0, **guard_ok}},
        ],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_refuel_vacuum_selftest():
    return {
        "run_id": 6789,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:03:00Z",
        "aborted": False,
        "summary": {"total": 2, "passed": 2, "failed": 0},
        "results": [
            {
                "test_id": 2220,
                "name": "refuel_vacuum_sensor_shift_factory",
                "pass": True,
                "metrics": {
                    "pre": 1638,
                    "post": 1642,
                    "shift": 4,
                    "pre_sp": 6,
                    "post_sp": 5,
                    "pre_n": 60,
                    "post_n": 60,
                    "rej": 0,
                    "rail": 0,
                    "spike": 0,
                    "fault": 0,
                    "to": 0,
                    "trace": 1,
                },
            },
            {
                "test_id": 2221,
                "name": "refuel_vacuum_cycle_repeatability_factory",
                "pass": True,
                "metrics": {
                    "cyc": 20,
                    "neg_n": 20,
                    "zero_n": 20,
                    "n_span": 30,
                    "z_span": 25,
                    "nps": 2000,
                    "zps": 1800,
                    "err": 20,
                    "settle": 700,
                    "guard": 0,
                    "ma": 30000,
                    "md": 7000,
                    "rej": 0,
                    "to": 0,
                    "trace": 1,
                },
            },
        ],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _raw_valve_characterization_selftest():
    common = {
        "psi": 2000,
        "rep": 10,
        "pulses": 30,
        "ready": 0,
        "home_to": 0,
        "fresh_to": 0,
        "focus": 1,
        "sm": 5,
        "sc": 120,
        "ec": 30,
        "timeout": 0,
    }
    rows = [
        {
            "test_id": 2473,
            "name": "valve_char_print_2psi_repeat_linearity",
            "pass": True,
            "metrics": {"ch": "p", **common},
        },
        {
            "test_id": 2474,
            "name": "valve_char_refuel_2psi_repeat_linearity",
            "pass": True,
            "metrics": {"ch": "r", **common},
        },
        {
            "test_id": 2475,
            "name": "valve_char_channel_balance_2psi",
            "pass": True,
            "metrics": {
                "psi": 2000,
                "rep": 10,
                "pulses": 60,
                "ready": 0,
                "home_to": 0,
                "fresh_to": 0,
                "sc": 240,
                "ec": 60,
                "timeout": 0,
            },
        },
    ]
    return {
        "run_id": 2468,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:06:00Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": rows,
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _derived_valve_characterization_metrics():
    common = {
        "m15": 20,
        "m30": 35,
        "m45": 50,
        "cv15": 4,
        "cv30": 5,
        "cv45": 5,
        "rg15": 80,
        "rg30": 120,
        "rg45": 160,
        "lt15": 5,
        "lt30": 6,
        "lt45": 7,
        "rej": 0,
        "lat_miss": 0,
        "ring_miss": 0,
        "excl": 3,
        "rw": 60,
        "sw": 80,
        "mono": 1,
    }
    return {
        2473: common,
        2474: {**common, "m15": 21, "m30": 36, "m45": 51},
        2475: {
            "m15p": 20,
            "m15r": 21,
            "m30p": 35,
            "m30r": 36,
            "m45p": 50,
            "m45r": 51,
            "r15": 95,
            "r30": 97,
            "r45": 98,
            "d15": 1,
            "d30": 1,
            "d45": 1,
            "rej": 0,
            "lat_miss": 0,
            "ring_miss": 0,
            "excl": 6,
        },
    }


def _raw_valve_gap_sweep_selftest():
    common = {
        "home_to": 0,
        "timeout": 0,
        "ready": 0,
        "fresh_to": 0,
        "focus": 1,
        "sc": 120,
        "ec": 30,
    }
    rows = [
        {
            "test_id": 2476,
            "name": "valve_gap_print_1500us_2psi",
            "pass": True,
            "metrics": {"ch": "p", "pw": 1500, "rep": 8, "pulses": 40, "gaps": 5, **common},
        },
        {
            "test_id": 2477,
            "name": "valve_gap_refuel_1500us_2psi",
            "pass": True,
            "metrics": {"ch": "r", "pw": 1500, "rep": 8, "pulses": 40, "gaps": 5, **common},
        },
        {
            "test_id": 2478,
            "name": "valve_gap_print_control_2psi",
            "pass": True,
            "metrics": {"ch": "p", "rep": 4, "pulses": 16, "cond": 4, **common},
        },
        {
            "test_id": 2479,
            "name": "valve_gap_refuel_control_2psi",
            "pass": True,
            "metrics": {"ch": "r", "rep": 4, "pulses": 16, "cond": 4, **common},
        },
    ]
    return {
        "run_id": 1357,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:06:00Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": rows,
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _derived_valve_gap_sweep_metrics():
    common = {"rej": 0, "lat_miss": 0, "ring_miss": 0}
    return {
        2476: {"g250": 4, "g500": 5, "g1000": 5, "g2000": 6, "g5000": 6, **common},
        2477: {"g250": 3, "g500": 4, "g1000": 4, "g2000": 5, "g5000": 5, **common},
        2478: {"m30g500": 9, "m30g2000": 10, "m45g500": 16, "m45g2000": 17, **common},
        2479: {"m30g500": 9, "m30g2000": 10, "m45g500": 16, "m45g2000": 17, **common},
    }


def _manifest_path(tmp_path):
    path = tmp_path / "unit_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "qualification_manifest_v0",
                "manifest_id": "unit_manifest",
                "name": "Unit Manifest",
                "profile": "FULL",
                "expected_test_ids": [1001],
                "analysis_rules": {"1001": {"category": "protocol", "failure_domain": "infrastructure"}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _gripper_manifest_ref():
    return "gripper_seal_v1"


def _gripper_stress_manifest_ref():
    return "gripper_seal_stress_v1"


def _xy_motion_manifest_ref():
    return "xy_motion_v1"


def _motion_envelope_manifest_ref():
    return "motion_envelope_v1"


def _pressure_regulator_manifest_ref():
    return "pressure_regulator_v1"


def _refuel_vacuum_manifest_ref():
    return "refuel_vacuum_v1"


def _valve_characterization_manifest_ref():
    return "valve_characterization_v1"


def _valve_gap_sweep_manifest_ref():
    return "valve_gap_sweep_v1"


class FakeSerial:
    def __init__(self, inbound: bytes):
        self._buf = bytearray(inbound)
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int) -> bytes:
        if not self._buf:
            return b""
        take = 1 if n > 0 else 0
        out = bytes(self._buf[:take])
        del self._buf[:take]
        return out

    def write(self, data: bytes):
        self.writes.append(bytes(data))
        return len(data)


def _frame(mod, payload: bytes) -> bytes:
    return mod.frame_payload(payload)


def _hello_ack(mod) -> bytes:
    return _frame(mod, bytes([mod.CMD_HELLO_ACK, 0x40]))


def _queue_ack(mod, seq8: int, seq32: int) -> bytes:
    payload = bytearray([mod.CMD_QUEUE_ACK, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    payload += bytes([mod.TAG_ACK_RESULT, 1, mod.ACK_RESULT_ACCEPTED])
    return _frame(mod, bytes(payload))


def _bye_ack(mod) -> bytes:
    return _frame(mod, bytes([mod.CMD_BYE_ACK, 0x43]))


def _bye_done(mod) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, 0x43])
    payload += bytes([mod.TAG_SEQ32, 4]) + (1).to_bytes(4, "little")
    return _frame(mod, bytes(payload))


def _written_commands(mod, serial: FakeSerial):
    commands = []
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if frame:
                commands.append(frame[0])
                break
    return commands


def test_run_qualification_wraps_fake_selftest_invoker(tmp_path):
    invocations = []

    def fake_invoker(invocation):
        invocations.append(invocation)
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        port="COM9",
        baud=57600,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=120000,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert result.report["overall_status"] == "pass"
    assert result.raw_selftest_path.exists()
    assert result.report_path.exists()
    assert result.summary_csv_path.exists()
    assert len(invocations) == 1
    command = invocations[0].command
    assert "--port" in command
    assert "COM9" in command
    assert "--baud" in command
    assert "57600" in command
    assert "--profile" in command
    assert "FULL" in command
    assert str(result.raw_selftest_path) in command
    assert "--progress-jsonl" not in command


def test_run_qualification_can_request_progress_jsonl(tmp_path):
    invocations = []

    def fake_invoker(invocation):
        invocations.append(invocation)
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        progress_jsonl=True,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert "--progress-jsonl" in invocations[0].command


def test_run_qualification_writes_failure_report_when_raw_missing(tmp_path):
    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        invoker=lambda _invocation: 3,
    )

    assert result.returncode == 3
    assert result.report["overall_status"] == "fail"
    raw = json.loads(result.raw_selftest_path.read_text(encoding="utf-8"))
    assert raw["aborted"] is True
    assert raw["host_checks"][0]["name"] == "selftest_invoker"


def test_qualification_cli_accepts_fake_invoker(tmp_path, capsys):
    def fake_invoker(invocation):
        invocation.raw_report_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
        return 0

    rc = cli.main(
        [
            "--manifest",
            str(_manifest_path(tmp_path)),
            "--machine-id",
            "LC-0001",
            "--identity-path",
            str(tmp_path / "local" / "machine_identity.json"),
            "--output-root",
            str(tmp_path / "qualification"),
            "--run-selftest-path",
            str(Path("tools") / "run_selftest.py"),
        ],
        invoker=fake_invoker,
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Wrote qualification report" in captured.out


def test_default_qualification_manifest_is_factory_acceptance_v3():
    assert DEFAULT_MANIFEST_REF == "factory_acceptance_v3"
    parser = cli.build_parser()
    args = parser.parse_args([])

    assert args.manifest == "factory_acceptance_v3"
    gripper_args = parser.parse_args([
        "--manifest",
        "gripper_seal_v1",
        "--fixture",
        "dummy_blocked_head_v1",
        "--operator-prompts",
    ])
    assert gripper_args.manifest == "gripper_seal_v1"
    assert gripper_args.fixture == "dummy_blocked_head_v1"
    assert gripper_args.operator_prompts is True


def test_default_gripper_control_preflight_uses_hello_then_print(monkeypatch):
    import tools.run_selftest as mod

    serial = FakeSerial(_hello_ack(mod) + _queue_ack(mod, 0x31, 1))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    rc = default_gripper_control("preflight_print", "/dev/ttyAMA0", 115200)

    assert rc == 0
    assert _written_commands(mod, serial) == [mod.CMD_HELLO, 0x20]


def test_default_gripper_control_shutdown_sends_goodbye(monkeypatch):
    import tools.run_selftest as mod

    serial = FakeSerial(_hello_ack(mod) + _bye_ack(mod) + _bye_done(mod))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    rc = default_gripper_control("shutdown", "/dev/ttyAMA0", 115200)

    assert rc == 0
    assert _written_commands(mod, serial) == [mod.CMD_HELLO, mod.CMD_GOODBYE]


def test_qualification_can_convert_existing_raw_report_without_invoker(tmp_path):
    raw_path = tmp_path / "existing_raw.json"
    raw_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 99

    result = run_qualification(
        manifest_ref=_manifest_path(tmp_path),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        raw_report_path=raw_path,
        invoker=fake_invoker,
    )

    assert result.returncode == 0
    assert called is False
    assert result.raw_selftest_path.read_text(encoding="utf-8") == raw_path.read_text(encoding="utf-8")
    assert result.report["schema_version"] == "qualification_report_v1"


def test_gripper_seal_manifest_rejects_hardware_run_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["overall_status"] == "fail"
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_gripper_seal_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["dummy_blocked_head_v1"]


def test_xy_motion_manifest_rejects_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_xy_motion_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="motion_clear_envelope_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_xy_motion_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_xy_motion_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["motion_clear_envelope_v1"]


def test_motion_envelope_manifest_rejects_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_motion_envelope_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="motion_full_envelope_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_motion_envelope_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_motion_envelope_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["motion_full_envelope_v1"]


def test_pressure_regulator_manifest_rejects_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_pressure_regulator_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="pressure_closed_loop_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_pressure_regulator_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_pressure_regulator_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["pressure_closed_loop_v1"]


def test_refuel_vacuum_manifest_rejects_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_refuel_vacuum_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="refuel_vacuum_dry_back_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_refuel_vacuum_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_refuel_vacuum_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == ["refuel_vacuum_dry_back_v1"]


def test_valve_characterization_manifest_rejects_without_operator_prompts(tmp_path):
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 0

    result = run_qualification(
        manifest_ref=_valve_characterization_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        fixture_id="valve_closed_loop_pulse_matrix_v1",
        operator_prompts=False,
        invoker=fake_invoker,
    )

    assert result.returncode == 3
    assert called is False
    assert result.report["host_checks"][0]["name"] == "operator_prompts_required"


def test_valve_characterization_manifest_rejects_missing_required_fixture(tmp_path):
    result = run_qualification(
        manifest_ref=_valve_characterization_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        operator_prompts=True,
        invoker=lambda _invocation: 0,
        prompter=lambda _message: None,
    )

    assert result.returncode == 3
    assert result.report["host_checks"][0]["name"] == "fixture_required"
    assert result.report["host_checks"][0]["details"]["allowed_fixture_ids"] == [
        "valve_closed_loop_pulse_matrix_v1"
    ]


def test_xy_motion_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--xy-motion-suite" in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_xy_motion_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"XY motion suite should not call gripper control: {action}:{port}:{baud}")

    result = run_qualification(
        manifest_ref=_xy_motion_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=300000,
        fixture_id="motion_clear_envelope_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "motion_clear_envelope_v1" in events[0]
    assert "hardware envelope is clear" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "motion_clear_envelope_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"


def test_pressure_regulator_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--pressure-regulator-suite" in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_pressure_regulator_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"Pressure regulator suite should not call gripper control: {action}:{port}:{baud}")

    result = run_qualification(
        manifest_ref=_pressure_regulator_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="pressure_closed_loop_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "pressure_closed_loop_v1" in events[0]
    assert "hardware envelope is clear" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "pressure_closed_loop_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"


def test_refuel_vacuum_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--refuel-vacuum-suite" in invocation.command
        assert "--pressure-trace" in invocation.command
        assert "--pressure-regulator-suite" not in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_refuel_vacuum_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"Refuel vacuum suite should not call gripper control: {action}:{port}:{baud}")

    result = run_qualification(
        manifest_ref=_refuel_vacuum_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=300000,
        fixture_id="refuel_vacuum_dry_back_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "refuel_vacuum_dry_back_v1" in events[0]
    assert "no reagent is loaded" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "refuel_vacuum_dry_back_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"


def test_valve_characterization_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path, monkeypatch):
    events = []
    generated_artifacts = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--valve-characterization-suite" in invocation.command
        assert "--pressure-trace" in invocation.command
        assert "--pressure-regulator-suite" not in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_valve_characterization_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"Valve characterization suite should not call gripper control: {action}:{port}:{baud}")

    def fake_generate_valve_artifacts(artifacts):
        generated_artifacts.append(artifacts.run_dir)
        return SimpleNamespace(report_metrics=_derived_valve_characterization_metrics())

    monkeypatch.setattr(qualification_runner, "generate_valve_trace_artifacts", fake_generate_valve_artifacts)

    result = run_qualification(
        manifest_ref=_valve_characterization_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="valve_closed_loop_pulse_matrix_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "valve_closed_loop_pulse_matrix_v1" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "valve_closed_loop_pulse_matrix_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"
    assert generated_artifacts == [result.run_dir]
    report_row = next(row for row in result.report["results"] if row["test_id"] == 2473)
    assert report_row["metrics"]["mono"] == 1
    raw_row = next(row for row in json.loads(result.raw_selftest_path.read_text(encoding="utf-8"))["results"] if row["test_id"] == 2473)
    assert "mono" not in raw_row["metrics"]


def test_valve_gap_sweep_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path, monkeypatch):
    events = []
    generated_artifacts = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--valve-gap-sweep-suite" in invocation.command
        assert "--pressure-trace" in invocation.command
        assert "--valve-characterization-suite" not in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_valve_gap_sweep_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"Valve gap sweep suite should not call gripper control: {action}:{port}:{baud}")

    def fake_generate_valve_artifacts(artifacts):
        generated_artifacts.append(artifacts.run_dir)
        return SimpleNamespace(report_metrics=_derived_valve_gap_sweep_metrics())

    monkeypatch.setattr(qualification_runner, "generate_valve_trace_artifacts", fake_generate_valve_artifacts)

    result = run_qualification(
        manifest_ref=_valve_gap_sweep_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="valve_closed_loop_pulse_matrix_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "valve_closed_loop_pulse_matrix_v1" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "valve_closed_loop_pulse_matrix_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"
    assert generated_artifacts == [result.run_dir]
    report_row = next(row for row in result.report["results"] if row["test_id"] == 2476)
    assert report_row["metrics"]["g500"] == 5
    raw_row = next(row for row in json.loads(result.raw_selftest_path.read_text(encoding="utf-8"))["results"] if row["test_id"] == 2476)
    assert "g500" not in raw_row["metrics"]


def test_motion_envelope_operator_prompt_runs_selected_suite_without_gripper_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--motion-envelope-suite" in invocation.command
        assert "--xy-motion-suite" not in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_motion_envelope_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        raise AssertionError(f"Motion envelope suite should not call gripper control: {action}:{port}:{baud}")

    result = run_qualification(
        manifest_ref=_motion_envelope_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="motion_full_envelope_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events[0].startswith("prompt:Confirm qualification setup")
    assert "motion_full_envelope_v1" in events[0]
    assert events == [events[0], "self-test"]
    assert result.report["run"]["fixture_id"] == "motion_full_envelope_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == ["confirm_fixture_setup"]
    assert result.report["overall_status"] == "pass"


def test_gripper_seal_operator_prompt_order_and_teardown(tmp_path):
    events = []

    def fake_prompter(message):
        if "Load" in message:
            events.append("prompt:load")
        elif "heard or felt" in message:
            events.append("prompt:valves")
        elif "Support" in message:
            events.append("prompt:support")
        elif "Remove" in message:
            events.append("prompt:remove")
        else:
            events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--gripper-seal-suite" in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        events.append(f"machine:{action}:{port}:{baud}")
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events == [
        "prompt:load",
        "machine:preflight_print:/dev/ttyAMA0:115200",
        "machine:preflight_refuel:/dev/ttyAMA0:115200",
        "prompt:valves",
        "self-test",
        "prompt:support",
        "machine:release:/dev/ttyAMA0:115200",
        "prompt:remove",
        "machine:off:/dev/ttyAMA0:115200",
        "machine:shutdown:/dev/ttyAMA0:115200",
    ]
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert [item["stage"] for item in result.report["operator_interactions"]] == [
        "load_dummy_head",
        "confirm_valve_clicks",
        "support_before_release",
        "remove_dummy_head",
    ]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_valve_preflight_print"]["pass"] is True
    assert host_checks["gripper_valve_preflight_refuel"]["pass"] is True
    assert host_checks["gripper_teardown_release"]["pass"] is True
    assert host_checks["gripper_teardown_off"]["pass"] is True
    assert host_checks["gripper_teardown_shutdown"]["pass"] is True


def test_gripper_seal_stress_uses_gripper_prompts_teardown_and_enriches_report(tmp_path, monkeypatch):
    events = []
    generated_artifacts = []

    def fake_prompter(message):
        if "Load" in message:
            events.append("prompt:load")
        elif "heard or felt" in message:
            events.append("prompt:valves")
        elif "Support" in message:
            events.append("prompt:support")
        elif "Remove" in message:
            events.append("prompt:remove")
        else:
            events.append(f"prompt:{message}")

    def fake_invoker(invocation):
        events.append("self-test")
        assert "--gripper-seal-stress-suite" in invocation.command
        assert "--pressure-trace" in invocation.command
        assert "--gripper-seal-suite" not in invocation.command
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_stress_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        events.append(f"machine:{action}:{port}:{baud}")
        return 0

    def fake_generate_gripper_artifacts(artifacts):
        generated_artifacts.append(artifacts.run_dir)
        return SimpleNamespace(report_metrics={2510: {"d3": 22, "rej_py": 0}, 2512: {"drop_mean": 12, "rej_py": 0}})

    monkeypatch.setattr(qualification_runner, "generate_gripper_trace_artifacts", fake_generate_gripper_artifacts)

    result = run_qualification(
        manifest_ref=_gripper_stress_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=900000,
        fixture_id="dummy_blocked_head_motion_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert events == [
        "prompt:load",
        "machine:preflight_print:/dev/ttyAMA0:115200",
        "machine:preflight_refuel:/dev/ttyAMA0:115200",
        "prompt:valves",
        "self-test",
        "prompt:support",
        "machine:release:/dev/ttyAMA0:115200",
        "prompt:remove",
        "machine:off:/dev/ttyAMA0:115200",
        "machine:shutdown:/dev/ttyAMA0:115200",
    ]
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_motion_v1"
    assert generated_artifacts == [result.run_dir]
    report_row = next(row for row in result.report["results"] if row["test_id"] == 2510)
    assert report_row["metrics"]["d3"] == 22
    raw_row = next(row for row in json.loads(result.raw_selftest_path.read_text(encoding="utf-8"))["results"] if row["test_id"] == 2510)
    assert "d3" not in raw_row["metrics"]


def test_gripper_teardown_release_succeeds_on_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification_runner, "GRIPPER_TEARDOWN_RETRY_DELAY_S", 0)
    release_calls = 0

    def fake_invoker(invocation):
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        nonlocal release_calls
        if action == "release":
            release_calls += 1
            return 3 if release_calls == 1 else 0
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=lambda _message: None,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    release = host_checks["gripper_teardown_release"]
    assert release["pass"] is True
    assert release["details"]["attempts"] == 2
    assert release["details"]["returncodes"] == [3, 0]
    assert release["details"]["ack_success"] is True
    assert release["details"]["manual_confirmed"] is False


def test_gripper_teardown_release_manual_recovery_keeps_successful_suite_passing(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification_runner, "GRIPPER_TEARDOWN_RETRY_DELAY_S", 0)
    prompts = []

    def fake_invoker(invocation):
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_prompter(message):
        prompts.append(message)

    def fake_gripper_control(action, port, baud):
        return 3 if action == "release" else 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=fake_prompter,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 0
    assert result.report["overall_status"] == "pass"
    assert any("automatic gripper release command" in prompt for prompt in prompts)
    assert [item["stage"] for item in result.report["operator_interactions"]] == [
        "load_dummy_head",
        "confirm_valve_clicks",
        "support_before_release",
        "manual_gripper_release_recovery",
        "remove_dummy_head",
    ]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    release = host_checks["gripper_teardown_release"]
    assert release["pass"] is True
    assert release["details"]["attempts"] == 3
    assert release["details"]["returncodes"] == [3, 3, 3]
    assert release["details"]["ack_success"] is False
    assert release["details"]["manual_confirmed"] is True


def test_gripper_teardown_off_failure_remains_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification_runner, "GRIPPER_TEARDOWN_RETRY_DELAY_S", 0)
    off_calls = 0

    def fake_invoker(invocation):
        invocation.raw_report_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
        return 0

    def fake_gripper_control(action, port, baud):
        nonlocal off_calls
        if action == "off":
            off_calls += 1
            return 3
        return 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=lambda _message: None,
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 3
    assert off_calls == 2
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_teardown_release"]["pass"] is True
    assert host_checks["gripper_teardown_off"]["pass"] is False
    assert host_checks["gripper_teardown_off"]["details"]["attempts"] == 2
    assert host_checks["gripper_teardown_shutdown"]["pass"] is True


def test_gripper_seal_preflight_failure_aborts_before_selftest(tmp_path):
    events = []

    def fake_invoker(_invocation):
        raise AssertionError("preflight failure should abort before self-test")

    def fake_gripper_control(action, port, baud):
        events.append(action)
        return 3 if action == "preflight_refuel" else 0

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        port="/dev/ttyAMA0",
        baud=115200,
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        timeout_ms=420000,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=True,
        invoker=fake_invoker,
        prompter=lambda _message: events.append("prompt"),
        gripper_control=fake_gripper_control,
    )

    assert result.returncode == 3
    assert events == ["prompt", "preflight_print", "preflight_refuel"]
    host_checks = {item["name"]: item for item in result.report["host_checks"]}
    assert host_checks["gripper_valve_preflight_print"]["pass"] is True
    assert host_checks["gripper_valve_preflight_refuel"]["pass"] is False


def test_gripper_seal_raw_report_conversion_skips_prompts_and_invoker(tmp_path):
    raw_path = tmp_path / "gripper_raw.json"
    raw_path.write_text(json.dumps(_raw_gripper_selftest()), encoding="utf-8")
    called = False

    def fake_invoker(_invocation):
        nonlocal called
        called = True
        return 99

    result = run_qualification(
        manifest_ref=_gripper_manifest_ref(),
        machine_id="LC-0001",
        identity_path=tmp_path / "local" / "machine_identity.json",
        output_root=tmp_path / "qualification",
        raw_report_path=raw_path,
        fixture_id="dummy_blocked_head_v1",
        operator_prompts=False,
        invoker=fake_invoker,
        prompter=lambda _message: (_ for _ in ()).throw(AssertionError("raw conversion should not prompt")),
    )

    assert result.returncode == 0
    assert called is False
    assert result.report["run"]["fixture_id"] == "dummy_blocked_head_v1"
    assert result.report["operator_interactions"] == []


def test_qualification_cli_raw_report_skips_invoker(tmp_path):
    raw_path = tmp_path / "existing_raw.json"
    raw_path.write_text(json.dumps(_raw_selftest()), encoding="utf-8")

    def fake_invoker(_invocation):
        raise AssertionError("raw report conversion should not invoke hardware self-test")

    rc = cli.main(
        [
            "--manifest",
            str(_manifest_path(tmp_path)),
            "--machine-id",
            "LC-0001",
            "--identity-path",
            str(tmp_path / "local" / "machine_identity.json"),
            "--output-root",
            str(tmp_path / "qualification"),
            "--raw-report",
            str(raw_path),
        ],
        invoker=fake_invoker,
    )

    assert rc == 0


def test_gitignore_excludes_local_identity():
    text = Path(".gitignore").read_text(encoding="utf-8")

    assert "local/" in text
