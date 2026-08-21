# Changelog

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
