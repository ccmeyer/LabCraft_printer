# app.py
import sys
import re
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import cv2

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QPalette, QColor, QImage, QPixmap, QTextCursor
from PySide6.QtCore import QTimer

from camera_pi import CaptureCamera


# -----------------------------
# Dark theme (same vibe as yours)
# -----------------------------
def set_dark_theme(app: QtWidgets.QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(53, 53, 53))
    pal.setColor(QPalette.WindowText, QColor(255, 255, 255))
    pal.setColor(QPalette.Base, QColor(25, 25, 25))
    pal.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    pal.setColor(QPalette.ToolTipBase, QColor(50, 50, 50))
    pal.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    pal.setColor(QPalette.Text, QColor(255, 255, 255))
    pal.setColor(QPalette.Button, QColor(53, 53, 53))
    pal.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    pal.setColor(QPalette.BrightText, QColor(255, 0, 0))
    pal.setColor(QPalette.Link, QColor(42, 130, 218))
    pal.setColor(QPalette.LinkVisited, QColor(42, 130, 218))
    pal.setColor(QPalette.Highlight, QColor(50, 50, 50))
    pal.setColor(QPalette.HighlightedText, QColor(150, 150, 150))
    app.setPalette(pal)
    app.setStyleSheet("QLabel { border-radius: 5px; }")


# -----------------------------
# Robust NumPy -> QImage
# -----------------------------
def np_to_qimage(img: np.ndarray) -> QImage:
    """Robust NumPy -> QImage. Supports gray uint8 (HxW), BGR uint8 (HxWx3), BGRA (HxWx4)."""
    if img is None:
        return QImage()

    # Grayscale
    if img.ndim == 2:
        img8 = img if img.dtype == np.uint8 else np.clip(img, 0, 255).astype(np.uint8)
        if not img8.flags["C_CONTIGUOUS"]:
            img8 = np.ascontiguousarray(img8)
        h, w = img8.shape
        qimg = QImage(img8.data, w, h, int(img8.strides[0]), QImage.Format_Grayscale8)
        return qimg.copy()

    # BGR -> RGB
    if img.ndim == 3 and img.shape[2] == 3:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if not rgb.flags["C_CONTIGUOUS"]:
            rgb = np.ascontiguousarray(rgb)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format_RGB888)
        return qimg.copy()

    # BGRA -> RGBA
    if img.ndim == 3 and img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        if not rgba.flags["C_CONTIGUOUS"]:
            rgba = np.ascontiguousarray(rgba)
        h, w, _ = rgba.shape
        qimg = QImage(rgba.data, w, h, int(rgba.strides[0]), QImage.Format_RGBA8888)
        return qimg.copy()

    return QImage()


# -----------------------------
# Helpers: naming + replicate index
# -----------------------------
_INVALID_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_basename(name: str) -> str:
    """
    Make a safe base filename. Keeps letters/numbers/._- ; converts whitespace to underscore;
    strips leading/trailing separators.
    """
    s = name.strip().replace(" ", "_")
    s = _INVALID_CHARS.sub("_", s)
    s = s.strip("._-")
    return s


def next_replicate_index(out_dir: Path, base_name: str, ext: str) -> int:
    """
    Find the next available replicate index for base_name in out_dir.
    Looks for files like base_#.ext (also tolerates base_###.json next to them).
    """
    # Example match: sample_12.png
    pattern = re.compile(rf"^{re.escape(base_name)}_(\d+){re.escape(ext)}$", re.IGNORECASE)

    max_n = 0
    if out_dir.exists():
        for p in out_dir.iterdir():
            if not p.is_file():
                continue
            m = pattern.match(p.name)
            if m:
                try:
                    max_n = max(max_n, int(m.group(1)))
                except ValueError:
                    pass
    return max_n + 1


def iso_now_local() -> str:
    # ISO timestamp with local timezone offset (no dependency on tzlocal)
    now = datetime.now().astimezone()
    return now.isoformat(timespec="seconds")


# -----------------------------
# Main App
# -----------------------------
class CaptureApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LabCraft — Pi Camera Capture")
        self.resize(1200, 800)

        # camera
        self.cam = CaptureCamera()
        self.cam.start_camera()

        # Right side labels
        self.preview_label = QtWidgets.QLabel("Preview (live)")
        self.preview_label.setMinimumSize(520, 390)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#202020")

        self.captured_label = QtWidgets.QLabel("Last capture")
        self.captured_label.setMinimumSize(520, 390)
        self.captured_label.setAlignment(QtCore.Qt.AlignCenter)
        self.captured_label.setStyleSheet("background:#202020")

        # --- Left side controls ---
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignLeft)

        # Output directory row (line edit + browse button)
        self.dir_le = QtWidgets.QLineEdit()
        default_dir = Path.home() / "captures"
        self.dir_le.setText(str(default_dir))

        self.browse_btn = QtWidgets.QPushButton("Browse…")
        self.browse_btn.clicked.connect(self.browse_dir)

        dir_row = QtWidgets.QHBoxLayout()
        dir_row.addWidget(self.dir_le, 1)
        dir_row.addWidget(self.browse_btn)
        form.addRow("Output dir", dir_row)

        # Base image name
        self.name_le = QtWidgets.QLineEdit()
        self.name_le.setPlaceholderText("e.g. nozzle_A")
        form.addRow("Image name", self.name_le)

        # File format
        self.format_cb = QtWidgets.QComboBox()
        self.format_cb.addItems([".png", ".jpg"])
        self.format_cb.setCurrentText(".png")
        self.format_cb.currentTextChanged.connect(self.refresh_next_name)
        form.addRow("Format", self.format_cb)

        # JPEG quality if .jpg (optional)
        self.jpg_quality = QtWidgets.QSpinBox()
        self.jpg_quality.setRange(10, 100)
        self.jpg_quality.setValue(95)
        self.jpg_quality.setEnabled(False)
        form.addRow("JPG quality", self.jpg_quality)

        self.format_cb.currentTextChanged.connect(self._on_format_changed)

        # Next filename preview
        self.next_name_label = QtWidgets.QLabel("—")
        self.next_name_label.setWordWrap(True)
        form.addRow("Next file", self.next_name_label)

        # Buttons
        self.capture_btn = QtWidgets.QPushButton("Capture (Space)")
        self.capture_btn.clicked.connect(self.capture_clicked)

        self.open_dir_btn = QtWidgets.QPushButton("Open Folder")
        self.open_dir_btn.clicked.connect(self.open_folder)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.capture_btn, 1)
        btn_row.addWidget(self.open_dir_btn, 0)

        # Log + status
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(240)
        self.log.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        mono = QtGui.QFont("Monospace")
        mono.setStyleHint(QtGui.QFont.TypeWriter)
        self.log.setFont(mono)

        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)

        left_box = QtWidgets.QVBoxLayout()
        left_box.addLayout(form)
        left_box.addLayout(btn_row)
        left_box.addWidget(self.log)
        left_box.addWidget(self.status_label)
        left_box.addStretch(1)

        right_box = QtWidgets.QVBoxLayout()
        right_box.addWidget(self.preview_label)
        right_box.addWidget(self.captured_label)

        layout = QtWidgets.QGridLayout()
        layout.addLayout(left_box, 0, 0, 2, 1)
        layout.addLayout(right_box, 0, 1, 2, 1)
        self.setLayout(layout)

        # Buffers
        self.last_frame = None
        self.last_meta = {}

        # Timer for preview
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)
        self.timer.start(80)  # 50–120ms typically fine

        # Hotkeys
        QtGui.QShortcut(QtGui.QKeySequence("Space"), self, activated=self.capture_clicked)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+L"), self, activated=self.dir_le.setFocus)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+N"), self, activated=self.name_le.setFocus)

        # update next-name when user types
        self.dir_le.textChanged.connect(self.refresh_next_name)
        self.name_le.textChanged.connect(self.refresh_next_name)

        self.refresh_next_name()

    def _on_format_changed(self, ext: str):
        self.jpg_quality.setEnabled(ext.lower() == ".jpg")
        self.refresh_next_name()

    # ---- preview ----
    def update_preview(self):
        frame, meta = self.cam.get_frame()
        if frame is None:
            return
        self.last_frame = frame
        self.last_meta = meta or {}

        qimg = np_to_qimage(frame)
        self.preview_label.setPixmap(
            QPixmap.fromImage(qimg).scaled(
                self.preview_label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )

    # ---- UI helpers ----
    def append_log(self, text: str):
        self.log.appendPlainText(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output directory", self.dir_le.text())
        if d:
            self.dir_le.setText(d)

    def open_folder(self):
        out_dir = Path(self.dir_le.text()).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(out_dir)))

    def refresh_next_name(self):
        out_dir = Path(self.dir_le.text()).expanduser()
        base = sanitize_basename(self.name_le.text())
        ext = self.format_cb.currentText()

        if not base:
            self.next_name_label.setText("Enter an image name (left).")
            return

        n = next_replicate_index(out_dir, base, ext)
        self.next_name_label.setText(str(out_dir / f"{base}_{n}{ext}"))

    # ---- capture + save ----
    def capture_clicked(self):
        if self.last_frame is None:
            self.status_label.setText("No frame yet.")
            return

        out_dir = Path(self.dir_le.text()).expanduser()
        base = sanitize_basename(self.name_le.text())
        ext = self.format_cb.currentText().lower()

        if not base:
            self.status_label.setText("Please enter an image name.")
            return

        try:
            out_dir.mkdir(parents=True, exist_ok=True)

            n = next_replicate_index(out_dir, base, ext)
            img_path = out_dir / f"{base}_{n}{ext}"
            json_path = out_dir / f"{base}_{n}.json"
            jsonl_path = out_dir / "captures.jsonl"

            # Save image
            params = []
            if ext == ".jpg":
                params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpg_quality.value())]

            ok = cv2.imwrite(str(img_path), self.last_frame, params)
            if not ok:
                raise RuntimeError(f"cv2.imwrite failed for {img_path}")

            # Build metadata
            meta = {
                "timestamp": iso_now_local(),
                "image_file": img_path.name,
                "image_path": str(img_path.resolve()),
                "directory": str(out_dir.resolve()),
                "base_name": base,
                "replicate_index": n,
                "format": ext,
                "shape_hwc": list(self.last_frame.shape),
                "dtype": str(self.last_frame.dtype),
                "camera_backend": self.cam.backend,
                "camera_metadata": self.last_meta or {},
            }

            # Write sidecar JSON
            json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            # Append to JSONL index
            with jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(meta) + "\n")

            # Show captured image on bottom-right
            qimg = np_to_qimage(self.last_frame)
            self.captured_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    self.captured_label.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            )

            self.status_label.setText(f"Saved: {img_path.name} (+ {json_path.name})")
            self.append_log(f"{meta['timestamp']} | saved {img_path.name}")

            # Update next name
            self.refresh_next_name()

        except Exception as e:
            self.status_label.setText(f"Capture failed: {e}")
            self.append_log(f"ERROR: {e}")

    def closeEvent(self, ev: QtGui.QCloseEvent):
        self.timer.stop()
        self.cam.stop_camera()
        super().closeEvent(ev)


def main():
    app = QtWidgets.QApplication(sys.argv)
    set_dark_theme(app)
    w = CaptureApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()