import json

from tools.qualification import gripper_refresh_production as production


class FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += float(seconds)

    @property
    def milliseconds(self):
        return int(round(self.seconds * 1000.0))


class FakeTransport:
    def __init__(self, clock, *, deferred_gap_ms=3800, fail_name=None, cleanup_fails=False):
        self.clock = clock
        self.deferred_gap_ms = deferred_gap_ms
        self.fail_name = fail_name
        self.cleanup_fails = cleanup_fails
        self.latest_refresh_period_ms = None
        self.latest_print_pressure_raw = None
        self.latest_target_print_pressure_raw = None
        self.latest_print_pressure_active = None
        self.next_seq32 = 1
        self.commands = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def hello(self):
        return None

    def queue(self, name, command, p1=0, p2=0, p3=0):
        if name == self.fail_name:
            raise production.ProductionPathError(f"forced failure: {name}")
        if self.cleanup_fails and name == "cleanup_disable_profile":
            raise production.ProductionPathError("forced cleanup failure")
        observation = production.CommandObservation(
            name=name,
            command=command,
            p1=p1,
            p2=p2,
            p3=p3,
            seq32=self.next_seq32,
            ack_result="accepted",
            sent_ms=self.clock.milliseconds,
        )
        self.next_seq32 += 1
        self.commands.append(observation)
        if name == "enable_deferred_profile":
            self.latest_refresh_period_ms = production.REFRESH_INTERVAL_MS
        return observation

    def wait_retired(self, observation, timeout_ms=production.COMMAND_RETIRE_TIMEOUT_MS):
        delay_ms = self.deferred_gap_ms if observation.name == "post_refresh_dispense" else 100
        self.clock.sleep(delay_ms / 1000.0)
        observation.retired_ms = self.clock.milliseconds
        return observation.retired_ms

    def wait_refresh_period(self, timeout_ms=1000):
        if self.latest_refresh_period_ms is None and any(
            item.name == "enable_deferred_profile" for item in self.commands
        ):
            self.latest_refresh_period_ms = production.REFRESH_INTERVAL_MS
        return self.latest_refresh_period_ms

    def reset_refresh_period_observation(self):
        self.latest_refresh_period_ms = None

    def reset_print_pressure_observation(self):
        self.latest_print_pressure_raw = None
        self.latest_target_print_pressure_raw = None
        self.latest_print_pressure_active = None

    def wait_print_pressure_ready(self, target_raw, tolerance_raw, timeout_ms=15000):
        del tolerance_raw, timeout_ms
        self.clock.sleep(0.2)
        self.latest_print_pressure_raw = target_raw
        self.latest_target_print_pressure_raw = target_raw
        self.latest_print_pressure_active = 1
        return {"pressure_raw": target_raw, "target_raw": target_raw, "active": 1}

    def clear(self):
        return not self.cleanup_fails


def test_command_tlvs_match_production_four_byte_parameter_contract():
    encoded = production._command_tlvs(1, 20, 0)

    assert encoded == bytes(
        [
            production.run_selftest.TAG_P1, 4, 1, 0, 0, 0,
            production.run_selftest.TAG_P2, 4, 20, 0, 0, 0,
            production.run_selftest.TAG_P3, 4, 0, 0, 0, 0,
        ]
    )


def test_serial_transport_parses_status_without_assuming_a_seq8_byte():
    clock = FakeClock()
    transport = production.SerialProductionTransport(
        "/dev/test",
        115200,
        serial_factory=lambda *_args, **_kwargs: None,
        monotonic=clock.monotonic,
    )
    frame = bytes(
        [production.CMD_STATUS,
         production.TAG_PRINT_PRESSURE, 2, 0xD0, 0x09,
         production.TAG_TARGET_PRINT_PRESSURE, 2, 0xD0, 0x09,
         production.TAG_ACTIVE_PRINT_PRESSURE, 2, 1, 0,
         production.TAG_LAST_RETIRED, 4, 7, 0, 0, 0,
         production.TAG_GRIP_REFRESH, 4, 0x30, 0x75, 0, 0]
    )

    transport._capture_status(frame)

    assert transport._last_retired == 7
    assert transport.latest_refresh_period_ms == 30000
    assert transport.latest_print_pressure_raw == 2512
    assert transport.latest_target_print_pressure_raw == 2512
    assert transport.latest_print_pressure_active == 1


def test_serial_transport_rejects_retirement_sequence_gap():
    clock = FakeClock()
    transport = production.SerialProductionTransport(
        "/dev/test",
        115200,
        serial_factory=lambda *_args, **_kwargs: None,
        monotonic=clock.monotonic,
    )
    transport._last_retired = 4
    observation = production.CommandObservation(
        name="expected_third_command",
        command=production.CMD_DISPENSE_PRINT,
        p1=1,
        p2=20,
        p3=0,
        seq32=3,
        ack_result="accepted",
        sent_ms=0,
    )

    try:
        transport.wait_retired(observation)
    except production.ProductionPathError as exc:
        assert "advanced from the expected 3 to 4" in str(exc)
    else:
        raise AssertionError("retirement sequence gaps must fail closed")


def test_refresh_period_observation_can_be_reset_after_enable_retirement():
    clock = FakeClock()
    transport = production.SerialProductionTransport(
        "/dev/test",
        115200,
        serial_factory=lambda *_args, **_kwargs: None,
        monotonic=clock.monotonic,
    )
    transport.latest_refresh_period_ms = 60000

    transport.reset_refresh_period_observation()

    assert transport.latest_refresh_period_ms is None


def test_production_path_happy_path_records_both_profile_modes(tmp_path):
    clock = FakeClock()
    transport = FakeTransport(clock)
    artifact_path = tmp_path / "production_path.json"

    check = production.run_gripper_refresh_production_path(
        port="/dev/test",
        baud=115200,
        artifact_path=artifact_path,
        transport_factory=lambda: transport,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert check["pass"] is True
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == production.PRODUCTION_PATH_SCHEMA
    assert artifact["pass"] is True
    assert artifact["metrics"]["reported_refresh_period_ms"] == 30000
    assert artifact["metrics"]["print_pressure_ready"] == {
        "pressure_raw": production.PRINT_PRESSURE_TARGET_RAW,
        "target_raw": production.PRINT_PRESSURE_TARGET_RAW,
        "active": 1,
    }
    assert artifact["metrics"]["startup_dispense_latency_ms"] == 100
    assert artifact["metrics"]["deferred_first_latency_ms"] == 100
    assert artifact["metrics"]["deferred_retirement_gap_ms"] == 3800
    assert artifact["metrics"]["p1_zero_dispense_1_latency_ms"] == 100
    assert artifact["metrics"]["p1_zero_dispense_2_latency_ms"] == 100
    assert artifact["cleanup"]["disable_retired"] is True
    assert [row["name"] for row in artifact["commands"]] == [
        "set_print_pressure_1psi",
        "regulate_print_pressure",
        "close_gripper",
        "enable_deferred_profile",
        "startup_dispense",
        "deferred_boundary_dispense",
        "post_refresh_dispense",
        "disable_deferred_profile",
        "enable_calibration_profile",
        "p1_zero_dispense_1",
        "p1_zero_dispense_2",
        "final_disable_profile",
        "deregulate_print_pressure",
    ]


def test_production_path_rejects_short_deferred_gap_and_disables_profile(tmp_path):
    clock = FakeClock()
    transport = FakeTransport(clock, deferred_gap_ms=100)

    check = production.run_gripper_refresh_production_path(
        port="/dev/test",
        baud=115200,
        artifact_path=tmp_path / "production_path.json",
        transport_factory=lambda: transport,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert check["pass"] is False
    assert "outside 3000..7000" in check["details"]["error"]["message"]
    assert check["details"]["cleanup"]["disable_retired"] is True
    assert check["details"]["cleanup"]["deregulate_retired"] is True
    assert transport.commands[-1].name == "cleanup_deregulate_print_pressure"
    assert all(item.command not in (production.run_selftest.CMD_GOODBYE, production.CMD_GRIPPER_CLOSE + 1) for item in transport.commands)


def test_production_path_uses_clear_fallback_when_cleanup_disable_fails(tmp_path):
    clock = FakeClock()
    transport = FakeTransport(
        clock,
        fail_name="startup_dispense",
        cleanup_fails=True,
    )

    check = production.run_gripper_refresh_production_path(
        port="/dev/test",
        baud=115200,
        artifact_path=tmp_path / "production_path.json",
        transport_factory=lambda: transport,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert check["pass"] is False
    assert check["details"]["cleanup"]["disable_retired"] is False
    assert check["details"]["cleanup"]["clear_fallback"] is False
    assert "reconnect" in check["details"]["cleanup"] or "reconnect_error" in check["details"]["cleanup"]
