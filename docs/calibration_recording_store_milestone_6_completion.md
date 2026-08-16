# Calibration Recording Store Migration: Milestone 6 Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 6 stops routine `calibration.json` creation and rewriting for new
experiments. New designs persist
`labcraft.calibration_storage.policy` v1 with
`legacy_writer_mode: canonical_only`. Historical designs that do not contain
the policy load conservatively as `legacy_compatible`, and design-only
duplicates start as fresh canonical-only designs without copied calibration
history.

The manager owns one centralized compatibility-writer guard. Canonical
structured updates, results, index events, diagnostics, capture retention,
readers, UI selection/application, calibration memory, audit, and export
remain active when the legacy writer is suppressed. The effective writer is
restored by `LABCRAFT_CALIBRATION_LEGACY_WRITER=1`, by the broader
authoritative-store rollback, or while either primary or secondary reader is
explicitly set to legacy. Policy changes are rejected during an active
calibration session.

This milestone changes no firmware, device protocol, camera or image-analysis
algorithm, motion, pressure, dispense, serial, GPIO, or historical experiment
file under `FreeRTOS-interface/Experiments/`.

## Compact SIL contract

The registered `calibration_storage_new_store_only_contract_v1` scenario
reuses the seven reviewed Milestone 1 fixture shapes through the tracked
`catalog_new_store_only_v1.json` catalog. Its SHA-256 is
`f61ca72e8281ae7fa5b404da9e843ba0e1356c636ce8d02a81f9a0d91d7c6e6b`.

One run executes 16 scripted processes, 17 ordered updates, 14 completed
processes, one stopped process, and one failed process. It then exercises
canonical memory, summary, and export consumers; closes and fresh-loads the
real MVC composition; selects and applies an exact canonical row through the
UI; and verifies settings-only simulator commands. The main experiment must
have no `calibration.json` or temporary legacy file. One historical canary
must dual-write without changing its pre-existing hash, and one explicit
rollback canary must dual-write from a canonical-only declared policy.

The scenario prints flushed `SIL_PROGRESS` records for setup, the 16-process
catalog, secondary memory/summary/export, and fresh application. It normally
finishes in roughly 12–15 seconds on the Windows host and Pi. The earlier
200-process/232-update stress workload is intentionally retired from this
milestone.

## Host validation

```text
Storage/reader/conversion compatibility tests: 86 passed in 9.28s
Policy, manifest, selection, and Pi orchestration tests: 166 passed in 21.42s
New-store-only lifecycle SIL: 1 passed in 12.67s
Report comparison tests: 26 passed in 1.29s
Candidate baseline and final focused contracts: 147 passed in 15.81s
Broad Python suite: 4801 passed, 147 skipped, 5 failed in 534.29s
Exact five repaired nodes: 5 passed after the compatibility fixes
```

The broad run exposed four tests whose intentionally minimal managers replaced
`_save_atomic` with the historical zero-argument seam, plus one lifecycle
suite-order expectation. The writer guard retained that zero-argument seam and
the suite expectation was updated. All five exact failing nodes then passed,
and the complete affected-area, manifest, orchestration, lifecycle, and report
comparison selections passed. Per the short-validation plan, the nine-minute
broad suite was not rerun a second time and no stress-selection flag was used.

## Pi qualification

The qualified command was:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_new_store_only_contract_v1 `
  -HostLabel pi5-calibration-storage-new-store-only-v1 `
  -WarmupRuns 0 `
  -MeasuredRuns 1 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 180
```

The measured run passed at clean implementation commit
`d1d2426f4b85001fece1c43b0fdcab52978419d7`. The wrapper, including its
independent 96-well hardware-safety audit, completed in 55.4 seconds. The
measured storage scenario took 13,830.907 ms.

The main experiment committed exactly 16 canonical results and 17 updates,
created no `calibration.json`, performed zero legacy writes, and recorded 50
suppressed legacy-write attempts. Both compatibility canaries passed. Fresh
MVC reload took 972.061 ms, selected a `canonical_only` row, and applied it
using settings-only simulated commands. The last-to-first update median ratio
was 1.068. Peak RSS was 432,209,920 bytes with 42,221,568 bytes growth. The
retained scenario inventory contained 162 files and 1,625,803 bytes.

The single-sample candidate is tracked at
`tests/performance/baselines/calibration_storage_new_store_only_pi5_v1.json`.
It is a regression canary, not a statistically stable distribution.

Qualification environment: Raspberry Pi 5 Model B Rev 1.0, aarch64 Linux
6.12.20+rpt-rpi-2712, NVMe/ext4, CPython 3.11.2, PySide/Qt 6.7.1, offscreen
Bubblewrap with a private device namespace, read-only root, and unshared
network. Hardware access was disabled. Camera, serial, GPIO, MCU, balance, and
firmware-update access were all false.

Retained evidence:

```text
Measured report SHA-256: dae80e46f546de7ff2e4b5da065a1882916e27b0f20389cc715e4c58e26a6bfb
Report-set SHA-256: 170064dfe2448ffb771b85de17b86c577c588b9d3fffc82a8409c6942f7b3ea7
Hardware-proof SHA-256: cbdd3381508eb21b0a006ff2b84fb2d3d103345286899d185de13e35f1347f50
Preflight SHA-256: b98d3ae685685190d849be8fda1a58078446afe562387bbcb38355f64042c6ff
Candidate baseline SHA-256: aa8a80de4ecd9e156cbcff79c462a8e87bfaba2bb433f8b98489464ef27671c9
```

The measured report is retained under
`verification_reports/virtual_workflows/pi-sil/calibration_storage_new_store_only_contract_v1/20260816T010406657677Z_composed/`.
The report set is retained under
`verification_reports/virtual_workflows/pi-sil/calibration_storage_new_store_only_contract_v1/20260816T010420515380Z_d1d2426f4b85_report_set/`.
The hardware proof and preflight are retained under
`verification_reports/virtual_workflows/pi-sil/pi-safety-20260816T010328Z/`.

## Risks and rollback

Historical designs intentionally continue whole-file legacy writes until
their persisted policy is changed by a separately approved workflow. A
canonical-only design opened with a legacy reader also retains the writer to
avoid a mixed compatibility state. The candidate performance limits are based
on one measured run and should be treated as coarse regression alarms.

Operational rollback sets `LABCRAFT_CALIBRATION_LEGACY_WRITER=1` and restarts
the application. The broader `LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE=0`
rollback remains available. A code rollback uses a revert commit deployed
through origin and Pi fast-forward-only synchronization. No rollback deletes
canonical artifacts or rewrites historical calibration data.
