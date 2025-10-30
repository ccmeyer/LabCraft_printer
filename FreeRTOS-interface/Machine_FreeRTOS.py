import threading
import time
import struct
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread, QMutex, QMutexLocker
from PySide6.QtWidgets import QApplication

from dfu_update import DfuUpdateWorker, reset_board, update_firmware

from collections import deque

import serial
import re
import json
import cv2
import numpy as np
import pandas as pd
import os
import joblib
import shutil
import subprocess
import glob

try:
    from picamera2 import Picamera2
    import gpiod
except ImportError:
    print("Running on a non-Raspberry Pi system or missing required libraries. Camera and GPIO functionality will be unavailable.")
    Picamera2 = None
    gpiod = None

def _gpiofind(line_name: str):
    if shutil.which("gpiofind") is None:
        raise RuntimeError("gpiofind not found. Install it: sudo apt install gpiod")
    out = subprocess.check_output(["gpiofind", line_name], text=True).strip()
    chip_path, off = out.split()
    return chip_path, int(off)

def _open_chip(chip_name: str):
    """Open a gpiod.Chip allowing 'gpiochipX' or '/dev/gpiochipX'."""
    import gpiod
    tried = []
    for name in (chip_name, f"/dev/{chip_name}" if not chip_name.startswith("/dev/") else None):
        if not name: continue
        tried.append(name)
        try:
            return gpiod.Chip(name)
        except FileNotFoundError:
            pass
    available = " ".join(sorted(glob.glob("/dev/gpiochip*"))) or "<none>"
    raise FileNotFoundError(f"Could not open GPIO chip {chip_name!r}. Tried {tried}. "
                            f"Available chips: {available}")
    
def _make_output_line(chip_name, offset, initial=0, consumer="gpio_out"):
    """
    Return an object with .set_value(v:int) and .release()
    that works across libgpiod v1 and v2.
    """
    try:
        import gpiod
    except Exception as e:
        # No GPIO available: return a no-op stub
        class _Null:
            def set_value(self, v): pass
            def release(self): pass
        return _Null()

    is_v2 = hasattr(gpiod, "line")  # v2 has the 'line' namespace

    if is_v2:
        print("Using gpiod v2 API, making output line")
        chip = _open_chip(chip_name)
        ls = gpiod.LineSettings()
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
        print("Using gpiod v1 API, making output line")
        chip = _open_chip(chip_name)
        line = chip.get_line(offset)
        line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT, default_vals=[initial])
        class OutV1:
            def set_value(self, v: int):
                line.set_value(1 if v else 0)
            def release(self):
                line.release()
        return OutV1()

def _make_rising_edge_input(chip_name, offset, consumer="gpio_in"):
    """
    Returns an object with:
      .event_wait(timeout_s: float) -> bool
      .event_consume() -> None
      .release() -> None
    Works with libgpiod v1 and v2.
    """
    try:
        import gpiod
    except Exception:
        # No GPIO available: return a no-op stub that always times out
        class _NullIn:
            def event_wait(self, timeout): return False
            def event_consume(self): pass
            def release(self): pass
        return _NullIn()

    is_v2 = hasattr(gpiod, "line")

    if is_v2:
        print("Using gpiod v2 API, making rising edge input line")
        chip = _open_chip(chip_name)
        ls = gpiod.LineSettings()
        Direction = gpiod.line.Direction
        Edge      = gpiod.line.Edge
        Bias      = getattr(gpiod.line, "Bias", None)

        ls.direction      = Direction.INPUT
        ls.edge_detection = Edge.RISING
        if Bias is not None:
            try: ls.bias = Bias.PULL_DOWN
            except Exception: pass

        req = chip.request_lines(consumer=consumer, config={offset: ls})

        class InV2:
            def event_wait(self, timeout):
                return req.wait_edge_events(timeout)
            def event_consume(self):
                _ = req.read_edge_events()
            def release(self):
                req.release()
        return InV2()

    else:
        print("Using gpiod v1 API, making rising edge input line")
        chip = _open_chip(chip_name)
        line = chip.get_line(offset)
        flags = 0
        if hasattr(gpiod, "LINE_REQ_FLAG_BIAS_PULL_DOWN"):
            flags |= gpiod.LINE_REQ_FLAG_BIAS_PULL_DOWN
        line.request(consumer=consumer, type=gpiod.LINE_REQ_EV_RISING_EDGE, flags=flags)

        class InV1:
            def event_wait(self, timeout):
                return line.event_wait(timeout)
            def event_consume(self):
                _ = line.event_read()
            def release(self):
                line.release()
        return InV1()

# ---------- DropletCamera: grabber-driven flash detection with time gating ----------

class DropletCamera(QObject):
    image_captured_signal = Signal()
    capture_failed_signal = Signal(str)  # emits error message on failure

    def __init__(self):
        super().__init__()
        # >>> wiring <<<
        self.trigger_pin_out_bcm = 17   # Pi -> MCU trigger
        self.flash_fired_in_bcm  = 22   # MCU -> Pi flash-ack

        # self._chip_name = "gpiochip4"
        self._trig_chip_name, off = _gpiofind("GPIO"+str(self.trigger_pin_out_bcm))
        self._trig_line = _make_output_line(self._trig_chip_name, off, initial=0)
        self._flash_chip_name, off = _gpiofind("GPIO"+str(self.flash_fired_in_bcm))
        self._edge_in   = _make_rising_edge_input(self._flash_chip_name, off)

        # camera
        self.camera = None
        self.exposure_time = 20_000  # us
        self.latest_frame = None

        # ring buffer of recent frames: (arr, md, t_done_ns, mean)
        self._buf = deque(maxlen=16)

        # grabber thread + state
        self._lock = threading.Lock()
        self._cv   = threading.Condition(self._lock)
        self._grab_thread = None
        self._grab_running = False

        # capture state (all under _lock)
        self._cap_active      = False
        self._cap_id          = 0
        self._cap_deadline    = 0.0
        self._cap_max_new     = 6     # allow up to 6 post-arm frames
        self._cap_seen        = 0
        self._cap_threshold   = 9999.0
        self._cap_brightest   = None  # among post-arm frames
        self._cap_emit_rotate = True
        self._cap_arm_ns      = 0     # <<< time gate: frames with t_done_ns > arm_ns are "new"
        
        self._cap_done = threading.Event()      # set when _complete_capture_locked runs
        self._cap_result = None                 # dict with mean/threshold/reason, and the image
        self._emit_on_complete = True           # gate emitting during retries
        
        # threshold tuning
        self.k_sigma   = 4.0
        self.min_delta = 25.0
        self.max_wait_s = 1.0

    # --- GPIO ---
    def _trigger_high(self): 
        # print("[Pi] trigger HIGH")
        self._trig_line.set_value(1)
    def _trigger_low(self): 
        # print("[Pi] trigger LOW")
        self._trig_line.set_value(0)

    # --- camera lifecycle ---
    def start_camera(self):
        self.camera = Picamera2(1)
        vid_cfg = self.camera.create_video_configuration(
            main={"size": self.camera.sensor_resolution, "format": "RGB888"},
            buffer_count=3
        )
        self.camera.configure(vid_cfg)
        self.camera.set_controls({
            "FrameDurationLimits": (self.exposure_time, self.exposure_time),
            "ExposureTime": self.exposure_time,
            "AeEnable": False,
            "AwbEnable": False,
            "AnalogueGain": 1.0,
        })
        self.camera.start()

        self._grab_running = True
        self._grab_thread = threading.Thread(target=self._grabber, daemon=True)
        self._grab_thread.start()

    def stop_camera(self):
        self._grab_running = False
        if self._grab_thread:
            self._grab_thread.join(timeout=1.0)
            self._grab_thread = None
        if self.camera:
            self.camera.stop()
            self.camera.close()
            self.camera = None
        self._trigger_low()

    def change_exposure_time(self, exposure_time_us, handler=None):
        self.exposure_time = int(exposure_time_us)
        if self.camera:
            self.camera.set_controls({
                "FrameDurationLimits": (self.exposure_time, self.exposure_time),
                "ExposureTime": self.exposure_time,
                "AeEnable": False,
                "AwbEnable": False,
            })
        if handler:
            handler()

    # --- grabber (sole consumer of capture_request) ---
    def _grabber(self):
        while self._grab_running and self.camera:
            req = self.camera.capture_request()
            if req is None:
                continue
            t_done_ns = time.monotonic_ns()  # completion time (local monotonic)
            try:
                md  = req.get_metadata()
                arr = req.make_array("main")
            finally:
                req.release()
            mean = float(np.mean(arr))
            # print(f"{mean}")  # your debug

            with self._cv:
                self._buf.append((arr, md, t_done_ns, mean))

                if self._cap_active:
                    # time-gated: only evaluate frames strictly after arming time
                    if t_done_ns > self._cap_arm_ns:
                        self._cap_seen += 1

                        # track brightest among post-arm frames
                        if (self._cap_brightest is None) or (mean > self._cap_brightest[3]):
                            self._cap_brightest = (arr, md, t_done_ns, mean)

                        # first above-threshold wins
                        if mean >= self._cap_threshold:
                            print(f"[Capture] cap_id={self._cap_id} mean={mean:.1f} thr={self._cap_threshold:.1f}")
                            self._complete_capture_locked(arr, md, mean, reason="threshold")
                        elif (self._cap_seen >= self._cap_max_new) or (time.monotonic() > self._cap_deadline):
                            # fallback to brightest seen post-arm
                            if self._cap_brightest is not None:
                                b_arr, b_md, _b_t, b_mean = self._cap_brightest
                                self._complete_capture_locked(b_arr, b_md, b_mean, reason="fallback")
                            else:
                                self._complete_capture_locked(arr, md, mean, reason="last_resort")

                self._cv.notify_all()

    # --- finalize one capture ---
    def _complete_capture_locked(self, arr, md, mean, reason):
        self._cap_active = False
        self._trigger_low()  # drop trigger now that we have a frame

        if self._cap_emit_rotate:
            arr = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)

        self.latest_frame = arr
        self._cap_result = {
            "arr": arr,
            "md": md,
            "mean": float(mean),
            "reason": str(reason),
            "threshold": float(self._cap_threshold),
            "cap_id": int(self._cap_id),
        }
        self._cap_done.set()
        # print(f"[Chosen] mean={mean:.1f} reason={reason} "
        #       f"Exp(us)={md.get('ExposureTime') if md else None} "
        #       f"FrameDur(us)={md.get('FrameDuration') if md else None}")

        # Only emit if allowed (wrappers will re-emit after a successful retry)
        if self._emit_on_complete:
            self.image_captured_signal.emit()
        # # Emit from grabber thread (Qt will deliver safely)
        # self.image_captured_signal.emit()

    # --- helpers ---
    def _baseline_before_ns_locked(self, cutoff_ns, N=4):
        """Compute baseline mean/std from the last up-to-N frames with t_done_ns < cutoff_ns."""
        vals = []
        for arr, md, t_done_ns, mean in reversed(self._buf):
            if t_done_ns < cutoff_ns:
                vals.append(mean)
                if len(vals) >= N:
                    break
        if len(vals) < 2:
            tail = [m for (_a,_m,_t,m) in list(self._buf)[-N:]]
            vals = tail if tail else [0.0, 0.0]
        vals = np.array(vals, dtype=float)
        return float(np.mean(vals)), float(np.std(vals))

    # --- public API ---
    def get_latest_frame(self):
        return self.latest_frame

    def capture_non_blocking(self, max_new_frames=6, timeout_s=1, *, emit_signal=True):
        """
        Arms a single attempt. The grabber will complete it and either emit
        image_captured_signal (if emit_signal=True) or just set _cap_result/_cap_done.
        """
        if not self.camera:
            print("Camera not started.")
            return

        # Drain stale edges from previous runs
        while self._edge_in.event_wait(0):
            self._edge_in.event_consume()

        # Raise trigger to MCU
        self._trigger_high()

        # Wait for MCU "flash fired" ACK
        if not self._edge_in.event_wait(timeout_s):
            print("Timed out waiting for flash-fired edge.")
            self._trigger_low()
            with self._cv:
                self._cap_active = False
                self._cap_result = {"arr": None, "md": None, "mean": 0.0,
                                    "reason": "edge_timeout", "threshold": 0.0, "cap_id": self._cap_id}
                self._cap_done.set()
            return
        self._edge_in.event_consume()

        # Immediately deassert trigger to avoid EXTI re-notifications while high
        self._trigger_low()

        # Arm the time gate AFTER the ack
        arm_ns = time.monotonic_ns()
        with self._cv:
            base_mean, base_std = self._baseline_before_ns_locked(arm_ns, N=4)
            threshold = base_mean + self.k_sigma * max(base_std, 1.0) + self.min_delta
            threshold = min(threshold, 150.0)

            self._cap_id         += 1
            self._cap_active      = True
            self._cap_arm_ns      = arm_ns
            self._cap_deadline    = time.monotonic() + timeout_s
            self._cap_max_new     = max_new_frames
            self._cap_seen        = 0
            self._cap_threshold   = threshold
            self._cap_brightest   = None
            self._emit_on_complete = bool(emit_signal)

            self._cap_done.clear()
            self._cap_result = None

            print(f"[Arm] cap_id={self._cap_id} base_mean={base_mean:.1f} "
                f"base_std={base_std:.1f} threshold={threshold:.1f} arm_ns={arm_ns}")
            
    def capture_with_retry_sync(
        self,
        attempts=3,
        *,
        max_new_frames=6,
        attempt_timeout_s=1,
        small_sleep_between=0.02,
    ) -> np.ndarray:
        """
        Block until we get a 'threshold' capture or exhaust attempts.
        Returns the final image (numpy array) on success.
        Raises RuntimeError on failure.
        """
        last_reason = None

        for i in range(attempts):
            # For each attempt, suppress automatic emission; we'll emit once on success.
            self.capture_non_blocking(max_new_frames=max_new_frames,
                                    timeout_s=attempt_timeout_s,
                                    emit_signal=False)

            # Wait for the grabber to select a frame or report edge timeout.
            # Allow a tiny grace beyond attempt_timeout_s to cover scheduling jitter.
            waited = self._cap_done.wait(attempt_timeout_s + 0.2)
            if not waited:
                last_reason = "attempt_timeout"
                print(f"[Retry] attempt {i+1}/{attempts} timed out waiting for completion")
            else:
                res = self._cap_result or {}
                last_reason = res.get("reason", "unknown")
                print(f"[Retry] attempt {i+1}/{attempts} result reason={last_reason} "
                    f"mean={res.get('mean')} thr={res.get('threshold')}")

                # success criterion: first frame that *crossed* threshold
                if last_reason == "threshold" and self.latest_frame is not None:
                    # emit once here for compatibility with existing slots
                    self.image_captured_signal.emit()
                    return self.latest_frame

            # not acceptable → try again unless we’re out of attempts
            if i < attempts - 1:
                time.sleep(small_sleep_between)

        # all attempts failed: signal and error
        msg = f"Flash capture failed after {attempts} attempts (last_reason={last_reason})"
        self.capture_failed_signal.emit(msg)
        raise RuntimeError(msg)
    
    def capture_with_retry_async(
        self,
        attempts=5,
        *,
        max_new_frames=10,
        attempt_timeout_s=1.0,
        small_sleep_between=0.05,
    ):
        """
        Start a capture with internal retries. On success, emits image_captured_signal once.
        On failure, emits capture_failed_signal(str). Returns immediately.
        """
        def _runner():
            try:
                self.capture_with_retry_sync(
                    attempts=attempts,
                    max_new_frames=max_new_frames,
                    attempt_timeout_s=attempt_timeout_s,
                    small_sleep_between=small_sleep_between,
                )
                # success path already emitted image_captured_signal inside sync wrapper
            except Exception as e:
                # already emitted capture_failed_signal inside sync wrapper,
                # but in case of other errors, emit here too
                self.capture_failed_signal.emit(str(e))

        t = threading.Thread(target=_runner, daemon=True)
        t.start()

class RefuelCamera(QObject):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.led_pin = 27
        # self._chip_name = "gpiochip4"  # adjust if needed on your Pi
        self._chip_name, off = _gpiofind("GPIO"+str(self.led_pin))
        # v1/v2 compatible output line
        self._led = _make_output_line(self._chip_name, off,
                                             initial=0, consumer="refuel_led")

    def start_camera(self):
        from picamera2 import Picamera2
        self.camera = Picamera2(0)
        self.camera.configure(self.camera.create_still_configuration(
            main={"size": self.camera.sensor_resolution, "format": "RGB888"}
        ))
        self.camera.start()

    def capture_image(self):
        return self.camera.capture_array() if self.camera else None

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera.close()
            self.camera = None
        # ensure LED off on stop
        try: self._led.set_value(0)
        except Exception: pass

    def led_on(self):
        print("---LED ON")
        self._led.set_value(1)

    def led_off(self):
        print("---LED OFF")
        self._led.set_value(0)

    def __del__(self):
        try:
            self._led.set_value(0)
            self._led.release()
        except Exception:
            pass


START_BYTE = 0xAA
CMD_STATUS = 0x02
CLEAR_QUEUE = 0xF2
HELLO       = 0xF3
HELLO_ACK   = 0xF4
GOODBYE     = 0xF5
BYE_ACK     = 0xF6
CLEAR_ACK   = 0xF7
BYE_DONE    = 0xF8

# TLV tag constants; must match firmware
TAG_LED_TOTAL     = 0x10
TAG_LED_REMAIN    = 0x11
TAG_PRINT_P       = 0x12
TAG_REFUEL_P      = 0x13
TAG_TAR_PRINT_P   = 0x14
TAG_TAR_REFUEL_P  = 0x15
TAG_X_POS         = 0x20
TAG_Y_POS         = 0x21
TAG_Z_POS         = 0x22
TAG_P_POS         = 0x23
TAG_R_POS         = 0x24
TAG_TAR_X_POS      = 0x25
TAG_TAR_Y_POS      = 0x26
TAG_TAR_Z_POS      = 0x27
TAG_TAR_P_POS      = 0x28
TAG_TAR_R_POS      = 0x29
TAG_DROP_TOTAL    = 0x30
TAG_DROP_REMAIN   = 0x31
TAG_PRINT_PW     = 0x32
TAG_REFUEL_PW    = 0x33
TAG_DISP_FREQ     = 0x34
TAG_ACTIVE_P      = 0x40
TAG_ACTIVE_R      = 0x41
TAG_CMD_DEPTH     = 0x50
TAG_LAST_CMD      = 0x51
TAG_CURR_CMD     = 0x52
TAG_FLASH_NUM	   = 0x60
TAG_FLASH_WIDTH   = 0x61
TAG_FLASH_DELAY   = 0x62
TAG_FLASH_DROPS   = 0x63
TAG_EXT_COUNTER   = 0x64
TAG_X_MAX_HZ      = 0x70
TAG_Y_MAX_HZ      = 0x71
TAG_Z_MAX_HZ      = 0x72
TAG_X_ACCEL       = 0x73
TAG_Y_ACCEL       = 0x74
TAG_Z_ACCEL       = 0x75
TAG_GRIP_PULSE    = 0x80
TAG_GRIP_REFRESH  = 0x81

# Map tags → (field name, length_in_bytes, signed?)
TAG_MAP = {
    TAG_LED_TOTAL:    ("led_total",    2, False),
    TAG_LED_REMAIN:   ("led_remain",   2, False),
    TAG_PRINT_P:      ("Pressure_P",2, False),
    TAG_REFUEL_P:     ("Pressure_R",2,False),
    TAG_TAR_PRINT_P:  ("Tar_print",2, False),
    TAG_TAR_REFUEL_P: ("Tar_refuel",2, False),
    TAG_X_POS:        ("X",        4, True),
    TAG_Y_POS:        ("Y",        4, True),
    TAG_Z_POS:        ("Z",        4, True),
    TAG_P_POS:        ("P",        4, True),
    TAG_R_POS:        ("R",        4, True),
    TAG_TAR_X_POS:    ("Tar_X", 4, True),
    TAG_TAR_Y_POS:    ("Tar_Y", 4, True),
    TAG_TAR_Z_POS:    ("Tar_Z", 4, True),
    TAG_TAR_P_POS:    ("Tar_P", 4, True),
    TAG_TAR_R_POS:    ("Tar_R", 4, True),
    TAG_DROP_TOTAL:   ("drop_total",   4, False),
    TAG_DROP_REMAIN:  ("drop_remain",  4, False),
    TAG_PRINT_PW:     ("Print_width",  2, False),
    TAG_REFUEL_PW:    ("Refuel_width", 2, False),
    TAG_ACTIVE_P:     ("print_active", 2, False),
    TAG_ACTIVE_R:     ("refuel_active",2, False),

    TAG_FLASH_NUM:    ("Flashes", 4, False),
    TAG_FLASH_WIDTH:  ("Flash_width", 4, False),
    TAG_FLASH_DELAY:  ("Flash_delay", 4, False),
    TAG_FLASH_DROPS:  ("Flash_droplets", 2, False),
    TAG_EXT_COUNTER:  ("Ext_counter", 4, False),

    TAG_GRIP_PULSE:    ("Grip_pulse", 4, False),
    TAG_GRIP_REFRESH:  ("Grip_refresh", 4, False),

    TAG_X_MAX_HZ:     ("X_max_hz", 4, False),
    TAG_Y_MAX_HZ:     ("Y_max_hz", 4, False),
    TAG_Z_MAX_HZ:     ("Z_max_hz", 4, False),
    TAG_X_ACCEL:      ("X_accel", 4, False),
    TAG_Y_ACCEL:      ("Y_accel", 4, False),
    TAG_Z_ACCEL:      ("Z_accel", 4, False),

    TAG_CMD_DEPTH:    ("cmd_depth",  4, False),
    TAG_LAST_CMD:     ("Last_completed", 4, False),
    TAG_CURR_CMD:     ("Current_command", 4, False),
}

CMD_MAP = {
    'RELATIVE_X': 0x02,
    'RELATIVE_Y': 0x03,
    'RELATIVE_Z': 0x04,
    'HOME_X': 0x05,
    'HOME_Y': 0x06,
    'HOME_Z': 0x07,
    'ENABLE_MOTORS': 0x08,
    'DISABLE_MOTORS': 0x09,
    'ABSOLUTE_X': 0x0A,
    'ABSOLUTE_Y': 0x0B,
    'ABSOLUTE_Z': 0x0C,
    'RELATIVE_XY': 0x0D,
    'ABSOLUTE_XY': 0x0E,

    'OPEN_GRIPPER': 0x10,
    'CLOSE_GRIPPER': 0x11,
    'GRIPPER_OFF': 0x12,

    'DISPENSE': 0x22,
    'DISPENSE_PRINT': 0x23,
    'DISPENSE_REFUEL': 0x24,

    'LED_ON': 0x30,
    'LED_OFF': 0x31,

    'SET_AXIS_MAXSPEED': 0x40,
    'SET_AXIS_ACCEL': 0x41,
    'SET_AXIS_PROFILE': 0x42,

    'HOME_XY' : 0x43,
	'HOME_PR_BOTH' : 0x44,

    'WAIT': 0x50,
    'CHANGE_ACCEL': 0x51,

    'ENABLE_PRINT_PROFILE': 0x60,
    'DISABLE_PRINT_PROFILE': 0x61,

    'SET_GRIPPER_PARAMS': 0x70,

    'START_READ_CAMERA': 0xC0,
    'STOP_READ_CAMERA': 0xC1,
    'SET_WIDTH_F' : 0xC2,
    'SET_DELAY_F': 0xC3,
    'SET_IMAGE_DROPLETS': 0xC4,

    'SET_WIDTH_P': 0XD0,
    'SET_WIDTH_R': 0xD1,
    
    'ABSOLUTE_PRESSURE_P': 0xE0,
    'ABSOLUTE_PRESSURE_R': 0xE1,
    'HOME_PRINT': 0xE2,
    'HOME_REFUEL': 0xE3,
    'REGULATE_PRESSURE_P': 0xE8,
    'DEREGULATE_PRESSURE_P': 0xE9,
    'REGULATE_PRESSURE_R': 0xEA,
    'DEREGULATE_PRESSURE_R': 0xEB,
    'RELATIVE_PRESSURE_P': 0xEC,
    'RELATIVE_PRESSURE_R': 0xED,
    'RESET_P': 0xEE,
    'RESET_R': 0xEF,

    'PAUSE': 0xF0,
    'RESUME': 0xF1,
    'CLEAR_QUEUE': 0xF2,
    'HELLO'       : 0xF3,
    'HELLO_ACK'   : 0xF4,
    'GOODBYE'     : 0xF5,
    'BYE_ACK'     : 0xF6,
    'CLEAR_ACK'   : 0xF7,
    'BYE_DONE'    : 0xF8
}

def crc16_x25(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def build_frame(cmd, seq32):
    TAG_SEQ32 = 0x10
    seq8 = seq32 & 0xFF
    payload = bytearray([cmd & 0xFF, seq8])
    # SEQ32 TLV
    payload += bytes([TAG_SEQ32, 4]) + struct.pack("<I", seq32 & 0xFFFFFFFF)
    header  = bytes([START_BYTE, len(payload)])
    c       = crc16_x25(payload)
    tail    = struct.pack("<H", c)
    return header + payload + tail

def parse_tlv_payload(payload: bytes) -> dict:
    """
    Walk the payload as tag‐len‐value, return a dict name->value.
    Unknown tags are skipped.
    """
    idx = 0
    result = {}
    while idx + 2 <= len(payload):
        tag    = payload[idx];    idx += 1
        length = payload[idx];    idx += 1
        if idx + length > len(payload):
            break  # malformed/truncated
        raw = payload[idx:idx+length]
        idx += length

        entry = TAG_MAP.get(tag)
        if not entry:
            continue  # unknown tag
        name, expected_len, signed = entry
        if expected_len != length:
            # length mismatch; skip or handle as error
            continue

        value = int.from_bytes(raw, byteorder="little", signed=signed)
        result[name] = value

    return result

class SerialReader(QThread):
    status_received = Signal(dict)
    ackReceived     = Signal(object)  # dict with ack_cmd, seq8, seq32

    def __init__(self, ser, parent=None):
        super().__init__(parent)
        self.ser = ser
        
    @staticmethod
    def _parse_ack(payload: bytes) -> dict:
        """
        payload layout: [ack_cmd, seq8, (TLVs...)]
        We only care about TAG_SEQ32 (0x10, len=4, LE)
        """
        TAG_SEQ32 = 0x10

        ack_cmd = payload[0]
        seq8 = payload[1] if len(payload) >= 2 else 0
        seq32 = None
        i = 2
        while i + 1 < len(payload):
            tag = payload[i]; ln = payload[i+1]; i += 2
            if i + ln > len(payload):
                break
            if tag == TAG_SEQ32 and ln == 4:
                seq32 = struct.unpack_from("<I", payload, i)[0]
            i += ln
        return {"ack_cmd": ack_cmd, "seq8": seq8, "seq32": seq32}


    def run(self):
        while not self.isInterruptionRequested():
            try:
                if not self.ser or not self.ser.is_open:
                    break
                hdr = self.ser.read(2)
                if len(hdr)!=2 or hdr[0]!=START_BYTE: continue
                length = hdr[1]
                payload = self.ser.read(length)
                if len(payload) != length: continue
                tail = self.ser.read(2)
                if len(tail) != 2: continue
                rec_crc = tail[0] | (tail[1]<<8)
                if crc16_x25(payload)!=rec_crc: continue

                cmd = payload[0]
                if cmd == CMD_STATUS:
                    data = parse_tlv_payload(payload[1:])
                    self.status_received.emit(data)
                else:
                    # HELLO_ACK, BYE_ACK, CLEAR_ACK, etc
                    # print(f"Non-status frame: cmd=0x{cmd:02X}, len={length}")
                    ack = self._parse_ack(payload)
                    print(f"Ack received: {ack['ack_cmd']} seq8={ack['seq8']} seq32={ack['seq32']}")
                    self.ackReceived.emit(ack)

            except (serial.SerialException, OSError, TypeError, ValueError):
                break

    def stop(self):
        # helper to mirror LogReader.stop()
        self.requestInterruption()
        try:
            if hasattr(self.ser, "cancel_read"):
                self.ser.cancel_read()
        except Exception:
            pass
        self.wait(1000)

class LogReader(QThread):
    lineReceived   = Signal(str)     # existing
    statsUpdated   = Signal(object)  # emits a dict with parsed stats (see below)
    messageReceived = Signal(str)
    

    def __init__(self, baud=115200, parent=None, log_port="/dev/ttyUSB0", history_len=360):
        super().__init__(parent)
        self.ser = serial.Serial(log_port, baud, timeout=1)
        self._running = True
        self._in_stats = False
        self._stats_block = []
        self.last_stats = None
        self.stats_history = deque(maxlen=history_len)  # ~18 minutes if MCU prints every 3s
        # regex: <task><spaces><time><spaces><percent?> (percent may be absent or have a % sign)
        self._stats_re = re.compile(
            r'^\s*(?P<task>.+?)\s+(?P<time>\d+)\s+<?(?P<pct>\d+(?:\.\d+)?)?%?\s*$'
        )

        self.message_history = deque(maxlen=2000)  # NEW: keep up to 2000 recent messages
        self._level_re = re.compile(r'^\s*\[(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)\]\s*(.*)$', re.I)

        print(f"LogReader initialized on {log_port} at {baud} baud")

    # ---------- public helpers for UI/controllers ----------
    def get_recent_messages(self):
        """Return a list of dicts: {'ts': float, 'text': str, 'level': Optional[str]}"""
        return list(self.message_history)

    def clear_messages(self):
        self.message_history.clear()

    def get_latest_stats(self):
        """Return the most recently parsed stats dict or None."""
        return self.last_stats

    def get_task_percent(self, task_name: str):
        """Convenience helper to fetch a single task's %."""
        if not self.last_stats:
            return None
        entry = self.last_stats["by_task"].get(task_name)
        return None if not entry else entry["percent"]

    def get_idle_percent(self):
        """Convenience helper for IDLE %."""
        return None if not self.last_stats else self.last_stats["idle_percent"]

    # ---------- thread loop ----------
    def run(self):
        """Continuously read lines and emit them + parse stats blocks."""
        while self._running:
            try:
                if not self.ser or not self.ser.is_open:
                    break

                line = self.ser.read_until(expected=b'\n', size=1024)
                # line = self.ser.readline()
                if not line:
                    continue
                text = line.decode('ascii', errors="ignore").rstrip("\r\n")
                # Always emit raw line for anything else listening
                self.lineReceived.emit(text)

                # Detect start of a stats block
                if text.strip() == "===LOG===":
                    self._in_stats = True
                    self._stats_block = []
                    continue

                # Accumulate stats lines until a blank line or next marker
                if self._in_stats:
                    if text.strip() == "" or text.strip() == "===LOG===":
                        # end of block (or a nested marker)
                        self._finish_stats_block()
                        # if it was a nested marker, keep collecting a new one
                        if text.strip() == "===LOG===":
                            self._in_stats = True
                            self._stats_block = []
                        else:
                            self._in_stats = False
                    else:
                        self._stats_block.append(text)

                # Outside of stats: treat as a normal log message
                elif text.strip():
                    self._record_message(text)

            except (serial.SerialException, OSError, TypeError, ValueError):
                break

    def stop(self):
        # Signal loop to stop
        self._running = False
        try:
            # Unblock any pending read so the thread can exit immediately
            if hasattr(self.ser, "cancel_read"):
                self.ser.cancel_read()
        except Exception:
            pass

        # give the thread time to unwind out of run()
        self.wait(1000)

        # Close port last
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    # ---------- parsing ----------
    def _finish_stats_block(self):
        """Parse the accumulated lines in self._stats_block and emit statsUpdated."""
        lines = self._stats_block
        rows = []
        times = []

        # Common headers/separators to ignore (robust to different FreeRTOS prints)
        def _is_header_or_sep(s: str) -> bool:
            s_stripped = s.strip().lower()
            if not s_stripped:
                return True
            if set(s_stripped) <= set("-=|+ "):
                return True
            # Typical FreeRTOS header contains 'task' and 'time'
            if ("task" in s_stripped and "time" in s_stripped) or "%" in s_stripped and "task" in s_stripped:
                return True
            return False

        for ln in lines:
            if _is_header_or_sep(ln):
                continue
            m = self._stats_re.match(ln)
            if not m:
                # Unrecognized line inside stats block; ignore gracefully
                continue
            task = m.group("task").strip()
            t = int(m.group("time"))
            pct_str = m.group("pct")
            pct = float(pct_str) if pct_str is not None else None
            rows.append({"task": task, "time": t, "percent": pct})
            times.append(t)

        by_task = {r["task"]: r for r in rows}
        idle_percent = by_task.get("IDLE", {}).get("percent")

        stats = {
            "raw": "\n".join(lines),
            "rows": rows,
            "by_task": by_task,
            "idle_percent": idle_percent,
            "ts": time.time(),
        }

        self.last_stats = stats
        self.stats_history.append(stats)
        self.statsUpdated.emit(stats)

    def _record_message(self, text: str):
        level = None
        m = self._level_re.match(text)
        if m:
            level = m.group(1).upper()
            text  = m.group(2)
        entry = {"ts": time.time(), "text": text, "level": level}
        self.message_history.append(entry)
        self.messageReceived.emit(entry["text"])

# class LogReader(QThread):
#     lineReceived = Signal(str)

#     def __init__(self, baud=115200, parent=None):
#         super().__init__(parent)
#         log_port = "/dev/ttyUSB0"
#         self.ser = serial.Serial(log_port, baud, timeout=1)
#         self._running = True
#         print(f"LogReader initialized on {log_port} at {baud} baud")

#     def run(self):
#         """Continuously read lines and emit them."""
#         while self._running:
#             try:
#                 line = self.ser.readline()
#                 if line:
#                     text = line.decode('ascii',errors="ignore").rstrip("\r\n")
#                     print(f"Log line received: {text}")
#                     self.lineReceived.emit(text)
#             except serial.SerialException:
#                 break
    
#     def stop(self):
#         self._running = False
#         self.wait(200)
#         if self.ser.is_open:
#             self.ser.close()

class Command:
    """
    Represents a command to be sent to the machine.
    
    Attributes:
    command_number (int): The number of the command.
    command_type (str): The type of the command.
    param1: The first parameter of the command.
    param2: The second parameter of the command.
    param3: The third parameter of the command.
    handler (function, optional): The handler function for the command.
    kwargs (dict, optional): Additional keyword arguments for the handler function.
    """

    TAG_P1 = 0x01
    TAG_P2 = 0x02
    TAG_P3 = 0x03
    TAG_SEQ32 = 0x10

    def __init__(self, command_number, command_type, param1, param2, param3,
                 handler=None, kwargs=None):
        self.command_number = int(command_number)
        self.seq8 = self.command_number & 0xFF
        self.command_type   = command_type
        self.command_code   = CMD_MAP[command_type]
        self.param1 = int(param1)
        self.param2 = int(param2)
        self.param3 = int(param3)

        # — build TLV payload —
        p = bytearray()
        # 1) cmd byte + seq
        p.append(self.command_code & 0xFF)
        p.append(self.seq8 & 0xFF)

        # SEQ32 TLV (little-endian)
        p.append(self.TAG_SEQ32); p.append(4)
        p.extend(struct.pack("<I", self.command_number & 0xFFFFFFFF))

        for tag, val in ((self.TAG_P1, self.param1),
                 (self.TAG_P2, self.param2),
                 (self.TAG_P3, self.param3)):
            p.append(tag)
            p.append(4)
            p.extend(struct.pack("<I", val & 0xFFFFFFFF))

        self.payload = bytes(p)

        # 2) wrap in header/CRC/footer
        self.header = bytes([START_BYTE, len(self.payload)])
        self.crc    = crc16_x25(self.payload)
        self.tail   = struct.pack("<H", self.crc)
        self.frame  = self.header + self.payload + self.tail

        # other metadata...
        self.status = "Added"
        self.timestamp = time.time()
        self.handler   = handler
        self.kwargs    = kwargs or {}
        self.signal = f'<{command_type} {self.command_number} {param1},{param2},{param3}>'


    def mark_as_sent(self):
        self.status = "Sent"

    def mark_as_executing(self):
        self.status = "Executing"

    def mark_as_completed(self):
        self.status = "Completed"
        self.execute_handler()

    def get_number(self):
        return self.command_number

    def get_command(self):
        return self.signal

    def get_timestamp(self):
        return self.timestamp

    def execute_handler(self):
        if self.handler is not None:
            self.handler(**self.kwargs)


class CommandQueue(QObject):
    """
    Represents a queue of commands to be sent to the machine.
    Uses deque to store the commands.
    Completed commands are transferred to the completed queue.
    """
    queue_updated = Signal()  # Signal to emit when the queue is updated
    commands_completed = Signal()  # Signal to emit when all commands are completed

    def __init__(self):
        super().__init__()  # Initialize the QObject
        self.queue = deque()
        self.completed = deque()
        self.command_number = 0
        self.max_sent_commands = 8  # Maximum number of commands that can be sent to the machine at once

    def add_command(self, command_type, param1, param2, param3, handler=None, kwargs=None):
        """Add a command to the queue."""
        
        
        self.command_number += 1
        # print(f'type params: {self.command_number}-{command_type} {type(param1)} {type(param2)} {type(param3)}')
        #print(f'Adding command: {command_type} {param1} {param2} {param3}')
        command = Command(self.command_number, command_type, param1, param2, param3, handler, kwargs)
        self.queue.append(command)
        return command

    def get_number_of_sent_commands(self):
        """Returns the number of commands that have been sent to the machine."""
        return len([command for command in self.queue if command.status == "Sent"])

    def get_next_command(self):
        """Send the next command to the machine if the buffer allows."""
        if self.queue and self.get_number_of_sent_commands() < self.max_sent_commands:
            for command in self.queue:
                if command.status == "Added":
                    command.mark_as_sent()
                    return command
        return None
    
    def update_command_status(self, current_executing_command, last_completed_command):
        if current_executing_command is None and last_completed_command is None:
            return

        curr = int(current_executing_command or -1)
        last = int(last_completed_command  or -1)

        # 1) Complete everything <= last (this is the main truth)
        for cmd in list(self.queue):
            if cmd.status in ("Sent", "Executing") and cmd.command_number <= last:
                cmd.mark_as_completed()

        # 2) Optionally mark one command in (last, curr] as Executing
        #    (if multiple were executed between status ticks, this might be empty)
        if curr >= 0 and curr > last:
            # pick the smallest Sent command > last
            cand = None
            for cmd in self.queue:
                if cmd.status == "Sent" and last < cmd.command_number <= curr:
                    cand = cmd
                    break
            if cand:
                cand.mark_as_executing()

        # Trim completed
        while self.queue and self.queue[0].status == "Completed":
            completed_command = self.queue.popleft()
            self.completed.append(completed_command)
            if len(self.completed) > 100:
                self.completed.popleft()

        if not self.queue:
            self.commands_completed.emit()

        self.queue_updated.emit()

    def clear_queue(self):
        """Clear the command queue."""
        self.queue.clear()
        self.completed.clear()
        self.command_number = 0
        self.queue_updated.emit()

class Machine(QObject):
    """
    Class for the machine object. This class is responsible for 
    sending and receiving data from the machine and organizing
    the command queue.
    """
    status_updated = Signal(dict)  # Signal to emit status updates
    command_sent = Signal(dict)    # Signal to emit when a command is sent
    error_occurred = Signal(str)   # Signal to emit errors
    homing_completed = Signal()    # Signal to emit when homing is completed
    gripper_open = Signal()      # Signal to emit when the gripper is opened
    gripper_closed = Signal()    # Signal to emit when the gripper is closed
    gripper_on_signal = Signal()        # Signal to emit when the gripper is turned on
    gripper_off_signal = Signal()       # Signal to emit when the gripper is turned off
    disconnect_complete_signal = Signal()  # Signal to stop timers
    machine_connected_signal = Signal(bool)  # Signal to emit when the machine is connected
    all_calibration_droplets_printed = Signal()  # Signal to emit when all calibration droplets are printed
    require_gripper_confirmation = Signal(str)   # "OPEN" or "CLOSE"
    log_stats_updated = Signal(object)  # Signal to emit when log stats are updated
    log_message_received = Signal(str)  # Signal to emit when a log message is received

    def __init__(self,model):
        super().__init__()
        self.command_queue = CommandQueue()
        self.baud = 115200  # Default baud rate for serial communication
        self.ser = None
        self.reader = None
        
        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

        self.execution_timer = None
        self.sent_command = None

        # ack_code -> {"timer": QTimer, "ok": callable, "to": callable}
        self._pending_acks = {}
        self._next_ctl_seq32 = 1          # for out-of-band control frames (HELLO, CLEAR, etc.)

        self._connection_attempts = 0
        self._tx_mutex = QMutex()
        self._tx_paused = False

        # --- Gripper confirmation gate ---
        # Start with confirmation required so the very first open/close pops the dialog.
        self._gripper_ack_required = True
        # self._blocked_gripper_command = None

        self._gripper_idle_timer = QTimer(self)
        self._gripper_idle_timer.setSingleShot(True)
        self._gripper_idle_timer.timeout.connect(self._on_gripper_idle_timeout)

        # When the gripper actually moves (command completes), if the gate is *not* set,
        # reset the 10-minute idle timer.
        self.gripper_open.connect(self._on_gripper_moved)
        self.gripper_closed.connect(self._on_gripper_moved)

        # Clean-up when disconnected
        self.disconnect_complete_signal.connect(self._on_disconnect_reset_gripper_timer)

        try:
            self.refuel_camera = RefuelCamera()
        except Exception as e:
            print(f'Error initializing refuel camera: {e}')
            self.refuel_camera = None

        try:
            self.droplet_camera = DropletCamera()
        except Exception as e:
            print(f'Error initializing droplet camera: {e}')
            self.droplet_camera = None

    def _alloc_ctl_seq32(self) -> int:
        n = self._next_ctl_seq32
        self._next_ctl_seq32 = (self._next_ctl_seq32 + 1) & 0xFFFFFFFF
        return n
    
    @staticmethod
    def _ack_key(ack_code: int, seq32: int | None, seq8: int | None = None):
        """
        Prefer SEQ32 if present; otherwise fall back to seq8.
        Use -1 when missing to keep a stable tuple key type.
        """
        if seq32 is not None:
            return (ack_code, int(seq32), -1)
        if seq8 is not None:
            return (ack_code, -1, int(seq8))
        return (ack_code, -1, -1)  # last-ditch fallback

    def _start_ack_wait(self, ack_code: int, seq32: int | None, timeout_ms: int,
                        on_ok: callable, on_timeout: callable, *, seq8: int | None = None):
        """Begin waiting for a specific ack_code with a one-shot timer."""
        # If a previous wait exists for this ack, cancel it
        # self._cancel_ack_wait(ack_code)
        key = self._ack_key(ack_code, seq32, seq8)
        self._cancel_ack_wait_by_key(key)

        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self._ack_timeout_by_key(key))
        self._pending_acks[key] = {"timer": t, "ok": on_ok, "to": on_timeout}
        t.start(timeout_ms)

    def _ack_timeout_by_key(self, key):
        entry = self._pending_acks.pop(key, None)
        if not entry:
            return
        try:
            entry["to"]()
        finally:
            entry["timer"].deleteLater()

    def _cancel_ack_wait_by_key(self, key):
        entry = self._pending_acks.pop(key, None)
        if entry:
            entry["timer"].stop()
            entry["timer"].deleteLater()

    @Slot(object)
    def _on_any_ack(self, ack: dict):
        """
        ack = {"ack_cmd": int, "seq8": int, "seq32": int|None}
        """
        ack_code = ack.get("ack_cmd")
        seq32    = ack.get("seq32")
        seq8     = ack.get("seq8")

        # Try SEQ32 first, then fall back to seq8
        key = self._ack_key(ack_code, seq32, None)
        entry = self._pending_acks.pop(key, None)
        if not entry and seq32 is None:
            key = self._ack_key(ack_code, None, seq8)
            entry = self._pending_acks.pop(key, None)

        if entry:
            entry["timer"].stop()
            try:
                entry["ok"]()
            finally:
                entry["timer"].deleteLater()
        else:
            # Optional: log stray ACKs
            print(f"Stray ACK: code=0x{ack_code:02X} seq32={seq32} seq8={seq8}")
            pass

    def connect_board(self, port):
        try:
            self.port = port
            self.ser = serial.Serial('/dev/ttyAMA0', self.baud, timeout=0.1)
            if not self.ser.is_open:
                raise IOError("Port not open")
            
            self.begin_reader_thread()

            # Send HELLO and wait up to 1000 ms for HELLO_ACK
            hello_seq = self._alloc_ctl_seq32()
            self._write_frame(build_frame(HELLO, hello_seq))
            self._start_ack_wait(
                HELLO_ACK, hello_seq, 1000,
                on_ok=self._on_hello_ack,
                on_timeout=lambda: self._hello_timeout()
            )

        except Exception as e:
            print(f"Connection error: {e}")
            self.error_occurred.emit(str(f"Connection error: {e}"))
            self.machine_connected_signal.emit(False)
    @Slot()
    def _on_hello_ack(self):
        self.begin_log_thread()
        self.begin_execution_timer()
        self.machine_connected_signal.emit(True)
        print(f"Connected to {self.ser.name}")
        self._connection_attempts = 0  # reset attempts on success

    def _hello_timeout(self):
        self.machine_connected_signal.emit(False)
        # Retry to connect
        if self._connection_attempts < 3:
            self._connection_attempts += 1
            print(f"Retrying connection ({self._connection_attempts}/3)…")
            self.connect_board(self.port)
        elif self._connection_attempts < 6:
            self._connection_attempts += 1
            self.reset_mcu_board()
            print(f"Resetting board and retrying connection ({self._connection_attempts}/6)…")
        else:
            print("Max connection attempts reached. Please check the machine.")
            self.machine_connected_signal.emit(False)

    def reset_board(self):
        print('Resetting board')
        self.command_queue.clear_queue()
        # Stop TX timer
        if getattr(self, 'execution_timer', None):
            try:
                self.execution_timer.stop()
                self.execution_timer.deleteLater()
            except Exception:
                pass
            self.execution_timer = None

        # Cancel any pending ack timers
        for entry in list(self._pending_acks.values()):
            try:
                entry["timer"].stop()
                entry["timer"].deleteLater()
            except Exception:
                pass
        self._pending_acks.clear()

        self.stop_reader_thread()
        self.stop_log_thread()

        try: self._gripper_idle_timer.stop()
        except Exception: pass
        self._gripper_ack_required = True
        # self._blocked_gripper_command = None

    def reset_mcu_board(self):
        reset_board()
        
    def disconnect_handler(self):
        self.reset_board()
        # Now it's safe to close the main serial
        try:
            if self.ser is not None:
                if self.ser.is_open:
                    self.ser.close()
        except Exception:
            pass
        finally:
            self.ser = None
            self.port = None

        self.disconnect_complete_signal.emit()

    def disconnect_board(self, error=False):
        if not self.ser:
            self.disconnect_handler()
            return
        # Optionally pause the execution timer so nothing else writes during bye
        if hasattr(self, 'execution_timer') and self.execution_timer:
            try: self.stop_execution_timer()
            except Exception: pass

        # Allocate a unique 32-bit control seq for GOODBYE
        seq = self._alloc_ctl_seq32()
        self._goodbye_seq32 = seq    # keep for BYE_DONE correlation

        frame = build_frame(GOODBYE, seq)  # MUST include SEQ32 TLV inside
        self._write_frame(frame)

        # Wait for BYE_ACK with the SAME seq32
        self._start_ack_wait(
            BYE_ACK, seq, 1000,
            on_ok=lambda s=seq: self._on_goodbye_ack_and_wait_done(s),
            on_timeout=lambda s=seq: self._on_goodbye_ack_and_wait_done(s)  # proceed anyway
        )


    def _on_goodbye_ack_and_wait_done(self, seq32):
        # Second wait: BYE_DONE (shutdown finished). If it never arrives, proceed anyway.
        print('Goodbye acknowledged, waiting for shutdown confirmation...')
        self._start_ack_wait(
            BYE_DONE, seq32, 3000,                   # adjust timeout to your shutdown worst-case
            on_ok=self._on_goodbye_done,
            on_timeout=self._on_goodbye_done  # proceed anyway after timeout
        )

    def _on_goodbye_done(self):
        try:
            time.sleep(0.05)
            self.ser.reset_input_buffer()
            print('Goodbye acknowledged, machine disconnected.')
        except Exception:
            print('Error during goodbye acknowledgment.')
            pass
        # stop threads, close, etc.
        self.disconnect_handler()

    def begin_reader_thread(self):
        """
        Start the serial reader thread to read data from the machine.
        """
        if self.reader is None:
            self.reader = SerialReader(self.ser)
            self.reader.status_received.connect(self.update_status)
            self.reader.ackReceived.connect(self._on_any_ack)
            self.reader.start()
            print('Serial reader thread started')
        else:
            print('Serial reader thread already running')

    def stop_reader_thread(self):
        """
        Stop the serial reader thread.
        """
        if self.reader is not None:
            try:
                self.reader.stop()
            except Exception:
                # fallback to old behavior
                self.reader.requestInterruption()
                self.reader.wait(1000)
            self.reader = None
            print('Serial reader thread stopped')
        else:
            print('No serial reader thread to stop')

    def begin_log_thread(self):
        """
        Start the log reader thread to read logs from the machine.
        """
        self.log_reader = LogReader(self.baud)
        self.log_reader.lineReceived.connect(self.on_log_line_received)
        self.log_reader.statsUpdated.connect(self.on_stats_updated)
        self.log_reader.messageReceived.connect(self.on_log_message_received)
        self.log_reader.start()

    def on_stats_updated(self, stats: dict):
        self.log_stats_updated.emit(stats)

    def on_log_message_received(self, message: str):
        self.log_message_received.emit(message)
        
    def stop_log_thread(self):
        """
        Stop the log reader thread.
        """
        if self.log_reader is not None:
            self.log_reader.stop()
            self.log_reader.wait(200)
            self.log_reader = None
            print('Log reader thread stopped')
        else:
            print('No log reader thread to stop')

    def begin_execution_timer(self):
        print('Starting execution timer')
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.send_next_command)
        self.execution_timer.start(90)  # Update every 100 ms

    def stop_execution_timer(self):
        print('Stopping execution timer')
        self.execution_timer.stop()

    def update_status(self, data):
        """
        Update the status of the machine with the received data.
        """
        if isinstance(data, dict):
            if getattr(self, "_waiting_for_post_clear_status", False):
                depth = data.get("cmd_depth", 0)
                curr  = data.get("Current_command", 0)
                last  = data.get("Last_completed", 0)
                if depth == 0 and curr == 0 and last == 0:
                    self._waiting_for_post_clear_status = False
                    self._tx_paused = False
                    self.begin_execution_timer()
                elif time.time() > getattr(self, "_wait_for_clear_status_deadline", 0):
                    # fallback: don’t block forever
                    self._waiting_for_post_clear_status = False
                    self._tx_paused = False
                    self.begin_execution_timer()
            self.status_updated.emit(data)
        else:
            print(f"Received non-dict status data: {data}")
    
    def on_log_line_received(self, line):
        """
        Handle a line received from the log reader.
        """
        # Here you can process the log line, e.g., print it or emit a signal
        if "HELLO_ACK" in line:
            print("HELLO_ACK received, machine is ready.")
            self.machine_connected_signal.emit(True)
        # print(f"Log line received: {line}")

    def update_command_numbers(self,current_command,last_completed):
        self.command_queue.update_command_status(current_command,last_completed)

    def add_command_to_queue(self, command_type, param1, param2, param3, handler=None, kwargs=None, manual=False):
        """Add a command to the queue."""
        # if self.board is None:
        #     print('No board connected')
        #     return False
        # if manual:
        #     completed = self.check_if_all_completed()
        #     if not completed:
        #         print('Cannot add manual command while commands are in queue')
        #         return False
        return self.command_queue.add_command(command_type, param1, param2, param3, handler, kwargs)
    
    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        if len(self.command_queue.queue) == 0:
            return True
        return False
    
    def get_remaining_commands(self):
        return len(self.command_queue.queue)
    
    def _write_frame(self, frame: bytes):
        with QMutexLocker(self._tx_mutex):
            self.ser.write(frame)
            self.ser.flush()

    def send_command_to_board(self, command):
        """Send a command to the board."""
        # self.ser.write(command.frame)
        # self.ser.flush()
        self._write_frame(command.frame)
        self.command_sent.emit({"command": command.get_command()})
        print(f"Sent command: {command.get_command()}")
        return True

    def send_next_command(self):
        """
        Send the next command in the queue to the machine.
        """
        if getattr(self, "_tx_paused", False):
            return

        command = self.command_queue.get_next_command()
        if not command:
            return

        # --- Gripper gate (SEND FIRST, then pause & prompt) ---
        if command.command_type in ('OPEN_GRIPPER', 'CLOSE_GRIPPER'):
            if self._gripper_ack_required:
                # 1) Send now so it actually executes and leaves the queue
                try:
                    self.send_command_to_board(command)
                    command.mark_as_sent()
                    print(f"Sent command (pre-prompt): {command.command_type} {command.param1} {command.param2} {command.param3}")
                except Exception as e:
                    print(f"Failed to send command: {e}")
                    self.error_occurred.emit(f"Failed to send command: {e}")
                    return

                # 2) Immediately pause TX and show the popup
                self._tx_paused = True
                action = 'OPEN' if command.command_type == 'OPEN_GRIPPER' else 'CLOSE'
                self.require_gripper_confirmation.emit(action)
                return
            else:
                # If we don't need a prompt, keep the idle timer fresh on gripper ops
                self._reset_gripper_idle_timer()

        # --- Normal path for everything else ---
        try:
            self.send_command_to_board(command)
            command.mark_as_sent()
            print(f"Sent command: {command.command_type} {command.param1} {command.param2} {command.param3}")
        except Exception as e:
            print(f"Failed to send command: {e}")
            self.error_occurred.emit(f"Failed to send command: {e}")
    
    def pause_commands(self):
        print('Pausing commands')
        new_command = Command(0, 'PAUSE', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending pause command')
        self.send_command_to_board(new_command)
    
    def resume_commands(self):
        print('Resuming commands')
        new_command = Command(0, 'RESUME', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending resume command')
        self.send_command_to_board(new_command)

    def clear_command_queue(self, handler=None):
        print('Clearing command queue')

        if hasattr(self, 'execution_timer') and self.execution_timer:
            try: self.stop_execution_timer()
            except Exception: pass

        # Optionally pause TX for safety while waiting
        self._tx_paused = True

        try: self.ser.reset_input_buffer()
        except Exception: pass

        # send CLEAR
        seq = self._alloc_ctl_seq32()
        frame = build_frame(CLEAR_QUEUE, seq)
        self._write_frame(frame)

        self._start_ack_wait(
            CLEAR_ACK, seq, 2000,
            on_ok=lambda: self._on_clear_ack(handler, timed_out=False),
            on_timeout=lambda: self._on_clear_ack(handler, timed_out=True)
        )        


    def _on_clear_ack(self, handler=None, timed_out=False):
        if timed_out:
            print("No CLEAR_ACK received, proceeding anyway.")
        else:
            print("CLEAR_ACK received, command queue cleared.")

        # Clear Python side queue & notify UI
        self.command_queue.clear_queue()
        self._tx_paused = False

        self._wait_for_clear_status_deadline = time.time() + 0.5  # 500 ms fallback
        self._waiting_for_post_clear_status = True

        if handler:
            handler()

        self.begin_execution_timer()

    def _reset_gripper_idle_timer(self):
        # 10 minutes in milliseconds
        self._gripper_idle_timer.start(10 * 60 * 1000)

    @Slot()
    def _on_gripper_idle_timeout(self):
        # After 10 minutes of no gripper activity, require confirmation next time
        self._gripper_ack_required = True

    @Slot()
    def _on_gripper_moved(self):
        # Only reset the timer when we are in the "free running" state
        if not self._gripper_ack_required:
            self._reset_gripper_idle_timer()

    @Slot()
    def confirm_gripper_ready(self):
        """
        Called by UI after the user has manually ensured the gripper is in the requested state.
        This clears the gate, starts the 10-minute timer, and resumes queue transmission.
        """
        self._gripper_ack_required = False
        self._reset_gripper_idle_timer()
        self._tx_paused = False
        # Nudge the sender so the blocked command can go out immediately
        try:
            self.send_next_command()
        except Exception:
            pass

    @Slot()
    def _on_disconnect_reset_gripper_timer(self):
        try:
            self._gripper_idle_timer.stop()
        except Exception:
            pass
        # On next connection we want the first gripper operation to prompt again
        self._gripper_ack_required = True
        # self._blocked_gripper_command = None

    def check_param_limits(self,param,min_val,max_val):
        if param >= min_val and param <= max_val:
            return True
        else:
            self.error_occurred.emit(f'Parameter out of range: {param} not in ({min_val},{max_val})')
            return False

    def enable_motors(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def disable_motors(self,handler=None,kwargs=None,manual=False):
        outcome = self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return outcome

    def set_axis_maxspeed(self, axis_idx, max_speed):
        return self.add_command_to_queue('SET_AXIS_MAXSPEED', axis_idx, max_speed, 0)

    def set_axis_accel(self, axis_idx, accel):
        return self.add_command_to_queue('SET_AXIS_ACCEL', axis_idx, accel, 0)

    def change_acceleration(self,acceleration,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(acceleration,1,50000):
            return self.add_command_to_queue('CHANGE_ACCEL',acceleration,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def reset_acceleration(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('RESET_ACCEL',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_print_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_refuel_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def deregulate_print_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def deregulate_refuel_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def reset_print_syringe(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('RESET_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def reset_refuel_syringe(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('RESET_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_absolute_XY(self, x, y, handler=None, kwargs=None, manual=False):
        """
        Set absolute X and Y positions.
        """
        if self.check_param_limits(x,0,80000) and self.check_param_limits(y,0,60000):
            return self.add_command_to_queue('ABSOLUTE_XY', x, y, 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Absolute X or Y position out of range: X={x}, Y={y}')
            return False
    
    def set_relative_X(self, x, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,-80000,80000):
            # calculate direction
            direction = 1 if x >= 0 else 0
            return self.add_command_to_queue('RELATIVE_X', direction, abs(x), 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Relative X position {x} out of range (-80000, 80000)')
            return False
    
    def set_absolute_X(self, x, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,0,80000):
            sign = 1 if x >= 0 else 0
            x = abs(x)
            return self.add_command_to_queue('ABSOLUTE_X', sign, x, 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Absolute X position {x} out of range (0, 80000)')
            return False
    
    def set_relative_Y(self, y, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(y,-60000,60000):
            # calculate direction
            direction = 1 if y >= 0 else 0
            return self.add_command_to_queue('RELATIVE_Y', direction, abs(y), 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Relative Y position {y} out of range (-60000, 60000)')
            return False
    
    def set_absolute_Y(self, y, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(y,0,60000):
            sign = 1 if y >= 0 else 0
            y = abs(y)
            return self.add_command_to_queue('ABSOLUTE_Y', sign, y, 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Absolute Y position {y} out of range (0, 60000)')
            return False
    
    def set_relative_Z(self, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(z,-130000,130000):
            direction = 1 if z >= 0 else 0
            return self.add_command_to_queue('RELATIVE_Z', direction, abs(z), 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Relative Z position {z} out of range (-130000, 130000)')
            return False
    
    def set_absolute_Z(self, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(z,0,130000):
            sign = 1 if z >= 0 else 0
            z = abs(z)
            return self.add_command_to_queue('ABSOLUTE_Z', sign, z, 30000, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Absolute Z position {z} out of range (0, 130000)')
            return False

    # def set_relative_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
    #     if self.check_param_limits(x,-50000,50000) and self.check_param_limits(y,-50000,50000) and self.check_param_limits(z,-50000,50000):
    #         return self.add_command_to_queue('RELATIVE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        
    # def set_absolute_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
    #     if self.check_param_limits(x,-50000,50000) and self.check_param_limits(y,-50000,50000) and self.check_param_limits(z,-50000,50000):
    #         return self.add_command_to_queue('ABSOLUTE_XYZ', x, y, 30000, handler=handler, kwargs=kwargs, manual=manual)
        
    def convert_to_psi(self,pressure):
        return round(((pressure - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int(round((psi / self.psi_max) * self.fss + self.psi_offset, 0))

    def set_relative_print_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative print pressure:',pressure)
        if self.check_param_limits(pressure,-2185,2185):
            sign = 1 if pressure >= 0 else 0
            pressure = abs(pressure)
            return self.add_command_to_queue('RELATIVE_PRESSURE_P',sign,pressure,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_relative_refuel_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative refuel pressure:',pressure)
        if self.check_param_limits(pressure,-2185,2185):
            sign = 1 if pressure >= 0 else 0
            pressure = abs(pressure)
            return self.add_command_to_queue('RELATIVE_PRESSURE_R',sign, pressure, 0,handler=handler,kwargs=kwargs,manual=manual)

    def set_absolute_print_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute print pressure:',pressure)
        if self.check_param_limits(pressure,0,10376):
            return self.add_command_to_queue('ABSOLUTE_PRESSURE_P',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_absolute_refuel_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute refuel pressure:',pressure)
        if self.check_param_limits(pressure,0,10376):
            return self.add_command_to_queue('ABSOLUTE_PRESSURE_R',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_print_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue('SET_WIDTH_P',int(pulse_width),0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_refuel_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue('SET_WIDTH_R',int(pulse_width),0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def enter_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('PRINT_MODE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def exit_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('NORMAL_MODE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def home_motor_handler(self):
        self.homed = True
        self.location = 'Home'
        self.homing_completed.emit()

    def home_motors(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.home_motor_handler
        self.add_command_to_queue('HOME_Z',10000,1000,1000,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_XY',10000,1000,1000,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_PR_BOTH',10000,1000,1000,handler=handler,kwargs=kwargs,manual=manual)

        return True
    
    def home_regulators(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('HOME_PR_BOTH',10000,1000,1000,handler=handler,kwargs=kwargs,manual=manual)
    
    def open_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_open.emit()

    def open_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.open_gripper_handler
        else:
            new_handler = lambda: self.open_gripper_handler(handler)
        return self.add_command_to_queue('OPEN_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
    
    def close_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_closed.emit()

    def close_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.close_gripper_handler
        else:
            new_handler = lambda: self.close_gripper_handler(handler)
        return self.add_command_to_queue('CLOSE_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
        
    def gripper_off_handler(self):
        self.gripper_off_signal.emit()

    def gripper_off(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.gripper_off_handler
        return self.add_command_to_queue('GRIPPER_OFF',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def wait_command(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('WAIT',200,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def print_droplets(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('DISPENSE',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)

    def LED_on(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('LED_ON',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def LED_off(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('LED_OFF',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def start_refuel_camera(self):
        self.refuel_camera.start_camera()
        return

    def capture_refuel_image(self):
        return self.refuel_camera.capture_image()

    def stop_refuel_camera(self):
        self.refuel_camera.stop_camera()
        return

    def refuel_led_on(self):
        self.refuel_camera.led_on()
        return

    def refuel_led_off(self):
        self.refuel_camera.led_off()
        return
    
    def start_droplet_camera(self):
        self.droplet_camera.start_camera()
        return
    
    def capture_droplet_image(self):
        # return self.droplet_camera.capture_non_blocking()
        return self.droplet_camera.capture_with_retry_async(attempts=5, attempt_timeout_s=1)
    
    def stop_droplet_camera(self):
        self.droplet_camera.stop_camera()
        return
    
    def start_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('START_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def stop_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('STOP_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_exposure_time(self, exposure_time, handler=None):
        return self.droplet_camera.change_exposure_time(exposure_time,handler=handler)
    
    def set_flash_duration(self,duration,handler=None,kwargs=None,manual=False):
        duration = int(duration) # Only allow durations in increments of 100 nsec
        if duration >= 1:
            return self.add_command_to_queue('SET_WIDTH_F',duration,0,0,handler=handler,kwargs=kwargs,manual=manual)
        else:
            print('Duration too low')

    def set_flash_delay(self,delay,handler=None,kwargs=None,manual=False):
        delay = round(delay,0)
        if delay >= 100:
            return self.add_command_to_queue('SET_DELAY_F',delay,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_imaging_droplets(self,droplets,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('SET_IMAGE_DROPLETS',droplets,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def print_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('DISPENSE_PRINT',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)

    def refuel_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('DISPENSE_REFUEL',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def enable_print_profile(self, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('ENABLE_PRINT_PROFILE', 0, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def disable_print_profile(self, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('DISABLE_PRINT_PROFILE', 0, 0, 0, handler=handler, kwargs=kwargs, manual=manual)

    def set_gripper_params(self, refresh_period, pulse_duration, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(refresh_period, 1000, 1000000) and self.check_param_limits(pulse_duration, 100, 10000):
            return self.add_command_to_queue('SET_GRIPPER_PARAMS', refresh_period, pulse_duration, 0, handler=handler, kwargs=kwargs, manual=manual)
        else:
            print(f'Gripper parameters out of range: refresh_period={refresh_period}, pulse_duration={pulse_duration}')
            return False