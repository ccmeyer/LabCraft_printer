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

# -------------------------
# Configuration defaults
# -------------------------

# Default pins (BCM names on Raspberry Pi):
BOOT_LINE_NAME_DEFAULT  = "GPIO24"  # BOOT0 control
RESET_LINE_NAME_DEFAULT = "GPIO23"  # NRST control

# Polarity:
# - BOOT:   set HIGH to enable DFU (BOOT0=1), set LOW to run app (BOOT0=0)
# - RESET:  pulse LOW to reset
BOOT_ACTIVE_HIGH  = True
RESET_ACTIVE_LOW  = True

# DFU details
DFU_VIDPID    = "0483:df11"
FLASH_ADDRESS = "0x08000000"  # STM32F4 internal flash base

# -------------------------
# Minimal gpiod helpers
# -------------------------

def _gpiofind(line_name: str):
    """
    Use the 'gpiofind' binary to resolve a line name like 'GPIO23' -> (chip, offset).
    Returns ("/dev/gpiochipX", offset) or raises RuntimeError.
    """
    if shutil.which("gpiofind") is None:
        raise RuntimeError("gpiofind not found. Install 'gpiod' tools (sudo apt install gpiod).")
    try:
        out = subprocess.check_output(["gpiofind", line_name], text=True).strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gpiofind failed for {line_name}: {e}") from e
    # Expected format: "/dev/gpiochip4 23"
    parts = out.split()
    if len(parts) != 2 or not parts[0].startswith("/dev/gpiochip"):
        raise RuntimeError(f"Unexpected gpiofind output for {line_name!r}: {out!r}")
    chip, off_s = parts
    try:
        off = int(off_s)
    except ValueError:
        raise RuntimeError(f"Unexpected gpiofind offset for {line_name!r}: {out!r}")
    return chip, off

def _request_output(chip_path: str, line_offset: int, initial: int):
    """
    Request an output line using python3-libgpiod v2 API.
    Returns a request object with .set_value(line, value).
    """
    try:
        import gpiod  # python3-libgpiod v2
    except Exception as e:
        raise RuntimeError("python3-libgpiod is required. Install with: sudo apt install python3-libgpiod") from e

    # Build config: one line, set initial value
    cfg = { line_offset: gpiod.LineSettings(direction=gpiod.LineDirection.OUTPUT,
                                            output_value=1 if initial else 0) }
    req = gpiod.request_lines(chip_path, consumer="dfu-update", config=cfg)
    return req

class BootReset:
    """
    Context manager that controls BOOT and RESET via libgpiod.
    """
    def __init__(self,
                 boot_line_name=BOOT_LINE_NAME_DEFAULT,
                 reset_line_name=RESET_LINE_NAME_DEFAULT,
                 boot_active_high=BOOT_ACTIVE_HIGH,
                 reset_active_low=RESET_ACTIVE_LOW):
        self.boot_line_name = boot_line_name
        self.reset_line_name = reset_line_name
        self.boot_active_high = boot_active_high
        self.reset_active_low = reset_active_low
        self._boot_chip = None
        self._boot_off  = None
        self._rst_chip  = None
        self._rst_off   = None
        self._boot_req  = None
        self._rst_req   = None

    def __enter__(self):
        self._boot_chip, self._boot_off = _gpiofind(self.boot_line_name)
        self._rst_chip,  self._rst_off  = _gpiofind(self.reset_line_name)

        # Initialize: BOOT = inactive (so we start in app mode); RESET = deasserted (high if active-low)
        boot_init = 0 if self.boot_active_high else 1
        rst_init  = 1 if self.reset_active_low else 0

        self._boot_req = _request_output(self._boot_chip, self._boot_off, boot_init)
        self._rst_req  = _request_output(self._rst_chip,  self._rst_off,  rst_init)
        return self

    def __exit__(self, exc_type, exc, tb):
        # Release in reverse order
        try:
            if self._boot_req:
                self._boot_req.release()
        finally:
            if self._rst_req:
                self._rst_req.release()

    def _set_boot_raw(self, val: int):
        self._boot_req.set_value(self._boot_off, 1 if val else 0)

    def _set_reset_raw(self, val: int):
        self._rst_req.set_value(self._rst_off, 1 if val else 0)

    def set_boot_enabled(self, enabled: bool):
        """
        enabled=True  -> drive BOOT into DFU-enabled state (BOOT0=1 if active-high)
        enabled=False -> normal run state
        """
        if self.boot_active_high:
            self._set_boot_raw(1 if enabled else 0)
        else:
            self._set_boot_raw(0 if enabled else 1)

    def pulse_reset(self, low_ms=300):
        """
        Pulse reset: assert then deassert.
        If reset is active-low, we drive low then high; if active-high, we drive high then low.
        """
        if self.reset_active_low:
            # assert
            self._set_reset_raw(0)
            time.sleep(low_ms / 1000.0)
            # deassert
            self._set_reset_raw(1)
        else:
            self._set_reset_raw(1)
            time.sleep(low_ms / 1000.0)
            self._set_reset_raw(0)

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
                    boot_line_name: str = BOOT_LINE_NAME_DEFAULT,
                    reset_line_name: str = RESET_LINE_NAME_DEFAULT,
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
    # bin_path = Path(bin_path)
    # if not bin_path.is_absolute():
    #     # If relative, try as given; if not found and we're in a subdir, try repo root + given path
    #     if not bin_path.exists():
    #         try:
    #             repo_root = Path(subprocess.check_output(
    #                 ["git", "rev-parse", "--show-toplevel"], text=True
    #             ).strip())
    #             alt = (repo_root / bin_path)
    #             if alt.exists():
    #                 bin_path = alt
    #         except Exception:
    #             pass

    # if not bin_path.exists():
    #     raise FileNotFoundError(f"Firmware .bin not found: {bin_path}")
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
        print(f"[DFU] Using firmware: {bin_path}")
        print(f"[DFU] Entering DFU mode via {boot_line_name} (BOOT) and {reset_line_name} (RESET) ...")

    with BootReset(boot_line_name=boot_line_name,
                   reset_line_name=reset_line_name,
                   boot_active_high=BOOT_ACTIVE_HIGH,
                   reset_active_low=RESET_ACTIVE_LOW) as br:
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
        _flash_with_dfu(bin_path, flash_addr=flash_address, cwd=(Path(cwd_for_dfu) if cwd_for_dfu else None))

        if verbose:
            print("[DFU] Flash complete. Exiting DFU and rebooting into application ...")

        # Exit DFU: disable BOOT and reset
        br.set_boot_enabled(False)
        time.sleep(0.02)
        br.pulse_reset(low_ms=exit_reset_ms)

    if verbose:
        print("[DFU] Done.")

# -------------------------
# CLI entry point
# -------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="STM32 DFU updater (Pi GPIO-24=BOOT, GPIO-23=RESET).")
    p.add_argument("--bin", dest="bin_path",
                   default="LabCraft_printer/firmware/freeRTOS_LabCraft.bin",
                   help="Path to firmware .bin (default: LabCraft_printer/firmware/freeRTOS_LabCraft.bin)")
    p.add_argument("--boot", dest="boot_line_name", default=BOOT_LINE_NAME_DEFAULT,
                   help='BOOT line name (for gpiofind), default "GPIO24"')
    p.add_argument("--reset", dest="reset_line_name", default=RESET_LINE_NAME_DEFAULT,
                   help='RESET line name (for gpiofind), default "GPIO23"')
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
        boot_line_name=args.boot_line_name,
        reset_line_name=args.reset_line_name,
        dfu_vidpid=args.dfu_vidpid,
        flash_address=args.flash_address,
        enter_reset_ms=args.enter_ms,
        exit_reset_ms=args.exit_ms,
        dfu_timeout_s=args.timeout,
        cwd_for_dfu=args.cwd_for_dfu,
        verbose=not args.quiet,
    )

if __name__ == "__main__":
    main()