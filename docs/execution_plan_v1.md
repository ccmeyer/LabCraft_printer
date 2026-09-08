# Execution Plan v1

## Purpose

`execution_plan.json` is the machine-readable snapshot of an experiment's
derived execution plan. It is separate from the authored design, progress
counters, and human-readable CSV exports.

Slice 3 writes the initial prepared plan when a fresh experiment is finalized.
Slice 4 adds immutable revision history, durable execution locking, and
calibration revisions without modifying the authored design.

## Schema identity

- `schema_name`: `labcraft.execution_plan`
- `schema_version`: `1`
- UTF-8 JSON object
- Exact effective volumes are stored as JSON numbers without display rounding.
- A v1 reader rejects unknown fields in execution-critical objects.
- Unsupported schema names or versions are rejected rather than interpreted by
  fallback logic.

Dynamic keys under `stocks` and `wells` are part of the schema. Their associated
records must contain exactly the fields documented below.

## Canonical structure

```json
{
  "schema_name": "labcraft.execution_plan",
  "schema_version": 1,
  "plan_id": "f33cf5d6-2f38-4ca7-86fd-74f73baac81d",
  "plan_revision": 1,
  "state": "prepared",
  "design_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "created_at_utc": "2026-07-17T12:00:00Z",
  "updated_at_utc": "2026-07-17T12:00:00Z",
  "locked_at_utc": null,
  "lock_reason": null,
  "plate": {
    "name": "shallow-384_well_plate",
    "rows": 16,
    "columns": 24
  },
  "volume_basis": {
    "target_printed_volume_nL": 2500.0,
    "final_reaction_volume_nL": 2500.0,
    "design_optimization_tolerance_nL": 50.0
  },
  "stocks": {
    "PURE MM_1.11_x": {
      "factor_name": "PURE MM",
      "option_name": null,
      "reagent_name": "PURE MM",
      "concentration": 1.11,
      "units": "x",
      "printing_mode": "stream",
      "intended_volume_nL": 60.0,
      "effective_volume_nL": 143.59278258103592,
      "printer_head_id": null,
      "calibration_record_key": null
    }
  },
  "wells": {
    "C3": {
      "reaction_id": "R1",
      "reagents": {
        "PURE MM_1.11_x": {
          "target_dispenses": 16
        }
      },
      "expected_printed_volume_nL": 2297.4845212965747
    }
  }
}
```

## Field authority

### Plan identity and lifecycle

- `plan_id` is a canonical UUID that remains stable across revisions of one
  finalized execution plan.
- `plan_revision` is a positive integer. The first durable lock and every
  distinct applied execution calibration increment it.
- `state` is one of `prepared`, `active`, `completed`, or `aborted`.
- A `prepared` plan has null lock fields. Every other state requires a UTC lock
  timestamp and nonempty lock reason.
- `design_sha256` links the execution plan to a caller-selected canonical frozen
  design payload. Slice 1 supplies deterministic hashing but does not choose the
  design projection.

### Plate and volume basis

- Plate dimensions are positive integers. Every well ID must use uppercase plate
  notation and fall inside those dimensions.
- The target and final reaction volumes are positive finite numbers.
- The design optimization tolerance is a nonnegative finite number. Initial
  design optimization continues to enforce its volume policy. Later calibration
  treats target printed volume plus this tolerance as a warning threshold, not
  an Apply limit.
- Calibration warning evidence distinguishes printed volume from projected final
  mixture volume. Planned non-printed volume is inferred as
  `max(0, final reaction volume - target printed volume)` and is added to the
  recalculated printed total for the projection. The intended final volume is
  diagnostic context, not a physical-capacity or Apply gate. Physical well
  capacity is intentionally not modeled by v1.

### Stocks

- A stock ID is unique within a plan and is the lookup key used by wells.
- Concentration is finite and nonnegative.
- `printing_mode` is `droplet` or `stream` in v1.
- Intended volume may be null. Effective volume is required, finite, positive,
  and never rounded for display.
- Printer-head and calibration-record references may be null before calibration.

### Wells

- A well contains a reaction ID and zero or more stock target counts.
- Target counts are nonnegative integers; booleans are not integers for schema
  purposes.
- Every referenced stock must exist in the plan.
- `expected_printed_volume_nL` must equal the sum of each target count multiplied
  by its stock's effective volume. Validation allows only a small floating-point
  comparison tolerance: `max(1e-6 nL, 1e-9 * expected volume)`.

## Strict validation policy

Readers reject:

- Unknown or missing fields.
- Duplicate JSON object keys.
- Unsupported schema names or versions.
- Invalid UUIDs, hashes, timestamps, states, printing modes, or well IDs.
- Boolean numeric values, NaN, infinity, invalid signs, and inconsistent totals.
- References to undeclared stocks.

A validation failure never causes the source document to be rewritten. Future
non-execution annotations must be introduced through a versioned, explicitly
non-authoritative field; v1 has no free-form extension container.

## Non-authoritative stock preparation worksheet

`stock_prep.json` is an optional operator worksheet stored beside the experiment
files. It is not part of the execution bundle, design hash, immutable revision
history, resume checkpoint, calibration evidence, or active-runtime file identity
set. Creating, changing, losing, or corrupting this file cannot change execution
eligibility.

The worksheet uses schema name `labcraft.stock_prep`, version `1`, and records the
current plan ID/revision, dead-volume and calibration extras, plus per-stock
preparation volume and source concentration keyed by the exact execution stock
ID. A draft without a plan uses a null plan ID and revision `1`. Target
concentration and total required volume are always derived from the current plan
and are never accepted from the worksheet. PREPARED and ACTIVE
executions may update the file atomically; COMPLETED, ABORTED, and recorded legacy
executions expose the calculator without persistence.

Older `stock_prep` values embedded in `experiment_design.json` remain frozen for
hash compatibility. When no sidecar exists they may seed the worksheet in memory,
but the calculator never rewrites the embedded field. A plan-ID change carries
worksheet inputs only for exact matching stock IDs. Editable copies and duplicate
experiments begin without a sidecar.

## Persistence

The slice 1 writer:

- Requires the parent directory to exist.
- Validates the full immutable model before writing.
- Writes a temporary file in the destination directory.
- Flushes and syncs it before atomically replacing the destination.
- Removes the temporary file after failure and leaves an existing destination
  unchanged.
- Uses deterministic sorted-key, two-space-indented JSON with a trailing newline.

## Design-time stock resolution policy

New experiment designs default to resolution-first stock allocation. The
optimizer preserves requested concentration levels where its deterministic
bounded search can do so. The advanced editor setting
`allow_avoidable_target_grouping=true` explicitly selects concentration-first
allocation, which may group requested levels to reduce stock concentration or
printed volume; unavoidable grouping is always reported.

Designs saved before this metadata field existed retain their historical
concentration-first behavior when opened for editing. The model normalizes the
missing field to `true`, identifies that choice to the editor as compatibility
behavior, and persists the existing boolean on the next save or editable copy.
Explicit `true` and `false` values are never reinterpreted. Authoritative and
recorded execution plans always reload their frozen stock identities and counts
without consulting this design-time optimization policy.

Resolution-first allocation completes the same single-stock search in both
modes before spending work on optional two-stock improvements. When single-stock
optimization succeeds, enabling two-stock mode cannot replace that baseline
with a worse allocation under the full resolution rank. A zero-loss baseline
using only single stocks skips pair enumeration. Designs requiring two stocks
for feasibility retain the existing bounded feasibility fallback.

The resolution phases share a deterministic 12,000-work-unit allowance. After
the baseline, at least half the remaining work is reserved for candidate
preparation and combined search. The rest is divided equally among eligible
reagents/options, with remainder units assigned in canonical key order.
Collapsed options are scanned before volume donors; fixed stocks are excluded
and existing pair candidates are reused. Unused scan allowance remains
available to combined search. Exhaustion or a handled search failure retains
the best allocation already validated, including accepted pair improvements.

Diagnostic result fields `stock_allocation_baseline_rank`,
`stock_allocation_baseline_work`, `stock_allocation_pair_work_by_key`, and
`stock_allocation_combined_work` expose these phases. Per-key entries use
JSON-encoded `[factor, option]` keys and report `limit`, `used`, and
`quota_exhausted`. `pair_quota` identifies a limited scan rather than claiming
the candidate space was exhausted. Work and candidate counters accumulate
across phases. When no single-stock allocation is feasible, the baseline phase
starts from the feasible incumbent, which can already contain two stocks.

Candidate dominance filtering uses NumPy batches while preserving the original
sequential decisions, `1e-12` comparison tolerance, and candidate identities and
ordering. Each candidate is compared only against earlier retained candidates;
fixed stocks bypass dominance filtering. Each temporary comparison matrix is
at most 256 candidates by 256 criteria (65,536 elements). Numeric storage grows
linearly with candidate count times criterion count, without constructing a
candidate-by-candidate matrix. Worst-case comparison work remains quadratic;
batching reduces Python overhead rather than changing the search space.

The diagnostic fields `stock_allocation_dominance_pairs_evaluated` and
`stock_allocation_dominance_blocks_evaluated` accumulate actual filtering work
across resolution phases. Pair counts include every retained candidate in an
evaluated row batch, even when an early match could end a scalar scan sooner.
`stock_allocation_dominance_max_block_elements` records the largest temporary
comparison block. These counters do not consume the existing resolution work
allowance or change stopping decisions; paths that do not filter report zero.

Well shading represents the selected stock's target dispense count relative to
its maximum across the plate. Opacity is clamped to the display range and encoded
as ARGB hex: low alpha values must not become fully opaque through Qt's special
interpretation of `rgba(...,1)`. This display encoding does not modify counts,
concentrations or execution progress; tooltips retain exact numeric counts.

Editor updates and import feasibility calculations run on one dedicated Qt
worker thread. The worker owns a detached input snapshot and computes both the
allocation and generated reaction data. It cannot write experiment files or
access live runtime bindings. The main thread publishes complete results only
while the request's inputs, owner, and editing interlocks remain current.
Explicit calculation and import jobs pause design inputs and dependent actions; Cancel
retains the previous published results and leaves the edited inputs dirty.
Save, preview, and finalize continue only after successful publication.

Automatic calculation waits while editing the same field. Leaving that field,
including Tab into the next cell, starts the existing 350 ms debounce. Typing in
the next field stops pending work and cooperatively cancels an obsolete job.
Automatic jobs leave input fields editable, but dependent lifecycle actions stay
locked. One pending flag coalesces edits behind the single worker; replacement
work starts only after the current field is committed and the worker settles.
Opening another dialog or switching applications does not commit an unfinished
edit. Incomplete target tokens are rejected instead of silently dropping them.

Publication checks the model snapshot fingerprint, session, current interlocks,
editor revision, and raw control values. Even a programmatic control change
without an edit signal invalidates the result. Obsolete results leave previous
allocations intact and inputs dirty. Explicit Recalculate Stocks, Save, preview,
and finalize retain their input locks, validation and continuations. Cancel or
close consumes the pending automatic request; it does not restart without
another edit or explicit request. Turning Auto off prevents pending replacements.

A permanently allocated footer in the editor and import wizard shows quiet
"Updating" text immediately. On the first half-second refresh at or after 500 ms,
it shows the current phase in blue and starts the progress animation. Jobs that
finish sooner never animate; completion and cancellation suppress late busy
feedback. Cancel and operation guards take effect immediately, independently
of this presentation delay. Normal processing leaves Design Information and
the stock table neutral. Result freshness does not imply an error; actual input,
computation, or publication errors are shown immediately in red.
After one second the footer also shows total elapsed job time and, where
available, one activity count: single-stock candidates considered, stock pairs
considered, candidates filtered, complete allocations evaluated, or reactions
generated. Search counters describe work in the current phase, not percent
complete or a prediction of remaining time. Only reaction generation has a
known total. A bounded shared snapshot coalesces activity; Qt refreshes the
footer at most twice per second. Status, a short progress bar, and Cancel occupy
one fixed-height row, with the full status available in a tooltip. Their space
remains allocated when idle, so starting and stopping jobs do not move the
window contents. The editor's initial height uses available desktop space up to
1,000 logical pixels, leaving room for window decorations. Its settings and
design tools scroll vertically rather than compress when Advanced Settings is
expanded or the window is short. Experiment lifecycle actions, including Save
and Finalize, stay outside that scroll area. It never opens or activates a
separate progress window. Canceling remains visible until
the worker's terminal outcome, and late phase updates cannot overwrite it.

Automatic editor stock calculations reaching three seconds pause future
automatic updates, without interrupting the current job. A persistent notice
explains that the user can make several edits and click **Recalculate Stocks**.
This action updates both stocks and reactions and does not save. The trigger
measures the actual optimizer call, including candidate preparation, but
excludes dispatch, exact output validation, reaction generation, publication,
and table refresh. Manual actions, import calculations, and layout/count-only
allocation reuse cannot trigger this policy. Threshold checks use an independent
monotonic clock and do not consume optimizer work or affect search decisions.

Re-enabling Auto-update after a slow pause explicitly opts in for the remainder
of that design session. Successful New, Load, editable-copy creation, Import
Apply, or Clear Imported Design resets the pause and override, restoring the
underlying user preference; an explicit Off remains Off. Ordinary edits, saves,
failed replacements, and canceled calculations do not reset this policy.
These are UI session flags only, with no persisted-schema or calibration change.

The implementation/validation plan for these additions is: extend the existing
computation control with coalesced activity and one-shot timing; use it from
actual search/generation counters; add delayed UI details and session-local
slow-update handling; verify thresholds, stale notices, cancellation and
preferences with deterministic tests; then qualify complete manual, automatic,
and import interactions on Windows and the Pi with the existing 250 ms
heartbeat and one-second cancellation gates. Evidence stays outside worktrees.
Rollback is a revert of the feature commit followed by normal development sync;
no experiment-data migration or calibration-history rewrite is required.

Optimizer qualification now distinguishes sparse regression inputs from dense
mixtures and manual group designs. The shared qualification catalog records
authored and unique compositions, active and varying reagents, target counts,
groups, volumes, and fixture hashes. Real experimental CSVs remain external.
Both stock modes are checked against their synchronous counterpart and, where
single-stock optimization succeeds, against its complete result rank. Separate
arithmetic checks verify counts, concentrations, fill, exact uploaded row/well
ordering, and independent manual Cartesian/choice compositions. A dedicated
64-reaction fixture requires three simultaneous two-stock allocations and zero
lost levels; merely enabling two-stock mode is not evidence of pair exploration.

The opt-in realistic benchmark records measured outcomes and input limitations,
including the import wizard's mode-default ejection volumes. Five measured
interactions follow one warm-up; early cancellation and observed candidate-phase
cancellation have separate evidence. Unobserved short phases are explicitly
identified rather than credited as exercised. Timing gates remain 250 ms per
heartbeat gap and one second for cancellation. A failed fixture, comparison,
input-coverage check, or responsiveness gate blocks qualification; this test-only
extension does not change production search decisions. README documents the
external fixture layout, selectors, evidence, watchdog, and Pi workflow.

Cancellation is cooperative, including candidate preparation, filtering,
combined search, and reaction generation. Brief worker yields let Qt's Python
callbacks acquire the interpreter lock; neither yielding nor cancellation
checks change search budgets or ranking. Initial dispatch follows pending UI
repaints, so disabling controls does not overlap worker garbage collection.
Closing an active editor cancels and
drains its job before completing normal unsaved-draft handling. Application
shutdown drains the worker without forcibly terminating a thread.

The synchronous model APIs remain available to calibration and non-UI callers.
Disk persistence and machine communications retain their existing execution
model. Background calculation is not a hard latency guarantee: qualification
measures complete UI interactions separately from optimizer compute time.

The 75 ms resolution target is diagnostic, not a wall-clock deadline. Work
units have different costs depending on target counts and reaction structure.
`optimizer_seed_elapsed_ms` includes seed/feasibility work outside the shared
resolution allowance; `stock_allocation_elapsed_ms` covers resolution phases;
`optimizer_total_elapsed_ms` covers the optimizer through result construction,
excluding stock-update subscribers. End-to-end benchmarks additionally measure
the complete interaction, including UI preparation and result publication.
Windows timings do not qualify Raspberry Pi responsiveness.

## Initial creation in Slice 3

- **Finish/Apply** creates the initial plan only after reactions have been
  assigned to their final runtime wells and before progress or key files are
  generated.
- Ordinary design saves, optimization previews, initialization, duplication,
  legacy loading, and merely opening a folder do not create a plan.
- The initial plan uses a new UUID, revision `1`, state `prepared`, equal
  creation/update timestamps, null lock fields, and null calibration/head
  references.
- The design hash is calculated from the exact parsed payload already persisted
  in `experiment_design.json`. Wells and targets come from the finalized runtime
  assignment, while exact concentrations and effective volumes come from the
  stock plan rather than rounded CSV headers.
- A valid existing prepared revision-1 plan is reused byte-for-byte only when
  its design and execution content match. Invalid, active, revised, or
  conflicting files are never overwritten.

Newly finalized progress files link to their plan with this metadata envelope:

```json
"__execution__": {
  "schema_version": 1,
  "plan_id": "f33cf5d6-2f38-4ca7-86fd-74f73baac81d",
  "plan_revision": 1
}
```

The reference has exactly these three fields. Well-oriented progress readers
exclude all `__*` metadata keys from reaction iteration.

Initial plan construction and persistence fail closed. A failure prevents a
successful runtime handoff and printing, clears partially loaded runtime
assignments, and leaves existing plan files unchanged. If the plan was already
written before a later progress/key failure, it remains as a prepared snapshot
and an identical retry reuses it.

## Durable locking and revisions in Slice 4

New finalizations also persist `execution_plan_revisions/revision_000001.json`.
The directory is immutable history: filenames are zero-padded, revisions are
contiguous from 1, and an existing revision can only be reused when its parsed
content is exactly equal. `execution_plan.json` is an exact mirror of the
latest history entry.

Before an execution-affecting calibration process or an accepted print request
can issue hardware actions, a prepared plan is durably changed to active:

- revision 1 `prepared` becomes revision 2 `active`;
- the reason is `calibration_started` or `printing_started`;
- the first lock timestamp and reason never change in later revisions; and
- progress is updated to reference the active revision before hardware starts.

Nozzle focus, trajectory, and other non-volume setup do not lock a plan by
themselves. A failed or stopped calibration does not unlock an already active
plan. If revision, current-mirror, progress, or sidecar synchronization fails,
the model retains a blocking synchronization error and hardware actions remain
disabled. Immutable artifacts that were written before a later failure are
retained; an exact retry adopts them and repairs the remaining mirrors instead
of creating another revision.

Result-producing pressure-sweep, stream-volume, and manually started droplet
search processes use that durable lock while an authoritative execution is
`prepared` or `active`. After a same-session execution becomes `completed` or
`aborted`, those processes remain available as diagnostics and record their
normal calibration observations without requesting another execution-plan
lock. Terminal plans and their progress, resume, revision-history, and
execution-calibration artifacts remain immutable, and a diagnostic result
cannot be applied to the terminal execution. Reopened historical or legacy
executions remain analysis-only and cannot start calibration processes.

Loading an active new-format plan validates the design hash, immutable history,
latest mirror, progress reference and targets, and calibration references. It
does not rewrite any artifact. Slice 5 extends this inspection into the explicit
activation and resume flow described below.

## Execution calibration sidecar

`execution_calibrations.json` uses schema
`labcraft.execution_calibrations`, version 3. Its root contains the schema
identity, `plan_id`, deterministic calibration records, manual-refuel checks,
and immutable `volume_warning_audits`. Readers continue to accept version 1
and 2 sidecars as empty warning-outbox inputs. Unknown, missing, malformed, or
duplicate fields fail closed.

Calibration-record UUIDs are deterministic UUID5 values derived from the plan,
stock, printer head, source-result fingerprint, exact effective volume,
printing mode, pulse width, and pressure. Recording time is preserved but does
not alter identity. Each calibrated stock points to its record through
`calibration_record_key`; stream manual-refuel checks point to that same record
and are stored only in the sidecar.

Applying a distinct calibration creates the next immutable plan revision. It:

- verifies the unchanged `experiment_design.json` hash and frozen execution
  identities;
- requires the exact loaded stock identity and rejects a selected stock
  that already has positive printed progress;
- for a two-stock reagent with neither leg printed, jointly re-quantizes both
  committed count maps; once the companion has any printed progress, freezes
  its **entire** map, including remaining planned drops in every well, and
  re-quantizes only the selected stock's residual contribution;
- changes calibration metadata only on the measured stock; the companion stock
  retains its concentration, effective volume, printing mode, printer-head
  reference, and calibration-record reference;
- preserves every unrelated non-fill target and permits only the calibrated
  stock, its one related companion, and fill to change per-well counts;
- preserves all counts, including fill, in wells selecting another choice-group
  option; missing reaction records or positive calibrated-stock counts in a
  reaction omitting that option remain integrity errors;
- recalculates fill in wells where fill has not started, reducing it to zero
  when calibrated non-fill volume already meets or exceeds that target;
  preserves the complete fill allocation in a well once any fill has printed;
- recomputes exact expected well volumes without re-running the design-time
  optimizer.

The supported finalized workflow is **calibrate A → print A across the array →
calibrate B → print B**, in either stock order. Save/reload and explicit runtime
activation may occur between stages. Partial companion printing is supported;
its remaining plan is preserved, not recalculated using only the printed drops.
Repeated calibration is allowed until the selected stock prints.

Preview and Apply use the same execution calculation. Each fixed contribution
uses its committed count and current calibrated effective volume. Integer counts
minimize absolute concentration error, then printed reagent volume, count churn,
and the count tuple for deterministic ties. Zero additional drops is valid,
including when the fixed contribution already exceeds the target. Approximation,
grouped target levels, and nonmonotonic achieved levels are diagnostics, not
rejection conditions. The unchanged ejection-volume envelope (1–250 nL), valid
measurements, stock identities, frozen design, calibration references and
execution integrity remain mandatory. Neither the recorded design threshold nor
the final reaction volume independently rejects an otherwise valid measurement.

The preview's achievable concentration includes starting concentration plus both
actual calibrated stock contributions, divided by the frozen final reaction
volume basis. Its signed deviation is achieved minus target. Expected printed
well volume includes unrelated reagents and the preserved or recalculated fill.
CSV concentration exports likewise describe planned achieved concentrations,
not an assertion that targets were met or that every planned drop has printed.

Two-stock previews carry the exact plan and durable/live progress context.
Apply rejects stale previews, unsaved live progress and pending print commands.
The context and allocation constraints are rechecked before persistence. Caught
two-stock publication failures restore the prior plan mirror, calibration
sidecar, checkpoint, exports and runtime, removing only the unpublished candidate
revision created by that attempt. Earlier immutable revisions and experiment
history remain untouched. Notifications and audit delivery follow successful
publication. If rollback itself fails, the runtime is invalidated and the error
requires recovery; a process crash/power loss still uses the existing durable
execution recovery path rather than this in-process rollback.

Before finalization, a mutable two-stock calibration saves the complete stock
allocation. Later single-stock, fill, or two-stock calibrations refresh that
allocation within the same guarded transaction, preserving earlier measured
volumes, stock identities, and calibration records across editable-design
reload and re-optimization. An active allocation must match the current inputs
and live stock plan before calibration starts; inconsistent active allocations
are rejected, and unrelated calibrations do not reactivate inactive allocations.
Allocation export, runtime rebinding, or save failures restore the prior model,
runtime, and file state through the existing transaction rollback.
Mutable design optimization retains its existing reachability and grouping
policy; the execution constraints above apply to finalized executions.

Qualification lives in `tests/test_execution_two_stock_workflow.py`: real model,
durable print intents, runtime progress and reload paths, plus the actual dialog
preview/Apply boundary with physical settings calls excluded. It covers both
stock orders, partial and complete printing, fill states, zero/absent choices,
replicates, additional conditions, unrelated reagents, fixed overshoot, grouping,
invalid measurements, stale results and publication fault injection. Run with
the repository Windows Python, `-B -m pytest -q`, and a unique external
`--basetemp`; also run the affected execution, persistence, calibration and SIL
suites. Pi qualification requires a clean pushed exact SHA followed by the
documented Status → Sync → Validate and no-hardware launch workflow. No physical
qualification is implied by these tests.

Code rollback is a revert of the execution-aware calibration fix commit. Keep
experiment artifacts and historical revisions intact. Experiments that already
used constrained calibration retain authoritative counts and references; older
code cannot continue calibrating the second stock after companion printing.

After preview and again from the committed candidate, calibration recalculates
every well's exact printed total. A printed total above target printed volume
plus design tolerance produces a prominent, non-blocking
`calibration_volume_tolerance_exceeded` warning. Its per-well evidence includes
printed volume, inferred planned non-printed volume, projected final volume, and
projected excess above the intended final volume. None of those diagnostic
projection values blocks Apply or printing.

Each distinct successful warned application commits an immutable audit intent
inside the same mutable-design or execution-calibration transaction. The
append-only `experiment_audit.jsonl` timeline is an idempotent projection of
that authoritative evidence: identical event IDs are reused, conflicting IDs
and malformed tails are preserved as integrity errors, and missing rows are
retried after load, when the timeline opens, and before printing. Timeline
delivery failure remains visible as pending but cannot roll back calibration or
block printing. Progress preserves all added counts while targets and its
`__execution__` revision reference are atomically replaced. `key.csv` and
`concentration_key.csv` are regenerated from the committed plan, not by running
stock optimization. `experiment_design.json` remains byte-identical throughout
locking, calibration, manual-refuel checks, and retries.

Mixed-volume dispense segments remain later work. A recorded older experiment
is reconstructed without changing its folder and can be explicitly displayed
in the main window read-only. The saved plan defines plate, stocks, wells, and
targets; recorded progress defines actual added counts, with missing historical
counts displayed as zero. Merely opening or viewing an experiment never creates
or repairs execution artifacts.

## Authoritative load and resume in Slice 5

When `execution_plan.json` exists, the application no longer regenerates an
experiment from design inputs. It treats the following as one authoritative
bundle:

- immutable plan revisions and the exact latest-plan mirror define stocks,
  concentrations, effective volumes, printing modes, wells, reaction IDs, and
  target counts;
- `progress.json` defines only the added counts at those frozen targets;
- `execution_calibrations.json` defines referenced calibration and manual-check
  evidence; and
- `execution_resume.json` defines durable command boundaries for hardware
  restart decisions.

Opening a folder performs strict, non-mutating inspection. It neither creates a
resume checkpoint nor repairs files. The editor remains locked and offers an
explicit **Activate Execution** action only when the saved bundle is internally
consistent. Activation reconstructs runtime objects with the exact saved stock
IDs, well assignments, targets, and progress, without optimization,
randomization, or design writes. Derived key CSVs may be regenerated only as an
explicit activation side effect after the frozen design hash is verified.

Positive progress without `execution_resume.json` is analysis-only because the
application cannot prove whether a hardware command was in flight when the
previous process ended. Zero-progress executions may create a clean checkpoint
during explicit activation. A pending intent is repairable only when persisted
progress proves the entire commanded count was recorded; otherwise the intent
is ambiguous and hardware resume fails closed.

### Resume checkpoint schema

`execution_resume.json` uses strict schema `labcraft.execution_resume`, version
1. Its root records the plan ID/revision, session UUID, state, active stock/head,
canonical progress hash, intent array, and UTC timestamps. Each intent records
the exact well, reaction, stock, baseline added count, commanded count, optional
32-bit command sequence, status, and timestamps. Unknown, missing, malformed,
duplicate, nonintegral, or inconsistent fields are rejected.

The intent array is a bounded recovery checkpoint, not an execution-history
log. New runtime writes retain only unresolved pending intents. After
`progress.json` durably proves a command's entire recorded count, the following
resume write retires that intent instead of retaining a completed copy. The
schema continues to accept version-1 `completed` records written by earlier
releases. Passive inspection validates those records without editing the
folder; the next explicit activation verifies every record against progress
and compacts the checkpoint in its existing activation write. If progress does
not prove a legacy completion, activation fails closed. Completed-command
history is intentionally not reconstructed elsewhere because progress and the
immutable execution plan are the authoritative durable result.

For every new-format well dispense the host:

1. atomically persists a deterministic pending intent before queuing the
   dispense command;
2. records the returned command sequence when available;
3. updates `progress.json` only in the existing command-completion handler; and
4. retires the proven intent in a third atomic resume write only after that
   progress write succeeds.

If the process stops between steps, reload classification is conservative.
Progress that includes the whole intent can repair the checkpoint during the
next explicit activation. Progress that does not include it cannot distinguish
"not executed" from "executed but not recorded" and blocks resume.

A confirmed **Stop After Well** is also a durable command boundary. After the
pause watermark is reached and the firmware queue is confirmed empty, pending
look-ahead intents with command sequences beyond that watermark are discarded
and the checkpoint becomes paused. If queue clearing is not confirmed, those
intents remain pending and resume continues to fail closed.

Before hardware starts, the loaded stock, printing mode, durable printer-head
identity, and any referenced calibration record must match the latest plan. A
previously unbound, unprinted stock is bound through a new immutable plan
revision before its first dispense. Existing bindings cannot silently change.
Calibration of an unprinted stock remains available after authoritative
activation and uses the Slice 4 revision path; stocks with positive added counts
remain immutable.

## Reset, copies, archival conversion, and terminal states in Slice 6

Recorded dispense counts are physical facts. Progress clearing and the Reset
Single/All Array actions first classify the folder and fail before changing
files or runtime objects when it contains positive counts, recorded legacy
evidence, any finalized plan, or an invalid partial new-format bundle. Editing
such an experiment always uses **Create Editable Copy**; the original folder is
never rewritten.

Editable copies are built in a sibling staging directory and published by one
directory rename only after stock optimization and design validation succeed.
They retain authored factors, reagent identities, conditions, random/manual
assignments, and embedded uploaded reactions. Intended dispense volumes and
printing modes replace calibrated effective values when available. Progress,
stock-preparation completion, calibration/manual-check evidence, plan history,
resume state, keys, recordings, and analysis outputs do not transfer. The fresh
copy contains a normalized design, empty `progress.json`, empty
`calibration.json`, and a materialized uploaded-design CSV when applicable.
Calibration-copy requests are rejected because physical evidence cannot grant
authority to a new execution.

Direct read-only viewing is the normal path for recorded older experiments. A
completed reconstruction is offered as **View Completed Experiment**; partial,
stopped, or otherwise recorded history is offered as **View Older Experiment**.
Both populate the saved plate and exact progress for analysis while keeping all
printing, calibration, reset, and other hardware actions unavailable. Plate
reader analysis continues to use the original folder, and **Create Editable
Copy** creates a fresh design with no historical progress.

Legacy conversion remains an optional backend archival operation rather than a
normal editor action. It always creates a full separate copy. It copies
historical files and raw analysis data, preserves
`experiment_design.json` byte-for-byte, reconstructs normalized progress, and
persists the deterministic legacy plan as revision 1 and the latest mirror.
Compatible calibration/manual-check evidence is converted to strict sidecar
records; incomplete evidence is omitted with a warning rather than fabricated.
No resume checkpoint is created.

`legacy_migration.json` is strict schema
`labcraft.legacy_execution_migration`, version 1. It contains the migrated plan
ID, source folder and canonical design hash, SHA-256 for every relative source
file, UTC migration time, exact code/message warnings, and the permanent
`hardware_policy` value `analysis_only`. Unknown, missing, duplicate, or
malformed fields invalidate the authoritative bundle. A valid manifest always
overrides otherwise-normal resume eligibility: migrated zero-progress, active,
completed, and aborted executions can be opened only for analysis.

Active plans may end in one immutable terminal revision. `completed` requires
every added count to equal its frozen target and a clean checkpoint with no
pending intent. A refill or successful soft stop remains active. An explicit
abandonment or Controller hard abort creates `aborted`, retains recorded counts
and intents, and marks the checkpoint `uncertain`. Terminal transitions cannot
change stocks, wells, targets, design/plate facts, or first-lock metadata, and
terminal revisions cannot have successors. Exact retries reuse the immutable
terminal revision and repair later mirrors without incrementing again.

Starting **New Experiment** is also non-destructive. It requires an idle array
runner, an empty command queue, and no printer head in the gripper, then detaches
the previous folder unchanged and clears only in-memory runtime/execution state
before creating the fresh design folder.

## Import publication and table responsiveness

Import Apply prepares factors, explicit rows, stock settings and validated
allocation reuse on the detached optimizer model. It publishes those inputs
and generated outputs together only while the original editor session, input
fingerprint, execution/gripper interlocks and available wells still permit the
replacement. Cancellation (including immediately before publication), worker
failure or rejected publication retains the previous design, calibration
history and saved files. Apply does not save files. The UI remains busy through
publication and display refresh, and a canceled import does not restart itself.
Once the atomic publication begins, the dialog briefly says "Finishing display
update" and removes Cancel. Control restoration runs on the next event-loop
turn; the job remains busy and shutdown waits until that step finishes.

Bulk reagent loading defers full-table sizing until all reagents are present.
The wizard composition table starts with fixed, manually resizable columns and
uniform row heights, avoiding a full content-sizing pass. The qualification
harness records main-thread Apply, publication and table timings separately
from worker phases. The application quit filter ignores unrelated widget events
before decoding their types in Python. The existing 250 ms heartbeat and one-second cancellation
gates remain unchanged. Native acceleration remains an opt-in experiment and
is not part of this application path.

Rollback is a revert of the import/UI fix followed by the normal development
synchronization workflow. No experiment or calibration-history migration is
needed.
