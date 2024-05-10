import customtkinter as ctk
import numpy as np
from Machine import Machine
from Frames import CoordinateFrame, ConnectionFrame, PressurePlotFrame


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Keyboard Shortcuts")
        self.geometry("1200x1000")

        # Bind the function self.on_key_press to the key press event
        self.bind("<Key>", self.on_key_press)
        self.machine = Machine()
        
        self.coordinate_frame = CoordinateFrame(self,self.machine)
        self.coordinate_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.update_coordinates_interval = 100
        self.update_coordinates()

        self.connection_frame = ConnectionFrame(self, self.machine,self.coordinate_frame)
        self.connection_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.pressure_plot_frame = PressurePlotFrame(self, self.machine)  # Create the PressurePlotFrame
        self.pressure_plot_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")  # Add the PressurePlotFrame to the grid

    def on_key_press(self, event):
        # The keysym attribute contains the name of the special key that was pressed
        if event.keysym == "Up":
            self.machine.move_relative({'X': 0, 'Y': 10, 'Z': 0, 'P': 0})
        elif event.keysym == "Down":
            self.machine.move_relative({'X': 0, 'Y': -10, 'Z': 0, 'P': 0})
        elif event.keysym == "Left":
            self.machine.move_relative({'X': -10, 'Y': 0, 'Z': 0, 'P': 0})
        elif event.keysym == "Right":
            self.machine.move_relative({'X': 10, 'Y': 0, 'Z': 0, 'P': 0})
        elif event.char == "k":
            self.machine.move_relative({'X': 0, 'Y': 0, 'Z': 10, 'P': 0})
        elif event.char == "m":
            self.machine.move_relative({'X': 0, 'Y': 0, 'Z': -10, 'P': 0})
        elif event.char == "9":
            self.machine.set_relative_pressure(10)
        elif event.char == "8":
            self.machine.set_relative_pressure(2)
        elif event.char == "7":
            self.machine.set_relative_pressure(-2)
        elif event.char == "6":
            self.machine.set_relative_pressure(-10)
        
        elif event.keysym == "BackSpace":
            print("Backspace key pressed")
        elif event.keysym == "Escape":
            print("Escape key pressed")
        else:
            print("Key pressed:", event.char)
        self.update_coordinates()
    
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

if __name__ == "__main__":
    app = App()
    app.mainloop()