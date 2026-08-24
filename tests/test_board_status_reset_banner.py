from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from Model import MachineModel
from View import BoardStatusBox


class _RootModel(QObject):
    machine_state_updated = Signal(bool)

    def __init__(self, machine_model):
        super().__init__()
        self.machine_model = machine_model
        self.location_model = _LocationModel()


class _LocationModel(QObject):
    locations_updated = Signal()


def test_board_status_does_not_render_last_reset_banner(qapp, test_profile):
    machine_model = MachineModel()
    root_model = _RootModel(machine_model)
    main_window = SimpleNamespace(color_dict={}, profile=test_profile)
    controller = SimpleNamespace()

    box = BoardStatusBox(main_window, root_model, controller)

    assert "Last Reset" not in box.labels


def test_board_status_shows_flash_session_and_fault_when_camera_model_is_present(qapp, test_profile):
    machine_model = MachineModel()
    root_model = _RootModel(machine_model)
    root_model.droplet_camera_model = SimpleNamespace(
        get_flash_session_armed=lambda: True,
        get_flash_fault_latched=lambda: True,
        get_flash_fault_reason_display=lambda: "Trigger line stayed high for too long",
    )
    main_window = SimpleNamespace(color_dict={}, profile=test_profile)
    controller = SimpleNamespace()

    box = BoardStatusBox(main_window, root_model, controller)
    box.update_status()

    assert box.labels["Flash Session"].text() == "Armed"
    assert box.labels["Flash Fault"].text() == "Trigger line stayed high for too long"


def test_board_status_uses_compact_paired_rows_and_full_width_fault(qapp, test_profile):
    machine_model = MachineModel()
    root_model = _RootModel(machine_model)
    root_model.droplet_camera_model = SimpleNamespace()
    main_window = SimpleNamespace(color_dict={}, profile=test_profile)

    box = BoardStatusBox(main_window, root_model, SimpleNamespace())
    layout = box.layout

    def position(widget):
        return layout.getItemPosition(layout.indexOf(widget))

    assert layout.rowCount() == 4
    assert position(box.status_name_labels["Homed"]) == (0, 0, 1, 1)
    assert position(box.status_name_labels["Paused"]) == (0, 2, 1, 1)
    assert position(box.status_name_labels["Location"]) == (1, 0, 1, 1)
    assert position(box.status_name_labels["Cycle Count"]) == (1, 2, 1, 1)
    assert position(box.status_name_labels["Current Micros"]) == (2, 0, 1, 1)
    assert position(box.status_name_labels["Flash Session"]) == (2, 2, 1, 1)
    assert position(box.status_name_labels["Flash Fault"]) == (3, 0, 1, 1)
    assert position(box.labels["Flash Fault"]) == (3, 1, 1, 3)
