import time
import serial
import threading
from threading import Thread
import re
import tkinter as tk
from tkinter import ttk

import glob
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
    The platform class includes all the methods required to control the Dobot
    robotic arm, the Arduino and the Precigenome pressure regulator
    '''
    def __init__(self):
        print('Created platform instance')
        self.last_signal = 'N'
        self.new_signal = 'N'
        self.ard_state = 'Free'
        self.x_pos = 'Unknown'
        self.y_pos = 'Unknown'
        self.z_pos = 'Unknown'
        self.p_pos = 'Unknown'
        self.r_pos = 'Unknown'
        self.refuel_state = 'Unknown'
        self.print_state = 'Unknown'
        self.refuel_pressure = 'Unknown'
        self.print_pressure = 'Unknown'
        self.refuel_psi = 'Unknown'
        self.print_psi = 'Unknown'
        self.print_valve = 'Unknown'
        self.target_print = 'Unknown'
        self.current = 'Unknown'
        self.clock = 'Unknown'

        self.com_open = 'Unknown'
        self.current_cmd = 'Unknown'
        self.last_added_cmd = 'Unknown'

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
        self.log_cols = ['time','run_number','x_pos', 'y_pos', 'z_pos', 'p_pos', 'r_pos','print_psi','refuel_psi','print_valve','refuel_valve','mass','actual_droplets','log_note']
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

        self.initiate_arduino('COM7')
        self.initiate_balance('COM6')

    def initiate_arduino(self,port):
        try:
            self.arduino = serial.Serial(port=port, baudrate=115200)
            print('Arduino starting...')
            time.sleep(2)
            print('Arduino started')
            self.ard_status = Thread(target = self.get_status,args=[])
            self.ard_status.daemon = True
            self.ard_status.start()
        except:
            print('\n---Arduino unable to connect\n')

    def get_status(self):
        print('\n- Started arduino thread')
        counter = 0
        while(True):
            if self.new_signal != self.last_signal:
                self.arduino.write(self.new_signal.encode())
                self.arduino.flush()
                self.new_signal = self.last_signal

            if self.arduino.in_waiting > 0:
                try:
                    data = self.arduino.readline().decode().strip()
                    try:
                        data_arr = data.split(',')

                        data_dict = {}
                        [data_dict.update({t.split(':')[0]:t.split(':')[1]}) for t in data_arr]
                        self.ard_state = data_dict['Serial']
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

    def update_monitor(self):
        time.sleep(3)
        print('--- Now updating monitor')

        while True:
            # try:
            self.convert_pressure()
            self.monitor.info_0.set(str(self.ard_state))
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
        self.ard_status.join()
        print('Joined arduino status thread')
        self.arduino.close()
        print('Closed Arduino')
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

    def move_to_well(self,row,col):
        row_spacing = 100
        col_spacing = 100

        # while True:
        #     if self.ard_state == 'Free':
        new_x = (row_spacing*row)+self.array_start_x
        new_y = (col_spacing*col)+self.array_start_y
        new_z = self.array_start_z
        self.set_absolute_coordinates(new_x,new_y,new_z)
        return
            # else:
            #     print('---Arduino is:',self.ard_state)
            #     time.sleep(0.2)

    # def print_droplets(self,droplets):
    #     while True:
    #         if self.ard_state == 'Free':
    #             self.new_signal = f'<print,{droplets}>'
    #             if self.active_log:
    #                 note_str = f'print,{droplets}'
    #                 self.log_note = note_str
    #             return
    #         else:
    #             print('---Arduino is:',self.ard_state)
    #             time.sleep(0.2)

    def print_array(self):

        if not self.ask_yes_no(message="Print an array? (y/n)"):
            return
        all_arrays = self.get_all_paths('Print_arrays/*.csv',base=True)
        chosen_path,quit = select_options(all_arrays,message='Select one of the arrays:',trim=True)
        if quit: return

        arr = pd.read_csv(chosen_path)

        self.array_start_x = self.x_pos
        self.array_start_y = self.y_pos
        self.array_start_z = self.z_pos


        for index, line in arr.iterrows():
            if self.check_for_pause():
                if self.ask_yes_no(message="Quit print? (y/n)"):
                    print('Quitting\n')
                    return

            print('\nOn {} out of {}'.format(index+1,len(arr)))

            self.move_to_well(line['Row'],line['Column'])
            time.sleep(0.2)
            self.print_droplets(line['Droplet'])
            time.sleep(0.2)

        return

    def generate_command(self,commandName,param1,param2,param3,timeout=0):
        if self.com_open == 1 and self.last_added_cmd - self.current_cmd <= 1:
            self.new_signal = f'<{self.command_number},{commandName},{param1},{param2},{param3}>'
            self.command_log.update({self.command_number:self.new_signal})
            self.command_number += 1
        elif timeout > 100:
            print('-COMMAND FAILED TO SEND-')
        else:
            time.sleep(0.2)
            print(f'---Waiting for Com:{timeout}---')
            timeout += 1
            self.generate_command(commandName,param1,param2,param3,timeout=timeout)
        return

    def set_relative_coordinates(self,x,y,z):
        self.generate_command('RELATIVE_XYZ',x,y,z)
        return
    
    def set_absolute_coordinates(self,x,y,z):
        self.generate_command('ABSOLUTE_XYZ',x,y,z)
        return
    
    def print_droplets(self,droplet_count):
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
        return
    
    def gripper_off(self):
        self.generate_command('GRIPPER_OFF',0,0,0)
        return
    
    def enable_motors(self):
        self.generate_command('ENABLE_MOTORS',0,0,0)
        return
    
    def disable_motors(self):
        self.generate_command('DISABLE_MOTORS',0,0,0)
        return
    
    def home_all(self):
        self.generate_command('HOME_ALL',0,0,0)
        return
    
    def regulate_pressure(self):
        self.generate_command('REGULATE_P',0,0,0)
        return
    
    def unregulate_pressure(self):
        self.generate_command('UNREGULATE_P',0,0,0)
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
                print('Arduino is:',self.ard_state)
                key = self.get_current_key()
                print(key)
                if key == Key.up:
                    self.set_relative_coordinates(1000,0,0)
                elif key == Key.down:
                    self.set_relative_coordinates(-1000,0,0)
                elif key == Key.left:
                    self.set_relative_coordinates(0,1000,0)
                elif key == Key.right:
                    self.set_relative_coordinates(0,-1000,0)
                elif key == 'k':
                    self.set_relative_coordinates(0,0,-1000)
                elif key == 'm':
                    self.set_relative_coordinates(0,0,1000)
                # elif key == 'R':
                #     self.new_signal = '<resetXYZ>'
                
                elif key == 'H':
                    self.home_all()
                elif key == 'D':
                    self.set_absolute_coordinates(-4500,3500,-35000)
                elif key == 'F':
                    self.set_absolute_coordinates(-5000,7000,-20000)
                # elif key == 'T':
                #     self.new_signal = '<absoluteXYZ,-5000,2000,-29000>'

                elif key == 'c':
                    self.print_droplets(5)
                elif key == 'v':
                    self.print_droplets(20)
                elif key == 'b':
                    self.print_droplets(100)

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
                # elif key == '{':
                #     self.new_signal = '<resetP>'

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


                elif key == 'S':
                    self.toggle_log()
                elif key == 'L':
                    self.initiate_log()

                elif key == 'q':
                    self.disable_motors()
                    time.sleep(0.5)
                    self.gripper_off()
                    time.sleep(0.5)
                    print('\n---Quitting---\n')
                    return
            else:
                print('---Arduino is:',self.ard_state)
                time.sleep(0.5)


if __name__ == '__main__':
    platform = Platform()
    platform.drive_platform()
    print('Trying to quit')
    platform.disconnect_all()
    print('Ended all threads, close window')
