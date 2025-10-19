#!/usr/bin/env python3
"""
DFU updater for STM32F446 from a Raspberry Pi.

- BOOT (BOOT0) is driven by Pi GPIO-24 (BCM 24)
- RESET (NRST) is driven by Pi GPIO-23 (BCM 23)
- Enters DFU, flashes a .bin with dfu-util, exits DFU (resets), and returns.

Use from code:
    from dfu_update import update_firmware
    update_firmware()  # or pass paths/overrides

Use from CLI:
    python3 dfu_update.py --bin LabCraft_printer/firmware/freeRTOS_LabCraft.bin

You can override GPIO mapping or logic polarity via CLI flags.

Initial setup:
printf '%s\n' 'SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", GROUP="plugdev", MODE="0664"' \
 | sudo tee /etc/udev/rules.d/45-st-dfu.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
getent group plugdev || sudo groupadd plugdev
sudo usermod -aG plugdev $USER
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtCore
import subprocess
import re

class DfuUpdateWorker(QtCore.QThread):
    progress = QtCore.Signal(int)          # 0..100
    stage    = QtCore.Signal(str)          # human message
    finished = QtCore.Signal(bool, str)    # ok, message
    output   = QtCore.Signal(str)          # raw stdout lines (optional)

    def __init__(self, dfu_script: Path, bin_path: Path, cwd: Path | None = None,
                 boot_chip="gpiochip0", boot_off=24, rst_chip="gpiochip0", rst_off=23,
                 timeout_s=20.0, parent=None):
        super().__init__(parent)
        self.dfu_script = Path(dfu_script)
        self.bin_path   = Path(bin_path)
        self.cwd        = None if cwd is None else Path(cwd)
        self.boot_chip  = boot_chip
        self.boot_off   = int(boot_off)
        self.rst_chip   = rst_chip
        self.rst_off    = int(rst_off)
        self.timeout_s  = float(timeout_s)

    @staticmethod
    def _scale(pct: int, lo: int, hi: int) -> int:
        # clamp and linearly map 0..100 → lo..hi
        if   pct < 0:   pct = 0
        elif pct > 100: pct = 100
        return lo + int((hi - lo) * (pct / 100.0))

    def run(self):
        if not self.dfu_script.is_file():
            self.finished.emit(False, f"DFU script not found: {self.dfu_script}")
            return
        if not self.bin_path.is_file():
            self.finished.emit(False, f"Firmware .bin not found: {self.bin_path}")
            return

        cmd = [
            sys.executable, "-u", str(self.dfu_script),
            "--bin", str(self.bin_path),
            "--boot-chip", self.boot_chip, "--boot-off", str(self.boot_off),
            "--rst-chip", self.rst_chip,   "--rst-off",  str(self.rst_off),
            "--timeout", str(self.timeout_s)
        ]

        self.stage.emit("Preparing…")
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

        # Allow leading spaces and CR-echoed progress lines; capture %.
        rx_erase_line      = re.compile(r"^\s*Erase\s+\[[^\]]*\]\s+(\d{1,3})%", re.IGNORECASE)
        rx_erase_done_line = re.compile(r"^\s*Erase\s+done\.", re.IGNORECASE)
        rx_dl_line         = re.compile(r"^\s*Download\s+\[[^\]]*\]\s+(\d{1,3})%", re.IGNORECASE)
        rx_dl_done_line    = re.compile(r"^\s*Download\s+done\.", re.IGNORECASE)

        # Fallback percentage (used only if we never detected a phase yet)
        rx_pct_generic     = re.compile(r"(\d{1,3})%")

        phase = None            # None | "erase" | "download"
        ui_percent = 1

        while True:
            raw = proc.stdout.readline() if proc.stdout else ""
            if not raw:
                if proc.poll() is not None:
                    break
                self.msleep(20)
                continue

            # dfu-util often uses '\r' to rewrite the same line; strip all CRs
            s = raw.replace('\r', '').rstrip('\n')
            low = s.lower()
            self.output.emit(s)

            # Early stages from your dfu_update.py prints
            if "[dfu] using firmware:" in low:
                self.stage.emit("Found firmware")
                if ui_percent < 5:
                    ui_percent = 5; self.progress.emit(ui_percent)
                continue
            if "detected. flashing" in low:
                self.stage.emit("Device detected")
                if ui_percent < 20:
                    ui_percent = 20; self.progress.emit(ui_percent)
                continue

            # ----- ERASE progress -----
            m = rx_erase_line.match(s)
            if m:
                pct = int(m.group(1))
                if phase != "erase":
                    phase = "erase"
                    self.stage.emit("Erasing…")
                    if ui_percent < 20:
                        ui_percent = 20; self.progress.emit(ui_percent)
                ui = self._scale(pct, 20, 50)  # 20–50%
                if ui > ui_percent:
                    ui_percent = ui
                    self.progress.emit(ui_percent)
                continue

            if rx_erase_done_line.match(s):
                phase = "erase"
                ui_percent = max(ui_percent, 50)
                self.progress.emit(ui_percent)
                # don't 'continue' early; next lines may switch to Download
                continue

            # ----- DOWNLOAD progress -----
            m = rx_dl_line.match(s)
            if m:
                pct = int(m.group(1))
                if phase != "download":
                    phase = "download"
                    self.stage.emit("Downloading…")
                    if ui_percent < 50:
                        ui_percent = 50; self.progress.emit(ui_percent)
                ui = self._scale(pct, 50, 90)  # 50–90%
                if ui > ui_percent:
                    ui_percent = ui
                    self.progress.emit(ui_percent)
                continue

            if rx_dl_done_line.match(s):
                phase = "download"
                ui_percent = max(ui_percent, 90)
                self.progress.emit(ui_percent)
                continue

            # End / finalize cues
            if "file downloaded successfully" in low:
                self.stage.emit("Finalizing…")
                ui_percent = max(ui_percent, 98)
                self.progress.emit(ui_percent)
                continue
            if "submitting leave request" in low or "transitioning to dfumanifest" in low:
                self.stage.emit("Rebooting…")
                ui_percent = max(ui_percent, 99)
                self.progress.emit(ui_percent)
                continue

            # Fallback percentage only if we haven't entered a phase yet
            if phase is None:
                m = rx_pct_generic.search(s)
                if m:
                    pct = int(m.group(1))
                    ui = 20 + int(0.78 * pct)  # 20–98
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
# -------------------------
# Configuration defaults
# -------------------------

# Default pins (BCM names on Raspberry Pi):
DEFAULT_BOOT_CHIP   = "gpiochip0"  # BOOT0 control
DEFAULT_BOOT_OFFSET = 24           # BCM 24 on many Pi setups
DEFAULT_RST_CHIP    = "gpiochip0"  # NRST control
DEFAULT_RST_OFFSET  = 23           # BCM 23 on many Pi setups

# Polarity:
# - BOOT:   set HIGH to enable DFU (BOOT0=1), set LOW to run app (BOOT0=0)
# - RESET:  pulse LOW to reset
BOOT_ACTIVE_HIGH  = True
RESET_ACTIVE_LOW  = False

# DFU details
DFU_VIDPID    = "0483:df11"
FLASH_ADDRESS = "0x08000000"  # STM32F4 internal flash base

# -------------------------
# gpiod helpers (v1 & v2)
# -------------------------

def _open_chip(chip_name: str):
    """Open a gpiod.Chip allowing either 'gpiochipX' or '/dev/gpiochipX'."""
    import gpiod
    tried = []
    for name in (chip_name, f"/dev/{chip_name}" if not chip_name.startswith("/dev/") else None):
        if not name:
            continue
        tried.append(name)
        try:
            return gpiod.Chip(name)
        except FileNotFoundError:
            pass
    # Show what's actually available to help debugging
    import glob
    available = " ".join(sorted(glob.glob("/dev/gpiochip*"))) or "<none>"
    raise FileNotFoundError(f"Could not open GPIO chip {chip_name!r}. Tried {tried}. "
                            f"Available chips: {available}")

def _gpiofind(line_name: str):
    """
    Resolve a line name like 'GPIO24' -> (chip_path, offset) using the gpiofind CLI.
    Requires 'gpiod' package (apt) which provides gpiofind/gpioinfo binaries.
    """
    if shutil.which("gpiofind") is None:
        raise RuntimeError("gpiofind not found. Install it: sudo apt install gpiod")
    out = subprocess.check_output(["gpiofind", line_name], text=True).strip()
    # Format: "/dev/gpiochipN <offset>"
    chip_path, off = out.split()
    return chip_path, int(off)

def _make_output_line(chip_name, offset, initial=0, consumer="dfu_updater"):
    """
    Return an object with .set_value(v:int) and .release() that controls a single GPIO line.
    Works with libgpiod v1 and v2.
    """
    try:
        import gpiod
    except Exception as e:
        raise RuntimeError(
            "python3-libgpiod/gpiod is required.\n"
            "On Raspberry Pi OS: sudo apt install python3-libgpiod gpiod"
        ) from e

    # Detect v2 by presence of the 'line' namespace
    is_v2 = hasattr(gpiod, "line")

    if is_v2:
        # ----- libgpiod v2 API -----
        chip = _open_chip(chip_name)
        ls = gpiod.LineSettings()

        # v2 enums live in gpiod.line
        Direction = gpiod.line.Direction
        Value     = gpiod.line.Value

        ls.direction    = Direction.OUTPUT
        ls.output_value = Value.ACTIVE if initial else Value.INACTIVE

        req = chip.request_lines(consumer=consumer, config={offset: ls})

        class OutV2:
            def set_value(self, v: int):
                req.set_values({offset: Value.ACTIVE if v else Value.INACTIVE})
            def release(self):
                req.release()
        return OutV2()

    else:
        # ----- libgpiod v1 API -----
        chip = _open_chip(chip_name)
        line = chip.get_line(offset)
        line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT, default_vals=[initial])

        class OutV1:
            def set_value(self, v: int):
                line.set_value(1 if v else 0)
            def release(self):
                line.release()
        return OutV1()

class BootReset:
    """
    Context manager that controls BOOT and RESET via libgpiod.
    """
    def __init__(self,
                 boot_chip=DEFAULT_BOOT_CHIP,
                 boot_offset=DEFAULT_BOOT_OFFSET,
                 rst_chip=DEFAULT_RST_CHIP,
                 rst_offset=DEFAULT_RST_OFFSET,
                 boot_active_high=BOOT_ACTIVE_HIGH,
                 reset_active_low=RESET_ACTIVE_LOW,
                 boot_line_name: str | None = None,
                 rst_line_name: str | None = None):
        self.boot_chip = boot_chip
        self.boot_offset = boot_offset
        self.rst_chip = rst_chip
        self.rst_offset = rst_offset
        self.boot_active_high = boot_active_high
        self.reset_active_low = reset_active_low
        self.boot_line_name = boot_line_name
        self.rst_line_name = rst_line_name
        self._boot = None
        self._rst = None

    def __enter__(self):
        # If names provided (e.g., 'GPIO24'), resolve to chip+offset dynamically
        if self.boot_line_name:
            self.boot_chip, self.boot_offset = _gpiofind(self.boot_line_name)
        if self.rst_line_name:
            self.rst_chip, self.rst_offset = _gpiofind(self.rst_line_name)

        # Start with BOOT disabled (run app) and RESET deasserted
        boot_init = 0 if self.boot_active_high else 1
        rst_init  = 1 if self.reset_active_low else 0

        self._boot = _make_output_line(self.boot_chip, self.boot_offset,
                                    initial=boot_init, consumer="dfu_boot")
        self._rst  = _make_output_line(self.rst_chip,  self.rst_offset,
                                    initial=rst_init,  consumer="dfu_reset")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._boot:
            self._boot.release()
        if self._rst:
            self._rst.release()

    def set_boot_enabled(self, enabled: bool):
        # enabled=True => BOOT0 asserted (enter DFU on next reset)
        if self.boot_active_high:
            self._boot.set_value(1 if enabled else 0)
        else:
            self._boot.set_value(0 if enabled else 1)

    def pulse_reset(self, low_ms=300):
        # Assert then deassert reset according to polarity
        if self.reset_active_low:
            self._rst.set_value(0)
            time.sleep(low_ms / 1000.0)
            self._rst.set_value(1)
        else:
            self._rst.set_value(1)
            time.sleep(low_ms / 1000.0)
            self._rst.set_value(0)

# -------------------------
# DFU helpers
# -------------------------

def _wait_for_dfu(vidpid=DFU_VIDPID, timeout_s=12.0, poll_s=0.25):
    """Wait until dfu-util -l shows the expected VID:PID (e.g., 0483:df11)."""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout_s:
        try:
            out = subprocess.check_output(["dfu-util", "-l"], text=True, stderr=subprocess.STDOUT)
            last = out
            if vidpid.lower() in out.lower():
                return
        except subprocess.CalledProcessError as e:
            last = str(e)
        time.sleep(poll_s)
    raise TimeoutError(f"DFU device {vidpid} not found within {timeout_s}s.\nLast output:\n{last}")

def _flash_with_dfu(bin_path: Path,
                    flash_addr=FLASH_ADDRESS,
                    cwd: Path | None = None):
    """
    Flash a .bin at flash_addr using dfu-util, then leave DFU (dfu-util :leave).
    """
    if not shutil.which("dfu-util"):
        raise RuntimeError("dfu-util not found. Install with: sudo apt install dfu-util")

    cmd = ["dfu-util", "-a", "0", "-s", f"{flash_addr}:leave", "-D", str(bin_path)]
    subprocess.run(cmd, check=True, cwd=(str(cwd) if cwd else None))

def _resolve_firmware_path(
    candidate: str | Path,
    module_dir: Path,
    extra_candidates: list[Path] | None = None,
) -> Path:
    """
    Return an absolute Path to the firmware .bin, or raise FileNotFoundError
    after trying a sensible set of locations.
    """
    tried: list[Path] = []

    def _ok(p: Path) -> Path | None:
        tried.append(p)
        return p if p.is_file() else None

    # 1) As given (expand ~, don’t assume relative/absolute yet)
    cand = Path(str(candidate)).expanduser()
    if cand.is_file():
        return cand.resolve()

    # 2) If relative, try relative to:
    #    a) current working directory
    if not cand.is_absolute():
        if (p := _ok(Path.cwd() / cand)):
            return p.resolve()
        #    b) this module’s directory (file sitting next to script)
        if (p := _ok(module_dir / cand)):
            return p.resolve()
        #    c) repo root (if we’re inside a git repo)
        try:
            repo_root = Path(
                subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
            )
            if (p := _ok(repo_root / cand)):
                return p.resolve()
        except Exception:
            pass

    # 3) Any extra explicit candidates you want to try
    for p in (extra_candidates or []):
        if (q := _ok(p.expanduser())):
            return q.resolve()

    # 4) Nothing worked
    msg = ["Firmware .bin not found. Tried:"]
    msg += [f"  - {p}" for p in tried]
    raise FileNotFoundError("\n".join(msg))

# -------------------------
# Public API
# -------------------------

def update_firmware(bin_path: str | Path = "LabCraft_printer/firmware/freeRTOS_LabCraft.bin",
                    boot_chip: str = DEFAULT_BOOT_CHIP,
                    boot_offset: int = DEFAULT_BOOT_OFFSET,
                    rst_chip: str = DEFAULT_RST_CHIP,
                    rst_offset: int = DEFAULT_RST_OFFSET,
                    boot_line_name: str | None = None,
                    rst_line_name:  str | None = None,
                    dfu_vidpid: str = DFU_VIDPID,
                    flash_address: str = FLASH_ADDRESS,
                    enter_reset_ms: int = 400,
                    exit_reset_ms: int = 200,
                    dfu_timeout_s: float = 12.0,
                    cwd_for_dfu: str | Path | None = None,
                    verbose: bool = True):
    """
    Full sequence:
      1) Set BOOT enabled, pulse RESET -> DFU ROM
      2) Wait for DFU USB device
      3) dfu-util flash .bin at flash_address
      4) Disable BOOT, pulse RESET -> run app

    Args:
        bin_path: path to the .bin (absolute or relative)
        boot_line_name, reset_line_name: line names for gpiofind (e.g., "GPIO24", "GPIO23")
        dfu_vidpid: VID:PID string to detect DFU device
        flash_address: address for dfu-util -s (e.g., "0x08000000")
        enter_reset_ms / exit_reset_ms: reset pulse widths (ms)
        dfu_timeout_s: how long to wait for DFU enumeration
        cwd_for_dfu: optional working directory when invoking dfu-util
        verbose: print progress
    """
    module_dir = Path(__file__).resolve().parent
    bin_abs = _resolve_firmware_path(
        candidate=bin_path,
        module_dir=module_dir,
        extra_candidates=[
            # your known absolute on the Pi:
            Path("/home/labcraft/LabCraft_printer/firmware/freeRTOS_LabCraft.bin"),
            # a common repo-relative location if the app is run elsewhere:
            module_dir.parent / "firmware" / "freeRTOS_LabCraft.bin",
        ],
    )
    if verbose:
        print(f"[DFU] Using firmware: {bin_abs}")
        print(f"[DFU] BOOT={boot_chip}:{boot_offset}, RESET={rst_chip}:{rst_offset}")

    with BootReset(boot_chip=boot_chip,
                   boot_offset=boot_offset,
                   rst_chip=rst_chip,
                   rst_offset=rst_offset,
                   boot_active_high=BOOT_ACTIVE_HIGH,
                   reset_active_low=RESET_ACTIVE_LOW,
                   boot_line_name=boot_line_name,
                   rst_line_name=rst_line_name) as br:
        # Ensure RESET is deasserted before we start, ensure BOOT is disabled
        br.set_boot_enabled(False)
        time.sleep(0.02)

        # Enter DFU: BOOT enable then RESET pulse
        br.set_boot_enabled(True)
        time.sleep(0.02)
        br.pulse_reset(low_ms=enter_reset_ms)

        # Wait for USB DFU to enumerate
        _wait_for_dfu(vidpid=dfu_vidpid, timeout_s=dfu_timeout_s)

        if verbose:
            print(f"[DFU] Device {dfu_vidpid} detected. Flashing at {flash_address} ...")

        # Flash
        _flash_with_dfu(bin_abs, flash_addr=flash_address, cwd=(Path(cwd_for_dfu) if cwd_for_dfu else None))

        if verbose:
            print("[DFU] Flash complete. Exiting DFU and rebooting into application ...")

        # Exit DFU: disable BOOT and reset
        br.set_boot_enabled(False)
        time.sleep(0.02)
        br.pulse_reset(low_ms=exit_reset_ms)

    if verbose:
        print("[DFU] Done.")

def reset_board(*,
                rst_chip: str = DEFAULT_RST_CHIP,
                rst_offset: int = DEFAULT_RST_OFFSET,
                rst_line_name: str | None = None,
                pulse_ms: int = 200,
                # The BOOT params are optional; we keep BOOT explicitly disabled
                boot_chip: str = DEFAULT_BOOT_CHIP,
                boot_offset: int = DEFAULT_BOOT_OFFSET,
                boot_line_name: str | None = None,
                verbose: bool = True):
    """
    Hardware reset only:
      - Ensure BOOT is *disabled* (run application).
      - Pulse RESET (NRST) for `pulse_ms`.
      - Do not wait for/enter DFU; no flashing.

    You can pass either chip/offset or a gpio line name via `*_line_name`
    (e.g., rst_line_name="GPIO23") and it will resolve with `gpiofind`.
    """
    if verbose:
        print(f"[RESET] rst={rst_chip}:{rst_offset} (name={rst_line_name or '—'})")

    with BootReset(boot_chip=boot_chip,
                   boot_offset=boot_offset,
                   rst_chip=rst_chip,
                   rst_offset=rst_offset,
                   boot_line_name=boot_line_name,
                   rst_line_name=rst_line_name,
                   boot_active_high=BOOT_ACTIVE_HIGH,
                   reset_active_low=RESET_ACTIVE_LOW) as br:
        # Make sure we are NOT in DFU mode
        br.set_boot_enabled(False)
        time.sleep(0.02)
        # Pulse NRST
        br.pulse_reset(low_ms=pulse_ms)

    if verbose:
        print("[RESET] Done.")

# -------------------------
# CLI entry point
# -------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="STM32 DFU updater (Pi GPIO-24=BOOT, GPIO-23=RESET).")
    p.add_argument("--bin", dest="bin_path",
                   default="LabCraft_printer/firmware/freeRTOS_LabCraft.bin",
                   help="Path to firmware .bin (default: LabCraft_printer/firmware/freeRTOS_LabCraft.bin)")
    p.add_argument("--boot-chip", default=DEFAULT_BOOT_CHIP, help="Chip for BOOT line (e.g., gpiochip4)")
    p.add_argument("--boot-off", type=int, default=DEFAULT_BOOT_OFFSET, help="Line offset for BOOT (e.g., 24)")
    p.add_argument("--rst-chip", default=DEFAULT_RST_CHIP, help="Chip for RESET line (e.g., gpiochip4)")
    p.add_argument("--rst-off", type=int, default=DEFAULT_RST_OFFSET, help="Line offset for RESET (e.g., 23)")
    p.add_argument("--vidpid", dest="dfu_vidpid", default=DFU_VIDPID,
                   help='DFU VID:PID string, default "0483:df11"')
    p.add_argument("--addr", dest="flash_address", default=FLASH_ADDRESS,
                   help='Flash base address for dfu-util -s, default "0x08000000"')
    p.add_argument("--enter-ms", type=int, default=400, help="Reset pulse (ms) when entering DFU")
    p.add_argument("--exit-ms", type=int, default=200, help="Reset pulse (ms) when exiting DFU")
    p.add_argument("--timeout", type=float, default=12.0, help="DFU enumeration timeout (s)")
    p.add_argument("--cwd", dest="cwd_for_dfu", default=None,
                   help="Working directory for dfu-util (optional)")
    p.add_argument("-q", "--quiet", action="store_true", help="Less verbose output")
    return p.parse_args(argv)

def main(argv=None):
    args = _parse_args(argv)
    update_firmware(
        bin_path=args.bin_path,
        boot_chip=args.boot_chip,
        boot_offset=args.boot_off,
        rst_chip=args.rst_chip,
        rst_offset=args.rst_off,
        dfu_vidpid=args.dfu_vidpid,
        flash_address=args.flash_address,
        enter_reset_ms=args.enter_ms,
        exit_reset_ms=args.exit_ms,
        dfu_timeout_s=args.timeout,
        cwd_for_dfu=args.cwd_for_dfu,
        verbose=not args.quiet,
    )

if __name__ == "__main__":
    main(sys.argv[1:])