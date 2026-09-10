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

### Large-copy Pi responsiveness follow-up

No-hardware qualification of `3876495e` found a 382 ms maximum Qt heartbeat
gap for the 10,000-row, 12-reagent copy; five isolated repeats measured
432-442 ms, failing the unchanged 250 ms limit. The other 212 focused Pi
tests and all nine standard baseline optimizer workloads passed.

Profiling the unchanged revision traced about 141 ms per lock-state refresh
to parsing the entire saved design solely to enable Create Editable Copy.
Copy completion and control restoration both performed that read. The
measured completion callback took 358-369 ms; guarded model publication
itself took only 30-31 ms.

Availability refresh now checks the consistent saved file/folder and file
existence without reading design contents. The copy action reads the file
once and validates its object/metadata structure before prompting or
submitting work. An existing malformed file can therefore leave the button
enabled, but clicking it reports an error and creates nothing. The worker
and final publication retain their allocation and exact source-byte guards.
No editing, gripper or execution interlocks were removed.

Regression tests prohibit file reads during repeated availability refreshes,
check that a removed source disables copying, and reject malformed/replaced
contents before any prompt, job or destination is created. The existing
large-copy heartbeat limit remains 250 ms through final UI restoration.

The first correction passed 110 focused Windows tests. Repeated Pi tests
still failed (380-441 ms): profiling isolated a second pause in allocation
input fingerprint preparation. Building all uploaded reaction documents
without checkpoints allowed garbage collection and serialization to hold
up Qt consecutively. Per-row cooperative checkpoints and a checkpoint
before hashing now separate those phases and allow cancellation during
preparation. Fingerprint contents, canonical encoding and allocation
validation are unchanged. A regression checks equal controlled/uncontrolled
documents and hashes, and cancellation before visiting the next row or
hashing the document.

Ordinary repeats still exposed 433-454 ms gaps. Sampling thread stacks
without wrapping application methods reproduced 459 ms across consecutive
input JSON decode/encode/decode operations and 398 ms across source
decode/hash preparation. Worker JSON decoding now uses the standard
parser's object hook for cooperative checkpoints; serialization and
verification steps also yield between their large operations. Object values,
source hashes and serialization validation remain unchanged. Tests cover
text/byte decoding equality and cancellation before parsing the remaining
document.

Final qualification on application/test revision
`07b256e9987ce02f4b29fa6207168c7e44fe4cb2` passed:

- Windows full suite: **6,488 passed, 180 skipped**, 637 warnings, **10m28s**;
  JUnit has zero failures/errors. Repository environment and unique external
  temporary directory; application/test files stayed unchanged throughout.
- Pi focused suite: **262 passed**, 22 warnings, **2m10s**, including the
  composed simulated disconnect lane and editor interlocks.
- Five ordinary Pi large-copy repetitions: **238, 237, 237, 238, 230 ms**
  maximum heartbeat gaps, all below the unchanged **250 ms** limit.
  Startup was 187-190 ms and model publication 30 ms.
- Nine standard baseline optimizer workloads passed, with one warm-up and
  five measured runs/cancellations per workload. Maximum heartbeat was
  **171.6 ms** and maximum cancellation **36.5 ms**.
- Wrapper offscreen application smoke passed, exit zero, with no forbidden
  hardware access. Final Validate -> Status confirmed unchanged production
  checkout/data, released firmware state, shared package inventory, workflow
  binding and retained worktrees, and no related Pi processes. The development
  store gained only the two expected smoke-session evidence records.
- `git diff --check` passed. The follow-up commit recording these results
  changes documentation only; the Pi remains clean/detached at the exact
  qualified application/test revision above.

External Windows evidence is under
`C:\Users\conar\AppData\Local\Temp\labcraft-pr3-copy-fix`
(`QUALIFICATION.md`, `qualification-summary.json`, `pi-evidence.zip`, and
wrapper receipts). Raw final Pi test/benchmark evidence is in the external
development-workflow sessions `pr3-copy-fix-copy-20260909T235731Z-02e312da`,
`pr3-copy-fix-focused-20260909T235901Z-bceb88cc`, and
`pr3-copy-fix-baseline-20260910T000128Z-5c90b2a9`.

This closes the measured large-copy pause. It does not establish the original
MCU disconnect's cause or qualify physical hardware. Independent review of
this follow-up and a freshly authorized attended connected campaign remain
pending. The full realistic fixture matrix and memory lane were not run.

The call path is editor UI -> background job -> detached model -> guarded
publication -> UI refresh; Controller, transport and firmware are unchanged.
Rollback can revert this performance follow-up alone while retaining every
previous MCU dispatch and teardown protection. No data migration is needed.

### Absent execution timer correction after review of `996a0f97`

Reset MCU follows View -> Controller.reset_mcu_board -> Machine GPIO reset and
reset_board cleanup. Normal disconnect completion calls Controller.reset_board,
which performs the same Machine timer cleanup and updates the Model's connection
state. The execution timer is absent until a successful HELLO recreates it.
The review found that the shutdown dispatch guard called stop_execution_timer
unconditionally, and that method dereferenced the absent timer, preventing GOODBYE
and leaving the disconnect latch set with an open serial port.

stop_execution_timer now tolerates a None timer, preserving all dispatch guards.
Four regression cases use the actual Controller reset/disconnect methods and its
disconnect-completion cleanup connection, with fake GPIO and serial endpoints.
Both Reset MCU -> Disconnect and completed teardown -> reconnect -> Disconnect
before HELLO_ACK failed with the reported AttributeError on `996a0f97`.
They now complete through ACKs or timeouts, close serial, clear pending work and
the shutdown latch, tolerate repeated teardown, and reconnect successfully with
a recreated timer. Queued motion remains blocked during shutdown and resumes only
after the subsequent handshake and status.

The focused gate passed **213 tests**, including the earlier late-motion
regressions, composed simulated disconnect, background optimization and editable
copy coverage, with 30 deprecation warnings. The production diff is one guarded
condition and an explanatory comment; protocol, firmware and shutdown timeouts are
unchanged. Pi and attended qualification remain pending. Use the complete PR
rollback described above rather than removing the shutdown dispatch guards.

The final full Windows suite passed **6,479 tests, 180 skipped**, with 637
deprecation warnings, in **9m35s**. It used the repository environment and a unique
external temporary directory/JUnit report. All four new lifecycle cases are
included, and application/test code remained unchanged throughout the run.
`git diff --check` passed.

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
