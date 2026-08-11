# Milestone 8 Slice 7 Completion Record

Status: complete (2026-08-07)

## Outcome

Manual Raspberry Pi suite integration is qualified. The authorized target was
`labcraft@192.168.0.33`; no other host was accessed. The qualification target
and local branch were clean at executable-source commit
`a7fd7b5a844fb88ce1c2fd2fdbe98bfe783beeb8`. The Pi execution-input tree had
SHA-256 `fb2875ac4039fc83e1d7049da3d221c3a6534bb28145a138a1ffb94b343789d1`
across 888 files.

The final preflight and traced proof passed on Raspberry Pi 5, Linux `aarch64`,
Qt/PySide 6.7.1, and the offscreen Qt platform. The proof recorded:

- Bubblewrap `bubblewrap_private_dev_v1`;
- private `/dev`, read-only root, and unshared network;
- zero UART/serial, GPIO, camera/video, I2C, or USB/DFU access matches;
- proof SHA-256
  `04bd01c4a0d7e77f7a36e9709a493ee576eb00983788f95be39a5c3e8d39cfa7`;
- trace SHA-256
  `ff00486d407e0653dd0b07b353dd7caa91686682885e9146b6a96858c8502059`.

The operator-invoked `pi_primary` suite and the exact replay retained in its
first aggregate both passed. Each aggregate contains one fresh child with:

- `offscreen_pi_sil` run mode;
- 96 expected and 96 observed stock/well completions;
- all ten required assertions passing;
- 215 accepted, queued, sent, executing, and completed simulator commands;
- a drained queue and zero unexpected starvation events;
- no unexpected dialogs or recorded workflow errors;
- a completed execution plan, no pending checkpoint intents, and clean
  authoritative persistence;
- successful application/session teardown with no remaining session lock.

The original aggregate parent/child PIDs were 2/3 inside the sandbox namespace;
the replay parent/child PIDs were 3/4. Both therefore prove fresh child-process
execution. Their report durations were approximately 20.51 and 20.07 seconds.
The retained completion screenshots were inspected and show the prominent
`SIMULATION — NO HARDWARE CONNECTED` banner, simulated connection, empty queue,
and 96/96 highlighted wells.

## Final evidence

Original aggregate:

`verification_reports/virtual_workflows/pi-sil/pi_primary/20260808T012615083809Z_9fd8f0e7-d0c/aggregate.json`

- SHA-256:
  `25ec6c8389564041531e354892dbbb165db87bf453f189b4b0a70ffc995f5060`
- child report SHA-256:
  `47a4c96350b21fc0f9fbf8e1c0c1ebcfe4d3de98ba25e1095b691aae763668eb`

Exact replay aggregate:

`verification_reports/virtual_workflows/pi-sil/pi_primary/20260808T012637538300Z_b70fd4a4-d66/aggregate.json`

- SHA-256:
  `16799d1e19973d6a23e3b30ba4c81f500cb118993e81b663f3204f5dd5cd486b`
- child report SHA-256:
  `fb2f37fdf88d81f4e5912a8ad92d8a437b1c58be8b7160de01e4a6c7b70ccf3e`

Validated bundle:

`verification_reports/virtual_workflows/pi-pulls/pi-suite-20260808T012543Z.zip`

- SHA-256:
  `ecb9fccc83017583eb2660f93db6fb89ffa2794aac864080505e4190d3927e09`

Remote evidence remains beneath:

`/home/labcraft/LabCraft_printer/verification_reports/virtual_workflows/pi-sil`

No cleanup was invoked.

## Focused corrections during qualification

The fail-closed gates found two orchestration defects before final success:

1. The traced composed proof audit used the Windows fallback run-mode label on
   native Linux ARM. Commit `c926f2db8b6257298a0c30df930a67f37e80dab0`
   aligned composed classification with the existing native Pi rule.
2. Aggregate child and replay commands resolved the repository virtualenv
   symlink to `/usr/bin/python3.11`, bypassing PySide6. Commit
   `a7fd7b5a844fb88ce1c2fd2fdbe98bfe783beeb8` preserves the absolute
   virtualenv entry-point path while retaining all ordinary path-containment
   resolution.

The failed proof and process-start evidence roots were retained for diagnosis.
Neither defect changed View, Controller, Model, simulator, fixture, manifest,
report schema, protocol, firmware, Pi configuration, or hardware behavior.

## Validation performed

Proof-classification correction:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_pi_virtual_workflow_lane.py
```

Result: 13 passed and 13 passed.

Virtualenv correction:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_suite_runner.py `
  tests\test_virtual_workflow_selection.py `
  tests\test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_pi_virtual_workflow_lane.py `
  tests\system\test_virtual_workflow_suite_execution.py
```

Result: 71 passed and 14 passed. Python compilation, `git diff --check`, remote
`bash -n`, clean-checkout verification, venv PySide6 import, wrapper bundle
validation, aggregate loading, report-hash inspection, and completion screenshot
inspection also passed.

The complete pytest suite remains intentionally deferred to Milestone 8 Slice
8. `pi_stress` was not run. No firmware, protocol, production-hardware, motion,
pressure, or physical droplet behavior was exercised or claimed.

## Risks and rollback

Pi suite execution remains operator-initiated and restricted to named suites.
Capability selection cannot indirectly launch stress. Exact replay remains
strictly allowlisted and evidence-bound, while remote artifacts remain retained
until a separate cleanup operation is explicitly reviewed and approved.

Rollback reverts commits `a7fd7b5a` and `c926f2db` after first preserving the
retained evidence. No data migration, Pi reconfiguration, firmware rollback,
or physical-hardware action is required.
