# Changelog

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
