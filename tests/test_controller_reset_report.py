from types import SimpleNamespace

from Controller import Controller


def test_handle_reset_report_updates_model_and_emits_popup():
    updates = []
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(update_last_reset_report=lambda report: updates.append(report))
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )

    report = {"summary": "Board restarted after watchdog reset."}

    Controller.handle_reset_report(controller, report)

    assert updates == [report]
    assert popups == [("Board Reset Detected", "Board restarted after watchdog reset.")]
