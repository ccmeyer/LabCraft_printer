from picamera2 import Picamera2

class RefuelCamera():
    def __init__(self):
        super().__init__()

    def start_camera(self):
        # Initialize Picamera2
        self.camera = Picamera2()
        self.camera.configure(self.camera.create_still_configuration(
            main={"size": self.camera.sensor_resolution, "format": "RGB888"}
        ))
        self.camera.start()

    def capture_image(self):
        return self.camera.capture_array()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera.close()