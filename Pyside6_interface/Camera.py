import time
import numpy as np
import cv2
import gpiod
from picamera2 import Picamera2

class Camera:
    def __init__(self, gpio_pin=17, debounce_time=0.02):
        self.gpio_pin = gpio_pin
        self.debounce_time = debounce_time
        self.last_high_time = None
        self.picam2 = Picamera2()
        self.chip = gpiod.Chip('gpiochip4')
        self.line = self.chip.get_line(self.gpio_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_IN)

    def configure_camera(self, exposure_time):
        config = self.picam2.create_still_configuration()
        self.picam2.configure(config)
        controls = {
            "ExposureTime": exposure_time,  # Set exposure time in microseconds
        }
        self.picam2.set_controls(controls)

    def capture_image(self):
        # Capture an image
        image = self.picam2.capture_array()
        return image

    def show_image(self, image):
        # Display the captured image
        cv2.imshow('Captured Image', image)
        cv2.waitKey(0)  # Wait indefinitely until a key is pressed
        cv2.destroyAllWindows()

    # def debounce_signal(self):
    #     """Check if the signal remains HIGH for the debounce time."""
    #     current_time = time.time()
    #     signal = self.line.get_value()
    #     print(signal)
    #     if signal == 1:
    #         if self.last_high_time is None:
    #             # Start of a new HIGH signal
    #             self.last_high_time = current_time
    #         elif current_time - self.last_high_time >= self.debounce_time:
    #             # Signal has remained HIGH for debounce time
    #             return True, current_time
    #     else:
    #         # Signal is LOW, reset the timer
    #         self.last_high_time = None
    #     return False, self.last_high_time

    def start_camera(self, exposure_time=100000):
        self.configure_camera(exposure_time)
        self.picam2.start()
        time.sleep(0.5)  # Allow some time for the camera to adjust

    def stop_camera(self):
        self.picam2.stop()

    def __del__(self):
        self.stop_camera()
        self.line.release()
        self.chip.close()