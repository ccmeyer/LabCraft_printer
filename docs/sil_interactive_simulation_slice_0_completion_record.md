# SIL Interactive Simulation Slice 0 Completion Record

Status: `complete`

Completed: 2026-07-28

Source commit: `c393f5d888b917a42e5f14a45e90e05b166fe78d`

Related documents:

- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_slice_0_implementation_plan.md`
- `docs/sil_verification_framework_hardening_plan.md`

This record is authoritative for Slice 0 status. It records the decisions,
compatibility anchors, characterization, retained evidence, validation, and
findings required by the Slice 0 implementation plan.

## Outcome

Slice 0 completed as an architecture, contract, and evidence freeze. No
production MVC, simulator, virtual-workflow runtime, fixture, report schema,
accepted baseline, Pi, firmware, protocol, or hardware behavior was changed.

The frozen application path is:

`real Qt control -> MainWindow/Controller -> Model/ExperimentModel/CalibrationManager -> existing persistence and audit writers`

Future simulation components may provide virtual external stimuli. They may
not replace application business logic, write authoritative experiment files
directly, manufacture terminal state, or report Controller/Model calls as UI
coverage.

The primary future full-lifecycle journey must start in the Experiment Editor.
It must not use
`tools/virtual_workflows/scenarios.py::_create_prepared_fixture`, direct canned
Model calibration, direct authoritative JSON/CSV writes, or direct Model state
mutation as user-workflow setup.

Existing prepared-fixture scenarios remain compatibility anchors until they
are migrated.

## Accepted Decisions

1. Hardening-plan Slice 4.7,
   `print_array_disconnect_mid_array_24_v1`, is paused. Disconnect becomes an
   early composed-journey proof after the shared session/harness exists.
2. `FreeRTOS-interface/App.py` remains production-only. Interactive simulation
   uses a dedicated launcher and launcher-owned `SIMULATOR CONTROL`.
3. The production connection widget remains disabled in simulation.
   Simulation connects only to `SIMULATED` and performs no port enumeration.
4. Sessions use a fresh contained root by default. Retention/reopen requires
   an explicit option or selected path.
5. Standard runs use a fixed instance-local seed. Exploratory seed sets are
   versioned and retained.
6. `labcraft.virtual_workflow_report` version 1 and the current report-set,
   baseline, comparison, policy, and Pi identities remain compatible through
   Milestone 5. New evidence is additive and nested.
7. Production-artifact fidelity is a gate. The same application writer and
   lifecycle operation must create, mutate, validate, and reload experiment
   artifacts.
8. Synthetic calibration will not fabricate camera captures or claim physical
   calibration/image-analysis coverage. Missing raw captures remain explicit.
9. SIL reports, screenshots, generic state traces, generated-result envelopes,
   stdout, tracebacks, and cleanup diagnostics remain outside the experiment
   directory.

## Frozen Compatibility Anchors

Existing tests confirmed:

- CLI default `virtual_print_array_96_v1`;
- all current registered scenario choices;
- current CLI flags, defaults, help behavior, and exit codes `0`, `2`, `3`,
  and `4`;
- `VirtualPrintArrayScenarioConfig`;
- `run_virtual_print_array_scenario`;
- `EditorLifecycleScenarioConfig` and the three public editor runners;
- `ScenarioDefinition` and registry dispatch;
- `labcraft.virtual_workflow_report` version 1;
- `labcraft.virtual_workflow_report_set` version 1;
- `labcraft.virtual_workflow_baseline` version 1;
- `labcraft.virtual_workflow_comparison` version 1;
- `virtual_workflow_policy_v1`;
- distinct Windows and Pi accepted-baseline population identities;
- capability-manifest identity, assertion IDs, artifact names, and Pi safety
  requirements.

No additional compatibility test was required because
`tests/test_virtual_workflow_contract_freeze.py` already executes these
contracts.

## Reference Evidence

The reports were generated from the source commit above with a dirty worktree
containing only the new untracked planning documents. All selected reports set
`hardware_access_allowed` to false and identify all physical interfaces as
disabled.

| Reference | Result | Report SHA-256 | Fixture SHA-256 |
| --- | --- | --- | --- |
| 24-well print | Pass; 24/24 completions; 12,688.639 ms | `23632B1847E2A670485DE55EC1AEB8DA4D6702D6CC7CB5E49255D5E748A64343` | `CC4F8758D70F207A221399A35ED4110A186C6D4644435E811A2C1A8AE61E7B67` |
| Editor create/finalize | Pass; 8/8 assertions; 8,495.477 ms | `C1ABA40231638E11D18CAB09E3F4A6B89089A9C304C85B8AE05A24969618DAD8` | `FC2BDF34FA5A7D8A9E851ACE7A099AA8E05C61C2D0CD075B620D69937F8BFC45` |
| Two-stock head exchange | Pass; 48/48 stock/well completions; 20,696.964 ms | `BEBB46745A37F60EFCD12D873042E780EB4F049537A834A52AD5307F4C53E638` | `6D85B7914F83358345A4A7FB28D60C1407E166852F0333E5FAFD7880EBE3EA54` |
| Injected-stall failure | Expected fail; stall detected; 6,147.5082 ms maximum event-loop gap; 2/24 completed | `56C9BEC217494C5FD92E8AC083088225524A8BA992F3F043708B252B97EDFDEB` | `CC4F8758D70F207A221399A35ED4110A186C6D4644435E811A2C1A8AE61E7B67` |

Exact report paths:

- `verification_reports/virtual_workflows/slice0_c393f5d888b9_retry/virtual_print_array_24_v1/20260729T004634903624Z_c393f5d888b9/report.json`
- `verification_reports/virtual_workflows/slice0_c393f5d888b9_retry/experiment_editor_create_finalize_v1/20260729T004658759824Z_c393f5d888b9/report.json`
- `verification_reports/virtual_workflows/slice0_c393f5d888b9_retry2/print_array_multi_stock_24x2_v1/20260729T004732187377Z_c393f5d888b9/report.json`
- `verification_reports/virtual_workflows/slice0_c393f5d888b9_failure2/virtual_print_array_24_v1/20260729T004838392043Z_c393f5d888b9/report.json`

The injected-stall report retains:

- `screenshots/failure.png`;
- `failure_traceback.txt`;
- `events.jsonl`;
- `stall_stacks.txt`;
- failed action/stage evidence;
- terminal and cleanup evidence.

All four documents passed the repository's `validate_report_v1` validator.
They are ignored compatibility evidence, not accepted performance baselines.
No baseline was accepted, replaced, or modified.

### Additional reload/resume characterization

The additional authoritative reload/resume run passed:

- 24/24 completions;
- one soft stop and close;
- reconstruction and activation in a second application session;
- resume and terminal completion;
- clean checkpoint with no retained intents;
- report SHA-256
  `0344149A4FF9C39289DDF116F70B75AFCA5B6075224FBFD03381D8653C1181F9`.

Report:

`verification_reports/virtual_workflows/slice0_c393f5d888b9_reload_retry/authoritative_reload_resume_24_v1/20260729T005226931285Z_c393f5d888b9/report.json`

Its audit sequence includes:

- initial authoritative activation;
- plan lock and calibration revision;
- print request/start;
- soft-stop request and pause;
- second authoritative activation;
- resume request/start;
- plan completion and print completion.

## Artifact Characterization

### Session-owned roots

Every selected session retained its application roots beneath
`scenario-root`:

- `config/`;
- `experiments/`;
- `calibration-memory/`.

Normal Model construction created the contained configuration files:

- `Locations.json`;
- `Obstacles.json`;
- `Plates.json`;
- `RegulatorProfiles.json`;
- `Settings.json`.

Calibration-memory initialization created its normal schema/config/entity
files. The editor-created experiment also produced application-owned
calibration-memory run, observation, catalog, recommendation, reagent,
head-type, pair, and pair-type index records through the real
calibration-manager session.

### Editor-created prepared experiment

The real Qt editor/finalization reference created:

- `experiment_design.json`;
- `progress.json`;
- `calibration.json`;
- `experiment_audit.jsonl`;
- `execution_plan.json`;
- `execution_plan_revisions/revision_000001.json`;
- `execution_resume.json` after explicit activation;
- `key.csv`;
- `concentration_key.csv`.

Final state:

- plan revision `1`;
- plan state `prepared`;
- progress plan identity matches the plan;
- resume state `clean` with no intents;
- latest immutable revision equals `execution_plan.json`;
- no execution calibration document, as expected before calibration.

### Completed one-stock experiment

The 24-well reference created the common files above plus:

- `execution_calibrations.json`;
- revisions `000001` through `000004`.

Final state:

- plan revision `4`;
- plan state `completed`;
- one execution-calibration record;
- progress and resume plan identities match the plan;
- resume state `clean` with no intents;
- latest immutable revision equals `execution_plan.json`;
- audit includes activation, lock, calibration, print request/start, plan
  completion, and print completion.

### Completed two-stock experiment

The two-stock reference created:

- the same authoritative base files;
- `execution_calibrations.json` with two records;
- revisions `000001` through `000005`.

Final state:

- plan revision `5`;
- plan state `completed`;
- two execution-calibration records;
- 48/48 stock/well completions over two head passes;
- progress and resume identities match the plan;
- resume state `clean` with no intents;
- latest immutable revision equals `execution_plan.json`.

### Interrupted experiment

The injected-stall reference retained:

- plan revision `3`;
- plan state `active`;
- progress and resume identities matching revision `3`;
- resume state `printing`;
- two explicit pending intents with well, reaction, stock, droplet, and command
  sequence identities;
- immutable revisions `000001` through `000003`;
- failure screenshot, traceback, events, stall stacks, and clean harness
  teardown.

This is the required durable interrupted-state anchor. The failure harness did
not manufacture a clean terminal application state.

### Reloaded terminal experiment

The reload/resume reference retained:

- plan revision `4`;
- plan state `completed`;
- `labcraft.execution_progress` version `2` linked to the same plan/revision;
- resume state `clean` with no intents;
- latest immutable revision equal to `execution_plan.json`;
- audit evidence spanning both application sessions.

### Cross-file validation

Read-only checks passed for all five characterized experiment directories:

- `execution_plan.json`, `progress.json`, and `execution_resume.json` have the
  same plan ID and revision;
- `execution_plan.json` is semantically identical to the immutable revision
  named for its current revision;
- revision names are contiguous for each selected lifecycle;
- selected reports and artifacts remain within their session/report roots.

## Important Fidelity Gap Carried Forward

No current print reference creates `calibration_recordings/`. Current print
scenarios prepare the plan with `_create_prepared_fixture` and apply direct
canned execution calibration. Their `calibration.json` does not represent a
normal completed imaging process.

This confirms, rather than resolves, the reason for Milestones 1-4:

- the future full lifecycle must begin in the real editor;
- synthetic calibration generation must be separate from presentation/apply;
- presentation and apply must use application-owned calibration APIs;
- the real calibration manager, audit writer, calibration-memory store, plan
  revision writer, progress writer, resume writer, and export writers must
  own their normal files;
- if process recording is active, the application recorder must create native
  metadata/event/analysis/verdict files;
- raw camera files must not be fabricated and their absence must be explicit.

## Intermittent Windows Persistence Finding

Three non-reference attempts failed closed on an intermittent Windows
filesystem access error during durable checkpoint replacement:

1. initial 24-well attempt: access denied replacing a temporary
   `execution_resume.json` after 19/24 wells;
2. initial two-stock attempt: progress save became ambiguous after 8/48
   stock/well completions;
3. initial reload/resume attempt: progress completed, but its durable intent
   could not be completed.

Each scenario passed on one clean retry. Focused persistence tests, lifecycle
tests, and the full suite also passed.

The failures were not converted to expected success and their reports remain
under the ignored Slice 0 output roots. No production persistence behavior was
changed in this slice.

Milestone 1 must:

- preserve the existing fail-closed behavior;
- retain the exact failing path, operation, exception, and checkpoint state;
- avoid placing interactive session roots in known sync/lock-prone locations
  by default when a safer contained local root is available;
- provide an explicit retained-root override;
- never silently retry or mask an ambiguous production checkpoint write;
- treat repeated access-denied failures as an environment or persistence
  finding, not simulator success.

## Validation Results

Focused contracts:

```text
188 passed in 74.36s
```

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_simulated_machine.py `
  tests\test_initial_execution_plan_integration.py `
  tests\test_execution_calibration_store.py `
  tests\test_experiment_audit_integration.py `
  tests\performance\test_virtual_workflow_comparison.py
```

Lifecycle:

```text
13 passed, 90 warnings in 79.45s
```

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_multi_stock_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py
```

Full regression:

```text
3655 passed, 38 skipped, 80 warnings in 1497.63s (0:24:57)
```

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

The warnings are existing Qt Charts deprecation warnings. Slow offline
analysis-pipeline tests remained skipped under the repository's normal test
policy.

The full suite includes safe application construction, supplied-root
containment, simulation identity, blocked physical/updater operations,
simulated-machine behavior, persistence, calibration, editor, execution,
report, comparison, and cleanup coverage.

## Slice 0 Gate

The Slice 0 gate is satisfied:

- decisions and dependency ownership are frozen;
- production-artifact fidelity is explicitly defined;
- current shortcut boundaries are documented;
- compatibility anchors are executable and passing;
- four required report-v1 references validate;
- an additional reload/resume reference validates;
- application artifact trees and cross-file identities reconcile;
- hardware access remains false and roots remain contained;
- focused, lifecycle, and full regression gates pass;
- synthetic/physical calibration limitations are explicit;
- intermittent Windows persistence failures are retained and carried forward;
- no runtime, baseline, Pi, firmware, protocol, or hardware change was made.

The next task is to create the concrete Milestone 1 plan for the dedicated
interactive `SimulationSession` and launcher. Do not implement synthetic
calibration, composed journey migration, disconnect injection, firmware,
protocol, Pi operations, or hardware behavior in Milestone 1.

## Rollback

Rollback removes only the Slice 0 documentation and ignored reference output.
It must not delete or rewrite production experiment data, accepted baselines,
tracked verification evidence, release metadata, tags, or history.

