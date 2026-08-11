# Milestone 13 Slice 13.4 Completion Record

Status: `complete`

Completed: 2026-08-09

## Outcome

Milestone 13 now has a separate schema-v2 fresh-process aggregate runner. It
retains each normalized sequence before launch, passes that exact file to the
child CLI, validates the child report against the retained bytes and frozen
hashes, and emits an aggregate replay command that consumes the retained
`exploration_plan.json`. Milestone 8 remains on its unchanged schema-v1 runner.

The frozen campaign passes six independent child processes and reports
complete semantic coverage across 12 states, 34 declared frozen transitions,
26 admitted operations, and eight rejection classes. Coverage comes only from
reached transitions in passing reports; seed count and action count are
explicitly not coverage measures.

Every child owns an immutable original-sequence reference, exact rerun command,
stdout/stderr, report/hash when present, cleanup evidence, and reached prefix.
The failure index is written even when empty. Injected missing-report and
timeout/kill tests prove that the runner continues, retains the original, and
fails closed. Deterministic reduction is intentionally disabled, so no
derivative can replace an authoritative original.

## Budgets and isolation

The qualifying frozen direct/replay each observed 362 action rows, 18 sessions,
24 screenshots, 83 retained files, approximately 10.8 MiB, and approximately
54 seconds. These are within the strict `480/18/24/1600/320 MiB/1800 s`
campaign limits. Each child retains the existing `80/3/4/256/48 MiB/270 s`
limits and a 300-second external watchdog.

Diagnostic seed 1 passed direct and exact replay as a one-child diagnostic
aggregate. It retained its plan, sequence, coverage, and reports, while
`release_gate.affected` remained false and status remained `not_applicable`.
Unit tests prove resolving/running diagnostics cannot alter the frozen plan or
hashes and that at most four explicit diagnostic seeds are accepted.

## Qualification evidence

| Evidence | Direct SHA-256 | Exact replay SHA-256 |
| --- | --- | --- |
| M13 frozen aggregate | `98a79fd77c6581058edffcb03382217767172eb35e26c27f9dab86e187cf7bb2` | `b8823687f80e439e6bb70bd522c770dca61132718886b45f02921b61ae368876` |
| diagnostic seed 1 aggregate | `b1fdbfd22b75a2a61f24bd6f18747c81a055ddcac514190dcf451a0053b57aa3` | `f46b850bc08509abdc5ad0acc97cf66e8c65d2c87814e48ae40ab7ef530a3c64` |
| unchanged M8 aggregate | `3e7223a3e2497e457582d76dc5d403822758f6663d39cdb6dc04e7524401fede` | `39ad32bd61890ae495c162b8c2c7e127249fa74c833660ec85e1a3601481a061` |

The M13 frozen retained-plan, coverage, and empty original-failure hashes are:

- plan:
  `bb6b9972489ffa0f5badd6df0e3420325f74cf18d982a82db36b828a84d44b78`;
- semantic coverage:
  `226b32003422424de431768fc800b1550b7e40780b1073bb76738c69d38434af`;
- original-failure index:
  `43ff106bbe0924c3ad27501ae616d0cf517de24d2cd8d789ec7eb3ecdc997161`.

Qualification roots are
`verification_reports/milestone_13_slice_4/qualified/`,
`diagnostic_qualified/`, and `m8_compat/`. Every aggregate and child report
retains its exact command and source identity. No aggregate is registered as a
replacement for deterministic capability evidence.

## Automated validation

Passed commands included:

```powershell
.\env\Scripts\python.exe -m pytest -q --basetemp verification_reports\pytest_tmp\m13_slice4_focus tests\test_virtual_workflow_exploration_m13.py tests\test_virtual_workflow_exploration_runner_m13.py tests\test_virtual_workflow_exploration_runner.py tests\test_virtual_workflow_m13_interaction_cases.py tests\test_virtual_workflow_actions.py tests\test_virtual_workflow_assertions.py tests\system\test_virtual_workflow_m13_exploration_execution.py tests\system\test_virtual_workflow_m13_exploration_aggregate.py
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle --basetemp verification_reports\pytest_tmp\m13_slice4_system_final tests\system\test_virtual_workflow_m13_exploration_execution.py tests\system\test_virtual_workflow_m13_exploration_aggregate.py
git diff --check
```

The default-marker focused selection passed 88 tests with seven expected
lifecycle skips. Final real-Qt/fresh-process system validation passed 7/7.
An earlier combined in-process run exposed a calibration-only queue-drain race;
the shared phase now waits for the existing simulator-drained boundary before
assertion. The isolated seed-83 rerun and the complete final system run both
passed without weakening the oracle. Analysis-pipeline tests were not run
because that code did not change.

## Files changed

- new `tools/virtual_workflows/exploration_runner_m13.py`
- `tools/virtual_workflows/exploration_m13.py`
- narrow M13 replay/diagnostic branches in `tools/run_virtual_workflow.py` and
  `tools/virtual_workflows/journeys.py`
- explicit calibration-only drain wait in
  `tools/virtual_workflows/journey_phases.py`
- M13 runner and fresh-process aggregate tests
- Milestone 13 master/execution/Slice 13.4 records

No production MVC, simulator protocol, firmware, hardware, refill/resume,
M8 runner/catalog, or deterministic M9-12/11A scenario changed.

## Risks and rollback

Replay intentionally validates retained normalized bytes against the current
versioned generator before execution. Any source/catalog drift therefore fails
before Qt rather than silently replaying a different meaning. Evidence
accounting includes the plan, originals, logs, children, coverage, failure
index, aggregate, and summary; any overrun fails without retry or cap growth.

Rollback removes only the schema-v2 runner, retained-plan/sequence CLI options,
diagnostic sequence composition, and related tests/records; restores the
Slice 13.3 explicit-sequence boundary; and leaves M8, deterministic scenarios,
retained evidence, and user experiment data untouched.
