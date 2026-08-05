# SIL Interactive Simulation Milestone 4C Completion Record

Date: 2026-08-05 (America/Los_Angeles)

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Implementation plan:
`docs/sil_interactive_simulation_milestone_4c_implementation_plan.md`

Baseline: `00e8473008390241b230d41844a4a489b536796e`

Status: `complete`

## Outcome

Milestone 4C moves the contained simulator behind the application's normal
Connect, Calibrate Printer Head, and Manual Refuel Check interfaces. The
Simulator Control dock is diagnostic-only. The real calibration layout retains
its Droplet and Stream tabs, summary rows, preview, confirmations, Apply, and
close behavior while physical acquisition controls remain inert in canonical
simulation.

The normal UI maps current mode and selected tab to `nominal_droplet`,
`droplet_to_stream`, `nominal_stream`, and `stream_to_droplet`. Applied
synthetic rows are reconstructed from fingerprint-validated retained artifacts
and authoritative execution-calibration records without populating physical
calibration history. The real manual-refuel dialog queues normal Controller
commands against `SimulatedMachine` and records actual trial metadata through
the existing authoritative persistence path.

Production remains the default. No firmware, protocol, serial, camera,
balance, physical calibration, hardware factory, Pi, or performance behavior
changed or was validated by this milestone.

## Implementation Scope

The intentional uncommitted diff from the baseline contains these application
and simulator files:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/CalibrationClasses/View.py`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/simulation/machine.py`
- `FreeRTOS-interface/simulation/state.py`
- `tools/sil/__init__.py`
- `tools/sil/calibration_application.py`
- `tools/sil/control.py`
- `tools/sil/manual_refuel.py`
- `tools/sil/session.py`
- `tools/sil/state_projection.py`
- `tools/sil/synthetic_calibration.py`
- `tools/virtual_workflows/page_drivers.py`

Focused coverage includes the two new 4C test modules, the stream lifecycle,
PressurePlotBox, calibration provider/application/UI/driver, manual refuel,
state projection, simulated machine, Simulator Control, production connection,
safe construction, session, phase-alias, summary-table, and authoritative-load
regressions named by the implementation plan.

Documentation includes the v1/v2 calibration schema documents, README,
roadmap, frozen 4C implementation plan, three focused correction plans, and
this completion record.

## Corrections Found During Visible Validation

Visible Windows testing exposed several application-level defects. Each was
diagnosed from its retained root before editing:

1. Camera-free close used hidden-window semantics that did not complete Qt
   dialog ownership, preventing the refuel handoff and later calibration
   launches.
2. Calibrate All temporarily ceded activation to the main window, and
   transient rows were not reconstructed when the dialog or retained session
   reopened.
3. The original symmetric v1 droplet-to-stream request could not transition the
   normal 9 nL default. The additive schema-v2 directional contract records a
   9 nL source and exact 40 nL target while leaving all v1 fingerprints stable.
4. Switching from an experiment with an active calibration run to legacy `{}`
   retained stale run identity; state projection could also report false zero
   counts from a stale cached execution bundle.
5. The post-calibration refuel dialog entered its modal event loop inside the
   simulator's command-completion callback. Its trial was accepted but could
   not execute until the dialog closed. A zero-delay Qt handoff now allows the
   completion stack to unwind without weakening the simulator's non-reentrant
   guard.

The correction plans are:

- `docs/sil_interactive_simulation_milestone_4c_low_volume_transition_correction_plan.md`
- `docs/sil_interactive_simulation_milestone_4c_experiment_switch_evidence_correction_plan.md`
- `docs/sil_interactive_simulation_milestone_4c_manual_refuel_dispatch_handoff_correction_plan.md`

## Consolidated Automated Validation

The final focused gate ran the 17 modules frozen in the implementation plan
plus the phase-alias and stream-lifecycle modules directly identified by the
corrections:

```text
259 passed, 240 warnings in 40.41s
```

Warnings are existing QtCharts deprecation notices. Compilation passed for all
13 modified application/simulation implementation modules. `git diff --check`
passed. The full pytest suite was intentionally not run, as required by the
Milestone 4C plan and user request.

Automated coverage proves production connection behavior is preserved,
physical/camera handlers remain inert in canonical simulation, all four profile
mappings are deterministic, stale identity fails before mutation, cancel paths
leave authoritative files unchanged, manual-refuel outcomes retain real trial
metadata, and stream-to-droplet reload reconstructs its applied history row
from the authoritative bundle.

## Full Normal-UI Sequence Evidence

The retained root below exercised all four profile mappings through normal
application controls, including nominal droplet, Droplet to Stream, nominal
stream, and Stream to Droplet, together with Failed, Unclear, and Passed refuel
outcomes:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260804T142958651283Z-4897e34cf3e4
```

Session ID: `6f1bb1f199c14276b89605eaaeb13901`

Fresh application session: `653e197e6ca04bee95d22ba692da8474`

Reload application session: `c7088b7f32cf4f81b1fd8992a7be1471`

This root is retained as inspected developmental evidence rather than the final
success root: its reload exposed the stale projection/history defects corrected
later. Those mismatches were not retried, hidden, or relabeled as success.

Additional preserved failure evidence includes:

- `20260804T194241257857Z-cd982ec2919b`, which exposed experiment-switch and
  stale state-evidence behavior;
- `20260805T122813738682Z-69447896d7bc`, where the first post-calibration
  `DISPENSE` remained accepted for about 8.14 seconds until the refuel dialog
  closed, while the Print Array launch executed immediately.

## Final Fresh Visible Windows Gate

Successful retained root:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260805T124515193488Z-ebd5d6342b4d
```

Session ID: `65798e1db59748759c9c8d21560a9ad5`

Fresh application session: `3c79aecfe1d0497dbb63f71e620b71fe`

Experiment: `Untitled-20260805_054520`

The operator used the normal UI to connect only to `SIMULATED`, enable/home,
regulate both pressures, finalize A1-A24 at the normal 9 nL default, stage the
matching virtual head, and open the real camera-free calibration dialog. The
Stream-tab Calibrate All action generated and applied an exact 9 nL Droplet to
40 nL Stream result through the real preview and confirmation paths.

Representative schema-v2 artifact:

- profile/provider version: `droplet_to_stream` v2 / `milestone-4c-v2`;
- request fingerprint:
  `0fef68f3caa85079a1a5a26a107ed8f51f4cda81ef8e31c1b75afc4704527900`;
- result fingerprint:
  `c28ba3e1179b27ce526b93b4fc13c14d7efe18181427c90f35f742c05a455376`;
- source/target volume: `9.0 nL` / `40.0 nL`;
- pressure/pulse width: `0.5997 psi` / `1300 us`;
- artifact directory:
  `artifacts/synthetic-calibration/3c79aecfe1d0497dbb63f71e620b71fe/c28ba3e1179b27ce526b93b4fc13c14d7efe18181427c90f35f742c05a455376/`.

The automatically opened real manual-refuel dialog queued command 22,
`DISPENSE`. It was accepted at `12:47:19.518274Z`, began executing at
`12:47:19.524600Z`, and completed at `12:47:19.670794Z` while the dialog
remained open. The operator recorded Passed with one five-droplet trial and
source `sil_simulated_manual_refuel_check`.

The manual export, disconnect, and terminal cleanup all reconciled plan
revision 3 with one calibration record, one refuel record, no mismatches, no
recorder failure, and no queued command. The application session and overall
session both completed cleanly.

## Retained-Root Reload Gate

The successful root was reopened with `--session-root` and loaded through the
existing Experiment Editor.

Reload application session: `824a673f816f4a99b7c2cbb51725870a`

The operator confirmed 40 nL stream mode and the reconstructed synthetic
calibration history. The authoritative projection confirms plan revision 3,
effective volume 40.0 nL, stream mode, the same calibration record/run ID, and
a matching Passed refuel record. Load, manual export, disconnect, and cleanup
snapshots all report one calibration record, one refuel record,
`reconciliation: ok`, zero mismatches, and no recorder failure. Both
application sessions are `completed`, both recorders are `closed`, containment
remains validated, and cleanup is `complete`.

## Limitations and Exclusions

All calibration and refuel evidence is explicitly synthetic. It does not prove
physical ejection, volume accuracy, pressure response, refueling, camera
segmentation, collision safety, firmware, protocol, or hardware communication.
Milestone 4C does not execute a print array or claim the full one-stock,
two-stock, and mixed-mode lifecycle characterization reserved for Milestone 5.

The visible launcher still prints pre-existing slot-location warnings and the
historical disconnect wording `Controller: Failed to connect to the machine.`
The retained trace nevertheless records a successful disconnect and complete
cleanup. These messages were not treated as Milestone 4C defects because they
did not alter the validated connection, command, persistence, or teardown
state.

## Rollback

Rollback removes the simulation UI bindings, full-layout camera-free mode,
schema-v2 directional transition support, extended simulated outcome bridge,
diagnostic-dock reduction, state/history reconstruction, focused tests, and 4C
documentation. Milestones 1 through 4B remain. No firmware, protocol, schema-v1
artifact, or retained experiment migration is required.

## Next Step

Create and review a revised concrete Milestone 5 plan for manual full-lifecycle
characterization around the converged normal UI before beginning that work.
