# camera_pi.py
from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any


class CaptureCamera:
    """
    Minimal camera wrapper:
      - On Raspberry Pi: uses Picamera2 if available (recommended for Camera Module 2)
      - Elsewhere: falls back to OpenCV VideoCapture(0)

    get_frame() returns:
      (frame_bgr: np.ndarray | None, meta: dict)
    """

    def __init__(self, preview_size: Tuple[int, int] = (1280, 720)):
        self.preview_size = preview_size
        self.camera = None
        self._backend: Optional[str] = None

    @property
    def backend(self) -> Optional[str]:
        return self._backend

    def start_camera(self) -> None:
        # Try Picamera2
        try:
            from picamera2 import Picamera2

            self.camera = Picamera2(0)

            # Video configuration is usually best for live preview + quick captures
            config = self.camera.create_video_configuration(
                main={"size": self.preview_size, "format": "RGB888"}
            )
            self.camera.configure(config)
            self.camera.start()
            self._backend = "picamera2"
            return
        except Exception:
            pass

        # Fallback: OpenCV webcam
        self.camera = cv2.VideoCapture(0)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.preview_size[0]))
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.preview_size[1]))
        self._backend = "opencv"

    def get_frame(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        if self._backend == "picamera2":
            try:
                arr = self.camera.capture_array()  # RGB
                frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

                # Best-effort metadata (may be empty depending on pipeline)
                meta = {}
                try:
                    meta = self.camera.capture_metadata() or {}
                except Exception:
                    meta = {}

                return frame, meta
            except Exception as e:
                return None, {"error": str(e)}

        if self._backend == "opencv":
            try:
                ret, frame = self.camera.read()
                if not ret:
                    return None, {"error": "opencv read() failed"}
                meta = {
                    "frame_width": int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    "frame_height": int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    "fps": float(self.camera.get(cv2.CAP_PROP_FPS)),
                }
                return frame, meta
            except Exception as e:
                return None, {"error": str(e)}

        return None, {"error": "camera not started"}

    def stop_camera(self) -> None:
        if self._backend == "picamera2" and self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
            try:
                self.camera.close()
            except Exception:
                pass

        elif self._backend == "opencv" and self.camera:
            try:
                self.camera.release()
            except Exception:
                pass

        self.camera = None
        self._backend = None