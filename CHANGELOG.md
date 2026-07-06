# Changelog

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
