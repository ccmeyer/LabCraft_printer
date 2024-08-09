import sys
from PySide6.QtWidgets import QApplication
from Machine_MVC import Machine
from Model import Model
from Controller import Controller
from View import View
from PySide6.QtCore import QTimer, QPointF
from PySide6.QtWidgets import QStyleFactory
from PySide6.QtGui import QPalette, QColor

def set_dark_theme(app):
    app.setStyle(QStyleFactory.create("Fusion"))

    dark_palette = QPalette()
    
    # Base color
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))  # red
    
    # Link colors
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.LinkVisited, QColor(42, 130, 218))
    
    # Highlight color
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))  # black

    app.setPalette(dark_palette)

def main():
    app = QApplication(sys.argv)

    # Initialize components
    machine = Machine()
    model = Model()
    controller = Controller(machine, model)
    controller.connect_to_machine()

    set_dark_theme(app)
    view = View(model,controller)

    # Show the main window
    view.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()