# Machine Data Migration Milestone 7 Completion Record

Status: `in_progress`

Started: 2026-08-20

Target release: `v1.3.0-rc.2`

Parent documents:

- [Machine Data Migration and Location Safety Plan](machine_data_migration_and_location_safety_plan.md)
- [Milestone 7 Implementation Plan](machine_data_migration_milestone_7_implementation_plan.md)
- [Machine Data Update and Rollback Runbook](machine_data_update_and_rollback_runbook.md)
- [Release Process](release_process.md)

## Current boundary

The verified M1-M6 branch has been merged into local `main`, and the untagged
rc.2 release commit is being constructed there. This record does not claim
that exact-commit Windows, target-Pi, attended hardware, local-tag,
publication, or rollout gates have passed. No `v1.3.0-rc.2` tag exists.

Physical Camera-route approval, firmware flashing, HIL, release publication,
and fleet rollout remain separate attended or operator-authorized gates.

## Slice 0 traceability audit

Every required parent-plan scenario has direct existing automated coverage.
No new runtime or test-code change is justified at candidate construction.
The exact collected node IDs and results will replace `pending execution` after
the focused gate runs.

| Requirement | Direct evidence | Status |
| --- | --- | --- |
| Exact rc.6 and rc.1 layouts | `test_machine_data_migration.py::test_historical_catalog_recognizes_both_reviewed_source_cohorts`; `test_machine_data_bootstrap.py::test_first_start_migrates_activates_and_reuses_from_second_checkout`; compatibility catalog tests | Mapped; pending execution |
| Machine-specific non-preset Camera | `test_machine_data_migration.py::test_custom_camera_is_not_mistaken_for_historical_camera`; Camera confirmation and authorizer tests | Mapped; pending execution |
| Camera-only/full-preset similarity | `test_machine_data_verification.py::test_camera_confirmation_and_preset_service_rules_fail_closed`; `test_machine_data_bootstrap_dialog.py::test_preset_like_candidate_surfaces_independent_service_requirement` | Mapped; pending execution |
| Folder layouts and ZIP | parametrized explicit shallow-layout test; missing/ambiguous layout test; selected-ZIP semantic-equality test | Mapped; pending execution |
| Duplicate/conflicting candidates | candidate comparison and bootstrap-dialog duplicate/conflict tests | Mapped; pending execution |
| Missing/malformed/partial data | invalid required/safety and incomplete calibration tests; archive and persisted-evidence parser tests | Mapped; pending execution |
| Existing canonical and new checkout | existing-canonical inspection, second-checkout bootstrap, and deployment-anchor reopen tests | Mapped; pending execution |
| Permission/disk/lock/interruption | insufficient-space, lock-contention, migration-recovery, transaction-fault, and update-recovery tests | Mapped; pending execution |
| Verification cancellation/revocation | bootstrap worker cancellation, cancelled transaction, target authorizer, and revoked legacy-export tests | Mapped; pending execution |
| Named/rack/plate history | named-location transaction and rack-pair/plate-quartet aggregate transaction tests | Mapped; pending execution |
| Guarded edits | safety-policy, preview, guarded-workflow, capture-precondition, and adapter tests | Mapped; pending execution |
| Update preservation | preservation, recovery, deployment-anchor, updater, window, and app-launch tests | Mapped; pending execution |
| Legacy rollback/re-upgrade | compatibility export, exact return, Camera conflict, and keep-canonical tests | Mapped; pending execution |
| Simulation/no hardware | App bootstrap ordering, safe construction, send-path guards, Pi hardware proof, and contained SIL | Mapped; pending execution |
| Release metadata/tag/bundle | release validator, candidate-series update check, bundle, and tag-validation tests | Mapped; pending execution |

## Read-only target-Pi Slice 0 preflight

On 2026-08-20, authorized read-only SSH inspection of
`labcraft@192.168.0.33` recorded:

- clean `update_bug_fix` checkout at `0ee3e50a`;
- `VERSION` `v1.3.0-rc.1`;
- no running `FreeRTOS-interface/App.py` process;
- no `LABCRAFT_MACHINE_DATA_ROOT` environment override;
- Desktop backup wrapper present for the rc.1 cohort;
- 148 backed-up `local/` files totaling 746,658 bytes;
- backup and live `Locations.json` hashes matched at truncated SHA-256
  `3e5b4de9...c5f3c7d02`;
- backup and expected Settings evidence matched at truncated SHA-256
  `69a5f4b9...a7646a`;
- hardware profile `current`; and
- resolved default external root below Qt application-local data, outside the
  Git checkout.

The exact Camera value, paths, and checklist state are retained only in ignored
private evidence. The prior external-drive backup is operator-attested but was
not mounted during this read-only inspection; it must be refreshed and opened
again before attended qualification.

## Candidate implementation

Working-tree changes prepared on local `main` on 2026-08-20:

- `VERSION` advanced to `v1.3.0-rc.2`;
- release index points to rc.2 while stable remains `v1.2.0`;
- rc.2 manifest declares the exact M6 machine-data preservation contract with
  `transition: none`;
- lineage is rc.1 to rc.2 with reviewed rollback target `v1.2.0`;
- the explicit v1.3 firmware requirement is retained for direct rc.6/v1.2.0
  upgrades while documenting byte identity with rc.1; and
- changelog/release notes cover external data, migration, verification,
  history, guarded changes, update preservation, support-guided rollback, and
  firmware pairing.

No runtime, firmware, protocol, motion, pressure, or updater source changed in
this candidate-construction slice.

## Windows validation

Status: exact-candidate gate pending.

Pre-candidate checks on the same application/release tree passed 570 focused
tests with one skip, release-metadata and release-JSON validation, firmware
identity checks, and one contained 96/96 SIL journey. The discarded first
pytest attempt executed no test bodies because the sandbox denied its default
temporary directory; the successful rerun used a unique OS-temporary base
outside the repository. Final full-suite and clean-commit evidence must be
collected again against the exact release commit.

The initial target-Pi sandbox attempt found that the private `/tmp` mount hid a
candidate checkout located below `/tmp`. Candidate execution stopped before
Python, the application, or hardware access. The Pi SIL shell now re-binds only
the candidate repository read-only after mounting the private `/tmp`, then
overlays only its evidence output writable. A regression assertion fixes that
mount order. The candidate must be re-frozen and all exact-commit gates rerun.

Record focused count, full-suite count/skips, contained SIL result, metadata,
JSON, firmware fingerprint, compilation, diff, and worktree evidence here.

## Target-Pi unattended qualification

Status: pending candidate commit and transport bundle.

Record the random `/tmp` parent, candidate SHA, cohort roots, test results,
hardware-isolation proof, production pre/post comparison, archive member count,
and archive SHA-256 here.

## Attended designated-machine qualification

Status: pending operator approval and attendance.

Record refreshed M0 copies, migration/config/Camera comparison, no-command
probe, audit/restore, firmware provenance or flash, SAFE/HIL results, Camera
route, observations, and evidence archive here.

## Local tag, updater, and rollback qualification

Status: pending attended pre-tag gate.

Record peeled tag commit, metadata tag validation, release-aware bundle hash,
exact rc.6/rc.1 old-updater lanes, offline equivalence, unchanged return, and
synthetic Camera-conflict recovery here.

## Publication and rollout

Status: not authorized.

Record tag/branch publication order, remote refs, controlled public-tag result,
rc.6 pilot, rc.1 pilot, evidence reviews, fleet batches, and final decision
here.

## Evidence

Private evidence root:
`verification_reports/machine_data_m7/`

No private evidence is tracked by Git. Final archives require a Pi-side and
post-transfer checksum match before their truncated hash is recorded here.

## Open gates

- Focused and complete Windows validation.
- Exact candidate commit and verified transport bundle.
- Disposable SSH/Pi qualification and archive recheck.
- Private operator, rc.6 pilot, rc.1 pilot, fixtures, and Camera-route approval.
- Attended designated-machine migration, firmware, HIL, and Camera route.
- Local tag and exact legacy updater/rollback qualification.
- Release publication and staged rollout.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Created the in-progress completion record, closed the software traceability audit without a code change, recorded sanitized read-only Pi preflight evidence, and documented the untagged rc.2 candidate changes and remaining gates. |
| 2026-08-20 | Recorded the local `main` integration boundary and the passing pre-candidate focused, metadata, firmware-identity, and contained-SIL checks without claiming the exact-commit gate. |
| 2026-08-20 | Recorded and corrected the Pi SIL private-`/tmp` visibility gap; the failed attempt reached neither Python nor hardware, and exact-candidate qualification restarted. |
