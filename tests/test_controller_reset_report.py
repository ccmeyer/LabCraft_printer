from types import SimpleNamespace

from Controller import Controller


def test_handle_reset_report_updates_model_and_emits_popup():
    updates = []
    recoveries = []
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: recoveries.append(True),
            update_last_reset_report=lambda report: updates.append(report),
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
    assert updates == [report]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert popups == [("Board Reset Detected", "Board restarted after watchdog reset.")]
