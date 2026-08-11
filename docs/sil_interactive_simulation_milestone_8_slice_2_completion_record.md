# Milestone 8 Slice 2 Completion Record

Date: 2026-08-07

Status: complete

Baseline HEAD: `fb30c0324727a259593e230395c692fd8cfdfbb5`

## Delivered behavior

The runner now has a read-only planning call path:

`CLI selector → validated capability manifest → typed resolver → deterministic JSON`

It supports catalog listing, direct-scenario/suite/capability dry-run plans, and
changed-source recommendations. Every payload includes the manifest identity
and SHA-256 and records `execution_authorized: false`. Planning returns before
Qt/application imports and creates no report directory.

The existing direct execution path remains unchanged:

`--scenario → registry → environment/Pi validation → existing workflow runner`

Suite/capability selection is deliberately dry-run-only until Slice 3. The
standard lane is frozen at one `print_array_smoke_24_v1` scenario, seed 1,
order 1, and a 60-second timeout. Deferred capabilities, inactive scenarios or
suites, platform mismatches, and missing Pi safety evidence fail closed.

Changed-source recommendations use explicit paths when supplied; otherwise
they read staged, unstaged, and untracked Git paths. Exact and directory-prefix
matches report capability status, matching source areas, and ordered active
scenarios but never execute them. Manifest schedule records now consistently
state `on_demand` cadence and `manual` automation status. Evidence-age values
remain informational.

No production View, Controller, Model, simulator, report schema, protocol,
firmware, Pi operation, scheduler, or hardware behavior changed.

## Focused validation

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests/test_virtual_workflow_selection.py `
  tests/test_virtual_workflow_manifest.py `
  tests/test_virtual_workflow_contract_freeze.py
```

Result: `117 passed in 4.69s`. A final repeat after Windows denied access to
pytest's user temp root used the repository-local
`--basetemp local\pytest_m8_slice2_final2` and passed `117` tests in `4.66s`.
The intervening setup errors occurred before test bodies and were not assertion
failures.

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests/system/test_virtual_workflow_smoke.py
```

Result: final repeat `2 passed in 4.67s`, with 14 existing Qt deprecation
warnings, using repository-local
`--basetemp local\pytest_m8_slice2_smoke_final` after the same user-temp issue.

Manual planning checks also passed:

- `--list all`: 6 suites, 28 capabilities, and 11 scenarios;
- `--suite lifecycle --dry-run`: eight scenarios in manifest order 1–8;
- mixed-mode capability dry-run: selected
  `print_array_mixed_mode_24x2_v1` and did not authorize execution;
- explicit `page_drivers.py` recommendation: selected the mixed-mode
  lifecycle capability/scenario without Git discovery or execution.
- Git discovery: found all 11 staged/unstaged/untracked Slice 2 paths, produced
  no unrelated capability recommendation, and did not authorize execution.

No suite report or scenario artifact was expected or written. The full pytest
suite remains intentionally deferred until final Milestone 8 Slice 8
validation, and no remote Pi validation was run.

## Risk and rollback

The principal risk is accidental execution from an ostensibly read-only mode.
The CLI tests replace the dispatcher with a hard failure, assert no output-root
creation, and prove the planning process imports neither PySide6 nor application
modules. Pi-capable scenarios require Pi evidence only when planned for the Pi;
Windows plans do not incorrectly demand it.

Rollback removes `selection.py` and the additive CLI options, restores the
prior schedule metadata, and reverts the focused tests/docs. No persisted
experiment data, accepted performance baseline, report schema, protocol,
firmware, or hardware state requires migration or recovery.
