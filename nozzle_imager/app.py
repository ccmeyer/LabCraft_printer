# app.py
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QGridLayout, QVBoxLayout, QHBoxLayout
from PySide6.QtGui import QImage, QPixmap, QColor, QPalette
from PySide6.QtCore import QTimer

import numpy as np
import cv2

from camera_pi import RefuelCamera
from nozzle_analyzer import analyze_nozzle_from_frame, UM_PER_PX

# -------- theme (your dark theme) --------
def set_dark_theme(app):
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(50,50,50))
    dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.LinkVisited, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(50, 50, 50))
    dark_palette.setColor(QPalette.HighlightedText, QColor(150, 150, 150))
    app.setPalette(dark_palette)
    app.setStyleSheet("QLabel { border-radius: 5px; }")

# -------- helpers --------
def np_to_qimage(img_bgr):
    """Convert BGR/Gray numpy image to QImage."""
    if img_bgr.ndim == 2:
        h, w = img_bgr.shape
        qimg = QImage(img_bgr.data, w, h, w, QImage.Format_Grayscale8)
        return qimg
    h, w, ch = img_bgr.shape
    bytes_per_line = ch * w
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

# -------- main window --------
class NozzleApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nozzle Analyzer")
        self.resize(1200, 800)

        # camera
        self.cam = RefuelCamera()
        self.cam.start_camera()

        # UI
        self.live_label = QLabel("Live")
        self.live_label.setMinimumSize(480, 360)
        self.live_label.setAlignment(QtCore.Qt.AlignCenter)
        self.live_label.setStyleSheet("background:#202020")

        self.annot_label = QLabel("Annotated (after Analyze)")
        self.annot_label.setMinimumSize(480, 360)
        self.annot_label.setAlignment(QtCore.Qt.AlignCenter)
        self.annot_label.setStyleSheet("background:#202020")

        self.analyze_btn = QPushButton("Analyze Nozzle")
        self.analyze_btn.clicked.connect(self.analyze_current_frame)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)

        left_box = QVBoxLayout()
        left_box.addWidget(self.analyze_btn)
        left_box.addWidget(self.status_label)
        left_box.addStretch(1)

        right_box = QVBoxLayout()
        right_box.addWidget(self.live_label)
        right_box.addWidget(self.annot_label)

        grid = QGridLayout()
        grid.addLayout(left_box, 0, 0, 2, 1)
        grid.addLayout(right_box, 0, 1, 2, 1)
        self.setLayout(grid)

        # timer to update live view
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_live)
        self.timer.start(150)  # ms

        self.last_frame = None

    # ---- camera preview ----
    def update_live(self):
        frame = self.cam.capture_image()
        if frame is None:
            return
        self.last_frame = frame
        qimg = np_to_qimage(frame)
        self.live_label.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.live_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    # ---- analysis ----
    def analyze_current_frame(self):
        if self.last_frame is None:
            self.status_label.setText("No frame yet.")
            return
        try:
            overlay_bgr, results, _roi = analyze_nozzle_from_frame(self.last_frame, um_per_px=UM_PER_PX)
            # show annotated ROI
            qimg = np_to_qimage(overlay_bgr)
            self.annot_label.setPixmap(QPixmap.fromImage(qimg).scaled(
                self.annot_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

            txt = (f"Diameter: {results['diameter_um']:.2f} µm  "
                   f"C_io: {results['circularity_io']:.3f}  "
                   f"(r_in={results['r_in_px']:.1f}px, r_out={results['r_out_px']:.1f}px)")
            self.status_label.setText(txt)
        except Exception as e:
            self.status_label.setText(f"Analysis failed: {e}")

    def closeEvent(self, ev):
        try:
            self.timer.stop()
        except Exception:
            pass
        self.cam.stop_camera()
        super().closeEvent(ev)

# -------- entry point --------
def main():
    app = QApplication(sys.argv)
    set_dark_theme(app)
    w = NozzleApp()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
