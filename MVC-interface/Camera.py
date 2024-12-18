from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget, QSpinBox, QGridLayout
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt, QTimer
from picamera2 import Picamera2
import numpy as np
import cv2
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from scipy.signal import find_peaks

def numpy_to_qimage(image):
    """
    Converts a numpy array (captured image) to a QImage.
    """
    height, width, channels = image.shape
    bytes_per_line = channels * width
    qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGB888)
    return qimage.rgbSwapped()

def numpy_to_qimage_grayscale(image):
    """
    Converts a grayscale numpy array to a QImage.
    """
    height, width = image.shape
    bytes_per_line = width
    qimage = QImage(image.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
    return qimage
    
def find_key_points(columns, line_values):
    """
    Identifies two low points and the high point between them in the data.

    Args:
        columns (np.array): The column indices (x-axis values).
        line_values (np.array): The pixel sum values (y-axis values).

    Returns:
        tuple: (low1_index, high_index, low2_index)
               Indices of the first low point, the high point, and the second low point.
    """
    # Negate the line_values to find minima using find_peaks
    inverted_values = -line_values
    low_points_indices = find_peaks(inverted_values)[0]  # Indices of local minima

    # Find the first two minima (low points)
    if len(low_points_indices) < 2:
        # ValueError("Not enough local minima found to identify two low points.")
        return None,None,None

    low1_index = low_points_indices[0]
    low2_index = low_points_indices[1]

    # Ensure the first low point comes before the second
    if low1_index > low2_index:
        low1_index, low2_index = low2_index, low1_index

    # Find the local maximum (high point) between the two low points
    high_point_indices = find_peaks(line_values)[0]  # Indices of local maxima
    high_index = None

    for idx in high_point_indices:
        if low1_index < idx < low2_index:
            high_index = idx
            break

    if high_index is None:
        raise ValueError("No local maximum found between the two low points.")

    return low1_index, high_index, low2_index
    
def find_low_point(rows,row_values):
    inverted_values = -row_values
    all_peaks = find_peaks(inverted_values)
    if len(all_peaks) > 0:
        if len(all_peaks[0]) > 0:
            lowest_point = all_peaks[0][0]
        else:
            lowest_point = None
    else:
        lowest_point = None
    return lowest_point
    
def calculate_rate_of_change(x, y):
    """
    Calculates the rate of change (first derivative) of y with respect to x.

    Args:
        x (np.array): Array of x values.
        y (np.array): Array of y values.

    Returns:
        np.array: Rate of change values.
        np.array: Midpoint x values where rate of change is calculated.
    """
    rate_of_change = np.diff(y) / np.diff(x)  # First derivative
    mid_x = (x[:-1] + x[1:]) / 2  # Midpoints between consecutive x values
    return rate_of_change

def find_largest_prominent_peak(rate_of_change):
    """
    Finds the largest peak based on prominence or width in the rate of change.

    Args:
        rate_of_change (np.array): Array of rate of change values.

    Returns:
        int: Index of the largest prominent peak.
    """
    peaks, _ = find_peaks(np.abs(rate_of_change))  # Find peaks of absolute rate of change
    if len(peaks) == 0:
        #raise ValueError("No peaks found in rate of change.")
        return None
    largest_peak_index = peaks[np.argmax(np.abs(rate_of_change[peaks]))]
    # ~ # Find peaks and calculate their prominence and width
    # ~ peaks, properties = find_peaks(np.abs(rate_of_change), prominence=10, width=2)
    
    # ~ if len(peaks) == 0:
        # ~ raise ValueError("No prominent peaks found in rate of change.")

    # ~ # Rank peaks based on prominence or width
    # ~ prominences = properties["prominences"]  # Prominence of each peak
    # ~ widths = properties["widths"]            # Width of each peak

    # ~ # Select the peak with the largest prominence
    # ~ largest_peak_index = peaks[np.argmax(widths)]

    return largest_peak_index

class CameraApp(QWidget):
    def __init__(self):
        super().__init__()

        # Initialize Picamera2
        self.camera = Picamera2()
        self.camera.configure(self.camera.create_still_configuration(
            main={"size": self.camera.sensor_resolution, "format": "RGB888"}
        ))
        self.camera.start()

        # UI Elements
        self.layout = QGridLayout()

        self.control_layout = QVBoxLayout()
        self.capture_button = QPushButton("Start Capturing Images")
        self.capture_button.clicked.connect(self.toggle_capture)

        self.save_button = QPushButton("Save Current Frame")
        self.save_button.clicked.connect(self.save_frame)

        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(0, 255)
        self.threshold_spinbox.setValue(120)
        self.threshold_spinbox.setSingleStep(5)
        self.threshold_spinbox.setPrefix("Threshold: ")
        self.threshold_spinbox.valueChanged.connect(self.update_analysis)

        self.blur_spinbox = QSpinBox()
        self.blur_spinbox.setRange(1, 31)  # Allow odd values for Gaussian blur size
        self.blur_spinbox.setValue(31)
        self.blur_spinbox.setSingleStep(2)
        self.blur_spinbox.setPrefix("Blur: ")
        self.blur_spinbox.valueChanged.connect(self.update_analysis)

        self.red_line_spinbox = QSpinBox()
        self.red_line_spinbox.setRange(0, 640)  # Assuming cropped image max width
        self.red_line_spinbox.setValue(10)
        self.red_line_spinbox.setPrefix("Red Line: ")
        self.red_line_spinbox.valueChanged.connect(self.update_analysis)

        self.blue_line_spinbox = QSpinBox()
        self.blue_line_spinbox.setRange(0, 640)  # Assuming cropped image max width
        self.blue_line_spinbox.setValue(30)
        self.blue_line_spinbox.setPrefix("Blue Line: ")
        self.blue_line_spinbox.valueChanged.connect(self.update_analysis)

        self.image_label = QLabel("No image captured yet.")
        self.image_label.setAlignment(Qt.AlignCenter)

        self.analyzed_image_label = QLabel("No analyzed image yet.")
        self.analyzed_image_label.setAlignment(Qt.AlignCenter)

        self.cropped_image_label = QLabel("No cropped image yet.")
        self.cropped_image_label.setAlignment(Qt.AlignCenter)

        self.plot_figure, self.plot_ax = plt.subplots()
        self.plot_canvas = FigureCanvas(self.plot_figure)
        
        self.volume_figure, self.volume_ax = plt.subplots()
        self.volume_canvas = FigureCanvas(self.volume_figure)
        
        self.level_cropped_image_label = QLabel("No level cropped image yet.")
        self.level_cropped_image_label.setAlignment(Qt.AlignCenter)

        self.control_layout.addWidget(self.capture_button)
        self.control_layout.addWidget(self.save_button)
        self.control_layout.addWidget(self.threshold_spinbox)
        self.control_layout.addWidget(self.blur_spinbox)
        self.control_layout.addWidget(self.red_line_spinbox)
        self.control_layout.addWidget(self.blue_line_spinbox)
        self.layout.addLayout(self.control_layout, 0, 0, 2, 1)
        self.layout.addWidget(self.image_label, 0, 1)
        self.layout.addWidget(self.analyzed_image_label, 0, 2)
        self.layout.addWidget(self.cropped_image_label, 0, 3)
        self.layout.addWidget(self.plot_canvas, 1, 1)
        self.layout.addWidget(self.volume_canvas, 1, 2)
        self.layout.addWidget(self.level_cropped_image_label, 1, 3)

        self.setLayout(self.layout)
        self.setWindowTitle("Camera App")

        # Timer for periodic image capture
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture_image)
        self.capturing = False

        # Store the latest frame
        self.latest_frame = None

    def toggle_capture(self):
        """
        Starts or stops capturing images based on the button toggle.
        """
        if self.capturing:
            self.timer.stop()
            self.capture_button.setText("Start Capturing Images")
        else:
            self.timer.start(100)  # Capture every 100 milliseconds
            self.capture_button.setText("Stop Capturing Images")
        self.capturing = not self.capturing

    def capture_image(self):
        """
        Captures an image and displays it in the QLabel.
        """
        # Capture image as numpy array
        frame = self.camera.capture_array()

        # Resize the image to fit within 640x480 while maintaining aspect ratio
        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)

        # Store the latest frame
        self.latest_frame = frame

        # Convert numpy array to QImage for display
        qimage = numpy_to_qimage(frame)

        # Display original image
        pixmap = QPixmap.fromImage(qimage)
        self.image_label.setPixmap(pixmap)
        self.image_label.setScaledContents(True)

        # Perform analysis
        self.update_analysis()

    def update_analysis(self):
        """
        Updates the analyzed image using the current threshold value and blur size.
        """
        if self.latest_frame is not None:
            gray = cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2GRAY)

            # Ensure blur size is odd
            blur_size = self.blur_spinbox.value()
            if blur_size % 2 == 0:
                blur_size += 1

            blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
            threshold_value = self.threshold_spinbox.value()
            _, thresholded = cv2.threshold(blurred, threshold_value, 255, cv2.THRESH_BINARY)

            # Convert the grayscale thresholded image to BGR for color drawing
            thresholded_color = cv2.cvtColor(thresholded, cv2.COLOR_GRAY2BGR)

            # Find contours in the thresholded image
            contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Identify the largest contour by area
            largest_contour = max(contours, key=cv2.contourArea) if contours else None

            cropped_image = None

            if largest_contour is not None:
                x, y, w, h = cv2.boundingRect(largest_contour)
                cv2.rectangle(thresholded_color, (x, y), (x + w, y + h), (0, 0, 255), 2)  # Draw red bounding rectangle

                # Crop the original image based on the bounding rectangle
                cropped_image = self.latest_frame[y:y + h, x:x + w]

                # Draw vertical lines on the cropped image
                if cropped_image is not None:
                    cropped_image = np.ascontiguousarray(cropped_image)  # Ensure memory is contiguous
                    level_image = cropped_image.copy()
                    height, width, _ = cropped_image.shape
                    red_line_x = np.clip(self.red_line_spinbox.value(), 0, width - 1)
                    blue_line_x = np.clip(self.blue_line_spinbox.value(), 0, width - 1)
                    cv2.line(cropped_image, (red_line_x, 0), (red_line_x, height), (0, 0, 255), 1)
                    cv2.line(cropped_image, (blue_line_x, 0), (blue_line_x, height), (255, 0, 0), 1)

                    # Generate plot data
                    if red_line_x < blue_line_x - 1:  # Ensure there's at least one column between the lines
                        cropped_gray = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
                        line_values = cropped_gray[:, red_line_x + 1:blue_line_x].sum(axis=0)  # Exclude red_line_x column
                        columns = np.arange(red_line_x + 1, blue_line_x)
                        
                        left_edge_idx, center_idx, right_edge_idx = find_key_points(columns, line_values)

                        # Update the plot
                        self.plot_ax.clear()
                        self.volume_ax.clear()
                        self.plot_ax.plot(columns, line_values, color="green")
                        if left_edge_idx is not None:
                            self.plot_ax.scatter(columns[left_edge_idx], line_values[left_edge_idx], color="blue", zorder=5)
                            self.plot_ax.text(columns[left_edge_idx], line_values[left_edge_idx] - 500, "Low 1", color="blue")
                        if center_idx is not None:
                            self.plot_ax.scatter(columns[center_idx], line_values[center_idx], color="red", zorder=5)
                            self.plot_ax.text(columns[center_idx], line_values[center_idx] + 500, "High", color="red")
                        if right_edge_idx is not None:
                            self.plot_ax.scatter(columns[right_edge_idx], line_values[right_edge_idx], color="blue", zorder=5)
                            self.plot_ax.text(columns[right_edge_idx], line_values[right_edge_idx] - 500, "Low 2", color="blue")
                        
                        if center_idx is not None:
                            buffer_rows = 10
                            channel_thickness = 3
                            row_values = np.array(cropped_gray[buffer_rows:-buffer_rows, columns[center_idx]-channel_thickness:columns[center_idx]+channel_thickness].sum(axis=1))
                            row_x_values = np.array(range(buffer_rows,len(row_values)+buffer_rows))
                            row_values = row_values.astype(np.int64)  # Cast to safe integer type

                            # Calculate rate of change
                            rate_of_change = calculate_rate_of_change(row_x_values,row_values)

                            self.volume_ax.plot(row_x_values[:],row_values,color="black")
                            # Find largest peak in rate of change
                            largest_peak_index = find_largest_prominent_peak(rate_of_change)

                            if largest_peak_index is not None:
                                largest_peak_x = row_x_values[largest_peak_index+1]
                                self.volume_ax.scatter(largest_peak_x, row_values[largest_peak_index], color="red", zorder=5)

                                cv2.line(level_image, (0, largest_peak_x), (width, largest_peak_x), (0, 0, 255), 1)

                        self.plot_ax.set_title("Sum of Pixel Values")
                        self.plot_ax.set_xlabel("Column")
                        self.plot_ax.set_ylabel("Sum of Pixel Values")
                        self.plot_canvas.draw()
                        
                        self.volume_ax.set_title("Sum of Pixel Values")
                        self.volume_ax.set_xlabel("Row")
                        self.volume_ax.set_ylabel("Sum of Pixel Values")
                        self.volume_canvas.draw()

            # Update analyzed image label
            analyzed_qimage = numpy_to_qimage(thresholded_color)
            analyzed_pixmap = QPixmap.fromImage(analyzed_qimage)
            self.analyzed_image_label.setPixmap(analyzed_pixmap)
            self.analyzed_image_label.setScaledContents(True)

            # Update cropped image label
            if cropped_image is not None:
                cropped_qimage = numpy_to_qimage(cropped_image)
                cropped_pixmap = QPixmap.fromImage(cropped_qimage)
                self.cropped_image_label.setPixmap(cropped_pixmap)
                self.cropped_image_label.setScaledContents(True)
                
                level_qimage = numpy_to_qimage(level_image)
                level_pixmap = QPixmap.fromImage(level_qimage)
                self.level_cropped_image_label.setPixmap(level_pixmap)
                self.level_cropped_image_label.setScaledContents(True)

    def save_frame(self):
        """
        Saves the latest captured frame to a file.
        """
        if self.latest_frame is not None:
            save_dir = "Images"
            os.makedirs(save_dir, exist_ok=True)

            # Find the next available filename
            existing_files = [f for f in os.listdir(save_dir) if f.startswith("image_") and f.endswith(".png")]
            existing_indices = [int(f.split("_")[1].split(".")[0]) for f in existing_files]
            next_index = max(existing_indices, default=0) + 1

            save_path = os.path.join(save_dir, f"image_{next_index:03}.png")
            cv2.imwrite(save_path, self.latest_frame)
            print(f"Frame saved to {save_path}")
            
            # Save the plot
            plot_path = os.path.join(save_dir, f"plot_{next_index:03}.png")
            self.volume_figure.savefig(plot_path)
            print(f"Line plot saved to {plot_path}")
        else:
            print("No frame to save.")

    def closeEvent(self, event):
        """
        Ensures the camera stops when the application is closed.
        """
        self.timer.stop()
        self.camera.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication([])

    window = CameraApp()
    window.resize(1920, 960)  # Adjusted for 2x2 grid layout
    window.show()

    app.exec()
    
# ~ import numpy as np
# ~ import matplotlib.pyplot as plt
# ~ from scipy.signal import find_peaks

# ~ def calculate_rate_of_change(x, y):
    # ~ """
    # ~ Calculates the rate of change (first derivative) of y with respect to x.

    # ~ Args:
        # ~ x (np.array): Array of x values.
        # ~ y (np.array): Array of y values.

    # ~ Returns:
        # ~ np.array: Rate of change values.
        # ~ np.array: Midpoint x values where rate of change is calculated.
    # ~ """
    # ~ rate_of_change = np.diff(y) / np.diff(x)  # First derivative
    # ~ mid_x = (x[:-1] + x[1:]) / 2  # Midpoints between consecutive x values
    # ~ return rate_of_change, mid_x

# ~ def find_largest_peak(rate_of_change):
    # ~ """
    # ~ Finds the largest peak (absolute value) in the rate of change.

    # ~ Args:
        # ~ rate_of_change (np.array): Array of rate of change values.

    # ~ Returns:
        # ~ int: Index of the largest peak.
    # ~ """
    # ~ peaks, _ = find_peaks(np.abs(rate_of_change))  # Find peaks of absolute rate of change
    # ~ if len(peaks) == 0:
        # ~ raise ValueError("No peaks found in rate of change.")
    # ~ largest_peak_index = peaks[np.argmax(np.abs(rate_of_change[peaks]))]
    # ~ return largest_peak_index
# ~ # Example Data
# ~ y = np.array([1014, 980, 941, 910, 910, 884, 856, 812, 786, 807, 820, 806, 791, 796, 814, 819, 814, 826, 848, 814, 783, 778, 777, 776, 779, 782, 776, 766, 755, 705, 633, 567, 637, 901, 1054, 1160, 1177, 1178, 1156, 1168, 1195, 1193, 1161, 1188, 1186, 1188, 1172, 1131, 1142, 1152, 1158, 1112, 1093, 1073, 1065, 1073, 1073, 1045, 1017, 990, 950, 947, 935, 945, 953, 938, 913, 907, 912, 868, 927, 912, 900, 889, 899, 895, 871, 892, 906, 915, 920, 898, 875, 869, 873, 855, 859, 887, 915, 933, 931, 946, 940, 955, 987, 1021, 1009]
# ~ )
# ~ x = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96])


# ~ # Calculate rate of change
# ~ rate_of_change, mid_x = calculate_rate_of_change(x, y)

# ~ # Find largest peak in rate of change
# ~ largest_peak_index = find_largest_peak(rate_of_change)
# ~ largest_peak_x = mid_x[largest_peak_index]

# ~ # Plot raw data and rate of change
# ~ plt.figure(figsize=(10, 6))

# ~ # Top plot: Raw data
# ~ plt.subplot(2, 1, 1)
# ~ plt.plot(x, y, label="Raw Data", color="black")
# ~ plt.title("Raw Data")
# ~ plt.xlabel("X")
# ~ plt.ylabel("Y")

# ~ # Bottom plot: Rate of change
# ~ plt.subplot(2, 1, 2)
# ~ plt.plot(mid_x, rate_of_change, label="Rate of Change", color="blue")
# ~ plt.scatter(mid_x[largest_peak_index], rate_of_change[largest_peak_index],
            # ~ color='red', zorder=5, label="Largest Peak")
# ~ plt.axvline(mid_x[largest_peak_index], color='red', linestyle='--', label="Largest Change")
# ~ plt.title("Rate of Change with Largest Peak Highlighted")
# ~ plt.xlabel("X")
# ~ plt.ylabel("Rate of Change")
# ~ plt.legend()

# ~ plt.tight_layout()
# ~ plt.show()

# ~ print(f"Largest change occurs at x = {largest_peak_x:.2f}")
