# app.py
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QPalette, QColor, QImage, QPixmap
from PySide6.QtCore import QTimer

import numpy as np
import cv2

from camera_pi import RefuelCamera
from nozzle_analyzer import (
    analyze_nozzle_from_roi,
    detect_field_robust, crop_central_roi,
    UM_PER_PX, DEFAULT_LO, DEFAULT_HI, SEED_WIN_FRAC, GRID_N
)

# ---- dark theme (your styling) ----
def set_dark_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(53,53,53))
    pal.setColor(QPalette.WindowText, QColor(255,255,255))
    pal.setColor(QPalette.Base, QColor(25,25,25))
    pal.setColor(QPalette.AlternateBase, QColor(53,53,53))
    pal.setColor(QPalette.ToolTipBase, QColor(50,50,50))
    pal.setColor(QPalette.ToolTipText, QColor(255,255,255))
    pal.setColor(QPalette.Text, QColor(255,255,255))
    pal.setColor(QPalette.Button, QColor(53,53,53))
    pal.setColor(QPalette.ButtonText, QColor(255,255,255))
    pal.setColor(QPalette.BrightText, QColor(255,0,0))
    pal.setColor(QPalette.Link, QColor(42,130,218))
    pal.setColor(QPalette.LinkVisited, QColor(42,130,218))
    pal.setColor(QPalette.Highlight, QColor(50,50,50))
    pal.setColor(QPalette.HighlightedText, QColor(150,150,150))
    app.setPalette(pal)
    app.setStyleSheet("QLabel { border-radius: 5px; }")

def np_to_qimage(img):
    """Robust NumPy -> QImage. Works for gray (uint8 HxW) and BGR (HxWx3)."""
    if img is None:
        return QImage()

    # Grayscale
    if img.ndim == 2:
        img8 = img
        if img8.dtype != np.uint8:
            img8 = np.clip(img8, 0, 255).astype(np.uint8)
        if not img8.flags['C_CONTIGUOUS']:
            img8 = np.ascontiguousarray(img8)
        h, w = img8.shape
        qimg = QImage(img8.data, w, h, int(img8.strides[0]), QImage.Format_Grayscale8)
        return qimg.copy()  # detach from NumPy buffer

    # Color (BGR -> RGB)
    if img.ndim == 3 and img.shape[2] == 3:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if not rgb.flags['C_CONTIGUOUS']:
            rgb = np.ascontiguousarray(rgb)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format_RGB888)
        return qimg.copy()

    # BGRA fallback
    if img.ndim == 3 and img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        if not rgba.flags['C_CONTIGUOUS']:
            rgba = np.ascontiguousarray(rgba)
        h, w, _ = rgba.shape
        qimg = QImage(rgba.data, w, h, int(rgba.strides[0]), QImage.Format_RGBA8888)
        return qimg.copy()

    return QImage()

class NozzleApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nozzle Analyzer")
        self.resize(1200, 800)

        # camera
        self.cam = RefuelCamera()
        self.cam.start_camera()

        # UI elements
        self.preview_label = QtWidgets.QLabel("ROI preview")
        self.preview_label.setMinimumSize(520, 390)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#202020")

        self.annot_label = QtWidgets.QLabel("Annotated (after Analyze)")
        self.annot_label.setMinimumSize(520, 390)
        self.annot_label.setAlignment(QtCore.Qt.AlignCenter)
        self.annot_label.setStyleSheet("background:#202020")

        # --- parameter controls (labels left, spinboxes right)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignLeft)

        self.um_per_px = QtWidgets.QDoubleSpinBox()
        self.um_per_px.setDecimals(4); self.um_per_px.setRange(0.001, 10.0)
        self.um_per_px.setSingleStep(0.001); self.um_per_px.setValue(UM_PER_PX)
        form.addRow("µm / px", self.um_per_px)

        self.lo_sb = QtWidgets.QSpinBox(); self.lo_sb.setRange(0, 100); self.lo_sb.setValue(DEFAULT_LO)
        form.addRow("Flood lo", self.lo_sb)

        self.hi_sb = QtWidgets.QSpinBox(); self.hi_sb.setRange(0, 100); self.hi_sb.setValue(DEFAULT_HI)
        form.addRow("Flood hi", self.hi_sb)

        self.seed_win = QtWidgets.QDoubleSpinBox()
        self.seed_win.setDecimals(3); self.seed_win.setRange(0.05, 0.50)
        self.seed_win.setSingleStep(0.01); self.seed_win.setValue(SEED_WIN_FRAC)
        form.addRow("Seed window frac", self.seed_win)

        self.grid_n = QtWidgets.QSpinBox(); self.grid_n.setRange(3, 11); self.grid_n.setSingleStep(2); self.grid_n.setValue(GRID_N)
        form.addRow("Grid N (seeds/side)", self.grid_n)

        self.p_lo = QtWidgets.QSpinBox(); self.p_lo.setRange(0, 49); self.p_lo.setValue(5)
        form.addRow("IO low percentile", self.p_lo)

        self.p_hi = QtWidgets.QSpinBox(); self.p_hi.setRange(51, 100); self.p_hi.setValue(95)
        form.addRow("IO high percentile", self.p_hi)

        self.analyze_btn = QtWidgets.QPushButton("Analyze Nozzle")
        self.analyze_btn.clicked.connect(self.analyze_clicked)

        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)

        left_box = QtWidgets.QVBoxLayout()
        left_box.addLayout(form)
        left_box.addWidget(self.analyze_btn)
        left_box.addSpacing(10)
        left_box.addWidget(self.status_label)
        left_box.addStretch(1)

        right_box = QtWidgets.QVBoxLayout()
        right_box.addWidget(self.preview_label)
        right_box.addWidget(self.annot_label)

        layout = QtWidgets.QGridLayout()
        layout.addLayout(left_box, 0, 0, 2, 1)
        layout.addLayout(right_box, 0, 1, 2, 1)
        self.setLayout(layout)

        # timers & buffers
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)
        self.timer.start(50)  # ms

        self.last_roi = None    # grayscale
        self.last_roi_bgr = None  # for debug if needed

    def update_preview(self):
        """Show the FULL camera frame in the preview window."""
        frame = self.cam.capture_image()
        if frame is None:
            return
        self.last_frame = frame  # keep for analysis
        qimg = np_to_qimage(frame)
        self.preview_label.setPixmap(
            QPixmap.fromImage(qimg).scaled(
                self.preview_label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
        )

    # -------- live ROI preview instead of raw camera ----------
    # def update_preview_roi(self):
    #     frame = self.cam.capture_image()
    #     if frame is None:
    #         return
    #     gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    #     center, field_r = detect_field_robust(gray)
    #     roi = crop_central_roi(gray, center, field_r, roi_scale=0.62)
    #     roi = np.ascontiguousarray(roi)  # optional; np_to_qimage already handles it

    #     self.last_roi = roi
    #     qimg = np_to_qimage(roi)
    #     self.preview_label.setPixmap(QPixmap.fromImage(qimg).scaled(
    #         self.preview_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    # -------- run analysis using current parameters ----------
    def analyze_clicked(self):
        if self.last_frame is None:
            self.status_label.setText("No frame yet.")
            return
        try:
            # Crop ROI from the full frame, then analyze with the current tunables
            gray = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2GRAY)
            center, field_r = detect_field_robust(gray)
            roi = crop_central_roi(gray, center, field_r, roi_scale=0.62)

            overlay_bgr, results = analyze_nozzle_from_roi(
                roi,
                um_per_px=self.um_per_px.value(),
                lo=self.lo_sb.value(),
                hi=self.hi_sb.value(),
                seed_win_frac=self.seed_win.value(),
                grid_n=self.grid_n.value(),
                p_lo=self.p_lo.value(),
                p_hi=self.p_hi.value()
            )

            qimg = np_to_qimage(overlay_bgr)
            self.annot_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    self.annot_label.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )
            )

            txt = (f"Diameter: {results['diameter_um']:.2f} µm   "
                f"C_io: {results['circularity_io']:.3f}   "
                f"(r_in={results['r_in_px']:.1f}px, r_out={results['r_out_px']:.1f}px)")
            self.status_label.setText(txt)

        except Exception as e:
            self.status_label.setText(f"Analysis failed: {e}")
            
    def closeEvent(self, ev):
        self.timer.stop()
        self.cam.stop_camera()
        super().closeEvent(ev)

def main():
    app = QtWidgets.QApplication(sys.argv)
    set_dark_theme(app)
    w = NozzleApp()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
