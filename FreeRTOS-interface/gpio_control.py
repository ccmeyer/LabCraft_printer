#!/usr/bin/env python3
import gpiod
import time

class GpioControl:
    """Class that allows the user to specify GPIO pins to turn on and off."""

    def __init__(self):
        self.chip = gpiod.Chip('gpiochip0')
        self.active_lines = {}

    def set_pin(self, pin, state):
        if pin not in self.active_lines:
            try:
                line = self.chip.get_line(pin)
                line.request(consumer="gpio_control", type=gpiod.LINE_REQ_DIR_OUT)
                self.active_lines[pin] = line
            except Exception as e:
                print(f"Error accessing pin {pin}: {e}")
                return
        try:
            self.active_lines[pin].set_value(state)
            print(f"Pin {pin} set to {state}")
        except Exception as e:
            print(f"Error setting pin {pin}: {e}")

    def cleanup(self):
        for pin, line in self.active_lines.items():
            try:
                line.release()
                print(f"Released pin {pin}")
            except Exception as e:
                print(f"Error releasing pin {pin}: {e}")
        self.active_lines.clear()

    def run(self):
        try:
            while True:
                user_input = input("Enter GPIO pin number (or 'exit' to quit): ")
                if user_input.lower() in ["exit", "quit"]:
                    break
                try:
                    pin = int(user_input)
                except ValueError:
                    print("Invalid pin number. Please enter an integer.")
                    continue

                state_input = input("Enter state (0 or 1): ")
                if state_input not in ["0", "1"]:
                    print("Invalid state. Please enter 0 or 1.")
                    continue
                state = int(state_input)

                self.set_pin(pin, state)
        except KeyboardInterrupt:
            print("\nKeyboard interrupt received. Exiting.")
        finally:
            self.cleanup()

if __name__ == "__main__":
    gpio = GpioControl()
    gpio.run()
