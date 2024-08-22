import numpy as np
from scipy import stats
import sys

class CalibrationModel:
    def __init__(self, target_volume=30.0):
        self.target_volume = target_volume  # Target droplet volume in nanoliters
        self.calibration_data = []  # Store tuples of (pressure, measured_volume)
        self.current_pressure = None

    def start_calibration(self, initial_pressure):
        """Start a new calibration process."""
        self.calibration_data.clear()
        self.current_pressure = initial_pressure
        print(f"Calibration started with initial pressure: {self.current_pressure} Pa")

    def calculate_droplet_volume(self, mass_mg, num_droplets=100):
        """Calculate droplet volume in nanoliters based on the mass difference in milligrams."""
        volume_nl = (mass_mg * 1000) / num_droplets  # Density assumed to be 1 mg/µL
        return volume_nl

    def update_calibration(self, measured_volume_nl):
        """Update calibration data with the new measured volume."""
        if self.current_pressure is not None:
            # self.calibration_data.append((self.current_pressure, measured_volume_nl))
            print(f"Added data point: Pressure={self.current_pressure} Pa, Measured Volume={measured_volume_nl} nL")
            print(f'Calibration data: {self.calibration_data}')
            # Calculate next pressure
            if len(self.calibration_data) <= 1:
                print("Need at least two data points for calibration.")
                # If only one data point, scale the pressure proportionally
                self.current_pressure *= self.target_volume / measured_volume_nl
            else:
                print("More than one data point available.")
                # If more than one data point, use linear regression to estimate the next pressure
                pressures, volumes = [x['pressure'] for x in self.calibration_data], [x['measured_volume'] for x in self.calibration_data]
                slope, intercept, _, _, _ = stats.linregress(volumes, pressures)
                self.current_pressure = slope * self.target_volume + intercept

            print(f"Next pressure to try: {self.current_pressure} Pa")

    def get_next_pressure(self):
        """Return the next pressure value to try."""
        return self.current_pressure
    
    def add_calibration_point(self, pressure, measured_volume_nl):
        """Add a calibration point to the model."""
        self.calibration_data.append({'pressure': pressure, 'measured_volume': measured_volume_nl})
        self.update_calibration(measured_volume_nl)

    def is_calibration_complete(self, tolerance=0.5):
        """Check if calibration is complete within a specified tolerance (in nL)."""
        if not self.calibration_data:
            return False

        _, last_measured_volume = self.calibration_data[-1]
        return abs(last_measured_volume - self.target_volume) <= tolerance

    def get_calibration_data(self):
        """Return the collected calibration data."""
        return self.calibration_data


from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFormLayout, QGridLayout
)
from PySide6.QtCore import QTimer, Signal, QObject
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class CalibrationDialog(QDialog):
    def __init__(self, calibration_model):
        super().__init__()
        self.calibration_model = calibration_model
        self.setWindowTitle("Printer Head Calibration")
        self.setFixedSize(1200, 600)

        # Create the layout
        layout = QHBoxLayout(self)

        # Real-time mass plot (left)
        self.mass_plot = PlotCanvas(self, title="Real-Time Mass", xlabel="Time (s)", ylabel="Mass (mg)")
        layout.addWidget(self.mass_plot)

        # Pressure vs. Volume plot (right)
        self.calibration_plot = PlotCanvas(self, title="Pressure vs. Volume", xlabel="Pressure (Pa)", ylabel="Volume (nL)")
        layout.addWidget(self.calibration_plot)

        # Control panel layout
        control_layout = QVBoxLayout()
        
        # Current pressure display
        self.current_pressure_label = QLabel("Current Pressure:")
        self.current_pressure_value = QLabel("N/A")
        control_layout.addWidget(self.current_pressure_label)
        control_layout.addWidget(self.current_pressure_value)
        
        # Target volume display
        self.target_volume_label = QLabel("Target Volume (nL):")
        self.target_volume_value = QLineEdit()
        self.target_volume_value.setText(str(self.calibration_model.target_volume))
        control_layout.addWidget(self.target_volume_label)
        control_layout.addWidget(self.target_volume_value)

        # Measured volume display
        self.measured_volume_label = QLabel("Measured Volume (nL):")
        self.measured_volume_value = QLabel("N/A")
        control_layout.addWidget(self.measured_volume_label)
        control_layout.addWidget(self.measured_volume_value)

        # Start and Stop buttons
        self.start_button = QPushButton("Start Calibration")
        self.start_button.clicked.connect(self.start_calibration)
        control_layout.addWidget(self.start_button)
        
        self.take_measurement_button = QPushButton("Take Another Measurement")
        self.take_measurement_button.clicked.connect(self.take_another_measurement)
        control_layout.addWidget(self.take_measurement_button)
        
        self.stop_button = QPushButton("Stop Calibration")
        self.stop_button.clicked.connect(self.stop_calibration)
        control_layout.addWidget(self.stop_button)

        layout.addLayout(control_layout)

        # Timer to simulate real-time mass readings (replace with actual microbalance reading logic)
        self.timer = QTimer()
        self.timer.timeout.connect(self.simulate_mass_reading)
        self.mass_data = []

    def start_calibration(self):
        """Start the calibration process."""
        self.mass_data = []
        self.mass_plot.clear()
        self.calibration_plot.clear()
        initial_pressure = float(2)
        self.calibration_model.start_calibration(initial_pressure)
        self.current_pressure_value.setText(str(initial_pressure))
        self.timer.start(100)  # Simulate mass readings every 100ms

    def take_another_measurement(self):
        """Take another measurement and update the calibration."""
        if self.mass_data:
            measured_mass = self.mass_data[-1]  # Last recorded mass
            measured_volume = self.calibration_model.calculate_droplet_volume(measured_mass)
            self.calibration_model.add_calibration_point(self.calibration_model.current_pressure, measured_volume)
            self.update_calibration_plot()
            self.measured_volume_value.setText(f"{measured_volume:.2f}")
            next_pressure = self.calibration_model.get_next_pressure()
            self.current_pressure_value.setText(f"{next_pressure:.2f}")
        self.mass_data = []
        self.mass_plot.clear()
        self.timer.start(100)

    def stop_calibration(self):
        """Stop the calibration process."""
        self.timer.stop()

    def simulate_mass_reading(self):
        """Simulate real-time mass reading (replace with actual microbalance logic)."""
        if not self.mass_data:
            self.mass_data.append(0)
        else:
            target_mass = self.simulate_mass(100, self.calibration_model.current_pressure)
            # Simulate mass stabilizing after a few seconds
            if self.mass_data[-1] < target_mass:
                self.mass_data.append(self.mass_data[-1] + np.random.normal(0.1, 0.02))
            else:
                self.mass_data.append(self.mass_data[-1] + np.random.normal(0.002, 0.005))
        
        self.mass_plot.update_plot(self.mass_data)

    def simulate_mass(self,num_droplets,psi):
        # Reference points
        ref_droplets = 100
        ref_points = np.array([
            [1.8, 3],
            [2.2, 4],
        ])

        # Calculate the linear fit for the reference points
        coefficients = np.polyfit(ref_points[:, 0], ref_points[:, 1] / ref_droplets, 1)
        print('Coefficients:',coefficients)
        # Calculate the mass per droplet for the given pressure
        mass_per_droplet = coefficients[0] * psi + coefficients[1]
        for point in ref_points:
            print('Point:',point[0],point[1],coefficients[0] * point[0] + coefficients[1])
        # Calculate the mass for the given number of droplets
        mass = mass_per_droplet * num_droplets

        return mass

    def update_calibration_plot(self):
        """Update the pressure vs. volume plot with new calibration data."""
        calibration_data = self.calibration_model.get_calibration_data()
        pressures = [d['pressure'] for d in calibration_data]
        volumes = [d['measured_volume'] for d in calibration_data]
        self.calibration_plot.update_scatter_plot(pressures, volumes)


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100, title="", xlabel="", ylabel=""):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        self.axes.set_title(title)
        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        super().__init__(fig)
        self.setParent(parent)

    def update_plot(self, data):
        """Update plot with new data."""
        self.axes.cla()
        self.axes.plot(data, 'b-')
        self.axes.figure.canvas.draw()

    def update_scatter_plot(self, x_data, y_data):
        """Update scatter plot with new data points."""
        self.axes.cla()
        self.axes.scatter(x_data, y_data, c='r')
        self.axes.figure.canvas.draw()

    def clear(self):
        """Clear the plot."""
        self.axes.cla()
        self.axes.figure.canvas.draw()

if __name__ == "__main__":
    # Example usage
    app = QApplication(sys.argv)

    # Assuming the CalibrationModel is already implemented as discussed
    calibration_model = CalibrationModel(target_volume=30)  # Initialize with a target volume of 30 nL
    dialog = CalibrationDialog(calibration_model)
    dialog.show()

    sys.exit(app.exec())
