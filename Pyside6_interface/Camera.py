import time
import numpy as np
import cv2
import gpiod
from picamera2 import Picamera2
import threading

class Camera:
    def __init__(self, main_window,gpio_pin=17):
        self.main_window = main_window
        self.gpio_pin = gpio_pin
        self.picam2 = Picamera2()
        self.initialized = False
        self.image = None
        self.chip = gpiod.Chip('gpiochip4')
        self.line = self.chip.get_line(self.gpio_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_OUT)
        self.line.set_value(0)

    def configure_camera(self, exposure_time):
        # config = self.picam2.create_still_configuration()
        # print('--- Modes:\n', self.picam2.sensor_modes(),'\n\n')
        config = self.picam2.create_still_configuration(main={"size": (640, 480)})
        self.picam2.configure(config)
        controls = {
            "ExposureTime": int(exposure_time),  # Set exposure time in microseconds
        }
        self.picam2.set_controls(controls)

    def set_exposure_time(self, exposure_time):
        self.picam2.stop()
        controls = {
            "ExposureTime": int(exposure_time),  # Set exposure time in microseconds
        }
        self.picam2.set_controls(controls)
        self.picam2.start()
        print("-- Camera changed,", self.picam2.capture_metadata()['ExposureTime'])


    def start_camera(self, exposure_time=1000000):
        if self.initialized:
            self.stop_camera()
            # self.picam2 = Picamera2()
        self.configure_camera(exposure_time)
        self.picam2.start()
        print("-- Camera started,", self.picam2.capture_metadata()['ExposureTime'])
        self.initialized = True
        time.sleep(2)  # Allow some time for the camera to adjust

    def stop_camera(self):
        self.picam2.stop()

    def start_flash(self):
        self.line.set_value(1)
    
    def stop_flash(self):
        self.line.set_value(0)

    def capture_image(self):
        print("Starting image capture")
        self.capture_event.set()
        self.image = self.picam2.capture_array()
        print("Image capture complete")
        return
    
    def start_capture_thread(self):
        self.capture_event = threading.Event()

        # Start the image capture in a separate thread
        self.capture_thread = threading.Thread(target=self.capture_image)
        self.capture_thread.start()

        # Wait until the capture has started
        self.capture_event.wait()

        self.start_flash()

        # Wait for the capture thread to finish
        self.capture_thread.join()
        self.stop_flash()

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

    def live_preview(self):
        """Displays a live preview of the camera feed, updating every second."""
        self.picam2.stop()  # Stop the camera if it is already running  
        try:
            self.picam2.start_preview()  # Start the picamera2 preview functionality
            print("Live preview started. Press 'q' to quit.")
            while True:
                time.sleep(1)  # Update the image every second
                frame = self.picam2.capture_array()  # Capture the current frame
                cv2.imshow("Live Preview", frame)  # Display the frame using OpenCV
                if cv2.waitKey(1) & 0xFF == ord('q'):  # Break the loop if 'q' is pressed
                    break
        finally:
            cv2.destroyAllWindows()  # Make sure to destroy all OpenCV windows
            self.picam2.stop_preview()  # Stop the picamera2 preview functionality
            print("Live preview stopped.")

    def __del__(self):
        self.stop_camera()
        self.line.release()
        self.chip.close()