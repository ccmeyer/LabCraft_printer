from typing import Any, Tuple
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class CoordinateFrame(ctk.CTkFrame):
    def __init__(self, master: Any, machine, width: int = 500, height: int = 400,  **kwargs):
        super().__init__(master, width, height, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=3)

        self.machine = machine
        self.current_row = 0
        self.title_label = ctk.CTkLabel(self, text="MOTORS", fg_color="gray30", corner_radius=6,font=("Arial", 14))
        self.title_label.grid(row=self.current_row, column=0, columnspan=3, padx=0, pady=10)
        self.current_row += 1

        self.coords_label = ctk.CTkLabel(self, text="Current", fg_color="gray30", corner_radius=6)
        self.coords_label.grid(row=self.current_row, column=1, padx=10, pady=(0, 10), sticky="ew")

        self.target_coords_label = ctk.CTkLabel(self, text="Target", fg_color="gray30", corner_radius=6)
        self.target_coords_label.grid(row=self.current_row, column=2, padx=10, pady=(0, 10), sticky="ew")
        self.current_row += 1

        labels = ["X", "Y", "Z", "P"]
        self.entries = {}
        self.target_entries = {}

        for i, text in enumerate(labels):
            label = ctk.CTkLabel(self, text=text, fg_color="gray30", corner_radius=6)
            label.grid(row=self.current_row, column=0, padx=10, pady=(0, 10), sticky="ew")

            entry = ctk.CTkEntry(self, width=10, justify='right')
            entry.grid(row=self.current_row, column=1, padx=10, pady=(0, 10), sticky="ew")

            target_entry = ctk.CTkEntry(self, width=10, justify='right')
            target_entry.grid(row=self.current_row, column=2, padx=10, pady=(0, 10), sticky="ew")

            self.entries[text] = entry
            self.target_entries[text] = target_entry
            self.current_row += 1
        
        self.check_var = ctk.StringVar(value="off")
        self.activate_button = ctk.CTkCheckBox(self, text="Activate", command=self.toggle_motors, variable=self.check_var, onvalue="on", offvalue="off")
        self.activate_button.grid(row=self.current_row, column=0, columnspan=3, padx=10, pady=10)
        self.activate_button.configure(state='disabled' if not self.machine.is_connected() else 'normal')
        self.current_row += 1
    

    def toggle_motors(self):
        if self.check_var.get() == 'on':
            self.machine.activate_motors()
        else:
            self.machine.deactivate_motors()

        for entry in self.entries.values():
            if self.check_var.get() == 'on':
                entry.configure(state='normal', fg_color='black')
            else:
                entry.configure(state='disabled', fg_color='gray30')
    def set_coordinates(self, coordinates,target_coordinates):
        for key in coordinates:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, str(coordinates[key]))
            self.target_entries[key].delete(0, "end")
            self.target_entries[key].insert(0, str(target_coordinates[key]))

class ConnectionFrame(ctk.CTkFrame):
    def __init__(self, master: Any, machine,coordinate_frame, width: int = 500, height: int = 400,  **kwargs):
        super().__init__(master, width, height, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)

        self.machine = machine
        self.coordinate_frame = coordinate_frame
        self.current_row = 0
        self.title_label = ctk.CTkLabel(self, text="CONNECTION", fg_color="gray30", corner_radius=6,font=("Arial", 14))
        self.title_label.grid(row=0, column=0, columnspan=3, padx=0, pady=10)
        self.current_row += 1

        com_ports = self.machine.get_com_ports()
        com_width=80
        button_width=10
        self.machine_label = ctk.CTkLabel(self, text='Machine port', fg_color="gray30", corner_radius=6)
        self.machine_label.grid(row=self.current_row, column=0, padx=10, pady=(0, 10), sticky="ew")

        machine_optionmenu_var = ctk.StringVar(value="Not set")
        self.machine_options = ctk.CTkOptionMenu(self, command=self.machine.set_machine_port, variable=machine_optionmenu_var,width=com_width)
        self.machine_options.grid(row=self.current_row, column=1, padx=10, pady=(0, 10), sticky="ew")
        self.machine_options.configure(values=com_ports)
        
        self.machine_action_button = ctk.CTkButton(self, text="Connect", command=self.connect_machine,width=button_width)
        self.machine_action_button.grid(row=self.current_row, column=2, padx=10, pady=(0, 10), sticky="ew")
        self.current_row += 1

        balance_optionmenu_var = ctk.StringVar(value="Not set")
        self.balance_label = ctk.CTkLabel(self, text='Balance port', fg_color="gray30", corner_radius=6)
        self.balance_label.grid(row=self.current_row, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.balance_options = ctk.CTkOptionMenu(self, command=self.machine.set_balance_port, variable=balance_optionmenu_var,width=com_width)
        self.balance_options.grid(row=self.current_row, column=1, padx=10, pady=(0, 10), sticky="ew")
        self.balance_options.configure(values=com_ports)

        self.balance_action_button = ctk.CTkButton(self, text="Connect", command=self.machine.connect_balance,width=button_width)
        self.balance_action_button.grid(row=self.current_row, column=2, padx=10, pady=(0, 10), sticky="ew")
        self.current_row += 1

        self.refresh_button = ctk.CTkButton(self, text="Refresh COM ports", command=self.refresh_com_ports,width=button_width)
        self.refresh_button.grid(row=self.current_row, column=0, columnspan=1, padx=10, pady=(0, 10), sticky="ew")

    def connect_machine(self):
        self.machine.connect_machine()
        
        if self.machine.is_connected():
            self.coordinate_frame.activate_button.configure(state='normal')
            self.machine_options.configure(state='disabled')
            self.machine_action_button.configure(state='disabled')
    
    def refresh_com_ports(self):
        com_ports = self.machine.refresh_com_ports()
        self.machine_options.configure(values=com_ports)
        self.balance_options.configure(values=com_ports)
        print('COM ports refreshed')


class PressurePlotFrame(ctk.CTkFrame):
    def __init__(self, master=None, machine=None, update_interval=1000):
        super().__init__(master)
        self.master = master
        self.machine = machine
        self.update_interval = update_interval

        self.fig, self.ax = plt.subplots(figsize=(5, 3))
        self.graph = FigureCanvasTkAgg(self.fig, master=self)
        self.graph.get_tk_widget().pack()

        self.update_plot()

    def update_plot(self):
        self.ax.clear()
        self.ax.plot(self.machine.pressure_log)
        self.ax.set_title('')
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Pressure')
        self.graph.draw()

        self.after(self.update_interval, self.update_plot)