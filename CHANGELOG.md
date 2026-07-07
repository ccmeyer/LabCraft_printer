# Changelog

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
