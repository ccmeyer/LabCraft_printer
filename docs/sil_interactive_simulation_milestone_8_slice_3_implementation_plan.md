# Milestone 8 Slice 3 — Isolated Host Suite Execution and Aggregation

Status: approved for implementation (2026-08-07)

## Scope and call path

Enable explicit Windows `--suite` and `--capability` execution while preserving
Slice 2 dry-run planning and direct `--scenario` behavior. The execution path
is:

`CLI selector → validated Slice 2 plan → sequential fresh Python children → direct scenario runner → report-v1 → hashed aggregate`

The parent process must not import Qt or application modules. No production
View, Controller, Model, simulator, report-v1, protocol, firmware, Pi,
scheduler, matrix, exploration, baseline, or hardware behavior changes.

## Aggregate contract

Each run is retained under
`verification_reports/suites/<selector>/<timestamp>_<run-id>/` with the exact
plan, aggregate JSON/text, process logs, and child scenario evidence. The
`labcraft.virtual_workflow_aggregate` v1 document records selector/manifest
identity, timing, parent and child PIDs, commands, timeouts, return codes,
log/report paths and hashes, source identity, child and aggregate status, and
exact replay commands.

Every selected scenario runs even after another child fails. Success requires
one valid identity-matched report whose classification agrees with the process
return code. Timeout, launch failure, missing/ambiguous/invalid evidence,
identity mismatch, or process/report disagreement fails closed. A child
watchdog uses its plan timeout plus 60 seconds; timeout termination waits five
seconds before killing the process.

## Implementation and validation

1. Add a typed, Qt-free suite runner with contained artifact layout, bounded
   child processes, validation, hashing, atomic non-overwriting writers, and
   deterministic summary generation.
2. Allow Windows suite/capability execution in the CLI while retaining direct
   and dry-run compatibility and rejecting Pi/unsupported aggregate controls.
3. Add focused unit tests for success, warning, continuation, timeout,
   malformed/missing/ambiguous evidence, identity/return-code disagreement,
   containment, hashes, replay, exit codes, and import isolation.
4. Add a real standard-suite system regression proving fresh process identity
   and authoritative report/aggregate hashes.
5. Qualify standard, mixed-mode capability, lifecycle, visible standard, and
   exact visible replay. Run targeted tests only; the full suite remains
   deferred to Milestone 8 Slice 8.
6. Update README, roadmap, and the completion record only after qualification.

Rollback removes the aggregate runner and execution branch and restores
suite/capability selectors to dry-run-only. Existing scenario evidence,
manifest data, Slice 2 planning, persisted experiments, protocol, firmware,
and hardware state require no migration.
