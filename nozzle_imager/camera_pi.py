# camera_pi.py
import cv2
import numpy as np

class RefuelCamera:
    """
    Minimal Picamera2 camera wrapper. If Picamera2 is not available, we
    automatically fall back to OpenCV VideoCapture(0) so you can test on a laptop.
    """
    def __init__(self):
        self.camera = None
        self._backend = None

    def start_camera(self):
        try:
            from picamera2 import Picamera2
            self.camera = Picamera2(0)
            self.camera.configure(self.camera.create_still_configuration(
                main={"size": self.camera.sensor_resolution, "format": "RGB888"}
            ))
            self.camera.start()
            self._backend = "picamera2"
        except Exception:
            # Fallback for dev machines: webcam
            self.camera = cv2.VideoCapture(0)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self._backend = "opencv"

    def capture_image(self):
        if self._backend == "picamera2":
            arr = self.camera.capture_array()  # RGB
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        elif self._backend == "opencv":
            ret, frame = self.camera.read()
            return frame if ret else None
        return None

    def stop_camera(self):
        if self._backend == "picamera2" and self.camera:
            self.camera.stop()
            self.camera.close()
        elif self._backend == "opencv" and self.camera:
            self.camera.release()
        self.camera = None
        self._backend = None
