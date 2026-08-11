# Milestone 13 Slice 13.2 Completion Record

Status: `complete`

Supersession note: the 64/384 action limits and the catalog, campaign, and case
hashes below are the historical Slice 13.2 legal-only contract. Slice 13.3
qualified seed 47 at 65 recorded actions and therefore versioned the strict
limits to 80/480 before its first complete qualification. See the Slice 13.3
completion record for the current hashes; no normalized sequence hash changed.

Completed: 2026-08-09

## Outcome

Both frozen legal sequences now drive the real Qt editor, printer-head,
calibration, authoritative loader/activation, and Start controls through the
existing Controller/Model/persistence/simulator path and finish at a fresh
read-only terminal reload. The compact literal case contains four reactions,
two durable stock identities, eight stock/well intents, and 44 commanded
droplets. Generated exploration remains supplementary to the reused M10/M11
deterministic oracles.

Seed 13 proves create/configure/randomize/Optimize & Generate/Finalize through
terminal authority. Seed 29 begins with the same prepared authority, changes
the reagent targets from `1/2` to `0.9/1.8` through real prepared-editor
controls, regenerates/refinalizes to a new design/plan/progress lineage, and
then reaches the same literal terminal truth. No UI row position is used as an
identity.

## Frozen compact contract and budget correction

The qualified calibration rows reuse the deterministic 1300 us/9 nL oracle
for distinct `Capacity A` and `Water` head identities. This preserves the
literal prepared/calibrated/terminal counts of 6 Capacity A plus 38 Water
droplets and proves two keyed calibration revisions.

The first full real-Qt run proved that the provisional 48-row action cap was
too small for the required lifecycle: seed 13 needs 56 rows before teardown
and 57 in the report; seed 29 needs 61 before teardown and 62 in the report.
The cap was therefore corrected before the first qualifying pass to the strict
inclusive value 64. The six-sequence cap is 384. No action, assertion, or
operator boundary was removed to fit the budget. The exact workload caps were
also tightened to `4/2/8/44` per sequence and `24/12/48/264` per campaign.

The resulting frozen identities are:

- catalog SHA-256:
  `995d29b97ba051a1184d6633353a74feff6a6d2390b149e25d776f83f989209d`;
- campaign SHA-256:
  `2e9806130983df06764cf4008eb21f6d1ea3954a4525736e185612929e8f1ce0`;
- compact case SHA-256:
  `2de7ddfcd2e53075f215e03e8fab191e4573a00516212648a391be92ab040129`;
- compact design SHA-256:
  `48a35b0b3dde09f480becab480c0bd814ce723a5ba1d182831a9dd22977f723e`;
- refinalized compact case SHA-256:
  `3fa9732cb884e45bb370be158817534446e606ca17ff2ee5b4ba9ca65953a7d7`;
- refinalized compact design SHA-256:
  `53eb5d4b71deba808363ed9d0494afc6c2ad5af6e6f303d9e1b1538b0269bb01`.

The state-model, operation-ledger, oracle-ledger, frozen-set, fixture
projection, and six normalized sequence hashes did not change.

## Qualification evidence

Fresh-process direct and exact emitted replay passed for seeds 13 and 29.
Visible direct and exact emitted replay passed for seed 13 at 20x. Every run
recorded exactly three application sessions, eight intent/command identities,
44 commanded droplets, four required screenshots (`prepared`, `fresh_loaded`,
`fresh_activated`, `terminal_reloaded`), terminal plan state `completed`, no
unexpected dialog, exact cleanup, and no retained session lock.

The final-hash report SHA-256 values are:

| Mode | Sequence | Direct report | Exact replay report |
| --- | --- | --- | --- |
| offscreen | seed 13 | `e6cbca198021ab77ee349c9f17af4995022face82588c59a27ab9acdbe50b0a4` | `0b273398e1d3e3338ae0595eeb973f23081c67aadfac071679e5a733971db401` |
| offscreen | seed 29 | `7a5cac1b873d8edeb74ee2e5b76c4ee1beb25510d96c25db679c31ddceaf68eb` | `14d72b697a2f90157e0814042ca0038cdccdbf6407f546bea0dafe47fe2db350` |
| visible | seed 13 | `5f9c35dceafc9a3abc00f6d81edd997787a2cc5ba1941102a41e1c4447f20a58` | `3e2ce39bf085ecfe3054272efb82ffd2ece6630e1157fd0d818c32f019ac0545` |

Evidence is retained under
`verification_reports/milestone_13_slice_2/qualified_direct/` and
`verification_reports/milestone_13_slice_2/visible/`. The qualified direct
root contains 40 files/5,804,850 bytes; the visible root contains 20
files/2,609,018 bytes. Each individual run remains below 256 files/48 MiB.

## Automated validation

Passed commands included:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle --basetemp verification_reports\pytest_tmp\m13_slice2_system_final tests\system\test_virtual_workflow_m13_exploration_execution.py
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle --basetemp verification_reports\pytest_tmp\m13_slice2_m11_compat tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py -k registered
.\env\Scripts\python.exe -m pytest -q --basetemp verification_reports\pytest_tmp\m13_slice2_focus tests\test_virtual_workflow_exploration_m13.py tests\test_virtual_workflow_m13_interaction_cases.py tests\test_virtual_workflow_assertions.py tests\test_virtual_workflow_contract_freeze.py tests\system\test_virtual_workflow_m13_exploration_execution.py tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py
git diff --check
```

Results: 2 M13 lifecycle tests passed, the selected registered M11 lifecycle
compatibility test passed, and the default-marker focused selection reported
55 passed/4 expected skips. Direct/replay/visible commands and exact report
paths are retained in their reports. `git diff --check` passed with only
Windows line-ending notices. Analysis-pipeline tests were not run because that
code did not change.

## Files changed

- `tools/virtual_workflows/m13_interaction_cases.py`
- narrow reusable screenshot-control additions in `actions.py`,
  `page_drivers.py`, and `journey_phases.py`
- M13 assertions, journey dispatch/reporting, and CLI execution gate in
  `assertions.py`, `journeys.py`, and `tools/run_virtual_workflow.py`
- `tests/test_virtual_workflow_m13_interaction_cases.py`
- `tests/system/test_virtual_workflow_m13_exploration_execution.py`
- Milestone 13 execution, master, implementation, and completion records

No production MVC, simulator, firmware, protocol, physical calibration,
motion, pressure, refill, or hardware file changed. Milestone 8 and the frozen
Milestone 9-12/11A scenarios remain intact.

## Risks and rollback

The new legal body deliberately composes mature M10/M11 helpers; a future
helper change could expand the ledger beyond 64 or alter screenshot names.
Frozen hash, action-cap, exact screenshot, literal count, and system tests fail
closed in that case. The application-session count is observed as three even
though the normalized plan models one explicit rotation; the third session is
the mandatory terminal read-only reload and is retained as authoritative
evidence.

Rollback removes the compact case, legal M13 assertion/journey/CLI branches,
focused tests, and Slice 13.2 records, restores the execution-disabled Slice
13.1 boundary, and leaves all deterministic Milestone 8-12/11A contracts and
user experiment data untouched.
