# Milestone 8 Slice 8 Editable-Copy Dialog Focused Correction

## Trigger and scope

The first current-source lifecycle refresh failed the
`experiment_editor_post_start_lock_v1` child because the editable-copy naming
dialog was not observed. A direct diagnostic passed, but a five-process repeat
reproduced the same failure twice. Instrumented mouse activation then exposed
the underlying race: the global unexpected-dialog auditor could reject the
expected editable-copy name dialog before the local 5 ms modal driver observed
it. The production callback consequently returned as a cancellation without
copying the design.

The affected call path is:

`QTest mouse interaction` -> `ExperimentDesignDialog._on_duplicate_design()` ->
`EditableCopyNameDialog` -> `Model.duplicate_design_from()` -> editor reload.

This correction is restricted to the reusable page driver and its tests. It
does not change View, Controller, Model, simulator, protocol, firmware, Pi
configuration, or hardware behavior.

## Correction contract

- Reacquire the owning window and button focus before each attempt.
- Use separated QTest mouse move, press, and release events only.
- Register only the exact `Duplicate Experiment Design` /
  `EditableCopyNameDialog` pair with the unexpected-dialog auditor for the
  bounded duration of the action.
- Accept success only when the naming-dialog evidence and authoritative copied
  experiment directory agree.
- Retry exactly once only when the button emitted no activation and the
  authoritative postcondition remained false.
- Treat an activation without the postcondition as an ambiguous write and fail
  immediately.
- Retain attempt, activation, retry, and postcondition evidence in the report.

Focused validation covers a swallowed first release, ambiguous activation,
exhausted retry, repeated fresh-process post-start journeys, and the complete
lifecycle suite. Because the driver is an execution input, all Slice 8 Windows
evidence is refreshed after the correction. Rollback removes the bounded helper
and its tests and restores the prior single `mouseClick` interaction.
