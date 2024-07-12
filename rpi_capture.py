import time
import cv2
import RPi.GPIO as GPIO

# Set up GPIO
GPIO.setmode(GPIO.BCM)  # Use BCM pin numbering
GPIO.setup(17, GPIO.IN)  # Replace 17 with your GPIO pin number

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
        if GPIO.input(17) == GPIO.HIGH:
            print("HIGH signal detected, capturing image...")
            capture_and_show_image()
        else:
            print("Waiting for HIGH signal...")
        
        # Sleep for a short period to avoid busy-waiting
        time.sleep(0.1)
except KeyboardInterrupt:
    print("Script terminated by user")
finally:
    # Clean up GPIO and release the camera
    GPIO.cleanup()
    cap.release()
