from types import SimpleNamespace

from Controller import Controller


def test_handle_reset_report_logs_and_emits_popup(tmp_path):
    events = []
    popups = []

    controller = Controller.__new__(Controller)
    controller._reset_report_log_path = tmp_path / "board_reset_reports.jsonl"
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: events.append(("recover", None)),
            update_last_reset_report=lambda report: events.append(("update", dict(report))),
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    report = {"summary": "Board restarted after watchdog reset."}

    Controller.handle_reset_report(controller, report)

    assert events == [("recover", None), ("update", report)]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert len(popups) == 1
    assert popups[0][0] == "Board Reset Detected"
    assert "Board restarted after watchdog reset." in popups[0][1]
    assert "Homing state was cleared. Home the motors before resuming motion." in popups[0][1]
    assert "Saved to:" in popups[0][1]
    assert str(controller._reset_report_log_path) in popups[0][1]
    assert controller._reset_report_log_path.exists()
    text = controller._reset_report_log_path.read_text(encoding="utf-8")
    assert '"summary": "Board restarted after watchdog reset."' in text


def test_handle_reset_report_emits_popup_when_log_write_fails():
    events = []
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: events.append(("recover", None)),
            update_last_reset_report=lambda report: events.append(("update", dict(report))),
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    def _raise_log_error(_report):
        raise OSError("disk unavailable")

    controller._append_reset_report_log = _raise_log_error
    report = {"summary": "Board restarted after power/brownout reset."}

    Controller.handle_reset_report(controller, report)

    assert events == [("recover", None), ("update", report)]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert len(popups) == 1
    assert popups[0][0] == "Board Reset Detected"
    assert "Board restarted after power/brownout reset." in popups[0][1]
    assert "Homing state was cleared. Home the motors before resuming motion." in popups[0][1]
    assert "Log save failed: disk unavailable" in popups[0][1]


def test_handle_serial_connection_lost_emits_guidance_popup():
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    Controller.handle_serial_connection_lost(
        controller,
        {
            "summary": "Machine serial connection ended unexpectedly (serial closed).",
            "black_box_log_path": "logs/machine_black_box/session.json",
            "black_box_log_error": None,
        },
    )

    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert popups[0][0] == "Machine Connection Lost"
    assert "Machine serial connection ended unexpectedly" in popups[0][1]
    assert "Machine state is no longer trusted." in popups[0][1]
    assert "Reconnect to the MCU and home the motors" in popups[0][1]
    assert "Black-box log: logs/machine_black_box/session.json" in popups[0][1]


def test_handle_serial_connection_lost_popup_survives_black_box_write_failure():
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    Controller.handle_serial_connection_lost(
        controller,
        {
            "summary": "Machine serial connection ended unexpectedly (OSError: device disconnected).",
            "black_box_log_path": None,
            "black_box_log_error": "disk unavailable",
        },
    )

    assert popups[0][0] == "Machine Connection Lost"
    assert "OSError: device disconnected" in popups[0][1]
    assert "Black-box log save failed: disk unavailable" in popups[0][1]
