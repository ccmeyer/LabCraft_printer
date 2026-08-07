# Veritas HPB-625i Serial Characterization Probe

## Purpose And Safety Boundary

`tools/probe_veritas_balance.py` records raw serial bytes from a Veritas
HPB-625i without starting the LabCraft application. It never transmits serial
data, invokes remote balance keys, or changes printer state.

The DB9 connector carries RS-232 electrical levels. Connect it only through
the BENFEI USB-to-RS-232 adapter. Never connect a DB9 signal directly to a
Raspberry Pi GPIO pin.

The physical characterization is performed on the separate, operator-run
Raspberry Pi selected for Slice 1. Do not guess a `/dev/ttyUSB*` number. The
printer Pi already has a Silicon Labs CP2102 (`10c4:ea60`) attached; that is
not the balance adapter.

## Prerequisites

- Veritas HPB-625i and BENFEI `000302`/PL-2303 RS-232-to-USB adapter.
- A Raspberry Pi/Linux checkout of the `feature/balance_integration` branch.
- Python 3 and pyserial 3.5. The repository requirements install it; verify
  with `python3 -c "import serial; print(serial.__version__)"`.
- Membership in the Linux group that owns the selected serial port, normally
  `dialout`. Check with `groups` and `ls -l <device>` rather than weakening
  device permissions globally.
- No terminal emulator or other program holding the balance port open.

Before changing the balance, write down its existing serial output mode and
baud rate. Using the HPB manual and the balance front panel, configure
continuous PC output (`PC cont`) at 9600 baud. The probe fixes the remaining
settings to eight data bits, no parity, one stop bit, and no flow control.

## Discover And Lock The Adapter Identity

Attach the BENFEI adapter and run:

```bash
python3 tools/probe_veritas_balance.py ports
python3 tools/probe_veritas_balance.py ports --json
```

Record all of the following in the Slice 1 bench notes:

- the Prolific VID:PID printed by the command;
- the `/dev/serial/by-id/...` path, when present;
- the resolved `/dev/ttyUSB*` path;
- USB product, manufacturer, and serial metadata;
- Linux driver name; and
- whether the by-id path remains the same after USB reconnect.

Use the by-id path when available. Every capture also requires the observed
VID:PID and refuses a mismatch before opening the device. For example only,
after replacing both values with those printed on the capture host:

```bash
export LABCRAFT_BALANCE_PORT=/dev/serial/by-id/<prolific-adapter-id>
export LABCRAFT_BALANCE_VID_PID=067b:2303
python3 tools/probe_veritas_balance.py capture \
  --port "$LABCRAFT_BALANCE_PORT" \
  --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" \
  --scenario stable_zero \
  --duration 60 \
  --display-reading "0.00000 g"
```

The VID:PID above is only an example. Use the identity observed on the actual
host. Do not substitute `10c4:ea60`, select the first enumerated port, or infer
the balance device from `/dev/ttyUSB1`.

## Operator Markers

During capture, type a short observation and press Enter. Each line is stored
with monotonic elapsed time in `markers.jsonl`. Useful marker text includes:

```text
display 1.23456 g stable icon on
disturbance start draft shield opened
sample removed display 0.00000 g stable icon on
sample replaced display 1.23457 g stable icon on
```

Markers are observations, not commands to the balance. Always include the
displayed sign, all decimal digits, unit, and visible stability-icon state.

## Required Capture Matrix

Run with the draft shield closed except during a marked disturbance. Use a
nonhazardous sample within the balance's rated capacity.

```bash
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario stable_zero --duration 60 --display-reading "<display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario stable_loaded --duration 60 --display-reading "<display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario disturb_recover --duration 60 --display-reading "<initial display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario natural_drift --duration 120 --display-reading "<display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario negative_after_manual_tare --duration 30 --display-reading "<initial display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario remove_replace --duration 60 --display-reading "<initial display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario fragmented_read --duration 30 --read-size 3 --display-reading "<display>"
python3 tools/probe_veritas_balance.py capture --port "$LABCRAFT_BALANCE_PORT" --expect-vid-pid "$LABCRAFT_BALANCE_VID_PID" --scenario disconnect --duration 30 --display-reading "<display>"
```

For `negative_after_manual_tare`, tare only from the balance keypad and then
remove the sample. For `disconnect`, enter a marker and unplug only the USB
side of the adapter while the capture is running. Exit code 3 is expected for
that deliberate disconnect. Reconnect USB and run `ports` again; do not
disconnect DB9 wiring while powered.

Exit codes are:

- `0`: scheduled capture completed with data;
- `2`: scheduled capture completed without data;
- `3`: validation, open, read, disconnect, close, or size-limit failure; and
- `130`: operator interruption.

## Evidence And Review

Each run is written beneath
`verification_reports/veritas_balance_probe/` with `run.json`, `chunks.jsonl`,
and `markers.jsonl`. That directory is intentionally ignored by Git. Preserve
the complete directory and transfer it back to the development workspace for
review.

Before creating the tracked fixture:

1. Verify each `run.json` SHA-256 against the concatenated `data_hex` values.
2. Compare transmitted records with the corresponding operator markers.
3. Document CR/LF boundaries, encoding, field widths, signs, decimal places,
   exact unit text, update cadence, and stable/unstable field values.
4. Retain representative stable, unstable, negative, fragmented, and
   disconnect-truncated chunks.
5. Remove hostnames, usernames, absolute paths, and USB serial numbers from
   the tracked fixture while retaining model, chipset, serial settings,
   scenario labels, raw hex, read boundaries, and source hashes.

Until that review is complete,
`tests/fixtures/veritas_balance/hpb625i_serial_samples_v1.json` deliberately
has status `awaiting_physical_capture` and contains no synthetic balance data.

## Troubleshooting And Restoration

- If no port appears, disconnect and reconnect USB, then inspect `dmesg` and
  repeat `ports`.
- If the port has no VID:PID, do not bypass the identity check. Collect the
  `ports --json` output for review.
- If opening fails with permission denied, correct the operator's serial-port
  group membership and start a new login session. Do not use a permanent
  world-writable permission workaround.
- If a capture exits 2, confirm `PC cont`, 9600 baud, the DB9 connection, and
  that another process is not holding the port.
- A disconnect or interruption still leaves partial evidence; retain it.

After the matrix is complete, restore the balance's serial output mode and
baud rate to the values recorded before characterization. Remove the adapter
from the capture host if it is not needed.
