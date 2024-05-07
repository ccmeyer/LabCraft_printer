import time
import serial
import threading
from threading import Thread
import re
import tkinter as tk
from tkinter import ttk

import glob
import json
import math
import os
import shutil

from pynput import keyboard
from pynput.keyboard import Key
from pyautogui import press
import datetime

import numpy as np
import pandas as pd

from utils import *


class Monitor(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.test = 'Something'
        self.start()

    def callback(self):
        self.root.quit()

    def run(self):
        self.root = tk.Tk()
        self.root.geometry("500x600")
        self.root.title("Status window")
        self.root.protocol("WM_DELETE_WINDOW", self.callback)
        self.root.resizable(0, 0)

        # configure the grid
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=2)

        self.label_0 = tk.StringVar()
        self.label_0.set('State:')
        self.l_0 = ttk.Label(self.root, textvariable=self.label_0)
        self.l_0.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

        self.info_0 = tk.StringVar()
        self.info_0.set('---')
        self.i_0 = ttk.Label(self.root, textvariable=self.info_0)
        self.i_0.grid(column=1, row=0, sticky=tk.W, padx=5, pady=5)

        self.label_1 = tk.StringVar()
        self.label_1.set('X:')
        self.l_1 = ttk.Label(self.root, textvariable=self.label_1)
        self.l_1.grid(column=0, row=1, sticky=tk.W, padx=5, pady=5)

        self.info_1 = tk.StringVar()
        self.info_1.set('---')
        self.i_1 = ttk.Label(self.root, textvariable=self.info_1)
        self.i_1.grid(column=1, row=1, sticky=tk.W, padx=5, pady=5)

        self.label_2 = tk.StringVar()
        self.label_2.set('Y:')
        self.l_2 = ttk.Label(self.root, textvariable=self.label_2)
        self.l_2.grid(column=0, row=2, sticky=tk.W, padx=5, pady=5)

        self.info_2 = tk.StringVar()
        self.info_2.set('---')
        self.i_2 = ttk.Label(self.root, textvariable=self.info_2)
        self.i_2.grid(column=1, row=2, sticky=tk.W, padx=5, pady=5)

        self.label_3 = tk.StringVar()
        self.label_3.set('Z:')
        self.l_3 = ttk.Label(self.root, textvariable=self.label_3)
        self.l_3.grid(column=0, row=3, sticky=tk.W, padx=5, pady=5)

        self.info_3 = tk.StringVar()
        self.info_3.set('---')
        self.i_3 = ttk.Label(self.root, textvariable=self.info_3)
        self.i_3.grid(column=1, row=3, sticky=tk.W, padx=5, pady=5)

        self.label_4 = tk.StringVar()
        self.label_4.set('P:')
        self.l_4 = ttk.Label(self.root, textvariable=self.label_4)
        self.l_4.grid(column=0, row=4, sticky=tk.W, padx=5, pady=5)

        self.info_4 = tk.StringVar()
        self.info_4.set('---')
        self.i_4 = ttk.Label(self.root, textvariable=self.info_4)
        self.i_4.grid(column=1, row=4, sticky=tk.W, padx=5, pady=5)

        self.label_5 = tk.StringVar()
        self.label_5.set('Droplets:')
        self.l_5 = ttk.Label(self.root, textvariable=self.label_5)
        self.l_5.grid(column=0, row=5, sticky=tk.W, padx=5, pady=5)

        self.info_5 = tk.StringVar()
        self.info_5.set('---')
        self.i_5 = ttk.Label(self.root, textvariable=self.info_5)
        self.i_5.grid(column=1, row=5, sticky=tk.W, padx=5, pady=5)

        self.label_6 = tk.StringVar()
        self.label_6.set('Print_pressure:')
        self.l_6 = ttk.Label(self.root, textvariable=self.label_6)
        self.l_6.grid(column=0, row=6, sticky=tk.W, padx=5, pady=5)

        self.info_6 = tk.StringVar()
        self.info_6.set('---')
        self.i_6 = ttk.Label(self.root, textvariable=self.info_6)
        self.i_6.grid(column=1, row=6, sticky=tk.W, padx=5, pady=5)

        self.label_7 = tk.StringVar()
        self.label_7.set('Print PSI:')
        self.l_7 = ttk.Label(self.root, textvariable=self.label_7)
        self.l_7.grid(column=0, row=7, sticky=tk.W, padx=5, pady=5)

        self.info_7 = tk.StringVar()
        self.info_7.set('---')
        self.i_7 = ttk.Label(self.root, textvariable=self.info_7)
        self.i_7.grid(column=1, row=7, sticky=tk.W, padx=5, pady=5)

        self.label_8 = tk.StringVar()
        self.label_8.set('Com_open:')
        self.l_8 = ttk.Label(self.root, textvariable=self.label_8)
        self.l_8.grid(column=0, row=8, sticky=tk.W, padx=5, pady=5)

        self.info_8 = tk.StringVar()
        self.info_8.set('---')
        self.i_8 = ttk.Label(self.root, textvariable=self.info_8)
        self.i_8.grid(column=1, row=8, sticky=tk.W, padx=5, pady=5)

        self.label_9 = tk.StringVar()
        self.label_9.set('Mass:')
        self.l_9 = ttk.Label(self.root, textvariable=self.label_9)
        self.l_9.grid(column=0, row=9, sticky=tk.W, padx=5, pady=5)

        self.info_9 = tk.StringVar()
        self.info_9.set('---')
        self.i_9 = ttk.Label(self.root, textvariable=self.info_9)
        self.i_9.grid(column=1, row=9, sticky=tk.W, padx=5, pady=5)

        self.label_10 = tk.StringVar()
        self.label_10.set('Set_print:')
        self.l_10 = ttk.Label(self.root, textvariable=self.label_10)
        self.l_10.grid(column=0, row=10, sticky=tk.W, padx=5, pady=5)

        self.info_10 = tk.StringVar()
        self.info_10.set('---')
        self.i_10 = ttk.Label(self.root, textvariable=self.info_10)
        self.i_10.grid(column=1, row=10, sticky=tk.W, padx=5, pady=5)

        self.label_11 = tk.StringVar()
        self.label_11.set('Current_command:')
        self.l_11 = ttk.Label(self.root, textvariable=self.label_11)
        self.l_11.grid(column=0, row=11, sticky=tk.W, padx=5, pady=5)

        self.info_11 = tk.StringVar()
        self.info_11.set('---')
        self.i_11 = ttk.Label(self.root, textvariable=self.info_11)
        self.i_11.grid(column=1, row=11, sticky=tk.W, padx=5, pady=5)

        self.label_12 = tk.StringVar()
        self.label_12.set('Clock:')
        self.l_12 = ttk.Label(self.root, textvariable=self.label_12)
        self.l_12.grid(column=0, row=12, sticky=tk.W, padx=5, pady=5)

        self.info_12 = tk.StringVar()
        self.info_12.set('---')
        self.i_12 = ttk.Label(self.root, textvariable=self.info_12)
        self.i_12.grid(column=1, row=12, sticky=tk.W, padx=5, pady=5)

        self.label_13 = tk.StringVar()
        self.label_13.set('Cycle_Count:')
        self.l_13 = ttk.Label(self.root, textvariable=self.label_13)
        self.l_13.grid(column=0, row=13, sticky=tk.W, padx=5, pady=5)

        self.info_13 = tk.StringVar()
        self.info_13.set('---')
        self.i_13 = ttk.Label(self.root, textvariable=self.info_13)
        self.i_13.grid(column=1, row=13, sticky=tk.W, padx=5, pady=5)

        self.label_14 = tk.StringVar()
        self.label_14.set('Last_added:')
        self.l_14 = ttk.Label(self.root, textvariable=self.label_14)
        self.l_14.grid(column=0, row=14, sticky=tk.W, padx=5, pady=5)

        self.info_14 = tk.StringVar()
        self.info_14.set('---')
        self.i_14 = ttk.Label(self.root, textvariable=self.info_14)
        self.i_14.grid(column=1, row=14, sticky=tk.W, padx=5, pady=5)

        self.root.mainloop()


class Platform():
    '''
    The platform class includes all the methods required to control all components of the printer
    '''
    def __init__(self):
        print('Created platform instance')
        self.last_signal = 'N'
        self.new_signal = 'N'
        self.controller_state = 'Free'
        self.x_pos = 'Unknown'
        self.y_pos = 'Unknown'
        self.z_pos = 'Unknown'
        self.p_pos = 'Unknown'

        self.step_size = 1000
        self.step_num = 3
        self.possible_steps = [50,250,500,1000,2000]

        self.default_pressure = 0
        self.print_state = 'Unknown'
        self.print_pressure = 'Unknown'
        self.print_psi = 'Unknown'
        self.target_print = 'Unknown'
        self.print_valve = 'Unknown'
        
        self.current = 'Unknown'
        self.clock = 'Unknown'
        self.cycle_count = 'Unknown'
        self.location = 'Unknown'

        self.com_open = 'Unknown'
        self.current_cmd = 'Unknown'
        self.last_added_cmd = 'Unknown'

        self.homed = False
        self.regulating_pressure = False
        self.gripper_active = False
        self.motors_active = False

        # PRESSURE CONVERSION VARIABLES
        self.FSS = 13107 #Set in manual 10-90% transfer function option Gage type sensor
        self.offset = 1638 #Set in manual 10-90% transfer function option Gage type sensor
        self.maxP = 15 # Max pressure for sensor is 15 psi

        self.command_number = 0
        self.command_log = {}

        self.array_start_x = 0
        self.array_start_y = 0
        self.array_start_z = 0

        self.log_path = 'Unknown'
        self.log_note = ''

        self.active_log = False
        self.log_cols = ['time','run_number','x_pos', 'y_pos', 'z_pos', 'p_pos','print_psi','print_valve','mass','actual_droplets','log_note']
        self.log_counter = 0
        self.run_number = 0

        self.mass = 'unknown'
        self.mass_record = []
        self.mass_diff = 0
        self.stable_mass = 'not_stable'

        self.actual_droplets = 0

        self.start_tracker()
        self.monitor = Monitor()
        self.update_thread = Thread(target = self.update_monitor,args=[])
        self.update_thread.daemon = True
        self.update_thread.start()
        self.current_key = False
        self.terminate = False
        self.base = './'

        self.read_defaults()
        self.select_mode(mode_name=self.default_settings['DEFAULT_DISPENSER'])
        self.load_default_positions()

        self.initiate_controller(self.default_settings['BOARD_PORT'])
        self.initiate_balance(self.default_settings['BALANCE_PORT'])

    def initiate_controller(self,port):
        try:
            self.controller = serial.Serial(port=port, baudrate=115200)
            print('Controller starting...')
            time.sleep(2)
            print('Controller started')
            self.controller_status = Thread(target = self.get_status,args=[])
            self.controller_status.daemon = True
            self.controller_status.start()
        except:
            print('\n---Controller unable to connect\n')

    def get_status(self):
        print('\n- Started controller thread')
        counter = 0
        while(True):
            if self.new_signal != self.last_signal:
                self.controller.write(self.new_signal.encode())
                self.controller.flush()
                self.new_signal = self.last_signal

            if self.controller.in_waiting > 0:
                try:
                    data = self.controller.readline().decode().strip()
                    try:
                        data_arr = data.split(',')

                        data_dict = {}
                        [data_dict.update({t.split(':')[0]:t.split(':')[1]}) for t in data_arr]
                        self.controller_state = data_dict['Serial']
                        self.clock = float(data_dict['Max_cycle'])
                        self.cycle_count = float(data_dict['Cycle_count'])
                        # # self.event = data_dict['Event']
                        self.x_pos = float(data_dict['X'])
                        self.y_pos = float(data_dict['Y'])
                        self.z_pos = float(data_dict['Z'])
                        self.p_pos = float(data_dict['P'])
                        # # self.r_pos = float(data_dict['R'])
                        self.com_open = int(data_dict['Com_open'])
                        self.current_cmd = int(data_dict['Current_command'])
                        self.last_added_cmd = int(data_dict['Last_added'])

                        self.print_valve = data_dict['Print_valve']
                        

                        # # self.refuel_valve = data_dict['Refuel_valve']
                        # # self.refuel_state = float(data_dict['Refuel_state'])
                        # # self.print_state = float(data_dict['Print_state'])
                        self.actual_droplets = float(data_dict['Droplets'])
                        # # self.refuel_pressure = float(data_dict['Refuel_data'])
                        # # self.refuel_pressure = 1600
                        self.print_pressure = float(data_dict['Print_pressure'])
                        self.target_print = float(data_dict['Set_print'])

                        # self.print_pressure_avg = float(data_dict['Average_Print'])

                    except:
                        print('Cant parse:',data)
                except:
                    print('Cant decode output')

            if self.terminate == True:
                print('quitting the status update thread')
                break

            counter += 1
            time.sleep(0.005)

    def convert_pressure(self):
        FSS = 13107 #Set in manual 10-90% transfer function option Gage type sensor
        offset = 1638 #Set in manual 10-90% transfer function option Gage type sensor
        maxP = 15 # Max pressure for sensor is 15 psi
        # psiConv = 68.948 # Conversion of mbar to psi 
        try:
            # self.print_psi = round(((self.print_pressure - offset) / FSS) * (maxP / psiConv),4)
            self.print_psi = round(((self.print_pressure - offset) / FSS) * (maxP),4)
        except:
            self.print_psi = '---'
        # self.refuel_psi = round(((self.refuel_pressure - offset) / FSS) * (maxP / psiConv),4)
        return

    def initiate_balance(self,port):
        try:
            self.balance = serial.Serial(port=port, baudrate=9600, bytesize=8, timeout=2, stopbits=serial.STOPBITS_ONE)
            self.masses = []
            self.mass_counter = 0
            self.mass_thread = Thread(target = self.update_mass,args=[])
            self.mass_thread.daemon = True
            self.mass_thread.start()
        except:
            print('\n--Unable to connect to balance--\n')
            self.mass = 'Unavailable'

    def update_mass(self):
        print('\n- Started mass thread')
        while(True):
            if self.terminate == True:
                print('quitting the Balance update thread')
                break
            try:
                if self.balance.in_waiting > 0:
                    data = self.balance.readline()
                    try:
                        data = data.decode("ASCII")
                        [sign,mass] = re.findall(r'(-?) *([0-9]+\.[0-9]+) [a-zA-Z]*',data)[0]
                        mass = float(''.join([sign,mass]))
                        if len(self.masses) < 5:
                            self.masses.append(mass)
                        else:
                            self.masses = self.masses[1:]
                            self.masses.append(mass)
                        self.mass = round(np.mean(self.masses),2)
                    except:
                        continue

            except:
                self.mass_counter += 1
                if self.mass_counter > 50:
                    self.mass = 'unknown'
                    self.mass_counter = 0
            time.sleep(0.1)

    def wait_for_stable_mass(self):
        print('--- Waiting for balance to stabilize...')
        count = 0
        time.sleep(0.5)
        while True:
            if self.stable_mass != 'not_stable':
                print(f'Count:{count}')
                count += 1
            else:
                count = 0
                print('.',end='')
            if count == 10:
                print('Mass stabilized')
                return self.stable_mass

            if self.check_for_pause():
                if self.ask_yes_no(message="Quit waiting for scale? (y/n)"):
                    print('Quitting\n')
                    return self.stable_mass
            time.sleep(0.5)
    
    def calibrate_pressure(self,target_volume=50,tolerance=0.02):
        if not self.regulating_pressure:
            print('Must regulate pressure')
            return
        if not self.ask_yes_no(message='Calibrate printer head? (y/n)'):
            print('Did not calibrate...')
            section_break()
            return
        
        if not self.gripper_active:
            self.toggle_gripper()

        self.move_to_location(location='balance',direct=False,safe_y=True)
        
        target_mass = (target_volume/1000) *100 # target_volume in nL and target_mass in mg
        max_pressure_change = 0.5  # maximum change in pressure in a single step
        while True:
            mass_initial = self.wait_for_stable_mass()
            self.print_droplets(100)
            mass_final = self.wait_for_stable_mass()
            mass_diff = mass_final - mass_initial
            print(f'Mass difference: {mass_diff}')
            if mass_diff > (target_mass*(1-tolerance)) and mass_diff < (target_mass*(1+tolerance)):
                print('TARGET VOLUME ACHIEVED')
                return
            else:
                proportion = (mass_diff / target_mass)
                print('Current proportion:',round(proportion,2))
                if not self.ask_yes_no(message='Continue calibrating? (y/n)'):
                    return
                pressure_change = (self.print_psi / proportion) - self.print_psi
                if abs(pressure_change) > max_pressure_change:
                    pressure_change = max_pressure_change if pressure_change > 0 else -max_pressure_change
                new_pressure = self.print_psi + pressure_change

                print('New pressure: ',new_pressure)
                self.set_absolute_pressure(new_pressure)
                time.sleep(0.2)


    def update_monitor(self):
        time.sleep(3)
        print('--- Now updating monitor')

        while True:
            # try:
            self.convert_pressure()
            self.monitor.info_0.set(str(self.controller_state))
            self.monitor.info_1.set(str(self.x_pos))
            self.monitor.info_2.set(str(self.y_pos))
            self.monitor.info_3.set(str(self.z_pos))
            self.monitor.info_4.set(str(self.p_pos))
            self.monitor.info_5.set(str(self.actual_droplets))
            self.monitor.info_6.set(str(self.print_pressure))
            self.monitor.info_7.set(str(self.print_psi))
            self.monitor.info_8.set(str(self.com_open))
            self.monitor.info_9.set(str(self.mass))
            self.monitor.info_10.set(str(self.target_print))
            self.monitor.info_11.set(str(self.current_cmd))
            self.monitor.info_12.set(str(self.clock))
            self.monitor.info_13.set(str(self.cycle_count))
            self.monitor.info_14.set(str(self.last_added_cmd))


            # self.monitor.info_10.set(str(self.r_pos))
            # self.monitor.info_11.set(str(self.print_valve))
            # self.monitor.info_12.set(str(self.refuel_valve))
            # self.monitor.info_13.set(str(self.mass))
            # self.monitor.info_14.set(str(self.actual_droplets))

            if self.mass != 'unknown':
                self.mass_record.append(self.mass)
                if len(self.mass_record) > 10:
                    self.mass_record.pop(0)
                if len(self.mass_record) == 10:
                    mass_std = np.std(self.mass_record)
                    if mass_std < 0.01:
                        self.stable_mass = round(np.mean(self.mass_record),3)
                    else:
                        self.stable_mass = 'not_stable'



            if self.active_log == True and self.log_counter >= 3:
                self.log_state()
                self.log_counter = 0
                self.log_note = ''
            # except:
            #     print('Monitor failure...')
            time.sleep(0.01)
            self.log_counter += 1

            if self.terminate == True:
                print('quitting the monitor update thread')
                break
        print('monitor down')
        return

    def start_tracker(self):
        print('starting traker')
        self.pause = False
        self.listener = keyboard.Listener(
            on_press=self.on_press)
        self.listener.start()
        self.time_stamp = datetime.datetime.now().timestamp()
        return

    def on_press(self,key):
        self.shift = False
        self.current_key = key
        self.time_stamp = datetime.datetime.now().timestamp()
        if key == keyboard.Key.backspace:
            self.pause = True
        if key == Key.shift or key == Key.shift_r:
            self.shift = True

    def get_current_key(self):
        while True:
            if self.current_key and datetime.datetime.now().timestamp() - self.time_stamp < 0.5:
                if self.current_key not in [Key.shift,Key.shift_r,Key.enter]:
                    try:
                        output = self.current_key.char
                    except:
                        output = self.current_key
                    press('esc')
                    self.current_key = False
                    return output
            time.sleep(0.01)

    def ask_yes_no(self,message='Choose yes (y) or no (n)'):
        print(message)
        while True:
            key = self.get_current_key()
            if type(key) != type('string'):
                continue
            if key == 'y':
                return True
            elif key == 'n':
                return False
            elif key == Key.esc:
                continue
            else:
                print(f'{key} is not a valid input')

    def get_file_path(self,path,base=False):
        if base:
            path = ''.join([self.base,path])
        paths = glob.glob(path)
        if len(paths) == 1:
            return paths[0]
        elif len(paths) == 0:
            print('Path: {} was not found'.format(path))
            return
        else:
            print('Found multiple paths')
            return select_options(paths,trim=True)

    def get_all_paths(self,path,base=False):
        if base:
            path = ''.join([self.base,path])
        paths = glob.glob(path)
        if len(paths) == 1:
            return paths[0]
        elif len(paths) == 0:
            print('Path: {} was not found'.format(path))
            return
        else:
            return paths

    def check_for_pause(self):
        if self.pause:
            print('Process has been paused')
            self.pause = False
            return True
        self.pause = False
        return False

    def stop_tracker(self):
        self.listener.stop()
        return

    def disconnect_all(self):
        print('Disconnecting update thread')
        self.terminate = True
        self.update_thread.join()
        print('\nJoined update thread')
        self.controller_status.join()
        print('Joined controller status thread')
        self.controller.close()
        print('Closed controller')
        return

    def initiate_log(self):
        file_name = input('Type file name: ')
        self.log_path = ''.join(['./pressure_data/',file_name,'.xlsx'])
        print('new log path: ',self.log_path)
        df = pd.DataFrame(columns=self.log_cols)
        df.set_index(self.log_cols[0]).to_excel(self.log_path)
        self.active_log = True
        return

    def toggle_log(self):
        if self.log_path == 'Unknown':
            self.initiate_log()
        if self.active_log:
            self.active_log = False
            print('-- Paused log --')
        else:
            self.run_number += 1
            self.active_log = True
            print('-- Resumed log --')
        return

    def log_state(self,note=''):
        complete_dict = self.__dict__
        export_data = dict((k,complete_dict[k]) for k in self.log_cols if k in complete_dict)
        export_data['time'] = datetime.datetime.now().time()
        previous = pd.read_excel(self.log_path)
        current = pd.DataFrame([export_data])
        export_df = pd.concat([previous,current])
        export_df.set_index(self.log_cols[0]).to_excel(self.log_path)
        return

    def read_defaults(self):
        with open('./default_settings.json') as json_file:
            self.default_settings =  json.load(json_file)
        print('Read the default_settings.json file')
        self.base = self.default_settings['BASE_PATH']
        self.possible_dispensers = list(self.default_settings['DISPENSER_TYPES'].keys())
        print('Possible modes:',self.possible_dispensers)

        self.mode = None
        return
    
    def select_mode(self,mode_name=False):
        if not mode_name:
            current_index = self.possible_dispensers.index(self.mode)
            new_index = (current_index + 1) % len(self.possible_dispensers)
            print(self.possible_dispensers[new_index])

            self.load_dispenser_defaults(self.possible_dispensers[new_index])
            return
        elif self.mode == mode_name:
            print('Already in the selected mode')
            self.load_dispenser_defaults(mode_name)
            return
        else:
            if not mode_name in self.possible_dispensers:
                print('Not an available mode')
                return
            else:
                self.load_dispenser_defaults(mode_name)
                # self.set_absolute_pressure(self.pulse_pressure,self.refuel_pressure)
                return
    
    def load_dispenser_defaults(self,mode):
        print('Loading mode:',mode)
        self.height = self.default_settings['DISPENSER_TYPES'][mode]['height']
        self.safe_y = self.default_settings['DISPENSER_TYPES'][mode]['safe_y']
        self.pulse_width = self.default_settings['DISPENSER_TYPES'][mode]['pulse_width']
        self.default_pressure = self.default_settings['DISPENSER_TYPES'][mode]['print_pressure']
        self.target_volume = self.default_settings['DISPENSER_TYPES'][mode]['target_disp_volume']
        self.frequency = self.default_settings['DISPENSER_TYPES'][mode]['frequency']
        self.max_volume =  self.default_settings['DISPENSER_TYPES'][mode]['max_volume']
        self.min_volume =  self.default_settings['DISPENSER_TYPES'][mode]['min_volume']
        self.current_volume = 0
        self.calibrated = False
        self.tracking_volume = False
        self.mode = mode

        return            

    def load_default_positions(self):
        # Extract all calibration data
        try:
            self.calibration_file_path = self.get_file_path('Calibrations/default_positions_{}.json'.format(self.mode),base=True)
            with open(self.calibration_file_path) as json_file:
                self.calibration_data =  json.load(json_file)
            print('Loaded default positions:{}'.format(self.mode))

        except:
            all_calibrations = self.get_all_paths('Calibrations/*.json',base=True)
            print('Possible printing calibrations:')

            target = select_options(all_calibrations,trim=True)
            print('Chosen plate: ',target)
            self.calibration_file_path = target

            with open(self.calibration_file_path) as json_file:
                self.calibration_data =  json.load(json_file)
        return

    def move_to_location(self,location=False,direct=False,safe_y=False):
        '''
        Tells the robot to move to a location based on the defined coordinates in the calibration file.
        If direct is set to True, the robot will move directly to the location. If safe_y is set to True, 
        the robot will move to the safe_y position before moving to the location to avoid running into an obsticle.
        '''
        if self.motors_active == False:
            print('Motors must be active')
            return
        print('Current',self.location)
        if not location:
            location,quit = select_options(list(self.calibration_data.keys()))
            if quit: return
        print('Moving to:',location)

        if self.location == location:
            print('Already in {} position'.format(location))
            return
        available_locations = list(self.calibration_data.keys())
        if location not in available_locations:
            print(f'{location} not present in calibration data')
            return
        
        if location == 'balance' or self.location == 'balance':
            safe_y = True
            direct = False

        target_coordinates = self.calibration_data[location]
        up_first = False
        if direct and self.z_pos < target_coordinates['z']:
            up_first = True
            self.set_absolute_coordinates(self.x_pos, self.y_pos, target_coordinates['z'])

        x_limit = -4500
        if self.x_pos > x_limit and target_coordinates['x'] < x_limit or self.x_pos < x_limit and target_coordinates['x'] > x_limit:
            safe_y = True

        if direct and not safe_y:
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        elif not direct and not safe_y:
            self.set_absolute_coordinates(self.x_pos, self.y_pos, self.height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.target_coordinates['z'])
        elif not direct and safe_y:
            self.set_absolute_coordinates(self.x_pos, self.y_pos, self.height)
            self.set_absolute_coordinates(self.x_pos, self.safe_y, self.height)
            self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.height)
            self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        elif direct and safe_y:
            if up_first:
                self.set_absolute_coordinates(self.x_pos, self.safe_y, target_coordinates['z'])
                self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, target_coordinates['z'])
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
            else:
                self.set_absolute_coordinates(self.x_pos, self.safe_y, self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], self.safe_y, self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], self.z_pos)
                self.set_absolute_coordinates(target_coordinates['x'], target_coordinates['y'], target_coordinates['z'])
        self.location = location
        return
    
    def save_position(self,location=False,new=False,ask=True):
        if new:
            if not self.ask_yes_no(message=f"Create a new position? (y/n)"): return
            location = input('Enter the name of the position: ')
            self.calibration_data.update({location:{"x":self.x_pos,"y":self.y_pos,"z":self.z_pos}})
        elif not location and not new:
            print('Select which position to set:')
            location,quit = select_options(list(self.calibration_data.keys()))
            if quit: return
            self.calibration_data[location] = {"x":self.x_pos,"y":self.y_pos,"z":self.z_pos}
        else:
            self.calibration_data[location] = {"x":self.x_pos,"y":self.y_pos,"z":self.z_pos}
        
        if ask:
            if not self.ask_yes_no(message=f"Write {location} position to file? (y/n)"): return
        
        with open(self.calibration_file_path, 'w') as outfile:
            json.dump(self.calibration_data, outfile)
        print("Position data saved")

        return

    def move_to_well(self,row,col):
        row_spacing = 100
        col_spacing = 100

        new_x = (row_spacing*row)+self.array_start_x
        new_y = (col_spacing*col)+self.array_start_y
        new_z = self.array_start_z
        self.set_absolute_coordinates(new_x,new_y,new_z)
        return
    
    def print_array(self):
        if not self.motors_active:
            print('Motors must be active')
            return
        if not self.regulating_pressure:
            print('Must regulate pressure')
            return
        if not self.ask_yes_no(message="Print an array? (y/n)"):
            return
        all_arrays = self.get_all_paths('Print_arrays/*.csv',base=True)
        chosen_path,quit = select_options(all_arrays,message='Select one of the arrays:',trim=True)
        if quit: return

        if not self.gripper_active:
            self.toggle_gripper()
        
        location= 'print'
        if self.ask_yes_no(message=f"Move to {location} position? (y/n)"):
            self.move_to_location(location='print',direct=True,safe_y=False)
            self.array_start_x = self.calibration_data[location]['x']
            self.array_start_y = self.calibration_data[location]['y']
            self.array_start_z = self.calibration_data[location]['z']
        else:
            self.array_start_x = self.x_pos
            self.array_start_y = self.y_pos
            self.array_start_z = self.z_pos
        
        arr = pd.read_csv(chosen_path)

        for index, line in arr.iterrows():
            if self.check_for_pause():
                if self.ask_yes_no(message="Quit print? (y/n)"):
                    print('Quitting\n')
                    return

            print('\nOn {} out of {}'.format(index+1,len(arr)))

            self.move_to_well(line['Row'],line['Column'])
            self.print_droplets(line['Droplet'])
        self.move_to_location(location='loading',direct=True,safe_y=False)
        return
    
    def generate_command(self, commandName, param1, param2, param3, timeout=0):
        while self.com_open == 0 or self.last_added_cmd - self.current_cmd > 1:
            time.sleep(0.2)
            print(f'---Waiting for Com:{timeout}---')
            timeout += 1
            if timeout > 100:
                print('-COMMAND FAILED TO SEND-')
                return
        
        self.new_signal = f'<{self.command_number},{commandName},{param1},{param2},{param3}>'
        self.command_log.update({self.command_number: self.new_signal})
        self.command_number += 1

        time.sleep(0.2)
        return

    def set_relative_coordinates(self,x,y,z):
        self.generate_command('RELATIVE_XYZ',x,y,z)
        return
    
    def set_absolute_coordinates(self,x,y,z):
        self.generate_command('ABSOLUTE_XYZ',x,y,z)
        return
    
    def print_droplets(self,droplet_count):
        if not self.regulating_pressure:
            print('Must be regulating pressure')
            return
        self.generate_command('PRINT',droplet_count,0,0)
        return

    def convert_psi(self,psi):
        return ((psi / self.maxP) * self.FSS) + self.offset
    
    def set_relative_pressure(self,pressure):
        raw_pressure = self.convert_psi(pressure) - self.offset
        self.generate_command('RELATIVE_P',raw_pressure,0,0)
        return

    def set_absolute_pressure(self,pressure):
        raw_pressure = self.convert_psi(pressure)
        self.generate_command('ABSOLUTE_P',raw_pressure,0,0)
        return
    
    def reset_syringe(self):
        self.generate_command('RESET_P',0,0,0)
        return
    
    def toggle_gripper(self):
        self.generate_command('TOGGLE_GRIPPER',0,0,0)
        self.gripper_active = True
        return
    
    def gripper_off(self):
        self.generate_command('GRIPPER_OFF',0,0,0)
        self.gripper_active = False
        return
    
    def enable_motors(self):
        self.generate_command('ENABLE_MOTORS',0,0,0)
        self.motors_active = True
        return
    
    def disable_motors(self):
        self.generate_command('DISABLE_MOTORS',0,0,0)
        self.motors_active = False
        return
    
    def home_all(self):
        if not self.motors_active:
            print('Most activate motors first')
            return
        self.generate_command('HOME_ALL',0,0,0)
        self.homed = True
        self.location = 'home'
        return
    
    def regulate_pressure(self):
        if not self.homed:
            print('Must home before regulating pressure')
            return
        self.generate_command('REGULATE_P',0,0,0)
        self.regulating_pressure = True
        return
    
    def unregulate_pressure(self):
        self.generate_command('UNREGULATE_P',0,0,0)
        self.regulating_pressure = False
        return

    def reset_syringe(self):
        if not self.motors_active:
            print('Motors must be active')
            return
        self.generate_command('RESET_P',0,0,0)
        return
    
    def pause_robot(self):
        self.generate_command('PAUSE',0,0,0)
        return
    
    def clear_queue(self):
        self.generate_command('CLEAR_QUEUE',0,0,0)
        return

    def drive_platform(self):
        '''
        Comprehensive manually driving function. Within this method, the
        operator is able to move the dobot by wells, load and unload the
        gripper, set and control pressures, and print defined arrays
        '''
        print("Driving platform...")

        while True:
            if self.com_open == 1:
                print('Controller is:',self.controller_state)
                key = self.get_current_key()
                print(key)
                if key == Key.up:
                    self.set_relative_coordinates(self.step_size,0,0)
                elif key == Key.down:
                    self.set_relative_coordinates(-self.step_size,0,0)
                elif key == Key.left:
                    self.set_relative_coordinates(0,self.step_size,0)
                elif key == Key.right:
                    self.set_relative_coordinates(0,-self.step_size,0)
                elif key == 'k':
                    self.set_relative_coordinates(0,0,self.step_size)
                elif key == 'm':
                    self.set_relative_coordinates(0,0,-self.step_size)
                # elif key == 'R':
                #     self.new_signal = '<resetXYZ>'
                
                elif key == 'H':
                    self.home_all()
                elif key == 'D':
                    self.move_to_location(direct=True,safe_y=False)
                    # self.set_absolute_coordinates(-4500,3500,-35000)
                elif key == 'F':
                    # self.set_absolute_coordinates(-5000,7000,-20000)
                    self.move_to_location(direct=False,safe_y=True)
                # elif key == 'T':
                #     self.new_signal = '<absoluteXYZ,-5000,2000,-29000>'
                elif key == 'L':
                    self.move_to_location(location='loading',direct=True,safe_y=False)
                elif key == '{':
                    self.move_to_location(location='print',direct=True,safe_y=False)

                elif key == 'c':
                    self.print_droplets(5)
                elif key == 'v':
                    self.print_droplets(20)
                elif key == 'b':
                    self.print_droplets(100)

                elif key == 'C':
                    self.calibrate_pressure(target_volume=self.target_volume,tolerance=0.02)

                elif key == 'P':
                    self.print_array()

                elif key == 'g':
                    self.toggle_gripper()
                elif key == 'G':
                    self.gripper_off()
                elif key == 'I':
                    self.enable_motors()
                elif key == 'O':
                    self.disable_motors()

                elif key == '!':
                    for key, value in self.command_log.items():
                        print(f'{key}: {value}')

                # elif key == '^':
                #     self.new_signal = '<openP>'
                # elif key == '(':
                #     self.new_signal = '<closeP>'
                elif key == '}':
                    self.reset_syringe()

                # elif key == '1':
                #     self.new_signal = '<relativeCurrent,-100>'
                    # self.new_signal = '<relativeCurrent,-100>'
                # elif key == '2':
                #     self.new_signal = '<relativePR,0,-100>'
                # elif key == '3':
                #     self.new_signal = '<relativePR,0,100>'
                # elif key == '4':
                #     self.new_signal = '<relativeCurrent,-100>'
                    # self.new_signal = '<relativeCurrent,100>'

                elif key == '6':
                    self.set_relative_pressure(-0.2)
                elif key == '7':
                    self.set_relative_pressure(-0.05)
                elif key == '8':
                    self.set_relative_pressure(0.05)
                elif key == '9':
                    self.set_relative_pressure(0.2)

                elif key == '+':
                    self.regulate_pressure()
                elif key == '-':
                    self.unregulate_pressure()

                elif key == '5':
                    self.set_absolute_pressure(0)
                elif key == '0':
                    self.set_absolute_pressure(1.8)


                # elif key == 'S':
                #     self.toggle_log()
                # elif key == 'L':
                #     self.initiate_log()

                elif key == 'Z':
                    self.save_position(new=False)
                elif key == 'X':
                    self.save_position(new=True)

                elif key == ';':
                    self.step_num += 1
                    self.step_size = self.possible_steps[abs(self.step_num) % len(self.possible_steps)]
                    print('Changed to {}'.format(self.step_size))
                elif key == '.':
                    self.step_num -= 1
                    self.step_size = self.possible_steps[abs(self.step_num) % len(self.possible_steps)]
                    print('Changed to {}'.format(self.step_size))
                
                elif key == 'q':
                    self.disable_motors()
                    time.sleep(0.5)
                    self.gripper_off()
                    time.sleep(0.5)
                    print('\n---Quitting---\n')
                    return
            else:
                print('---Controller is:',self.controller_state)
                time.sleep(0.5)


if __name__ == '__main__':
    platform = Platform()
    platform.drive_platform()
    print('Trying to quit')
    platform.disconnect_all()
    print('Ended all threads, close window')
