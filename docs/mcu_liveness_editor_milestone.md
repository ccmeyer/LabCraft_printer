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
commands against stale GUI state. Each reader stamps frames with its generation
and an increasing sequence. Dispatch waits for the contiguous watermark of
completed handlers to reach the reader's received count; it cannot resume from
an earlier ACK while a later received fault remains queued. Replaced-generation
callbacks are ignored, including reader-stop notifications. Reentrant processing
cannot skip unfinished handlers, and failed handlers or stopped readers block TX.
Real silence keeps the existing timeout, snapshot, cleared host queue,
blocked transport and explicit reconnect behavior. No automatic MCU reset.

Editor -> optimization worker -> detached ExperimentModel -> validated allocation,
generated reactions and verified staged files -> guarded GUI publication. The GUI
checks source bytes/destination, renames the staging directory and adopts ordinary
Python state without repeating allocation validation, generation or serialization.
The job manager cleans up owned staging files even after late cancellation or
owner destruction. No worker QObject is installed on the GUI thread.
No controller or firmware calls are needed for design computation. Cancellation
or stale source must publish no copy. Loading snapshots exact persisted model
inputs; UI control rounding is not applied to a loaded design's allocation.
No protocol, firmware, calibration, machine-data routing or release metadata changes.

The response timeout remains 2.5 seconds. If the entire Python process, including
the serial reader, cannot run, fresh reception cannot be established; this change
does not grant an unbounded grace period or suppress real communication loss.
Queued status processing and physical MCU receipt remain distinct from proof of
the cause of the September 9 incident. Final source verification, directory rename
and result display still occur on the GUI thread; their latency is included in
the copy heartbeat test and covered by passive diagnostics.

Expected files: `FreeRTOS-interface/{Machine_FreeRTOS,App,OptimizationJobs,Model,View}.py`,
focused tests under `tests/`, this plan and `README.md`.

## Qualification and rollback

Windows regression tests use fake serial and offscreen Qt only. Before release:
commit/push the reviewed revision, then use the documented Pi Status -> Sync ->
Validate/no-hardware wrappers. A connected editor/save campaign requires fresh
attended authorization and the repository's restoration/postflight procedure.
Do not modify the running production session for qualification.

Rollback uses the previous reviewed application revision or reverts this PR as a
whole. Do not remove the dispatch watermark while retaining reader-side liveness:
that combination reintroduces the review's confirmed fault-ordering defect.
No data migration or firmware rollback is required.
The original incident must not be described as conclusively reproduced unless
new evidence establishes that link.

## Independent review corrections

The independent review of `e4c02712` identified an unsafe ACK/fault backlog
ordering, precision loss from rebuilding loaded inputs from controls, and repeated
GUI-thread computation during copy publication. The implementation now uses the
completed-handler watermark, a direct model-input load job, and worker-prepared
copy files/state described above.

New regression coverage includes mixed ACK/reset and ACK/status-fault ordering,
old status/ACK/reset/stop callbacks across reader replacement, failed and reentrant
handlers, and exact synchronous/background load equivalence for 10.04 nL droplets
and 249.04 nL streams with Auto Update disabled. Copy tests cover late cancellation,
close requests, changed source bytes/model, occupied destination, active
calibration rejection and staged-file write failure.

A 10,000-row, 12-reagent uploaded copy test measures Qt heartbeats through job
submission, worker computation, publication and final display restoration. It
requires a maximum gap below 250 ms and verifies that allocation validation and
reaction generation each occur once, on the worker. A focused run measured 57 ms
submission, 16 ms publication and a 154 ms maximum heartbeat gap. These Windows
measurements do not qualify Pi timing or establish the original incident's cause.

## Validation results

### Disconnect dispatch correction after review of `1ad57a5d`

The review identified that the completed-frame wrapper could pump pending motion
after `BYE_ACK`, even though Disconnect had stopped the execution timer. A new
fake-serial regression reproduces `GOODBYE -> ABSOLUTE_XY` on `1ad57a5d` and
observes only `GOODBYE` with the correction.

The call path is View Disconnect -> Controller workflow interruption -> Machine
shutdown -> firmware GOODBYE handling. The Model receives the disconnected state
after teardown; it does not gate serial dispatch. Firmware accepts ordinary
commands into its queue while paused, so the host must close its dispatch gate
before writing GOODBYE, rather than relying on firmware pause or timer shutdown.

Disconnect now invalidates transport readiness, stops the watchdog and dispatch
timer, and cancels outstanding ACK/pause/clear callbacks before sending GOODBYE.
Connection and reset-recovery entry points remain blocked during shutdown. Delayed
reset reports are recorded but cannot replace shutdown ACK waits with a HELLO.
Teardown clears the host queue and leaves transport unready. A fresh successful
HELLO and its first status frame are required before new queued work can dispatch;
the existing reception-generation/watermark guards still apply. A serial exception
or GOODBYE write failure closes the transport and permits explicit reconnect.

Seven new cases cover the exact review reproduction, all combinations of BYE_ACK
and BYE_DONE delivery/timeouts, delayed status/reset/HELLO callbacks, repeated
Disconnect, reconnect during shutdown, old callbacks across connection replacement,
serial failure, and dispatch attempted from inside the GOODBYE write. Tests also
verify that the previous queue is discarded and fresh motion dispatches after the
new handshake. The focused gate passed **144 tests**, including the composed
simulated disconnect workflow (`--run-sil-lifecycle`), with 30 deprecation warnings.

The final full Windows suite passed **6,475 tests, 180 skipped**, with 637
deprecation warnings, in **9m37s**, using the repository environment and a unique
external temporary directory/JUnit report. All seven new regressions are included.
No application or test code changed after the full run started. `git diff --check`
also passed.

The correction is application-only. No firmware, wire protocol, machine data or
release metadata changes are needed. Pi and attended qualification remain pending.
Rollback remains the complete PR rollback described above; removing only this
shutdown guard would restore the confirmed late-dispatch defect.

### Earlier milestone validation

The full Windows suite on the review-fix application code passed: **6,467 passed,
180 skipped**, with 637 deprecation warnings, in 13m38s. It used the repository
Windows environment, a unique external `--basetemp`, and an external JUnit report.
No application code changed after that run started.

A final owner-destruction cleanup regression added during the full run passed
separately (1 passed). Earlier focused gates passed 293 affected tests and then
18 final failure/transition and heartbeat cases; these overlap the full suite.
`git diff --check` passed.

Coverage includes genuine silence, received-but-undelivered frames, mixed
ACK/fault ordering, stale connection callbacks, failed/reentrant handlers, exact
saved-input loading, droplet/stream preservation, staged-copy cancellation and
failure cleanup, and heartbeat timing through final copy publication/display.
Tests use simulated serial and offscreen Qt only.

Pi qualification and an attended connected campaign remain release gates;
Windows tests do not qualify the live printer. No Pi session, firmware, release
metadata or release tag was changed by this milestone. The original incident's
precise cause remains unconfirmed.
