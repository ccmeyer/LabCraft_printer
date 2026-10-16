# Parallel Windows development worktrees

Windows x64 CPython 3.13 is the supported local development platform (initial
qualification uses 3.13.14). Each worktree owns an `env`; pip's download cache
may be shared, but installed packages and mutable test data are never shared.
Install Git for Windows, Python, and PowerShell first. Firmware work also needs
CMake, Visual Studio C++ build tools, and STM32CubeIDE 1.18.1 at the location
already used by the firmware build script.

## Create and provision

Run in the existing repository, supplying your new branch and destination:

The base revision must include these tools. Until this work is merged, use
`codex/parallel-worktrees` in place of `main` below.

```powershell
git worktree add -b codex/my-change ..\LabCraft-my-change main
Set-Location ..\LabCraft-my-change
.\tools\setup_worktree.ps1 -Python 'C:\absolute\Python313\python.exe'
# Include local firmware prerequisites and the exact pinned CppUTest submodule:
.\tools\setup_worktree.ps1 -Python 'C:\absolute\Python313\python.exe' -IncludeFirmware
# Read-only prerequisite/environment verification:
.\tools\setup_worktree.ps1 -Python 'C:\absolute\Python313\python.exe' -IncludeFirmware -CheckOnly
```

Setup never updates an existing environment: rerunning verifies the exact lock
and dependency consistency. An incompatible/partial environment is a refusal;
keep it for diagnosis and provision a fresh worktree. Do not copy environments,
CMake caches, experiment directories, or submodule `.git` files. Git submodule
commands use the installed Git for Windows Bash environment without modifying
global PATH or Git configuration. Missing tools and dirty/mismatched submodules
are blockers, not permission to overwrite them.
Git paths are decoded as UTF-8, including accented worktree names; temporary
output checks inventory every registered worktree with NUL-delimited paths.

Development requirements live under `requirements/windows-dev/` so adding them
does not change the existing Pi root dependency fingerprint. `requirements.in`
records direct dependencies; `requirements.lock` pins their complete Windows
closure, including packaging tools. To change dependencies, update both files
on a branch and qualify a fresh environment; do not change the Pi interpreter.

## Tests and simulation

```powershell
.\tools\run_worktree_tests.ps1 -PytestArgs @('-q','tests/test_legacy_execution_migration.py')
.\tools\run_worktree_tests.ps1 -PytestArgs @('-q')
.\tools\run_worktree_tests.ps1 -PytestArgs @('-q','--run-sil-lifecycle','tests/system/test_virtual_workflow_smoke.py')
```

The runner verifies this worktree's environment, clears inherited Python/pytest
and machine/hardware authority settings, uses offscreen Qt, and selects the
known pytest-qt plugin. Each invocation receives a fresh external OS temporary
root with `run.json`, `pytest.log`, `junit.xml`, pytest data and caches. The
runner prints that path immediately and preserves pytest's exit status.
Keep the Windows temporary base short: deeply nested paths can exceed Git's
filename limit in local-remote fixtures. For durable retention, copy the finished
`run.json`, `pytest.log`, and `junit.xml` into an external evidence directory;
preserve their bytes and record the original run directory. Do not redirect
live test data into a deep report-archive path or change Git limits to hide a
failing qualification.
Caller overrides of temporary/report paths, plugins and pytest configuration
are refused, including `-c`/`--config-file` and all `--debug` forms, which could
otherwise select checkout-local logs or caches. Invoke only one setup operation
per worktree; use separate worktrees for concurrent testing.
Direct `env\Scripts\python.exe -m pytest`
remains available for diagnosis; give it a unique external `--basetemp`.

Test fixtures must pass temporary configuration and black-box log roots rather
than writing the checkout's ignored `local/` or `logs/` directories. The wrappers
disable source bytecode generation as well. Include ignored outputs in final
worktree audits: clean tracked Git status alone does not prove output isolation.

Use distinct fresh SIL sessions for interactive simulation. Keep acceptance
benchmarks and timing qualifications separate from competing heavy work.
Allow at least 15 minutes per full-suite process.

## Historical recording replays

Default tests never discover archived recordings under an ignored checkout.
Historical tests require `--historical-fixture-root`; synthetic tests still run.
Stage the 175 manifest-listed inputs plus the bounded dense-tail geometry
derivation once, preserving the originals:

```powershell
.\env\Scripts\python.exe tools\historical_fixtures.py `
  --source 'C:\archive\Experiments' --destination 'C:\LabCraft-test-data\historical-v1'
.\tools\run_worktree_tests.ps1 -PytestArgs @('-q','tests','-m','historical_replay',
  '--historical-fixture-root','C:\LabCraft-test-data\historical-v1')
```

Keep the explicit `tests` target: it loads the repository's custom pytest
options before pytest interprets the external fixture directory.

The source may be an existing ignored `FreeRTOS-interface/Experiments` archive.
The destination must be new and outside every registered worktree. Staging
copies only declared CSV/JSON/image inputs, checks SHA-256 values, and refuses
existing destinations. For the 26 dense stream runs it also reads the exact
referenced 3,146 raw captures, derives geometry using the recorded nozzle
coordinates and pinned silhouette parameters, and writes 26 small geometry CSVs
plus a provenance receipt. Raw dense captures are read only, not copied. Their
per-run source inventory hashes, derived output hashes, LF-normalized analyser
source hashes, dependency versions, and parameters are pinned in
`tests/fixtures/dense_tail_geometry_manifest.json`. The resulting staged dataset
has 202 files. Allow a few minutes for geometry extraction. Changed sources,
implementation, dependencies, or derived bytes are refusals. Failed staging
leaves its partial copy for diagnosis.
Tests validate the selected replay group's bytes before and after use.
Missing, altered, or insufficient inputs fail when replay is requested.
The separate optimizer fixture contract is unchanged.

The tracked stream-tail validation manifest is checked as a historical snapshot.
Its generator uses small synthetic runs in default tests, including missing-file
exclusions and density correction; default tests do not regenerate that snapshot
by scanning the original 156 archived runs. Qt test cleanup also collects Python
reference cycles on the GUI thread after worker shutdown, so later worker
allocations cannot collect objects retained by a previous test.

Dense-tail replay joins independently extracted geometry to feature rows by
capture identity and both absolute/relative times. It validates the emergence
reference and uses the existing runtime plateau-anchor selection and capture
budget compression helpers. The original numerical gates remain at least five
usable results, median error <=400 us, and worst error <=700 us. The archived
feature CSVs alone do not contain the required geometry; older 175-file staged
datasets must be preserved and replaced by a newly staged external dataset.
Do not synthesize geometry from expected tail-start labels or lower the gates.

## Firmware and shared resources

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Host build output stays in this worktree and CubeIDE uses a unique temporary
workspace. The combined gate rebuilds `firmware/artifacts/LabCraft_firmware.bin`;
review any difference and include the same-build artifact with firmware
milestone commits. Never reset a changed binary to obtain a clean gate.
The firmware embeds `__DATE__`/ `__TIME__`, so equivalent builds can differ in
that diagnostic string. Record exact hashes and inspect differences rather than
claiming byte reproducibility. The build restores settings only when CubeIDE
changed generated environment hashes; substantive settings edits are retained.

Git worktrees share refs, repository configuration and object storage. Give each
worktree a distinct branch, avoid concurrent ref/configuration changes, and do
not remove retained worktrees. The Pi development worktree, production Python
environment, machine-data store and installed firmware remain shared resources.
Serialize Pi operations through the existing guarded wrappers. Local setup and
tests do not authorize any Pi launch, flash, or physical hardware operation.

## Recovery and retirement

Keep failed-run evidence. Repair missing system prerequisites explicitly and
rerun check-only; never bypass blockers. Do not automatically delete partial
environments. Before retiring a task-owned worktree, verify its absolute path,
clean Git/submodule state, retained files and stopped owned processes, then use
normal `git worktree remove` without force. Preserve user data and evidence.
Rollback repository changes with normal branch commits/reverts; no machine-data
migration or installed-firmware rollback is required for this local workflow.
