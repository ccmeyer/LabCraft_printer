import customtkinter as ctk
import numpy as np
from Machine import Machine
from Frames import *

class Shortcut:
    def __init__(self, name, key, function):
        self.name = name
        self.key = key
        self.function = function

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Keyboard Shortcuts")
        self.geometry("1200x750+10+10") # Set the window size and position WxH+X+Y

        # Bind the function self.on_key_press to the key press event
        self.bind("<Key>", self.on_key_press)
        self.machine = Machine(self)
        self.shortcuts = [
            Shortcut("Move Up", "Up", lambda: self.machine.move_relative({'X': 0, 'Y': 10, 'Z': 0, 'P': 0})),
            Shortcut("Move Down", "Down", lambda: self.machine.move_relative({'X': 0, 'Y': -10, 'Z': 0, 'P': 0})),
            Shortcut("Move Left", "Left", lambda: self.machine.move_relative({'X': -10, 'Y': 0, 'Z': 0, 'P': 0})),
            Shortcut("Move Right", "Right", lambda: self.machine.move_relative({'X': 10, 'Y': 0, 'Z': 0, 'P': 0})),
            Shortcut("Move Up", "k", lambda: self.machine.move_relative({'X': 0, 'Y': 0, 'Z': 10, 'P': 0})),
            Shortcut("Move Down", "m", lambda: self.machine.move_relative({'X': 0, 'Y': 0, 'Z': -10, 'P': 0})),
            Shortcut("Large Increase Pressure", "9", lambda: self.machine.set_relative_pressure(10)),
            Shortcut("Small Increase Pressure", "8", lambda: self.machine.set_relative_pressure(2)),
            Shortcut("Small Decrease Pressure", "7", lambda: self.machine.set_relative_pressure(-2)),
            Shortcut("Large Decrease Pressure", "6", lambda: self.machine.set_relative_pressure(-10)),
        ]
        
        self.coordinate_frame = CoordinateFrame(self,self,self.machine)
        self.coordinate_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.update_coordinates_interval = 100
        self.update_coordinates()

        self.connection_frame = ConnectionFrame(self, self.machine,self.coordinate_frame)
        self.connection_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.pressure_plot_frame = PressurePlotFrame(self, self.machine)  # Create the PressurePlotFrame
        self.pressure_plot_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")  # Add the PressurePlotFrame to the grid

        self.command_log_frame = ScrollableCommandFrame(self, self.machine,self)  # Create the ScollableFrame
        self.command_log_frame.grid(row=0, column=1, padx=10, pady=10, sticky="ew")  # Add the ScollableFrame to the grid

        self.shortcut_frame = ScrollableShortcutsFrame(self,self)  # Create the ScollableFrame
        self.shortcut_frame.grid(row=1, column=1, padx=10, pady=10, sticky="ew")  # Add the ScollableFrame to the grid

        self.cartridge_slots_frame = CartridgeSlotsFrame(self, self.machine.slots)
        self.cartridge_slots_frame.grid(row=2, column=1,columnspan=3, padx=10, pady=10, sticky="ew")



    def on_key_press(self, event):
        # The keysym attribute contains the name of the special key that was pressed
        for shortcut in self.shortcuts:
            if event.keysym == shortcut.key or event.char == shortcut.key:
                shortcut.function()
                break
        self.update_coordinates()
    
    def toggle_motor_state(self):
        if self.coordinate_frame.check_var.get() == 'on':
            self.pressure_plot_frame.activate_button_pressure.configure(state='normal')
        else:
            self.pressure_plot_frame.activate_button_pressure.setvar('off')
            self.pressure_plot_frame.activate_button_pressure.configure(state='disabled')
            self.machine.regulating_pressure = False
            self.pressure_plot_frame.check_var_pressure.set('off')
    
    def get_coordinates(self):
        return self.machine.get_coordinates()

    def update_coordinates(self):
        current_coordinates = self.get_coordinates()
        target_coordinates = self.machine.get_target_coordinates()
        self.coordinate_frame.set_coordinates(current_coordinates, target_coordinates)
        
        self.after(self.update_coordinates_interval, self.update_coordinates)

    def update_target_coordinates(self):
        target_coordinates = {}
        for key in self.coordinate_frame.entries:
            target_coordinates[key] = float(self.coordinate_frame.entries[key].get())
        self.machine.set_target_coordinates(target_coordinates)

    def add_command_to_log(self, command_number, command):
        self.command_log_frame.add_command(command_number, command)

    def load_cartridge(self, slot_number):
        self.machine.load_cartridge(slot_number)
        self.cartridge_slots_frame.update_cartridge(slot_number)

if __name__ == "__main__":
    app = App()
    app.mainloop()