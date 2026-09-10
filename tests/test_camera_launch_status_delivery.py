"""Camera dialogs must not hold an MCU status frame open in a modal loop."""
import gc
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QMessageBox

import Machine_FreeRTOS as mfr
from View import PressurePlotBox
from hardware.profile import CURRENT_PROFILE
from test_host_black_box_log import _make_machine
from test_mcu_reader_liveness import LiveSerial
from test_pressure_plotbox_buttons import (
    _FakeMachineModel, _make_controller, _make_main_window, _make_model,
)


def _launch_box(kind):
    model = _make_model(
        _FakeMachineModel(regulating_print_pressure=True, current_location="plate"),
        [], printer_head=object(),
    )
    controller = _make_controller([])
    box = PressurePlotBox(
        _make_main_window(CURRENT_PROFILE, [], popup_response=QMessageBox.Yes),
        model, controller,
    )
    method = "droplet_imager" if kind == "droplet" else "refuel_camera"
    launcher = "_launch_droplet_imager_dialog" if kind == "droplet" else "_launch_refuel_camera_dialog"
    return box, model, controller, method, launcher


@pytest.fixture(autouse=True)
def _collect_probe_cycles():
    yield
    # These composed fakes retain callbacks back to their Qt owners. Collect
    # their cycles between tests, rather than during a later dialog event loop.
    gc.collect()


@pytest.mark.parametrize("kind", ["droplet", "refuel"])
def test_move_status_returns_before_modal_camera_arming(qapp, test_profile, tmp_path, kind):
    box, model, controller, method, launcher = _launch_box(kind)
    machine = _make_machine(qapp, test_profile, tmp_path)
    machine.ser = LiveSerial()
    reader = machine.reader = mfr.SerialReader(machine.ser)
    machine._transport_ready = True
    machine._tx_paused = False
    machine._awaiting_first_status_after_hello = False
    machine.send_command_to_board = Mock(return_value=False)
    observations = []

    def modal_camera():
        # Use the real arming command and dispatch gate, but no physical camera.
        machine.start_read_camera()
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
        observations.append({
            "processed": reader.receive_snapshot()["processed_count"],
            "sent": [call.args[0].command_type for call in machine.send_command_to_board.call_args_list],
        })

    setattr(box, launcher, modal_camera)
    getattr(box, method)()
    completion = controller.move_to_location.call_args.kwargs["on_complete"]
    move = machine.command_queue.add_command("ABSOLUTE_XY", 0, 0, 0, handler=completion)
    move.mark_as_sent()

    def apply_status(data):
        model.machine_model.current_location = "camera"
        machine.update_command_numbers(data["Current_command"], data["Last_completed"])

    machine.status_updated.connect(apply_status)
    status = {"Current_command": move.command_number, "Last_completed": move.command_number,
              "Last_accepted": move.command_number, "Last_retired": move.command_number,
              "cmd_depth": 0, "Transport_paused": False}
    reader.stamp_frame(status, "status")
    try:
        machine.update_status(status)
        qapp.processEvents()
        assert len(observations) == 1
        assert observations[0]["processed"] == 1, observations[0]
        assert "START_READ_CAMERA" in observations[0]["sent"]
    finally:
        machine.status_updated.disconnect(apply_status)
        machine._cancel_pending_acks()
        machine.stop_execution_timer()
        machine.command_queue.clear_queue()
        machine.reader = None
        reader.deleteLater()
        machine.deleteLater()
        box.close()


@pytest.mark.parametrize("kind", ["droplet", "refuel"])
@pytest.mark.parametrize("reason", ["queue_clear_requested", "machine_disconnected", "mcu_reset_requested"])
def test_interruption_after_move_completion_cancels_deferred_camera_launch(qapp, kind, reason):
    box, _model, controller, method, launcher = _launch_box(kind)
    launched = Mock()
    setattr(box, launcher, launched)
    getattr(box, method)()
    completion = controller.move_to_location.call_args.kwargs["on_complete"]
    completion()
    controller.machine_workflow_interrupted_signal.emit({"reason": reason, "notify_user": False})
    qapp.processEvents()
    launched.assert_not_called()
    box.close()


@pytest.mark.parametrize("kind", ["droplet", "refuel"])
def test_destroyed_owner_does_not_open_deferred_camera(qapp, kind):
    box, _model, controller, method, launcher = _launch_box(kind)
    launched = Mock()
    setattr(box, launcher, launched)
    getattr(box, method)()
    completion = controller.move_to_location.call_args.kwargs["on_complete"]
    completion()
    box.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    launched.assert_not_called()
