def generate_gcode(rows, columns, intensity, dwell_time, pulses, nozzle_spacing, square_size):
    gcode = []

    # Initialize the laser cutter
    gcode.append("; G-code generated for laser cutting an array of nozzles and surrounding squares")
    gcode.append("G21 ; Set units to millimeters")
    gcode.append("G90 ; Use absolute positioning")
    gcode.append("M4 ; Enable laser dynamic mode")

    half_square = square_size / 2.0
    nozzle_offset_x = 0.0  # Nozzle centered in X direction
    nozzle_offset_y = -half_square + 2.0  # Nozzle 2mm from the top in Y direction

    # Loop through each position in the grid to cut holes
    for i in range(rows):
        for j in range(columns):
            x_center = j * nozzle_spacing
            y_center = i * nozzle_spacing

            x_nozzle = x_center + nozzle_offset_x
            y_nozzle = y_center + nozzle_offset_y

            # Move to the nozzle position
            gcode.append(f"G0 X{x_nozzle:.3f} Y{y_nozzle:.3f}")

            # Fire the laser for the specified number of pulses to cut the hole
            for _ in range(pulses):
                gcode.append(f"G1 S{intensity} ; Set laser power")
                gcode.append(f"G4 P{dwell_time:.3f} ; Dwell for specified time")
                gcode.append("G1 S0 ; Turn off laser between pulses")
                gcode.append(f"G4 P{pulse_interval:.3f} ; Dwell between pulses")

    # Loop through each position in the grid to cut squares
    for i in range(rows):
        for j in range(columns):
            x_center = j * nozzle_spacing
            y_center = i * nozzle_spacing

            x_start = x_center - half_square
            y_start = y_center - half_square

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
columns = 3  # Number of columns
intensity = 255  # Laser intensity (0-255 for 0%-100% power)
dwell_time = 0.003  # Dwell time in seconds
pulse_interval = 0.01  # Dwell time between pulses in seconds
pulses = 2  # Number of pulses per hole
nozzle_spacing = 9.0  # Distance between holes in millimeters
square_size = 9.0  # Size of the square in millimeters

if __name__ == "__main__":
    # Generate G-code
    gcode = generate_gcode(rows, columns, intensity, dwell_time, pulses, nozzle_spacing, square_size)

    # Save to a file
    with open("./laser_cut_nozzles_and_squares.gcode", "w") as file:
        file.write(gcode)

    print("G-code generated and saved to laser_cut_nozzles_and_squares.gcode")