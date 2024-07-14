import time
import numpy as np
import cv2
import gpiod
from picamera2 import Picamera2

# Define the GPIO pin for the signal
GPIO_PIN = 17
DEBOUNCE_TIME = 0.02  # 20 milliseconds

# Initialize GPIO
chip = gpiod.Chip('gpiochip4')  # Use the correct gpiochip for your GPIO pin
line = chip.get_line(GPIO_PIN)
line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_IN)

# Initialize the camera
picam2 = Picamera2()

def configure_camera(exposure_time):
    config = picam2.create_still_configuration()
    picam2.configure(config)
    controls = {
        "ExposureTime": exposure_time,  # Set exposure time in microseconds
    }
    picam2.set_controls(controls)

def capture_image():
    # Capture an image
    image = picam2.capture_array()
    return image

def show_image(image):
    # Display the captured image
    cv2.imshow('Captured Image', image)
    cv2.waitKey(0)  # Wait indefinitely until a key is pressed
    cv2.destroyAllWindows()

def debounce_signal(line, last_high_time, debounce_time=0.02):
    """Check if the signal remains HIGH for the debounce time."""
    current_time = time.time()
    signal = line.get_value()
    print(signal)
    if signal == 1:
        if last_high_time is None:
            # Start of a new HIGH signal
            last_high_time = current_time
        elif current_time - last_high_time >= debounce_time:
            # Signal has remained HIGH for debounce time
            return True, current_time
    else:
        # Signal is LOW, reset the timer
        last_high_time = None
    return False, last_high_time

try:
    # Configure and start the camera
    exposure_time = 10000  # 10 ms exposure time
    configure_camera(exposure_time)
    picam2.start()
    time.sleep(2)  # Allow some time for the camera to adjust

    last_high_time = None

    while True:
        # Check the GPIO pin state with debounce logic
        signal_stable, last_high_time = debounce_signal(line, last_high_time, DEBOUNCE_TIME)
        if signal_stable:
            print("HIGH signal detected, capturing image...")
            # image = capture_image()
            # show_image(image)
            last_high_time = None  # Reset after capturing
        else:
            # print("Waiting for HIGH signal...", end="")
            print("...", end="")
        
        # Sleep for a short period to avoid busy-waiting
        time.sleep(0.01)

except KeyboardInterrupt:
    print("Script terminated by user")
finally:
    # Stop and release the camera
    picam2.stop()
    line.release()
