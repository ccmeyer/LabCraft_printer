# Calibration Recording Store Migration: Milestone 5 Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 5 adds an explicit, offline historical calibration conversion path.
The converter accepts exactly one experiment directory, defaults to dry-run,
and supports explicit apply, resume, and validation modes. Conversion is
additive: existing `calibration.json` and recording files are hashed and left
byte-identical, while deterministic canonical run bundles, index events, and a
commit-gated migration manifest are created alongside them.

The reader exposes generated results only after a completed migration manifest
and its referenced source and bundle hashes validate. Generated results retain
legacy source coordinates, reconcile as matching dual records, and participate
in the existing history, selection, application, and export paths. The
`LABCRAFT_CALIBRATION_MIGRATED_RESULTS=0` rollback flag hides generated results
without deleting any files.

Ambiguous or unsupported history is reported and skipped. Existing canonical
records are recognized rather than duplicated. Repeated conversion is
idempotent, interrupted conversion can resume, and conflicts fail closed.
Normal application startup never invokes conversion or repairs an index.

The implementation changes the offline conversion, canonical store/reader,
export, SIL fixture/journey, registry/manifest, Pi orchestration contract,
tests, and documentation. It does not change firmware, device protocols,
camera or image analysis, motion, pressure, dispense, serial, GPIO, or any
historical file under `FreeRTOS-interface/Experiments/`.

## Fixture and SIL contract

The reviewed fixture
`tools/virtual_workflows/fixtures/calibration_history_conversion_contract_v1.json`
contains 12 synthetic source steps. The frozen expected inventory is 9
conversions, 1 already-canonical step, 2 intentionally skipped steps, and 0
conflicts. Its SHA-256 is
`bfe4614e32dcca3c11b2d4bfe9a7e42b7336334d1cbb0c935efde0afa6c0b095`.

The registered
`calibration_storage_historical_conversion_contract_v1` journey performs a
fresh real MVC reload, reads and resolves migrated history, applies one exact
selection through the existing settings path, exports the result, repeats the
conversion to prove idempotence, and verifies source immutability. It emits
flushed progress records for MVC launch, inventory, planning, bundle/index
work, validation, reload, application, and export.

This offline-only milestone deliberately replaces the inherited 8-head x
25-run writer workload with one compact conversion-contract run. The prior
200-process storage workload was not run. The Pi wrapper's independent
96-well hardware-safety audit still ran as required by the existing Pi SIL
containment contract.

## Host validation

```text
Focused conversion/store/reader/CLI/fixture tests: 90 passed in 9.89s
Historical-conversion lifecycle SIL: 1 passed in 3.44s
Manifest and scenario coverage tests: 96 passed
Report-set regression and Pi orchestration-contract tests: 47 passed
Full Python suite: 4794 passed, 146 skipped, 533 warnings in 242.29s
```

The full suite used an external temporary base directory because the SIL root
containment checks correctly reject a repository-local pytest temporary tree.
No stress-selection flag was supplied, and no 200-process workload was
executed.

## Pi qualification

The qualified command was:

```powershell
.\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519 `
  -Scenario calibration_storage_historical_conversion_contract_v1 `
  -HostLabel pi5-calibration-storage-migration-v1 `
  -WarmupRuns 0 `
  -MeasuredRuns 1 `
  -SpeedMultiplier 1000 `
  -TimeoutSeconds 120
```

The measured run passed at implementation commit
`2a8750a2c2b80340f02a70921bd32a8b19453160` with a clean tracked tree. It took
2,408.532 ms. Planning took 4.625 ms and apply took 50.812 ms. Fresh history
materialization took 4.902 ms, export took 35.138 ms, and the idempotent
reapply took 7.648 ms. The resulting store contained the expected 9 generated
bundles plus the 1 pre-existing canonical result, 10 index events, 6 usable
history rows, 0 reader issues, and an exact `matching_dual` selection.

Source immutability, required export contents, exact counts, and idempotence
all passed. The classification was `pass`; the report set was functionally
`pass`, had no dirty source, no injected stall, and correctly marked
single-sample noise analysis as not applicable.

Qualification environment: Raspberry Pi 5 Model B Rev 1.0, aarch64 Linux
6.12.20+rpt-rpi-2712, NVMe/ext4, CPython 3.11.2, PySide/Qt 6.7.1, offscreen
Bubblewrap with a private device namespace, read-only root, and unshared
network. Hardware access was disabled. Camera, serial, GPIO, MCU, balance, and
firmware-update access were all false, with zero forbidden-access attempts.

Retained evidence:

```text
Measured report SHA-256: b7fc7de21860913a20d9dfbe0b921602e9928e904132b975e70c181cf18929b1
Report-set SHA-256: a5084945c601eec6cf0d47153ed672c4f9ead9699205672122b37d130d36c50d
Hardware-proof SHA-256: f4111ccce4024b62060fcb1ec867523b09b6650cd7056891021f498aa76666b9
Preflight SHA-256: da276847336766e8d421a282849615faeb291c6b4c2f174f1bcb490774e532bd
Retrieved bundle SHA-256: dcd292ac9bf6b1c6fb88d56c81639e13ba7444cb6647dcb0352932f4e18972e2
```

The measured report is retained under
`verification_reports/virtual_workflows/pi-sil/calibration_storage_historical_conversion_contract_v1/20260816T000516748776Z_composed/`.
The classified report set is retained under
`verification_reports/virtual_workflows/pi-sil/calibration_storage_historical_conversion_contract_v1/20260816T000519172975Z_2a8750a2c2b8_report_set/`.
The hardware proof and preflight are retained under
`verification_reports/virtual_workflows/pi-sil/pi-safety-20260816T000438Z/`.

An earlier Pi invocation completed the compact scenario successfully but the
post-run report-set builder incorrectly required a print-responsiveness metric
from this storage scenario. Commit `2a8750a2` classifies the migration scenario
with the storage metric profile and adds regression coverage. The retained
qualification above is the clean rerun after that correction.

## Risks and rollback

Historical shapes that cannot be linked unambiguously remain skipped and must
be reviewed rather than guessed. Conversion requires enough free storage for
additive canonical artifacts. A power loss before the manifest commit may
leave incomplete generated bundles, but they remain invisible to readers and
an explicit resume can finish the same deterministic plan.

Operational rollback sets `LABCRAFT_CALIBRATION_MIGRATED_RESULTS=0` and
restarts the application. This hides generated migration results while
preserving original legacy data and all additive artifacts. A code rollback
uses a revert commit deployed through origin and Pi fast-forward-only
synchronization. No rollback deletes or rewrites historical calibration data.
