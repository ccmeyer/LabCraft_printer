# Changelog

## v1.3.0-rc.10 - 2026-08-25

### Fixed

- Made fill calibration preview and application share one authoritative calculation from the immutable finalized execution plan. Sparse uploaded designs retain their exact explicit well IDs, while preview and committed revisions use identical old/new droplet counts and totals.
- Made printer-head calibration identity durable across object reconstruction by consistently preferring `printer_head_id`, then `serial`, then legacy `id`. A genuinely different durable head remains ineligible for the recorded calibration.
- Made machine interruptions terminate droplet-calibration work immediately and idempotently. Disconnect, serial loss, reset, transport faults, queue clearing, pause, and homing interruption now cancel pending capture without recovery hardware actions, clear queued work, close active sequences, and prevent late callbacks from reviving work.
- Refreshed selected calibration result readiness when connection, busy, capture, fault, dirty-shutdown, and gripper context changes. An open fill-calibration dialog now regains preview and Apply readiness after reconnect and same-head reconstruction without row reselection.
- Corrected SIL workflow handling for delayed printable-well dialogs, deleted Qt wrappers, and calibration results hidden by an older result-set filter. The terminal-label oracle now distinguishes **Array Complete** while the final head remains loaded from **Experiment Complete** after that head is returned.

### Changed

- Added explicit, default-cancelled **Record diagnostic calibration?** consent for progressed, terminal, or known out-of-plan stocks. Confirmed diagnostic results remain recorded for analysis but cannot modify the current design or execution.
- Routed pressure sweep, manual characterization, online stream calibration, recheck, Calibrate All, stream sequences, and pulse-width sweeps through the same non-sticky diagnostic-consent eligibility check.

### Safety and compatibility

- Printed-progress and terminal execution safeguards remain authoritative for fill and non-fill stocks. Diagnostic confirmation never bypasses Apply eligibility, and missing identity, unreadable progress, runtime mismatch, inactive persisted execution, and historical/read-only execution remain hard blockers.
- Disconnect cleanup never initiates capture-recovery hardware actions. Ordinary user Stop behavior remains graceful and all existing execution, progress, storage, and canonical-result integrity checks remain fail-closed.
- Device protocol, execution-plan and calibration-record schemas, machine-data schema version 1, update preservation contract, dependencies, and firmware source are unchanged.
- The bundled firmware is byte-identical to rc.7, rc.8, and rc.9: 367,968 bytes with SHA-256 `1FEC7C6C8D3C0022844695CDF51A860539BCFBDA291BB18C12A99062C7A32577`. Direct legacy upgrades must still deploy and verify this exact artifact.

### Validation

- Focused fill lifecycle SIL, fill requantization, durable identity, calibration audit, interruption/capture, reconnect UI, and workflow-harness regressions passed on the merged release candidate.
- Complete Python suite passed 5,843 tests with 158 expected skips; release-metadata validation, strict release-JSON parsing, firmware identity, and static diff checks passed on the release candidate.
- During attended LC-001 verification at exact pushed implementation commit `465446ba`, the operator confirmed the simulated fill-calibration workflow behaved as intended. A separate hardware-capable window-only launch exited normally; exact released-firmware restoration then passed strict SAFE 30/30, final production readiness was true, and no related process remained.

### Rollback

- The reviewed application rollback target remains stable `v1.2.0`. Because it predates external machine data, use only the support-guided compatibility export and restore its paired firmware.
- Do not manually edit authoritative execution files, calibration history, machine data, or firmware-state evidence during rollback.

## v1.3.0-rc.9 - 2026-08-25

### Fixed

- Restored printer-head cleaning return to the exact pre-cleaning imager position by replacing the blocked custom Camera target with a Controller-owned, in-memory checkpoint bound to the current machine, motion-trust epoch, telemetry, command state, and exact endpoint.
- Kept cleaning recovery fail-closed: forged or released tokens, changed trust, stale telemetry, unsafe endpoints, failed dispatch, and stale completion callbacks cannot authorize a different coordinate or silently finish the workflow.
- Prevented Prep Stocks from trapping users after an execution plan is locked. **Save and Close**, the window X, and Escape now write only the optional worksheet sidecar; a failed write offers Retry or a default **Close Without Saving** path that always dismisses the dialog.

### Changed

- Moved mutable preparation volume, source concentration, and worksheet defaults into optional `stock_prep.json`. Target concentrations, effective dispense volumes, stock identities, and total required volumes remain derived from the current execution plan.
- Allowed Prep Stocks during PREPARED and ACTIVE executions. Completed, aborted, invalid-authoritative, and recorded legacy experiments expose the same editable calculator without persistence, while calibration remains disabled in historical views.
- Preserved exact matching stock entries across a legitimate prepared-plan replacement and ignored malformed worksheet entries, bindings, schemas, and files without affecting execution eligibility.

### Safety and compatibility

- The cleaning return exception is scoped only to the exact zero-offset Camera checkpoint captured for the current cleaning session; ordinary saved-target authorization remains unchanged for every other request.
- `stock_prep.json` is non-authoritative and is excluded from design hashes, execution bundles, immutable revisions, resume checkpoints, calibration evidence, and active-runtime file monitoring. Existing embedded worksheet data remains unchanged for older software and fallback loading.
- Device protocol, machine-data schema version 1, update preservation contract, execution-plan schema, and firmware source are unchanged.
- The bundled firmware is byte-identical to rc.7 and rc.8: 367,968 bytes with SHA-256 `1FEC7C6C8D3C0022844695CDF51A860539BCFBDA291BB18C12A99062C7A32577`. Direct legacy upgrades must still deploy and verify this exact artifact.

### Validation

- Focused cleaning checkpoint, cleaning-dialog, Stock Prep, execution-plan, authoritative-load, duplication, updater, and virtual-workflow tests passed.
- Complete Python suite passed 5,821 tests with 156 expected skips; release-metadata validation, strict release-JSON parsing, firmware identity, and static diff checks passed on the release candidate.
- During an attended LC-001 hardware-capable development session at exact pushed commit `e39ebf3f`, the operator verified both printer-head cleaning return and Prep Stocks behavior. The launch exited normally, exact released firmware restoration passed strict SAFE, final production readiness was true, and no related process remained.

### Rollback

- The reviewed application rollback target remains stable `v1.2.0`. Because it predates external machine data, use only the support-guided compatibility export and restore its paired firmware.
- Older software ignores `stock_prep.json`; the frozen embedded worksheet remains available. Do not manually edit authoritative execution files, machine data, or firmware-state evidence during rollback.

## v1.3.0-rc.8 - 2026-08-24

### Fixed

- Restored direct first-start migration from `v1.2.0`, `v1.2.0-rc.6`, and `v1.3.0-rc.1` by allowing rc.8 to create the initial deployment anchor only while completing the currently reviewed activation transaction.
- Bound genesis enrollment to the exact immutable migration receipt, verified backup, machine identity, activation receipt, verification receipt, target version, and full target commit. Unsupported source releases remain blocked.
- Made the deployment anchor durable before publishing `active_machine.json`. An enrollment failure now leaves no apparently active machine and retains the staged evidence for support-guided recovery.
- Prevented ordinary startup from creating or recreating a missing deployment anchor, including a deleted anchor on the same rc.8 commit.

### Added

- Added an exact-tag upgrade-rehearsal workflow that runs each preserved legacy cohort through its original updater, visible cancellation and source review, isolated activation, exact migration verification, and second-checkout reuse without touching production data or firmware.

### Safety and compatibility

- Machine-data schema version 1, the update preservation contract, configuration history, and device protocol are unchanged.
- The bundled firmware is byte-identical to rc.7: 367,968 bytes with SHA-256 `1FEC7C6C8D3C0022844695CDF51A860539BCFBDA291BB18C12A99062C7A32577`. Legacy-source machines must deploy and verify that exact firmware; application update success alone is not firmware provenance.
- Rc.7 remains immutable but is not approved for direct rc.6/rc.1 rollout. Failed rehearsal roots are retained and never reused.

### Validation

- Focused bootstrap, migration, deployment-anchor, updater-rehearsal, and recovery tests passed on Windows and the isolated Pi development worktree.
- The exact correction commit passed Pi `Status -> Sync -> Validate` and the five-second physically isolated no-hardware launch with protected invariants unchanged.
- Complete Python suite passed 5,785 tests with 156 expected skips; release-metadata validation, strict release-JSON parsing, and static diff checks passed before tagging. Exact-tag rc.1/rc.6 rehearsal remains the fleet-rollout gate.

### Rollback

- The reviewed application rollback target remains stable `v1.2.0`. Because it predates external machine data, use only the support-guided compatibility export and restore its paired firmware.

## v1.3.0-rc.7 - 2026-08-24

### Fixed

- Made coordinated XY completion endpoint-safe across firmware and host layers. Firmware now distinguishes queue depletion from physical endpoint completion, while the application waits for coherent terminal X/Y/Z telemetry before advancing a dependent workflow.
- Preserved the exact commanded endpoint through pause/resume and queue drain instead of allowing stale partial telemetry to replace it. Genuine coherent mismatches, trust changes, and timeouts remain fail-closed.
- Replaced stale post-home reconciliation with a fresh all-axis Home telemetry barrier bound to the new motion-trust epoch. Plate-calibration preflight now reports a missing calibration head deterministically and queues no motion.
- Moved rack calibration travel into a token-bound Controller session. Initial entry, inter-anchor moves, Back navigation, and the final retract all reach the qualified `Z=500` plane before rack-directed XY travel and suppress dependent commands after any rejection or interruption.
- Added a pre-motion plate-installed acknowledgement and kept plate entry safe-height-first. Cancelling the acknowledgement leaves motion, temporary captures, governed configuration, and authorization unchanged.
- Corrected plate-relative Pause maintenance: a successful plate calibration now preserves Pause X/Y and atomically derives Pause Z from the calibrated top-left corner.

### Changed

- A guarded **Save New Location** or **Modify Location** operation now immediately verifies the captured value when fresh machine identity, trust epoch, telemetry, and exact expected/reported-position evidence all agree.
- Ordinary pending locations can be reviewed through read-only coordinates and one explicit acknowledgement checkbox; users no longer transcribe exact JSON. Plate and rack targets continue to direct users to their physical calibration workflows.
- The Pi development firmware and hardware wrappers now default their released recovery binding to `v1.3.0-rc.7`; explicit release arguments remain supported.

### Safety and compatibility

- This release changes the bundled firmware. Deploy and verify the exact 367,968-byte rc.7 artifact with SHA-256 `1FEC7C6C8D3C0022844695CDF51A860539BCFBDA291BB18C12A99062C7A32577`. Application update success alone is not proof of installed firmware.
- Device command framing and payload layouts are unchanged. SAFE remains non-actuating, and FULL or physical motion qualification remains attended-only.
- Machine-data schema version 1 and the external preservation contract are unchanged. Existing authorized values and immutable history remain intact; only governed values explicitly changed by a transaction receive new events or authorization evidence.
- Release rollback remains support-guided stable `v1.2.0` with its paired firmware and compatibility export; do not manually edit machine data or firmware-state evidence.

### Validation

- Firmware gate: 485/485 host tests passed and the STM32CubeIDE Debug target built successfully from the merged source.
- Focused Windows and Pi tests passed for endpoint reconciliation, guarded configuration, plate/rack calibration, updater metadata, and development workflow behavior.
- Complete Python suite, release metadata validation, strict JSON parsing, and static diff checks passed on the final untagged candidate.
- Attended isolated-development qualification on LC-001 verified safe plate and rack entry, successful saves, immediate controlled verification, cancellation without partial writes, and no unexpected activity; exact rc.6 firmware restoration and protected postflight passed afterward.

### Rollback

- The reviewed application rollback target remains stable `v1.2.0`. Because that release predates the external machine-data preservation contract, use only the support-guided compatibility export in `docs/machine_data_update_and_rollback_runbook.md`.
- Restore and verify the firmware artifact paired with the rollback release; application rollback does not automatically establish installed-firmware provenance.

## v1.3.0-rc.6 - 2026-08-24

### Fixed

- Debounced the X/Y optical limit inputs with a continuously running 1 MHz TIM5 service and bounded 15 ms confirmation deadlines. Both coordinated and direct motion paths now share the same wrap-safe confirmation policy and retain exact limit attribution through terminal cleanup.
- Reworked pause/resume so coordinated X/Y and direct-axis moves resume from a fresh remaining-distance plan, begin at the bounded 3 kHz restart rate, rearm disabled stepper drivers exactly once, wait for the powered-settle interval, and retain the original commanded endpoint.
- Guarded queue clearing and Resume against active or invalid terminal plans. Clearing, pausing, disconnecting, resetting, or changing motion trust now cancels dependent workflows instead of allowing stale commands or UI state to continue.
- Canonicalized exact-integral host motion endpoints and reconciled queue completion against one coherent post-motion X/Y/Z telemetry generation, preventing stale partial telemetry from replacing the commanded endpoint.
- Made plate-calibration entry fail closed. Every entry raises Z to 500 before the plate dogleg or XY travel; unverified plates stop at safe height for manual first-point alignment, and verified plates descend only after exact telemetry reconciliation.
- Removed calibration-dialog constructor motion and moved remaining plate-corner planning into a token-bound Controller session. Interruption, mismatch, timeout, stale callbacks, or trust changes discard temporary captures without saving.
- Corrected pause/action-button layout and sizing while preserving keyboard and disconnect behavior.

### Changed

- Successful rack and plate calibrations now atomically save the governed configuration event and authorize their exact targets as `verified_by_controlled_calibration`. Eligible older controlled-calibration evidence can be reviewed and promoted without motion or coordinate transcription.
- Guarded configuration confirmation now uses one proposal-bound acknowledgement checkbox instead of a typed `SAVE ...` phrase. Imports, restores, and ordinary edits still revoke changed targets until separately verified.
- Rebuilt the well-plate preview immediately after calibration while preserving the selected reagent by stock ID.

### Safety and compatibility

- This release changes the bundled firmware. All upgrades from `v1.2.0`, `v1.2.0-rc.6`, or `v1.3.0-rc.1` through rc.5 require deployment and verification of the exact rc.6 artifact. The application update alone does not prove that the controller was flashed.
- The rc.6 firmware artifact is 366,144 bytes with SHA-256 `CFC1103B7A4EAB58688CDD3303DB0174C8B3FDF8887FA0C7C90B931FDB87DFA5`.
- Device command framing and payload layouts are unchanged. SAFE remains non-actuating, and FULL or physical motion qualification remains attended-only.
- Machine-data schema version 1 and the external preservation contract are unchanged. Existing migrated target authorization and history are preserved when their exact values remain unchanged; only targets changed by a guarded operation are revoked.

### Validation

- Firmware gate: 480/480 host tests passed and the STM32CubeIDE Debug target built successfully from the merged source.
- All 36 Python test modules changed by this branch passed: 697 tests.
- Complete Python suite: 5,686 passed and 156 skipped.
- Release metadata validation, strict parsing of every release JSON file, and static diff checks passed on the untagged candidate.
- The safe-height plate-entry, controlled plate/rack authorization, cancellation, and repaint paths completed an attended isolated-development qualification on LC-001 at implementation checkpoint `02fdd92c`; the final rc.6 candidate is separately required to pass exact-artifact SAFE 30/30 with released-firmware restoration.

### Rollback

- The reviewed application rollback target remains stable `v1.2.0`. Because that release predates the external machine-data preservation contract, use only the support-guided compatibility export in `docs/machine_data_update_and_rollback_runbook.md`.
- Restore and verify the firmware artifact paired with the rollback release; application rollback does not automatically establish installed-firmware provenance.

## v1.3.0-rc.5 - 2026-08-20

### Fixed

- Normalized derived well coordinates to exact built-in integers and added a complete print-array endpoint preflight. Every remaining well and row-entry approach must now pass coordinate, global-bound, and active-plate authorization checks before the execution plan is locked or any hardware command is queued.
- Fixed production restart after legitimate calibration activity by classifying validated active `CalibrationMemory/` and `calibration/` payloads as runtime-owned. Copied, staged, and unverified migrations remain byte-exact; the calibration-memory schema and required seed documents remain enforced.
- Kept governed configuration, including `Locations.json`, `Plates.json`, target authorization, configuration history, active-machine identity, activation evidence, and deployment anchors under their existing exact or transaction-backed integrity checks.

### Added

- Added a byte-verified external development-store clone and a commit-bound development launcher so ordinary code changes can be exercised without changing the production deployment or its authorized machine-data tree.
- Development launches default to a simulated machine with serial, camera, GPIO, updater, and firmware/DFU access blocked. Attended hardware development requires an explicit hardware flag and the exact warning confirmation, while update and firmware controls remain blocked.

### Safety and compatibility

- Production startup still requires the exact commit authorized by the protected updater. Development mode can bypass that release gate only for a separately marked external development store and cannot reinterpret the production store as development data.
- The print-array correction fails before queueing hardware work if any endpoint is invalid; it accepts only values that are already mathematically integral and never truncates fractional, non-finite, or Boolean values.
- This release changes no firmware, device protocol, pressure behavior, or firmware timing. The bundled firmware artifact is byte-identical to rc.1 through rc.4 with SHA-256 `EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884`.

### Validation

- Complete Python suite: `5,461 passed, 156 skipped`.
- Focused migration, development-composition, updater/deployment, and print-array guard suites passed on Windows.
- Contained Windows and Raspberry Pi `virtual_print_array_96_v1` qualification completed 96/96 with hardware isolation.
- A disposable external development clone reopened on the Pi with `SimulatedMachine`, blocked updater access, no physical interface, and commit-bound session evidence.
- Read-only production inspection accepted the runtime calibration changes and reported only the expected rc.4 deployment-anchor mismatch while the checkout was on the rc.5 code candidate; the complete production tree fingerprint remained unchanged.

### Rollback

- The reviewed rollback target remains `v1.2.0` with its matching firmware and the support-guided compatibility export described in `docs/machine_data_update_and_rollback_runbook.md`.
- Before the protected rc.4-to-rc.5 update, retain the current production calibration-memory files and restore the two timestamp-only files from the verified rc.4 migration source so rc.4 can authorize the updater. Do not edit coordinates or bypass the deployment anchor.

## v1.3.0-rc.4 - 2026-08-20

### Fixed

- Fixed guarded exact-backup restore so it can remove a location or plate calibration that was added by the transaction being undone; ordinary governed imports still cannot remove saved coordinates.
- Bound every restore preview to the source transaction, active machine identity, immutable source-event manifest hash, backup fingerprint, and exact member hashes, and revalidate that binding immediately before commit.
- Restores now fail closed if the source event is missing or ambiguous, the backup changed after its original event or after preview, the active machine identity differs, or the configuration changed while the review window was open.
- Clarified the restore review window by displaying the verified transaction and manifest, marking removals explicitly, and naming the exact-backup/revocation consequence on the action button.

### Safety and compatibility

- The correction changes no firmware, device protocol, motion, pressure, coordinate, obstacle, or timing behavior. Changed restored targets remain revoked until separately verified, and the current no-command authorization gate remains in force.
- `v1.3.0-rc.3` remains immutable. This release preserves its external machine-data, audit history, guarded-change, protected-update, and rollback contracts and is intended to repair the attended restore failure without manual configuration editing.

## v1.3.0-rc.3 - 2026-08-20

### Fixed

- Fixed the protected updater's source identity mismatch: the app now binds updates to the full 40-character Git commit used by the updater and deployment anchor.
- Added narrowly scoped compatibility for the exact 12-character lowercase hexadecimal commit prefix written by `v1.3.0-rc.2`; shorter, uppercase, non-hexadecimal, and mismatched values continue to fail closed.
- Added an attended recovery launch mode for an already-enrolled rc.2 machine. It derives identity from the authorized external store, requires the recorded `source_binding_mismatch` failure log, and requires a clean separately qualified updater checkout whose commit exactly equals the requested target tag.
- Ensured a recovery updater executed from a separate target checkout uses that target's machine-data protection modules while still applying Git only to the explicitly selected production checkout.
- Extended reviewed first-start genesis enrollment to rc.3 for machines upgrading directly from rc.6, v1.2.0, or rc.1, while binding enrollment to rc.3's exact activation and verification evidence so a removed rc.2 anchor cannot be silently recreated by rc.3.

### Safety

- The failed rc.2 update occurs before a preservation transaction or Git mutation; rc.3 retains that fail-before-Git behavior for every identity mismatch outside the exact historical compatibility case.
- All new launch bindings, transaction evidence, and deployment anchors use full commit identities. Successful update authorization still requires a verified pre-update archive, unchanged protected bytes, the exact target commit, and a receipt-gated relaunch decision.
- The rc.2 recovery mode cannot accept manually supplied machine identity fields, cannot run rollback/offline/automatic-relaunch paths, and cannot operate on any source version or deployment-anchor shape other than the affected rc.2 genesis enrollment.

### Firmware

- The bundled firmware artifact is unchanged from `v1.3.0-rc.2` and `v1.3.0-rc.1`: SHA-256 `EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884`.
- Machines updating directly from `v1.2.0-rc.6` or `v1.2.0` still require the v1.3 firmware. Machines already on `v1.3.0-rc.1` or rc.2 must verify matching firmware provenance or redeploy the artifact.

### Validation

- Complete Python suite: `.\env\Scripts\python.exe -m pytest -q`.
- Release metadata validation: `.\env\Scripts\python.exe tools\validate_release_metadata.py`.
- Contained Windows and target-Pi `virtual_print_array_96_v1` qualification with hardware isolation.
- Disposable target-Pi qualification of the exact rc.2 short-binding recovery, verified backup, no-schema byte preservation, full target anchor, and target bootstrap reopen.
- Static checks: `git diff --check` and strict parsing of every release JSON file.

### Rollback

- The reviewed rollback target remains `v1.2.0` with its matching firmware.
- Because `v1.2.0` predates the external machine-data preservation contract, use only the support-guided compatibility-export procedure in `docs/machine_data_update_and_rollback_runbook.md`.

## v1.3.0-rc.2 - 2026-08-20

### Added

- Added checkout-independent external machine data shared by every checkout and worktree on an authorized machine.
- Added fail-closed first-start migration for `v1.2.0-rc.6`, `v1.2.0`, and `v1.3.0-rc.1`, including verified backups, exact copy evidence, machine identity confirmation, Camera review, and per-target authorization.
- Added immutable configuration history, exact restoration, and aggregate transactions for named locations, rack pairs, and four-corner plate calibrations.
- Added guarded configuration previews with exact deltas, hard-invalid rejection, and stronger confirmation for policy-threshold changes.
- Added external update-preservation transactions, deployment anchors, receipt-gated relaunch, exact post-update byte verification, and support-guided legacy compatibility export and rollback.

### Changed

- Corrected first-start inspection of the prefilled checkout-local `local/` directory so it is treated as a direct candidate instead of an invalid nested `local/local` source.
- Replaced manual Camera-coordinate transcription with read-only values sourced from immutable inspection evidence and a dedicated approval to preserve that exact position.

### Safety

- Missing checkout-local or external data no longer silently becomes motion-authorized tracked preset data.
- Saved-location authorization is checked before any safe-height, dogleg, or final-target command is queued.
- Preset-like Camera values require explicit review and service evidence; migration requires the selected source, verified backup, canonical destination, and confirmation to agree exactly.
- Changing the inspected source clears both Camera and whole-source approvals; activation cannot reuse stale review state.
- Legacy rollback keeps canonical data frozen, verifies a target-specific checkout-local export before changing Git, and treats every legacy edit as an explicit re-upgrade conflict rather than silently copying it.

### Firmware

- The bundled firmware artifact is unchanged from `v1.3.0-rc.1`: SHA-256 `EDA070CE734D5167F0795FAF30DF461C8A07341E09CA698DE9D850315B0D5884`.
- Machines updating directly from `v1.2.0-rc.6` or `v1.2.0` must install the required v1.3 firmware. Machines updating from `v1.3.0-rc.1` must verify matching firmware provenance or redeploy the artifact. The application updater does not flash firmware automatically.

### Validation

- Complete Python suite:
  `.\env\Scripts\python.exe -m pytest -q`
- Release metadata validation:
  `.\env\Scripts\python.exe tools\validate_release_metadata.py`
- Contained Windows and target-Pi `virtual_print_array_96_v1` qualification with hardware isolation.
- Disposable target-Pi exact rc.6/rc.1 migration, update, rollback, re-upgrade, and cross-checkout qualification over SSH.
- Attended LC-001 app/firmware, focused HIL, fail-closed target, guarded audit/restore, and machine-specific Camera-route qualification.
- Static checks:
  `git diff --check`
  `Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }`

### Rollback

- The reviewed rollback target is `v1.2.0` with its matching firmware.
- Because `v1.2.0` predates the external machine-data preservation contract, rollback is support-guided and must use the authorized compatibility-export procedure in `docs/machine_data_update_and_rollback_runbook.md`; do not run a shortened backend command.

## v1.3.0-rc.1 - 2026-08-18

### Changed

- Added normalized-LUT direct XYZ motion and coordinated production XY motion with bounded terminal guarantees.
- Added MCU XY failure context, bounded homing recovery for rejected move starts, and guided operator recovery for failed XY motion.
- Hardened firmware watchdog, motion-limit, pressure, gripper, flash, and printing behavior while expanding host, HIL, and qualification coverage.
- Made canonical calibration recording and history authoritative, with historical conversion, recovery, and refined Droplet and Stream calibration workflows.
- Improved durable experiment execution, resume behavior, experiment editing, workflow diagnostics, and hardware-isolated verification.
- Updated the application and bundled firmware together; `v1.3.0-rc.1` must be deployed with its matching firmware because the command and reset-diagnostic contracts evolved in lockstep.

### Validation

- Full Python suite:
  `.\env\Scripts\python.exe -m pytest -q`
- Firmware host tests and headless build:
  `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- Full firmware HIL plus focused direct-LUT, normal-XY, production-MRES3, and camera-transition qualification on `LC-001`.
- Metadata and static checks:
  `.\env\Scripts\python.exe tools\validate_release_metadata.py`
  `git diff --check`
  `Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }`

### Rollback

- Roll back the application to `v1.2.0` and restore its matching firmware; the application updater does not flash firmware automatically.

## v1.2.0 - 2026-08-18

### Changed

- Promoted the deployed `v1.2.0-rc.6` application and firmware payload unchanged to final stable `v1.2.0`.
- Set `v1.2.0` as the stable application release and prepared support-guided release-candidate discovery for `v1.3.0-rc.1` and later `v1.3.0-rc.N` tags.
- Kept normal online updates on the stable release channel by default while preserving the support-guided release-candidate toggle.
- Kept application behavior, the bundled firmware binary, device protocol, motion, pressure control, Model behavior, and updater logic identical to `v1.2.0-rc.6`.

### Validation

- Full Python suite:
  `.\env\Scripts\python.exe -m pytest -q`
- The release metadata validator from the current release tooling was run externally against this promotion checkout.
- Metadata and static checks:
  `git diff --check`
  `Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }`

### Rollback

- Recommended rollback version: `v1.1.17`.

## v1.2.0-rc.6 - 2026-07-07

### Changed

- Carried forward the camera/refuel release-candidate line from `v1.2.0-rc.5`.
- Merged the stable metadata release `v1.1.17` so stable-channel machines can discover this release candidate from the in-app updater.
- Kept normal online updates on the stable release channel by default while preserving the support-guided release-candidate toggle.
- Updated the release-candidate rollback target to `v1.1.17`.
- No additional firmware, device protocol, motion, pressure-control, or Model changes beyond the existing camera/refuel release-candidate line.

### Validation

- Recommended before tagging:
  `.\env\Scripts\python.exe -m pytest -q`
- Metadata/static checks:
  `git diff --check`
  `Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }`

### Rollback

- Recommended rollback version: `v1.1.17`.

## v1.1.17 - 2026-07-07

### Changed

- Added a metadata-only stable release for advertising the next camera/refuel release candidate to stable-channel machines.
- Updated the release-candidate pointer from `v1.2.0-rc.4` to `v1.2.0-rc.6`.
- Kept normal online updates on the stable release channel by default unless the operator enables release-candidate updates.
- No firmware, device protocol, motion, pressure-control, Model behavior, updater logic, or rollback behavior changes.

### Validation

- Focused updater and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.16`.

## v1.2.0-rc.5 - 2026-07-07

### Changed

- Carried forward the camera/refuel release-candidate line from `v1.2.0-rc.4`.
- Merged the stable updater and rollback hardening line through `v1.1.16`.
- Kept normal online updates on the stable release channel by default while preserving the support-guided release-candidate toggle.
- Updated the release-candidate rollback target to `v1.1.16`.
- No additional firmware, device protocol, motion, pressure-control, or Model changes beyond the existing camera/refuel release-candidate line.

### Validation

- Recommended before tagging:
  `.\env\Scripts\python.exe -m pytest -q`
- Metadata/static checks:
  `git diff --check`
  `Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }`

### Rollback

- Recommended rollback version: `v1.1.16`.

## v1.1.16 - 2026-07-07

### Changed

- Added automatic offline rollback discovery to `Check Rollback` when online release-tag fetch fails.
- Scans removable-drive `LabCraftUpdates/*.json` manifests and uses a valid release-aware rollback bundle when available.
- Kept manual `Offline Restore` manifest selection available as the explicit support-guided override path.
- Skipped advertising the metadata-incomplete `v1.1.15` test tag and used `v1.1.14` as the previous valid stable release.
- No firmware, device protocol, motion, pressure-control, Model behavior, or update apply behavior changes.

### Validation

- Focused updater and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.14`.

## v1.1.14 - 2026-07-07

### Changed

- Added a metadata-only smoke-test release for validating release-aware offline update bundles from `v1.1.13`.
- Updated stable release metadata so machines on `v1.1.13` can install `v1.1.14` from a support-provided offline bundle.
- No app logic, updater logic, UI behavior, rollback behavior, offline bundle, firmware, device protocol, motion, pressure-control, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.13`.

## v1.1.13 - 2026-07-07

### Changed

- Added a metadata-only smoke-test release for validating the app-based updater window path from `v1.1.12`.
- Updated stable release metadata so machines on `v1.1.12` can install `v1.1.13` through the UI.
- No app logic, updater logic, UI behavior, rollback behavior, offline bundle, firmware, device protocol, motion, pressure-control, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.12`.

## v1.1.12 - 2026-07-07

### Fixed

- Overrode `QT_QPA_PLATFORM=xcb` with `wayland;xcb` for the standalone updater window when `WAYLAND_DISPLAY` is present.
- Kept missing-platform Wayland preference from `v1.1.10` and preserved explicit non-`xcb` Qt platform choices.
- Continued sanitizing OpenCV/cv2 Qt plugin paths before launching the updater window.
- No update targeting, rollback, offline bundle, firmware, device protocol, motion, pressure-control, UI behavior, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.11`.

## v1.1.11 - 2026-07-07

### Changed

- Added a metadata-only smoke-test release for validating the app-based updater window path from `v1.1.10`.
- Updated stable release metadata so machines on `v1.1.10` can install `v1.1.11` through the UI.
- No app logic, updater logic, UI behavior, rollback behavior, offline bundle, firmware, device protocol, motion, pressure-control, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.10`.

## v1.1.10 - 2026-07-07

### Fixed

- Preferred Wayland for the standalone updater window when `WAYLAND_DISPLAY` is present.
- Set `QT_QPA_PLATFORM=wayland;xcb` only when no explicit Qt platform is already configured.
- Preserved explicit Qt platform choices and continued sanitizing OpenCV/cv2 Qt plugin paths.
- No update targeting, rollback, offline bundle, firmware, device protocol, motion, pressure-control, UI behavior, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.9`.

## v1.1.9 - 2026-07-07

### Changed

- Added a metadata-only smoke-test release for validating the app-based updater window path from `v1.1.8`.
- Updated stable release metadata so machines on `v1.1.8` can install `v1.1.9` through the UI.
- No app logic, updater logic, UI behavior, rollback behavior, offline bundle, firmware, device protocol, motion, pressure-control, or Model changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.8`.

## v1.1.8 - 2026-07-07

### Fixed

- Sanitized Qt plugin and font environment variables before launching the standalone updater window.
- Prevented OpenCV/cv2 Qt plugin paths from being inherited by the PySide6 updater process.
- Kept Pi display and desktop session variables available for the updater window.
- Added defensive Qt environment cleanup inside the updater backend before importing the GUI window.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused updater launcher and updater window tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py tests/test_update_window.py`

### Rollback

- Recommended rollback version: `v1.1.7`.

## v1.1.7 - 2026-07-06

### Changed

- Highlighted the `Update App` button when an update check finds an actionable app update.
- Highlighted the `Restore Previous` button when a rollback check finds an actionable rollback target.
- Cleared stale update and rollback action highlights when checks start, fail, or become non-actionable.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused app-update UI and updater tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py`

### Rollback

- Recommended rollback version: `v1.1.6`.

## v1.1.6 - 2026-07-06

### Fixed

- Fixed updater window launches on Raspberry Pi checkouts where `env/bin/python` symlinks to the system Python.
- Preserved the virtual-environment Python path instead of resolving it to `/usr/bin/python`.
- Added a PySide6 import probe before closing the main app for update or rollback.
- Added Python probe diagnostics to `local/update_logs/app_update_launcher_*.log`.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused updater launcher tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py`

### Rollback

- Recommended rollback version: `v1.1.5`.

## v1.1.5 - 2026-07-06

### Changed

- Reorganized the Firmware tab into a two-column maintenance layout.
- Grouped firmware update, application update, service, log, and MCU task usage controls.
- Replaced the tall vertical stack of application update and rollback buttons with a compact button grid.
- Removed the unused speed and acceleration controls from the Firmware tab.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused Firmware tab and updater tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_qualification_readonly_window.py tests/test_regulator_calibration_window.py`
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py`

### Rollback

- Recommended rollback version: `v1.1.4`.

## v1.1.4 - 2026-07-06

### Added

- Added launcher diagnostics in `local/update_logs/app_update_launcher_*.log` before the standalone updater starts.
- Added immediate-exit detection for updater and rollback subprocess launches.

### Changed

- Application update and rollback launches now prefer the active virtual environment or repo-local Python environment.
- Application update and rollback launches now use a detached subprocess so the updater can continue after the main app closes.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused updater launcher tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py`

### Rollback

- Recommended rollback version: `v1.1.3`.

## v1.2.0-rc.4 - 2026-07-06

### Added

- Added release metadata for the `v1.2.0-rc.4` release candidate.
- Included the `v1.1.3` release-candidate update toggle in the v1.2.0 release-candidate line.
- Added support-guided UI access for installing the current release candidate from `releases/latest.json`.

### Changed

- Set the app `VERSION` to `v1.2.0-rc.4`.
- Kept `v1.1.3` as the latest stable release while advertising `v1.2.0-rc.4` as the current release candidate.
- Set the recommended rollback version for this release candidate to `v1.1.3`.

### Validation

- Focused release-channel updater tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py`

### Rollback

- Recommended rollback version: `v1.1.3`.

## v1.2.0-rc.3 - 2026-07-06

### Added

- Added release metadata for the `v1.2.0-rc.3` release candidate.
- Integrated the camera/refuel release candidate line with release-aware online/offline updates and controlled rollback support.
- Added droplet camera capture coordination, capture diagnostics, manual refuel checking, and dual-stream detection improvements from the v1.2.0 release-candidate line.

### Changed

- Set the app `VERSION` to `v1.2.0-rc.3`.
- Advertised `v1.2.0-rc.3` as the current release candidate in `releases/latest.json` while leaving stable at `v1.1.2`.
- Recorded that this release candidate uses the bundled firmware artifact from the v1.2.0 release-candidate line.

### Validation

- Full Python suite passed before the metadata-only RC3 bump:
  `.\env\Scripts\python.exe -m pytest -q`
- Focused release updater validation:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_create_update_bundle.py tests/test_app_update_request.py`

### Rollback

- Recommended rollback version: `v1.1.2`.

## v1.1.3 - 2026-07-06

### Added

- Added a default-off `Include release candidates` checkbox in the Application Update area.
- Added release-channel resolution so support-guided online update checks can target `release_candidate` from `releases/latest.json`.
- Added release-candidate warnings to update details and confirmation messaging.

### Changed

- Normal online app updates still target the latest stable release tag by default.
- Update apply behavior remains pinned to the confirmed release tag.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Focused release-channel updater tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py`

### Rollback

- Recommended rollback version: `v1.1.2`.



## v1.1.2 - 2026-07-06

### Added

- Added repo-tracked application release metadata.
- Added release manifests for `v1.1.0`, `v1.1.1`, and `v1.1.2`.
- Added a stable release index for future version-aware updater work.
- Added installed app version display in the Application Update area.
- Added release-aware online update checks using the stable release named by upstream `releases/latest.json`.
- Added release-aware online update apply behavior using `git merge --ff-only <release-tag>`.
- Added release-aware offline bundle creation with `tools/create_update_bundle.py --release <version>`.
- Added release details to offline bundle manifests and offline update checks.
- Added an explicit `Install Offline Bundle` action for selecting support-provided update manifests.
- Added release details to update confirmation and startup result messages.
- Added support-only release rollback using verified release metadata and `git reset --hard` after dirty-worktree checks.
- Added rollback-specific updater window and startup result messaging.
- Added controlled rollback UI actions for checking/restoring the configured rollback target and support-provided offline rollback bundles.

### Changed

- Online app updates now target named stable release tags instead of arbitrary upstream branch head.
- The app passes the confirmed target release to the standalone updater process.
- Offline Git bundle updates can now target named release tags while preserving compatibility with existing branch/commit manifests.
- Operators can intentionally validate and install an offline bundle without waiting for the online check to fail.
- Rollback remains constrained to release metadata or support-provided offline bundles; arbitrary tag selection is not exposed.
- No firmware, device protocol, motion, or pressure-control changes.

### Validation

- Static metadata validation.
- Focused updater-related tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_create_update_bundle.py tests/test_app_update_request.py`
- Focused release-aware updater tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py`
- Focused release-aware offline bundle tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_create_update_bundle.py tests/test_update_and_restart.py tests/test_app_update_request.py`
- Focused explicit offline install tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py tests/test_update_and_restart.py`
- Focused support rollback tests:
  `.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_update_window.py tests/test_app_update_request.py`

### Rollback

- Recommended rollback version: `v1.1.1`.

## v1.1.1 - 2026-07-05

### Added

- Added a passive UI freeze watchdog and bounded droplet image shutdown handling.
- Added a second-stage prompt for force-closing the droplet imager after timeout failures.
- Updated the stream calibration validation set to include density measurements.

### Fixed

- Fixed stalled droplet capture stop/close handling in the imager sequence.

### Validation

- Release validation recorded outside this metadata slice.

### Rollback

- Recommended rollback version: `v1.1.0`.

## v1.1.0 - 2026-07-05

### Added

- Marked the deployed `stable` branch head as the stable baseline release.
- Included existing branch-head online app update support.
- Included existing offline Git bundle update support.

### Validation

- Release validation recorded outside this metadata slice.

### Rollback

- No earlier rollback version is defined for this release metadata set.
