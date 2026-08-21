# Tools - Agent Instructions

## Scope

These rules specialize the repository root instructions for operational tools,
especially Pi development wrappers, remote workers, migration/update tooling,
firmware-state management, and evidence collection.

Read `README.md` and `docs/pi_development_workflow_plan.md` before changing the
behavior or interface of a Pi development wrapper.

## Protected orchestration invariants

- `/home/labcraft/LabCraft_printer` is a protected production worktree. Tools
  may inventory it read-only but must not switch, reset, clean, update, or write
  through it during development workflows.
- Development execution must use a clean, detached exact commit in
  `/home/labcraft/LabCraft_printer-dev` selected by the wrapper from a clean,
  pushed Windows revision.
- Logs, requests, uploads, runtime files, receipts, state, and reports must use
  declared absolute external development-workflow roots. Reject worktree paths,
  broad home/root paths, traversal, and ambiguous containment.
- The shared production interpreter is lexical, explicit, and read-only.
  Dependency-manifest mismatch is a blocker; tools must never install packages
  to make development pass.
- Development machine data must come from the persisted external binding with
  verified store and machine identities. Never fall back to production data or
  silently create a replacement store.
- Collect and compare production/development Git state, registered worktrees,
  machine-data evidence, workflow configuration, shared-environment evidence,
  firmware state, and related processes around every mutation or launch.

## Firmware-state and recovery rules

- Installed firmware is proven only by the durable external firmware-state
  schema plus exact artifact, flash, and SAFE evidence. Git state is not proof.
- State transitions must be atomic, compare-before-write, monotonic, and
  restricted to the documented transition graph. Write an external receipt for
  every durable transition.
- Record `recovery-required` before a flash. Record `development` or `released`
  only after the exact flash exits zero and strict SAFE passes.
- Autonomous firmware qualification is fixed SAFE-only. Reject FULL, selectors,
  extra tests, actuation metrics, or ambiguous inventories.
- Prevalidate the released artifact and recovery command before development
  flashing. Once development flashing begins, released restoration is
  mandatory even if development flash, SAFE, state publication, or later
  qualification fails.
- Never report production readiness unless durable firmware role is verified
  `released`.
- Never add a manual state-bypass, checkout inference, arbitrary artifact, or
  JSON repair path.

## Process and hardware boundaries

- Detect conflicting application, updater, DFU, flash, and HIL processes before
  mutation or launch.
- A supervisor may signal only the process group it created. Use bounded wait,
  SIGINT/SIGTERM/SIGKILL escalation as applicable, and record cleanup actions.
- No-hardware remains the default application lane and must not import, probe,
  or instantiate physical hardware factories.
- Hardware-capable launch requires a short-lived external authorization bound
  to operator, exact commit, data store, firmware-state bytes, and current
  confirmation hashes. Revalidate it at application bootstrap.
- Do not embed or reuse attended confirmation text in evidence or defaults as
  implicit authority. Require fresh user input for each campaign.

## Implementation method

Before changing a wrapper or remote worker:

1. Trace Windows wrapper -> local Python supervisor -> SSH request -> remote
   worker -> application/DFU/HIL entrypoint -> evidence and postflight.
2. State a plan of at most eight steps and list expected files.
3. Preserve compatibility with current configuration/evidence schemas or add
   an explicit migration and failure-closed version check.
4. Test success, refusal, interruption, cleanup, and protected-invariance paths.

Keep the PowerShell wrapper thin. Put validation and report logic in testable
Python. Treat all remote request values as untrusted and revalidate them on the
Pi immediately before use.

## Focused validation

- Run the focused `tests/test_pi_development_*.py`, firmware-state, launcher,
  migration, or updater tests that cover the changed tool.
- If the tool changes firmware builds, tracked artifacts, flashing, SAFE
  inventory, self-test, or HIL behavior, also follow `firmware/AGENTS.md` and
  run its mandatory combined firmware gate.
- Use fake SSH/subprocess tests for command construction and refusal paths.
- Use a unique OS temporary directory outside the repository for tests that
  create session roots.
- Do not run real SSH, flash, HIL, update, or hardware operations without the
  authority required by the root and firmware/application instructions.
- When command interfaces, evidence schemas, state transitions, recovery, or
  prerequisites change, update `README.md` and
  `docs/pi_development_workflow_plan.md` in the same milestone.

## Code review rules

Flag any path that can write to production, escape external roots, use a dirty
or moving commit, substitute artifacts, fall back to production data, leave
development firmware installed, kill unowned processes, or claim readiness
without durable evidence. The safe path is exact binding, fail-closed refusal,
owned cleanup, mandatory restoration, and sealed pre/post evidence.

## Definition of done

- Focused success and failure-path tests pass.
- Wrapper help/README/live-plan documentation matches behavior.
- Evidence remains structured, external, and sufficient to diagnose failure.
- Authorized Pi qualification preserves production/data/environment
  invariants, restores released firmware when required, and leaves no process.
