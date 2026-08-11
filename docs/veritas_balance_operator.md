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
Silicon Labs CP2102 `10c4:ea60`. `MACHINE_LOG_PORT` is an optional preferred
path; a blank or stale preference uses the sole attached device with that exact
USB identity. The application prefers its persistent by-id alias and never
selects by `/dev/ttyUSB` order, product-name regex, or fuzzy matching. Zero or
multiple CP2102 matches block the machine connection before any candidate is
opened.

The following read-only commands inventory the attached adapters without
opening them:

```bash
python3 -m serial.tools.list_ports -v
ls -l /dev/serial/by-id
```

If more than one CP2102 is attached, set `MACHINE_LOG_PORT` in
`local/Settings.json` to the verified by-id alias that belongs to the MCU log
channel.

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
4. On the first run, or whenever the previous mass is no longer reusable, the
   printer head moves to the existing loading position. This is the only
   pre-calibration motion; no calibration session, flash snapshot, gripper
   action, pressure action, or ejection has begun.
5. Remove the collection tube, place it on the balance, and click
   **Sample Placed - Read Starting Mass**. Leave the tube undisturbed while
   the status and sample count update.
6. Review the candidate mass. Reinstall that same collection tube on the
   printer head, then click **Same Tube Reinstalled - Confirm Starting Mass &
   Return to Camera**.
7. The head returns to the camera. Only after arrival, and only if no ejection
   was attempted in the meantime, does the existing calibration session,
   gripper preamble, and stream sequence begin.

After a successful balance-backed ending save, the next Begin may offer a
choice instead of moving to loading:

- **Use Previous Ending Mass** carries that verified ending mass forward as
  the next starting mass. Select it only when the same collection tube remains
  installed. The run starts from the camera without another weighing.
- **Measure New Starting Mass** performs the loading-position workflow above.

Carry-forward is available only in the same running application. Any
`DISPENSE` or `DISPENSE_PRINT` attempt outside or inside the workflow, an MCU
reset/reconnect, serial transport uncertainty, a discarded run, or manual
ending-mass fallback invalidates it. `DISPENSE_REFUEL` alone does not invalidate
it. When invalidated, Begin proceeds to a new loading-position measurement.

Use **Cancel Reading** to stop an active measurement and **Read Again** after a
timeout, cancellation, service error, or unwanted candidate. A retry keeps the
staged repetition, notes, capture mode, and provisional stream session, but
uses a new balance request identity.

Use **Use Manual Starting Mass** to abandon the staged balance measurement.
Because the head and tube may be at loading, first reinstall the tube and click
**Same Tube Reinstalled - Return to Camera**. After camera arrival the existing
manual controls and their pre-request contents are restored, the session
opt-in is turned off, and another click of **Begin Session** is required.
Closing the imager while a starting reading is active cancels that reading but
does not move the machine, discard the staged workflow, disconnect the
balance, or clear the application-session opt-in. Reopening restores the
appropriate prompt for the current physical position.

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
6. Reinstall the same collection tube on the printer head. If the candidate is
   correct, click **Same Tube Reinstalled - Confirm Ending Mass & Save**. This
   is the only balance path that invokes the existing CSV finalizer, gripper
   restoration, camera return, and creation of a reusable next-run baseline.

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

## Pre-Start Loading And Baseline-Reuse Pi Acceptance

The development Raspberry Pi passed this checklist on 2026-08-10 at balance
integration commit `6494bb57550dcbf4398606707fa5e2eac50f9590`, using the
HPB-625i through Prolific `067b:23a3` and the MCU logger through CP2102
`10c4:ea60`. Repeat it after relevant hardware or workflow changes:

1. First Begin moves to loading before starting a balance request, calibration
   session, flash snapshot, pressure action, gripper action, or ejection.
2. Starting balance reading begins only after the sample-ready button.
3. Reinstalling the same tube and confirming returns the head to the camera
   before the calibration sequence begins.
4. Ending loading arrival does not start a balance request before its
   sample-ready button is clicked.
5. The ending candidate agrees with the HPB display and no CSV row exists
   before confirmation.
6. **Same Tube Reinstalled - Confirm Ending Mass & Save** writes exactly one
   expected CSV row; gripper settings are restored before camera return.
7. A second Begin with no intervening ejection offers the prior ending mass.
   Explicit reuse starts without another loading move and uses exactly that
   value as the new starting mass.
8. After a later ending save, issue a manual droplet ejection. The next Begin
   must not offer reuse and must require another loading measurement.
9. Verify CSV `Num Prints` uses the unified completed-ejection count. For a
   normal camera timecourse, the capture-artifact and GPIO-acknowledged totals
   should agree. Completed serial `DISPENSE`/`DISPENSE_PRINT` droplets, if any,
   are added separately.
10. Check `stream_capture_log.jsonl` for `ejection_count_source`, the serial
   delta, GPIO acknowledged/attempt deltas, capture-derived count, and the
   starting/ending ledger snapshots. No raw serial, GPIO, or image data is
   stored in these fields.

If `ejection_count_source` is `serial_plus_capture_fallback`, the application
detected incomplete GPIO-ledger coverage and preserved the nonzero artifact
count rather than replacing it with zero. This is saveable with a provenance
warning when there is no uncertainty. A trigger without a flash
acknowledgement, an unknown configured imaging count, or a related firmware
flash fault marks accounting uncertain and blocks confirmed save; do not
override that condition with a manual count.

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
- MCU connection rejected with no CP2102 match: use the read-only inventory
  commands above and confirm the logger reports VID:PID `10c4:ea60`.
- MCU connection rejected as ambiguous: more than one CP2102 is attached; set
  `MACHINE_LOG_PORT` to the verified logger by-id alias. Never substitute a
  guessed `/dev/ttyUSB0` or `/dev/ttyUSB1`, because those names can swap when
  the Prolific adapter is attached.
- Never select or work around filtering for the printer MCU. The observed MCU
  adapter is CP2102 VID:PID `10c4:ea60`.
