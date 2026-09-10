# Calibration first-open arming after a camera move

## Finding

The rc.13 operator reported that calibration controls were usable on first open
but capture was rejected because the camera/flash session was not armed. Closing
and reopening at the camera worked. The operator subsequently confirmed the
trigger is the move to the camera, independent of loading/copying an experiment.

The software reproduction confirms a synchronous callback deadlock:

1. PressurePlotBox requests Controller.move_to_location("camera") with a
   completion callback that opens the calibration dialog.
2. SerialReader delivers a stamped status frame to Machine.update_status.
   Controller.handle_status_update updates Model state; command-number changes
   reach Machine.update_command_numbers and CommandQueue.update_command_status.
3. The completed move runs its success handler synchronously. The handler
   activates the dialog and calls QDialog.exec(), retaining the original status
   handler on the stack throughout the modal session.
4. Activation calls Controller.start_read_camera -> Machine.start_read_camera,
   which queues START_READ_CAMERA (0xC0 / firmware CMD_INIT_FLASH). The firmware
   handler would initialize and arm its flash session if this command arrived.
5. The rc.13 reader watermark correctly requires every received frame to finish
   handling before dispatch. The retained status frame cannot finish until the
   dialog closes, so its flash-arming command cannot dispatch while it is open.
   Capture preflight eventually reports flash_disarmed.

Reopening while already at the camera comes directly from the user action,
without a retained move-completion status frame. The optimizer worker does not
participate in this cycle. The refuel-camera modal launch has the same callback
pattern and is included in the bounded correction.

## Correction and boundaries

Schedule the existing post-move dialog continuations for the next Qt event-loop
turn. The move handler returns so status processing can complete. The scheduled
continuation retains the original launch token and checks it at execution time;
Clear Queue, reset, disconnect or a newer launch invalidates an older request.
It also checks the Qt owner's validity before accessing the view.

The changed path remains UI -> Controller -> Model -> machine communications ->
firmware, with only the final UI continuation deferred. Existing move preflight,
profile leases, duplicate-window handling and flash preflight remain in force.
No command, wire format, firmware behavior, timeout, allocation, saved data or
dispatch guard changes. Rejection/cancellation opens no new camera window and
does not initiate its arming/capture commands. The already completed move is not
reversed automatically. An already-at-camera launch retains its existing path.

## Verification

On an external archive of released v1.3.0-rc.13 (`67b096c0`), both new composed
post-move modal tests fail: the observed reader completed count is zero and the
list of sent commands is empty while the modal event loop is running. They use
the production Machine, SerialReader watermark, CommandQueue completion and
PressurePlotBox launch methods, a simulated serial port, and a short modal event
loop in place of physical camera construction.

The corrected branch passed **269 tests in 9.34 seconds**, covering:

- First post-move calibration/refuel launch can dispatch START_READ_CAMERA while
  its dialog is open, after completing the triggering status frame.
- Clear Queue, disconnect and reset between move completion and deferred launch
  suppress the launch; a destroyed Qt owner cannot launch it either.
- Existing duplicate launch, stale completion, profile cleanup, already-at-camera
  and historical-experiment restrictions, with complete original assertions.
- MCU ACK/fault ordering, stale reader generations, shutdown dispatch protection,
  missing-timer teardown, capture coordinator and flash rejection behavior.
- The opt-in no-hardware calibration-dialog lifecycle through eight open/close
  cycles, plus the refuel-panel/camera UI tests.

The new composed tests initially triggered a Windows Qt access violation later
in a combined process; smaller runs and the released baseline comparison passed.
The final fixture explicitly releases its machine/reader resources and collects
fake callback ownership cycles between tests, rather than leaving collection to
a later dialog event loop. The complete combined run then passed. No production
garbage-collection policy or timing threshold was changed. Earlier crash logs
remain in the external evidence alongside the passing report.

Evidence root:
`C:\Users\conar\AppData\Local\Temp\labcraft-calibration-first-open-5cb52e66-4715-402d-a056-c8ddcbe49b41`.
Final combined report: `focused-owned-cleanup.xml`; released-code reproduction:
`released-repro.xml`. `base-combined.log` is a current-branch comparison without
the new tests; `released-combined.log` is the separate released-source comparison.

Full-suite and Pi qualification are not claimed by this focused investigation.
Before another release, obtain independent review, run the final integration
gate, and qualify the exact pushed revision through the Pi wrappers. An attended
reproduction must explicitly authorize the camera-approach movement and any
capture/dispensing scope, compare first-open and already-at-camera reopen, and
finish with required released restoration, SAFE and postflight. Do not infer
new hardware authority from the earlier rc.13 campaign.

Rollback is a normal revert of this isolated UI/test/documentation fix. Preserve
the complete rc.13 reader watermark and disconnect protections. No data migration
or firmware update is involved. The original rc.12 MCU-unresponsive incident's
precise cause remains a separate, unconfirmed question.
