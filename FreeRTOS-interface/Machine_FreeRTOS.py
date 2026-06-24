import threading
import time
import struct
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread, QMutex, QMutexLocker
from PySide6.QtWidgets import QApplication

from dfu_update import reset_board, update_firmware
from dfu_update_worker import DfuUpdateWorker

from collections import deque

import serial
import re
import json
import logging
import cv2
import numpy as np
import pandas as pd
import os
import joblib
import shutil
import subprocess
import glob
import select

from hardware.profile import CURRENT_PROFILE, HardwareProfile
from hardware.null_devices import NullCamera
from HostBlackBoxLog import HostBlackBoxRecorder

logger = logging.getLogger(__name__)

LOG_READER_SERIAL_TIMEOUT_S = 0.1
SERIAL_READER_STOP_WAIT_MS = 250
LOG_READER_STOP_WAIT_MS = 250
READER_STOP_FALLBACK_WAIT_MS = 1000

try:
    from picamera2 import Picamera2
    import gpiod
except ImportError:
    print("Running on a non-Raspberry Pi system or missing required libraries. Camera and GPIO functionality will be unavailable.")
    Picamera2 = None
    gpiod = None

def _gpiofind(line_name: str):
    """
    Resolve a GPIO line name like "GPIO17" to (chip_path, offset).

    Prefer the legacy gpiofind CLI when present, but fall back to scanning the
    available gpiochips via the Python gpiod binding. Newer Raspberry Pi /
    Debian images may ship gpioinfo/gpiodetect without the standalone gpiofind
    binary.
    """
    gpiofind_bin = shutil.which("gpiofind")
    if gpiofind_bin is not None:
        out = subprocess.check_output([gpiofind_bin, line_name], text=True).strip()
        chip_path, off = out.split()
        return chip_path, int(off)

    try:
        import gpiod
    except Exception as e:
        raise RuntimeError(
            "gpiofind is not available and python gpiod could not be imported. "
            "Install python3-libgpiod, or configure GPIO using chip+offset."
        ) from e

    chip_paths = sorted(glob.glob("/dev/gpiochip*"))
    lookup_errors = []
    for chip_path in chip_paths:
        chip = None
        try:
            chip = gpiod.Chip(chip_path)

            if hasattr(chip, "line_offset_from_id"):
                try:
                    return chip_path, int(chip.line_offset_from_id(line_name))
                except Exception:
                    pass

            get_line_info = getattr(chip, "get_line_info", None)
            if callable(get_line_info):
                try:
                    info = get_line_info(line_name)
                except Exception:
                    info = None
                if info is not None:
                    offset = getattr(info, "offset", getattr(info, "line_offset", None))
                    if offset is not None:
                        return chip_path, int(offset)
        except Exception as e:
            lookup_errors.append(f"{chip_path}: {e}")
        finally:
            close = getattr(chip, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    available = " ".join(chip_paths) or "<none>"
    detail = f" Lookup errors: {'; '.join(lookup_errors)}" if lookup_errors else ""
    raise FileNotFoundError(
        f"GPIO line {line_name!r} was not found. Available chips: {available}.{detail}"
    )

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

def _wait_edge_events_compat(wait_fn, timeout):
    """
    Call a libgpiod wait function across API/version differences.
    Some builds accept float seconds, others require timedelta, integers, or
    sec/nsec pairs.
    """
    errs = []
    try:
        t = max(0.0, float(timeout))
    except Exception:
        t = 0.0

    # 1) Common one-arg forms.
    candidates = [timeout]
    try:
        import datetime as _dt
        candidates.append(_dt.timedelta(seconds=t))
    except Exception:
        pass
    # Integer fallbacks (common in some C-extension signatures)
    candidates.extend([
        int(round(t * 1_000_000_000)),  # ns
        int(round(t * 1_000_000)),      # us
        int(round(t * 1_000)),          # ms
        int(max(0, round(t))),          # s
    ])

    for arg in candidates:
        try:
            return bool(wait_fn(arg))
        except TypeError as e:
            errs.append(str(e))
        except Exception as e:
            # Unexpected runtime failure should propagate.
            raise

    # 2) Two-arg / keyword sec+nsec forms used by some v1 bindings.
    sec = int(t)
    nsec = int(round((t - sec) * 1_000_000_000))
    for args, kwargs in (
        ((sec, nsec), {}),
        ((), {"sec": sec, "nsec": nsec}),
        ((), {"seconds": sec, "nanoseconds": nsec}),
    ):
        try:
            return bool(wait_fn(*args, **kwargs))
        except TypeError as e:
            errs.append(str(e))
        except Exception:
            raise

    # 3) If every signature probe failed, keep behavior explicit.
    detail = errs[-1] if errs else "unsupported timeout signature"
    raise TypeError(f"Unable to call edge wait with timeout={timeout!r}: {detail}")

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
                return _wait_edge_events_compat(req.wait_edge_events, timeout)
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
        event_get_fd = getattr(line, "event_get_fd", None)
        if not callable(event_get_fd):
            try:
                line.release()
            except Exception:
                pass
            raise RuntimeError(
                f"gpio_edge_fd_unavailable: libgpiod v1 edge line {chip_name}:{offset} "
                "does not expose event_get_fd(); refusing unbounded event_wait."
            )
        try:
            event_fd = int(event_get_fd())
        except Exception as exc:
            try:
                line.release()
            except Exception:
                pass
            raise RuntimeError(
                f"gpio_edge_fd_unavailable: could not get event fd for {chip_name}:{offset}: {exc}"
            ) from exc

        class InV1:
            def event_wait(self, timeout):
                try:
                    timeout_s = max(0.0, float(timeout))
                except Exception:
                    timeout_s = 0.0
                ready, _w, _x = select.select([event_fd], [], [], timeout_s)
                return bool(ready)
            def event_consume(self):
                _ = line.event_read()
            def release(self):
                line.release()
        return InV1()

# ---------- DropletCamera: grabber-driven flash detection with time gating ----------

class StaleCaptureBackend(RuntimeError):
    """Raised when an old capture worker touches a backend after recovery replaced it."""


class _DropletCaptureBackend:
    def __init__(self, backend_id, trigger_line, edge_line):
        self.backend_id = str(backend_id)
        self.trigger_line = trigger_line
        self.edge_line = edge_line
        self._released = False
        self._lock = threading.Lock()

    @property
    def is_open(self):
        with self._lock:
            return not self._released

    def _line_or_stale(self, attr_name, action):
        with self._lock:
            if self._released:
                raise StaleCaptureBackend(
                    f"capture backend {self.backend_id} is stale during {action}"
                )
            return getattr(self, attr_name)

    def _raise_if_released_after(self, action):
        with self._lock:
            if self._released:
                raise StaleCaptureBackend(
                    f"capture backend {self.backend_id} was released during {action}"
                )

    def trigger_high(self):
        line = self._line_or_stale("trigger_line", "trigger_high")
        line.set_value(1)
        self._raise_if_released_after("trigger_high")

    def trigger_low(self):
        line = self._line_or_stale("trigger_line", "trigger_low")
        line.set_value(0)
        self._raise_if_released_after("trigger_low")

    def event_wait(self, timeout):
        edge = self._line_or_stale("edge_line", "event_wait")
        try:
            fired = edge.event_wait(timeout)
        except Exception as exc:
            with self._lock:
                released = self._released
            if released:
                raise StaleCaptureBackend(
                    f"capture backend {self.backend_id} released while waiting for edge"
                ) from exc
            raise
        self._raise_if_released_after("event_wait")
        return fired

    def event_consume(self):
        edge = self._line_or_stale("edge_line", "event_consume")
        try:
            edge.event_consume()
        except Exception as exc:
            with self._lock:
                released = self._released
            if released:
                raise StaleCaptureBackend(
                    f"capture backend {self.backend_id} released while consuming edge"
                ) from exc
            raise
        self._raise_if_released_after("event_consume")

    def release(self):
        with self._lock:
            if self._released:
                return False
            self._released = True
            trigger_line = self.trigger_line
            edge_line = self.edge_line

        try:
            trigger_line.set_value(0)
        except Exception:
            pass
        for line in (edge_line, trigger_line):
            release = getattr(line, "release", None)
            if callable(release):
                try:
                    release()
                except Exception:
                    pass
        return True


class _OwnerCaptureBackendAdapter:
    """Compatibility backend for tests or legacy instances built without __init__."""

    backend_id = "legacy-owner"

    @property
    def is_open(self):
        return True

    def __init__(self, owner):
        self._owner = owner

    def trigger_high(self):
        self._owner._trigger_high()

    def trigger_low(self):
        self._owner._trigger_low()

    def event_wait(self, timeout):
        return self._owner._edge_in.event_wait(timeout)

    def event_consume(self):
        return self._owner._edge_in.event_consume()

    def release(self):
        return False

class DropletCamera(QObject):
    image_captured_signal = Signal()
    capture_completed_signal = Signal(object)
    capture_failed_signal = Signal(str)  # emits error message on failure
    capture_phase_signal = Signal(object)

    def __init__(self):
        super().__init__()
        # >>> wiring <<<
        self.trigger_pin_out_bcm = 17   # Pi -> MCU trigger
        self.flash_fired_in_bcm  = 22   # MCU -> Pi flash-ack

        # self._chip_name = "gpiochip4"
        self._trig_chip_name, self._trig_offset = _gpiofind("GPIO"+str(self.trigger_pin_out_bcm))
        self._flash_chip_name, self._flash_offset = _gpiofind("GPIO"+str(self.flash_fired_in_bcm))
        self._backend_lock = threading.Lock()
        self._capture_backend_seq = 0
        self._capture_backend = None
        self._trig_line = None
        self._edge_in = None
        self._last_backend_error = None
        self._last_backend_create_step = None
        self._replace_capture_backend(reason="init")

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
        self._signal_stride   = 1
        self._signal_channel  = None  # None => full RGB mean, else BGR channel index
        
        self._cap_done = threading.Event()      # set when _complete_capture_locked runs
        self._cap_result = None                 # dict with mean/threshold/reason, and the image
        self._emit_on_complete = True           # gate emitting during retries
        self._capture_worker_active = threading.Event()
        self._capture_worker_thread = None
        self._capture_generation = 0
        self._cap_request_id = None
        
        # threshold tuning
        self.k_sigma   = 4.0
        self.min_delta = 25.0
        self.max_wait_s = 1.0

    def set_capture_profile(self, profile_name: str):
        """
        Set capture behavior profile.
        - default: preserve historical behavior (full-frame mean, rotate output)
        - throughput: reduce per-frame CPU work and skip rotate
        """
        p = str(profile_name or "default").strip().lower()
        if p == "throughput":
            self._signal_stride = 4
            self._signal_channel = 1  # green channel
            self._cap_emit_rotate = False
            return
        self._signal_stride = 1
        self._signal_channel = None
        self._cap_emit_rotate = True

    def _signal_mean(self, arr) -> float:
        if arr is None:
            return 0.0
        try:
            if self._signal_channel is None:
                if self._signal_stride <= 1:
                    return float(np.mean(arr))
                return float(np.mean(arr[:: self._signal_stride, :: self._signal_stride, :]))
            chan = int(self._signal_channel)
            if self._signal_stride <= 1:
                return float(np.mean(arr[:, :, chan]))
            return float(np.mean(arr[:: self._signal_stride, :: self._signal_stride, chan]))
        except Exception:
            return float(np.mean(arr))

    # --- GPIO ---
    def _trigger_high(self):
        # print("[Pi] trigger HIGH")
        backend = self._get_current_capture_backend()
        if backend is not None:
            backend.trigger_high()
            return
        self._trig_line.set_value(1)
    def _trigger_low(self):
        # print("[Pi] trigger LOW")
        backend = self._get_current_capture_backend()
        if backend is not None:
            backend.trigger_low()
            return
        if self._trig_line is not None:
            self._trig_line.set_value(0)

    def _make_capture_backend(self, *, reason=""):
        self._capture_backend_seq = int(getattr(self, "_capture_backend_seq", 0)) + 1
        backend_id = self._capture_backend_seq
        trigger_line = None
        edge_line = None
        step = "edge_input"
        try:
            edge_line = _make_rising_edge_input(
                self._flash_chip_name,
                self._flash_offset,
                consumer="droplet_flash_edge",
            )
            step = "trigger_output"
            trigger_line = _make_output_line(
                self._trig_chip_name,
                self._trig_offset,
                initial=0,
                consumer="droplet_trigger",
            )
            backend = _DropletCaptureBackend(backend_id, trigger_line, edge_line)
            self._last_backend_error = None
            self._last_backend_create_step = None
            self._log_capture_phase("backend_created", backend=backend, reason=str(reason or ""))
            return backend
        except Exception as exc:
            self._last_backend_error = str(exc)
            self._last_backend_create_step = step
            self._log_capture_phase(
                "backend_create_failed",
                backend_id=backend_id,
                reason=str(reason or ""),
                step=step,
                trigger_chip=self._trig_chip_name,
                trigger_offset=self._trig_offset,
                edge_chip=self._flash_chip_name,
                edge_offset=self._flash_offset,
                error=str(exc),
                level="warning",
            )
            for line in (trigger_line, edge_line):
                if line is None:
                    continue
                try:
                    if line is trigger_line:
                        line.set_value(0)
                except Exception:
                    pass
                release = getattr(line, "release", None)
                if callable(release):
                    try:
                        release()
                    except Exception:
                        pass
            raise

    def _replace_capture_backend(self, *, reason=""):
        old_backend = None
        lock = getattr(self, "_backend_lock", None)
        if lock is None:
            self._backend_lock = threading.Lock()
            lock = self._backend_lock
        with lock:
            old_backend = getattr(self, "_capture_backend", None)
            self._capture_backend = None
            self._trig_line = None
            self._edge_in = None

        if old_backend is not None:
            released = False
            try:
                released = bool(old_backend.release())
            finally:
                self._log_capture_phase(
                    "backend_released",
                    backend=old_backend,
                    reason=str(reason or ""),
                    released=released,
                )

        backend = self._make_capture_backend(reason=reason)
        with lock:
            self._capture_backend = backend
            self._trig_line = backend.trigger_line
            self._edge_in = backend.edge_line
        return backend

    def _get_current_capture_backend(self):
        lock = getattr(self, "_backend_lock", None)
        if lock is None:
            return getattr(self, "_capture_backend", None)
        with lock:
            return getattr(self, "_capture_backend", None)

    def _resolve_capture_backend(self, backend=None):
        if backend is not None:
            return backend
        current = self._get_current_capture_backend()
        if current is not None:
            return current
        if getattr(self, "_edge_in", None) is not None:
            return _OwnerCaptureBackendAdapter(self)
        return None

    def _capture_backend_id(self, backend=None):
        backend = self._resolve_capture_backend(backend)
        return getattr(backend, "backend_id", None)

    def _is_worker_context_stale(self, *, backend=None, generation=None):
        if generation is not None and hasattr(self, "_capture_generation"):
            try:
                if int(generation) != int(getattr(self, "_capture_generation", 0)):
                    return True
            except Exception:
                return True
        current = self._get_current_capture_backend()
        if backend is not None and current is not None:
            return getattr(backend, "backend_id", None) != getattr(current, "backend_id", None)
        return False

    def _raise_if_worker_context_stale(self, *, backend=None, generation=None, action="capture"):
        if self._is_worker_context_stale(backend=backend, generation=generation):
            raise StaleCaptureBackend(f"capture worker context is stale during {action}")

    def _camera_ready_for_capture(self):
        if self.camera is None:
            return False
        if hasattr(self, "_grab_running") and not bool(getattr(self, "_grab_running", False)):
            return False
        thread = getattr(self, "_grab_thread", None)
        if thread is not None:
            try:
                return bool(thread.is_alive())
            except Exception:
                return False
        return True

    def _capture_backend_ready(self):
        backend = self._get_current_capture_backend()
        return backend is not None and bool(getattr(backend, "is_open", False))

    # --- camera lifecycle ---
    def start_camera(self):
        # Idempotent start: if this camera instance is already running, keep it.
        if self.camera is not None and self._grab_running and self._grab_thread and self._grab_thread.is_alive():
            return

        # Clean stale partial state before reopening.
        self._grab_running = False
        if self._grab_thread:
            self._grab_thread.join(timeout=1.0)
            self._grab_thread = None
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
            try:
                self.camera.close()
            except Exception:
                pass
            self.camera = None

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
            try:
                self.camera.stop()
            except Exception:
                pass
            try:
                self.camera.close()
            except Exception:
                pass
            self.camera = None
        self._trigger_low()

    def get_last_capture_result(self) -> dict | None:
        """
        Returns the last capture result dict produced by _complete_capture_locked.
        Safe to call from Qt thread.
        """
        with self._cv:  # uses the same lock as the grabber
            if isinstance(self._cap_result, dict):
                return dict(self._cap_result)
            return None

    def get_capture_state(self) -> dict:
        worker = getattr(self, "_capture_worker_thread", None)
        backend = self._get_current_capture_backend()
        with self._cv:
            return {
                "cap_active": bool(self._cap_active),
                "worker_active": bool(self._capture_worker_active.is_set()),
                "worker_thread_alive": bool(worker is not None and worker.is_alive()),
                "generation": int(getattr(self, "_capture_generation", 0)),
                "cap_id": int(getattr(self, "_cap_id", 0)),
                "request_id": getattr(self, "_cap_request_id", None),
                "cap_done": bool(self._cap_done.is_set()),
                "camera_started": self.camera is not None,
                "backend_id": getattr(backend, "backend_id", None),
                "backend_open": bool(getattr(backend, "is_open", False)) if backend is not None else False,
                "backend_available": backend is not None and bool(getattr(backend, "is_open", False)),
                "backend_error": getattr(self, "_last_backend_error", None),
                "backend_create_step": getattr(self, "_last_backend_create_step", None),
                "grabber_running": bool(getattr(self, "_grab_running", False)),
            }

    def _log_capture_phase(
        self,
        phase: str,
        *,
        request_id=None,
        generation=None,
        started_ns=None,
        backend=None,
        backend_id=None,
        level="info",
        **fields,
    ):
        elapsed_ms = 0.0
        if started_ns is not None:
            try:
                elapsed_ms = (time.monotonic_ns() - int(started_ns)) / 1_000_000.0
            except Exception:
                elapsed_ms = 0.0
        if backend_id is None and backend is not None:
            backend_id = getattr(backend, "backend_id", None)
        details = {
            "request_id": request_id,
            "gen": generation,
            "cap_id": int(getattr(self, "_cap_id", 0)),
            "backend_id": backend_id,
            "elapsed_ms": f"{elapsed_ms:.1f}",
        }
        details.update(fields)
        print("[CameraPhase] " + str(phase) + " " + " ".join(f"{k}={v}" for k, v in details.items()))
        payload = {
            "phase": str(phase),
            "request_id": request_id,
            "generation": generation,
            "cap_id": int(getattr(self, "_cap_id", 0)),
            "backend_id": backend_id,
            "elapsed_ms": float(elapsed_ms),
            "level": str(level or "info"),
        }
        payload.update(fields)
        try:
            self.capture_phase_signal.emit(payload)
        except Exception as exc:
            if str(phase) != "capture_phase_signal_error":
                print(f"[Camera] capture phase signal failed phase={phase}: {exc}")

    def _set_capture_failure_result(self, reason: str, *, request_id=None, generation=None, error=None, **extra):
        with self._cv:
            self._cap_active = False
            self._cap_result = {
                "arr": None,
                "md": None,
                "mean": 0.0,
                "reason": str(reason),
                "threshold": 0.0,
                "cap_id": int(getattr(self, "_cap_id", 0)),
                "request_id": request_id,
                "generation": generation,
            }
            if error is not None:
                self._cap_result["error"] = str(error)
            self._cap_result.update(extra)
            self._cap_done.set()
            self._cv.notify_all()

    def recover_stale_capture(self, reason: str = "") -> dict:
        reason = str(reason or "stale_capture_recovery")
        restarted = False
        backend_reopened = False
        backend_error = None
        ready_for_retry = False
        worker_alive_after_join = False
        old_backend = self._get_current_capture_backend()
        self._log_capture_phase(
            "recovery_start",
            backend=old_backend,
            reason=reason,
            level="warning",
        )
        try:
            if old_backend is not None:
                old_backend.trigger_low()
            else:
                self._trigger_low()
        except StaleCaptureBackend:
            pass
        except Exception as exc:
            print(f"[Camera] recovery trigger-low failed: {exc}")
        with self._cv:
            self._capture_generation += 1
            generation = int(self._capture_generation)
            self._cap_active = False
            self._emit_on_complete = False
            self._cap_request_id = None
            self._cap_result = {
                "arr": None,
                "md": None,
                "mean": 0.0,
                "reason": "recovered_stale_capture",
                "error": reason,
                "threshold": 0.0,
                "cap_id": int(getattr(self, "_cap_id", 0)),
                "generation": generation,
                "backend_id": getattr(old_backend, "backend_id", None),
            }
            self._cap_done.set()
            self._cv.notify_all()
        worker = getattr(self, "_capture_worker_thread", None)
        if worker is not None and worker is not threading.current_thread():
            try:
                worker.join(timeout=0.25)
                worker_alive_after_join = bool(worker.is_alive())
            except Exception:
                worker_alive_after_join = True

        self._capture_worker_active.clear()

        try:
            self._replace_capture_backend(reason=reason)
            backend_reopened = True
        except Exception as exc:
            backend_error = str(exc)
            print(f"[Camera] recovery backend reopen failed: {exc}")

        if worker_alive_after_join and self.camera is not None:
            try:
                self.stop_camera()
                self.start_camera()
                restarted = True
            except Exception as exc:
                print(f"[Camera] recovery camera restart failed: {exc}")
        backend_ready = backend_reopened and self._capture_backend_ready()
        camera_ready = self._camera_ready_for_capture()
        if worker_alive_after_join and self.camera is not None and not restarted:
            camera_ready = False
        ready_for_retry = bool(backend_ready and camera_ready)

        result = {
            "ok": True,
            "ready_for_retry": bool(ready_for_retry),
            "reason": reason,
            "generation": generation,
            "worker_alive_after_join": worker_alive_after_join,
            "camera_restarted": restarted,
            "backend_reopened": backend_reopened,
            "backend_id": self._capture_backend_id(),
            "backend_ready": bool(backend_ready),
            "camera_ready": bool(camera_ready),
        }
        if backend_error:
            result["backend_error"] = backend_error
            result["ok"] = False
        self._log_capture_phase(
            "recovery_end",
            backend=self._get_current_capture_backend(),
            generation=generation,
            reason=reason,
            ready_for_retry=bool(ready_for_retry),
            worker_alive_after_join=worker_alive_after_join,
            camera_restarted=restarted,
            backend_reopened=backend_reopened,
            backend_ready=bool(backend_ready),
            camera_ready=bool(camera_ready),
            level="warning",
        )
        return result

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
            mean = self._signal_mean(arr)
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
                            print(
                                f"[Capture] request_id={getattr(self, '_cap_request_id', None)} "
                                f"gen={getattr(self, '_capture_generation', 0)} "
                                f"cap_id={self._cap_id} mean={mean:.1f} thr={self._cap_threshold:.1f}"
                            )
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
        backend = self._get_current_capture_backend()
        self._cap_result = {
            "arr": arr,
            "md": md,
            "mean": float(mean),
            "reason": str(reason),
            "threshold": float(self._cap_threshold),
            "cap_id": int(self._cap_id),
            "request_id": getattr(self, "_cap_request_id", None),
            "generation": int(getattr(self, "_capture_generation", 0)),
            "backend_id": getattr(backend, "backend_id", None),
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

    def capture_non_blocking(
        self,
        max_new_frames=6,
        timeout_s=1,
        *,
        emit_signal=True,
        request_id=None,
        generation=None,
        backend=None,
        backend_id=None,
    ):
        """
        Arms a single attempt. The grabber will complete it and either emit
        image_captured_signal (if emit_signal=True) or just set _cap_result/_cap_done.
        """
        phase_started_ns = time.monotonic_ns()
        backend = self._resolve_capture_backend(backend)
        backend_id = backend_id if backend_id is not None else getattr(backend, "backend_id", None)
        if not self.camera:
            print("Camera not started.")
            self._set_capture_failure_result(
                "camera_not_started",
                request_id=request_id,
                generation=generation,
                backend_id=backend_id,
            )
            return
        if backend is None:
            self._set_capture_failure_result(
                "backend_not_available",
                request_id=request_id,
                generation=generation,
                backend_id=backend_id,
            )
            return
        self._raise_if_worker_context_stale(backend=backend, generation=generation, action="capture_non_blocking")

        with self._cv:
            self._cap_done.clear()
            self._cap_result = None
            self._cap_request_id = request_id

        # Drain stale edges from previous runs
        drain_start_ns = time.monotonic_ns()
        drain_count = 0
        drain_max_edges = int(getattr(self, "prearm_drain_max_edges", 16))
        drain_timeout_s = float(getattr(self, "prearm_drain_timeout_s", 0.050))
        self._log_capture_phase(
            "drain_start",
            request_id=request_id,
            generation=generation,
            started_ns=phase_started_ns,
            backend=backend,
            drain_max_edges=drain_max_edges,
            drain_timeout_ms=f"{drain_timeout_s * 1000.0:.1f}",
        )
        while backend.event_wait(0):
            self._raise_if_worker_context_stale(backend=backend, generation=generation, action="stale_edge_drain")
            backend.event_consume()
            drain_count += 1
            elapsed_s = (time.monotonic_ns() - drain_start_ns) / 1_000_000_000.0
            if drain_count >= drain_max_edges or elapsed_s >= drain_timeout_s:
                try:
                    backend.trigger_low()
                except StaleCaptureBackend:
                    pass
                self._log_capture_phase(
                    "drain_stuck",
                    request_id=request_id,
                    generation=generation,
                    started_ns=phase_started_ns,
                    backend=backend,
                    drained_edges=drain_count,
                    elapsed_drain_ms=f"{elapsed_s * 1000.0:.1f}",
                )
                self._set_capture_failure_result(
                    "edge_drain_stuck",
                    request_id=request_id,
                    generation=generation,
                    backend_id=backend_id,
                    drained_edges=drain_count,
                    drain_elapsed_ms=float(elapsed_s * 1000.0),
                )
                return
        self._log_capture_phase(
            "drain_done",
            request_id=request_id,
            generation=generation,
            started_ns=phase_started_ns,
            backend=backend,
            drained_edges=drain_count,
        )

        trigger_asserted = False
        try:
            self._raise_if_worker_context_stale(backend=backend, generation=generation, action="trigger_high")
            # Raise trigger to MCU
            backend.trigger_high()
            trigger_asserted = True
            self._log_capture_phase(
                "trigger_high",
                request_id=request_id,
                generation=generation,
                started_ns=phase_started_ns,
                backend=backend,
                drained_edges=drain_count,
            )

            # Wait for MCU "flash fired" ACK
            try:
                self._log_capture_phase(
                    "edge_wait_start",
                    request_id=request_id,
                    generation=generation,
                    started_ns=phase_started_ns,
                    backend=backend,
                    timeout_s=timeout_s,
                    drained_edges=drain_count,
                )
                fired = backend.event_wait(timeout_s)
                self._raise_if_worker_context_stale(backend=backend, generation=generation, action="edge_wait")
                self._log_capture_phase(
                    "edge_wait_done",
                    request_id=request_id,
                    generation=generation,
                    started_ns=phase_started_ns,
                    backend=backend,
                    fired=bool(fired),
                    drained_edges=drain_count,
                )
            except StaleCaptureBackend:
                raise
            except Exception as e:
                print(f"Error while waiting for flash-fired edge: {e}")
                self._log_capture_phase(
                    "backend_error",
                    request_id=request_id,
                    generation=generation,
                    started_ns=phase_started_ns,
                    backend=backend,
                    error=str(e),
                    level="warning",
                )
                self._set_capture_failure_result(
                    "edge_wait_error",
                    request_id=request_id,
                    generation=generation,
                    error=str(e),
                    backend_id=backend_id,
                    drained_edges=drain_count,
                )
                return

            if not fired:
                print("Timed out waiting for flash-fired edge.")
                self._set_capture_failure_result(
                    "edge_timeout",
                    request_id=request_id,
                    generation=generation,
                    backend_id=backend_id,
                    drained_edges=drain_count,
                )
                return
            backend.event_consume()
            self._log_capture_phase(
                "edge_consume_done",
                request_id=request_id,
                generation=generation,
                started_ns=phase_started_ns,
                backend=backend,
                drained_edges=drain_count,
            )
        finally:
            if trigger_asserted:
                # Always deassert the Pi trigger, even if edge consumption or
                # GPIO waiting raises. Leaving it high can latch firmware flash
                # safety and block later captures until restart.
                backend.trigger_low()

        # Arm the time gate AFTER the ack
        self._raise_if_worker_context_stale(backend=backend, generation=generation, action="arm_start")
        arm_ns = time.monotonic_ns()
        self._log_capture_phase(
            "arm_start",
            request_id=request_id,
            generation=generation,
            started_ns=phase_started_ns,
            backend=backend,
            drained_edges=drain_count,
        )
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
            self._cap_request_id = request_id

            self._cap_done.clear()
            self._cap_result = None

            print(
                f"[Arm] request_id={request_id} gen={generation} cap_id={self._cap_id} "
                f"backend_id={backend_id} "
                f"base_mean={base_mean:.1f} base_std={base_std:.1f} "
                f"threshold={threshold:.1f} arm_ns={arm_ns}"
            )
            
    def capture_with_retry_sync(
        self,
        attempts=3,
        *,
        max_new_frames=6,
        attempt_timeout_s=1,
        small_sleep_between=0.02,
        success_reasons=("threshold",),
        request_id=None,
        generation=None,
        backend=None,
        backend_id=None,
    ) -> dict:
        """
        Block until we get a 'threshold' capture or exhaust attempts.
        Returns a completion payload on success.
        Raises RuntimeError on failure.
        """
        last_reason = None
        backend = self._resolve_capture_backend(backend)
        backend_id = backend_id if backend_id is not None else getattr(backend, "backend_id", None)

        for i in range(attempts):
            self._raise_if_worker_context_stale(backend=backend, generation=generation, action="retry_attempt")
            # For each attempt, suppress automatic emission; we'll emit once on success.
            try:
                self.capture_non_blocking(max_new_frames=max_new_frames,
                                        timeout_s=attempt_timeout_s,
                                        emit_signal=False,
                                        request_id=request_id,
                                        generation=generation,
                                        backend=backend,
                                        backend_id=backend_id)
            except StaleCaptureBackend as exc:
                self._log_capture_phase(
                    "stale_worker_exit",
                    request_id=request_id,
                    generation=generation,
                    backend=backend,
                    error=str(exc),
                    level="warning",
                )
                self._set_capture_failure_result(
                    "stale_backend",
                    request_id=request_id,
                    generation=generation,
                    error=str(exc),
                    backend_id=backend_id,
                )
                raise

            # Wait for the grabber to select a frame or report edge timeout.
            # Allow a tiny grace beyond attempt_timeout_s to cover scheduling jitter.
            waited = self._cap_done.wait(attempt_timeout_s + 0.2)
            if not waited:
                last_reason = "attempt_timeout"
                print(f"[Retry] attempt {i+1}/{attempts} timed out waiting for completion")
            else:
                res = self._cap_result or {}
                last_reason = res.get("reason", "unknown")
                if last_reason == "stale_backend":
                    raise StaleCaptureBackend(str(res.get("error") or "stale_backend"))
                print(f"[Retry] attempt {i+1}/{attempts} result reason={last_reason} "
                    f"mean={res.get('mean')} thr={res.get('threshold')}")

                # success criterion: first frame that *crossed* threshold
                if (last_reason in set(success_reasons)) and self.latest_frame is not None:
                    capture_info = dict(res)
                    capture_info.pop("arr", None)
                    return {
                        "status": "success",
                        "request_id": request_id,
                        "generation": generation,
                        "backend_id": backend_id,
                        "cap_id": int(res.get("cap_id") or 0),
                        "frame": self.latest_frame,
                        "capture_info": capture_info,
                        "reason": str(last_reason),
                    }

            # not acceptable → try again unless we’re out of attempts
            if i < attempts - 1:
                time.sleep(small_sleep_between)

        msg = f"Flash capture failed after {attempts} attempts (last_reason={last_reason})"
        raise RuntimeError(msg)
    
    def capture_with_retry_async(
        self,
        attempts=5,
        *,
        max_new_frames=10,
        attempt_timeout_s=1.0,
        small_sleep_between=0.05,
        success_reasons=("threshold",),
        request_id=None,
    ):
        """
        Start a capture with internal retries. On success, emits capture_completed_signal once.
        On failure, emits capture_failed_signal(str). Returns immediately.
        """
        if self._capture_worker_active.is_set():
            state = self.get_capture_state()
            print(f"[Camera] capture rejected request_id={request_id} reason=worker_active state={state}")
            return False
        if not self.camera:
            print(f"[Camera] capture rejected request_id={request_id} reason=camera_not_started state={self.get_capture_state()}")
            return False
        backend = self._get_current_capture_backend()
        if backend is None and hasattr(self, "_trig_chip_name"):
            try:
                backend = self._replace_capture_backend(reason="capture_queue_missing_backend")
            except Exception as exc:
                print(
                    f"[Camera] capture rejected request_id={request_id} "
                    f"reason=backend_unavailable error={exc} state={self.get_capture_state()}"
                )
                return False
        if backend is not None and not bool(getattr(backend, "is_open", False)):
            print(f"[Camera] capture rejected request_id={request_id} reason=backend_closed state={self.get_capture_state()}")
            return False
        backend_id = getattr(backend, "backend_id", None)

        self._capture_worker_active.set()
        with self._cv:
            self._capture_generation += 1
            generation = int(self._capture_generation)

        def _runner():
            payload = None
            try:
                payload = self.capture_with_retry_sync(
                    attempts=attempts,
                    max_new_frames=max_new_frames,
                    attempt_timeout_s=attempt_timeout_s,
                    small_sleep_between=small_sleep_between,
                    success_reasons=success_reasons,
                    request_id=request_id,
                    generation=generation,
                    backend=backend,
                    backend_id=backend_id,
                )
            except StaleCaptureBackend as e:
                capture_info = self.get_last_capture_result() or {}
                capture_info.pop("arr", None)
                payload = {
                    "status": "stale",
                    "stale": True,
                    "request_id": request_id,
                    "generation": generation,
                    "backend_id": backend_id,
                    "cap_id": int(capture_info.get("cap_id") or 0),
                    "frame": None,
                    "capture_info": capture_info,
                    "reason": str(capture_info.get("reason") or "stale_backend"),
                    "error": str(e),
                }
            except Exception as e:
                capture_info = self.get_last_capture_result() or {}
                capture_info.pop("arr", None)
                payload = {
                    "status": "failed",
                    "request_id": request_id,
                    "generation": generation,
                    "backend_id": backend_id,
                    "cap_id": int(capture_info.get("cap_id") or 0),
                    "frame": None,
                    "capture_info": capture_info,
                    "reason": str(capture_info.get("reason") or "retry_failed"),
                    "error": str(e),
                }
            finally:
                # Release the worker latch before any Qt signal delivery. A stranded
                # completion signal must not make every later capture look busy.
                self._capture_worker_active.clear()
                if getattr(self, "_capture_worker_thread", None) is threading.current_thread():
                    self._capture_worker_thread = None

            if not isinstance(payload, dict):
                payload = {
                    "status": "failed",
                    "request_id": request_id,
                    "generation": generation,
                    "backend_id": backend_id,
                    "cap_id": 0,
                    "frame": None,
                    "capture_info": {},
                    "reason": "missing_payload",
                    "error": "Capture worker produced no payload.",
                }

            current_generation = int(getattr(self, "_capture_generation", 0))
            current_backend = self._get_current_capture_backend()
            current_backend_id = getattr(current_backend, "backend_id", None)
            if backend_id is not None and current_backend_id is not None and backend_id != current_backend_id:
                payload = dict(payload)
                payload["status"] = "stale"
                payload["stale"] = True
                payload["stale_reason"] = "worker_backend_superseded"
                payload["current_backend_id"] = current_backend_id
            if int(payload.get("generation") or -1) != current_generation:
                payload = dict(payload)
                payload["status"] = "stale"
                payload["stale"] = True
                payload.setdefault("stale_reason", "worker_generation_superseded")
                payload["current_generation"] = current_generation

            payload["worker_active"] = bool(self._capture_worker_active.is_set())
            print(
                f"[Camera] capture complete request_id={request_id} "
                f"status={payload.get('status')} cap_id={payload.get('cap_id')} "
                f"gen={payload.get('generation')} current_gen={current_generation} "
                f"backend_id={payload.get('backend_id')} current_backend_id={current_backend_id} "
                f"worker_active={payload.get('worker_active')}"
            )

            try:
                self.capture_completed_signal.emit(payload)
            except Exception as exc:
                print(f"[Camera] capture completion signal failed request_id={request_id}: {exc}")

            status = str(payload.get("status") or "")
            if status == "success":
                try:
                    self.image_captured_signal.emit()
                except Exception as exc:
                    print(f"[Camera] legacy image_captured_signal failed request_id={request_id}: {exc}")
            elif status == "failed":
                err = str(payload.get("error") or payload.get("reason") or "Capture failed.")
                try:
                    self.capture_failed_signal.emit(err)
                except Exception as exc:
                    print(f"[Camera] legacy capture_failed_signal failed request_id={request_id}: {exc}")

        t = threading.Thread(target=_runner, daemon=True)
        self._capture_worker_thread = t
        print(
            f"[Camera] capture queued request_id={request_id} gen={generation} "
            f"backend_id={backend_id} "
            f"attempts={attempts} max_new_frames={max_new_frames} timeout_s={attempt_timeout_s}"
        )
        t.start()
        return True

class RefuelCamera(QObject):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.exposure_time = 20_000  # us
        self.frame_duration_us = self.exposure_time
        self.analogue_gain = 1.0
        self.led_pin = 27
        # self._chip_name = "gpiochip4"  # adjust if needed on your Pi
        self._chip_name, off = _gpiofind("GPIO"+str(self.led_pin))
        # v1/v2 compatible output line
        self._led = _make_output_line(self._chip_name, off,
                                             initial=0, consumer="refuel_led")

    def get_camera_control_defaults(self):
        exposure_time = int(self.exposure_time)
        frame_duration = int(getattr(self, "frame_duration_us", exposure_time))
        return {
            "FrameDurationLimits": (frame_duration, frame_duration),
            "ExposureTime": exposure_time,
            "AeEnable": False,
            "AwbEnable": False,
            "AnalogueGain": float(self.analogue_gain),
        }

    def start_camera(self):
        if self.camera is not None:
            return

        from picamera2 import Picamera2
        camera = Picamera2(0)
        try:
            camera.configure(camera.create_still_configuration(
                main={"size": camera.sensor_resolution, "format": "RGB888"}
            ))
            camera.set_controls(self.get_camera_control_defaults())
            camera.start()
        except Exception:
            try:
                camera.close()
            except Exception:
                pass
            raise
        self.camera = camera

    def capture_image(self):
        return self.camera.capture_array() if self.camera else None

    def stop_camera(self):
        camera_error = None
        led_error = None
        if self.camera:
            try:
                self.camera.stop()
            except Exception as exc:
                camera_error = exc
            try:
                self.camera.close()
            except Exception as exc:
                if camera_error is None:
                    camera_error = exc
            self.camera = None
        # ensure LED off on stop
        try:
            self._led.set_value(0)
        except Exception as exc:
            led_error = exc
        if led_error is not None:
            raise led_error
        if camera_error is not None:
            raise camera_error

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
RESET_REPORT = 0xF9
CMD_QUEUE_ACK = 0xFE
PAUSE_AFTER_SEQ32 = 0xFF

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
TAG_LAST_ACCEPTED_CMD = 0x53
TAG_LAST_RETIRED_CMD = 0x54
TAG_PAUSE_AFTER_CMD = 0x55
TAG_PAUSE_WATERMARK_REACHED = 0x56
TAG_TRANSPORT_PAUSED = 0x57
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

TAG_RESET_SEQ32             = 0x10
TAG_RESET_CAUSE             = 0x11
TAG_RESET_FLAGS             = 0x12
TAG_RESET_LAST_FAULT        = 0x13
TAG_RESET_LAST_TASK         = 0x14
TAG_RESET_BOOT_COUNT        = 0x15
TAG_RESET_FAULT_COUNT       = 0x16
TAG_RESET_WATCHDOG_COUNT    = 0x17
TAG_RESET_WATCHDOG_STICKY_CT = 0x18
TAG_RESET_WATCHDOG_RAW_SR   = 0x19
TAG_RESET_UPTIME_MS         = 0x1A
TAG_RESET_BOOT_STAGE        = 0x1B
TAG_RESET_RECOVERY_BOOT     = 0x1C
TAG_RESET_FAULT_STAGE       = 0x1D
TAG_RESET_WATCHDOG_LATE_TASK = 0x1E
TAG_RESET_ACTIVE_COMMAND    = 0x1F
TAG_RESET_RCC_FLAGS         = 0x20
TAG_RESET_TASK_NAME4        = 0x21

ACK_TLV_SEQ32 = 0x10
ACK_TLV_RESULT = 0x11
ACK_TLV_EXPECTED_SEQ32 = 0x12
ACK_TLV_CAPABILITIES = 0x13

ACK_RESULT_ACCEPTED = 1
ACK_RESULT_DUPLICATE = 2
ACK_RESULT_GAP = 3
ACK_RESULT_BUSY = 4
ACK_RESULT_WATERMARK_SET = 5
ACK_RESULT_WATERMARK_REJECTED = 6

ACK_RESULT_NAMES = {
    ACK_RESULT_ACCEPTED: "accepted",
    ACK_RESULT_DUPLICATE: "duplicate",
    ACK_RESULT_GAP: "gap",
    ACK_RESULT_BUSY: "busy",
    ACK_RESULT_WATERMARK_SET: "watermark_set",
    ACK_RESULT_WATERMARK_REJECTED: "watermark_rejected",
}

TRANSPORT_CAP_QUEUE_ACK = 1 << 0
TRANSPORT_CAP_STATUS_FRONTIERS = 1 << 1
TRANSPORT_CAP_PAUSE_AFTER_SEQ32 = 1 << 2
TRANSPORT_CAP_SESSION_SEQ_PERSIST = 1 << 3
REQUIRED_TRANSPORT_CAPS = (
    TRANSPORT_CAP_QUEUE_ACK
    | TRANSPORT_CAP_STATUS_FRONTIERS
    | TRANSPORT_CAP_PAUSE_AFTER_SEQ32
    | TRANSPORT_CAP_SESSION_SEQ_PERSIST
)

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
    TAG_DISP_FREQ:    ("Disp_freq",    2, False),
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
    TAG_LAST_ACCEPTED_CMD: ("Last_accepted", 4, False),
    TAG_LAST_RETIRED_CMD: ("Last_retired", 4, False),
    TAG_PAUSE_AFTER_CMD: ("Pause_after_seq32", 4, False),
    TAG_PAUSE_WATERMARK_REACHED: ("Pause_watermark_reached", 1, False),
    TAG_TRANSPORT_PAUSED: ("Transport_paused", 1, False),
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

    'SET_GRIPPER_PARAMS': 0x62,
    'REFUEL_VACUUM_ENTER': 0x65,
    'REFUEL_VACUUM_SET_TARGET': 0x66,
    'REFUEL_VACUUM_EXIT': 0x67,
    'SET_REG_RECOVERY_PROFILE': 0x68,
    'SET_REG_SLEW_PROFILE': 0x69,
    'SET_REG_READY_PROFILE': 0x6A,
    'RESTORE_REG_PROFILE': 0x6B,
    'QUERY_REG_PROFILE': 0x6C,

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
    'BYE_DONE'    : 0xF8,
    'RESET_REPORT': 0xF9,
    'QUEUE_ACK'   : 0xFE,
    'PAUSE_AFTER_SEQ32': 0xFF,
}

CMD_NAME_BY_CODE = {value: key.lower() for key, value in CMD_MAP.items()}

REGULATOR_PROFILE_CHANNELS = {
    "print": 0,
    "p": 0,
    0: 0,
    "refuel": 1,
    "r": 1,
    1: 1,
}

REGULATOR_PROFILE_RESTORE_SOURCES = {
    "baseline": 0,
    "defaults": 1,
}

REGULATOR_PROFILE_RECOVERY_BOUNDS = {
    "active_ticks": (0, 20),
    "base_boost_hz": (0, 6000),
    "pulse_coeff_hz_per_us": (0, 4),
    "pressure_coeff_hz_per_raw": (0, 4),
    "max_boost_hz": (0, 12000),
    "recovery_floor_hz": (0, 5000),
    "recovery_exit_error_raw": (1, 30),
    "max_extend_ticks": (0, 10),
}

REGULATOR_PROFILE_RECOVERY_BOOL_FIELDS = (
    "allow_extend_while_undershoot",
    "boost_only_when_undershoot",
    "linear_decay",
)

REGULATOR_PROFILE_SLEW_BOUNDS = {
    "max_hz_delta_up_per_loop": (1, 2500),
    "max_hz_delta_down_per_loop": (1, 2500),
    "recovery_bypass_slew_ticks": (0, 5),
}

REGULATOR_PROFILE_READY_BOUNDS = {
    "ready_tol_raw": (1, 25),
    "consecutive_samples": (1, 5),
}


def _pack_regulator_profile_u16_pair(low, high):
    return (int(high) << 16) | int(low)


def _normalize_regulator_profile_channel(channel):
    if isinstance(channel, bool):
        raise ValueError(f"invalid regulator channel: {channel}")
    if isinstance(channel, str):
        channel = channel.strip().lower()
    if channel not in REGULATOR_PROFILE_CHANNELS:
        raise ValueError(f"invalid regulator channel: {channel}")
    return REGULATOR_PROFILE_CHANNELS[channel]


def _normalize_regulator_profile_restore_source(source):
    if isinstance(source, str):
        source = source.strip().lower()
    if source not in REGULATOR_PROFILE_RESTORE_SOURCES:
        raise ValueError(f"invalid regulator restore source: {source}")
    return REGULATOR_PROFILE_RESTORE_SOURCES[source]


def _normalize_regulator_profile_restore_mask(channels):
    if isinstance(channels, str):
        normalized = channels.strip().lower()
        if normalized == "both":
            return 0x3
        channels = [normalized]
    elif isinstance(channels, int) and not isinstance(channels, bool):
        if channels in (0x1, 0x2, 0x3):
            return channels
        raise ValueError(f"invalid regulator restore channel mask: {channels}")
    else:
        try:
            channels = list(channels)
        except TypeError as exc:
            raise ValueError(f"invalid regulator restore channels: {channels}") from exc

    mask = 0
    for channel in channels:
        code = _normalize_regulator_profile_channel(channel)
        mask |= 0x1 if code == 0 else 0x2
    if mask == 0:
        raise ValueError("regulator restore channels cannot be empty")
    return mask


def _require_regulator_profile_int(config, field, min_value, max_value):
    if field not in config:
        raise ValueError(f"missing regulator profile field: {field}")
    value = config[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"regulator profile field {field} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(
            f"regulator profile field {field} out of range: {value} not in ({min_value},{max_value})"
        )
    return value


def _require_regulator_profile_bool(config, field):
    if field not in config:
        raise ValueError(f"missing regulator profile field: {field}")
    value = config[field]
    if not isinstance(value, bool):
        raise ValueError(f"regulator profile field {field} must be a boolean")
    return value


def _validate_regulator_profile_config(config, bounds, bool_fields=()):
    if not isinstance(config, dict):
        raise ValueError("regulator profile config must be a dictionary")
    validated = {}
    for field, (min_value, max_value) in bounds.items():
        validated[field] = _require_regulator_profile_int(
            config,
            field,
            min_value,
            max_value,
        )
    for field in bool_fields:
        validated[field] = _require_regulator_profile_bool(config, field)
    return validated

CRASHLOG_FLAG_PENDING = 0x00000002
CRASHLOG_FLAG_WDT_ARM_STICKY = 0x00000004

RESET_CAUSE_NAMES = {
    0: "unknown",
    1: "power",
    2: "pin_reset",
    3: "software",
    4: "iwdg",
    5: "wwdg",
    6: "low_power",
}

RESET_CAUSE_SUMMARIES = {
    "power": "Board restarted after power/brownout reset.",
    "pin_reset": "Board restarted after external reset pin event.",
    "software": "Board restarted after software reset.",
    "low_power": "Board restarted after low-power reset.",
}

RESET_RCC_FLAG_NAMES = {
    0x80000000: "low_power",
    0x40000000: "wwdg",
    0x20000000: "iwdg",
    0x10000000: "software",
    0x08000000: "por",
    0x04000000: "pin_reset",
    0x02000000: "bor",
}

CRASH_FAULT_NAMES = {
    0: "none",
    1: "hardfault",
    2: "memmanage",
    3: "busfault",
    4: "usagefault",
    5: "nmi",
    6: "stack_overflow",
    7: "assert",
    8: "error_handler",
    9: "wdt",
}

CRASH_TASK_NAMES = {
    0: "none",
    1: "boot",
    2: "orchestrator",
    3: "status",
    4: "pressure",
    5: "print_regulator",
    6: "refuel_regulator",
    7: "home_x",
    8: "home_y",
    9: "home_z",
    10: "home_print_regulator",
    11: "home_refuel_regulator",
    12: "printer",
    13: "gripper",
    14: "led",
    15: "led_fade",
    16: "log_stats",
    17: "heartbeat",
    18: "watchdog",
    19: "idle",
    20: "timer",
}

CRASH_BOOT_STAGE_NAMES = {
    0: "reset",
    1: "hal_init",
    2: "crashlog_ready",
    3: "orchestrator_ready",
    4: "logger_ready",
    5: "comm_init",
    6: "comm_rx_armed",
    7: "comm_rx_rearmed",
    8: "comm_ready",
    9: "watchdog_task_ready",
    10: "hello_rx",
    11: "hello_ack",
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

def build_frame(cmd, seq32, *, p1=None, p2=None, p3=None):
    TAG_SEQ32 = ACK_TLV_SEQ32
    seq8 = seq32 & 0xFF
    payload = bytearray([cmd & 0xFF, seq8])
    # SEQ32 TLV
    payload += bytes([TAG_SEQ32, 4]) + struct.pack("<I", seq32 & 0xFFFFFFFF)
    for tag, value in (
        (Command.TAG_P1, p1),
        (Command.TAG_P2, p2),
        (Command.TAG_P3, p3),
    ):
        if value is None:
            continue
        payload += bytes([tag, 4]) + struct.pack("<I", int(value) & 0xFFFFFFFF)
    if len(payload) > 255:
        raise ValueError("Payload length exceeds 255 bytes")
    header  = bytes([START_BYTE, len(payload)])
    c       = crc16_x25(payload)
    tail    = struct.pack("<H", c)
    return header + payload + tail

def parse_tlvs(payload: bytes) -> dict[int, bytes]:
    idx = 0
    result = {}
    while idx + 2 <= len(payload):
        tag = payload[idx]
        length = payload[idx + 1]
        idx += 2
        if idx + length > len(payload):
            logger.warning("Malformed TLV payload: tag=0x%02X len=%d exceeds payload", tag, length)
            break
        result[tag] = payload[idx:idx + length]
        idx += length
    return result

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
            logger.warning("Malformed TLV payload: tag=0x%02X len=%d exceeds payload", tag, length)
            break  # malformed/truncated
        raw = payload[idx:idx+length]
        idx += length

        entry = TAG_MAP.get(tag)
        if not entry:
            logger.warning("Unknown TLV tag: 0x%02X", tag)
            continue  # unknown tag
        name, expected_len, signed = entry
        if expected_len != length:
            # length mismatch; skip or handle as error
            logger.warning(
                "TLV length mismatch for %s: expected=%d got=%d",
                name,
                expected_len,
                length,
            )
            continue

        value = int.from_bytes(raw, byteorder="little", signed=signed)
        result[name] = value

    return result


def default_flash_safety_state() -> dict:
    return {
        "flash_session_armed": False,
        "flash_fault_latched": False,
        "flash_fault_reason": "",
    }


def parse_flash_safety_log_event(text: str) -> dict | None:
    message = str(text or "").strip()
    if message == "FLASH_ARMED":
        return {"kind": "armed"}

    m = re.match(r"^FLASH_DISARMED(?:\s+reason=(?P<reason>[a-z_]+))?$", message)
    if m:
        return {"kind": "disarmed", "reason": (m.group("reason") or "").strip().lower()}

    m = re.match(r"^FLASH_FAULT(?:\s+reason=(?P<reason>[a-z_]+))?$", message)
    if m:
        return {"kind": "fault", "reason": (m.group("reason") or "").strip().lower()}

    return None


def apply_flash_safety_log_event(state: dict | None, event: dict | None) -> dict:
    next_state = dict(default_flash_safety_state())
    if isinstance(state, dict):
        next_state.update(
            {
                "flash_session_armed": bool(state.get("flash_session_armed", False)),
                "flash_fault_latched": bool(state.get("flash_fault_latched", False)),
                "flash_fault_reason": str(state.get("flash_fault_reason", "") or ""),
            }
        )

    if not isinstance(event, dict):
        return next_state

    kind = str(event.get("kind", "")).strip().lower()
    reason = str(event.get("reason", "") or "").strip().lower()

    if kind == "armed":
        next_state["flash_session_armed"] = True
        next_state["flash_fault_latched"] = False
        next_state["flash_fault_reason"] = ""
        return next_state

    if kind == "fault":
        next_state["flash_session_armed"] = False
        next_state["flash_fault_latched"] = True
        next_state["flash_fault_reason"] = reason
        return next_state

    if kind == "disarmed":
        next_state["flash_session_armed"] = False
        if reason in ("stop", "shutdown"):
            next_state["flash_fault_latched"] = False
            next_state["flash_fault_reason"] = ""
        elif reason == "fault":
            next_state["flash_fault_latched"] = True
        return next_state

    return next_state

class SerialReader(QThread):
    status_received = Signal(dict)
    ackReceived     = Signal(object)  # dict with ack_cmd, seq8, seq32
    resetReportReceived = Signal(dict)
    readerStopped = Signal(dict)

    def __init__(self, ser, parent=None):
        super().__init__(parent)
        self.ser = ser
        self._stop_requested = False

    def _reader_stop_info(self, reason, exc=None):
        info = {
            "reason": str(reason or "unknown"),
            "requested_stop": bool(self._stop_requested),
        }
        if exc is not None:
            info["exception_type"] = exc.__class__.__name__
            info["message"] = str(exc)
        return info
        
    @staticmethod
    def _parse_ack(payload: bytes) -> dict:
        """
        payload layout: [ack_cmd, seq8, (TLVs...)]
        Parse common ACK metadata and any optional transport-control TLVs.
        """
        if not payload:
            return {
                "ack_cmd": None,
                "seq8": None,
                "seq32": None,
                "ack_result": None,
                "expected_seq32": None,
                "capabilities": None,
            }

        ack_cmd = payload[0]
        seq8 = payload[1] if len(payload) >= 2 else 0
        seq32 = None
        ack_result = None
        expected_seq32 = None
        capabilities = None
        i = 2
        while i + 1 < len(payload):
            tag = payload[i]; ln = payload[i+1]; i += 2
            if i + ln > len(payload):
                break
            if tag == ACK_TLV_SEQ32 and ln == 4:
                seq32 = struct.unpack_from("<I", payload, i)[0]
            elif tag == ACK_TLV_RESULT and ln == 1:
                ack_result = ACK_RESULT_NAMES.get(payload[i], f"result_{payload[i]}")
            elif tag == ACK_TLV_EXPECTED_SEQ32 and ln == 4:
                expected_seq32 = struct.unpack_from("<I", payload, i)[0]
            elif tag == ACK_TLV_CAPABILITIES and ln == 4:
                capabilities = struct.unpack_from("<I", payload, i)[0]
            i += ln
        return {
            "ack_cmd": ack_cmd,
            "seq8": seq8,
            "seq32": seq32,
            "ack_result": ack_result,
            "expected_seq32": expected_seq32,
            "capabilities": capabilities,
        }

    @staticmethod
    def _parse_reset_report(payload: bytes) -> dict | None:
        if len(payload) < 2 or payload[0] != RESET_REPORT:
            return None

        seq8 = payload[1]
        tlvs = parse_tlvs(payload[2:])

        def _u8(tag, default=0):
            raw = tlvs.get(tag)
            if raw is None or len(raw) != 1:
                return default
            return raw[0]

        def _u32(tag, default=0):
            raw = tlvs.get(tag)
            if raw is None or len(raw) != 4:
                return default
            return struct.unpack("<I", raw)[0]

        def _u32_or_none(tag):
            raw = tlvs.get(tag)
            if raw is None or len(raw) != 4:
                return None
            return struct.unpack("<I", raw)[0]

        def _name4_or_none(tag):
            raw = tlvs.get(tag)
            if raw is None or len(raw) != 4:
                return None
            text = raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            return text or None

        reset_cause = _u8(TAG_RESET_CAUSE)
        flags = _u32(TAG_RESET_FLAGS)
        reset_flags_raw = _u32_or_none(TAG_RESET_RCC_FLAGS)
        fault_task_name4 = _name4_or_none(TAG_RESET_TASK_NAME4)
        last_fault = _u8(TAG_RESET_LAST_FAULT)
        last_task = _u8(TAG_RESET_LAST_TASK)
        boot_stage = _u8(TAG_RESET_BOOT_STAGE)
        fault_stage = _u8(TAG_RESET_FAULT_STAGE, boot_stage)
        watchdog_late_task = _u8(TAG_RESET_WATCHDOG_LATE_TASK)
        active_command = _u8(TAG_RESET_ACTIVE_COMMAND)
        pending = bool(flags & CRASHLOG_FLAG_PENDING)
        sticky = bool(flags & CRASHLOG_FLAG_WDT_ARM_STICKY)

        reset_cause_name = RESET_CAUSE_NAMES.get(reset_cause, f"reset_{reset_cause}")
        last_fault_name = CRASH_FAULT_NAMES.get(last_fault, f"fault_{last_fault}")
        last_task_name = CRASH_TASK_NAMES.get(last_task, f"task_{last_task}")
        boot_stage_name = CRASH_BOOT_STAGE_NAMES.get(boot_stage, f"stage_{boot_stage}")
        fault_stage_name = CRASH_BOOT_STAGE_NAMES.get(fault_stage, f"stage_{fault_stage}")
        watchdog_late_task_name = CRASH_TASK_NAMES.get(watchdog_late_task, f"task_{watchdog_late_task}")
        active_command_name = CMD_NAME_BY_CODE.get(active_command, f"cmd_0x{active_command:02x}")
        reset_flag_names = [
            name
            for bit, name in RESET_RCC_FLAG_NAMES.items()
            if reset_flags_raw is not None and (reset_flags_raw & bit)
        ]
        reset_flag_summary = ", ".join(reset_flag_names)

        if reset_cause_name == "iwdg":
            summary = "Board restarted after watchdog reset."
        elif reset_cause_name == "wwdg":
            summary = "Board restarted after window watchdog reset."
        elif pending:
            summary = "Board restarted after a retained crash event."
        else:
            summary = RESET_CAUSE_SUMMARIES.get(
                reset_cause_name,
                f"Board restarted after {reset_cause_name} reset.",
            )

        if pending and last_fault_name == "wdt":
            details = []
            if active_command != 0:
                details.append(f"during {active_command_name}")
            if last_task_name != "none":
                details.append(f"{last_task_name} active")
            if watchdog_late_task_name != "none":
                details.append(f"first late task {watchdog_late_task_name}")
            details.append(f"fault stage {fault_stage_name}")
            summary += " Watchdog starvation: " + ", ".join(details) + "."
        elif last_fault_name != "none":
            task_label = f"{last_task_name} task"
            if fault_task_name4:
                task_label = f"{task_label} ({fault_task_name4})"
            summary += f" Last fault: {last_fault_name} in {task_label} at stage {fault_stage_name}."
        elif sticky:
            summary += f" Sticky watchdog state was recorded at stage {boot_stage_name}."

        return {
            "seq8": seq8,
            "seq32": _u32(TAG_RESET_SEQ32),
            "reset_cause": reset_cause,
            "reset_cause_name": reset_cause_name,
            "flags": flags,
            "reset_flags_raw": reset_flags_raw,
            "reset_flag_names": reset_flag_names,
            "reset_flag_summary": reset_flag_summary,
            "fault_task_name4": fault_task_name4,
            "pending": pending,
            "sticky": sticky,
            "last_fault": last_fault,
            "last_fault_name": last_fault_name,
            "last_task": last_task,
            "last_task_name": last_task_name,
            "watchdog_late_task": watchdog_late_task,
            "watchdog_late_task_name": watchdog_late_task_name,
            "active_command": active_command,
            "active_command_name": active_command_name,
            "boot_count": _u32(TAG_RESET_BOOT_COUNT),
            "fault_count": _u32(TAG_RESET_FAULT_COUNT),
            "watchdog_reset_count": _u32(TAG_RESET_WATCHDOG_COUNT),
            "watchdog_sticky_count": _u32(TAG_RESET_WATCHDOG_STICKY_CT),
            "watchdog_raw_status": _u32(TAG_RESET_WATCHDOG_RAW_SR),
            "uptime_ms": _u32(TAG_RESET_UPTIME_MS),
            "boot_stage": boot_stage,
            "boot_stage_name": boot_stage_name,
            "fault_stage": fault_stage,
            "fault_stage_name": fault_stage_name,
            "recovery_boot": bool(_u8(TAG_RESET_RECOVERY_BOOT)),
            "summary": summary,
        }


    def run(self):
        stop_info = None
        try:
            while True:
                if self.isInterruptionRequested():
                    stop_info = self._reader_stop_info("requested_stop")
                    break
                if not self.ser or not self.ser.is_open:
                    reason = "requested_stop" if self._stop_requested else "serial_closed"
                    stop_info = self._reader_stop_info(reason)
                    break
                hdr = self.ser.read(2)
                if len(hdr)!=2 or hdr[0]!=START_BYTE: continue
                length = hdr[1]
                payload = self.ser.read(length)
                if len(payload) != length: continue
                if length == 0:
                    continue
                tail = self.ser.read(2)
                if len(tail) != 2: continue
                rec_crc = tail[0] | (tail[1]<<8)
                if crc16_x25(payload)!=rec_crc: continue

                cmd = payload[0]
                if cmd == CMD_STATUS:
                    data = parse_tlv_payload(payload[1:])
                    data["__host_rx_monotonic_ns"] = int(time.monotonic_ns())
                    self.status_received.emit(data)
                elif cmd == RESET_REPORT:
                    report = self._parse_reset_report(payload)
                    if report is not None:
                        self.resetReportReceived.emit(report)
                else:
                    # HELLO_ACK, BYE_ACK, CLEAR_ACK, etc
                    # print(f"Non-status frame: cmd=0x{cmd:02X}, len={length}")
                    ack = self._parse_ack(payload)
                    if ack.get("ack_cmd") is None:
                        continue
                    print(f"Ack received: {ack['ack_cmd']} seq8={ack['seq8']} seq32={ack['seq32']}")
                    self.ackReceived.emit(ack)

        except (serial.SerialException, OSError, TypeError, ValueError, IndexError) as exc:
            reason = "requested_stop" if self._stop_requested else "exception"
            stop_info = self._reader_stop_info(reason, exc)
        finally:
            if stop_info is None:
                reason = "requested_stop" if self._stop_requested else "completed"
                stop_info = self._reader_stop_info(reason)
            self.readerStopped.emit(stop_info)

    def request_stop(self):
        if self._stop_requested:
            return

        self._stop_requested = True
        self.requestInterruption()
        try:
            if hasattr(self.ser, "cancel_read"):
                self.ser.cancel_read()
        except Exception:
            pass

    def wait_for_stop(self, timeout_ms):
        try:
            return (not self.isRunning()) or bool(self.wait(timeout_ms))
        except Exception:
            return False

    def stop(self):
        self.request_stop()
        return self.wait_for_stop(READER_STOP_FALLBACK_WAIT_MS)

class LogReader(QThread):
    lineReceived   = Signal(str)     # existing
    statsUpdated   = Signal(object)  # emits a dict with parsed stats (see below)
    messageReceived = Signal(str)
    flashStateChanged = Signal(object)
    

    def __init__(self, baud=115200, parent=None, log_port="/dev/ttyUSB0", history_len=360, serial_factory=serial.Serial):
        super().__init__(parent)
        self.ser = serial_factory(log_port, baud, timeout=LOG_READER_SERIAL_TIMEOUT_S)
        self._running = True
        self._stop_requested = False
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
        self._flash_state = default_flash_safety_state()

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
        while self._running and not self.isInterruptionRequested():
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

    def _close_serial_port(self):
        ser = getattr(self, "ser", None)
        try:
            if ser is not None and getattr(ser, "is_open", False):
                ser.close()
        except Exception:
            pass

    def request_stop(self):
        if self._stop_requested:
            return

        self._stop_requested = True
        self._running = False

        try:
            self.requestInterruption()
        except Exception:
            pass

        try:
            ser = getattr(self, "ser", None)
            if ser is not None and hasattr(ser, "cancel_read"):
                ser.cancel_read()
        except Exception:
            pass

    def wait_for_stop(self, timeout_ms):
        wait_started = time.monotonic()
        try:
            stopped = (not self.isRunning()) or bool(self.wait(timeout_ms))
        except Exception:
            stopped = False
        wait_elapsed_ms = int((time.monotonic() - wait_started) * 1000)

        if stopped:
            close_started = time.monotonic()
            self._close_serial_port()
            close_elapsed_ms = int((time.monotonic() - close_started) * 1000)
            print(
                "LogReader stop timing: "
                f"wait={wait_elapsed_ms} ms, close={close_elapsed_ms} ms"
            )
        else:
            print(
                "LogReader stop timing: "
                f"wait timed out after {wait_elapsed_ms} ms (budget {timeout_ms} ms)"
            )
        return stopped

    def stop(self):
        self.request_stop()
        return self.wait_for_stop(READER_STOP_FALLBACK_WAIT_MS)

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
        flash_event = parse_flash_safety_log_event(entry["text"])
        if flash_event is not None:
            self._flash_state = apply_flash_safety_log_event(self._flash_state, flash_event)
            self.flashStateChanged.emit(dict(self._flash_state))

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
                 handler=None, kwargs=None, trace_metadata=None):
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
        if len(self.payload) > 255:
            raise ValueError("Payload length exceeds 255 bytes")

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
        self.trace_metadata = dict(trace_metadata or {})
        self.send_attempts = 0
        self.lifecycle_ns = {
            "queued": int(time.monotonic_ns()),
            "sent": None,
            "accepted": None,
            "executing": None,
            "completed": None,
            "canceled": None,
        }
        self.signal = f'<{command_type} {self.command_number} {param1},{param2},{param3}>'


    def mark_as_sent(self):
        self.status = "Sent"
        if self.lifecycle_ns["sent"] is None:
            self.lifecycle_ns["sent"] = int(time.monotonic_ns())
            return True
        return False

    def mark_as_accepted(self):
        if self.status in ("Completed", "Canceled"):
            return False
        self.status = "Accepted"
        if self.lifecycle_ns["accepted"] is None:
            self.lifecycle_ns["accepted"] = int(time.monotonic_ns())
            return True
        return False

    def mark_as_executing(self):
        if self.status in ("Completed", "Canceled"):
            return False
        self.status = "Executing"
        if self.lifecycle_ns["executing"] is None:
            self.lifecycle_ns["executing"] = int(time.monotonic_ns())
            return True
        return False

    def mark_as_completed(self):
        self.status = "Completed"
        if self.lifecycle_ns["completed"] is None:
            self.lifecycle_ns["completed"] = int(time.monotonic_ns())
            self.execute_handler()
            return True
        return False

    def mark_as_canceled(self):
        self.status = "Canceled"
        if self.lifecycle_ns["canceled"] is None:
            self.lifecycle_ns["canceled"] = int(time.monotonic_ns())
            return True
        return False

    def reset_for_resend(self):
        if self.status in ("Completed", "Canceled"):
            return False
        self.status = "Added"
        self.lifecycle_ns["sent"] = None
        self.lifecycle_ns["accepted"] = None
        self.lifecycle_ns["executing"] = None
        return True

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

    def __init__(self, event_callback=None):
        super().__init__()  # Initialize the QObject
        self.queue = deque()
        self.completed = deque()
        self.command_number = 0
        self.max_inflight_commands = 4  # Sliding-window size for accepted or pending-ack commands
        self._event_callback = event_callback

    def _emit_command_event(self, command, event_name):
        if callable(self._event_callback):
            try:
                self._event_callback(command, str(event_name))
            except Exception:
                pass

    def add_command(self, command_type, param1, param2, param3, handler=None, kwargs=None, trace_metadata=None):
        """Add a command to the queue."""
        
        
        self.command_number += 1
        # print(f'type params: {self.command_number}-{command_type} {type(param1)} {type(param2)} {type(param3)}')
        #print(f'Adding command: {command_type} {param1} {param2} {param3}')
        command = Command(
            self.command_number,
            command_type,
            param1,
            param2,
            param3,
            handler,
            kwargs,
            trace_metadata=trace_metadata,
        )
        self.queue.append(command)
        self._emit_command_event(command, "queued")
        return command

    def get_inflight_command_count(self):
        """Return the number of non-terminal commands currently occupying the transport window."""
        active_statuses = {"Sent", "Accepted", "Executing"}
        return len([command for command in self.queue if command.status in active_statuses])

    def get_next_command(self):
        """Return the next locally queued command if the sliding window has capacity."""
        if self.queue and self.get_inflight_command_count() < self.max_inflight_commands:
            for command in self.queue:
                if command.status == "Added":
                    return command
        return None

    def _trim_terminal_commands(self):
        while self.queue and self.queue[0].status in {"Completed", "Canceled"}:
            completed_command = self.queue.popleft()
            self.completed.append(completed_command)
            if len(self.completed) > 100:
                self.completed.popleft()

    def mark_command_accepted(self, command_number):
        target = int(command_number or 0)
        for cmd in self.queue:
            if cmd.command_number == target:
                if cmd.mark_as_accepted():
                    self._emit_command_event(cmd, "accepted")
                break
        self._trim_terminal_commands()
        self.queue_updated.emit()

    def mark_for_resend_from(self, command_number):
        floor = int(command_number or 0)
        for cmd in self.queue:
            if cmd.command_number >= floor and cmd.status in {"Added", "Sent"}:
                if cmd.reset_for_resend():
                    self._emit_command_event(cmd, "requeued")
        self.queue_updated.emit()

    def update_command_status(
        self,
        current_executing_command,
        last_completed_command,
        last_accepted_command=None,
        last_retired_command=None,
    ):
        if (
            current_executing_command is None
            and last_completed_command is None
            and last_accepted_command is None
            and last_retired_command is None
        ):
            return

        curr = int(current_executing_command or -1)
        last = int(last_completed_command  or -1)
        accepted = int(last_accepted_command if last_accepted_command is not None else last)
        retired = int(last_retired_command if last_retired_command is not None else last)

        for cmd in list(self.queue):
            if cmd.status in {"Added", "Sent"} and cmd.command_number <= accepted:
                if cmd.mark_as_accepted():
                    self._emit_command_event(cmd, "accepted")

        # 1) Complete everything <= last.
        for cmd in list(self.queue):
            if cmd.status in {"Sent", "Accepted", "Executing"} and cmd.command_number <= last:
                if cmd.mark_as_completed():
                    self._emit_command_event(cmd, "completed")

        # 2) Retire contiguous canceled commands after the completed frontier.
        for cmd in list(self.queue):
            if cmd.status in {"Sent", "Accepted", "Executing"} and last < cmd.command_number <= retired:
                if cmd.mark_as_canceled():
                    self._emit_command_event(cmd, "canceled")

        # 3) Optionally mark one accepted command in (last, curr] as executing.
        if curr >= 0 and curr > last:
            cand = None
            for cmd in self.queue:
                if cmd.status in {"Accepted", "Sent"} and last < cmd.command_number <= curr:
                    cand = cmd
                    break
            if cand:
                if cand.mark_as_executing():
                    self._emit_command_event(cand, "executing")

        self._trim_terminal_commands()

        if not self.queue:
            self.commands_completed.emit()

        self.queue_updated.emit()

    def clear_queue(self, *, reset_counter=True):
        """Clear queue state; keep the seq counter unless a whole transport session is being reset."""
        self.queue.clear()
        self.completed.clear()
        if reset_counter:
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
    reset_report_received = Signal(dict)
    serial_connection_lost = Signal(dict)
    all_calibration_droplets_printed = Signal()  # Signal to emit when all calibration droplets are printed
    require_gripper_confirmation = Signal(str)   # "OPEN" or "CLOSE"
    log_stats_updated = Signal(object)  # Signal to emit when log stats are updated
    log_message_received = Signal(str)  # Signal to emit when a log message is received
    flash_state_updated = Signal(object)

    def __init__(
        self,
        model,
        profile: HardwareProfile = CURRENT_PROFILE,
        serial_factory=serial.Serial,
        *,
        black_box_log_dir=None,
    ):
        super().__init__()
        self.model = model
        self.profile = profile
        self._serial_factory = serial_factory

        self.balance_droplets = []   # <-- for legacy Balance simulation queue

        self.command_queue = CommandQueue(event_callback=self._record_command_event)
        self.baud = 115200  # Default baud rate for serial communication
        self.ser = None
        self.port = None
        self.reader = None
        self.black_box_recorder = HostBlackBoxRecorder(log_dir=black_box_log_dir)
        self._last_black_box_log_result = None
        self._expected_serial_reader_stop_reason = None
        self._handling_unclean_serial_loss = False
        
        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

        self.execution_timer = None
        self.execution_interval_ms = 90
        self.sent_command = None
        self._last_reset_report = None
        self._flash_state = default_flash_safety_state()
        self.status_history = deque(maxlen=512)
        self.command_event_history = deque(maxlen=512)
        self._settings_trace_requests = {}
        self._latest_status_sample = None

        # ack_code -> {"timer": QTimer, "ok": callable, "to": callable}
        self._pending_acks = {}
        self._control_seq_base = 0x80000000
        self._next_ctl_seq32 = self._control_seq_base
        self._transport_capabilities = 0
        self._transport_ready = False
        self._queue_ack_timeout_ms = 200
        self._queue_ack_max_retries = 3
        self._mcu_response_timeout_ms = 2500
        self._mcu_response_check_interval_ms = 250
        self._last_mcu_rx_monotonic_ns = None
        self._last_mcu_rx_kind = None
        self._transport_ready_monotonic_ns = None
        self._mcu_unresponsive_reported = False
        self._handling_mcu_unresponsive = False
        self._command_queue_blocked_reason = None
        self._pause_after_ack_timeout_ms = 1000
        self._pause_after_confirm_timeout_ms = 2500
        self._pending_pause_after_requests = {}
        self._pending_clear_request = None

        self._connection_attempts = 0
        self._tx_mutex = QMutex()
        self._tx_paused = False
        self._sequence_pause = False  # blocks TX during UI countdowns

        self.execution_timer = QTimer(self)
        self.execution_timer.timeout.connect(self.pump_send_queue)
        self._mcu_response_timer = QTimer(self)
        self._mcu_response_timer.setInterval(self._mcu_response_check_interval_ms)
        self._mcu_response_timer.timeout.connect(self._check_mcu_response_health)
        self._session_recovery_in_progress = False
        self._waiting_for_post_clear_status = False

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

        # Cameras (ONLY if profile supports)
        if self.profile.has_refuel_camera:
            try:
                self.refuel_camera = RefuelCamera()
            except Exception as e:
                print(f"Error initializing refuel camera: {e}")
                self.refuel_camera = NullCamera()
        else:
            self.refuel_camera = NullCamera()

        if self.profile.has_droplet_camera:
            try:
                self.droplet_camera = DropletCamera()
            except Exception as e:
                print(f"Error initializing droplet camera: {e}")
                self.droplet_camera = NullCamera()
        else:
            self.droplet_camera = NullCamera()

        self.log_reader = None

        # try:
        #     self.refuel_camera = RefuelCamera()
        # except Exception as e:
        #     print(f'Error initializing refuel camera: {e}')
        #     self.refuel_camera = None

        # try:
        #     self.droplet_camera = DropletCamera()
        # except Exception as e:
        #     print(f'Error initializing droplet camera: {e}')
        #     self.droplet_camera = None

    def _alloc_ctl_seq32(self) -> int:
        n = self._next_ctl_seq32
        if self._next_ctl_seq32 >= 0xFFFFFFFF:
            self._next_ctl_seq32 = self._control_seq_base
        else:
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

    def _record_black_box_event(self, kind, payload=None):
        recorder = getattr(self, "black_box_recorder", None)
        if recorder is None:
            return None
        try:
            return recorder.record(kind, payload or {})
        except Exception as exc:
            print(f"Black-box event record failed: {exc}")
            return None

    def _mark_mcu_rx(self, frame_kind):
        self._last_mcu_rx_monotonic_ns = int(time.monotonic_ns())
        self._last_mcu_rx_kind = str(frame_kind or "frame")

    def _last_mcu_rx_age_ms(self, now_ns=None):
        last_ns = self._coerce_optional_int(getattr(self, "_last_mcu_rx_monotonic_ns", None))
        if last_ns is None:
            return None
        if now_ns is None:
            now_ns = int(time.monotonic_ns())
        return max(0.0, (int(now_ns) - int(last_ns)) / 1_000_000.0)

    def _start_mcu_response_watchdog(self):
        now_ns = int(time.monotonic_ns())
        self._transport_ready_monotonic_ns = now_ns
        if self._last_mcu_rx_monotonic_ns is None:
            self._last_mcu_rx_monotonic_ns = now_ns
            self._last_mcu_rx_kind = "transport_ready"
        self._mcu_unresponsive_reported = False
        timer = getattr(self, "_mcu_response_timer", None)
        if timer is not None:
            try:
                timer.start(self._mcu_response_check_interval_ms)
            except TypeError:
                timer.start()

    def _stop_mcu_response_watchdog(self):
        timer = getattr(self, "_mcu_response_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _check_mcu_response_health(self, now_ns=None):
        if not getattr(self, "_transport_ready", False):
            return
        if getattr(self, "_mcu_unresponsive_reported", False):
            return
        ser = getattr(self, "ser", None)
        if ser is None or not getattr(ser, "is_open", False):
            return

        if now_ns is None:
            now_ns = int(time.monotonic_ns())
        last_ns = self._coerce_optional_int(getattr(self, "_last_mcu_rx_monotonic_ns", None))
        if last_ns is None:
            last_ns = self._coerce_optional_int(getattr(self, "_transport_ready_monotonic_ns", None))
        if last_ns is None:
            return

        age_ms = max(0.0, (int(now_ns) - int(last_ns)) / 1_000_000.0)
        timeout_ms = int(getattr(self, "_mcu_response_timeout_ms", 2500) or 2500)
        if age_ms < timeout_ms:
            return

        self._handle_mcu_unresponsive(
            "no_mcu_frames",
            {
                "last_frame_kind": getattr(self, "_last_mcu_rx_kind", None),
                "last_frame_age_ms": round(age_ms, 3),
                "timeout_ms": timeout_ms,
            },
        )

    def _ack_key_for_output(self, key):
        try:
            ack_code, seq32, seq8 = key
        except Exception:
            return {"raw": str(key)}

        seq32 = self._coerce_optional_int(seq32)
        seq8 = self._coerce_optional_int(seq8)
        return {
            "ack_cmd": self._coerce_optional_int(ack_code),
            "seq32": None if seq32 == -1 else seq32,
            "seq8": None if seq8 == -1 else seq8,
        }

    def _ack_event_payload(self, ack, *, matched_pending, handler=None, ignored_control_ack=False):
        ack = dict(ack or {})
        payload = {
            "ack_cmd": self._coerce_optional_int(ack.get("ack_cmd")),
            "seq8": self._coerce_optional_int(ack.get("seq8")),
            "seq32": self._coerce_optional_int(ack.get("seq32")),
            "ack_result": ack.get("ack_result"),
            "expected_seq32": self._coerce_optional_int(ack.get("expected_seq32")),
            "capabilities": self._coerce_optional_int(ack.get("capabilities")),
            "matched_pending": bool(matched_pending),
            "ignored_control_ack": bool(ignored_control_ack),
        }
        if handler:
            payload["handler"] = str(handler)
        return payload

    def _compact_command_for_black_box(self, command):
        return {
            "command_number": self._coerce_optional_int(getattr(command, "command_number", None)),
            "command_type": str(getattr(command, "command_type", "") or ""),
            "status": str(getattr(command, "status", "") or ""),
            "param1": self._coerce_optional_int(getattr(command, "param1", None)),
            "param2": self._coerce_optional_int(getattr(command, "param2", None)),
            "param3": self._coerce_optional_int(getattr(command, "param3", None)),
            "send_attempts": self._coerce_optional_int(getattr(command, "send_attempts", None)),
        }

    def _status_sample_for_black_box(self, sample):
        sample = dict(sample or {})
        out = self._status_sample_for_output(sample)
        out["monotonic_ns"] = self._coerce_optional_int(sample.get("monotonic_ns"))
        return out

    def _black_box_transport_state(self):
        queue = getattr(getattr(self, "command_queue", None), "queue", [])
        completed = getattr(getattr(self, "command_queue", None), "completed", [])
        pending_acks = getattr(self, "_pending_acks", {})
        last_rx_age = self._last_mcu_rx_age_ms()
        return {
            "port": getattr(self, "port", None),
            "serial_open": bool(getattr(getattr(self, "ser", None), "is_open", False)),
            "profile": str(getattr(getattr(self, "profile", None), "name", "") or ""),
            "transport_ready": bool(getattr(self, "_transport_ready", False)),
            "tx_paused": bool(getattr(self, "_tx_paused", False)),
            "sequence_pause": bool(getattr(self, "_sequence_pause", False)),
            "session_recovery_in_progress": bool(getattr(self, "_session_recovery_in_progress", False)),
            "waiting_for_post_clear_status": bool(getattr(self, "_waiting_for_post_clear_status", False)),
            "pending_ack_count": len(pending_acks),
            "pending_ack_keys": [self._ack_key_for_output(key) for key in list(pending_acks.keys())],
            "command_queue_depth": len(queue),
            "completed_command_count": len(completed),
            "latest_status": self._status_sample_for_black_box(getattr(self, "_latest_status_sample", {}) or {}),
            "last_mcu_rx_kind": getattr(self, "_last_mcu_rx_kind", None),
            "last_mcu_rx_monotonic_ns": self._coerce_optional_int(getattr(self, "_last_mcu_rx_monotonic_ns", None)),
            "last_mcu_rx_age_ms": round(last_rx_age, 3) if last_rx_age is not None else None,
            "mcu_response_timeout_ms": self._coerce_optional_int(getattr(self, "_mcu_response_timeout_ms", None)),
            "mcu_unresponsive_reported": bool(getattr(self, "_mcu_unresponsive_reported", False)),
        }

    def _build_black_box_snapshot(self, reason, trigger=None):
        recorder = getattr(self, "black_box_recorder", None)
        queue = getattr(getattr(self, "command_queue", None), "queue", [])
        completed = getattr(getattr(self, "command_queue", None), "completed", [])
        return {
            "schema_version": "host_black_box_v1",
            "reason": str(reason or "snapshot"),
            "session_id": getattr(recorder, "session_id", None),
            "trigger": dict(trigger or {}),
            "transport": self._black_box_transport_state(),
            "last_reset_report": dict(getattr(self, "_last_reset_report", {}) or {}),
            "status_history": [
                self._status_sample_for_black_box(sample)
                for sample in list(getattr(self, "status_history", []))
            ],
            "command_events": [
                dict(event)
                for event in list(getattr(self, "command_event_history", []))
            ],
            "black_box_events": recorder.recent_events() if recorder is not None else [],
            "commands": {
                "queued": [self._compact_command_for_black_box(cmd) for cmd in list(queue)],
                "completed": [self._compact_command_for_black_box(cmd) for cmd in list(completed)],
            },
        }

    def _write_black_box_snapshot(self, reason, trigger=None):
        recorder = getattr(self, "black_box_recorder", None)
        if recorder is None:
            return {"path": None, "error": "black_box_recorder_missing"}
        snapshot = self._build_black_box_snapshot(reason, trigger)
        try:
            result = recorder.write_snapshot(snapshot)
        except Exception as exc:
            result = {"path": None, "error": str(exc) or exc.__class__.__name__}
        result = dict(result or {"path": None, "error": "black_box_write_returned_empty"})
        self._last_black_box_log_result = dict(result or {})
        if result.get("error"):
            self._record_black_box_event(
                "black_box_log_write_failed",
                {"reason": str(reason or "snapshot"), "error": result.get("error")},
            )
            print(f"Black-box log write failed: {result.get('error')}")
        else:
            self._record_black_box_event(
                "black_box_log_written",
                {"reason": str(reason or "snapshot"), "path": result.get("path")},
            )
        return result

    def get_debug_bundle_context(self):
        recorder = getattr(self, "black_box_recorder", None)
        recent_snapshots = []
        if recorder is not None and hasattr(recorder, "recent_snapshots"):
            recent_snapshots = recorder.recent_snapshots()
        return {
            "port": getattr(self, "port", None),
            "profile": str(getattr(getattr(self, "profile", None), "name", "") or ""),
            "black_box_log_dir": str(getattr(recorder, "log_dir", "")) if recorder is not None else None,
            "black_box_session_id": getattr(recorder, "session_id", None),
            "black_box_snapshots": recent_snapshots,
            "black_box_last_write_result": dict(getattr(self, "_last_black_box_log_result", {}) or {}),
        }

    def get_reset_debug_bundle_context(self):
        return self.get_debug_bundle_context()

    def _expect_serial_reader_stop(self, reason):
        self._expected_serial_reader_stop_reason = str(reason or "expected")
        self._record_black_box_event(
            "expected_serial_reader_stop",
            {
                "reason": self._expected_serial_reader_stop_reason,
                "port": getattr(self, "port", None),
            },
        )

    def _consume_expected_serial_reader_stop(self):
        reason = getattr(self, "_expected_serial_reader_stop_reason", None)
        self._expected_serial_reader_stop_reason = None
        return reason

    def _has_operational_transport_session(self):
        return bool(
            getattr(self, "_transport_ready", False)
            or getattr(self, "_session_recovery_in_progress", False)
        )

    def _is_unclean_serial_reader_stop(self, info, expected_reason):
        if expected_reason:
            return False
        reason = str((info or {}).get("reason") or "")
        if reason == "requested_stop":
            return False
        if reason == "exception":
            return True
        if reason in {"serial_closed", "completed"}:
            return self._has_operational_transport_session()
        return self._has_operational_transport_session()

    def _serial_loss_report(self, info, snapshot_result):
        info = dict(info or {})
        snapshot_result = dict(snapshot_result or {})
        reason = str(info.get("reason") or "unknown")
        port = getattr(self, "port", None)
        detail = reason.replace("_", " ")
        summary = "Machine serial connection ended unexpectedly."
        if info.get("exception_type"):
            message = str(info.get("message") or "")
            detail = f"{info.get('exception_type')}: {message}".rstrip(": ")
            summary = f"Machine serial connection ended unexpectedly ({detail})."
        elif reason:
            summary = f"Machine serial connection ended unexpectedly ({detail})."
        return {
            "reason": reason,
            "requested_stop": bool(info.get("requested_stop", False)),
            "port": port,
            "exception_type": info.get("exception_type"),
            "message": info.get("message"),
            "summary": summary,
            "black_box_reason": "serial_reader_stopped",
            "black_box_log_path": snapshot_result.get("path"),
            "black_box_log_error": snapshot_result.get("error"),
        }

    def _mcu_unresponsive_report(self, trigger, snapshot_result):
        trigger = dict(trigger or {})
        snapshot_result = dict(snapshot_result or {})
        age_ms = self._coerce_optional_int(trigger.get("last_frame_age_ms"))
        if age_ms is None:
            age_ms = self._last_mcu_rx_age_ms()
        timeout_ms = self._coerce_optional_int(trigger.get("timeout_ms"))
        if timeout_ms is None:
            timeout_ms = self._coerce_optional_int(getattr(self, "_mcu_response_timeout_ms", None))
        trigger_reason = str(trigger.get("trigger_reason") or trigger.get("reason") or "unknown")
        if trigger_reason == "ack_timeout":
            summary = "MCU command transport stopped responding while waiting for a command ACK."
        elif age_ms is not None:
            summary = f"MCU stopped responding; no valid frames received for {int(round(age_ms))} ms."
        else:
            summary = "MCU stopped responding; no valid frames are being received."
        return {
            "reason": "mcu_unresponsive",
            "trigger_reason": trigger_reason,
            "requested_stop": False,
            "port": getattr(self, "port", None),
            "summary": summary,
            "last_mcu_rx_kind": getattr(self, "_last_mcu_rx_kind", None),
            "last_mcu_rx_age_ms": round(float(age_ms), 3) if age_ms is not None else None,
            "mcu_response_timeout_ms": timeout_ms,
            "pending_ack_keys": [
                self._ack_key_for_output(key)
                for key in list(getattr(self, "_pending_acks", {}).keys())
            ],
            "black_box_reason": "mcu_unresponsive",
            "black_box_log_path": snapshot_result.get("path"),
            "black_box_log_error": snapshot_result.get("error"),
        }

    def _clear_transport_after_unclean_serial_loss(self):
        self.command_queue.clear_queue(reset_counter=True)
        self.sent_command = None
        self._cancel_pending_acks()
        self._cancel_pending_pause_after_requests()
        self._transport_capabilities = 0
        self._transport_ready = False
        self._command_queue_blocked_reason = "serial_connection_lost"
        self._next_ctl_seq32 = self._control_seq_base
        self._tx_paused = True
        self._sequence_pause = False
        self._session_recovery_in_progress = False
        self._waiting_for_post_clear_status = False
        self._pending_clear_request = None
        self._goodbye_seq32 = None
        try:
            if getattr(self, "execution_timer", None):
                self.execution_timer.stop()
        except Exception:
            pass
        try:
            if self.ser is not None and getattr(self.ser, "is_open", False):
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.port = None
        self.reader = None
        self._stop_mcu_response_watchdog()

    def _clear_transport_after_mcu_unresponsive(self):
        self.command_queue.clear_queue(reset_counter=True)
        self.sent_command = None
        self._cancel_pending_acks()
        self._cancel_pending_pause_after_requests()
        self._transport_capabilities = 0
        self._transport_ready = False
        self._command_queue_blocked_reason = "mcu_unresponsive"
        self._next_ctl_seq32 = self._control_seq_base
        self._tx_paused = True
        self._sequence_pause = False
        self._session_recovery_in_progress = False
        self._waiting_for_post_clear_status = False
        self._pending_clear_request = None
        self._goodbye_seq32 = None
        self._stop_mcu_response_watchdog()
        try:
            if getattr(self, "execution_timer", None):
                self.execution_timer.stop()
        except Exception:
            pass

    def _handle_mcu_unresponsive(self, trigger_reason, trigger=None):
        if getattr(self, "_handling_mcu_unresponsive", False):
            return
        if getattr(self, "_mcu_unresponsive_reported", False):
            return

        trigger = dict(trigger or {})
        trigger["trigger_reason"] = str(trigger_reason or trigger.get("trigger_reason") or "unknown")
        trigger.setdefault("port", getattr(self, "port", None))
        trigger.setdefault("last_frame_kind", getattr(self, "_last_mcu_rx_kind", None))
        age_ms = self._last_mcu_rx_age_ms()
        if age_ms is not None:
            trigger.setdefault("last_frame_age_ms", round(age_ms, 3))
        trigger.setdefault("timeout_ms", getattr(self, "_mcu_response_timeout_ms", None))
        trigger.setdefault(
            "pending_ack_keys",
            [self._ack_key_for_output(key) for key in list(getattr(self, "_pending_acks", {}).keys())],
        )

        self._handling_mcu_unresponsive = True
        self._mcu_unresponsive_reported = True
        self._stop_mcu_response_watchdog()
        try:
            self._record_black_box_event("mcu_unresponsive", trigger)
            snapshot_result = self._write_black_box_snapshot("mcu_unresponsive", trigger)
            report = self._mcu_unresponsive_report(trigger, snapshot_result)
            self._record_black_box_event("serial_connection_lost", report)
            self._clear_transport_after_mcu_unresponsive()
            self.machine_connected_signal.emit(False)
            self.serial_connection_lost.emit(report)
        finally:
            self._handling_mcu_unresponsive = False

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

    def _invoke_ack_callback(self, callback, ack=None):
        if not callable(callback):
            return
        try:
            callback(ack)
        except TypeError:
            callback()

    def _ack_timeout_by_key(self, key):
        entry = self._pending_acks.pop(key, None)
        if not entry:
            return
        self._record_black_box_event("ack_timeout", {"key": self._ack_key_for_output(key)})
        try:
            self._invoke_ack_callback(entry["to"])
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
        self._mark_mcu_rx("ack")
        ack_code = ack.get("ack_cmd")
        seq32    = ack.get("seq32")
        seq8     = ack.get("seq8")
        if ack_code == CMD_QUEUE_ACK and self._handle_pause_after_queue_ack(ack):
            self._record_black_box_event(
                "ack",
                self._ack_event_payload(ack, matched_pending=True, handler="pause_after"),
            )
            return

        # Try SEQ32 first, then fall back to seq8
        key = self._ack_key(ack_code, seq32, None)
        entry = self._pending_acks.pop(key, None)
        if not entry and seq32 is None:
            key = self._ack_key(ack_code, None, seq8)
            entry = self._pending_acks.pop(key, None)

        if entry:
            entry["timer"].stop()
            self._record_black_box_event(
                "ack",
                self._ack_event_payload(ack, matched_pending=True, handler="pending_ack"),
            )
            try:
                self._invoke_ack_callback(entry["ok"], ack)
            finally:
                entry["timer"].deleteLater()
        else:
            if ack_code == CMD_QUEUE_ACK and seq32 is not None and int(seq32) >= int(self._control_seq_base):
                self._record_black_box_event(
                    "ack",
                    self._ack_event_payload(
                        ack,
                        matched_pending=False,
                        ignored_control_ack=True,
                    ),
                )
                return
            self._record_black_box_event(
                "ack",
                self._ack_event_payload(ack, matched_pending=False),
            )
            # Optional: log stray ACKs
            print(f"Stray ACK: code=0x{ack_code:02X} seq32={seq32} seq8={seq8}")
            pass

    def connect_board(self, port):
        try:
            if (
                self.ser is not None
                and getattr(self.ser, "is_open", False)
                and not getattr(self, "_transport_ready", False)
                and str(getattr(self, "port", port)) == str(port)
            ):
                self.port = port
                self._record_black_box_event("connect_board_reuse_open_serial", {"port": self.port})
                self.begin_reader_thread()
                self._send_hello()
                return
            self.port = port
            self.ser = self._serial_factory(self.port, self.baud, timeout=0.1)
            if not self.ser.is_open:
                raise IOError("Port not open")
            self._record_black_box_event("connect_board", {"port": self.port})
            
            self.begin_reader_thread()
            self._send_hello()

        except Exception as e:
            print(f"Connection error: {e}")
            self.error_occurred.emit(str(f"Connection error: {e}"))
            self.machine_connected_signal.emit(False)

    def _send_hello(self):
        self._transport_ready = False
        self._transport_capabilities = 0
        self._stop_mcu_response_watchdog()
        hello_seq = self._alloc_ctl_seq32()
        self._write_frame(build_frame(HELLO, hello_seq))
        self._start_ack_wait(
            HELLO_ACK, hello_seq, 1000,
            on_ok=self._on_hello_ack,
            on_timeout=lambda: self._hello_timeout()
        )

    @Slot()
    def _on_hello_ack(self, ack=None):
        capabilities = int((ack or {}).get("capabilities") or 0)
        missing_caps = REQUIRED_TRANSPORT_CAPS & ~capabilities
        if missing_caps:
            self._transport_capabilities = capabilities
            self._transport_ready = False
            msg = (
                "Connected board does not advertise the required transport capabilities. "
                f"missing=0x{missing_caps:08X} advertised=0x{capabilities:08X}"
            )
            print(msg)
            self.error_occurred.emit(msg)
            self.machine_connected_signal.emit(False)
            return
        if self.profile.has_log_channel:
            self.begin_log_thread()
        self._session_recovery_in_progress = False
        self._transport_capabilities = capabilities
        self._transport_ready = True
        self._command_queue_blocked_reason = None
        self._tx_paused = False
        self._sequence_pause = False
        self._waiting_for_post_clear_status = False
        self._start_mcu_response_watchdog()
        self.begin_execution_timer()
        self.pump_send_queue()
        self.machine_connected_signal.emit(True)
        print(f"Connected to {self.ser.name}")
        self._connection_attempts = 0  # reset attempts on success

    def _hello_timeout(self):
        self.machine_connected_signal.emit(False)
        # Retry to connect
        if self._connection_attempts < 3:
            self._connection_attempts += 1
            self._teardown_transport_for_retry()
            print(f"Retrying connection ({self._connection_attempts}/3)…")
            self.connect_board(self.port)
        elif self._connection_attempts < 6:
            self._connection_attempts += 1
            self._teardown_transport_for_retry()
            self.reset_mcu_board()
            print(f"Resetting board and retrying connection ({self._connection_attempts}/6)…")
            self.connect_board(self.port)
        else:
            msg = (
                f"No HELLO_ACK from device on {self.port}. "
                "This usually means the wrong COM port (e.g. balance selected instead of MCU) "
                "or the board is not running the expected firmware."
            )
            print(msg)
            self.error_occurred.emit(msg)
            self.machine_connected_signal.emit(False)

    def _teardown_transport_for_retry(self):
        """Close current transport before recursive reconnect attempts."""
        self._expect_serial_reader_stop("connection_retry")
        self._stop_mcu_response_watchdog()
        try:
            self.stop_reader_thread()
        except Exception:
            pass
        try:
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def reset_board(self):
        print('Resetting board')
        self._expect_serial_reader_stop("reset_board")
        self._stop_mcu_response_watchdog()
        self.command_queue.clear_queue(reset_counter=True)
        self._transport_capabilities = 0
        self._transport_ready = False
        self._next_ctl_seq32 = self._control_seq_base
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

        serial_reader = self.reader
        log_reader = self.log_reader
        if log_reader is not None:
            self._disconnect_log_reader_signals(log_reader)

        shutdown_started = time.monotonic()
        serial_shutdown_ms = 0
        log_shutdown_ms = 0
        if serial_reader is not None or log_reader is not None:
            print("Requesting serial and log reader shutdown...")
            self._request_reader_stop(serial_reader, "Serial reader thread")
            self._request_reader_stop(log_reader, "Log reader thread")
            serial_shutdown_ms, _ = self._wait_for_reader_stop(
                serial_reader,
                "reader",
                "Serial reader thread",
                SERIAL_READER_STOP_WAIT_MS,
            )
            log_shutdown_ms, _ = self._wait_for_reader_stop(
                log_reader,
                "log_reader",
                "Log reader thread",
                LOG_READER_STOP_WAIT_MS,
            )
            total_shutdown_ms = int((time.monotonic() - shutdown_started) * 1000)
            print(
                "Reader shutdown finished in "
                f"{total_shutdown_ms} ms (serial={serial_shutdown_ms} ms, log={log_shutdown_ms} ms)"
            )
        self._flash_state = default_flash_safety_state()
        self.flash_state_updated.emit(dict(self._flash_state))

        try: self._gripper_idle_timer.stop()
        except Exception: pass
        self._gripper_ack_required = True
        # self._blocked_gripper_command = None

    def _cancel_pending_acks(self):
        for entry in list(self._pending_acks.values()):
            try:
                entry["timer"].stop()
                entry["timer"].deleteLater()
            except Exception:
                pass
        self._pending_acks.clear()
        self._cancel_pending_pause_after_requests()
        self._pending_clear_request = None

    def _cleanup_timer(self, timer):
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timer.deleteLater()
        except Exception:
            pass

    def _clear_pause_after_request(self, seq32):
        request = self._pending_pause_after_requests.pop(int(seq32 or 0), None)
        if request is None:
            return None
        self._cleanup_timer(request.get("ack_timer"))
        self._cleanup_timer(request.get("confirm_timer"))
        return request

    def _cancel_pending_pause_after_requests(self):
        for seq32 in list(self._pending_pause_after_requests.keys()):
            self._clear_pause_after_request(seq32)

    def _complete_pending_clear_request(self, *, status_confirmed, status_timed_out):
        request = self._pending_clear_request
        self._pending_clear_request = None
        if request is None:
            return

        payload = {
            "ack_received": bool(request.get("ack_received", False)),
            "ack_timed_out": bool(request.get("ack_timed_out", False)),
            "status_confirmed": bool(status_confirmed),
            "status_timed_out": bool(status_timed_out),
        }

        handler = request.get("handler")
        if handler:
            self._invoke_ack_callback(handler, payload)

    def _reset_session_state_for_recovery(self):
        self.command_queue.clear_queue(reset_counter=True)
        self.sent_command = None
        self._cancel_pending_acks()
        self._cancel_pending_pause_after_requests()
        self._transport_capabilities = 0
        self._transport_ready = False
        self._command_queue_blocked_reason = "board_reset_recovery"
        self._next_ctl_seq32 = self._control_seq_base
        self._tx_paused = True
        self._sequence_pause = False
        self._waiting_for_post_clear_status = False
        self._pending_clear_request = None
        self._goodbye_seq32 = None
        self._stop_mcu_response_watchdog()
        if getattr(self, 'execution_timer', None):
            try:
                self.execution_timer.stop()
            except Exception:
                pass
        try:
            if self.ser is not None:
                self.ser.reset_input_buffer()
        except Exception:
            pass
        try:
            self._gripper_idle_timer.stop()
        except Exception:
            pass
        self._gripper_ack_required = True

    def _begin_recovery_handshake(self):
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return
        self._session_recovery_in_progress = True
        self._send_hello()

    def reset_mcu_board(self):
        reset_board()
        
    def disconnect_handler(self):
        # self.reset_board()
        self._expect_serial_reader_stop("disconnect_handler")
        self._stop_mcu_response_watchdog()
        self._record_black_box_event(
            "disconnect_complete",
            {"port": getattr(self, "port", None)},
        )
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

    def release_serial_for_external_owner(self, reason="external_owner"):
        """
        Temporarily release the COM port without sending GOODBYE.

        This is intentionally narrower than disconnect_board(): it is used by
        regulator calibration to hand the port to the pressure-trace self-test
        runner while leaving MCU runtime state intact.
        """
        ser = self.ser
        if ser is None or not getattr(ser, "is_open", False):
            print(f"Cannot release serial port for {reason}: serial port is not open.")
            return False

        timer_was_active = False
        if getattr(self, "execution_timer", None) is not None:
            try:
                timer_was_active = bool(self.execution_timer.isActive())
                self.stop_execution_timer()
            except Exception:
                timer_was_active = False

        previous_transport_ready = bool(getattr(self, "_transport_ready", False))
        previous_tx_paused = bool(getattr(self, "_tx_paused", False))
        self._stop_mcu_response_watchdog()
        self._cancel_pending_acks()

        serial_reader = self.reader
        log_reader = self.log_reader
        if log_reader is not None:
            self._disconnect_log_reader_signals(log_reader)

        print(f"Releasing serial port for {reason} without GOODBYE...")
        self._expect_serial_reader_stop(f"serial_handoff:{reason}")
        self._request_reader_stop(serial_reader, "Serial reader thread")
        self._request_reader_stop(log_reader, "Log reader thread")
        _serial_ms, serial_stopped = self._wait_for_reader_stop(
            serial_reader,
            "reader",
            "Serial reader thread",
            SERIAL_READER_STOP_WAIT_MS,
        )
        _log_ms, log_stopped = self._wait_for_reader_stop(
            log_reader,
            "log_reader",
            "Log reader thread",
            LOG_READER_STOP_WAIT_MS,
        )
        if not serial_stopped or not log_stopped:
            print(f"Serial release for {reason} failed because a reader thread did not stop cleanly.")
            self._expected_serial_reader_stop_reason = None
            self._transport_ready = previous_transport_ready
            self._tx_paused = previous_tx_paused
            if previous_transport_ready:
                self._start_mcu_response_watchdog()
            if timer_was_active:
                try:
                    self.begin_execution_timer()
                except Exception:
                    pass
            return False

        try:
            if hasattr(ser, "close"):
                ser.close()
        except Exception as exc:
            print(f"Serial release for {reason} failed while closing the port: {exc}")
            self._expected_serial_reader_stop_reason = None
            self._transport_ready = previous_transport_ready
            self._tx_paused = previous_tx_paused
            if previous_transport_ready:
                self._start_mcu_response_watchdog()
            if timer_was_active:
                try:
                    self.begin_execution_timer()
                except Exception:
                    pass
            return False

        self.ser = None
        self.sent_command = None
        self._transport_ready = False
        self._tx_paused = True
        self._sequence_pause = False
        self._session_recovery_in_progress = False
        print(f"Serial port released for {reason}.")
        return True

    def disconnect_board(self, error=False):
        self._record_black_box_event(
            "disconnect_requested",
            {"error": bool(error), "port": getattr(self, "port", None)},
        )
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
            if self.ser is not None:
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
        reader = self.reader
        if reader is not None:
            try:
                if reader.isRunning():
                    print('Serial reader thread already running')
                    return
            except Exception:
                return
            try:
                reader.stop()
            except Exception:
                pass
            self.reader = None

        if self.reader is None:
            self._expected_serial_reader_stop_reason = None
            self.reader = SerialReader(self.ser)
            self.reader.status_received.connect(self.update_status)
            self.reader.ackReceived.connect(self._on_any_ack)
            self.reader.resetReportReceived.connect(self._on_reset_report)
            reader_stopped = getattr(self.reader, "readerStopped", None)
            if reader_stopped is not None:
                reader_stopped.connect(self._on_serial_reader_stopped)
            self.reader.start()
            self._record_black_box_event(
                "serial_reader_started",
                {"port": getattr(self, "port", None)},
            )
            print('Serial reader thread started')
        else:
            print('Serial reader thread already running')

    @Slot(dict)
    def _on_reset_report(self, report):
        self._mark_mcu_rx("reset_report")
        self._last_reset_report = dict(report)
        self._record_black_box_event("reset_report", dict(report))
        self._write_black_box_snapshot("reset_report", {"report": dict(report)})
        self._reset_session_state_for_recovery()
        self._begin_recovery_handshake()
        self.reset_report_received.emit(dict(report))

    @Slot(dict)
    def _on_serial_reader_stopped(self, info):
        info = dict(info or {})
        self._record_black_box_event("serial_reader_stopped", info)
        expected_reason = self._consume_expected_serial_reader_stop()
        if expected_reason:
            info["expected_stop_reason"] = expected_reason
            self._record_black_box_event("serial_reader_stop_expected", info)
            return
        if info.get("reason") == "requested_stop":
            return

        snapshot_result = self._write_black_box_snapshot("serial_reader_stopped", info)
        if not self._is_unclean_serial_reader_stop(info, expected_reason):
            return
        if self._handling_unclean_serial_loss:
            return

        self._handling_unclean_serial_loss = True
        try:
            report = self._serial_loss_report(info, snapshot_result)
            self._record_black_box_event("serial_connection_lost", report)
            self._clear_transport_after_unclean_serial_loss()
            self.machine_connected_signal.emit(False)
            self.serial_connection_lost.emit(report)
        finally:
            self._handling_unclean_serial_loss = False

    def stop_reader_thread(self):
        """
        Stop the serial reader thread.
        """
        reader = self.reader
        if reader is None:
            print('No serial reader thread to stop')
            return

        self._request_reader_stop(reader, "Serial reader thread")
        self._wait_for_reader_stop(
            reader,
            "reader",
            "Serial reader thread",
            READER_STOP_FALLBACK_WAIT_MS,
            fallback_timeout_ms=None,
        )

    def begin_log_thread(self):
        """
        Start the log reader thread to read logs from the machine.
        """
        if not self.profile.has_log_channel:
            self.log_reader = None
            return

        reader = self.log_reader
        if reader is not None:
            try:
                if reader.isRunning():
                    return
            except Exception:
                return
            try:
                reader.stop()
            except Exception:
                pass
            self.log_reader = None

        try:
            self.log_reader = LogReader(self.baud, serial_factory=self._serial_factory)
            self.log_reader.lineReceived.connect(self.on_log_line_received)
            self.log_reader.statsUpdated.connect(self.on_stats_updated)
            self.log_reader.messageReceived.connect(self.on_log_message_received)
            self.log_reader.flashStateChanged.connect(self.on_flash_state_changed)
            self.log_reader.start()
        except Exception as e:
            print(f"Could not start log thread: {e}")
            self.log_reader = None

    def on_stats_updated(self, stats: dict):
        self.log_stats_updated.emit(stats)

    def on_log_message_received(self, message: str):
        self.log_message_received.emit(message)

    def on_flash_state_changed(self, state: dict):
        next_state = default_flash_safety_state()
        if isinstance(state, dict):
            next_state.update(
                {
                    "flash_session_armed": bool(state.get("flash_session_armed", False)),
                    "flash_fault_latched": bool(state.get("flash_fault_latched", False)),
                    "flash_fault_reason": str(state.get("flash_fault_reason", "") or ""),
                }
            )
        self._flash_state = next_state
        self.flash_state_updated.emit(dict(self._flash_state))

    def _disconnect_log_reader_signals(self, reader):
        for signal_obj, slot in (
            (getattr(reader, "lineReceived", None), self.on_log_line_received),
            (getattr(reader, "statsUpdated", None), self.on_stats_updated),
            (getattr(reader, "messageReceived", None), self.on_log_message_received),
            (getattr(reader, "flashStateChanged", None), self.on_flash_state_changed),
        ):
            if signal_obj is None:
                continue
            try:
                signal_obj.disconnect(slot)
            except Exception:
                pass

    def _request_reader_stop(self, reader, label):
        if reader is None:
            return
        try:
            reader.request_stop()
        except Exception as exc:
            print(f"{label} stop request raised an error: {exc}")

    def _wait_for_reader_stop(self, reader, attr_name, label, timeout_ms, fallback_timeout_ms=READER_STOP_FALLBACK_WAIT_MS):
        if reader is None:
            return 0, True

        wait_started = time.monotonic()
        try:
            stopped = bool(reader.wait_for_stop(timeout_ms))
        except Exception as exc:
            print(f"{label} stop wait raised an error: {exc}")
            stopped = False
        elapsed_ms = int((time.monotonic() - wait_started) * 1000)

        if not stopped and fallback_timeout_ms is not None:
            print(
                f"{label} fast stop timed out after {elapsed_ms} ms; "
                f"waiting up to {fallback_timeout_ms} ms more"
            )
            wait_started = time.monotonic()
            try:
                stopped = bool(reader.wait_for_stop(fallback_timeout_ms))
            except Exception as exc:
                print(f"{label} fallback stop wait raised an error: {exc}")
                stopped = False
            elapsed_ms += int((time.monotonic() - wait_started) * 1000)

        if stopped:
            if getattr(self, attr_name, None) is reader:
                setattr(self, attr_name, None)
            print(f"{label} stopped in {elapsed_ms} ms")
        else:
            print(f"{label} did not stop cleanly after {elapsed_ms} ms; keeping existing reader reference")

        return elapsed_ms, stopped
        
    def stop_log_thread(self):
        """
        Stop the log reader thread.
        """
        reader = self.log_reader
        if reader is None:
            return

        self._disconnect_log_reader_signals(reader)
        self._request_reader_stop(reader, "Log reader thread")
        self._wait_for_reader_stop(
            reader,
            "log_reader",
            "Log reader thread",
            READER_STOP_FALLBACK_WAIT_MS,
            fallback_timeout_ms=None,
        )

    def begin_execution_timer(self):
        print('Starting execution timer')
        if self.execution_timer is None:
            self.execution_timer = QTimer(self)
            self.execution_timer.timeout.connect(self.pump_send_queue)
        if not self.execution_timer.isActive():
            self.execution_timer.start(max(1, int(self.execution_interval_ms)))

    def set_execution_interval_ms(self, interval_ms: int):
        self.execution_interval_ms = max(1, int(interval_ms))
        if self.execution_timer is not None and self.execution_timer.isActive():
            self.execution_timer.start(self.execution_interval_ms)

    def stop_execution_timer(self):
        print('Stopping execution timer')
        if self.execution_timer.isActive():
            self.execution_timer.stop()

    def _coerce_optional_int(self, value):
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _relative_ms(self, value_ns, base_ns):
        value = self._coerce_optional_int(value_ns)
        base = self._coerce_optional_int(base_ns)
        if value is None or base is None:
            return None
        return round((value - base) / 1_000_000.0, 3)

    def _status_sample_from_dict(self, data, observed_monotonic_ns):
        data = dict(data or {})
        now_ns = int(observed_monotonic_ns)
        host_rx_ns = self._coerce_optional_int(data.get("__host_rx_monotonic_ns"))
        rx_to_main_thread_ms = None
        if host_rx_ns is not None:
            rx_to_main_thread_ms = round(max(0, now_ns - host_rx_ns) / 1_000_000.0, 3)
        sample = {
            "monotonic_ns": now_ns,
            "Current_command": self._coerce_optional_int(data.get("Current_command")),
            "Last_completed": self._coerce_optional_int(data.get("Last_completed")),
            "Last_accepted": self._coerce_optional_int(data.get("Last_accepted")),
            "Last_retired": self._coerce_optional_int(data.get("Last_retired")),
            "Pause_after_seq32": self._coerce_optional_int(data.get("Pause_after_seq32")),
            "Pause_watermark_reached": bool(data.get("Pause_watermark_reached", False)),
            "Transport_paused": bool(data.get("Transport_paused", False)),
            "cmd_depth": self._coerce_optional_int(data.get("cmd_depth")),
            "Flash_delay": self._coerce_optional_int(data.get("Flash_delay")),
            "Flash_droplets": self._coerce_optional_int(data.get("Flash_droplets")),
            "rx_to_main_thread_ms": rx_to_main_thread_ms,
        }
        for key in (
            "Pressure_P",
            "Pressure_R",
            "Tar_print",
            "Tar_refuel",
            "X",
            "Y",
            "Z",
            "P",
            "R",
            "Tar_X",
            "Tar_Y",
            "Tar_Z",
            "Tar_P",
            "Tar_R",
            "Print_width",
            "Refuel_width",
            "Disp_freq",
            "drop_total",
            "drop_remain",
            "print_active",
            "refuel_active",
            "Flashes",
            "Flash_width",
            "Ext_counter",
        ):
            if key in data:
                sample[key] = self._coerce_optional_int(data.get(key))
        return sample

    def _status_sample_for_output(self, sample, request_created_monotonic_ns=None):
        sample = dict(sample or {})
        out = {
            "Current_command": self._coerce_optional_int(sample.get("Current_command")),
            "Last_completed": self._coerce_optional_int(sample.get("Last_completed")),
            "Last_accepted": self._coerce_optional_int(sample.get("Last_accepted")),
            "Last_retired": self._coerce_optional_int(sample.get("Last_retired")),
            "Pause_after_seq32": self._coerce_optional_int(sample.get("Pause_after_seq32")),
            "Pause_watermark_reached": bool(sample.get("Pause_watermark_reached", False)),
            "Transport_paused": bool(sample.get("Transport_paused", False)),
            "cmd_depth": self._coerce_optional_int(sample.get("cmd_depth")),
            "Flash_delay": self._coerce_optional_int(sample.get("Flash_delay")),
            "Flash_droplets": self._coerce_optional_int(sample.get("Flash_droplets")),
            "rx_to_main_thread_ms": sample.get("rx_to_main_thread_ms"),
        }
        for key in (
            "Pressure_P",
            "Pressure_R",
            "Tar_print",
            "Tar_refuel",
            "X",
            "Y",
            "Z",
            "P",
            "R",
            "Tar_X",
            "Tar_Y",
            "Tar_Z",
            "Tar_P",
            "Tar_R",
            "Print_width",
            "Refuel_width",
            "Disp_freq",
            "drop_total",
            "drop_remain",
            "print_active",
            "refuel_active",
            "Flashes",
            "Flash_width",
            "Ext_counter",
        ):
            if key in sample:
                out[key] = self._coerce_optional_int(sample.get(key))
        observed_ms = self._relative_ms(sample.get("monotonic_ns"), request_created_monotonic_ns)
        if observed_ms is not None:
            out["observed_ms"] = observed_ms
        return out

    def _find_command_by_number(self, command_number):
        command_number = self._coerce_optional_int(command_number)
        if command_number is None:
            return None
        for command in list(getattr(self.command_queue, "queue", [])):
            if getattr(command, "command_number", None) == command_number:
                return command
        for command in list(getattr(self.command_queue, "completed", [])):
            if getattr(command, "command_number", None) == command_number:
                return command
        return None

    def _lowest_queued_command_number(self):
        numbers = [
            self._coerce_optional_int(getattr(command, "command_number", None))
            for command in list(getattr(self.command_queue, "queue", []))
            if getattr(command, "status", None) not in {"Completed", "Canceled"}
        ]
        numbers = [number for number in numbers if number is not None]
        return min(numbers) if numbers else None

    def _align_command_counter_after_clear(self, last_retired_command):
        last_retired = self._coerce_optional_int(last_retired_command)
        if last_retired is None:
            return
        if len(getattr(self.command_queue, "queue", [])) != 0:
            return
        self.command_queue.command_number = max(0, int(last_retired))

    def _record_command_event(self, command, event_name):
        metadata = dict(getattr(command, "trace_metadata", {}) or {})
        request_id = metadata.get("request_id")
        request_id = str(request_id) if request_id else None
        observed_ns = int(time.monotonic_ns())
        request_created_monotonic_ns = metadata.get("request_created_monotonic_ns")
        event = {
            "request_id": request_id,
            "event": str(event_name),
            "command_number": int(getattr(command, "command_number", 0)),
            "command_type": str(getattr(command, "command_type", "") or ""),
            "setting_key": metadata.get("setting_key"),
            "requested_value": metadata.get("requested_value"),
            "status": str(getattr(command, "status", "") or ""),
            "observed_monotonic_ns": observed_ns,
            "observed_ms": self._relative_ms(observed_ns, request_created_monotonic_ns),
        }
        self.command_event_history.append(event)
        self._record_black_box_event("command_lifecycle", event)

    def register_settings_trace_binding(self, payload):
        payload = dict(payload or {})
        request_id = str(payload.get("request_id") or "")
        if not request_id:
            return None
        commands = []
        for command in list(payload.get("commands") or []):
            item = dict(command or {})
            command_number = self._coerce_optional_int(item.get("command_number"))
            commands.append(
                {
                    "command_number": command_number,
                    "command_type": str(item.get("command_type") or ""),
                    "setting_key": str(item.get("setting_key") or ""),
                    "requested_value": item.get("requested_value"),
                }
            )
        record = {
            "request_id": request_id,
            "context": str(payload.get("context") or ""),
            "requested_settings": dict(payload.get("settings") or payload.get("requested_settings") or {}),
            "timeout_ms": self._coerce_optional_int(payload.get("timeout_ms")),
            "request_created_monotonic_ns": self._coerce_optional_int(payload.get("request_created_monotonic_ns")),
            "completion_command_number": self._coerce_optional_int(payload.get("completion_command_number")),
            "commands": commands,
            "bound_monotonic_ns": int(time.monotonic_ns()),
        }
        self._settings_trace_requests[request_id] = record
        return dict(record)

    def _status_matches_requested_settings(self, latest_status, requested_settings):
        latest_status = dict(latest_status or {})
        requested_settings = dict(requested_settings or {})
        status_map = {
            "flash_delay": "Flash_delay",
            "num_droplets": "Flash_droplets",
        }
        matched_any = False
        for setting_key, status_key in status_map.items():
            if setting_key not in requested_settings:
                continue
            matched_any = True
            if self._coerce_optional_int(latest_status.get(status_key)) != self._coerce_optional_int(requested_settings.get(setting_key)):
                return False
        return matched_any

    def _build_command_trace_summary(self, request_id, request_created_monotonic_ns, command_info):
        command_info = dict(command_info or {})
        command_number = self._coerce_optional_int(command_info.get("command_number"))
        command = self._find_command_by_number(command_number)
        lifecycle_ns = {
            "queued": None,
            "sent": None,
            "accepted": None,
            "executing": None,
            "completed": None,
            "canceled": None,
        }
        status = None
        for event in list(self.command_event_history):
            if str(event.get("request_id") or "") != str(request_id):
                continue
            if self._coerce_optional_int(event.get("command_number")) != command_number:
                continue
            event_name = str(event.get("event") or "")
            observed_ns = self._coerce_optional_int(event.get("observed_monotonic_ns"))
            if event_name in lifecycle_ns and lifecycle_ns[event_name] is None:
                lifecycle_ns[event_name] = observed_ns
            if event.get("status"):
                status = str(event.get("status"))
        if command is not None:
            status = str(getattr(command, "status", status or ""))
            for key in lifecycle_ns:
                if lifecycle_ns[key] is None:
                    lifecycle_ns[key] = self._coerce_optional_int(getattr(command, "lifecycle_ns", {}).get(key))
        if not status:
            status = "NotQueued" if command_number is None else "Unknown"
        return {
            "command_number": command_number,
            "command_type": str(command_info.get("command_type") or ""),
            "setting_key": str(command_info.get("setting_key") or ""),
            "requested_value": command_info.get("requested_value"),
            "status": status,
            "queued_ms": self._relative_ms(lifecycle_ns["queued"], request_created_monotonic_ns),
            "sent_ms": self._relative_ms(lifecycle_ns["sent"], request_created_monotonic_ns),
            "accepted_ms": self._relative_ms(lifecycle_ns["accepted"], request_created_monotonic_ns),
            "executing_ms": self._relative_ms(lifecycle_ns["executing"], request_created_monotonic_ns),
            "completed_ms": self._relative_ms(lifecycle_ns["completed"], request_created_monotonic_ns),
            "canceled_ms": self._relative_ms(lifecycle_ns["canceled"], request_created_monotonic_ns),
            "_lifecycle_ns": lifecycle_ns,
        }

    def get_settings_trace_snapshot(self, request_id, timed_out_monotonic_ns=None):
        request_id = str(request_id or "")
        record = dict(self._settings_trace_requests.get(request_id) or {})
        if not record:
            return {
                "request_id": request_id,
                "context": "",
                "requested_settings": {},
                "timeout_ms": None,
                "commands": [],
                "latest_status": {
                    "Current_command": None,
                    "Last_completed": None,
                    "Last_accepted": None,
                    "Last_retired": None,
                    "cmd_depth": None,
                    "Flash_delay": None,
                    "Flash_droplets": None,
                    "rx_to_main_thread_ms": None,
                },
                "recent_status": [],
                "recent_command_events": [],
                "stall_hint": "commands_not_bound",
            }

        request_created_monotonic_ns = self._coerce_optional_int(record.get("request_created_monotonic_ns"))
        completion_command_number = self._coerce_optional_int(record.get("completion_command_number"))
        commands = [
            self._build_command_trace_summary(request_id, request_created_monotonic_ns, info)
            for info in list(record.get("commands") or [])
        ]
        latest_status_sample = dict(self._latest_status_sample or {})
        latest_status = self._status_sample_for_output(latest_status_sample, request_created_monotonic_ns)
        recent_status = []
        for sample in list(self.status_history):
            if request_created_monotonic_ns is not None:
                sample_ns = self._coerce_optional_int(sample.get("monotonic_ns"))
                if sample_ns is not None and sample_ns < request_created_monotonic_ns:
                    continue
            recent_status.append(self._status_sample_for_output(sample, request_created_monotonic_ns))
        recent_status = recent_status[-12:]

        recent_command_events = []
        for event in list(self.command_event_history):
            if str(event.get("request_id") or "") != request_id:
                continue
            recent_command_events.append(
                {
                    "event": str(event.get("event") or ""),
                    "command_number": self._coerce_optional_int(event.get("command_number")),
                    "command_type": str(event.get("command_type") or ""),
                    "setting_key": event.get("setting_key"),
                    "requested_value": event.get("requested_value"),
                    "status": str(event.get("status") or ""),
                    "observed_ms": event.get("observed_ms"),
                }
            )
        recent_command_events = recent_command_events[-16:]

        completion_command = None
        for item in commands:
            if self._coerce_optional_int(item.get("command_number")) == completion_command_number:
                completion_command = item
                break

        timed_out_ns = self._coerce_optional_int(timed_out_monotonic_ns)
        stall_hint = "unknown"
        if not commands or completion_command_number is None or completion_command is None:
            stall_hint = "commands_not_bound"
        elif (
            timed_out_ns is not None
            and self._coerce_optional_int(completion_command.get("_lifecycle_ns", {}).get("completed")) is not None
            and self._coerce_optional_int(completion_command.get("_lifecycle_ns", {}).get("completed")) > timed_out_ns
        ):
            stall_hint = "late_completion_after_timeout"
        elif (
            completion_command.get("completed_ms") is None
            and self._status_matches_requested_settings(latest_status, record.get("requested_settings"))
        ):
            stall_hint = "state_matches_settings_but_completion_missing"
        elif completion_command.get("sent_ms") is None:
            stall_hint = "completion_command_not_sent"
        elif completion_command.get("completed_ms") is None:
            stall_hint = "completion_command_sent_not_retired"

        for item in commands:
            item.pop("_lifecycle_ns", None)

        return {
            "request_id": request_id,
            "context": str(record.get("context") or ""),
            "requested_settings": dict(record.get("requested_settings") or {}),
            "timeout_ms": self._coerce_optional_int(record.get("timeout_ms")),
            "commands": commands,
            "latest_status": latest_status,
            "recent_status": recent_status,
            "recent_command_events": recent_command_events,
            "stall_hint": stall_hint,
        }

    def update_status(self, data):
        """
        Update the status of the machine with the received data.
        """
        if isinstance(data, dict):
            self._mark_mcu_rx("status")
            observed_monotonic_ns = int(time.monotonic_ns())
            sample = self._status_sample_from_dict(data, observed_monotonic_ns)
            self.status_history.append(sample)
            self._latest_status_sample = dict(sample)
            self._update_pause_after_requests_from_status(sample)
            if getattr(self, "_waiting_for_post_clear_status", False):
                depth = data.get("cmd_depth", 0)
                curr  = data.get("Current_command", 0)
                last  = data.get("Last_completed", 0)
                retired = data.get("Last_retired", last)
                if depth == 0 and curr == retired:
                    self._waiting_for_post_clear_status = False
                    self._align_command_counter_after_clear(retired)
                    self._tx_paused = False
                    self.begin_execution_timer()
                    self.pump_send_queue()
                    self._complete_pending_clear_request(
                        status_confirmed=True,
                        status_timed_out=False,
                    )
                elif time.time() > getattr(self, "_wait_for_clear_status_deadline", 0):
                    # fallback: don’t block forever
                    self._waiting_for_post_clear_status = False
                    self._tx_paused = False
                    self.begin_execution_timer()
                    self.pump_send_queue()
                    self._complete_pending_clear_request(
                        status_confirmed=False,
                        status_timed_out=True,
                    )
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

    def update_command_numbers(self,current_command,last_completed,last_accepted=None,last_retired=None):
        self.command_queue.update_command_status(
            current_command,
            last_completed,
            last_accepted_command=last_accepted,
            last_retired_command=last_retired,
        )

    def add_command_to_queue(self, command_type, param1, param2, param3, handler=None, kwargs=None, manual=False, trace_metadata=None):
        """Add a command to the queue."""
        # if self.board is None:
        #     print('No board connected')
        #     return False
        # if manual:
        #     completed = self.check_if_all_completed()
        #     if not completed:
        #         print('Cannot add manual command while commands are in queue')
        #         return False
        blocked_reason = getattr(self, "_command_queue_blocked_reason", None)
        if blocked_reason and not getattr(self, "_transport_ready", False):
            message = (
                f"Cannot queue {command_type}: machine connection is not trusted after "
                f"{blocked_reason}. Reconnect to the MCU and home the motors before sending commands."
            )
            self._record_black_box_event(
                "command_rejected_untrusted_transport",
                {
                    "command_type": str(command_type or ""),
                    "blocked_reason": str(blocked_reason),
                },
            )
            print(message)
            self.error_occurred.emit(message)
            return False
        command = self.command_queue.add_command(
            command_type,
            param1,
            param2,
            param3,
            handler,
            kwargs,
            trace_metadata=trace_metadata,
        )
        if self._transport_ready and not self._tx_paused and not self._sequence_pause:
            self.pump_send_queue()
        return command
    
    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        if len(self.command_queue.queue) == 0:
            return True
        return False
    
    def get_remaining_commands(self):
        return len(self.command_queue.queue)
    
    def _write_frame(self, frame: bytes):
        if self.ser is None or not getattr(self.ser, "is_open", False):
            raise IOError("Serial port is not open")
        with QMutexLocker(self._tx_mutex):
            self.ser.write(frame)
            self.ser.flush()

    def send_command_to_board(self, command):
        """Send a command to the board."""
        try:
            self._write_frame(command.frame)
            self.command_sent.emit({"command": command.get_command()})
            print(f"Sent command: {command.get_command()}")
            return True
        except Exception as e:
            msg = f"Failed to send command: {e}"
            print(msg)
            self.error_occurred.emit(msg)
            return False

    def _cancel_queue_ack_waits_from(self, command_number):
        floor = int(command_number or 0)
        for key in list(self._pending_acks.keys()):
            ack_code, seq32, _seq8 = key
            if ack_code != CMD_QUEUE_ACK:
                continue
            if seq32 >= floor:
                self._cancel_ack_wait_by_key(key)

    def _mark_command_sent(self, command):
        command.send_attempts += 1
        if command.mark_as_sent():
            self._record_command_event(command, "sent")

    def _handle_transport_fault(self, message):
        payload = {"message": str(message)}
        self._record_black_box_event("transport_fault", payload)
        self._write_black_box_snapshot("transport_fault", payload)
        self._tx_paused = True
        try:
            self.stop_execution_timer()
        except Exception:
            pass
        print(message)
        self.error_occurred.emit(message)

    def _start_command_ack_wait(self, command):
        seq32 = int(getattr(command, "command_number", 0) or 0)
        self._start_ack_wait(
            CMD_QUEUE_ACK,
            seq32,
            self._queue_ack_timeout_ms,
            on_ok=lambda ack, seq=seq32: self._on_queue_ack(seq, ack),
            on_timeout=lambda _ack=None, seq=seq32: self._on_queue_ack_timeout(seq),
        )

    def _on_queue_ack(self, seq32, ack):
        command = self._find_command_by_number(seq32)
        if command is None:
            return

        ack_result = str((ack or {}).get("ack_result") or "")
        expected_seq32 = self._coerce_optional_int((ack or {}).get("expected_seq32"))

        if ack_result in {"accepted", "duplicate"}:
            self.command_queue.mark_command_accepted(seq32)
            self.pump_send_queue()
            return

        if ack_result == "gap":
            resend_from = expected_seq32 if expected_seq32 is not None else seq32
            lowest_queued = self._lowest_queued_command_number()
            if lowest_queued is not None and int(resend_from) < int(lowest_queued):
                self._handle_transport_fault(
                    f"MCU requested resend from command {resend_from}, but earliest local queued command is {lowest_queued}. Clear the queue or reconnect before continuing."
                )
                return
            if int(getattr(command, "send_attempts", 0) or 0) >= int(self._queue_ack_max_retries):
                self._handle_transport_fault(
                    f"Timed out recovering queue gap for command {seq32} after {command.send_attempts} attempts."
                )
                return
            self._cancel_queue_ack_waits_from(resend_from)
            self.command_queue.mark_for_resend_from(resend_from)
            self.pump_send_queue()
            return

        if ack_result == "busy":
            if int(getattr(command, "send_attempts", 0) or 0) >= int(self._queue_ack_max_retries):
                self._handle_transport_fault(
                    f"MCU remained busy for command {seq32} after {command.send_attempts} attempts."
                )
                return
            self.command_queue.mark_for_resend_from(seq32)
            QtCore.QTimer.singleShot(20, self.pump_send_queue)
            return

        if ack_result == "watermark_set":
            return

        if ack_result == "watermark_rejected":
            self._handle_transport_fault(
                f"MCU rejected pause-after watermark for seq32={seq32}."
            )
            return

        self._handle_transport_fault(
            f"Unexpected queue ACK result for seq32={seq32}: {ack_result or 'missing'}"
        )

    def _on_queue_ack_timeout(self, seq32):
        command = self._find_command_by_number(seq32)
        if command is None or command.status in {"Completed", "Canceled", "Accepted", "Executing"}:
            return
        if int(getattr(command, "send_attempts", 0) or 0) >= int(self._queue_ack_max_retries):
            self._handle_mcu_unresponsive(
                "ack_timeout",
                {
                    "command_number": int(seq32 or 0),
                    "command_type": str(getattr(command, "command_type", "") or ""),
                    "send_attempts": int(getattr(command, "send_attempts", 0) or 0),
                    "message": (
                        f"Timed out waiting for queue ACK for command {seq32} "
                        f"after {command.send_attempts} attempts."
                    ),
                },
            )
            return
        if command.reset_for_resend():
            self._record_command_event(command, "requeued")
        self.pump_send_queue()

    def _notify_pause_after_failure(self, on_failure, *, reason, barrier_seq32, ack_result=None, error=None):
        payload = {
            "reason": str(reason or "unknown"),
            "barrier_seq32": int(barrier_seq32 or 0),
            "ack_result": ack_result,
            "error": error,
        }
        if callable(on_failure):
            on_failure(payload)
            return

        detail = payload["reason"]
        if ack_result:
            detail = f"{detail}:{ack_result}"
        if error:
            detail = f"{detail}:{error}"
        self.error_occurred.emit(
            f"Pause-after watermark request failed for barrier {payload['barrier_seq32']}: {detail}"
        )

    def _emit_pause_after_success(self, request, payload):
        if request is None or request.get("success_emitted"):
            return
        request["success_emitted"] = True
        callback = request.get("on_success")
        if callable(callback):
            self._invoke_ack_callback(callback, payload)

    def _fail_pause_after_request(self, seq32, *, reason, ack_result=None, error=None):
        request = self._clear_pause_after_request(seq32)
        if request is None:
            return
        self._notify_pause_after_failure(
            request.get("on_failure"),
            reason=reason,
            barrier_seq32=request.get("barrier_seq32"),
            ack_result=ack_result,
            error=error,
        )

    def _handle_pause_after_queue_ack(self, ack):
        seq32 = self._coerce_optional_int((ack or {}).get("seq32"))
        if seq32 is None:
            return False
        request = self._pending_pause_after_requests.get(seq32)
        if request is None:
            return False

        request["last_ack"] = dict(ack or {})
        request["ack_received"] = True
        ack_result = str((ack or {}).get("ack_result") or "")
        if request.get("ack_timer") is not None:
            self._cleanup_timer(request.get("ack_timer"))
            request["ack_timer"] = None

        if ack_result == "watermark_rejected":
            self._fail_pause_after_request(
                seq32,
                reason="ack_rejected",
                ack_result=ack_result,
            )
            return True

        if ack_result in {"watermark_set", "accepted", "duplicate"}:
            request["ack_result"] = ack_result
            if ack_result == "watermark_set":
                request["status_confirmed"] = True
                self._emit_pause_after_success(request, ack)
            return True

        self._fail_pause_after_request(
            seq32,
            reason="ack_rejected",
            ack_result=ack_result or "missing",
        )
        return True

    def _status_confirms_pause_after_request(self, request, sample):
        if request is None or not isinstance(sample, dict):
            return False
        sample_ns = self._coerce_optional_int(sample.get("monotonic_ns"))
        created_ns = self._coerce_optional_int(request.get("created_monotonic_ns"))
        if sample_ns is not None and created_ns is not None and sample_ns < created_ns:
            return False
        barrier_seq32 = int(request.get("barrier_seq32") or 0)
        pause_after_seq32 = self._coerce_optional_int(sample.get("Pause_after_seq32"))
        if pause_after_seq32 == barrier_seq32 and barrier_seq32 > 0:
            return True
        return bool(sample.get("Pause_watermark_reached")) and bool(sample.get("Transport_paused"))

    def _update_pause_after_requests_from_status(self, sample):
        if not self._pending_pause_after_requests:
            return
        status_payload = dict(sample or {})
        for seq32, request in list(self._pending_pause_after_requests.items()):
            if not self._status_confirms_pause_after_request(request, status_payload):
                continue
            request["status_confirmed"] = True
            if request.get("ack_timer") is not None:
                self._cleanup_timer(request.get("ack_timer"))
                request["ack_timer"] = None
            self._emit_pause_after_success(
                request,
                {
                    "ack_result": "status_confirmed",
                    "barrier_seq32": int(request.get("barrier_seq32") or 0),
                    "status": dict(status_payload),
                },
            )

    def _on_pause_after_ack_timeout(self, seq32):
        request = self._pending_pause_after_requests.get(int(seq32 or 0))
        if request is None:
            return
        request["ack_timed_out"] = True
        if request.get("ack_timer") is not None:
            self._cleanup_timer(request.get("ack_timer"))
            request["ack_timer"] = None

    def _on_pause_after_confirm_timeout(self, seq32):
        request = self._pending_pause_after_requests.get(int(seq32 or 0))
        if request is None:
            return
        if request.get("status_confirmed"):
            self._clear_pause_after_request(seq32)
            return
        self._fail_pause_after_request(seq32, reason="not_confirmed")

    def request_pause_after_seq32(self, barrier_seq32, on_success=None, on_failure=None):
        barrier_seq32 = int(barrier_seq32 or 0)
        if barrier_seq32 <= 0:
            self._notify_pause_after_failure(
                on_failure,
                reason="invalid_barrier",
                barrier_seq32=barrier_seq32,
            )
            return False
        seq32 = self._alloc_ctl_seq32()
        frame = build_frame(PAUSE_AFTER_SEQ32, seq32, p1=barrier_seq32)
        try:
            self._write_frame(frame)
        except Exception as exc:
            self._notify_pause_after_failure(
                on_failure,
                reason="write_failed",
                barrier_seq32=barrier_seq32,
                error=str(exc),
            )
            return False

        self._clear_pause_after_request(seq32)
        ack_timer = QTimer(self)
        ack_timer.setSingleShot(True)
        ack_timer.timeout.connect(lambda s=seq32: self._on_pause_after_ack_timeout(s))
        confirm_timer = QTimer(self)
        confirm_timer.setSingleShot(True)
        confirm_timer.timeout.connect(lambda s=seq32: self._on_pause_after_confirm_timeout(s))
        self._pending_pause_after_requests[seq32] = {
            "seq32": seq32,
            "barrier_seq32": barrier_seq32,
            "on_success": on_success,
            "on_failure": on_failure,
            "ack_timer": ack_timer,
            "confirm_timer": confirm_timer,
            "created_monotonic_ns": int(time.monotonic_ns()),
            "ack_received": False,
            "ack_timed_out": False,
            "ack_result": None,
            "status_confirmed": False,
            "success_emitted": False,
            "last_ack": None,
        }
        ack_timer.start(self._pause_after_ack_timeout_ms)
        confirm_timer.start(self._pause_after_confirm_timeout_ms)
        return True

    def pump_send_queue(self):
        """
        Fill the transport window with locally queued commands.
        """
        if not self._transport_ready:
            return
        if getattr(self, "_tx_paused", False) or getattr(self, "_sequence_pause", False):
            return

        while True:
            command = self.command_queue.get_next_command()
            if not command:
                return

            if command.command_type in ('OPEN_GRIPPER', 'CLOSE_GRIPPER') and not self._gripper_ack_required:
                self._reset_gripper_idle_timer()

            if not self.send_command_to_board(command):
                return

            self._mark_command_sent(command)
            self._start_command_ack_wait(command)
            print(f"Sent command: {command.command_type} {command.param1} {command.param2} {command.param3}")

            if command.command_type in ('OPEN_GRIPPER', 'CLOSE_GRIPPER') and self._gripper_ack_required:
                self._tx_paused = True
                action = 'OPEN' if command.command_type == 'OPEN_GRIPPER' else 'CLOSE'
                self.require_gripper_confirmation.emit(action)
                return

    def send_next_command(self):
        self.pump_send_queue()
    
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
        self._pending_clear_request = {
            "handler": handler,
            "ack_received": False,
            "ack_timed_out": False,
        }

        self._start_ack_wait(
            CLEAR_ACK, seq, 2000,
            on_ok=lambda: self._on_clear_ack(timed_out=False),
            on_timeout=lambda: self._on_clear_ack(timed_out=True)
        )        

    def set_sequence_pause(self, paused: bool):
        self._sequence_pause = bool(paused)

    def _on_clear_ack(self, timed_out=False):
        if self._pending_clear_request is None:
            self._pending_clear_request = {
                "handler": None,
                "ack_received": False,
                "ack_timed_out": False,
            }

        if timed_out:
            print("No CLEAR_ACK received, proceeding anyway.")
            self._pending_clear_request["ack_timed_out"] = True
        else:
            print("CLEAR_ACK received, command queue cleared.")
            self._pending_clear_request["ack_received"] = True

        # Clear Python side queue & notify UI
        self.command_queue.clear_queue(reset_counter=False)

        self._wait_for_clear_status_deadline = time.time() + 0.5  # 500 ms fallback
        self._waiting_for_post_clear_status = True

        # self.begin_execution_timer()

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

    def _reject_regulator_profile_command(self, error):
        message = f"Invalid regulator profile command: {error}"
        print(message)
        self.error_occurred.emit(message)
        return False

    def enable_motors(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def disable_motors(self,handler=None,kwargs=None,manual=False):
        outcome = self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return outcome

    def set_axis_maxspeed(self, axis_idx, max_speed):
        return self.add_command_to_queue('SET_AXIS_MAXSPEED', axis_idx, max_speed, 0)

    def set_axis_accel(self, axis_idx, accel, handler=None, kwargs=None, manual=False):
        return self.add_command_to_queue('SET_AXIS_ACCEL', axis_idx, accel, 0, handler=handler, kwargs=kwargs, manual=manual)

    def _unsupported_global_accel_command(self, command_name):
        msg = (
            f"{command_name} is not supported by the current firmware command set. "
            "Use set_axis_accel per axis instead."
        )
        print(msg)
        self.error_occurred.emit(msg)
        return False

    def change_acceleration(self,acceleration,handler=None,kwargs=None,manual=False):
        return self._unsupported_global_accel_command("CHANGE_ACCEL")

    def reset_acceleration(self,handler=None,kwargs=None,manual=False):
        return self._unsupported_global_accel_command("RESET_ACCEL")
    
    def regulate_print_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_refuel_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def deregulate_print_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def deregulate_refuel_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_regulator_recovery_profile(self, channel, recovery_dict, handler=None, kwargs=None, manual=False):
        try:
            channel_code = _normalize_regulator_profile_channel(channel)
            recovery = _validate_regulator_profile_config(
                recovery_dict,
                REGULATOR_PROFILE_RECOVERY_BOUNDS,
                REGULATOR_PROFILE_RECOVERY_BOOL_FIELDS,
            )
        except ValueError as exc:
            return self._reject_regulator_profile_command(exc)

        flags = (
            (0x1 if recovery["allow_extend_while_undershoot"] else 0)
            | (0x2 if recovery["boost_only_when_undershoot"] else 0)
            | (0x4 if recovery["linear_decay"] else 0)
        )
        chunks = (
            (
                (0 << 8) | channel_code,
                _pack_regulator_profile_u16_pair(
                    recovery["active_ticks"],
                    recovery["base_boost_hz"],
                ),
                _pack_regulator_profile_u16_pair(
                    recovery["pulse_coeff_hz_per_us"],
                    recovery["pressure_coeff_hz_per_raw"],
                ),
            ),
            (
                (1 << 8) | channel_code,
                _pack_regulator_profile_u16_pair(
                    recovery["max_boost_hz"],
                    recovery["recovery_floor_hz"],
                ),
                _pack_regulator_profile_u16_pair(
                    recovery["recovery_exit_error_raw"],
                    recovery["max_extend_ticks"],
                ),
            ),
            (
                (2 << 8) | (1 << 16) | channel_code,
                flags,
                0,
            ),
        )
        commands = []
        for index, (p1, p2, p3) in enumerate(chunks):
            commands.append(
                self.add_command_to_queue(
                    'SET_REG_RECOVERY_PROFILE',
                    p1,
                    p2,
                    p3,
                    handler=handler if index == 2 else None,
                    kwargs=kwargs if index == 2 else None,
                    manual=manual,
                )
            )
        return commands

    def set_regulator_slew_profile(self, channel, slew_dict, handler=None, kwargs=None, manual=False):
        try:
            channel_code = _normalize_regulator_profile_channel(channel)
            slew = _validate_regulator_profile_config(
                slew_dict,
                REGULATOR_PROFILE_SLEW_BOUNDS,
            )
        except ValueError as exc:
            return self._reject_regulator_profile_command(exc)

        return self.add_command_to_queue(
            'SET_REG_SLEW_PROFILE',
            channel_code,
            _pack_regulator_profile_u16_pair(
                slew["max_hz_delta_up_per_loop"],
                slew["max_hz_delta_down_per_loop"],
            ),
            slew["recovery_bypass_slew_ticks"],
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def set_regulator_ready_profile(self, channel, ready_dict, handler=None, kwargs=None, manual=False):
        try:
            channel_code = _normalize_regulator_profile_channel(channel)
            ready = _validate_regulator_profile_config(
                ready_dict,
                REGULATOR_PROFILE_READY_BOUNDS,
            )
        except ValueError as exc:
            return self._reject_regulator_profile_command(exc)

        return self.add_command_to_queue(
            'SET_REG_READY_PROFILE',
            channel_code,
            ready["ready_tol_raw"],
            ready["consecutive_samples"],
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )

    def restore_regulator_profile(self, channels, source="baseline", handler=None, kwargs=None, manual=False):
        try:
            channel_mask = _normalize_regulator_profile_restore_mask(channels)
            source_code = _normalize_regulator_profile_restore_source(source)
        except ValueError as exc:
            return self._reject_regulator_profile_command(exc)

        return self.add_command_to_queue(
            'RESTORE_REG_PROFILE',
            channel_mask,
            source_code,
            0,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
        )
    
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

    def set_absolute_print_pressure(self,psi,handler=None,kwargs=None,manual=False,trace_metadata=None):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute print pressure:',pressure)
        if self.check_param_limits(pressure,0,10376):
            return self.add_command_to_queue(
                'ABSOLUTE_PRESSURE_P',
                pressure,
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
                trace_metadata=trace_metadata,
            )
        
    def set_absolute_refuel_pressure(self,psi,handler=None,kwargs=None,manual=False,trace_metadata=None):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute refuel pressure:',pressure)
        if self.check_param_limits(pressure,self.psi_offset,10376):
            return self.add_command_to_queue(
                'ABSOLUTE_PRESSURE_R',
                pressure,
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
                trace_metadata=trace_metadata,
            )

    def _validate_refuel_vacuum_pressure(self, psi):
        try:
            psi = float(psi)
        except (TypeError, ValueError):
            print(f'Refuel vacuum pressure is invalid: {psi}')
            return None
        if psi < -1.0 or psi > 0.0:
            print(f'Refuel vacuum pressure out of range (-1.0, 0.0): {psi}')
            return None
        return psi

    def enter_refuel_vacuum_mode(
        self,
        target_psi=-1.0,
        prep_position_steps=20000,
        move_hz=5000,
        handler=None,
        kwargs=None,
        manual=False,
    ):
        target_psi = self._validate_refuel_vacuum_pressure(target_psi)
        if target_psi is None:
            return False
        target_raw = self.convert_to_raw_pressure(target_psi)
        if (
            self.check_param_limits(target_raw, 764, self.psi_offset)
            and self.check_param_limits(int(prep_position_steps), 1, 100000)
            and self.check_param_limits(int(move_hz), 1, 40000)
        ):
            return self.add_command_to_queue(
                'REFUEL_VACUUM_ENTER',
                int(target_raw),
                int(prep_position_steps),
                int(move_hz),
                handler=handler,
                kwargs=kwargs,
                manual=manual,
            )
        return False

    def set_refuel_vacuum_pressure(self, pressure_psi, handler=None, kwargs=None, manual=False):
        pressure_psi = self._validate_refuel_vacuum_pressure(pressure_psi)
        if pressure_psi is None:
            return False
        target_raw = self.convert_to_raw_pressure(pressure_psi)
        if self.check_param_limits(target_raw, 764, self.psi_offset):
            return self.add_command_to_queue(
                'REFUEL_VACUUM_SET_TARGET',
                int(target_raw),
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
            )
        return False

    def exit_refuel_vacuum_mode(self, restore_pressure_psi, handler=None, kwargs=None, manual=False):
        try:
            restore_pressure_psi = float(restore_pressure_psi)
        except (TypeError, ValueError):
            print(f'Refuel vacuum restore pressure is invalid: {restore_pressure_psi}')
            return False
        if restore_pressure_psi < 0:
            restore_pressure_psi = 0.0
        restore_raw = self.convert_to_raw_pressure(restore_pressure_psi)
        if self.check_param_limits(restore_raw, self.psi_offset, 10376):
            return self.add_command_to_queue(
                'REFUEL_VACUUM_EXIT',
                int(restore_raw),
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
            )
        return False

    def set_print_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False,trace_metadata=None):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue(
                'SET_WIDTH_P',
                int(pulse_width),
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
                trace_metadata=trace_metadata,
            )
        
    def set_refuel_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False,trace_metadata=None):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue(
                'SET_WIDTH_R',
                int(pulse_width),
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
                trace_metadata=trace_metadata,
            )
    
    def enter_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('ENABLE_PRINT_PROFILE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def exit_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DISABLE_PRINT_PROFILE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
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
    
    def wait_ms(self, ms: int, handler=None, kwargs=None, manual=False):
        """Queue a firmware WAIT for ms milliseconds (param1=ms)."""
        ms = int(ms)
        if self.check_param_limits(ms, 1, 600000):  # 1 ms .. 10 min (adjust as you like)
            return self.add_command_to_queue('WAIT', ms, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
        return False

    def _get_dispense_rate_hz(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        getter = getattr(machine_model, "get_dispense_frequency_hz", None)
        try:
            value = getter() if callable(getter) else getattr(machine_model, "dispense_frequency_hz", 0)
        except Exception:
            value = 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    
    def print_droplets(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        rate_hz = self._get_dispense_rate_hz()
        return self.add_command_to_queue('DISPENSE',int(droplet_count),rate_hz,0,handler=handler,kwargs=kwargs,manual=manual)

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
    
    def capture_droplet_image(self, *, throughput_mode=False, capture_request_id=None):
        # Throughput mode is intended for repeated live imaging; keep strict mode for calibration.
        success_reasons = ("threshold", "fallback") if throughput_mode else ("threshold",)
        attempts = 2 if throughput_mode else 5
        attempt_timeout_s = 0.2 if throughput_mode else 1.0
        small_sleep_between = 0.01 if throughput_mode else 0.05
        max_new_frames = 4 if throughput_mode else 10
        return self.droplet_camera.capture_with_retry_async(
            attempts=attempts,
            max_new_frames=max_new_frames,
            attempt_timeout_s=attempt_timeout_s,
            small_sleep_between=small_sleep_between,
            success_reasons=success_reasons,
            request_id=capture_request_id,
        )

    def recover_droplet_capture(self, reason=""):
        recover = getattr(self.droplet_camera, "recover_stale_capture", None)
        if callable(recover):
            return recover(reason=reason)
        return {"ok": False, "reason": "recovery_not_supported"}

    def get_droplet_capture_state(self):
        getter = getattr(self.droplet_camera, "get_capture_state", None)
        if callable(getter):
            return getter()
        return {}
    
    def stop_droplet_camera(self):
        self.droplet_camera.stop_camera()
        return
    
    def start_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('START_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def stop_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('STOP_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_exposure_time(self, exposure_time, handler=None, trace_metadata=None):
        return self.droplet_camera.change_exposure_time(exposure_time,handler=handler)

    def set_droplet_capture_profile(self, profile_name: str):
        if hasattr(self.droplet_camera, "set_capture_profile"):
            self.droplet_camera.set_capture_profile(profile_name)
    
    def set_flash_duration(self,duration,handler=None,kwargs=None,manual=False,trace_metadata=None):
        duration = int(duration)
        # Hardware safety limit to protect LED; firmware also enforces this clamp.
        safe_duration = max(100, min(5000, duration))
        if safe_duration != duration:
            print(f"Clamped flash duration from {duration} ns to {safe_duration} ns for LED safety.")
        return self.add_command_to_queue(
            'SET_WIDTH_F',
            safe_duration,
            0,
            0,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def set_flash_delay(self,delay,handler=None,kwargs=None,manual=False,trace_metadata=None):
        delay = int(round(float(delay), 0))
        if delay >= 100:
            return self.add_command_to_queue(
                'SET_DELAY_F',
                delay,
                0,
                0,
                handler=handler,
                kwargs=kwargs,
                manual=manual,
                trace_metadata=trace_metadata,
            )

    def set_imaging_droplets(self,droplets,handler=None,kwargs=None,manual=False,trace_metadata=None):
        return self.add_command_to_queue(
            'SET_IMAGE_DROPLETS',
            int(droplets),
            0,
            0,
            handler=handler,
            kwargs=kwargs,
            manual=manual,
            trace_metadata=trace_metadata,
        )

    def print_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        rate_hz = self._get_dispense_rate_hz()
        return self.add_command_to_queue('DISPENSE_PRINT',int(droplet_count),rate_hz,0,handler=handler,kwargs=kwargs,manual=manual)

    def refuel_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        rate_hz = self._get_dispense_rate_hz()
        return self.add_command_to_queue('DISPENSE_REFUEL',int(droplet_count),rate_hz,0,handler=handler,kwargs=kwargs,manual=manual)
    
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
        
    def calibrate_pressure_handler(self):
        self.all_calibration_droplets_printed.emit()

    def print_calibration_droplets(self,num_droplets,manual=False,pressure=None,pulse_width=None):
        print('Machine: Printing calibration droplets')
        # if self.balance.simulate:
        #     if pressure is None:
        #         pressure = self.get_current_print_pressure()
        #     self.balance_droplets.append([num_droplets,pressure])
        self.check_param_limits(num_droplets,1,1000)
        self.print_droplets(num_droplets,handler=self.calibrate_pressure_handler,manual=manual)


