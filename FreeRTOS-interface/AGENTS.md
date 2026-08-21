# FreeRTOS Interface - Agent Instructions

## Scope

These rules specialize the repository root instructions for the Qt application,
MVC layers, machine communication, configuration/calibration storage, and
hardware dependency composition under `FreeRTOS-interface/`.

## Required call-path analysis

Before editing, locate and state the applicable path:

`UI -> Controller -> Model -> machine communications -> firmware handler`

If a layer is intentionally skipped, explain why. Provide a plan of at most
eight steps and list expected files before editing. Avoid broad MVC refactors;
make the smallest behavior-preserving change that satisfies the task.

## Runtime and machine-data boundaries

- Production and development machine-data roots are explicit external inputs.
  Never choose a store from the current checkout, working directory, missing
  file fallback, or legacy `local/` path.
- Development must validate the external store marker, machine identity, active
  pointer, and authorized root. Never fall back to, seed from, or write through
  production machine data during a development launch.
- No-hardware is the default development composition. It must use simulated
  dependencies and must not probe or instantiate serial, GPIO, DFU, camera,
  balance, or other physical factories.
- Hardware-capable development requires the explicit enable flag, both current
  confirmation contracts, and a short-lived external authorization bound to
  operator, exact commit, development store, current firmware-state bytes, and
  artifact hashes.
- Revalidate authorization and firmware compatibility at application bootstrap.
  Never infer readiness from environment variables or Git alone.
- Updater, rollback, release switching, and in-app firmware/DFU remain blocked
  in every development composition.

## Configuration, calibration, and history

- Do not directly overwrite canonical location, plate, obstacle, settings, or
  calibration JSON from UI/controller/model code.
- Route configuration changes through the guarded transaction/archive service
  so validation, backup, atomic replacement, history events, target
  verification, and recovery remain coherent.
- Large or out-of-envelope changes must use the configured review/verification
  workflow. Do not add silent auto-approval or a generic hardcoded threshold
  that bypasses target-specific policy.
- Plate calibration changes must preserve all coordinates and record reviewable
  before/after target evidence.
- Preserve immutable migration/activation evidence. Runtime configuration
  history is additive; do not rewrite old events to repair current state.

## Hardware-affecting changes

For motion, homing, pressure, pump, valve, dispensing, timing, camera, balance,
limit-switch, or real-hardware factory changes:

- Trace the complete MVC-to-firmware path and identify queue/timing boundaries.
- Define safe input bounds, rejection behavior, interruption behavior, and the
  machine state after rejection or cancellation.
- Add explicit verification steps and a rollback plan before implementation.
- Prefer SIL and no-hardware tests first. SAFE HIL does not authorize actuation.
- Do not run attended hardware behavior unless the user grants fresh scope and
  confirms the physical prerequisites for that campaign.

## Application validation

- Run focused unit/integration tests for every changed layer and failure path.
- Use SIL/no-hardware application construction for UI and orchestration changes
  before considering a hardware-capable launch.
- Tests must prove development data isolation, updater/DFU blocking, hardware
  factory exclusion in no-hardware mode, and authorization rejection when the
  relevant behavior changes.
- Use the root full-suite policy for final integration/release gates.
- Do not launch the Pi production app directly for development; use the
  repository wrappers and external evidence workflow.

## Code review rules

Flag direct canonical JSON writes, hidden machine-data fallbacks, no-hardware
physical imports/probes, development updater/DFU access, authorization bypass,
firmware inference from Git, and motion/pressure commands that can be queued
after a rejection. The safe path is explicit roots, guarded transactions,
simulated default composition, current authorization/state revalidation, and
bounded fail-closed control flow.

## Definition of done

- The call path and affected layers are documented.
- Focused tests cover success, rejection, cancellation, and persistence as
  applicable.
- No-hardware behavior remains physically isolated unless explicitly changed
  under attended authority.
- Configuration/history and machine-data invariants remain valid.
- The handoff includes risks, operator-visible effects, validation, and
  rollback.
