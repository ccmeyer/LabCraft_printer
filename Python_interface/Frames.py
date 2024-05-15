from typing import Any, Tuple
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class CoordinateFrame(ctk.CTkFrame):
    def __init__(self, master: Any, app,machine, width: int = 500, height: int = 400,  **kwargs):
        super().__init__(master, width, height, **kwargs)
        self.app = app
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
        self.app.get_coordinates()
        self.check_var = ctk.StringVar(value="off")
        self.activate_button = ctk.CTkSwitch(self, text="Activate", command=self.toggle_motors, variable=self.check_var, onvalue="on", offvalue="off")
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
        self.app.toggle_motor_state()
    
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
    def __init__(self, master=None, machine=None, update_interval=100):
        super().__init__(master)
        self.master = master
        self.machine = machine
        self.update_interval = update_interval

        self.fig, self.ax = plt.subplots(figsize=(4, 2), facecolor='black')
        self.ax.set_facecolor('black')
        self.graph = FigureCanvasTkAgg(self.fig, master=self)
        self.graph.get_tk_widget().pack()

        self.target_pressure_label = ctk.CTkLabel(self, text="Target Pressure:")
        self.target_pressure_label.pack()

        self.target_pressure_entry = ctk.CTkEntry(self)
        self.target_pressure_entry.pack()
        self.target_pressure_entry.insert(0, str(self.machine.target_pressure))

        self.check_var_pressure = ctk.StringVar(value="off")
        self.activate_button_pressure = ctk.CTkSwitch(self, text="Regulate Pressure", command=self.toggle_pressure, variable=self.check_var_pressure, onvalue="on", offvalue="off")
        self.activate_button_pressure.pack()
        self.activate_button_pressure.configure(state='disabled' if not self.machine.is_connected() else 'normal')
        
        self.update_plot()

    def toggle_pressure(self):
        if self.check_var_pressure.get() == 'on':
            self.machine.start_pressure_regulation()
        else:
            self.machine.stop_pressure_regulation()

        
    def update_plot(self):
        self.ax.clear()
        self.ax.plot(self.machine.pressure_log)
        self.ax.axhline(self.machine.target_pressure, color='r', linestyle='--')
        self.ax.set_title('')
        self.ax.set_xlabel('')
        self.ax.set_ylabel('Pressure (psi)',color='white')
        self.ax.tick_params(colors='white')
        self.graph.draw()

        self.target_pressure_entry.delete(0, "end")
        self.target_pressure_entry.insert(0, str(self.machine.target_pressure))

        self.after(self.update_interval, self.update_plot)

class ScrollableCommandFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, machine, app, command=None,width: int = 500, height: int = 800, **kwargs):
        self.app = app
        window_height = app.winfo_height()
        window_width = app.winfo_width()
        super().__init__(master, width=window_width,height=window_height, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=5)
        self.title_label = ctk.CTkLabel(self, text="COMMAND LOG", fg_color="gray30", corner_radius=6,font=("Arial", 14))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=0, pady=10)

        self.num_list = []
        self.command_list = []

    def add_command(self, command_number, command):
        number_label = ctk.CTkLabel(self, text=command_number, compound="left", padx=5, anchor="w")
        command_label = ctk.CTkLabel(self, text=command, compound="left", padx=5, anchor="w")

        self.num_list.insert(0, number_label)
        self.command_list.insert(0, command_label)

        for i, (number_label, command_label) in enumerate(zip(self.num_list, self.command_list)):
            number_label.grid(row=i+1, column=0, pady=(0, 10), sticky="w")
            command_label.grid(row=i+1, column=1, pady=(0, 10), padx=5)

class ScrollableShortcutsFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, app, width: int = 500, height: int = 800, **kwargs):
        self.app = app
        window_height = app.winfo_height()
        window_width = app.winfo_width()
        super().__init__(master, width=window_width,height=window_height, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=5)

        self.title_label = ctk.CTkLabel(self, text="SHORTCUTS", fg_color="gray30", corner_radius=6,font=("Arial", 14))
        self.title_label.grid(row=0, column=0, columnspan=2, padx=0, pady=10)
        self.key_list = []
        self.name_list = []
        for shortcut in app.shortcuts:
            self.add_shortcut(shortcut)

    def add_shortcut(self, shortcut):
        key_label = ctk.CTkLabel(self, text=shortcut.key, compound="left", padx=5, anchor="w")
        name_label = ctk.CTkLabel(self, text=shortcut.name, compound="left", padx=5, anchor="w")
        key_label.grid(row=len(self.key_list)+1, column=0, pady=(0, 10), sticky="w")
        name_label.grid(row=len(self.key_list)+1, column=1, pady=(0, 10), sticky="w")

        self.key_list.append(key_label)
        self.name_list.append(name_label)


class CartridgeSlotsFrame(ctk.CTkFrame):
    def __init__(self, master, slots, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.slots = slots
        self.slot_labels = []

        for slot in self.slots:
            slot_label = ctk.CTkLabel(self, text=f"Slot {slot.slot_number}: {slot.cartridge_loaded or 'Empty'}", compound="left", padx=5, anchor="w")
            slot_label.grid(row=0, column=slot.slot_number, pady=(0, 10), padx=5)
            self.slot_labels.append(slot_label)

    def update_slots(self):
        for slot, slot_label in zip(self.slots, self.slot_labels):
            slot_label.config(text=f"Slot {slot.slot_number}: {slot.cartridge_loaded or 'Empty'}")
