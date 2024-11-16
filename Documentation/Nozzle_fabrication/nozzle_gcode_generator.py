def generate_gcode(rows, columns, intensity, dwell_time, pulses, pulse_interval, nozzle_spacing, square_size, x_offset=0.0, y_offset=0.0,cut_squares=True):
    gcode = []

    # Initialize the laser cutter
    gcode.append("; G-code generated for laser cutting an array of nozzles and surrounding squares")
    gcode.append("G21 ; Set units to millimeters")
    gcode.append("G90 ; Use absolute positioning")
    # gcode.append("M4 ; Enable laser dynamic mode")

    # nozzle_offset_x = 1.536
    # nozzle_offset_y = 2.25
    nozzle_offset_x = 7.364
    nozzle_offset_y = 6.65

    # Loop through each position in the grid to cut holes
    for i in range(rows):
        for j in range(columns):
            x_center = j * nozzle_spacing + x_offset
            y_center = i * nozzle_spacing + y_offset

            x_nozzle = x_center + nozzle_offset_x
            y_nozzle = y_center + nozzle_offset_y

            # Move to the nozzle position
            gcode.append(f"G0 X{x_nozzle:.3f} Y{y_nozzle:.3f}")

            # Fire the laser for the specified number of pulses to cut the hole
            for _ in range(pulses):
                gcode.append(f"M3 S{intensity:.3f} ; Set laser power")
                gcode.append("G1 F1000 ; Set feed rate to 1000 mm/min")
                gcode.append(f"G4 P{dwell_time:.3f} ; Dwell for specified time")
                gcode.append("M3 S0 ; Turn off laser between pulses")
                gcode.append("G1 S0 ; Turn off laser between pulses")
                gcode.append(f"G4 P{pulse_interval:.3f} ; Dwell between pulses")

    # Loop through each position in the grid to cut squares
    if cut_squares:
        for i in range(rows):
            for j in range(columns):
                x_start = j * nozzle_spacing + x_offset
                y_start = i * nozzle_spacing + y_offset

                # Move to the starting point of the square
                gcode.append(f"G0 X{x_start:.3f} Y{y_start:.3f}")
                gcode.append(f"G1 S{intensity} ; Set laser power")

                # Cut the square
                gcode.append(f"G1 X{x_start + square_size:.3f} Y{y_start:.3f} ; Cut right")
                gcode.append(f"G1 X{x_start + square_size:.3f} Y{y_start + square_size:.3f} ; Cut up")
                gcode.append(f"G1 X{x_start:.3f} Y{y_start + square_size:.3f} ; Cut left")
                gcode.append(f"G1 X{x_start:.3f} Y{y_start:.3f} ; Cut down")

                gcode.append("G1 S0 ; Turn off laser after cutting the square")

    # Finalize the G-code
    gcode.append("M5 ; Disable laser")
    gcode.append("G0 X0 Y0 ; Return to home position")

    return "\n".join(gcode)

# Parameters
rows = 3  # Number of rows
columns = 5  # Number of columns
intensity = 3  # Laser intensity (0-1000 for 0%-100% power)
dwell_time = 1  # Dwell time in milliseconds
# dwell_time = 0.003  # Dwell time in seconds
pulse_interval = 10  # Dwell time between pulses in milliseconds
pulses = 1  # Number of pulses per hole
nozzle_spacing = 9  # Distance between holes in millimeters
square_size = 9  # Size of the square in millimeters
x_offset = 25  # Offset in X direction
y_offset = -25-9  # Offset in Y direction
cut_squares = True  # Whether to cut squares around the holes

if __name__ == "__main__":
    # Generate G-code
    gcode = generate_gcode(rows, columns, intensity, dwell_time, pulses, pulse_interval, nozzle_spacing, square_size, x_offset, y_offset,cut_squares=cut_squares)

    # Save to a file
    file_name = f"./dual_M3_{intensity}int_{dwell_time}dwell_{pulses}pul_{rows}x{columns}_cut.gcode"
    with open(file_name, "w") as file:
        file.write(gcode)

    print(f"G-code generated and saved to {file_name}")
