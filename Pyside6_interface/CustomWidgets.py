from PySide6 import QtCore, QtWidgets, QtGui

from PySide6 import QtCharts
from PySide6.QtCore import QTimer, QPointF
import numpy as np
from Machine import Machine,Command


# class Plate():
#     def __init__(self, name, rows=16, columns=24):
#         self.name = name
#         self.rows = rows
#         self.columns = columns

# class PlateBox(QtWidgets.QGroupBox):
#     def __init__(self, title, plate):
#         super().__init__(title)
#         self.plate = plate
#         self.layout = QtWidgets.QGridLayout(self)
#         self.rows = plate.rows
#         self.columns = plate.columns
#         self.cells = []
#         for row in range(self.rows):
#             for column in range(self.columns):
#                 cell = QtWidgets.QPushButton(f"{row+1}, {column+1}")
#                 cell.setFocusPolicy(QtCore.Qt.NoFocus)
#                 self.layout.addWidget(cell, row, column)
#                 self.cells.append(cell)


class CustomWidget(QtWidgets.QWidget):
    def __init__(self,main_window):
        super().__init__()
        self.main_window = main_window
        self.label = QtWidgets.QLabel("I'm a custom widget!")

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.label)

        self.reagent_input_button = QtWidgets.QPushButton("Open Reagent Input")
        self.reagent_input_button.setStyleSheet(f"background-color: {self.main_window.colors['dark_gray']}")
        self.reagent_input_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.reagent_input_button.clicked.connect(self.open_reagent_input)
        self.layout.addWidget(self.reagent_input_button)
    
    def open_reagent_input(self):
        self.reagent_input_window = ReagentInputWindow(self.main_window)
        self.reagent_input_window.show()

class ReagentInputWindow(QtWidgets.QDialog):
    def __init__(self,main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowTitle("Reagent Input")
        self.resize(800, 600)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.reagent_table = QtWidgets.QTableWidget(0, 4)  # 0 rows, 4 columns
        self.reagent_table.setHorizontalHeaderLabels(["Reagent Name", "Min Concentration", "Max Concentration", "Number of Concentrations"])
        self.layout.addWidget(self.reagent_table)
        # Set the width of the columns
        for i in range(self.reagent_table.columnCount()):
            self.reagent_table.setColumnWidth(i, 150)

        add_reagent_button = QtWidgets.QPushButton("Add Row")
        add_reagent_button.clicked.connect(self.add_reagent_row)
        self.layout.addWidget(add_reagent_button)

        add_new_reagent_button = QtWidgets.QPushButton("Add New Reagent")
        add_new_reagent_button.clicked.connect(self.add_new_reagent)
        self.layout.addWidget(add_new_reagent_button)

        submit_button = QtWidgets.QPushButton("Submit")
        submit_button.clicked.connect(self.submit)
        self.layout.addWidget(submit_button)
        self.add_reagent_row()

    def add_new_reagent(self):
        self.new_reagent_window = QtWidgets.QDialog()
        self.new_reagent_window.setWindowTitle("Add new reagent")

        window_layout = QtWidgets.QVBoxLayout(self.new_reagent_window)

        self.name_input = QtWidgets.QLineEdit()
        self.color_input = QtWidgets.QComboBox()
        self.color_input.addItems(list(self.main_window.colors.keys()))
        
        window_layout.addWidget(QtWidgets.QLabel("Name:"))
        window_layout.addWidget(self.name_input)
        window_layout.addWidget(QtWidgets.QLabel("Color:"))
        window_layout.addWidget(self.color_input)

        add_button = QtWidgets.QPushButton("Add Reagent")
        add_button.clicked.connect(self.add_reagent_to_main)
        window_layout.addWidget(add_button)

        self.new_reagent_window.exec()
    
    def add_reagent_to_main(self):
        name = self.name_input.text()
        color = self.color_input.currentText()

        new_reagent = Reagent(name, color)
        self.main_window.reagents.append(new_reagent)

        # Update the items in the combo boxes
        for row in range(self.reagent_table.rowCount()):
            self.reagent_table.cellWidget(row, 0).clear()
            self.reagent_table.cellWidget(row, 0).addItems(self.main_window.get_reagent_names())

        self.new_reagent_window.close()

    def add_reagent_row(self):
        row = self.reagent_table.rowCount()
        self.reagent_table.insertRow(row)

        reagent_name_input = QtWidgets.QComboBox()
        names = self.main_window.get_reagent_names()
        reagent_name_input.addItems(names)
        reagent_name_input.setEditable(False)  # The user must select one of the provided options

        min_concentration_input = QtWidgets.QDoubleSpinBox()
        min_concentration_input.setRange(0, 100)  # Set a minimum and maximum value
        min_concentration_input.setDecimals(2)  # Set the number of decimal places
        
        max_concentration_input = QtWidgets.QDoubleSpinBox()
        max_concentration_input.setRange(0, 100)  # Set a minimum and maximum value
        max_concentration_input.setDecimals(2)  # Set the number of decimal places
        
        num_concentrations_input = QtWidgets.QSpinBox()
        num_concentrations_input.setRange(1, 100)  # Set a minimum and maximum value
        
        self.reagent_table.setCellWidget(row, 0, reagent_name_input)
        self.reagent_table.setCellWidget(row, 1, min_concentration_input)
        self.reagent_table.setCellWidget(row, 2, max_concentration_input)
        self.reagent_table.setCellWidget(row, 3, num_concentrations_input)

    def submit(self):
        for row in range(self.reagent_table.rowCount()):
            reagent_name = self.reagent_table.cellWidget(row, 0).currentText()
            min_concentration = self.reagent_table.cellWidget(row, 1).value()
            max_concentration = self.reagent_table.cellWidget(row, 2).value()
            num_concentrations = self.reagent_table.cellWidget(row, 3).value()
            print(f"Reagent: {reagent_name}, Min: {min_concentration}, Max: {max_concentration}, Num: {num_concentrations}")       

class CoordinateBox(QtWidgets.QGroupBox):
    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)
        self.value_labels = []

        labels = ["X", "Y", "Z", "P"]
        self.entries = {}
        self.target_entries = {}

        for i, axis in enumerate(labels):
            label = QtWidgets.QLabel(axis)
            self.layout.addWidget(label, i, 0)

            entry = QtWidgets.QLabel()
            # entry.setFocusPolicy(QtCore.Qt.StrongFocus)
            self.layout.addWidget(entry, i, 1)
            self.entries[axis] = entry

            target_entry = QtWidgets.QLabel()
            # target_entry.setFocusPolicy(QtCore.Qt.StrongFocus)
            self.layout.addWidget(target_entry, i, 2)
            self.target_entries[axis] = target_entry
        self.set_text_bg_color('white',self.main_window.colors['dark_gray'])


    def update_coordinates(self, values,target_values):
        for axis in values.keys():
            self.entries[axis].setText(str(values[axis]))
            self.target_entries[axis].setText(str(target_values[axis]))

    def set_text_bg_color(self, color,bg_color):
        for axis in self.entries.keys():
            self.entries[axis].setStyleSheet(f"color: {color}")
            self.entries[axis].setStyleSheet(f"background-color: {bg_color}")
            self.target_entries[axis].setStyleSheet(f"color: {color}")
            self.target_entries[axis].setStyleSheet(f"background-color: {bg_color}")


class DropdownBox(QtWidgets.QGroupBox):
    machine_connected = QtCore.Signal(str)  # Define a new signal
    balance_connected = QtCore.Signal(str)  # Define a new signal
    
    def __init__(self, title,main_window):
        super().__init__(title)
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)

        self.machine_port_options = QtWidgets.QComboBox()
        self.machine_port_options.addItems(["COM1", "COM2", "COM3"])
        self.machine_port_options.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button = QtWidgets.QPushButton("Connect")
        self.machine_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.machine_connect_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.machine_connect_button.clicked.connect(lambda: self.machine_connected.emit(self.machine_port_options.currentText()))

        self.layout.addWidget(QtWidgets.QLabel("Machine Ports:"), 0, 0)
        self.layout.addWidget(self.machine_port_options, 0, 1)
        self.layout.addWidget(self.machine_connect_button, 0, 2)

        self.balance_port_options = QtWidgets.QComboBox()
        self.balance_port_options.addItems(["COM1", "COM2", "COM3"])
        self.balance_port_options.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button = QtWidgets.QPushButton("Connect")
        self.balance_connect_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.balance_connect_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.balance_connect_button.clicked.connect(lambda: self.balance_connected.emit(self.balance_port_options.currentText()))
        self.layout.addWidget(QtWidgets.QLabel("Balance Ports:"), 1, 0)
        self.layout.addWidget(self.balance_port_options, 1, 1)
        self.layout.addWidget(self.balance_connect_button, 1, 2)

class PressurePlotBox(QtWidgets.QGroupBox):
    regulating_pressure = QtCore.Signal(bool)
    def __init__(self, title, main_window):
        super().__init__(title)
        self.main_window = main_window
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QGridLayout(self)

        self.current_pressure_label = QtWidgets.QLabel("Current Pressure:")  # Create a new QLabel for the current pressure label
        self.current_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the current pressure value
        self.target_pressure_label = QtWidgets.QLabel("Target Pressure:")  # Create a new QLabel for the target pressure label
        self.target_pressure_value = QtWidgets.QLabel()  # Create a new QLabel for the target pressure value

        self.layout.addWidget(self.current_pressure_label, 0, 0)  # Add the QLabel to the layout at position (0, 0)
        self.layout.addWidget(self.current_pressure_value, 0, 1)  # Add the QLabel to the layout at position (0, 1)
        self.layout.addWidget(self.target_pressure_label, 1, 0)  # Add the QLabel to the layout at position (1, 0)
        self.layout.addWidget(self.target_pressure_value, 1, 1)  # Add the QLabel to the layout at position (1, 1)

        self.pressure_regulation_button = QtWidgets.QPushButton("Regulate Pressure")
        self.pressure_regulation_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.pressure_regulation_button.setStyleSheet(f"background-color: {self.main_window.colors['blue']}")
        self.regulating = False
        self.pressure_regulation_button.clicked.connect(self.toggle_regulation)
        self.layout.addWidget(self.pressure_regulation_button, 2, 0, 1, 2)  # Add the button to the layout at position (2, 0) and make it span 2 columns

        self.chart = QtCharts.QChart()
        self.chart.setTheme(QtCharts.QChart.ChartThemeDark)
        self.chart.setBackgroundBrush(QtGui.QBrush(self.main_window.colors['dark_gray']))  # Set the background color to grey
        self.chart_view = QtCharts.QChartView(self.chart)
        self.series = QtCharts.QLineSeries()
        self.series.setColor(QtCore.Qt.white)
        self.chart.addSeries(self.series)

        self.target_pressure_series = QtCharts.QLineSeries()  # Create a new line series for the target pressure
        self.target_pressure_series.setColor(QtCore.Qt.red)  # Set the line color to red
        self.chart.addSeries(self.target_pressure_series)

        self.axisX = QtCharts.QValueAxis()
        self.axisX.setTickCount(3)
        self.axisX.setRange(0, 100)
        self.axisY = QtCharts.QValueAxis()
        self.axisY.setTitleText("Pressure (psi)")

        self.chart.addAxis(self.axisX, QtCore.Qt.AlignBottom)
        self.chart.addAxis(self.axisY, QtCore.Qt.AlignLeft)

        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)
        self.target_pressure_series.attachAxis(self.axisX)
        self.target_pressure_series.attachAxis(self.axisY)

        self.chart.legend().hide()  # Hide the legend
        self.chart_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.chart_view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.chart_view)

    def update_pressure(self, pressure_log,target_pressure):
        self.series.clear()
        self.target_pressure_series.clear()
        for i, pressure in enumerate(pressure_log):
            self.series.append(i, pressure)

        self.target_pressure_series.append(0,target_pressure)  # Add the lower point of the target pressure line
        self.target_pressure_series.append(100,target_pressure)  # Add the upper point of the target pressure line

        min_pressure = min(pressure_log + [target_pressure]) - 2
        max_pressure = max(pressure_log + [target_pressure]) + 2

        self.axisY.setRange(min_pressure, max_pressure)

        self.current_pressure_value.setText(f"{pressure_log[-1]}")  # Update the current pressure value
        self.target_pressure_value.setText(f"{target_pressure}")  # Update the target pressure value
    
    def toggle_regulation(self):
        self.regulating = not self.regulating
        self.regulating_pressure.emit(self.regulating)

class ShortcutTable(QtWidgets.QWidget):
    def __init__(self, shortcuts):
        super().__init__()
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        self.layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Shortcut Name", "Shortcut Key"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(shortcuts))

        for i, shortcut in enumerate(shortcuts):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(shortcut.key)))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(shortcut.name))
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.table)

class CommandTable(QtWidgets.QWidget):
    def __init__(self, commands):
        super().__init__()
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Number", "Command"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(1)

        for i, command_num in enumerate(commands.keys()):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(commands[command_num].get_number())))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(commands[command_num].get_command()))
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.layout.addWidget(self.table)
    
    def add_command(self, new_command):
        self.table.insertRow(0)
        self.table.setItem(0, 0, QtWidgets.QTableWidgetItem(str(new_command.get_number())))
        self.table.setItem(0, 1, QtWidgets.QTableWidgetItem(new_command.get_command()))

class Reagent():
    def __init__(self, name, color='white'):
        self.name = name
        self.color = color

class Slot:
    def __init__(self, number, reagent):
        self.number = number
        self.reagent = reagent
    
    def change_reagent(self, new_reagent):
        self.reagent = new_reagent

class RackBox(QtWidgets.QWidget):
    reagent_loaded = QtCore.Signal(Slot)

    def __init__(self,main_window, slots,reagents):
        super().__init__()
        self.main_window = main_window
        self.layout = QtWidgets.QGridLayout(self)
        self.reagents = reagents
        self.current_reagents = []
        self.slot_dropdowns = []
        self.slot_buttons = []
        self.slots = slots
        num_slots = len(slots)
        self.reagent_names = [reagent.name for reagent in reagents]

        self.add_reagent_button = QtWidgets.QPushButton("Add Reagent")
        self.add_reagent_button.clicked.connect(self.add_reagent)
        self.add_reagent_button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.add_reagent_button.setFocusPolicy(QtCore.Qt.NoFocus)
        # self.add_reagent_button.setObjectName("active")
        self.add_reagent_button.setCheckable(True)
        self.layout.addWidget(self.add_reagent_button, 0, num_slots,3,1)

        for slot in range(num_slots):
            current_reagent = QtWidgets.QLabel()
            # current_reagent.setObjectName("title")
            current_reagent.setStyleSheet(f"background-color: {self.main_window.colors['red']}")
            current_reagent.setStyleSheet("color: white")
            current_reagent.setText("Empty")
            current_reagent.setAlignment(QtCore.Qt.AlignCenter)
            self.current_reagents.append(current_reagent)
            self.layout.addWidget(self.current_reagents[slot], 0, slot)

            slot_options = QtWidgets.QComboBox()
            slot_options.addItems(self.reagent_names)
            slot_options.setStyleSheet("background-color: #474747; color: white;")
            slot_options.setFocusPolicy(QtCore.Qt.NoFocus)
            self.slot_dropdowns.append(slot_options)
            self.layout.addWidget(self.slot_dropdowns[slot], 1, slot)

            slot_button = QtWidgets.QPushButton("Load")
            slot_button.setFocusPolicy(QtCore.Qt.NoFocus)
            slot_button.setStyleSheet("background-color: #1e64b4")
            self.slot_buttons.append(slot_button)
            self.slot_buttons[slot].clicked.connect(self.emit_loading_signal(slot))
            self.layout.addWidget(self.slot_buttons[slot], 2, slot) 
    
    def emit_loading_signal(self, slot):
        def emit_signal():
            target_name = self.slot_dropdowns[slot].currentText()
            reagent = next((r for r in self.reagents if r.name == target_name), None)
            self.reagent_loaded.emit(Slot(slot, reagent))
        return emit_signal
    
    def update_reagents_dropdown(self, reagents):
        self.reagents = reagents
        self.reagent_names = [reagent.name for reagent in reagents]
        for slot_num in range(len(self.slots)):
            self.slot_dropdowns[slot_num].clear()
            self.slot_dropdowns[slot_num].addItems(self.reagent_names)

    def load_reagent(self, slot, reagent):    
        self.slots[slot].reagent = reagent
        self.current_reagents[slot].setText(reagent.name)
        self.current_reagents[slot].setStyleSheet(f"background-color: {reagent.color}")

    def make_transparent_icon(self):
        transparent_image = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        transparent_image.fill(QtCore.Qt.transparent)
        transparent_pixmap = QtGui.QPixmap.fromImage(transparent_image)
        transparent_icon = QtGui.QIcon(transparent_pixmap)
        return transparent_icon
    
    def add_reagent(self):
        self.new_reagent_window = QtWidgets.QDialog()
        self.new_reagent_window.setWindowTitle("Add new reagent")
        transparent_icon = self.make_transparent_icon()
        self.new_reagent_window.setWindowIcon(transparent_icon)
        window_layout = QtWidgets.QVBoxLayout(self.new_reagent_window)
        # Create input fields for the name and color of the reagent
        self.name_input = QtWidgets.QLineEdit()
        self.color_input = QtWidgets.QComboBox()
        self.color_input.addItems(list(self.main_window.colors.keys()))  # Add color options from main_window.colors

        window_layout.addWidget(QtWidgets.QLabel("Name:"))
        window_layout.addWidget(self.name_input)
        window_layout.addWidget(QtWidgets.QLabel("Color:"))
        window_layout.addWidget(self.color_input)

        # Create a button to add the new reagent
        add_button = QtWidgets.QPushButton("Add Reagent")
        add_button.clicked.connect(self.add_new_reagent)
        window_layout.addWidget(add_button)
        self.new_reagent_window.exec()
    
    def add_new_reagent(self):
        # Get the name and color from the input fields
        name = self.name_input.text()
        color = self.color_input.currentText()

        # Create a new reagent and add it to the list of reagents
        new_reagent = Reagent(name, color)
        self.reagents.append(new_reagent)

        # Update the dropdowns with the new reagent
        self.update_reagents_dropdown(self.reagents)

        # Close the new reagent window
        self.new_reagent_window.close()