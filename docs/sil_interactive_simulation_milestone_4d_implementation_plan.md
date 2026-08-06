# Milestone 4D — Pulse-Aware Synthetic Ejection Response and Calibration Settings Convergence

Baseline: clean worktree at `525bf9f713e45c8d3de348d8850dd9b658911ac6`;
Milestones 1–4C are complete.

## Frozen behavior

New synthetic calibration requests use a versioned pulse-only response model.
Droplet mode maps 1300–1800 us linearly from 9–18 nL. Stream mode maps
2500–10000 us linearly from 60–250 nL. Values outside the target mode's
inclusive interval, including the 1801–2499 us gap, fail closed without
clamping. Pressure remains recorded provenance but is not an input to this
non-empirical response.

```text
Normal Calibrate All
  -> simulation-only target-mode pulse preflight
  -> optional configured print-profile selection
  -> Controller.apply_print_profile()
  -> SimMachine command completion
  -> settings revalidation
  -> schema-v3 pulse-aware provider
  -> retained artifacts and synthetic row
  -> real preview / confirmation / Apply
  -> existing ExperimentModel and Controller persistence paths
```

The physical Controller preflight remains unchanged. New application results
use schema v3 and all four normal-UI profile mappings. V1/v2 artifacts remain
byte-stable and readable, but historical pre-v3 synthetic candidates are
read-only because they lack pulse-response provenance. Existing authoritative
experiment state is not migrated.

## Gates

Run only directly affected response, provider, adapter, calibration UI,
profile, simulated-machine, and SIL lifecycle tests. Run Python compilation,
`git diff --check`, and `git status --short`. Then complete a visible fresh and
retained-root reload exercise covering 1300→9, 1800→18, 2500→60, 10000→250,
profile-driven forward/reverse mode transitions, manual refuel, snapshot,
disconnect, and reload reconciliation.

## Exclusions and rollback

No firmware, protocol, hardware factory, camera, physical calibration,
Controller preflight, experiment schema, or simulated dispense behavior is
changed. Rollback removes the v3 model/contracts, simulation preflight bridge,
legacy application restriction, tests, and this documentation. V1/v2 evidence
and retained experiments require no migration.
