# Experimental HPB Balance Connection

This connection panel is an intentionally hidden data-collection aid for the
Veritas/BEL HPB-625i. It can display the live balance stream and, after an
additional session opt-in, stage a stable starting mass for stream gravimetric
capture. The printer sequence never begins until the operator confirms the
candidate starting mass.

## Before Launch

1. Connect the HPB-625i through the RS-232-to-USB adapter. Never connect an
   RS-232 DB9 cable directly to Raspberry Pi GPIO.
2. On the balance front panel, record its prior serial output mode, then select
   `PC cont`, 9600 baud, and `mg` units.
3. Leave the printer MCU connected to its normal adapter. The application
   excludes CP2102, STM, and the active MCU device from the balance list.

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

Slice 5 automates only the confirmed starting mass. Ending-mass entry remains
the existing manual workflow until Slice 6 is implemented.

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
- Never select or work around filtering for the printer MCU. The observed MCU
  adapter is CP2102 VID:PID `10c4:ea60`.
