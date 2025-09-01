from PySide6 import QtCore
from pathlib import Path
from dfu_update import DfuUpdateWorker

class FirmwareUpdateControllerMixin(QtCore.QObject):
    dfu_progress = QtCore.Signal(int)
    dfu_stage    = QtCore.Signal(str)
    dfu_finished = QtCore.Signal(bool, str)
    dfu_output   = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dfu_thread: DfuUpdateWorker | None = None

        # Defaults; tweak if you keep them elsewhere
        self._dfu_script = Path(__file__).resolve().parent / "dfu_update.py"
        self._bin_path   = Path("/home/labcraft/LabCraft_printer/firmware/freeRTOS_LabCraft.bin")
        self._boot_chip  = "gpiochip0"; self._boot_off = 24
        self._rst_chip   = "gpiochip0"; self._rst_off  = 23
        self._cwd        = None  # or Path("/home/labcraft/LabCraft_printer")

    def start_firmware_update(self):
        if self._dfu_thread and self._dfu_thread.isRunning():
            return  # already running
        w = DfuUpdateWorker(
            dfu_script=self._dfu_script,
            bin_path=self._bin_path,
            cwd=self._cwd,
            boot_chip=self._boot_chip, boot_off=self._boot_off,
            rst_chip=self._rst_chip,   rst_off=self._rst_off,
        )
        w.progress.connect(self.dfu_progress)
        w.stage.connect(self.dfu_stage)
        w.finished.connect(self.dfu_finished)
        w.output.connect(self.dfu_output)
        # Retain ref so it isn’t GC’d
        self._dfu_thread = w
        w.start()