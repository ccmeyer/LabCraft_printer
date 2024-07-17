import time
import numpy as np
import cv2
import gpiod
from picamera2 import Picamera2

class Camera:
    def __init__(self, gpio_pin=17):
        self.picam2 = Picamera2()
        self.initialized = False
        self.image = None
        self.chip = gpiod.Chip('gpiochip4')
        self.line = self.chip.get_line(gpio_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_OUT)
        self.line.set_value(0)

    def live_preview(self):
        """Displays a live preview of the camera feed, updating every second."""
        try:
            self.picam2.start()  # Start the picamera2 preview functionality
            print("Live preview started. Press 'q' to quit.")
            while True:
                time.sleep(1)  # Update the image every second
                frame = self.picam2.capture_array()  # Capture the current frame
                cv2.imshow("Live Preview", frame)  # Display the frame using OpenCV
                if cv2.waitKey(1) & 0xFF == ord('q'):  # Break the loop if 'q' is pressed
                    break
        finally:
            cv2.destroyAllWindows()  # Make sure to destroy all OpenCV windows
            self.picam2.stop()  # Stop the picamera2 preview functionality
            print("Live preview stopped.")

if __name__ == "__main__":
    camera = Camera()
    camera.live_preview()