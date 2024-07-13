# import time
# import cv2
# import RPi.GPIO as GPIO

# # Set up GPIO
# GPIO.setmode(GPIO.BCM)  # Use BCM pin numbering
# GPIO.setup(17, GPIO.IN)  # Replace 17 with your GPIO pin number

# # Initialize the camera
# cap = cv2.VideoCapture(0)  # Use the first camera

# def capture_and_show_image():
#     # Wait for 500 milliseconds
#     time.sleep(0.5)
    
#     # Capture an image
#     ret, frame = cap.read()
#     if ret:
#         # Show the captured image
#         cv2.imshow('Captured Image', frame)
#         cv2.waitKey(0)  # Wait indefinitely until a key is pressed
#         cv2.destroyAllWindows()
#     else:
#         print("Failed to capture image")

# try:
#     while True:
#         # Check the GPIO pin state
#         if GPIO.input(17) == GPIO.HIGH:
#             print("HIGH signal detected, capturing image...")
#             capture_and_show_image()
#         else:
#             print("Waiting for HIGH signal...")
        
#         # Sleep for a short period to avoid busy-waiting
#         time.sleep(0.1)
# except KeyboardInterrupt:
#     print("Script terminated by user")
# finally:
#     # Clean up GPIO and release the camera
#     GPIO.cleanup()
#     cap.release()
import time
import cv2
import gpiod

# Define the GPIO pin
GPIO_PIN = 17
WRITE_PIN = 27

# Initialize GPIO
chip = gpiod.Chip('gpiochip0')  # Use the correct gpiochip for your GPIO pin
read = chip.get_line(GPIO_PIN)
read.request(consumer="Read", type=gpiod.LINE_REQ_DIR_IN)
write = chip.get_line(WRITE_PIN)
write.request(consumer="Write", type=gpiod.LINE_REQ_DIR_OUT)
write_value = 0
write.set_value(write_value)
counter = 0

# Initialize the camera
cap = cv2.VideoCapture(0)  # Use the first camera

def capture_and_show_image():
    # Wait for 500 milliseconds
    time.sleep(0.5)
    
    # Capture an image
    ret, frame = cap.read()
    if ret:
        # Show the captured image
        cv2.imshow('Captured Image', frame)
        cv2.waitKey(0)  # Wait indefinitely until a key is pressed
        cv2.destroyAllWindows()
    else:
        print("Failed to capture image")

try:
    while True:
        # Check the GPIO pin state
        if counter == 10:
            print("No HIGH signal detected for 10 seconds, resetting counter...")
            counter = 0
            if write_value == 1:
                write_value = 0
                write.set_value(write_value)
            else:
                write_value = 1
                write.set_value(write_value)
        if read.get_value() == 1:
            print("HIGH signal detected, capturing image...")
            capture_and_show_image()
        else:
            print("Waiting for HIGH signal...")
            counter += 1
        
        # Sleep for a short period to avoid busy-waiting
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Script terminated by user")
finally:
    # Clean up
    read.release()
    write.release()
    cap.release()
