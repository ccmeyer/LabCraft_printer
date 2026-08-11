# Milestone 8 Slice 7 Pi Proof Bootstrap Correction

## Scope

The first authorized `pi_primary` qualification attempt stopped before suite
execution because the traced 96-well proof audit was labeled
`offscreen_windows_sil`. The audit itself passed 96/96 completions on Linux
`aarch64` under the Bubblewrap private-device boundary, but the proof validator
correctly rejected a report not labeled `offscreen_pi_sil`.

The defect is confined to the common composed-report adapter. The legacy report
path already derives Pi run mode from the native Linux ARM environment, whereas
the composed adapter used a Windows fallback whenever no completed proof had
yet populated `report_identity`. A proof audit cannot supply that completed
proof without creating a circular dependency.

## Correction plan

1. Derive the composed adapter's default run mode from the collected operating
   system, architecture, and Qt platform, matching the existing legacy rule.
2. Preserve an explicit `report_identity.run_mode` as authoritative for normal
   proof-backed Pi children and preserve all Windows behavior.
3. Unit-test native Linux `aarch64` classification and retain a fail-closed
   trace-validator regression for a mislabeled audit.
4. Run the focused report and Pi-lane tests, then deploy the exact correction
   commit to the clean authorized Pi checkout.
5. Re-run only `pi_primary` and its exact replay. Retain all remote evidence and
   do not run `pi_stress`.

## Exclusions, risks, and rollback

No View, Controller, Model, simulator, fixture, manifest, protocol, firmware,
Pi configuration, or physical-hardware behavior changes. The main risk is
misclassifying an unrelated Linux host; classification is therefore restricted
to Linux `aarch64`/`arm64`, and proof-backed operational runs still require the
full preflight, traced proof, private-device safeguards, and matching hashes.

Rollback reverts the composed-report default and its focused tests. It requires
no data migration, Pi reconfiguration, firmware rollback, or hardware action.

## Retained failed-attempt evidence

The Pi retained the failed proof root at
`verification_reports/virtual_workflows/pi-sil/pi-safety-20260808T011436Z`.
Its audit report passed with 96 completed wells, no errors, no unexpected
dialogs, simulated port `SIMULATED`, and every hardware interface disabled.
The suite itself did not start.
