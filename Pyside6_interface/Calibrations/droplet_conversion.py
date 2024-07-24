import cv2
import numpy as np
import matplotlib.pyplot as plt
import os

pixels_per_micrometer = 0.879

# Function to calculate the volume of a sphere in cubic micrometers
def calculate_volume(diameter):
    radius = diameter / 2
    volume = (4/3) * np.pi * (radius ** 3)
    return volume

# Function to convert cubic micrometers to nanoliters
def cubic_meters_to_nanoliters(volume_cubic_micrometers):
    return volume_cubic_micrometers * 1e12

def process_image(image_path):

    # Load the droplet image
    image = cv2.imread(image_path)
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
    pixels_per_micrometer = 0.879  # Use the actual conversion factor calculated previously

    # Convert diameter from pixels to micrometers
    diameter_micrometers = diameter_pixels / pixels_per_micrometer
    diameter_meters = diameter_micrometers * 1e-6

    # Calculate the volume of the droplet in cubic micrometers
    volume_cubic_meters = calculate_volume(diameter_meters)

    # Convert the volume to nanoliters
    volume_nanoliters = cubic_meters_to_nanoliters(volume_cubic_meters)

    # print(f"Diameter in Pixels: {diameter_pixels}")
    # print(f"Diameter in Micrometers: {diameter_micrometers}")
    # # print(f"Volume of the Droplet (cubic micrometers): {volume_cubic_micrometers}")
    # print(f"Volume of the Droplet (nanoliters): {volume_nanoliters}")

    # # Draw the bounding box and center on the image
    # cv2.rectangle(image, (x, y), (x+w, y+h), (0, 255, 0), 2)
    # cv2.circle(image, (x + w//2, y + h//2), int(diameter_pixels//2), (255, 0, 0), 2)

    # # Show the image with the droplet marked
    # cv2.imshow('Droplet', image)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    return volume_nanoliters

image_directory = 'to_analyze'
volumes = []
files = []
for filename in os.listdir(image_directory):
    if filename.endswith(".jpg") or filename.endswith(".png"):  # Add more image extensions if needed
        image_path = os.path.join(image_directory, filename)
        # print(f"Processing image: {image_path}")
        volume = process_image(image_path)
        print(f"Volume of {filename}: {volume} nanoliters")
        files.append(filename)
        volumes.append(volume)

