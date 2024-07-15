import time
import numpy as np
import cv2
import gpiod
from picamera2 import Picamera2
import threading

class Camera:
    def __init__(self, main_window,gpio_pin=17, debounce_time=0.02):
        self.main_window = main_window
        self.gpio_pin = gpio_pin
        self.debounce_time = debounce_time
        self.last_high_time = None
        self.picam2 = Picamera2()
        self.image = None
        self.chip = gpiod.Chip('gpiochip4')
        self.line = self.chip.get_line(self.gpio_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_IN)

    def configure_camera(self, exposure_time):
        config = self.picam2.create_still_configuration()
        self.picam2.configure(config)
        controls = {
            "ExposureTime": int(exposure_time),  # Set exposure time in microseconds
        }
        self.picam2.set_controls(controls)

    # def capture_image(self):
    #     # Capture an image
    #     image = self.picam2.capture_array()
    #     return image
    
    def capture_image(self):
        print("Starting image capture")
        self.capture_event.set()
        self.image = self.picam2.capture_array()
        print("Image capture complete")
        return
    
    def start_capture_thread(self,num_flashes,flash_duration,inter_flash_delay):
        self.capture_event = threading.Event()

        # Start the image capture in a separate thread
        self.capture_thread = threading.Thread(target=self.capture_image)
        self.capture_thread.start()

        # Wait until the capture has started
        self.capture_event.wait()

        self.main_window.machine.flash_led(num_flashes,flash_duration,inter_flash_delay)

        # Wait for the capture thread to finish
        self.capture_thread.join()

        self.show_image()

    def show_image(self):
        # Display the captured image
        if self.image is None:
            print("No image to display")
            return
        cv2.imshow('Captured Image', self.image)
        cv2.waitKey(0)  # Wait indefinitely until a key is pressed
        cv2.destroyAllWindows()
        self.image = None

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