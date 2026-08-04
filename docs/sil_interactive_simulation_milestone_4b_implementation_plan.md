# SIL Interactive Simulation Milestone 4B Implementation Plan

Date: 2026-08-02

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Prerequisites: Milestones 1 through 4A `complete`

Planning baseline: `53aa2295c6914922394c40a2e2b2493210322d7b`

Status: `complete`

## Goal

Extend the camera-free synthetic calibration application surface to support
`droplet_to_stream` and `nominal_stream`, apply those results through the
existing mode-switch and execution-calibration paths, and record explicitly
simulated `passed`, `deferred`, and `failed` manual-refuel outcomes through the
existing Controller/Model API.

## Call Paths

```text
Simulator Control
  -> SyntheticCalibrationApplicationAdapter
  -> deterministic stream request/result and retained artifacts
  -> transient characterization candidate
  -> camera-free DropletImagingDialog
  -> preview and real mode-switch confirmation
  -> ExperimentModel apply operation / execution-plan revision
  -> Controller-driven simulated settings
  -> required manual-refuel preflight

Simulator Control refuel outcome
  -> SimulatedManualRefuelOutcomeAdapter
  -> Controller.record_manual_refuel_check_outcome()
  -> ExperimentModel manual-refuel store
  -> execution_calibrations.json
  -> preflight, task guidance, state evidence, and retained-root reload
```

Neither path invokes a physical camera, balance, hardware factory, firmware,
or protocol handler.

## Frozen Interfaces And Behavior

- `TransientCharacterizationCandidate` retains `printing_mode` as the applied
  mode and adds the requested/original mode used for pre-Apply identity checks.
- `SyntheticCalibrationApplicationAdapter.generate_and_present(profile_id)`
  accepts only `nominal_droplet`, `droplet_to_stream`, and `nominal_stream`.
  The existing nominal-droplet wrapper remains supported.
- Droplet-to-stream generation requires a current droplet volume strictly
  above 20 nL and below 40 nL. Its request interval reaches the 40 nL mode
  boundary without leaving the provider envelope. Nominal stream generation
  accepts inclusive 40--250 nL stream contexts.
- Stream results retain the Milestone 3 warning and limitations and display
  their requested/applied mode pair in the camera-free presentation.
- `SimulatedManualRefuelOutcomeAdapter` exposes `availability()`,
  `record_outcome()`, and `status_text()`. It accepts only `passed`, `deferred`,
  and `failed`, records through the existing Controller API, and never invokes
  bypass.
- Simulated manual-refuel records use source
  `sil_simulated_manual_refuel_check`, one five-droplet virtual trial,
  `operator_judgment="simulated"`, the normal machine snapshot, and canonical
  provider/seed JSON in the existing `notes` field. No authoritative schema is
  changed.
- A stale expected calibration fingerprint fails before recording. An
  identical already-recorded simulated outcome is idempotent. An ambiguous
  recording failure latches the adapter, marks the session failed/retained,
  and cannot be retried.
- The simulator dock owns the simulated outcome controls. The physical-style
  operator manual-refuel dialog remains unchanged.

## Implementation Steps

1. Extend transient-candidate requested/applied mode validation.
2. Add mode-aware presentation and the existing post-Apply refuel callback to
   the simulation launcher.
3. Generalize the SIL calibration adapter without changing the pure provider.
4. Add and integrate the simulated manual-refuel outcome adapter.
5. Extend Simulator Control and the bounded calibration dialog driver.
6. Add focused adapter, UI, control, persistence, and lifecycle tests.
7. Update the README and parent roadmap and run all automated and visible
   gates.
8. Only after every gate passes, add the completion record and mark Milestone
   4B complete.

## Exclusions

No core `Controller.py`, core `Model.py`, `ExecutionCalibrationStore.py`,
Milestone 3 provider, experiment schema, launcher CLI, firmware, protocol,
camera emulation, workflow migration, fault injection, Pi operation,
performance remediation, print execution, or bypass automation belongs to
this milestone.

## Verification Gates

Focused tests cover deterministic stream generation, mode identity and stale
candidate rejection, mode-switch confirmation, camera isolation, plan/settings
application, required/deferred/failed/passed refuel behavior, stale
fingerprints, idempotence, failure latching, state evidence, and retained-root
reload. Final validation includes Python compilation, the complete Python
suite, `git diff --check`, and a visible Windows fresh/reopen exercise.

## Risks And Rollback

The primary risks are stale mode identity, synthetic evidence being mistaken
for physical evidence, silently clearing stream preflight, and ambiguous
authoritative writes. Double identity validation, explicit provenance, the
existing Controller/Model path, no bypass control, and failure latching address
those risks.

Rollback removes stream presentation support, the simulated outcome adapter
and controls, related driver/tests, and Milestone 4B documentation. Milestones
1 through 4A and the pure Milestone 3 provider remain intact; no firmware,
protocol, schema, or retained-data migration is required.
