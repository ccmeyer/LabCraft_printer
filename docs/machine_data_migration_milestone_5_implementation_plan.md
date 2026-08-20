# Machine Data Migration Milestone 5: Guarded Location and Calibration Changes

Status: `implementation_complete`

Prepared: 2026-08-20

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:

- Milestone 1 machine-data contract `9b882141` (`verified`)
- Milestone 2 migration engine `157db800` (`verified`)
- Milestone 3 production cutover `b3cf12ad` and lifecycle correction
  `08d41bc2` (`verified`)
- Milestone 4 transaction history `6925d029` and exact-restore correction
  `f6d65fd9` (`verified`)
- Milestone 4 verification record `9a2f92e4`

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 5 inserts a pure, versioned safety assessment between a proposed
location/calibration change and the Milestone 4 transaction-intent boundary.
Every operator sees the exact prior values, proposed values, and per-axis
deltas. Hard-invalid proposals are rejected; valid but high-risk proposals
require a stronger, proposal-bound confirmation. Accepted proposals retain the
Milestone 4 guarantees: exact pre-change backup, atomic durable persistence,
immutable history, disk-before-memory installation, and immediate revocation
of changed motion targets.

The same policy supplies defense in depth at startup and immediately before
motion dispatch. A UI bypass, stale dialog, `override=True`, import, restore,
or direct Controller call cannot persist or dispatch a coordinate outside the
active machine's hard travel bounds.

At the end of the milestone:

- a capture is possible only while the machine identity, connection, homing
  state, motion trust epoch, queue state, and position telemetry are current;
- every named-location, rack-pair, and plate-quartet proposal has a frozen,
  hash-bound preview and guard assessment;
- Camera, rack, plate, and reserved machine-location changes always use the
  strong path in the initial rc.2 policy;
- an approved per-target/per-axis threshold table may classify ordinary
  changes as routine, but missing evidence never silently relaxes a guard;
- no delta threshold is described as a collision envelope;
- hard bounds and structural geometry are non-bypassable;
- cancellation and rejection produce immutable non-mutating history events;
- accepted events include the policy identity, policy hash, preconditions,
  exact deltas, hard-check results, confirmation tier, and proposal hash;
- changed targets remain blocked until a separate exact-value physical or
  service-record verification event is committed; and
- the firmware protocol, motion opcodes, firmware handlers, and path-planning
  algorithms remain unchanged.

## Scope

### In scope

- Current-position capture for named locations.
- Per-point capture for rack Left/Right and all four plate corners.
- Guarded named-location add/modify, guided rack commit, and guided plate
  commit.
- Hard validation of governed imports, restores, and exact target
  re-verification where they affect motion targets.
- Strict parsing of active `Obstacles.json` bounds and configured axis-aligned
  exclusion volumes for guard use.
- Versioned warning/strong-confirmation policy and a sanitized characterization
  tool.
- Exact old/proposed/delta previews and proposal-bound confirmation.
- Accepted/cancelled/rejected guard evidence in configuration history.
- Bootstrap validation of the active governed documents before hardware
  construction.
- Non-bypassable endpoint bounds at Controller dispatch, including existing
  `override=True` routes.
- Windows, contained SIL, and target-Pi no-hardware qualification.

### Out of scope

- Changing firmware, command opcodes, framing, parsing, coordinated-XY
  execution, step generation, acceleration, or motor timing.
- Claiming physical collision coverage from an empty obstacle list.
- Inventing unmeasured collision volumes or controlled-approach routes.
- Replacing the current movement router or resolving every historical
  `override=True` use in one refactor.
- Automatically authorizing a target because a large-change confirmation was
  accepted.
- Authenticated user roles. Operator name remains an attestation paired with
  the OS account; it is not identity authentication.
- Automatic cloud/fleet upload of calibration data.
- Guarding non-coordinate pressure/regulator profile changes beyond existing
  Milestone 4 transaction and schema validation.
- Future update preservation and rollback export, which remain Milestone 6.
- Final physical exclusion/path HIL, app/firmware pairing, and staged fleet
  rollout, which remain Milestone 7.

## Audited call paths

### Named-location capture and commit

Current:

```text
MainWindow.add_new_location() / modify_location()
-> MachineModel.get_current_position()
-> MainWindow.request_configuration_identity()
-> Controller.commit_named_location()
-> ConfigurationTransactionService.commit_documents()
-> Controller._install_committed_configuration()
-> Model.install_committed_locations()
```

Milestone 5 target:

```text
MainWindow requests guarded capture
-> Controller.capture_configuration_point()
-> verify active machine + connected + enabled + homed + trusted epoch
-> verify queue/run states idle + fresh X/Y/Z telemetry
-> freeze proposed complete Locations document and source hashes
-> ConfigurationChangeGuard.assess()
-> ConfigurationChangePreviewDialog displays exact old/new/delta + checks
-> Controller revalidates proposal, telemetry/preconditions, policy hash,
   confirmation tier, and current config hashes
-> ConfigurationTransactionService.commit_documents(guard_evidence=...)
-> exact backup + event + head + disk reopen
-> Model installs only service-returned document
```

### Rack calibration

Current:

```text
RackCalibrationDialog
-> captures temporary rack_position_Left / rack_position_Right in RackModel
-> MainWindow requests operator/reason
-> Controller.commit_rack_calibration()
-> one Locations.json transaction
```

Milestone 5 target:

```text
each Confirm Position
-> Controller captures one point with telemetry + homing/trust-epoch evidence
-> temporary coordinates and capture evidence remain inactive
final Submit
-> require both points from same machine UUID and homing/trust epoch
-> derive every rack slot
-> validate anchors, orientation, span, derived slots, bounds, exclusions
-> show pair-level old/new/delta and strongest-axis classification
-> proposal-bound confirmation
-> one guarded Locations.json transaction
```

The generic named-location editor must not modify
`rack_position_Left` or `rack_position_Right`; those reserved keys can change
only through the pair workflow, reviewed import, or reviewed restore.

### Plate calibration

Current:

```text
PlateCalibrationDialog
-> captures temporary top_left, top_right, bottom_right, bottom_left
-> Controller.commit_plate_calibration()
-> one Plates.json transaction
-> WellPlate installs and calculates the transform after disk commit
```

Milestone 5 target:

```text
each Confirm Position
-> guarded point capture with per-corner evidence
final Submit
-> require complete same-machine/same-trust-epoch quartet
-> validate bounds, simple convex ordering, orientation continuity,
   non-degenerate/invertible transform, finite derived wells, and exclusions
-> show complete four-corner old/new/delta preview
-> proposal-bound confirmation
-> one guarded Plates.json transaction
-> install and calculate transform only after durable success
```

### Motion dispatch

Current saved/derived dispatch:

```text
View or workflow
-> Controller.move_to_location() / _queue_next_array_well()
-> Milestone 4 SavedTargetAuthorizer
-> Controller.set_absolute_X/Y/Z/coordinates()
-> optional combined collision/bounds check unless override=True
-> Machine_FreeRTOS.set_absolute_XY() / set_absolute_Z()
-> ABSOLUTE_XY (0x0E) / ABSOLUTE_Z (0x0C) command queue
-> firmware Orchestrator CMD_ABS_XY / CMD_ABS_Z handlers
```

Milestone 5 keeps the firmware half unchanged and adds:

```text
resolved saved/derived target and every intermediate endpoint
-> exact-value authorization
-> non-bypassable numeric/global-bound validation
-> configured exclusion/path decision with explicit override scope
-> only then call existing set_absolute_* and Machine_FreeRTOS APIs
```

`override=True` must never bypass numeric validity or global travel bounds. It
may bypass only an explicitly identified, separately reviewed obstacle/path
rule in workflows that already require that behavior. A boolean override is
not evidence that an out-of-bounds coordinate is safe.

## Fixed safety invariants

1. **No preview/commit gap:** committed bytes and embedded guard evidence must
   describe the exact proposal shown to the operator.
2. **Current disk binding:** a changed configuration head or governed-file hash
   after preview rejects the commit and requires a new preview.
3. **Current telemetry binding:** a named capture commits only if the latest
   fresh reported coordinates still equal the previewed capture.
4. **Per-point calibration evidence:** rack and plate points retain the machine
   UUID, homing/trust epoch, capture coordinate, telemetry generations, and
   freshness result from the moment each point was confirmed.
5. **No stale homing trust:** disconnect, board reset, home reset, motion
   recovery, or a new home invalidates earlier temporary capture evidence.
6. **Non-bypassable bounds:** manual, calibration, safe-height, offset,
   import, restore, verification, and `override=True` paths cannot persist or
   dispatch an endpoint outside hard global bounds.
7. **Hard rejection changes nothing:** invalid proposals create at most a
   non-mutating rejected event; config and active Model state stay unchanged.
8. **Strong confirmation is not verification:** accepted coordinate changes
   remain `revoked_pending_verification` under Milestone 4.
9. **No silent policy fallback:** missing, malformed, unknown, or mismatched
   policy fails closed in production before hardware construction.
10. **No generic reserved-key mutation:** rack anchors and synthetic `slot-`
    namespace cannot be created/changed through the generic location editor.
11. **Aggregate integrity:** rack is one pair and plate is one quartet from
    preview through transaction and Model installation.
12. **Auditable decision:** accepted, cancelled, and rejected attempts bind the
    policy ID/hash, proposal hash, target keys, deltas, rule codes, and result.
13. **No obstacle overclaim:** an empty configured obstacle list is reported as
    no modeled exclusion geometry, not as proof of a collision-free machine.
14. **No firmware change:** host guards do not alter protocol payloads or imply
    firmware-side coordinate enforcement that is not present.

## Policy contract

### Tracked policy artifact

Add a reviewed, tracked policy such as:

`FreeRTOS-interface/Policies/configuration_change_policy_v1.json`

It is application safety policy, not per-machine calibration, and therefore is
not stored in the external machine-data tree. Production startup loads it by
exact path, validates its schema, records its SHA-256 in every guard
assessment, and rejects an unknown policy version. There is no environment
variable, user-editable local override, or UI checkbox that disables it.

The v1 schema contains:

- `schema_name = labcraft.configuration_change_policy`
- `schema_version = 1`
- stable `policy_id`
- supported hardware-profile names
- maximum per-axis position telemetry age
- reserved location names and reserved prefixes
- target class mapping (`camera`, reserved location, generic location, rack,
  plate)
- `always_strong` flags
- optional per-target/per-axis warning thresholds in steps
- optional service-reference tier thresholds
- rack orientation and geometry rules
- plate orientation and transform rules
- confirmation phrase/version
- policy rationale and approval reference

The pure loader returns an immutable policy object. Duplicate target rules,
unknown axes, booleans used as integers, negative thresholds, unsupported
profiles, or incomplete required fields are fatal validation errors.

### Initial rc.2 confirmation policy

The recommended release-safe default is:

- Camera changes: always strong.
- Rack pair changes: always strong.
- Plate quartet changes: always strong.
- Reserved `home`, `loading`, `pause`, `plate`, and `balance` changes: always
  strong.
- Adding a new target: always strong because there is no prior delta.
- Generic named-location changes: strong until an approved per-axis threshold
  table says otherwise.

This conservative fallback keeps calibration usable but never turns missing
fleet evidence into a permissive threshold. It may be relaxed only by a
reviewed policy revision with characterization evidence. It is not a hard
collision envelope: valid proposals can still be saved after strong
confirmation and will remain motion-blocked pending separate verification.

### Threshold characterization

Add a read-only tool such as:

`tools/export_configuration_change_characterization.py`

The tool accepts explicit machine-data/history or reviewed backup paths and
emits a sanitized JSON/CSV report containing only:

- caller-supplied cohort label;
- hardware profile;
- target class and non-identifying target category;
- axis;
- absolute delta in steps;
- workflow and whether the change was later verified/restored; and
- aggregate sample counts/distributions.

By default it must omit absolute coordinates, machine ID/UUID, operator names,
reasons, source paths, and experiment content. It never uploads, edits, or
opens the active store for writing. Threshold selection remains a reviewed
human decision; the tool must not automatically turn a percentile into policy.

Before a numeric threshold is accepted:

1. collect normal changes from each supported hardware profile and calibration
   workflow;
2. add physical calibration resolution/tolerance evidence;
3. compare the proposed threshold against the damaging Camera scenario;
4. test all rc.6/rc.1 and current fleet fixtures;
5. record why each target/axis is routine, strong, or service-reference tier;
6. freeze the policy ID, file hash, approval, and effective release.

No universal 5,000-step threshold is permitted. If this gate lacks evidence,
the initial all-strong policy remains.

### Guard assessment schema

The pure evaluator returns a JSON-safe immutable assessment with:

- schema name/version;
- policy ID and raw SHA-256;
- proposal SHA-256;
- workflow, target keys/kinds, and hardware profile;
- governed-file hashes on which the proposal was based;
- complete before/proposed values and signed/absolute per-axis deltas;
- capture/precondition evidence where applicable;
- hard-check result codes and messages;
- threshold rule and classification for every changed axis;
- overall result: `routine_confirmation`, `strong_confirmation`, or `reject`;
- required confirmation phrase version; and
- authorization consequence (`revoked_pending_verification`).

The proposal hash covers the complete proposed governed document set relevant
to the operation, not only the displayed coordinate subset. The View renders
from this assessment; it does not independently recalculate deltas.

## Hard safety validation

### Active bounds and exclusions

Hard travel bounds come from the active canonical `Obstacles.json`, not the
tracked preset. Milestone 5 strictly requires:

- one `boundaries` object;
- exact `min` and `max` objects;
- integer X/Y/Z values with `min <= max` for each axis; and
- an `obstacles` list whose entries, when present, have two complete integer
  X/Y/Z corners.

Every governed location, rack anchor/derived slot, plate corner/derived well,
final saved/derived dispatch target, offset target, and intermediate route
endpoint must be within the global bounds. Malformed bounds fail startup and
guard evaluation closed.

A point inside a configured exclusion volume is hard-invalid. Route
intersection uses the existing Controller behavior until separately measured
geometry and a real segment/route policy are approved. Empty `obstacles` means
`no_configured_exclusion_geometry`; it does not produce a safety claim.

### Named locations and reserved namespaces

- Names remain nonempty and unique by `casefold`, as Milestone 4 already
  requires.
- `rack_position_Left` and `rack_position_Right` are pair-only reserved keys.
- Names beginning with `slot-` are reserved for rack-derived motion and cannot
  be added as persisted generic locations.
- Reserved machine names are matched case-insensitively and classified by the
  policy, never by ad hoc View string checks.
- Every coordinate must be an integer and hard-valid.
- A new target has no routine delta and therefore uses strong confirmation.

### Rack pair

Hard validation requires:

- exactly Left and Right complete integer points;
- distinct anchors;
- policy-approved Left-to-Right orientation for the hardware profile;
- nonzero usable span;
- every interpolated rack slot is finite, unique after integer rounding,
  within global bounds, and outside configured exclusions; and
- no orientation reversal relative to a valid prior pair.

Physical span and Z-slope tolerances may become hard rules only when their
measured ranges are approved in policy. Until then, large span/slope deltas are
strong-confirmation evidence rather than invented hard limits.

### Plate quartet

Hard validation requires:

- exactly `top_left`, `top_right`, `bottom_right`, and `bottom_left` complete
  integer points;
- every corner within bounds and outside configured exclusions;
- a simple, convex, non-self-intersecting XY quadrilateral;
- nonzero signed area and an orientation consistent with the valid prior
  calibration or the hardware-profile policy for an initial calibration;
- a finite, invertible perspective transform;
- finite derived coordinates for every well;
- every derived well within global bounds and outside configured exclusions;
  and
- no duplicate corner or derived-well collapse caused by rounding.

Edge-length, opposing-edge, diagonal, Z-plane, and condition-number limits are
policy fields. They become hard limits only with measured rationale; otherwise
their deltas are displayed and force strong confirmation.

## Capture preconditions and telemetry provenance

### Position telemetry

`MachineModel` currently updates X/Y/Z but records no receive time. Add
per-axis host-monotonic receive timestamps and generations. Only status fields
actually present in a received status payload refresh an axis; an unrelated
pressure/status message cannot make stale position data appear fresh.

The initial proposed maximum age is 2,500 ms, aligned with the current MCU
response timeout. Slice 0 must measure the normal Pi status cadence and either
confirm this value or freeze another reviewed value before implementation is
marked verified. The timeout cannot expand automatically at runtime.

### Trust epoch

Add a motion/capture trust epoch that changes on:

- connection loss or reconnect;
- board reset/recovery;
- home state reset;
- successful new home; and
- entry into a motion-recovery-required state.

Every captured point binds the active machine UUID and current trust epoch.
Rack/plate finalization rejects mixed or stale epochs.

### Capture readiness

At each point capture, Controller must prove:

- production has an authorized machine context and expected machine UUID;
- machine connected;
- motors enabled and homed;
- XY recovery state `idle`;
- machine not paused and transport not paused;
- array runner, sequence runner, and calibration conflicts idle;
- Machine_FreeRTOS command queue empty;
- MachineModel reports free/idle;
- X, Y, and Z telemetry each within the policy age;
- reported X/Y/Z are valid integers inside hard bounds; and
- Controller expected position equals the reported position.

Failure records a reason code such as `not_homed`, `queue_not_empty`,
`position_stale`, `expected_position_mismatch`, or `motion_recovery_active` and
does not alter temporary or active calibration state.

Named-location commit rechecks that the current fresh position still equals
the previewed capture. Rack/plate finalization rechecks current readiness and
every stored point's UUID/epoch evidence; it does not require the current
position to equal all prior corners.

## Preview and confirmation UX

Create one reusable modal `ConfigurationChangePreviewDialog` driven only by a
validated guard assessment.

The dialog shows:

- machine display ID and hardware profile;
- workflow and target key/kind;
- policy ID and short policy/proposal hashes;
- exact old and proposed coordinates;
- signed and absolute X/Y/Z deltas for every point;
- capture readiness and telemetry-age results;
- bounds, exclusion, rack, or plate geometry checks;
- routine/strong/reject classification and the exact rule that caused it;
- explicit notice that the saved value will remain motion-blocked until a
  separate verification event; and
- operator name and required reason.

Behavior:

- `reject`: Save is disabled; Record Rejection and Close is the only terminal
  action after the audit succeeds.
- `routine_confirmation`: operator/reason plus one exact Save-and-Revoke
  confirmation.
- `strong_confirmation`: operator/reason, acknowledgement of the displayed
  deltas, and a generated typed phrase containing the target key and short
  proposal hash. Paste is permitted, but the phrase must match exactly.
- Close, Escape, Back, or Cancel records a non-mutating cancellation with its
  stage and proposal/policy identity.
- A proposal/precondition change while the dialog is open invalidates the
  response and opens a newly calculated preview; it is never silently updated
  underneath the operator.

Camera remains a single independently displayed target. Rack shows both
anchors and derived-span summary. Plate shows all four corners and transform
summary. The View must not truncate the axis carrying the strongest warning.

## Transaction and history integration

Extend `ConfigurationTransactionService.commit_documents()` with an optional,
strictly validated `guard_evidence` mapping. For guarded coordinate workflows:

- absence of guard evidence is rejected;
- policy/proposal hashes are revalidated before commit intent;
- `expected_config_sha256` binds the preview to current governed bytes;
- the validated assessment is appended as an embedded change record;
- the existing event schema version can remain 1 because `changes` already
  contains extensible JSON mappings, but the embedded guard record has its own
  schema name/version;
- pending journal, recovery, event hash, and history export therefore cover
  the guard evidence automatically; and
- restore/recovery remain byte-exact and deterministic.

`record_attempt()` stores the same assessment or the available partial
precondition evidence for cancellation/rejection. Audit failure is visible and
cannot be reported as a successful save.

Update `ConfigurationHistoryReader` so table/Markdown summaries surface target,
result tier, largest delta, rejection code, policy ID, and proposal hash while
retaining complete JSON details.

## Workflow enforcement

### Controller as the mandatory gate

All production coordinate-changing Controller adapters must use one helper:

```text
prepare proposal
-> validate complete documents and active policy
-> assess hard rules/deltas/preconditions
-> request View confirmation through returned assessment
-> revalidate proposal + hashes + current readiness
-> commit once through Milestone 4
```

Apply it to:

- named location add/modify;
- rack calibration pair;
- plate calibration quartet;
- reviewed `Locations.json` / `Plates.json` import;
- configuration restore affecting those files; and
- exact target verification, which must refuse a hard-invalid current value.

Legacy direct Model writes remain rejected by the Milestone 4 writer
inventory. Compatibility adapters must call the guarded Controller path, not
construct permissive evidence.

### Bootstrap and composition

`MachineDataBootstrap.open_ready()` loads and validates the tracked policy and
hard-validates the active target snapshot after Milestone 4 reconciliation but
before returning `AuthorizedMachineContext`. A hard-invalid existing target or
policy failure returns `recovery_required` before normal App imports construct
Model, serial, cameras, balance, Controller, or View.

Add the immutable policy/guard to `AuthorizedMachineContext` and inject the
same object into Controller through `ApplicationComposition`. Production
composition requires it. Tests/simulation receive an explicit validated test
policy; production must not use a permissive `None` fallback.

Before enabling this startup gate, run all rc.6/rc.1 tracked fixtures, the
verified M3/M4 Pi evidence copy, and known fleet configuration fixtures through
the pure validator. A legacy incompatibility is resolved explicitly; startup
must not rewrite data to make it pass.

### Dispatch defense in depth

Split the current combined collision function conceptually into:

1. numeric and global-bound endpoint validation, always enforced;
2. configured exclusion/route evaluation, whose narrowly documented override
   behavior remains separate; and
3. Milestone 4 exact saved-target authorization.

Every `set_absolute_X`, `set_absolute_Y`, `set_absolute_Z`, combined absolute,
and relative endpoint enforces layer 1 even when `override=True`. Saved and
derived location/rack/plate movement also enforces the relevant M5 target
policy before any safe-height, dogleg, overshoot, XY, or Z command is queued.

Tests must cover named moves, rack slot offsets, plate reference/dogleg points,
array-well and row-entry overshoot points, calibration clearance points, and
manual relative endpoints. A rejection must leave the Machine_FreeRTOS queue
and Controller expected position unchanged.

## Compatibility

### Existing rc.6/rc.1 migrated data

Milestone 5 performs no migration and no startup rewrite. Existing data enters
through the verified M2/M3/M4 canonical store. Hard validation must accept all
reviewed valid cohort fixtures exactly as stored, including noncanonical raw
JSON formatting, because the guard reads semantic values and does not
reserialize at startup.

### Existing Milestone 4 history

History without embedded guard records remains valid. Guard evidence is
required only for new guarded coordinate events at or after the M5 application
commit. The active policy is not retroactively asserted over an old operator
decision, although current hard validity is checked at startup and dispatch.

### Rollback readability

M5 embeds guard records inside the already extensible v1 `changes` list, so M4
history parsing should remain readable. This is data-format compatibility, not
permission to operate older code after M5: M4 does not enforce M5 capture,
hard-bound, or confirmation policy.

## Implementation slices

Each slice begins with failing tests and ends with focused passing tests. Keep
the implementation in one dedicated Milestone 5 code commit after all gates.

### Slice 0 - Characterize and freeze policy

- Implement the read-only sanitized delta characterization tool.
- Measure Pi status cadence without commanding hardware.
- Validate rc.6, rc.1, M3/M4, and available fleet fixtures.
- Freeze the v1 policy schema, initial 2,500 ms telemetry-age decision, reserved
  targets, all-strong fallback, and any approved numeric threshold table.
- Record approvals/rationale; no automatic threshold selection.

### Slice 1 - Pure policy, hard rules, and assessments

- Add policy loader/hash validation and immutable data types.
- Add strict bounds/exclusion parser.
- Add target classification, delta calculation, confirmation tiers, proposal
  hashing, named/rack/plate hard validation, and JSON-safe assessment parsing.
- Keep this module free of Qt, Machine_FreeRTOS, Model, and filesystem writes.

### Slice 2 - Telemetry and capture provenance

- Record per-axis monotonic timestamps/generations only for received axes.
- Add machine motion/capture trust epoch lifecycle.
- Add Controller capture-readiness snapshot and reason codes.
- Route named/rack/plate point capture through Controller; preserve temporary
  data as inactive coordinate-plus-evidence records.

### Slice 3 - Guard evidence in transactions/history

- Add strict optional guard evidence to mutating transaction commits.
- Require it for configured coordinate workflows without breaking old history.
- Add cancellation/rejection evidence and readable history summaries.
- Extend journal/recovery/fault tests so guard evidence is hash-covered and
  survives every recognized interruption state.

### Slice 4 - Guarded Controller workflows

- Centralize proposal preparation/revalidation/commit.
- Guard named add/modify and close reserved-name bypasses.
- Guard aggregate rack and plate commits.
- Guard coordinate imports, restores, and verification.
- Preserve M4 disk-before-memory, backup, revocation, and fatal-latch behavior.

### Slice 5 - Preview and strong-confirmation UI

- Add the reusable assessment-driven preview dialog.
- Integrate named, rack, plate, import, restore, and verification flows.
- Record close/cancel/reject consistently.
- Ensure a stale proposal returns to a newly calculated preview.
- Keep Camera, pair, and quartet presentation complete and unambiguous.

### Slice 6 - Bootstrap and dispatch defense

- Load/validate policy and active hard validity before hardware construction.
- Inject one immutable guard through authorized composition.
- Make global endpoint bounds non-bypassable for all absolute/relative APIs.
- Guard saved/derived target and intermediate endpoints before queue mutation.
- Retain separately scoped obstacle override behavior and document every call
  site in a regression inventory.

### Slice 7 - Qualification and closeout

- Run changed-module compilation, focused tests, writer/override inventory,
  full Windows suite, contained SIL, and static diff checks.
- Commit one dedicated Milestone 5 implementation commit.
- Pull it to the Pi and run the fresh disposable no-hardware qualification
  below.
- Preserve/hash evidence, update both plans, and mark verified only after all
  exit criteria pass.

## Expected implementation files

### New application/policy files

- `FreeRTOS-interface/ConfigurationSafetyPolicy.py`
- `FreeRTOS-interface/Policies/configuration_change_policy_v1.json`
- `tools/export_configuration_change_characterization.py`

The final names may change during tests-first implementation, but policy
loading, pure assessment, and characterization must remain separated from
hardware construction and canonical writes.

### Existing application files

- `FreeRTOS-interface/MachineDataBootstrap.py`
- `FreeRTOS-interface/ApplicationComposition.py`
- `FreeRTOS-interface/MachineDataTransactions.py`
- `FreeRTOS-interface/ConfigurationHistoryReader.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/View.py`

`LocalConfig.py` should remain structural compatibility validation unless a
small shared helper is clearly safer than duplicating strict policy parsing.
No firmware file is expected to change.

### New tests

- `tests/test_configuration_safety_policy.py`
- `tests/test_configuration_capture_preconditions.py`
- `tests/test_configuration_change_preview.py`
- `tests/test_configuration_guarded_workflows.py`
- `tests/test_configuration_change_characterization.py`

### Existing tests expected to expand

- `tests/test_app_machine_data_bootstrap.py`
- `tests/test_safe_application_construction.py`
- `tests/test_machine_data_transactions.py`
- `tests/test_configuration_history_reader.py`
- `tests/test_configuration_controller_adapters.py`
- `tests/test_configuration_mutation_adapters.py`
- `tests/test_configuration_writer_inventory.py`
- `tests/test_controller_saved_target_authorization.py`
- `tests/test_controller_move_to_location.py`
- `tests/test_controller_collision_config.py`
- `tests/test_rack_calibration_ui_workflow.py`
- `tests/test_rack_calibration_travel_safety.py`
- `tests/test_plate_calibration_storage.py`
- relevant contained SIL application/dialog tests

### Documentation

- this implementation plan and parent live plan;
- policy characterization/approval record;
- operator guidance for routine, strong, rejected, and separately verified
  states;
- Milestone 5 completion record after qualification.

## Automated test matrix

### Policy/schema

- Valid policy loads identically on Windows and Pi and has a stable hash.
- Missing/extra fields, unknown version/profile/axis, duplicate rule, boolean
  integer, negative threshold, and invalid confirmation mode reject.
- All-strong fallback is explicit; a missing target rule never means routine.
- Proposal hash changes for any hidden or displayed governed value change.
- Assessment parse/serialize round-trips exactly.

### Bounds and exclusions

- Boundary minimum/maximum endpoints pass; one-step outside rejects per axis.
- Malformed/missing/list bounds reject.
- Point inside configured exclusion rejects; empty list reports unmodeled.
- `override=True` cannot bypass numeric/global bounds.
- Rejection changes neither expected position nor command queue.
- rc.6/rc.1 and verified M3/M4 semantic fixtures pass active validation.

### Capture readiness

- Connected/enabled/homed/idle/fresh/equal expected position passes.
- Disconnected, disabled, not homed, paused, transport paused, queue nonempty,
  Model busy, runner active, recovery active, stale one-axis telemetry, missing
  axis telemetry, or expected/current mismatch rejects with exact code.
- Pressure-only status does not refresh position freshness.
- Status for one axis refreshes only that axis.
- Reconnect/reset/rehome invalidates older capture evidence.
- Named proposal rejects if current fresh position changes after preview.
- Rack/plate reject mixed machine UUID or trust epoch.

### Named locations

- Exact old/proposed/signed/absolute X/Y/Z deltas display.
- Camera and reserved targets always strong under initial policy.
- New target is strong.
- Approved generic under-threshold fixture can be routine when a numeric policy
  is present.
- Any exceeded configured axis selects the strongest tier.
- Rack anchor and `slot-` generic editing reject.
- Cancel/reject write one non-mutating event and change no bytes/memory.
- Accept writes one event, one backup, exact guard evidence, and revokes only
  affected authorization.

### Rack

- Complete valid pair and every derived slot pass.
- Missing/duplicate anchors, reversed orientation, zero span, duplicate rounded
  slots, out-of-bounds slot, or excluded slot reject.
- Pair preview contains both anchors and all deltas.
- One confirmation produces one transaction and one rack revocation.
- Failure/cancel retains prior active anchors/slot coordinates.

### Plate

- Valid convex quartet and finite transform/derived wells pass.
- Missing corner, duplicate corner, self-intersection, concavity, zero area,
  orientation flip, singular/ill-conditioned transform under approved policy,
  nonfinite result, out-of-bounds well, or excluded well reject.
- Preview contains all four corners and every delta.
- One confirmation produces one transaction and one plate revocation.
- Failure/cancel retains prior transform and active well positions.

### Confirmation binding

- Routine and strong dialogs expose correct controls.
- Wrong phrase, target key, proposal hash, operator, or reason rejects.
- Changed config/policy/proposal/precondition after preview requires new review.
- Strong acceptance does not authorize movement.
- Separate exact verification refuses a hard-invalid target and authorizes only
  the exact valid current value.

### Transaction, recovery, and history

- Guard evidence appears in accepted/rejected/cancelled events and exports.
- Missing/malformed evidence for guarded workflow rejects before backup/intent.
- Existing M4 events without guard evidence still replay.
- Faults around journal, each config replace, event, head, and cleanup preserve
  exact guard evidence and deterministic recovery.
- Restore/import guard results are hash-bound and affected targets remain
  revoked.
- History summary includes tier/largest delta/rejection/policy/proposal without
  hiding complete JSON.

### Dispatch and zero-command safety

- Named Camera, rack slot plus offsets, plate reference/dogleg, derived well,
  row-entry overshoot, calibration clearance, and relative endpoints are hard
  checked before queue mutation.
- Revoked or hard-invalid targets issue zero Machine_FreeRTOS calls even with
  manual/override/ignore-safe-height flags.
- Valid previously qualified routes preserve ordering and command payloads.
- No protocol or firmware golden vector changes.

## Windows validation gates

During implementation, run focused files after every slice. Before the
dedicated commit, run at minimum:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_configuration_safety_policy.py `
  tests\test_configuration_capture_preconditions.py `
  tests\test_configuration_change_preview.py `
  tests\test_configuration_guarded_workflows.py `
  tests\test_configuration_change_characterization.py `
  tests\test_machine_data_transactions.py `
  tests\test_configuration_history_reader.py `
  tests\test_configuration_controller_adapters.py `
  tests\test_configuration_mutation_adapters.py `
  tests\test_configuration_writer_inventory.py `
  tests\test_controller_saved_target_authorization.py `
  tests\test_controller_move_to_location.py `
  tests\test_controller_collision_config.py `
  tests\test_rack_calibration_ui_workflow.py `
  tests\test_rack_calibration_travel_safety.py `
  tests\test_plate_calibration_storage.py `
  tests\test_app_machine_data_bootstrap.py `
  tests\test_safe_application_construction.py

.\env\Scripts\python.exe -m pytest -q

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root <external-output-root> `
  --warmup-runs 0 --measured-runs 1 `
  --host-label windows-m5-guarded-config

git diff --check
```

Use a full-suite timeout of at least 900,000 ms and an external pytest/SIL
temporary root. Compile every changed Python module with the project
interpreter. Run the writer inventory and a new override/endpoint inventory so
new coordinate dispatch sites cannot bypass the guard.

## Target-Pi no-hardware qualification

Use the supplied qualification target only after the dedicated Milestone 5
commit is pulled into a clean checkout:

- host: `labcraft@192.168.0.33`
- SSH identity:
  `verification_reports\pi_sil_codex_network_ed25519`
- repository: `/home/labcraft/LabCraft_printer`
- interpreter: `/home/labcraft/LabCraft_printer/env/bin/python`

The qualification must not launch production `App.py`, open serial/camera/
balance/GPIO, enable/home motors, or send a physical command. It uses a fresh
disposable copy of the verified M4 sequence-zero baseline or another reviewed
M4 disposable source under `/tmp`.

Required sequence:

1. Record exact commit, clean status, policy SHA-256, Python version,
   disposable real paths, machine identity, and baseline hashes; prove no
   `App.py` process is running.
2. Run policy/active-document compatibility against the untouched M4 copy;
   prove no head/event/backup/config byte changes.
3. Feed recorded/synthetic status into a Controller harness with a machine
   object whose every command method fails the test if called.
4. Exercise fresh, stale, not-homed, queue-nonempty, recovery-active, and
   expected-position-mismatch captures; prove only the fresh case can reach a
   preview and all cases queue zero commands.
5. On a disposable copy only, propose a synthetic substantial Camera Y change;
   prove strong classification, exact preview, cancel event, unchanged config,
   and unchanged Camera authorization.
6. Accept the same synthetic proposal with the exact phrase; prove one backup,
   one event with guard evidence, Camera revocation, and zero commands. Do not
   verify or move to the synthetic Camera.
7. Submit one out-of-bounds named proposal, invalid rack pair, and invalid
   plate quartet; prove rejected events, unchanged bytes/Model, and zero
   commands.
8. Submit valid synthetic rack/plate aggregates; prove one event each,
   revocation, complete preview evidence, then exact-restore every governed
   file to baseline bytes.
9. Reopen through bootstrap and a detached checkout; prove identical history,
   active hard validity, no pending transaction, exact baseline config bytes,
   and no Camera change in the original source.
10. Run focused Pi tests, the existing zero-command safety gate, and contained
    `virtual_print_array_96_v1` (96/96, all hardware interfaces disabled).
11. Seal result JSON, logs, histories, policy/config hashes, and a SHA-256
    manifest; recheck it, copy the evidence to ignored local
    `verification_reports/`, and record a non-sensitive completion record.

If the policy's 2,500 ms freshness value is being qualified, status cadence is
measured from already captured/simulated status delivery. Do not connect to
hardware merely to make this software qualification pass.

## Physical qualification boundary

Milestone 5 no-hardware qualification proves rejection, persistence, audit,
authorization, and unchanged command payloads. It does not prove unmeasured
obstacle geometry or physical clearances.

Before release, Milestone 7 must perform a separately approved, attended HIL
procedure with the work envelope cleared. It should confirm that known-valid
existing Camera/rack/plate routes remain usable after exact verification and
that host-rejected values produce no firmware command. No unattended SSH
session may initiate those moves.

## Rollback strategy

### Development rollback

- Revert the current slice while retaining its tests and external disposable
  evidence.
- Never point partial M5 code at the default production machine-data root.
- If a new event exists, preserve its complete history/backups; discard only an
  exactly identified disposable root after path review.

### Before the first M5-guarded event

An untouched M4 store remains readable by the verified M4 commit. Reverting
application code is possible for development diagnosis, but doing so removes
M5 guards and is not a production safety remedy.

### After an M5-guarded event

M4 should still parse the extensible change record, but it does not enforce
M5 policy. Do not operate production hardware by rolling back to M4. Preserve
the canonical store and use the Milestone 6 controlled compatibility/update
path. Never remove guard records or rewrite history to enable rollback.

### Policy correction

If a valid legacy calibration is blocked, preserve the rejection evidence and
revise the tracked policy with reviewed fixture/physical evidence. Do not add a
runtime disable flag, hand-edit the active policy, weaken global bounds, or use
`override=True` to bypass the rejection.

## Definition of done

Milestone 5 is `verified` only when:

- the v1 policy and fallback behavior are reviewed, versioned, and hash-bound;
- all known valid rc.6/rc.1/M3/M4/fleet fixtures pass hard validation without
  startup mutation;
- all current coordinate capture and mutation paths route through one guard;
- named/rack/plate captures prove fresh telemetry and trusted state;
- exact old/proposed/delta values are shown and bound to the commit;
- Camera, rack, plate, reserved, and new targets cannot use routine
  confirmation under the initial policy;
- hard-invalid proposals cannot persist, install in Model, verify, restore,
  import, or dispatch;
- global endpoint bounds cannot be bypassed by `override=True`;
- accepted/cancelled/rejected history includes complete guard evidence;
- strong confirmation does not grant verification;
- rack pair and plate quartet stay aggregate through preview, commit, and
  memory installation;
- existing M4 history and exact restoration continue to pass;
- changed-module compilation, focused/full Windows tests, writer/override
  inventories, standard contained SIL, and `git diff --check` pass;
- fresh target-Pi no-hardware qualification and evidence preservation pass;
- the live and concrete plans record decisions, findings, commit, and evidence;
  and
- one dedicated Milestone 5 implementation commit contains code/tests/docs,
  with no machine data, credentials, generated logs, or evidence archive.

## Progress checklist

- [x] Audit post-M4 named, rack, plate, import, restore, verification, startup,
  dispatch, comms, and firmware-handler paths.
- [x] Define guard boundary, non-bypassable rules, strong-confirmation behavior,
  and separate verification.
- [x] Define policy schema, safe threshold fallback, characterization process,
  telemetry provenance, and geometry rules.
- [x] Define eight implementation slices, file inventory, tests, Pi gate, and
  rollback strategy.
- [ ] Complete Slice 0 Pi cadence measurement and final policy approval. The
  tracked all-strong fallback and sanitized characterization tool are complete;
  no numeric relaxation was introduced.
- [x] Implement Slices 1-6 tests-first.
- [x] Complete local Slice 7 qualification.
- [ ] Create dedicated Milestone 5 implementation commit.
- [ ] Complete target-Pi no-hardware qualification and evidence preservation.
- [ ] Mark Milestone 5 `verified` in both plans.

## Implementation and local validation record

Implementation completed on 2026-08-20 in the uncommitted `update_bug_fix`
working tree. The dedicated commit and clean target-Pi qualification remain
required before this milestone can become `verified`.

Implemented behavior:

- tracked v1 policy with an all-strong rc.2 fallback, strict schema parsing,
  stable LF checkout bytes, and a hash embedded in every assessment;
- strict active bounds/exclusion parsing; reserved-name enforcement; rack
  anchor/derived-slot checks; and plate convexity, orientation, invertible
  perspective-transform, and derived-well checks;
- per-axis receive timestamps/generations plus a motion trust epoch, without
  refreshing missing axes from unrelated status payloads;
- Controller-owned fresh capture for named, rack, and plate workflows;
- one reusable complete old/proposed/delta preview, proposal-bound typed strong
  confirmation, and cancellation/rejection audit handling;
- hash-bound guard evidence inside the existing M4 event chain, with readable
  policy/result/largest-delta/proposal summaries;
- guarded named, guided rack, guided plate, coordinate import, and exact
  coordinate restore paths, while exact verification refuses hard-invalid
  active values;
- startup policy and active-document validation before authorized MVC/hardware
  construction; and
- non-bypassable integer/global endpoint bounds on all Controller absolute and
  relative APIs, including calls using `override=True`, without changing the
  device protocol or firmware.

Local validation:

- the five new focused files passed: `14 passed`;
- the M4 transaction/history plus M5 focused set passed: `66 passed`;
- the final full Python suite passed: `5,377 passed, 156 skipped` in 324.31 seconds;
- the contained `virtual_print_array_96_v1` SIL completed `96 / 96`, seed 1,
  with the simulation dependency graph and no physical hardware;
- changed-module compilation and `git diff --check` passed; and
- policy raw SHA-256 is
  `7f724af4b2e88ab3d46d774f38bb6be8cdd6b82240027e04785bc80b9cfa4274`.

The Pi gate was not run against this uncommitted tree. After the dedicated
commit is pulled into a clean Pi checkout, run the no-hardware sequence in this
document, measure/confirm the 2,500 ms freshness decision from synthetic or
already captured status delivery, preserve its evidence, and only then mark
Milestone 5 `verified`.

## Planning findings

1. Milestone 4 provides the correct single write boundary and accepts
   `expected_config_sha256`, but current Controller adapters do not bind a
   preview or guard assessment to it.
2. Current X/Y/Z state has no receive timestamp. Because `Model.update_state`
   calls the position updater for unrelated status payloads, freshness must be
   tracked per axis actually present in the payload.
3. Rack and plate dialogs store only coordinates. Final aggregate validation
   cannot prove when, on which homing epoch, or from which machine state each
   point was captured without new sidecar evidence.
4. `Controller.check_collision` combines global bounds and obstacles, while
   `override=True` bypasses both. Global bounds must be split out and made
   non-bypassable.
5. The configured obstacle list is empty in both rc.6 and rc.1 tracked
   cohorts. No plan or UI may translate that absence into collision coverage.
6. M4's event `changes` list is already extensible, so a separately versioned
   embedded guard record can be hash-chained without changing the top-level
   event schema or invalidating old history.
7. Strong confirmation and M4 target verification solve different problems.
   Combining them would let an operator authorize a value before independent
   physical verification.
8. Generic named-location editing can currently select rack anchor keys, while
   names beginning `slot-` receive rack-derived authorization semantics.
   Reserved namespaces must be closed at the generic editor and Controller.
9. Plate structural validation requires four integer corners but does not prove
   convex ordering, invertibility, or that derived wells remain within bounds.
10. Rack interpolation can yield invalid or duplicate rounded slot coordinates
    even when both anchor objects are structurally valid.
11. A per-axis numeric threshold cannot be inferred safely from one machine or
    the maximum UI jog size. The implementation needs a conservative
    all-strong fallback plus an explicit characterization/approval gate.
12. The existing firmware handlers consume the same absolute command values;
    M5 can be implemented entirely on the host without a protocol or firmware
    change.
13. Raw policy hashing is cross-platform only when checkout line endings are
    fixed. `.gitattributes` now forces LF for the tracked v1 policy.
14. M4's pure transaction tests intentionally exercise the repository without
    M5 UI confirmation. Production bootstrap explicitly enables required guard
    evidence after loading and validating the tracked policy; the M4 test
    helper explicitly disables only that composition requirement.
15. Coordinate import and exact restore previews enumerate every changed
    coordinate while restore still commits the verified raw backup bytes. The
    assessment never reserializes an active file merely to validate it.

## Open decisions and required approvals

| Decision | Recommended direction | Required before |
| --- | --- | --- |
| Numeric generic/reserved per-axis thresholds | Use reviewed characterization; otherwise keep all coordinate changes strong | Marking Slice 0 complete |
| Position freshness age | Provisional 2,500 ms, confirm against normal Pi status cadence and current MCU timeout | Implementing production capture guard |
| Rack physical span/Z tolerances | Keep invariant violations hard and unmeasured magnitudes strong until physical ranges are approved | Adding numeric hard geometry limits |
| Plate edge/Z/condition limits | Keep topology/invertibility/bounds hard and unmeasured magnitudes strong until plate/profile evidence is approved | Adding numeric hard geometry limits |
| Physical exclusions and route behavior | Leave empty/unclaimed; add only measured geometry with attended HIL | Enabling any obstacle safety claim |
| Strong confirmation phrase | Target key plus short proposal hash, with visible full delta acknowledgement | UI Slice 5 freeze |

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Created the concrete post-Milestone-4 guard policy, telemetry, preview, audit, dispatch, eight-slice implementation, Windows/Pi qualification, and rollback plan. |
| 2026-08-20 | Recorded completed Slices 1-6 and local Slice 7 gates; retained `implementation_complete` pending dedicated commit, Pi cadence/policy confirmation, and clean no-hardware Pi evidence. |
