import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
from PySide6.QtWidgets import QApplication

from collections import deque

import serial
import re
import json
import cv2
import numpy as np
import pandas as pd
import os
import joblib
try:
    from picamera2 import Picamera2
    import gpiod
except ImportError:
    print("Running on a non-Raspberry Pi system or missing required libraries. Camera and GPIO functionality will be unavailable.")
    Picamera2 = None
    gpiod = None

START_BYTE = 0xAA
CMD_STATUS = 0x02

# TLV tag constants; must match firmware
TAG_LED_TOTAL     = 0x10
TAG_LED_REMAIN    = 0x11
TAG_PRINT_P       = 0x12
TAG_REFUEL_P      = 0x13
TAG_X_POS         = 0x20
TAG_Y_POS         = 0x21
TAG_Z_POS         = 0x22
TAG_P_POS         = 0x23
TAG_R_POS         = 0x24
TAG_DROP_TOTAL    = 0x30
TAG_DROP_REMAIN   = 0x31
TAG_ACTIVE_P      = 0x40
TAG_ACTIVE_R      = 0x41
TAG_CMD_DEPTH     = 0x50

# Map tags → (field name, length_in_bytes, signed?)
TAG_MAP = {
    TAG_LED_TOTAL:    ("led_total",    2, False),
    TAG_LED_REMAIN:   ("led_remain",   2, False),
    TAG_PRINT_P:      ("Pressure_P",2, False),
    TAG_REFUEL_P:     ("Pressure_R",2,False),
    TAG_X_POS:        ("X",        4, True),
    TAG_Y_POS:        ("Y",        4, True),
    TAG_Z_POS:        ("Z",        4, True),
    TAG_P_POS:        ("P",        4, True),
    TAG_R_POS:        ("R",        4, True),
    TAG_DROP_TOTAL:   ("drop_total",   4, False),
    TAG_DROP_REMAIN:  ("drop_remain",  4, False),
    TAG_ACTIVE_P:     ("print_active", 2, False),
    TAG_ACTIVE_R:     ("refuel_active",2, False),
    TAG_CMD_DEPTH:    ("cmd_depth",  4, False),
}

def crc16_x25(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def parse_tlv_payload(payload: bytes) -> dict:
    """
    Walk the payload as tag‐len‐value, return a dict name->value.
    Unknown tags are skipped.
    """
    idx = 0
    result = {}
    while idx + 2 <= len(payload):
        tag    = payload[idx];    idx += 1
        length = payload[idx];    idx += 1
        if idx + length > len(payload):
            break  # malformed/truncated
        raw = payload[idx:idx+length]
        idx += length

        entry = TAG_MAP.get(tag)
        if not entry:
            continue  # unknown tag
        name, expected_len, signed = entry
        if expected_len != length:
            # length mismatch; skip or handle as error
            continue

        value = int.from_bytes(raw, byteorder="little", signed=signed)
        result[name] = value

    return result

class StatusThread(QThread):
    status_received = Signal(dict)  # emit parsed status data
    error = Signal(str)

    def __init__(self, ser):
        super().__init__()
        self.ser = ser

    def run(self):
        try:
            while not self.isInterruptionRequested():
                # print("Interrupted:", self.isInterruptionRequested())
                b = self.ser.read(1)
                if not b or b[0] != START_BYTE:
                    print("Start byte not received, waiting...")
                    continue
                L = self.ser.read(1)
                if len(L)!=1:
                    print("Length byte not received, waiting...")
                    continue
                length = L[0]
                payload = self.ser.read(length)
                if len(payload)!=length:
                    print("Payload length mismatch, waiting...")
                    continue
                tail = self.ser.read(2)
                if len(tail)!=2:
                    print("CRC tail not received, waiting...")
                    continue
                rec_crc = tail[0] | (tail[1]<<8)
                if rec_crc != crc16_x25(payload):
                    self.status_received.emit("! CRC ERROR on incoming frame")
                    continue
                cmd = payload[0]
                if cmd == CMD_STATUS and len(payload)>=9:
                    # instead of unpacking fixed fields, do:
                    data = parse_tlv_payload(payload[1:])  # skip the CMD byte
                    # now `data` is a dict like {"led_total": 123, "pos_x": 456, …}
                    # hand it off to your UI:
                    self.status_received.emit(data)

                else:
                    # ignore or show other async messages
                    pass
        except Exception as e:
            self.error.emit(f"Reader thread error: {e}")


class Machine(QObject):
    """
    Class for the machine object. This class is responsible for 
    sending and receiving data from the machine and organizing
    the command queue.
    """
    status_updated = Signal(dict)  # Signal to emit status updates
    def __init__(self):
        super().__init__()
        self.baud = 115200  # Default baud rate for serial communication
        self.ser = None

        try:
            self.ser = serial.Serial('/dev/ttyAMA0', self.baud, timeout=0.1)
        except Exception as e:
            print(f"Failed to open serial port: {e}")

        self.status_thread = StatusThread(self.ser)
        self.status_thread.status_updated.connect(self.update_status)
        self.status_thread.error.connect(self.on_error)
        self.status_thread.start()
