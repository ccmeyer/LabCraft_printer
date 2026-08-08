# Experimental HPB Balance Connection

This connection panel is an intentionally hidden data-collection aid for the
Veritas/BEL HPB-625i. It can display the live balance stream and, after an
additional session opt-in, stage stable starting and ending masses for stream
gravimetric capture. The printer sequence never begins until the operator
confirms the candidate starting mass, and a completed row is never saved until
the operator confirms the candidate ending mass.

## Before Launch

1. Connect the HPB-625i through the RS-232-to-USB adapter. Never connect an
   RS-232 DB9 cable directly to Raspberry Pi GPIO.
2. On the balance front panel, record its prior serial output mode, then select
   `PC cont`, 9600 baud, and `mg` units.
3. Leave the printer MCU connected to its normal adapter. The application
   excludes CP2102, STM, and the active MCU device from the balance list.

The current printer profile requires the MCU log adapter to identify as the
Silicon Labs CP2102 `10c4:ea60`. Its configured persistent path is:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0
```

The application validates this identity before opening the log reader and no
longer falls back to `/dev/ttyUSB0`. Verify both adapters before launch:

```bash
ls -l /dev/serial/by-id
readlink -f /dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0
readlink -f /dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_CKAXb132J02-if00-port0
```

## Intentional Activation

On Raspberry Pi/Linux:

```bash
cd ~/LabCraft_printer
LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE=1 \
  ./env/bin/python FreeRTOS-interface/App.py
```

On Windows PowerShell:

```powershell
$env:LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE = "1"
.\env\Scripts\python.exe FreeRTOS-interface\App.py
```

Only the exact value `1` enables the feature. Values such as `true`, `yes`, or
` 1` do not enable it.

## Connect And Observe

1. Open the droplet imager and select the **Debug / Specialty** tab.
2. Find **Stream Gravimetric Capture**, then **Experimental Balance**.
3. Select the Prolific/balance adapter. A persistent
   `/dev/serial/by-id/...` name is preferred when Linux provides one.
4. Click **Connect**. Merely opening the dialog, refreshing the list, or
   selecting an adapter never opens it.
5. Confirm that the state changes to **Streaming** and the last-reading line
   follows the HPB display, including stable/unstable status.
6. Click **Disconnect** when finished. Closing the imager dialog alone leaves
   the application-owned connection running until explicit disconnect or app
   shutdown.

The existing `BALANCE_PORT` setting is only an optional visual preselection.
This panel does not modify it.

## Use A Balance Starting Mass

1. Wait until the connection state reads **Streaming**.
2. Select **Use connected balance for stream capture**. This choice lasts only
   for the running application; it is not saved in `Settings.json`.
3. Enter the repetition, notes, and capture mode as usual, then click the
   normal **Begin Session** control.
4. Leave the sample undisturbed while the status and sample count update.
5. Review the candidate mass when it appears. No calibration session, gripper
   action, flash snapshot, motion, pressure, dispensing, or printer command
   has started at this point.
6. Click **Confirm Starting Mass & Begin** only when the candidate is correct.
   This explicit confirmation releases the existing stream sequence.

Use **Cancel Reading** to stop an active measurement and **Read Again** after a
timeout, cancellation, service error, or unwanted candidate. A retry keeps the
staged repetition, notes, capture mode, and provisional stream session, but
uses a new balance request identity.

Use **Use Manual Starting Mass** to abandon the staged balance measurement.
This restores the existing manual controls and their pre-request contents,
turns off the session opt-in, and requires another click of **Begin Session**.
Closing the imager while a starting reading or candidate is pending abandons
that provisional measurement but does not disconnect the balance or clear the
application-session opt-in.

## Use A Balance Ending Mass

This path is offered only when the run began with a confirmed balance starting
mass, the session opt-in remains selected, and the balance is still Streaming.
Otherwise, loading arrival opens the unchanged manual ending-mass workflow.

1. Complete the existing stream sequence and wait for the printer head to
   reach the loading position.
2. Place the collected sample on the balance. No ending-mass request starts
   merely because the loading position was reached.
3. In the ending-mass dialog, click **Sample Placed - Read Ending Mass**.
4. Leave the sample undisturbed while the progress display updates.
5. Review the candidate, mass change, mass per print, sample count, duration,
   span, standard deviation, and slope.
6. If the candidate is correct, click **Confirm Ending Mass & Save**. This is
   the only balance path that invokes the existing CSV finalizer, gripper
   restoration, and camera return.

A zero or negative mass gain displays a prominent warning, but it may still be
saved intentionally for diagnostic data. Use **Cancel Reading** while a read is
active, **Read Again** after a failure or unwanted candidate, or **Enter Ending
Mass Manually** to return to the existing editable ending-mass workflow without
repeating the print run. Manual ending fallback does not clear the
application-session balance opt-in.

Closing the imager cancels an active ending read but retains the completed run.
Reopen the imager to retry the read or finish it manually. Discard uses the
existing gripper-restoration and camera-return sequence.

The CSV columns and calculations are unchanged. Balance request policy,
stability evidence, selected adapter, connection generation, and receive-only
serial settings are written only as additive provenance in
`stream_capture_log.jsonl`; raw serial frames are not stored there.

## Slice 6 Pi Acceptance

Before treating ending capture as hardware-verified, complete one real
balance-backed run and check all of the following:

1. Loading arrival does not start a balance request before the sample-ready
   button is clicked.
2. The candidate agrees with the HPB display and no CSV row exists before
   confirmation.
3. **Confirm Ending Mass & Save** writes exactly one expected CSV row.
4. The matching `stream_capture_log.jsonl` entry includes both starting and
   ending capture provenance and contains no raw frame history.
5. Gripper refresh settings are restored before the head returns to the
   camera position.

## Disable And Restore

Close the application and relaunch it without the environment variable. In
PowerShell, it may be cleared explicitly before relaunch:

```powershell
Remove-Item Env:LABCRAFT_ENABLE_EXPERIMENTAL_BALANCE -ErrorAction SilentlyContinue
.\env\Scripts\python.exe FreeRTOS-interface\App.py
```

Restore the balance's prior serial-output mode after the data-collection
session if `PC cont` is not its normal configuration.

## Troubleshooting

- No experimental group: completely close and relaunch the app with the exact
  flag value `1`; enabling it in a different shell does not affect a running
  process.
- Empty list: confirm the USB adapter is attached and visible to Linux. The
  verified adapter reports Prolific VID:PID `067b:23a3`.
- Permission denied: verify the Pi user has access to the serial device and
  re-login after any serial-group membership change.
- Error after unplugging: click **Disconnect** to reset the service, reconnect
  the adapter, click **Refresh**, and then explicitly connect again.
- MCU connection rejected with an MCU log-adapter error: confirm the CP2102
  by-id path exists and resolves to a device whose VID:PID is `10c4:ea60`.
  Never substitute `/dev/ttyUSB0` or `/dev/ttyUSB1`; those names can swap when
  the Prolific adapter is attached. If the CP2102 hardware is replaced, update
  `MACHINE_LOG_PORT` in `local/Settings.json` only after verifying the new
  persistent alias and USB identity.
- Never select or work around filtering for the printer MCU. The observed MCU
  adapter is CP2102 VID:PID `10c4:ea60`.
