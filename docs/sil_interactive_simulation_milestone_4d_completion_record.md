# Milestone 4D Completion Record

Milestone 4D is complete on the intentionally uncommitted worktree based on
`525bf9f713e45c8d3de348d8850dd9b658911ac6`.

## Delivered behavior

- deterministic simulation-only pulse response: 1300–1800 us maps to 9–18 nL
  droplet volume and 2500–10000 us maps to 60–250 nL stream volume;
- normal settings preflight and configured-profile application through
  Controller and the simulated command queue;
- schema-v3 request/result evidence while v1/v2 artifacts remain readable and
  fingerprint-stable;
- fingerprint-deduplicated `pending_apply`, `generated_unapplied`, and
  `applied_history` rows in the real calibration dialog;
- strict canonical request/result-pair rehydration without treating generated
  evidence as authoritative applied state;
- retained schema-v3 result reuse with exact identity, idle-array, and
  empty-queue validation;
- promotion of a retained generated row to applied history without creating a
  duplicate.

Production calibration, Controller protocol, firmware, hardware factories,
physical cameras, experiment schemas, and SimMachine behavior were unchanged.

## Automated evidence

The final correction-focused command passed 83 tests with 20 existing Qt chart
deprecation warnings in 42.39 seconds:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_calibration_ui.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_droplet_imaging_summary_table.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py
```

Python compilation and `git diff --check` passed. The full pytest suite was not
run because the approved Milestone 4D gate intentionally uses only directly
affected tests.

## Visible Windows and retained-root evidence

Retained root:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260806T013313958941Z-b16f1e22f56d
```

The fresh application session generated three distinct canonical artifact
pairs:

| Profile | Result fingerprint | Pulse width | Effective volume | Initial state |
|---|---|---:|---:|---|
| `nominal_droplet` | `014612374be4f27fc7b39709e4a5292015b01e9eab653a3139746f325f50572d` | 1800 us | 18 nL | generated, unapplied |
| `droplet_to_stream` | `cffd506d2a3557ab58feb7bfe0fb7d5401e748b64079583237e0f5186d401226` | 2500 us | 60 nL | applied |
| `stream_to_droplet` | `ec98d924cb308069f0334afa2770b83c9e38ffc9dbe5ccde5af6339094a95c68` | 1300 us | 9 nL | applied |

All request/result files deserialize, reproduce their fingerprints, and are
byte-identical to canonical serialization. Fresh snapshot `snapshot-000071`
at event 1359 reported reconciliation `ok`, zero mismatches, two applied
records, one Passed five-droplet manual-refuel check, plan revision 4, and an
empty command queue. Disconnect, recorder closure, and cleanup completed with
no launcher error or retained-session failure.

The retained-root application session loaded the same experiment and three
rows without generating another result. It applied the saved 18 nL nominal
droplet fingerprint directly. `execution_calibrations.json` then contained
exactly three records, while the artifact result count remained three. The
execution plan advanced to revision 5 with final reagent mode `droplet`, final
effective volume 18 nL, and calibration record
`7499165d-1fa6-570e-b20f-64486a5c90a6`.

Reload snapshot `snapshot-000048` at event 963 reported reconciliation `ok`,
zero mismatches, three applied records, one retained refuel check, revision 5,
and an empty queue. The staged head and stock matched the expected head and
`reagent-1_27.78_mM`; the head was in droplet mode. The second application
session, recorder, disconnect, and cleanup all completed normally.

The launcher emitted existing nonfatal `Slot-1`/`Slot-2` location lookup
messages while reconstructing rack interactions. Snapshot evidence confirms
the correct head was staged and reconciled, and the messages did not alter the
calibration, movement-command completion, or teardown gates.

## Limitations and next action

The response remains a deterministic, non-empirical simulation model. Pressure
is retained as provenance but does not affect volume, and no physical droplet,
stream, camera, balance, firmware, protocol, or hardware behavior is proven.

Milestone 4D is closed. The next action is to create and review the concrete
Milestone 5 manual full-lifecycle characterization plan before beginning
automated workflow migration.
