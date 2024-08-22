import numpy as np
from scipy import stats
import sys
import re
import serial

class Balance():
    def __init__(self,machine):
        self.machine = machine
        self.connected = False
        self.port = None
        self.simulate = True
        self.error_count = 0
        self.current_mass = 0
        self.target_mass = 0
        self.mass_update_timer = None
        self.mass_log = []

    def is_connected(self):
        return self.connected

    def connect_balance(self,port):
        if port == 'Virtual':
            self.connected = True
            self.simulate = True
            self.mass_update_timer = QTimer()
            self.mass_update_timer.timeout.connect(self.update_simulated_mass)
            self.mass_update_timer.start(25)
            self.show_connection()
            self.begin_reading()
            return True
        try:
            self.port = serial.Serial(port, baudrate=9600, bytesize=8, timeout=2, stopbits=serial.STOPBITS_ONE)
            if not self.port.is_open:  # Add this line
                raise serial.SerialException('Could not open port')  # Add this line
            self.connected = True
            self.simulate = False
            self.show_connection()
            self.begin_reading()
            return True
        except:
            self.main_window.popup_message('Connection error',f'Could not connect to balance at port {port}')
            self.connected = False
            return False
        
    def close_connection(self):
        if not self.simulate:
            self.port.close()
        else:
            self.mass_update_timer.stop()
        if self.mass_update_timer is not None:
            self.mass_update_timer.stop()
        self.connected = False
        return

    def show_connection(self):
        print('Balance connected')

    def get_mass(self):
        if not self.simulate:
            if self.port.in_waiting > 0:
                data = self.port.readline()
                try:
                    data = data.decode("ASCII")
                    # print('Data:',data)
                    [sign,mass] = re.findall(r'(-?) *([0-9]+\.[0-9]+) [a-zA-Z]*',data)[0]
                    mass = float(''.join([sign,mass]))
                    self.current_mass = mass
                    self.add_to_log(self.current_mass)
                except Exception as e:
                    print(f'--Error {e} reading from balance')
                    self.error_count += 1
                    if self.error_count > 100:
                        self.close_connection()
                        self.main_window.popup_message('Connection error','Lost connection to balance')
                    
        else:
            self.add_to_log(self.current_mass)
        
    def begin_reading(self):
        self.mass_update_timer = QTimer()
        self.mass_update_timer.timeout.connect(self.get_mass)
        self.mass_update_timer.start(10)

    def add_to_log(self,mass):
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)

    def get_recent_mass(self):
        if self.mass_log != []:
            return self.mass_log[-1]
        else:
            return 0

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
    
    def update_simulated_mass(self):
        if self.machine.balance_droplets != []:
            print('Balance droplets:',self.machine.balance_droplets)
            [num_droplets,psi] = self.machine.balance_droplets.pop(0)
            print('Found balance droplets',num_droplets,psi)
            mass = self.simulate_mass(num_droplets,psi)
            print('Simulated mass:',mass,self.current_mass,self.target_mass)
            self.target_mass += mass
        
        if self.current_mass < self.target_mass:
            self.current_mass += 0.01

class CalibrationModel:
    def __init__(self, target_volume=30.0):
        self.target_volume = target_volume  # Target droplet volume in nanoliters
        self.calibration_data = []  # Store tuples of (pressure, measured_volume)
        self.current_pressure = None
        self.simulating = True

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
            # self.calibration_model.add_calibration_point(self.calibration_model.current_pressure, measured_volume)
            self.measured_volume_value.setText(f"{measured_volume:.2f}")
            next_pressure = self.calibration_model.get_next_pressure()
            self.current_pressure_value.setText(f"{next_pressure:.2f}")
        self.mass_data = []
        self.mass_plot.clear()
        self.timer.start(100)

    def stop_calibration(self):
        """Stop the calibration process."""
        self.timer.stop()
        if self.mass_data:
            measured_mass = self.mass_data[-1]  # Last recorded mass
            measured_volume = self.calibration_model.calculate_droplet_volume(measured_mass)
            self.calibration_model.add_calibration_point(self.calibration_model.current_pressure, measured_volume)
            self.update_calibration_plot()
            self.measured_volume_value.setText(f"{measured_volume:.2f}")
            next_pressure = self.calibration_model.get_next_pressure()
            self.current_pressure_value.setText(f"{next_pressure:.2f}")

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

    def simulate_mass(self, num_droplets, psi):
        # Reference points
        ref_droplets = 100
        ref_points = np.array([
            [1.8, 3],
            [2.2, 4],
        ])

        # Calculate the linear fit for the reference points
        coefficients = np.polyfit(ref_points[:, 0], ref_points[:, 1] / ref_droplets, 1)
        # print('Coefficients:', coefficients)
        # Calculate the mass per droplet for the given pressure
        mass_per_droplet = coefficients[0] * psi + coefficients[1]
        # for point in ref_points:
        #     print('Point:', point[0], point[1], coefficients[0] * point[0] + coefficients[1])
        # Calculate the mass for the given number of droplets
        mass = mass_per_droplet * num_droplets

        return mass

    def update_calibration_plot(self):
        """Update the pressure vs. volume plot with new calibration data."""
        calibration_data = self.calibration_model.get_calibration_data()
        pressures = [d['pressure'] for d in calibration_data]
        volumes = [d['measured_volume'] for d in calibration_data]

        # Plot scatter data
        self.calibration_plot.update_scatter_plot(pressures, volumes)

        # Plot linear fit line
        if len(calibration_data) > 1:
            slope, intercept, _, _, _ = stats.linregress(pressures, volumes)
            fit_line = [slope * p + intercept for p in pressures]
            self.calibration_plot.update_fit_line(pressures, fit_line)


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100, title="", xlabel="", ylabel=""):
        fig = Figure(figsize=(width, height), dpi=dpi, facecolor='black')
        self.axes = fig.add_subplot(111, facecolor='black')
        self.axes.set_title(title, color='white')
        self.axes.set_xlabel(xlabel, color='white')
        self.axes.set_ylabel(ylabel, color='white')
        self.axes.tick_params(axis='x', colors='white')
        self.axes.tick_params(axis='y', colors='white')
        super().__init__(fig)
        self.setParent(parent)

    def update_plot(self, data):
        """Update plot with new data."""
        self.axes.cla()
        self.axes.plot(data, 'cyan')
        self.axes.figure.canvas.draw()

    def update_scatter_plot(self, x_data, y_data):
        """Update scatter plot with new data points."""
        self.axes.cla()
        self.axes.scatter(x_data, y_data, c='red')
        self.axes.figure.canvas.draw()

    def update_fit_line(self, x_data, y_data):
        """Update plot with a linear fit line."""
        self.axes.plot(x_data, y_data, 'r--')
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
