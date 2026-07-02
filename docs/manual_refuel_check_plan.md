# Manual Refuel Check Plan

## Status

- Date: 2026-07-01
- Scope: planning document only
- Goal: introduce a guided manual refuel-pressure check for stream-mode printing before any camera-assisted or automated interpretation is trusted

## Purpose

Stream-mode printing depends on the net volume change in the printing channel staying near zero when the normal paired print/refuel command runs. Today the operator manually checks this by moving the printer head to a visible loading position, using refuel-only and print-only pulses to place the fluid level near mid-channel, then running paired print droplets and watching whether the level remains stable.

The first implementation should preserve that operator judgment. The software should guide the steps, enforce preflight checks, record the outcome, and prompt at the right workflow moments. It should not rely on refuel camera image analysis and should not introduce closed-loop pressure control.

## Current Command Path

The existing manual pulse controls already use the right firmware behavior:

`View.py shortcut/button -> Controller -> Machine_FreeRTOS -> existing queued command`

Relevant existing paths:

- `View.py` shortcuts:
  - `z` / `x`: refuel-only pulses
  - `c` / `v`: print-only pulses
  - `w` / `e` / `r` / `t`: normal paired print/refuel droplets
- `Controller.print_droplets(...) -> Machine_FreeRTOS.print_droplets(...) -> DISPENSE`
- `Controller.print_only(...) -> Machine_FreeRTOS.print_only(...) -> DISPENSE_PRINT`
- `Controller.refuel_only(...) -> Machine_FreeRTOS.refuel_only(...) -> DISPENSE_REFUEL`
- `Controller.set_relative_refuel_pressure(...) -> Machine_FreeRTOS.set_relative_refuel_pressure(...)`
- `Controller.move_to_location(...) -> location model and queued motion commands`

The new workflow should reuse these commands. It should not add or change protocol opcodes, message parsing, command formats, firmware handlers, or timing semantics.

## Target User Workflow

### After Applying A Stream Calibration Result

When a stream calibration result is applied to the experiment or printer head:

1. Mark the corresponding stream refuel check as required unless a valid passed check already exists for the same applied stream calibration settings.
2. Ask the operator whether to calibrate/check refuel pressure now.
3. If the operator chooses yes:
   - close the droplet imager/calibration window cleanly
   - move to the loading/check position
   - open the manual refuel check window
4. If the operator chooses no:
   - leave the check in a required or deferred state
   - prompt again before print-array start

### Before Starting A Stream Print Array

When the operator starts a stream-mode print array:

1. Check whether the loaded head and applied stream calibration have a passed manual refuel check.
2. If passed, allow normal print-array start.
3. If missing, stale, deferred, or unclear, show a prompt with choices:
   - run manual refuel check now
   - proceed without refuel check
   - cancel
4. If the operator bypasses the check, record an explicit bypass event and allow printing.

Bypass must remain possible because the operator may already have checked the condition outside the guided workflow.

## Manual Check Dialog Workflow

The first version should be a guided manual dialog. It should not display or analyze camera frames.

Recommended steps:

1. **Preflight**
   - command queue idle
   - machine connected
   - printer head loaded
   - print and refuel pressure regulation active
   - stream-mode calibration/settings available
   - loading/check location available

2. **Position**
   - move to the loading/check position, or confirm already there
   - avoid hidden automatic motion inside the dialog after the operator starts manual inspection

3. **Center Level**
   - provide buttons for small and large refuel-only pulses
   - provide buttons for small and large print-only pulses
   - tell the operator to bring the visible level to a clearly observable mid-channel range

4. **Run Trial**
   - run the same paired print/refuel command used during normal printing
   - start with a conservative fixed count, for example 10 or 20 droplets
   - optionally allow repeat trials without closing the dialog

5. **Operator Judgment**
   - stable
   - level rose
   - level fell
   - unclear / cannot judge

6. **Guidance**
   - stable: record pass
   - level rose: recommend decreasing refuel pressure or refuel pulse width
   - level fell: recommend increasing refuel pressure or refuel pulse width
   - unclear: do not mark passed

7. **Retest Loop**
   - keep the dialog open after adjustments
   - allow repeated trials until the operator records stable or cancels

## State Contract

The workflow needs a small persistent state object. It should be keyed tightly enough that an old pass cannot silently validate a different stream condition.

Recommended key fields:

- printer head identity
- reagent/stock identity when available
- applied stream calibration record id or stable calibration fingerprint
- print pressure
- print pulse width
- stream duration or ejection volume target
- refuel pressure
- refuel pulse width

Recommended status values:

- `unknown`: no current information
- `required`: a stream calibration was applied and a refuel check is needed
- `deferred`: operator declined the immediate post-apply check
- `passed`: operator observed stable level
- `failed`: operator observed drift and did not resolve it
- `unclear`: operator could not judge
- `bypassed`: operator chose to print without a recorded pass

Recommended result fields:

- status
- timestamp
- operator action source: post-apply prompt, print-array preflight, standalone dialog
- trial droplet count
- number of trials
- operator judgment
- optional operator notes
- print pressure at pass
- refuel pressure at pass
- print pulse width at pass
- refuel pulse width at pass
- command frequency if relevant
- previous status
- bypass reason when applicable

## Implementation Slices

### Slice 1: Planning Document

Add this document and use it as the implementation reference.

No code changes.

### Slice 2: State And Preflight Contract

Add model/controller support for:

- marking a manual refuel check required after stream calibration application
- recording pass, failed, unclear, deferred, and bypass outcomes
- querying print-array readiness
- returning prompt-friendly preflight messages

This slice should include tests for state transitions and stale/mismatched calibration detection.

### Slice 3: Manual Check Dialog

Add a standalone manual refuel check dialog that uses existing controller methods only:

- `refuel_only`
- `print_only`
- `print_droplets`
- `set_relative_refuel_pressure`
- `move_to_location`

This slice should not launch the camera and should not consume image analysis.

### Slice 4: Post-Apply Prompt

After applying a stream calibration result, prompt the operator:

- yes: close imager, move to loading/check position, open manual refuel check dialog
- no: mark deferred/required and leave normal calibration workflow

This slice should handle window close and move completion explicitly rather than racing the dialog open before motion completes.

#### Slice 4 Concrete Implementation Plan

##### Summary

Wire the Slice 3 manual refuel check dialog into the stream-calibration apply workflow. When a stream calibration is successfully applied to the experiment design, the droplet imager should ask whether the operator wants to run the manual refuel check now. Choosing yes should close the imager, queue a move to `loading`, and open the manual refuel check dialog only after that move completes. Choosing no should record a deferred manual refuel check through the Slice 2 controller API.

No print-array guard, visible pressure-box button, camera-assisted level view, firmware change, protocol change, or automatic pressure tuning belongs in this slice.

##### Call Path

Primary yes path:

`DropletImagingDialog apply action -> ExperimentModel applied calibration recording -> DropletImagingDialog post-apply prompt -> PressurePlotBox post-apply refuel-check launcher -> Controller.move_to_location("loading", manual=True, on_complete=...) -> PressurePlotBox._launch_manual_refuel_check_dialog() -> ManualRefuelCheckDialog -> Controller manual pulse/outcome APIs`

Primary no path:

`DropletImagingDialog apply action -> ExperimentModel applied calibration recording -> DropletImagingDialog post-apply prompt -> Controller.mark_manual_refuel_check_deferred(source="post_apply_prompt")`

Slice 2 already marks the check `required` when the stream calibration is recorded. Slice 4 should only add the operator prompt and the explicit deferred outcome when the operator declines.

##### Files To Touch

- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/View.py`
- `tests/test_droplet_imaging_summary_table.py`
- `tests/test_pressure_plotbox_buttons.py`

No `Controller.py` or `Model.py` changes should be necessary unless the implementation discovers a missing facade while wiring tests.

##### Implementation Steps

1. Add a small helper in `DropletImagingDialog` that runs after an applied calibration succeeds, for example `_handle_post_apply_manual_refuel_prompt(applied_calibration, completion_message, settings_result)`.
2. Gate the helper to stream mode only using the applied calibration payload's normalized `printing_mode` / `applied_printing_mode`; droplet-mode and fill/droplet calibrations should keep the current completion behavior and should not call the refuel-check APIs.
3. If applying the calibration's print settings failed, keep the existing settings warning and do not launch the refuel check immediately. The check would not validate the applied stream settings. Leave the required state in place so Slice 5 can prompt again before print-array start.
4. Show a yes/no prompt after the stream calibration is applied and settings are usable. The prompt text should state that yes will close the imager, move to `loading`, and open the manual refuel check dialog.
5. On no, call `controller.mark_manual_refuel_check_deferred(source="post_apply_prompt")`. If recording deferred fails, show a warning but do not block the user from remaining in the imager.
6. On yes, schedule the post-apply launch through the parent `PressurePlotBox` rather than constructing the manual dialog inside `DropletImagingDialog`. Close the imager first, then run the launcher after the imager's modal `exec()` has unwound, using `finished` plus `QTimer.singleShot(0, ...)` or an equivalent one-shot callback.
7. In `PressurePlotBox`, add a post-apply launcher method, for example `manual_refuel_check_after_stream_apply()`, that reuses the Slice 3 preflight checks, rejects duplicate launches, checks the queue, and queues `controller.move_to_location("loading", manual=True, on_complete=...)`. If the machine is already at `loading`, launch immediately. If the move cannot be queued, clear the pending state and show a popup.
8. Keep `PressurePlotBox.manual_refuel_check()` as the internal no-motion launcher from Slice 3, or refactor both entry points through a shared private helper so the preflight and duplicate-launch behavior stay identical.

##### Prompt Behavior

- Prompt title: `Manual Refuel Check Required`
- Yes label/meaning: run the check now
- No label/meaning: defer until print-array preflight
- Yes outcome:
  - close the droplet imager
  - queue `move_to_location("loading", manual=True, on_complete=...)`
  - open `ManualRefuelCheckDialog` only from the move completion callback
- No outcome:
  - record `status="deferred"`, `source="post_apply_prompt"`
  - leave the imager open and preserve the existing applied-calibration UI state
- Prompt is skipped when:
  - applied mode is not `stream`
  - controller/model context is unavailable
  - applying stream print settings failed
  - legacy profile is active

##### Safety And Sequencing Rules

- Do not open the manual refuel dialog before the imager has closed.
- Do not move while the command queue is busy.
- Do not hide motion inside the manual refuel dialog; the post-apply launcher owns the one automatic move to `loading` after explicit operator consent.
- Do not start any print array or trial automatically after the dialog opens.
- Do not call refuel camera start/capture APIs.
- Preserve existing `Esc` / pause behavior in both windows.

##### Test Plan

Add focused tests for `DropletImagingDialog` apply behavior:

- Stream calibration apply with yes response schedules the post-apply launcher and closes/accepts the imager.
- Stream calibration apply with no response calls `mark_manual_refuel_check_deferred(source="post_apply_prompt")` and leaves the imager open.
- Droplet-mode calibration apply does not prompt and does not call deferred or launcher APIs.
- Stream calibration apply with failed print-settings application does not launch the manual refuel check and leaves the required state for later.
- Missing post-apply launcher shows a warning and does not crash.

Add focused tests for `PressurePlotBox` post-apply launcher behavior:

- Valid stream context queues `move_to_location("loading", manual=True, on_complete=...)`, then opens `ManualRefuelCheckDialog` only when the callback runs.
- If already at `loading`, the dialog opens without queueing motion.
- Queue busy, no loaded head, unregulated pressure, invalid imaging calibration, and non-stream/not-required contexts block launch with prompt-friendly messages.
- Duplicate launch is rejected both while a loading move is pending and while the manual refuel dialog is open.
- A failed `move_to_location("loading", ...)` clears pending launch state and shows a popup.

Run focused verification:

`.\env\Scripts\python.exe -m pytest -q tests\test_droplet_imaging_summary_table.py tests\test_pressure_plotbox_buttons.py tests\test_manual_refuel_check_dialog.py tests\test_controller_print_guards.py tests\test_experiment_model_runtime_refresh.py`

##### Rollback

Rollback for Slice 4 is Python/UI-only:

1. Remove or disable the `DropletImagingDialog` post-apply prompt helper.
2. Remove or disable the `PressurePlotBox` post-apply launch method.
3. Leave Slice 2 persisted state and Slice 3 manual dialog intact.
4. Operators can continue using the existing keyboard shortcuts and the internal manual dialog launcher.

### Slice 5: Print-Array Guard

Extend the existing print-array start preflight so stream arrays prompt for the refuel check when needed.

The guard should allow:

- run check now
- proceed without check
- cancel

Proceeding without the check must record a bypass.

### Slice 6: Workflow Display And Persistence

Surface the refuel-check status in the experiment/head workflow near calibration application and print-array readiness.

Persist enough state so app restart does not accidentally convert an unchecked stream calibration into a passed one.

### Slice 7: Hybrid Camera-Assisted Manual Check

Reuse the same state contract and dialog outcome model, but show the refuel camera feed so the operator can inspect the level at the camera position.

This should still be manual judgment first. Image-analysis guidance can be added later as advisory-only.

## Validation Plan

Python tests should cover:

- state transition behavior
- required/deferred/pass/bypass status handling
- print-array prompt decisions
- stale check detection when applied stream settings change
- no prompt for non-stream or legacy-only contexts unless explicitly required
- manual dialog calls existing controller methods with expected droplet counts
- post-apply prompt routes yes/no choices correctly

Manual validation should cover:

1. Apply stream calibration result and choose no. Confirm print-array start prompts again.
2. Apply stream calibration result and choose yes. Confirm imager closes, machine moves to loading/check position, and manual check dialog opens.
3. Mark stable. Confirm print-array start no longer prompts.
4. Mark level rose. Confirm guidance recommends decreasing refuel pressure or refuel pulse width.
5. Mark level fell. Confirm guidance recommends increasing refuel pressure or refuel pulse width.
6. Bypass at print-array start. Confirm print starts only after explicit bypass and the bypass is recorded.

## Safety Rules

- Do not change firmware or protocol behavior.
- Do not automate pressure changes in the first version.
- Do not treat camera analysis as authoritative in the first version.
- Do not start a print array automatically after a refuel check pass.
- Do not run the check while the command queue is busy.
- Keep stop/pause behavior available during all manual trials.
- Prefer explicit operator confirmation before motion to the loading/check position.

## Risks And Open Questions

- The exact "apply stream calibration" hook may differ between online stream calibration completion, tail override application, and experiment-level applied calibration selection.
- The loading/check position name should be confirmed. Existing location names include `camera`, `plate`, `pause`, and likely machine-specific saved locations.
- The staleness rule needs a practical tolerance. Exact equality on floating pressures may be too strict; a small tolerance should be used for pressure comparisons.
- If refuel pulse width is not exposed in the same workflow as refuel pressure, the first version can guide pressure-only adjustment and record pulse width for traceability.
- The app should avoid making a failed/unclear result block all printing forever. The print-array bypass path is the intentional escape valve.

## Rollback Plan

Because the proposed implementation should be Python-only and should not alter firmware/protocol behavior, rollback should be straightforward:

1. Disable the post-apply prompt.
2. Disable the print-array refuel-check guard.
3. Hide or remove the manual refuel check dialog entry point.
4. Leave recorded check history as inert metadata, or remove the model fields in a follow-up cleanup.

Operators can continue using the existing manual keyboard shortcuts throughout rollback.
