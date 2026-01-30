#!/usr/bin/env python3
import sys, struct, argparse
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QMessageBox, QLabel
)
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import QThread, Signal, Slot
import serial, time, re

START_BYTE = 0xAA
CMD_STATUS = 0x02

# TLV tag constants; must match firmware
TAG_LED_TOTAL     = 0x10
TAG_LED_REMAIN    = 0x11
TAG_PRINT_P       = 0x14
TAG_REFUEL_P      = 0x15
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
    TAG_PRINT_P:      ("print_pressure",2, False),
    TAG_REFUEL_P:     ("refuel_pressure",2,False),
    TAG_X_POS:        ("pos_x",        4, True),
    TAG_Y_POS:        ("pos_y",        4, True),
    TAG_Z_POS:        ("pos_z",        4, True),
    TAG_P_POS:        ("pos_p",        4, True),
    TAG_R_POS:        ("pos_r",        4, True),
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

class ShortcutManager:
    """Manage application shortcuts and their descriptions."""
    def __init__(self, parent):
        self.parent = parent
        self.shortcuts = []

    def add_shortcut(self, key_sequence, description, callback):
        """Add a shortcut to the application and store its description."""
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent, activated=callback)
        self.shortcuts.append((key_sequence, description))
        return shortcut

    def get_shortcuts(self):
        """Return a list of shortcuts and their descriptions."""
        return self.shortcuts

class LogReader(QThread):
    lineReceived = Signal(str)

    def __init__(self, baud=115200, parent=None):
        super().__init__(parent)
        log_port = "/dev/ttyUSB0"
        self.ser = serial.Serial(log_port, baud, timeout=1)
        self._running = True
        print(f"LogReader initialized on {log_port} at {baud} baud")

    def run(self):
        """Continuously read lines and emit them."""
        while self._running:
            try:
                # while True:
                #     packet = self.ser.read(8)
                #     if len(packet) < 8:
                #         continue
                #     sync       = packet[0]
                #     slave_addr = packet[1]
                #     reg        = packet[2]
                #     data_bytes = packet[3:7]
                #     crc        = packet[7]
                #     data_int   = int.from_bytes(data_bytes, 'big')
                #     bits = ' '.join(f'{b:08b}' for b in packet)
                #     print(f"Raw bits: {bits}")
                #     print(f"  Sync:     0x{sync:02X}")
                #     print(f"  Slave:    0x{slave_addr:02X}")
                #     print(f"  Register: 0x{reg:02X}")
                #     print(f"  Data:     0x{data_int:08X}")
                #     print(f"  CRC:      0x{crc:02X}\n")
                line = self.ser.readline()
                if line:
                    # decode to str, strip trailing CR/LF
                    text = line.decode('ascii',errors="ignore").rstrip("\r\n")
                    # text = re.sub(r'[^\x20-\x7E]', '', text)  # remove ANSI escape codes
                    # text = line.decode(errors="replace").rstrip("\r\n")
                    self.lineReceived.emit(text)
            except serial.SerialException:
                break

    def stop(self):
        self._running = False
        self.wait(200)
        if self.ser.is_open:
            self.ser.close()

class ReaderThread(QThread):
    status_received = Signal(dict)  # emit parsed status data
    error = Signal(str)

    def __init__(self, ser):
        super().__init__()
        self.ser = ser

    def read_TLV(self,payload):
        """Read TLV (Type-Length-Value) encoded data from the payload."""
        i = 0
        while i < len(payload):
            tag    = payload[i];    i+=1
            length = payload[i];    i+=1
            data   = payload[i:i+length]
            i      += length

            if tag == TAG_LED_TOTAL:
                tot = int.from_bytes(data, 'little')
            elif tag == TAG_X_POS:
                x = int.from_bytes(data, 'little', signed=True)

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

class MainWindow(QWidget):
    def __init__(self, port, baud):
        super().__init__()
        self.setWindowTitle("Octopus Comm GUI")
        self.resize(600, 400)
        self.shortcut_manager = ShortcutManager(self)
        self.setup_shortcuts()

        # serial
        try:
            self.ser = serial.Serial('/dev/ttyAMA0', baud, timeout=0.1)
        except Exception as e:
            QMessageBox.critical(self, "Serial Error", str(e))
            sys.exit(1)

        self.seq = 0

        # UI
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("cmd seq p1 p2 p3 (e.g. 0x01 0x00 100 200 0)")
        self.send_btn = QPushButton("Send")

        self.cmd_log = QTextEdit()
        self.cmd_log.setReadOnly(True)

        self.logView = QTextEdit(readOnly=True)

        h = QHBoxLayout()
        h.addWidget(self.cmd_edit)
        h.addWidget(self.send_btn)

        v = QVBoxLayout(self)
        v.addLayout(h)
        v.addWidget(self.cmd_log)
        v.addWidget(self.logView)

        # Create a status display using the TAG_MAP to dynamically create fields that update with status data
        # This should be a Qlabel for each Tag in the TAG_MAP
        # self.status_box = QVBoxLayout(self)
        self.status_labels = {}
        for tag, (name, length, signed) in TAG_MAP.items():
            label = QLabel(f"{name}: N/A")
            self.status_labels[name] = label
            v.addWidget(label)
        # v.addLayout(self.status_box)

        self.send_btn.clicked.connect(self.on_send)

        # reader thread
        self.thread = ReaderThread(self.ser)
        self.thread.status_received.connect(self.update_status)
        self.thread.error.connect(self.on_error)
        self.thread.start()

        # start log-reader thread
        self.reader = LogReader(baud)
        self.reader.lineReceived.connect(self.append_line)
        self.reader.start()

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', lambda: self.on_send(manual="0x03 0 5000 30000"))
        self.shortcut_manager.add_shortcut('Right', 'Move right', lambda: self.on_send(manual="0x03 1 5000 30000"))
        self.shortcut_manager.add_shortcut('Up', 'Move forward', lambda: self.on_send(manual="0x02 0 5000 30000"))
        self.shortcut_manager.add_shortcut('Down', 'Move backward', lambda: self.on_send(manual="0x02 1 5000 30000"))
        self.shortcut_manager.add_shortcut('k', 'Move up', lambda: self.on_send(manual="0x04 0 5000 30000"))
        self.shortcut_manager.add_shortcut('m', 'Move down', lambda: self.on_send(manual="0x04 1 5000 30000"))
        self.shortcut_manager.add_shortcut('Return', 'Send command', self.on_send)
        self.shortcut_manager.add_shortcut('h', 'Home X', lambda: self.on_send(manual="0x05 1 10000 1000"))
        self.shortcut_manager.add_shortcut('t', 'Dispense 10', lambda: self.on_send(manual="0x0B 10 20"))
        self.shortcut_manager.add_shortcut('Shift+T', 'Test Sequence', lambda: self.test_sequence())
        self.shortcut_manager.add_shortcut('Shift+G', 'Open Gripper', lambda: self.on_send(manual="0x06 0"))
        self.shortcut_manager.add_shortcut('g', 'Close Gripper', lambda: self.on_send(manual="0x07 0"))
        self.shortcut_manager.add_shortcut('Esc','Pause', lambda: self.on_send(manual="0xF0 0 0 0"))
        self.shortcut_manager.add_shortcut('Shift+R', 'Resume', lambda: self.on_send(manual="0xF1 0 0 0"))
        self.shortcut_manager.add_shortcut('Shift+C', 'Clear Queue', lambda: self.on_send(manual="0xF2 0 0 0"))
    
    def test_sequence(self):
        """Send a predefined sequence of commands for testing."""
        commands = [
            "0x0B 100 20",
            "2 0 10000 10000",
            "0x0B 100 20",
            "2 1 10000 10000"
        ]
        for cmd in commands:
            self.on_send(manual=cmd)
            time.sleep(0.1)

    @Slot(str)
    def append_line(self, text):
        """Append a new line of log text."""
        self.logView.append(text)

    @Slot()
    def on_send(self, manual=False):
        if not manual:
            text = self.cmd_edit.text().strip()
        else:
            text = manual.strip()
        if not text:
            return
        parts = text.split()
        if len(parts) < 2:
            self.append_cmd_log("! need at least cmd and seq")
            return
        try:
            cmd = int(parts[0], 0)
            seq = self.seq
            p1  = int(parts[1], 0) if len(parts)>1 else 0
            p2  = int(parts[2], 0) if len(parts)>2 else 0
            p3  = int(parts[3], 0) if len(parts)>3 else 0
        except ValueError:
            self.append_log("! parse error, use ints or 0xhex")
            return

        payload = struct.pack(">BBHHH",
            cmd & 0xFF, 
            seq & 0xFF,
            p1 & 0xFFFF,
            p2 & 0xFFFF,
            p3 & 0xFFFF
        )
        header = bytes([START_BYTE, len(payload)])
        crc    = crc16_x25(payload)
        tail   = struct.pack("<H", crc)
        frame  = header + payload + tail

        try:
            self.ser.write(frame)
            self.append_cmd_log(f">>> {frame.hex()}  cmd=0x{cmd:02X} seq={seq} p1={p1} p2={p2} p3={p3} crc=0x{crc:04X}")
            self.seq = (self.seq + 1) & 0xFF
        except Exception as e:
            self.append_log(f"! write error: {e}")

    # @Slot(str)
    # def append_log(self, line):
    #     self.log.append(line)

    @Slot(dict)
    def update_status(self, data):
        """Update the status display with new data."""
        if isinstance(data, str):
            self.append_cmd_log(data)
            return

        for tag, value in data.items():
            label = self.status_labels.get(tag)
            if label:
                label.setText(f"{tag}: {value}")


    @Slot(str)
    def append_cmd_log(self, line):
        self.cmd_log.append(line)

    @Slot(str)
    def on_error(self, msg):
        QMessageBox.critical(self, "Reader Error", msg)

    def closeEvent(self, event):
        # clean up thread + serial
        self.thread.requestInterruption()
        self.thread.wait(200)
        try:
            self.ser.close()
        except:
            pass
        super().closeEvent(event)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default='/dev/ttyAMA0', help="serial port, e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    w = MainWindow(args.port, args.baud)
    w.show()
    sys.exit(app.exec())