import sys
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStyleFactory
from PySide6.QtGui import QPalette, QColor, QPixmap
import os

def set_dark_theme(app):
    app.setStyle(QStyleFactory.create("Fusion"))

    dark_palette = QPalette()
    
    # Base color
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(50,50,50))  # white
    dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))  # red
    
    # Link colors
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.LinkVisited, QColor(42, 130, 218))
    
    # Highlight color
    dark_palette.setColor(QPalette.Highlight, QColor(50, 50, 50))
    dark_palette.setColor(QPalette.HighlightedText, QColor(150, 150, 150))

    app.setPalette(dark_palette)

    app.setStyleSheet("""
        QLabel {
            border-radius: 5px;  /* Rounded corners for QLabel */
        }
    """)

def main():
    app = QApplication(sys.argv)

    # Create splash screen
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(script_dir, 'Presets','LabCraft_logo.png')
    pixmap = QPixmap(logo_path)  # Replace with your logo image path
    splash = QSplashScreen(pixmap)
    splash.show()

    from Machine_MVC import Machine
    from Model import Model
    from Controller import Controller
    from View import MainWindow

    # Initialize components
    model = Model()
    machine = Machine(model)
    controller = Controller(machine, model)

    set_dark_theme(app)
    view = MainWindow(model,controller)

    # Delay for the splash screen to simulate loading tasks
    QTimer.singleShot(100, lambda: (splash.finish(view), view.show()))  # 2000 ms = 2 seconds


    # # Show the main window
    # view.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    print("Starting application...")
    main()