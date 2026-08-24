# Rc.8 Exact-Tag Legacy Upgrade Rehearsal

Status: `rc.8 published; exact-tag legacy rehearsal qualified; physical pilots pending`

This live record qualifies direct public updates from genuine preserved legacy
machine data to immutable `v1.3.0-rc.8`. It uses the reusable interface in
`README.md` and the safety contract in
`docs/machine_data_rc7_upgrade_rehearsal_plan.md`; rc.7's retained runs remain
historical failure evidence and are never resumed.

## Immutable release bindings

| Role | Tag | Peeled commit |
| --- | --- | --- |
| Legacy cohort 1 | `v1.2.0-rc.6` | `199807eea95a238896137bddb2a83d3d892e2aab` |
| Legacy cohort 2 | `v1.3.0-rc.1` | `922f2ac65eab2ff1f63ffc0719a98b777bc2128f` |
| Corrected target | `v1.3.0-rc.8` | `f611604346f1a5e64d8b5a1ecb115492a8960dc6` |

Rc.7 remains immutable at `b6138f9d029289385812fe80c276e0eddea90c23`
but is blocked for direct legacy rollout. Its rc.1 rehearsal proved the old
updater and cancellation path, then exposed that genesis enrollment was
restricted to rc.2/rc.3 and occurred after active-pointer publication.

Rc.8 permits genesis enrollment only inside the currently reviewed activation
transaction. It requires an exact approved legacy source version plus matching
migration, backup, identity, verification, activation, target version, and full
target commit evidence. The deployment anchor is durable before
`active_machine.json`; ordinary startup cannot create or recreate an anchor.

## Protected boundaries

Every cohort uses a fresh standalone clone, immutable owned source copy,
cancellation destination, activation destination, and second target checkout.
The campaign must not change:

- the protected production checkout;
- the normal detached development worktree except through `Status -> Sync ->
  Validate` before a campaign;
- production or development machine-data stores;
- the shared Python environment;
- installed firmware or durable firmware state; or
- any process outside the supervisor-owned bootstrap process group.

Failed roots remain non-reusable. The wrapper returns only hashes, counts,
commits, states, and pass/fail results to Windows. Coordinates and source bytes
remain private on the Pi.

## Pre-tag validation completed

- 169 affected Windows bootstrap/deployment/rehearsal tests passed.
- Exact correction commit `d06523cb` passed Pi `Status -> Sync -> Validate`,
  167 focused tests with two Windows-only skips, and the five-second isolated
  offscreen launch.
- 494 combined release/updater/wrapper tests passed.
- The complete Windows suite passed 5,785 tests with 156 expected skips.
- Release metadata, strict release JSON, tag binding, and static diff checks
  passed before publication.

## Cohort sequence

Use `tools/run_pi_upgrade_rehearsal.ps1` with an explicit run ID after Prepare:

1. `Prepare` the genuine wrapper against source tag and target rc.8.
2. `Status` and require `prepared`, matching protected invariants, and zero
   related processes.
3. `Update` through the source tag's own legacy updater and require exact rc.8.
4. `Cancel` in a distinct empty destination after inspecting the locked source.
5. `Activate` in another fresh destination after reviewing identity, Camera,
   rack, plate, settings, ownership, and preset evidence.
6. `Verify` raw and semantic source/canonical equality, all immutable receipts,
   genesis anchor, exact Camera, target authorization, and second-checkout
   reuse.
7. `Summarize` both sealed run IDs only after every gate passes.

The cancellation title ends in `CANCELLED`; inspect the selected source and
close with **Cancel**. The activation title ends in `ACTIVATED`; inspect the
source, complete the Camera/source acknowledgements and any required genuine
service record, then select **Create verified backup and activate**. Neither
action starts the normal app or constructs hardware.

## Live cohort status

| Cohort/attempt | Source | Run ID | Stage | Result |
| --- | --- | --- | --- | --- |
| rc.1 retained verifier failure | Genuine preserved Pi backup | `b33c56e7-dfde-4557-b6e2-a8eb3fed2b61` | Activation passed; verify failed | Harness verifier expected a non-persisted `activation_allowed` field; protected invariants remained unchanged |
| rc.1 qualified | Genuine preserved Pi backup | `64b5253c-c634-414b-a32c-115cf2debda1` | Verified and sealed | Passed updater, cancellation, activation, exact migration, genesis anchor, authorization, two-checkout reopen, and invariance gates |
| rc.6 qualified | Genuine transferred machine backup | `fc946a27-8398-4986-8b51-7ebb2860fdf8` | Verified and sealed | Passed updater, cancellation, activation, exact migration, genesis anchor, authorization, two-checkout reopen, and invariance gates |

The first rc.1 rc.8 run proved the old updater, cancellation, activation,
genesis-anchor creation, and ready reopen. Its sealing step then exposed a
rehearsal-only schema mismatch: ownership decisions persist
`classification`, not the derived Python property `activation_allowed`. The
root and failure receipt are retained. The verifier correction validates the
real persisted fields, accepts only `canonical` or `archive_only`, and rejects
malformed, unsafe, duplicated, prohibited, or unclassified entries. The rc.1
cohort was restarted under a fresh run ID after the corrected harness was
committed, pushed, synchronized, and validated. Harness commit `d924e153` then
passed 45 focused Windows supervisor tests, 37 ownership/bootstrap tests, and
43 focused Pi tests with two expected Windows-only skips before the successful
reruns.

The two successful seals were aggregated as campaign
`c3c80b1e-6dbd-4f00-a7b1-fc5ff73440e8`. The campaign binds distinct genuine
`v1.2.0-rc.6` and `v1.3.0-rc.1` source tags to the same exact rc.8 commit and
records `all_gates_passed=true`. Both runs used the same protected-invariant
baseline and ended with zero related processes. Source coordinates and bytes
remain private on the Pi.

## Fleet-rollout gate

The updater and migration path is qualified for both legacy cohorts. Fleet
rollout still requires one paused physical pilot per cohort for machine
identity, firmware pairing, and physically meaningful saved-position review.
The rehearsal alone does not authorize unattended fleet deployment.

## Recovery

On any failure, stop the cohort, retain its root and failure receipt, confirm
protected invariants and zero processes, correct the cause in a new release or
harness commit as appropriate, and restart with a new run ID. Never delete an
anchor, edit a durable pointer/receipt, reuse a partial destination, or bypass
the production deployment gate.
