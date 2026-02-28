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
