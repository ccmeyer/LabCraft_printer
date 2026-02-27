from pathlib import Path
import re
import subprocess
import sys

from PySide6 import QtCore


class DfuUpdateWorker(QtCore.QThread):
    progress = QtCore.Signal(int)          # 0..100
    stage    = QtCore.Signal(str)          # human message
    finished = QtCore.Signal(bool, str)    # ok, message
    output   = QtCore.Signal(str)          # raw stdout lines (optional)

    def __init__(
        self,
        dfu_script: Path,
        bin_path: Path,
        cwd: Path | None = None,
        boot_chip="gpiochip0",
        boot_off=24,
        rst_chip="gpiochip0",
        rst_off=23,
        manual: bool = False,
        dfu_vidpid: str = "0483:df11",
        flash_address: str = "0x08000000",
        timeout_s=20.0,
        parent=None,
    ):
        super().__init__(parent)
        self.dfu_script = Path(dfu_script)
        self.bin_path   = Path(bin_path)
        self.cwd        = None if cwd is None else Path(cwd)
        self.boot_chip  = boot_chip
        self.boot_off   = int(boot_off)
        self.rst_chip   = rst_chip
        self.rst_off    = int(rst_off)
        self.timeout_s  = float(timeout_s)

        self.manual = bool(manual)
        self.dfu_vidpid = str(dfu_vidpid)
        self.flash_address = str(flash_address)
        print("[DfuUpdateWorker] Initialized with manual =", self.manual)

    @staticmethod
    def _scale(pct: int, lo: int, hi: int) -> int:
        # clamp and linearly map 0..100 -> lo..hi
        if pct < 0:
            pct = 0
        elif pct > 100:
            pct = 100
        return lo + int((hi - lo) * (pct / 100.0))

    def run(self):
        print("[DfuUpdateWorker] Running DFU update..., manual =", self.manual)
        if not self.dfu_script.is_file():
            self.finished.emit(False, f"DFU script not found: {self.dfu_script}")
            return
        if not self.bin_path.is_file():
            self.finished.emit(False, f"Firmware .bin not found: {self.bin_path}")
            return

        cmd = [
            sys.executable, "-u", str(self.dfu_script),
            "--bin", str(self.bin_path),
            "--timeout", str(self.timeout_s),
            "--vidpid", self.dfu_vidpid,
            "--addr", self.flash_address,
        ]

        if self.manual:
            cmd += ["--manual"]
        else:
            cmd += [
                "--boot-chip", self.boot_chip, "--boot-off", str(self.boot_off),
                "--rst-chip",  self.rst_chip,  "--rst-off",  str(self.rst_off),
            ]

        self.stage.emit("Preparing...")
        self.progress.emit(1)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=(str(self.cwd) if self.cwd else None),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
        except Exception as e:
            self.finished.emit(False, f"Failed to spawn DFU: {e}")
            return

        rx_erase_line      = re.compile(r"^\s*Erase\s+\[[^\]]*\]\s+(\d{1,3})%", re.IGNORECASE)
        rx_erase_done_line = re.compile(r"^\s*Erase\s+done\.", re.IGNORECASE)
        rx_dl_line         = re.compile(r"^\s*Download\s+\[[^\]]*\]\s+(\d{1,3})%", re.IGNORECASE)
        rx_dl_done_line    = re.compile(r"^\s*Download\s+done\.", re.IGNORECASE)
        rx_pct_generic     = re.compile(r"(\d{1,3})%")

        phase = None
        ui_percent = 1

        while True:
            raw = proc.stdout.readline() if proc.stdout else ""
            if not raw:
                if proc.poll() is not None:
                    break
                self.msleep(20)
                continue

            s = raw.replace("\r", "").rstrip("\n")
            low = s.lower()
            self.output.emit(s)

            if "[dfu] using firmware:" in low:
                self.stage.emit("Found firmware")
                if ui_percent < 5:
                    ui_percent = 5
                    self.progress.emit(ui_percent)
                continue
            if "detected. flashing" in low:
                self.stage.emit("Device detected")
                if ui_percent < 20:
                    ui_percent = 20
                    self.progress.emit(ui_percent)
                continue

            m = rx_erase_line.match(s)
            if m:
                pct = int(m.group(1))
                if phase != "erase":
                    phase = "erase"
                    self.stage.emit("Erasing...")
                    if ui_percent < 20:
                        ui_percent = 20
                        self.progress.emit(ui_percent)
                ui = self._scale(pct, 20, 50)
                if ui > ui_percent:
                    ui_percent = ui
                    self.progress.emit(ui_percent)
                continue

            if rx_erase_done_line.match(s):
                phase = "erase"
                ui_percent = max(ui_percent, 50)
                self.progress.emit(ui_percent)
                continue

            m = rx_dl_line.match(s)
            if m:
                pct = int(m.group(1))
                if phase != "download":
                    phase = "download"
                    self.stage.emit("Downloading...")
                    if ui_percent < 50:
                        ui_percent = 50
                        self.progress.emit(ui_percent)
                ui = self._scale(pct, 50, 90)
                if ui > ui_percent:
                    ui_percent = ui
                    self.progress.emit(ui_percent)
                continue

            if rx_dl_done_line.match(s):
                phase = "download"
                ui_percent = max(ui_percent, 90)
                self.progress.emit(ui_percent)
                continue

            if "file downloaded successfully" in low:
                self.stage.emit("Finalizing...")
                ui_percent = max(ui_percent, 98)
                self.progress.emit(ui_percent)
                continue
            if "submitting leave request" in low or "transitioning to dfumanifest" in low:
                self.stage.emit("Rebooting...")
                ui_percent = max(ui_percent, 99)
                self.progress.emit(ui_percent)
                continue

            if phase is None:
                m = rx_pct_generic.search(s)
                if m:
                    pct = int(m.group(1))
                    ui = 20 + int(0.78 * pct)
                    if ui > ui_percent:
                        ui_percent = ui
                        self.progress.emit(ui_percent)

        rc = proc.wait()
        if rc == 0:
            self.progress.emit(100)
            self.stage.emit("Done")
            self.finished.emit(True, "Firmware updated successfully.")
        else:
            self.finished.emit(False, f"DFU failed (rc={rc}). Check logs.")
