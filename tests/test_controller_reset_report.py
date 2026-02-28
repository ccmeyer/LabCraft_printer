from types import SimpleNamespace

from Controller import Controller


def test_handle_reset_report_logs_and_emits_popup(tmp_path):
    recoveries = []
    popups = []

    controller = Controller.__new__(Controller)
    controller._reset_report_log_path = tmp_path / "board_reset_reports.jsonl"
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: recoveries.append(True),
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

    assert recoveries == [True]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert len(popups) == 1
    assert popups[0][0] == "Board Reset Detected"
    assert "Board restarted after watchdog reset." in popups[0][1]
    assert str(controller._reset_report_log_path) in popups[0][1]
    assert controller._reset_report_log_path.exists()
    text = controller._reset_report_log_path.read_text(encoding="utf-8")
    assert '"summary": "Board restarted after watchdog reset."' in text
