import struct

import Machine_FreeRTOS as mfr


def _frame(payload: bytes) -> bytes:
    crc = mfr.crc16_x25(payload)
    return bytes([mfr.START_BYTE, len(payload)]) + payload + struct.pack("<H", crc)


def _reset_report_payload(reset_cause: int) -> bytes:
    return bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            1,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            reset_cause,
        ]
    )


def _tlv(tag: int, raw: bytes) -> bytes:
    return bytes([tag, len(raw)]) + raw


def _regulator_context_payload(
    *,
    p_flags=0x0089,
    r_flags=0x0103,
    p_wdg_enabled=0,
    r_wdg_enabled=1,
    p_wdg_age_ms=0xFFFFFFFF,
    r_wdg_age_ms=42,
    p_last_event=3,
    r_last_event=14,
    p_last_event_age_ms=12,
    r_last_event_age_ms=0xFFFFFFFF,
    snapshot_tick_ms=123456,
) -> bytes:
    return struct.pack(
        "<BBHHBBIIBBIII",
        1,
        1,
        p_flags,
        r_flags,
        p_wdg_enabled,
        r_wdg_enabled,
        p_wdg_age_ms,
        r_wdg_age_ms,
        p_last_event,
        r_last_event,
        p_last_event_age_ms,
        r_last_event_age_ms,
        snapshot_tick_ms,
    )


def _fault_context_payload(*, version=1) -> bytes:
    header = (version, 0x7D, 1, 7, mfr.CMD_MAP["HOME_XY"], 2, 3, 0, 5, 7, 16)
    registers = (
        0xFFFFFFFD, 0x20001200, 0x20010000, 0x20001200, 0x20001000, 0x20001400,
        0x00000001, 0x00000002, 0x00000003, 0x00000004, 0x0000000C, 0x08005679,
        0x08001235, 0x21000010, 0x00008200, 0x40000000, 0x00000002, 0x00000000,
        0x00070000, 0x20000020, 0x20000024, 0x00000002, 0x00000000, 0x00000001,
        0x00000000,
    )
    return struct.pack("<10BH25I", *header, *registers)


class FakeSerial:
    def __init__(self, data: bytes):
        self._buf = bytearray(data)
        self.is_open = True

    def read(self, n: int) -> bytes:
        if not self._buf:
            self.is_open = False
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def cancel_read(self):
        self.is_open = False


def test_serial_reader_emits_status_and_ack(qapp):
    status_payload = bytes(
        [
            mfr.CMD_STATUS,
            mfr.TAG_CURR_CMD,
            4,
            3,
            0,
            0,
            0,
            mfr.TAG_LAST_CMD,
            4,
            2,
            0,
            0,
            0,
            mfr.TAG_LAST_ACCEPTED_CMD,
            4,
            3,
            0,
            0,
            0,
            mfr.TAG_LAST_RETIRED_CMD,
            4,
            2,
            0,
            0,
            0,
        ]
    )
    ack_payload = bytes(
        [
            mfr.HELLO_ACK,
            0x01,
            mfr.ACK_TLV_SEQ32,
            4,
            1,
            0,
            0,
            0,
            mfr.ACK_TLV_CAPABILITIES,
            4,
            mfr.REQUIRED_TRANSPORT_CAPS & 0xFF,
            (mfr.REQUIRED_TRANSPORT_CAPS >> 8) & 0xFF,
            (mfr.REQUIRED_TRANSPORT_CAPS >> 16) & 0xFF,
            (mfr.REQUIRED_TRANSPORT_CAPS >> 24) & 0xFF,
        ]
    )
    serial_stream = _frame(status_payload) + _frame(ack_payload)

    fake_ser = FakeSerial(serial_stream)
    reader = mfr.SerialReader(fake_ser)
    statuses = []
    acks = []
    reader.status_received.connect(statuses.append)
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert len(statuses) == 1
    assert statuses[0]["Current_command"] == 3
    assert statuses[0]["Last_completed"] == 2
    assert statuses[0]["Last_accepted"] == 3
    assert statuses[0]["Last_retired"] == 2
    assert isinstance(statuses[0]["__host_rx_monotonic_ns"], int)
    assert len(acks) == 1
    assert acks[0]["ack_cmd"] == mfr.HELLO_ACK
    assert acks[0]["seq32"] == 1
    assert acks[0]["capabilities"] == mfr.REQUIRED_TRANSPORT_CAPS


def test_serial_reader_rejects_bad_crc(qapp):
    payload = bytes([mfr.HELLO_ACK, 0x01, mfr.ACK_TLV_SEQ32, 4, 1, 0, 0, 0])
    good = _frame(payload)
    bad = good[:-1] + bytes([good[-1] ^ 0xFF])
    fake_ser = FakeSerial(bad)

    reader = mfr.SerialReader(fake_ser)
    statuses = []
    acks = []
    reader.status_received.connect(statuses.append)
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert statuses == []
    assert acks == []


def test_serial_reader_emits_reset_report_without_consuming_ack_path(qapp):
    ack_payload = bytes([mfr.HELLO_ACK, 0x01, mfr.ACK_TLV_SEQ32, 4, 1, 0, 0, 0])
    reset_payload = bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            1,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            4,
            mfr.TAG_RESET_FLAGS,
            4,
            mfr.CRASHLOG_FLAG_PENDING,
            0,
            0,
            0,
            mfr.TAG_RESET_LAST_FAULT,
            1,
            9,
            mfr.TAG_RESET_LAST_TASK,
            1,
            2,
            mfr.TAG_RESET_BOOT_STAGE,
            1,
            11,
            mfr.TAG_RESET_RECOVERY_BOOT,
            1,
            1,
            mfr.TAG_RESET_FAULT_STAGE,
            1,
            11,
            mfr.TAG_RESET_WATCHDOG_LATE_TASK,
            1,
            4,
            mfr.TAG_RESET_ACTIVE_COMMAND,
            1,
            mfr.CMD_MAP["OPEN_GRIPPER"],
            mfr.TAG_RESET_RCC_FLAGS,
            4,
            0,
            0,
            0,
            0x20,
        ]
    )
    serial_stream = _frame(ack_payload) + _frame(reset_payload)

    fake_ser = FakeSerial(serial_stream)
    reader = mfr.SerialReader(fake_ser)
    acks = []
    reports = []
    reader.ackReceived.connect(acks.append)
    reader.resetReportReceived.connect(reports.append)

    reader.run()

    assert len(acks) == 1
    assert acks[0]["ack_cmd"] == mfr.HELLO_ACK
    assert len(reports) == 1
    assert reports[0]["reset_cause_name"] == "iwdg"
    assert reports[0]["last_fault_name"] == "wdt"
    assert reports[0]["last_task_name"] == "orchestrator"
    assert reports[0]["watchdog_late_task_name"] == "pressure"
    assert reports[0]["active_command_name"] == "open_gripper"
    assert reports[0]["boot_stage_name"] == "hello_ack"
    assert reports[0]["fault_stage_name"] == "hello_ack"
    assert reports[0]["pending"] is True
    assert reports[0]["recovery_boot"] is True
    assert reports[0]["reset_flags_raw"] == 0x20000000
    assert reports[0]["reset_flag_names"] == ["iwdg"]
    assert reports[0]["reset_flag_summary"] == "iwdg"
    assert "during open_gripper" in reports[0]["summary"]
    assert "first late task pressure" in reports[0]["summary"]


def test_serial_reader_decodes_optional_raw_reset_flags(qapp):
    raw_flags = 0x10000000 | 0x04000000
    reset_payload = bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            0,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            3,
            mfr.TAG_RESET_FLAGS,
            4,
            0,
            0,
            0,
            0,
            mfr.TAG_RESET_RCC_FLAGS,
            4,
            raw_flags & 0xFF,
            (raw_flags >> 8) & 0xFF,
            (raw_flags >> 16) & 0xFF,
            (raw_flags >> 24) & 0xFF,
        ]
    )

    report = mfr.SerialReader._parse_reset_report(reset_payload)

    assert report is not None
    assert report["seq32"] == 0
    assert report["reset_cause_name"] == "software"
    assert report["reset_flags_raw"] == raw_flags
    assert report["reset_flag_names"] == ["software", "pin_reset"]
    assert report["reset_flag_summary"] == "software, pin_reset"


def test_serial_reader_decodes_optional_fault_task_name4(qapp):
    reset_payload = bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            0,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            3,
            mfr.TAG_RESET_FLAGS,
            4,
            mfr.CRASHLOG_FLAG_PENDING,
            0,
            0,
            0,
            mfr.TAG_RESET_LAST_FAULT,
            1,
            6,
            mfr.TAG_RESET_LAST_TASK,
            1,
            2,
            mfr.TAG_RESET_FAULT_STAGE,
            1,
            7,
            mfr.TAG_RESET_ACTIVE_COMMAND,
            1,
            mfr.CMD_MAP["ABSOLUTE_XY"],
            mfr.TAG_RESET_TASK_NAME4,
            4,
            ord("O"),
            ord("r"),
            ord("c"),
            ord("h"),
        ]
    )

    report = mfr.SerialReader._parse_reset_report(reset_payload)

    assert report is not None
    assert report["fault_task_name4"] == "Orch"
    assert report["last_task_name"] == "orchestrator"
    assert "stack_overflow in orchestrator task (Orch)" in report["summary"]
    assert "stage comm_rx_rearmed" in report["summary"]


def test_serial_reader_decodes_regulator_context_in_watchdog_reset_report(qapp):
    reset_payload = bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            1,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            4,
            mfr.TAG_RESET_FLAGS,
            4,
            mfr.CRASHLOG_FLAG_PENDING,
            0,
            0,
            0,
            mfr.TAG_RESET_LAST_FAULT,
            1,
            2,
            mfr.TAG_RESET_LAST_TASK,
            1,
            3,
            mfr.TAG_RESET_WATCHDOG_LATE_TASK,
            1,
            4,
        ]
    ) + _tlv(mfr.TAG_RESET_REG_CONTEXT, _regulator_context_payload())

    report = mfr.SerialReader._parse_reset_report(reset_payload)

    assert report is not None
    context = report["regulator_context"]
    assert context["valid"] is True
    assert context["snapshot_tick_ms"] == 123456
    assert context["print"]["names"] == ["active", "motion_hold", "motion_hold_wdg"]
    assert context["print"]["watchdog_enabled"] is False
    assert context["print"]["watchdog_age_ms"] is None
    assert context["print"]["last_event_name"] == "motion_hold_enter"
    assert context["print"]["last_event_age_ms"] == 12
    assert context["refuel"]["names"] == ["active", "homing", "recovery_hold"]
    assert context["refuel"]["watchdog_enabled"] is True
    assert context["refuel"]["watchdog_age_ms"] == 42
    assert context["refuel"]["last_event_name"] == "step_limit"
    assert context["refuel"]["last_event_age_ms"] is None
    assert "Regulator context:" in report["summary"]
    assert "refuel flags=active,homing,recovery_hold event=step_limit wdg=enabled/42ms" in report["summary"]


def test_serial_reader_marks_bad_regulator_context_invalid(qapp):
    reset_payload = _reset_report_payload(4) + _tlv(mfr.TAG_RESET_REG_CONTEXT, b"\x01\x01\x00")

    report = mfr.SerialReader._parse_reset_report(reset_payload)

    assert report is not None
    assert report["regulator_context"] == {
        "valid": False,
        "error": "bad_length",
        "raw_length": 3,
    }


def test_serial_reader_decodes_fault_context_and_adds_hex_summary(qapp):
    reset_payload = _reset_report_payload(3) + _tlv(
        mfr.TAG_RESET_FAULT_CONTEXT, _fault_context_payload()
    )

    report = mfr.SerialReader._parse_reset_report(reset_payload)

    assert report is not None
    context = report["fault_context"]
    assert context["version"] == 1
    assert context["core_frame_valid"] is True
    assert context["extended_fpu_frame"] is False
    assert context["task_stack_matched"] is True
    assert context["task_name"] == "home_x"
    assert context["active_exception_name"] == "irq_0"
    assert context["pc"] == 0x08001235
    assert context["lr"] == 0x08005679
    assert context["cfsr"] == 0x00008200
    assert context["task_stack_low"] == 0x20001000
    assert context["task_stack_high"] == 0x20001400
    assert context["home_phases"]["x"] == {"value": 2, "name": "coarse_seek"}
    assert context["home_phases"]["p"] == {"value": 5, "name": "final_backoff"}
    assert "PC=0x08001235" in report["summary"]
    assert "CFSR=0x00008200" in report["summary"]
    assert "task=home_x" in report["summary"]
    assert "active=irq_0" in report["summary"]
    assert "X=coarse_seek" in report["summary"]


def test_serial_reader_ignores_malformed_and_unknown_fault_context(qapp):
    for raw in (b"\x01\x02", _fault_context_payload(version=2)):
        report = mfr.SerialReader._parse_reset_report(
            _reset_report_payload(3) + _tlv(mfr.TAG_RESET_FAULT_CONTEXT, raw)
        )
        assert report is not None
        assert report["fault_context"] is None
        assert "Fault context:" not in report["summary"]


def test_serial_reader_accepts_older_reset_report_without_raw_flags(qapp):
    report = mfr.SerialReader._parse_reset_report(_reset_report_payload(1))

    assert report is not None
    assert report["reset_cause_name"] == "power"
    assert report["reset_flags_raw"] is None
    assert report["reset_flag_names"] == []
    assert report["reset_flag_summary"] == ""
    assert report["fault_task_name4"] is None
    assert report["regulator_context"] is None
    assert report["fault_context"] is None


def test_serial_reader_maps_new_crash_task_ids():
    assert mfr.CRASH_TASK_NAMES[12] == "printer"
    assert mfr.CRASH_TASK_NAMES[13] == "gripper"
    assert mfr.CRASH_TASK_NAMES[18] == "watchdog"
    assert mfr.CRASH_TASK_NAMES[20] == "timer"


def test_serial_reader_summarizes_non_fault_reset_causes():
    cases = [
        (1, "power", "Board restarted after power/brownout reset."),
        (2, "pin_reset", "Board restarted after external reset pin event."),
        (3, "software", "Board restarted after software reset."),
        (6, "low_power", "Board restarted after low-power reset."),
    ]

    for cause, expected_name, expected_summary in cases:
        report = mfr.SerialReader._parse_reset_report(_reset_report_payload(cause))

        assert report is not None
        assert report["reset_cause_name"] == expected_name
        assert report["summary"] == expected_summary


def test_serial_reader_decodes_queue_ack_result_and_expected_seq32(qapp):
    ack_payload = bytes(
        [
            mfr.CMD_QUEUE_ACK,
            0x05,
            mfr.ACK_TLV_SEQ32,
            4,
            9,
            0,
            0,
            0,
            mfr.ACK_TLV_RESULT,
            1,
            mfr.ACK_RESULT_GAP,
            mfr.ACK_TLV_EXPECTED_SEQ32,
            4,
            7,
            0,
            0,
            0,
        ]
    )
    fake_ser = FakeSerial(_frame(ack_payload))
    reader = mfr.SerialReader(fake_ser)
    acks = []
    reader.ackReceived.connect(acks.append)

    reader.run()

    assert acks == [
        {
            "ack_cmd": mfr.CMD_QUEUE_ACK,
            "seq8": 0x05,
            "seq32": 9,
            "ack_result": "gap",
            "expected_seq32": 7,
            "capabilities": None,
        }
    ]


def test_serial_reader_decodes_home_task_names_in_reset_reports(qapp):
    reset_payload = bytes(
        [
            mfr.RESET_REPORT,
            0x01,
            mfr.TAG_RESET_SEQ32,
            4,
            1,
            0,
            0,
            0,
            mfr.TAG_RESET_CAUSE,
            1,
            3,
            mfr.TAG_RESET_FLAGS,
            4,
            mfr.CRASHLOG_FLAG_PENDING,
            0,
            0,
            0,
            mfr.TAG_RESET_LAST_FAULT,
            1,
            6,
            mfr.TAG_RESET_LAST_TASK,
            1,
            7,
            mfr.TAG_RESET_BOOT_STAGE,
            1,
            7,
            mfr.TAG_RESET_FAULT_STAGE,
            1,
            7,
            mfr.TAG_RESET_WATCHDOG_LATE_TASK,
            1,
            0,
        ]
    )
    fake_ser = FakeSerial(_frame(reset_payload))

    reader = mfr.SerialReader(fake_ser)
    reports = []
    reader.resetReportReceived.connect(reports.append)

    reader.run()

    assert len(reports) == 1
    assert reports[0]["last_task_name"] == "home_x"
    assert "home_x" in reports[0]["summary"]


def test_serial_reader_request_stop_is_idempotent_and_waits_with_requested_timeout(qapp):
    class _Serial:
        def __init__(self):
            self.is_open = True
            self.cancel_calls = 0

        def cancel_read(self):
            self.cancel_calls += 1

    class _TestSerialReader(mfr.SerialReader):
        def __init__(self, ser):
            self.interrupt_calls = 0
            self.wait_calls = []
            super().__init__(ser)

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupt_calls += 1

        def wait(self, timeout):
            self.wait_calls.append(timeout)
            return True

    ser = _Serial()
    reader = _TestSerialReader(ser)

    reader.request_stop()
    reader.request_stop()
    stopped = reader.wait_for_stop(mfr.SERIAL_READER_STOP_WAIT_MS)

    assert stopped is True
    assert reader.interrupt_calls == 1
    assert reader.wait_calls == [mfr.SERIAL_READER_STOP_WAIT_MS]
    assert ser.cancel_calls == 1


def test_serial_reader_emits_exception_stop_reason(qapp):
    class _FailingSerial:
        is_open = True

        def read(self, _n):
            raise OSError("device disconnected")

    reader = mfr.SerialReader(_FailingSerial())
    stops = []
    reader.readerStopped.connect(stops.append)

    reader.run()

    assert stops == [
        {
            "reason": "exception",
            "requested_stop": False,
            "exception_type": "OSError",
            "message": "device disconnected",
        }
    ]
