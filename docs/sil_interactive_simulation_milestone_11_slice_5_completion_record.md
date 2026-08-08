# Milestone 11 Slice 11.5 Completion Record

Status: complete (2026-08-08)

## Outcome

Milestone 11 is complete. The source-current joined randomized-design,
calibration, clean-session reload, three-stock execution, and terminal-reload
scenario passes retained offscreen and visible Windows qualification plus each
exact emitted replay. The expanded nine-child lifecycle suite and 96-well host
regression suite also pass with exact aggregate replays. Focused Milestone 11,
Milestone 9/10 compatibility, and the complete default Python suite pass.

All accepted reports identify entrance commit
`a385b1bfa699893a5fc4c6d50207d783957aa200`, Git tree
`6638b8e7c6b898a9703e1e31769055dbe7a3e7e2`, and execution-input source-tree
SHA-256
`9d4214e4e97dbec54f71db93607fe2e1f65121306caeb0eb953d587d1252ca79`
over 898 files. Reports record `dirty_worktree: true` only because the required
Slice 11.5 implementation plan was the sole untracked file. Documentation and
ignored retained reports are excluded from the execution-input fingerprint;
no execution source changed after qualification began.

Slice 11.5 changes documentation only. No production MVC, firmware, protocol,
physical-machine, persisted application-data format, fixture, manifest,
report/aggregate schema, release metadata, Milestone 12 safeguard, or
refill/resume behavior changed during closeout. No Pi, host-stress, analysis-
pipeline, firmware, protocol, HIL, or physical-hardware path ran.

## Frozen joined contracts

- scenario/registry ID: `randomized_calibration_reload_execution_v1`;
- scenario name/version:
  `randomized_calibration_reload_execution` / `1`;
- capability: `execution.randomized_calibration_reload_execution`;
- joined case SHA-256:
  `3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd`;
- tracked fixture SHA-256:
  `bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118`;
- literal count-oracle SHA-256:
  `468d78216fd52f326898c5b5625f6ae591995c642118a72ddb1cdf0cb5790814`;
- capability-manifest SHA-256:
  `7856a944617ee3330cff29b47c143957f60ae6f8c795bcd7486a9cfd2128d08c`;
- selected Milestone 10 case: `multi_reagent_seed_4321`, case SHA-256
  `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51`;
- experiment-design catalog SHA-256:
  `acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f`;
- planned design catalog SHA-256:
  `15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd`;
- seed-4321 assignment SHA-256:
  `e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef`;
- reaction-multiset SHA-256:
  `b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696`;
- preserved Milestone 9 requantization catalog SHA-256:
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`;
- preserved mixed-mode catalog SHA-256:
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.

The fixed randomization seed is `4321`. The literal reaction mapping is:

| Well | Reaction |
| --- | --- |
| A1 | R8 |
| A2 | R6 |
| A3 | R3 |
| A4 | R2 |
| A5 | R7 |
| A6 | R4 |
| A7 | R1 |
| A8 | R5 |

All expected values remain case-owned literals. The Milestone 9 count oracle
normalizes observations only; it does not calculate expected values. Every
assertion and evidence reconciliation uses `(stock_id, well_id)`, never list,
row, or iteration position.

## Literal counts and identity joins

Counts below are ordered A1 through A8:

| Stock | Prepared counts | Final calibrated counts | Head / calibration |
| --- | --- | --- | --- |
| Design A | `2,1,2,1,2,2,1,1` | `1,1,1,1,1,1,1,1` | `virtual-head-m11-design-a-v1`; 1800 us; 18 nL |
| Design B | `3,3,1,3,1,3,1,1` | `3,3,1,3,1,3,1,1` | `virtual-head-m11-design-b-v1`; 1400 us; 10.8 nL |
| Water | `6,7,8,7,8,6,9,9` | `6,6,8,6,8,6,8,8` | `virtual-head-m11-water-v1`; 1300 us; 9 nL |

Design A is the only stock receiving the Milestone 9 boundary-crossing
calibration and maps to exactly one execution stock. Design B is the exact
unchanged stock/count oracle. Water and Design B receive only their qualified
remaining-stock calibration after the clean rotation. The reports join each
stock by ID to one printer head, calibration record, plan stock, plan revision,
and progress reference.

The real Qt editor creates authoritative prepared revision 1. Design A Apply
produces active revision 3 with zero progress. The first application closes
cleanly; the second application has a different application-session ID,
reconstructs from authoritative files, and activates explicitly with zero
first-session dispatch. Water and Design B calibration produce revisions 4
and 5 without progress. ID-keyed Design A, Design B, and Water passes reach
exact cumulative boundaries 8/16/24 with active/active/completed states.

Terminal reconciliation proves 24 unique intent begins, 24 unique command
attachments and sequence identities, 24 completed non-manual simulator
DISPENSE commands, 24 unique durable completions, and 80 droplets. There is no
discard, overflow, starvation, unexpected dialog, or workflow error. Revision
6 is `completed` and `analysis_only`. A third distinct application session
loads it read-only without activation or dispatch, and plan targets, progress
targets, progress added, commands, and completions equal the final literal map
exactly once.

## Direct retained qualification

All direct evidence is retained beneath `verification_reports/m11-s5/`.

| Qualification | Run | Report SHA-256 | Evidence-manifest SHA-256 |
| --- | --- | --- | --- |
| offscreen | `offscreen/randomized_calibration_reload_execution_v1/20260808T232940080044Z_composed` | `d4d74d3d16161f6d46a7880cc857ec03692e0c8f8ec11d5101da23990d6f539e` | `e023e0d3a9fe88373af6c4304157fc1419bcabd363c23d602d94ad7e719b1587` |
| offscreen exact replay | `offscreen/randomized_calibration_reload_execution_v1/20260808T232957767292Z_composed` | `04604f8ba4b6f9964887b13e2ed19f2fee85b37cdac10ce7b5a151dcf903bfe6` | `3f45077fdc987adad06effc75a1ddbf6f0a4a68d1ad0bd2f0b0c8845e351aba0` |
| visible Windows | `visible/randomized_calibration_reload_execution_v1/20260808T233916267504Z_composed` | `99d407fca54bb279530f24debd68d4c482937717007ff56cb424b0f1f7d2e16f` | `7660cf030b73b39399f66dae47b02d8b892eb38e46a826679bb24bb24e34d653` |
| visible exact replay | `visible/randomized_calibration_reload_execution_v1/20260808T233943911181Z_composed` | `35b20a04f21ea6fe48abc4cc4b05e64b552bba521af9e0f38cd000c31e46509f` | `3d7f6529590ec51cfde214a4c2df3fce7c23a9532fedb57277b11eec5068845d` |

All four reports pass with 80 actions against the cap of 96, 14 required
assertions passing, 24 intents, 80 droplets, three application sessions, zero
queue starvation/overflow, and passing teardown. The exact direct replay
commands retained by the reports are:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root C:\Users\conar\source\LabCraft_printer\verification_reports\m11-s5\offscreen `
  --seed 1 --speed-multiplier 1000.0 --timeout-seconds 180.0

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root C:\Users\conar\source\LabCraft_printer\verification_reports\m11-s5\visible `
  --seed 1 --speed-multiplier 20.0 --timeout-seconds 240.0 --visible
```

## Suite and replay qualification

| Qualification | Result | Aggregate | SHA-256 |
| --- | --- | --- | --- |
| lifecycle | 9/9 pass | `verification_reports/m11-s5/suites/lifecycle/20260808T234051196464Z_0f7677f5-a03/aggregate.json` | `33f9406576df7322faf47657aac6ef616cb90ecd707e07a13e9c389f8829f0ef` |
| lifecycle exact replay | 9/9 pass | `verification_reports/m11-s5/suites/lifecycle/20260808T234208730863Z_07c8034e-e3e/aggregate.json` | `8f29a1e180c9ae91bf61dbe7cf6a8b1e2f593bcf7d70b9c37f79525ad717c5c4` |
| host regression | 1/1 pass; 96 wells | `verification_reports/m11-s5/suites/host_regression/20260808T234326582006Z_8340d197-c2d/aggregate.json` | `558a1f0b3823771313cbe23d8d3c5326b1792f925b9dd007c4a57f099d370abe` |
| host-regression exact replay | 1/1 pass; 96 wells | `verification_reports/m11-s5/suites/host_regression/20260808T234347149076Z_92d5c0ce-506/aggregate.json` | `5a970ed427cc31ed6c3e4d95f6e4b100fc724300ad65610d6de69cc728715d8a` |

Both lifecycle selection plans have SHA-256
`c8fb7a542badd9ffbeb6a301d0d17005ba00ca113eb9c297844911fd50dd6d74`.
Both host-regression selection plans have SHA-256
`18cdd0e6ce33da8dd6d3c5ae1f394f1c3eee18121587f39d3a1edc414720d8c0`.
Every child used a fresh process, returned zero, avoided timeout/termination,
and produced exactly one matching passing report whose hash agrees with its
aggregate. Original and replay selectors, manifests, source commit, and source-
tree identity are identical.

Across all 24 retained direct and suite-child reports, classification is
`pass`, source commit and source-tree identity are identical, all 24 evidence
manifests exist, and every teardown records `close_succeeded: true` with no
session lock. A final process audit found no Milestone 11 runner or pytest
child. One unrelated pre-existing Milestone 10 two-stock diagnostic parent/
child pair remains unchanged and was not treated as Milestone 11 state.

The exact aggregate replay commands were:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\m11-s5\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_regression --output-root verification_reports\m11-s5\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen
```

## Visible screenshot audit

All eleven visible original screenshots were manually inspected. Main-window
frames show `SIMULATION — NO HARDWARE CONNECTED`; editor frames show the
read-only saved design, seed 4321, eight selected wells, and exact calibrated
values. Fresh loaded and fresh activated are distinct. Terminal reload visibly
shows execution locked, hardware loading unavailable, completed plan state,
Design A 18 nL, Design B 10.8 nL, and Water 9 nL.

| Screenshot | SHA-256 |
| --- | --- |
| `design_generated.png` | `269fbb658b4bfaf935d61968afeeef3d6dcaf406386630355699d10972f9ac2f` |
| `prepared_randomized.png` | `269fbb658b4bfaf935d61968afeeef3d6dcaf406386630355699d10972f9ac2f` |
| `calibrated_zero_progress.png` | `77625b2db4a11f1382e4f47adda3c9e7ed66fa6a4887d3715d5a5ee44bf0a7c2` |
| `fresh_loaded.png` | `13a9a19f0459bbe91fa68ad61ba10b1b4f61451396c0395743033d4286914989` |
| `fresh_activated.png` | `22410b8ddd5d496057f12a657ce6e6939351b8ce564f05d4af42fd26d66c4b20` |
| `remaining_stocks_calibrated.png` | `a6789cf1b6b2e1241809b592e61ca168ed7ab3dd32116089b1c3905ae95ae0bb` |
| `design_a_pass_complete.png` | `d34817edd10db46bb986afb88d35b811d4c60a478c6114daf1d21c860936a317` |
| `design_b_pass_complete.png` | `f52d7afc4ca70d068614cea3f2ddcc30fc5eb03c618f771aad23e365a0a98f3d` |
| `water_pass_complete.png` | `144608284c2605af535d9b70ac0c4173abce5add7479ddf1105b42b446ca9d2a` |
| `completed.png` | `144608284c2605af535d9b70ac0c4173abce5add7479ddf1105b42b446ca9d2a` |
| `terminal_reloaded.png` | `d628ebd7d9388f63499fc09237885e50553913a8f495b303edda314615241865` |

At 20x, `water_pass_complete` and `completed` capture the main window one Qt
paint behind the durable completion boundary: the visible guide still shows
the final Water command in progress. This is an accepted display-timing
limitation, not an evidence ambiguity: the assertion ledger already records
the exact 24th durable completion and completed revision 6, and the immediately
following fresh `terminal_reloaded` frame visibly reconstructs the completed,
locked, analysis-only bundle. No state or assertion was weakened to accept it.

## Automated validation

Focused unit, contract, driver, assertion, composition, selection, manifest,
report, authoritative-evidence, and direct/registered system tests:

```powershell
.\env\Scripts\python.exe -m pytest -q <focused Milestone 11 files> `
  --run-sil-lifecycle `
  --basetemp C:\Users\conar\AppData\Local\Temp\LabCraft\pytest-m11-s5-focused-20260808a
```

Result: `278 passed`, with 90 existing Qt deprecation warnings.

Explicit Milestone 9/10 catalog, case, joined-source, and contract-freeze
compatibility checks:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_joined_interaction_cases.py `
  tests\test_virtual_workflow_contract_freeze.py `
  --basetemp C:\Users\conar\AppData\Local\Temp\LabCraft\pytest-m11-s5-compat-20260808a
```

Result: `60 passed`.

The complete default suite ran exactly once with a fresh external root:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp C:\Users\conar\AppData\Local\Temp\LabCraft\pytest-m11-s5-full-20260808a
```

Result: `4192 passed, 90 skipped, 389 warnings in 254.14s (0:04:14)`.
Warnings are existing Qt deprecations. The opt-in analysis pipeline was not
enabled, and the complete suite was not rerun. `git diff --check` passed.

## Slice and commit record

- planning: `2f3b654` (`docs: plan milestone 11 slices`);
- Slice 11.1 contract: `f81d4d5`;
- Slice 11.2 calibrated zero-progress checkpoint: `67c01ff`;
- Slice 11.3 clean authoritative session rotation: `25deb6a`;
- Slice 11.4 complete registered execution journey: `a385b1b`;
- Slice 11.5: this documentation-only closeout commit.

Each slice has its own implementation plan, focused validation, completion
record, and independent commit.

## Compatibility, limitations, risk, and rollback

Milestone 11 preserves every Milestone 9/10 catalog, case hash, fixture,
schema, selector, runner family, historical artifact, exact replay grammar,
paused/completed reload contract, and negative no-mutation assertion. The
lifecycle suite changed only by the intentional append of the completed joined
scenario. Report-v1, selection-plan-v1, aggregate-v1, and persisted application
formats remain unchanged.

This application SIL evidence proves real Qt UI, Controller, Model,
authoritative persistence, Machine_FreeRTOS application adapter, and
SimulatedMachine intent semantics. It does not claim firmware, serial protocol,
physical motion, pressure response, calibration accuracy, droplet quality,
camera, balance, collision, timing, or real printer-head behavior. Generated
plan/record/session/command IDs, timestamps, and paths legitimately differ
across replay. The three application compositions share one in-process
QApplication and retained SIL root; direct CLI and suite executions supply
fresh operating-system processes around each complete journey.

Residual risk is future drift between randomized identity, calibration
association, and persistence. The registered scenario now fails closed on that
drift by explicit stock/head/record/plan/progress IDs and keyed counts. Rollback
reverts only the Slice 11.5 documentation commit; Slices 11.1-11.4 and retained
historical evidence remain. No evidence deletion or data migration is needed.

The documented next action is Milestone 12 planning for editor, execution-
preflight, and persistence safeguards. Refill-required/resume remains deferred
while authoritative volume tracking is disabled, and Milestone 13 must wait
until deterministic Milestones 9-12 are stable.
