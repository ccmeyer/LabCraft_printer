# MCU liveness and editor responsiveness milestone

## Motivation and evidence

On 2026-09-09 at 19:42:03 UTC, rc.12 reported `mcu_unresponsive` after
2,540 ms without a main-thread frame callback. The queue was empty and no reset
report was captured. The incident's precise cause remains unconfirmed. A separate
18:56:20 UTC stack dump proves Duplicate Design ran optimization on the GUI
thread and blocked its heartbeat for 5.5 seconds.

## Implementation plan

1. Test received-but-undelivered traffic, real silence, stale callbacks and editor work.
2. Record parsed, CRC-validated frame reception in SerialReader independently of Qt.
3. Diagnose reception, callback and heartbeat ages separately; capture UI stalls at
   one second, before the unchanged 2.5-second MCU timeout.
4. Compute editable-copy allocations in the existing cancellable worker; verify
   source identity and reuse the validated allocation during transactional saving.
   Defer unrun-design load searches to the same editor worker, preserving recorded
   execution reconstruction and the synchronous model API for non-UI callers.
5. Run focused Windows communication/editor tests and broader integration checks.
6. Leave a reviewable branch with qualification gates and rollback instructions.

## Call paths and safety contract

SerialReader -> queued status/ACK/reset signal -> Machine -> Controller -> loss UI.
Reader reception is liveness evidence, not permission to ignore faults or send
commands against stale GUI state. Defer queued dispatch while callback processing
is stale. Real silence keeps the existing timeout, snapshot, cleared host queue,
blocked transport and explicit reconnect behavior. No automatic MCU reset.

Editor -> optimization worker -> detached ExperimentModel -> validated result ->
GUI publication -> staged experiment save. No controller or firmware calls are
needed for design computation. Cancellation or stale source must publish no copy.
No protocol, firmware, calibration, machine-data routing or release metadata changes.

The response timeout remains 2.5 seconds. If the entire Python process, including
the serial reader, cannot run, fresh reception cannot be established; this change
does not grant an unbounded grace period or suppress real communication loss.
Queued status processing and physical MCU receipt remain distinct from proof of
the cause of the September 9 incident. File I/O and result display still occur on
the GUI thread, now covered by shorter passive diagnostics.

Expected files: `FreeRTOS-interface/{Machine_FreeRTOS,App,OptimizationJobs,Model,View}.py`,
focused tests under `tests/`, this plan and `README.md`.

## Qualification and rollback

Windows regression tests use fake serial and offscreen Qt only. Before release:
commit/push the reviewed revision, then use the documented Pi Status -> Sync ->
Validate/no-hardware wrappers. A connected editor/save campaign requires fresh
attended authorization and the repository's restoration/postflight procedure.
Do not modify the running production session for qualification.

Rollback is a revert of the milestone commit and deployment of the previous
reviewed application revision. No data migration or firmware rollback is required.
The original incident must not be described as conclusively reproduced unless
new evidence establishes that link.

## Validation results

Initial focused gate: 89 passed (reader liveness, parser, worker/editor jobs,
duplicate-design transactions and UI freeze diagnostics). Includes a simulated
serial stream during a save computation held longer than the production timeout,
stale callbacks, corrupt frames, connection replacement, cancellation, source
changes, gripper interlock, occupied destination and uploaded-design preservation.

The full Windows suite completed in 12m56s: 6,448 passed, 180 skipped and three
failures. All three were plan-dictionary comparisons: the existing reuse validator
materializes `printing_mode: droplet`, whereas fresh optimizer plans can omit that
default. The assertions now account for the explicit default while still comparing
all allocation values; no solver behavior or calibration rules were changed.

After that adjustment and the final UI/diagnostic refinements, the affected suite
passed: 274 tests across the README's focused set plus
`test_experiment_designer_interlock.py`, `test_experiment_model_runtime_refresh.py`
and `test_stock_resolution_policy_compatibility.py`. A subsequent explicit stream
copy case also passed with the eight existing copy cases (9 passed), checking
printing mode and ejection volume after publication. The full suite was not rerun
after these focused checks. `git diff --check` passed.

Pi qualification and an attended connected campaign remain release gates;
Windows tests do not qualify the live printer. No Pi session, firmware, release
metadata or release tag was changed by this milestone.
