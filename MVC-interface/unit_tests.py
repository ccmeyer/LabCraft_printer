import unittest
import numpy as np
from PySide6.QtCore import QCoreApplication
from Model import MachineModel  # Replace with your actual filename

class TestMachineModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Initialize the Qt application once for all tests
        cls.app = QCoreApplication([])

    def setUp(self):
        # Initialize MachineModel for each test
        self.model = MachineModel()

    def test_convert_to_psi(self):
        # Test conversion from raw pressure to PSI
        raw_pressure = 1638  # Example raw pressure value
        expected_psi = 0.0  # Expected PSI value at psi_offset
        self.assertEqual(self.model.convert_to_psi(raw_pressure), expected_psi)

    def test_convert_to_raw_pressure(self):
        # Test conversion from PSI to raw pressure
        psi_value = 15.0  # Max PSI value
        expected_raw_pressure = self.model.fss + self.model.psi_offset  # Expected raw pressure at max psi
        self.assertEqual(self.model.convert_to_raw_pressure(psi_value), expected_raw_pressure)

    def test_set_step_size(self):
        # Connect to the signal and set up a flag
        self.signal_emitted = False
        # Set initial step size to a value different from 500
        self.model.set_step_size(250)

        def signal_handler(new_step_size):
            self.signal_emitted = True
            self.assertEqual(new_step_size, 500)

        self.model.step_size_changed.connect(signal_handler)

        # Change step size to a valid new size
        self.model.set_step_size(500)
        self.assertTrue(self.signal_emitted)
        self.assertEqual(self.model.step_size, 500)
        self.assertEqual(self.model.step_num, self.model.possible_steps.index(500))

    def test_increase_step_size(self):
        # Increase step size
        initial_step_size = self.model.step_size
        self.model.increase_step_size()
        self.assertGreater(self.model.step_size, initial_step_size)
        self.assertEqual(self.model.step_size, self.model.possible_steps[self.model.step_num])

    def test_decrease_step_size(self):
        # Decrease step size
        self.model.set_step_size(500)
        initial_step_size = self.model.step_size
        self.model.decrease_step_size()
        self.assertLess(self.model.step_size, initial_step_size)
        self.assertEqual(self.model.step_size, self.model.possible_steps[self.model.step_num])

    def test_toggle_motor_state(self):
        # Connect to the signal and set up a flag
        self.signal_emitted = False
        def signal_handler(motors_enabled):
            self.signal_emitted = True
            self.assertTrue(motors_enabled)
        
        self.model.motor_state_changed.connect(signal_handler)
        
        # Toggle motor state
        self.model.toggle_motor_state()
        self.assertTrue(self.signal_emitted)
        self.assertTrue(self.model.motors_enabled)

    def test_toggle_regulation_state(self):
        # Connect to the signal and set up a flag
        self.signal_emitted = False
        def signal_handler(regulating_pressure):
            self.signal_emitted = True
            self.assertTrue(regulating_pressure)
        
        self.model.regulation_state_changed.connect(signal_handler)
        
        # Toggle regulation state
        self.model.toggle_regulation_state()
        self.assertTrue(self.signal_emitted)
        self.assertTrue(self.model.regulating_pressure)

    def test_update_pressure(self):
        # Connect to the signal and set up a flag
        self.signal_emitted = False
        def signal_handler(pressure_readings):
            self.signal_emitted = True
            self.assertEqual(round(pressure_readings[-1],2), 42.0)
        
        self.model.pressure_updated.connect(signal_handler)

        # Update pressure readings
        raw_pressure = self.model.convert_to_raw_pressure(42.0)
        self.model.update_pressure(raw_pressure)
        self.assertTrue(self.signal_emitted)
        self.assertEqual(round(self.model.pressure_readings[-1],2), 42.0)

if __name__ == '__main__':
    unittest.main()