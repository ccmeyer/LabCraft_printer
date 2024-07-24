import time
import numpy as np
import cv2
from datetime import datetime
import os
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
    
    def start_capture_thread(self,save=False):
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

        self.show_image(save=save)

    def show_image(self,save=False):
        # Display the captured image
        if self.image is None:
            print("No image to display")
            return
    
        if save:
            # Specify the directory and filename
            directory = "saved_images"
            filename = f"captured_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = os.path.join(directory, filename)
            
            # Create the directory if it doesn't exist
            if not os.path.exists(directory):
                os.makedirs(directory)
        
            # Save the image
            cv2.imwrite(filepath, self.image)
            print(f"Image saved to {filepath}")
            try:
                volume = self.process_image(self.image)
                print(f"Volume of the droplet: {volume:.2f} nanoliters")
            except Exception as e:
                print("Error processing image:", e)
        
        cv2.imshow('Captured Image', self.image)
        cv2.waitKey(0)  # Wait indefinitely until a key is pressed
        cv2.destroyAllWindows()
        self.image = None

    # Function to calculate the volume of a sphere in cubic micrometers
    def calculate_volume(self,diameter):
        radius = diameter / 2
        volume = (4/3) * np.pi * (radius ** 3)
        return volume

    # Function to convert cubic micrometers to nanoliters
    def cubic_meters_to_nanoliters(self,volume_cubic_micrometers):
        return volume_cubic_micrometers * 1e12

    def process_image(self,image):

        # Load the droplet image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Apply a binary threshold to segment the droplet
        _, thresh = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)

        # Find contours in the thresholded image
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Identify the largest contour as the droplet
        droplet_contour = max(contours, key=cv2.contourArea)

        # Calculate the bounding box of the droplet contour
        x, y, w, h = cv2.boundingRect(droplet_contour)

        # Calculate the diameter of the droplet (average of width and height)
        diameter_pixels = (w + h) / 2

        # Assume the previously calculated conversion factor (pixels_per_micrometer)
        pixels_per_micrometer = 0.879  # Derived from calibration

        # Convert diameter from pixels to micrometers
        diameter_micrometers = diameter_pixels / pixels_per_micrometer
        diameter_meters = diameter_micrometers * 1e-6

        # Calculate the volume of the droplet in cubic micrometers
        volume_cubic_meters = self.calculate_volume(diameter_meters)

        # Convert the volume to nanoliters
        volume_nanoliters = self.cubic_meters_to_nanoliters(volume_cubic_meters)

        return volume_nanoliters

    def __del__(self):
        self.stop_camera()
        self.line.release()
        self.chip.close()