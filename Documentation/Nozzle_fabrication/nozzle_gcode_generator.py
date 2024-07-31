def generate_gcode(rows, columns, intensity, cutting_intensity, dwell_time, pulse_interval, pulses, nozzle_spacing, square_size, feedrate,cut):
    gcode = []

    # Initialize the laser cutter
    gcode.append("; G-code generated for laser cutting an array of nozzles and surrounding squares")
    gcode.append("G21 ; Set units to millimeters")
    gcode.append("G90 ; Use absolute positioning")
    gcode.append(f"M3 S0 ; Shut off laser")

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
                gcode.append(f"M3 S{intensity:.3f} ; Enable laser dynamic mode")
                gcode.append(f"G1 F{feedrate} ; Set laser power and feedrate")
                gcode.append(f"G4 P{dwell_time:.3f} ; Dwell for specified time")
                gcode.append(f"M3 S0 ; Enable laser dynamic mode")
                gcode.append("G1 S0 ; Turn off laser between pulses")
                gcode.append(f"G4 P{pulse_interval:.3f} ; Dwell between pulses")

    # Loop through each position in the grid to cut squares
    if cut:
        for i in range(rows):
            for j in range(columns):
                x_center = j * nozzle_spacing
                y_center = i * nozzle_spacing

                x_start = x_center - half_square
                y_start = y_center - half_square

                # Move to the starting point of the square
                gcode.append(f"G0 X{x_start:.3f} Y{y_start:.3f}")
                gcode.append(f"G1 S{cutting_intensity} F{feedrate} ; Set laser power and feedrate")

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
rows = 1  # Number of rows
columns = 5  # Number of columns
percent_intensity = 0.03  # Laser intensity as a percentage (0-100% power)
intensity = int(percent_intensity * 1000)  # Convert percentage to 0-1000 scale
percent_cutting_intensity = 0.05  # Laser intensity for cutting the squares
cutting_intensity = int(percent_cutting_intensity * 1000)  # Convert percentage to 0-255 scale
dwell_time = 1  # Dwell time in milliseconds
pulse_interval = 10  # Dwell time between pulses in milliseconds
pulses = 4  # Number of pulses per hole
nozzle_spacing = 9  # Distance between holes in millimeters
square_size = 9.0  # Size of the square in millimeters
feedrate = 1000  # Feedrate in millimeters per minute
cut = True  # Whether to cut the squares or not

if __name__ == "__main__":
    # Generate G-code
    gcode = generate_gcode(rows, columns, intensity, cutting_intensity, dwell_time, pulse_interval, pulses, nozzle_spacing, square_size, feedrate,cut)

    # Save to a file
    with open("./M3_03per_1dwell_4pul_1x5_cut.gcode", "w") as file:
        file.write(gcode)

    print("G-code generated and saved to laser_cut_nozzles_and_squares.gcode")
