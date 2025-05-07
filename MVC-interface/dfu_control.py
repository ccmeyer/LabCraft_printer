#!/usr/bin/env python3
import gpiod
import time

BOOT_PIN, RESET_PIN = 16, 20
PULSE_DURATION = 5

class DfuControl:
    def __init__(self):
        self.chip = gpiod.Chip('gpiochip0')
        self.boot_line = self.chip.get_line(BOOT_PIN)
        self.reset_line = self.chip.get_line(RESET_PIN)

        # Request lines
        self.boot_line.request(consumer='dfu_control', type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
        self.reset_line.request(consumer='dfu_control', type=gpiod.LINE_REQ_DIR_OUT, default_val=0)

    def enter_dfu_mode(self):
        print("Entering DFU mode...")
        self.boot_line.set_value(1)
        self.reset_line.set_value(1)
        time.sleep(PULSE_DURATION)
        self.reset_line.set_value(0)
        print("DFU mode activated.")

    def exit_dfu_mode(self):
        print("Exiting DFU mode...")
        self.boot_line.set_value(0)
        time.sleep(0.5)
        self.reset_line.set_value(1)
        time.sleep(PULSE_DURATION)
        self.reset_line.set_value(0)
        print("DFU mode deactivated.")

    def cleanup(self):
        print("Cleaning up GPIO lines...")
        self.boot_line.release()
        self.reset_line.release()
        self.chip.close()
        print("Cleanup complete.")

if __name__ == "__main__":
    dfu_control = DfuControl()
    try:
        dfu_control.enter_dfu_mode()
        # Wait for user input to exit DFU mode
        input("Press Enter to exit DFU mode...")
        # Optionally, you can add a timeout here
        # time.sleep(10)  # Wait for 10 seconds before exiting DFU mode
        dfu_control.exit_dfu_mode()
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        dfu_control.cleanup()
# This script controls the GPIO pins for entering and exiting DFU mode.
# It uses the gpiod library to manage GPIO lines and perform the necessary operations.
# The script can be run directly to test the functionality.
