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


def test_serial_reader_accepts_older_reset_report_without_raw_flags(qapp):
    report = mfr.SerialReader._parse_reset_report(_reset_report_payload(1))

    assert report is not None
    assert report["reset_cause_name"] == "power"
    assert report["reset_flags_raw"] is None
    assert report["reset_flag_names"] == []
    assert report["reset_flag_summary"] == ""


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
