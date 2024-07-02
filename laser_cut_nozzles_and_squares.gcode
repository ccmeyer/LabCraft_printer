; G-code generated for laser cutting an array of nozzles and surrounding squares
G21 ; Set units to millimeters
G90 ; Use absolute positioning
M4 ; Enable laser dynamic mode
G0 X0.000 Y-2.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X9.000 Y-2.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X18.000 Y-2.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X0.000 Y6.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X9.000 Y6.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X18.000 Y6.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X0.000 Y15.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X9.000 Y15.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X18.000 Y15.500
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G1 S255 ; Set laser power
G4 P0.003 ; Dwell for specified time
G1 S0 ; Turn off laser between pulses
G4 P0.010 ; Dwell between pulses
G0 X-4.500 Y-4.500
G1 S255 ; Set laser power
G1 X4.500 Y-4.500 ; Cut right
G1 X4.500 Y4.500 ; Cut up
G1 X-4.500 Y4.500 ; Cut left
G1 X-4.500 Y-4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X4.500 Y-4.500
G1 S255 ; Set laser power
G1 X13.500 Y-4.500 ; Cut right
G1 X13.500 Y4.500 ; Cut up
G1 X4.500 Y4.500 ; Cut left
G1 X4.500 Y-4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X13.500 Y-4.500
G1 S255 ; Set laser power
G1 X22.500 Y-4.500 ; Cut right
G1 X22.500 Y4.500 ; Cut up
G1 X13.500 Y4.500 ; Cut left
G1 X13.500 Y-4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X-4.500 Y4.500
G1 S255 ; Set laser power
G1 X4.500 Y4.500 ; Cut right
G1 X4.500 Y13.500 ; Cut up
G1 X-4.500 Y13.500 ; Cut left
G1 X-4.500 Y4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X4.500 Y4.500
G1 S255 ; Set laser power
G1 X13.500 Y4.500 ; Cut right
G1 X13.500 Y13.500 ; Cut up
G1 X4.500 Y13.500 ; Cut left
G1 X4.500 Y4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X13.500 Y4.500
G1 S255 ; Set laser power
G1 X22.500 Y4.500 ; Cut right
G1 X22.500 Y13.500 ; Cut up
G1 X13.500 Y13.500 ; Cut left
G1 X13.500 Y4.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X-4.500 Y13.500
G1 S255 ; Set laser power
G1 X4.500 Y13.500 ; Cut right
G1 X4.500 Y22.500 ; Cut up
G1 X-4.500 Y22.500 ; Cut left
G1 X-4.500 Y13.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X4.500 Y13.500
G1 S255 ; Set laser power
G1 X13.500 Y13.500 ; Cut right
G1 X13.500 Y22.500 ; Cut up
G1 X4.500 Y22.500 ; Cut left
G1 X4.500 Y13.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
G0 X13.500 Y13.500
G1 S255 ; Set laser power
G1 X22.500 Y13.500 ; Cut right
G1 X22.500 Y22.500 ; Cut up
G1 X13.500 Y22.500 ; Cut left
G1 X13.500 Y13.500 ; Cut down
G1 S0 ; Turn off laser after cutting the square
M5 ; Disable laser
G0 X0 Y0 ; Return to home position