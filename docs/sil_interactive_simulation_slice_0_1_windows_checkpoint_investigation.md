# Slice 0.1 Windows Checkpoint Access Investigation

Date: 2026-07-28  
Source commit: `c393f5d888b917a42e5f14a45e90e05b166fe78d`

## Outcome

The post-restart investigation did not reproduce a checkpoint access failure
through the production-equivalent absolute-path workflow or writer controls.
It is reasonable to proceed to the Milestone 1 planning work without changing
application persistence behavior.

The earlier failures remain real and are not considered fixed. They are
classified as intermittent Windows/external-environment access denials because:

- both `progress.json` and `execution_resume.json` atomic replacements failed;
- each failure was a `PermissionError`/`[WinError 5] Access is denied`;
- instrumented persistence phases were serialized on one application thread;
- the same scenarios passed on retry before the restart;
- 28 composed workflow runs passed after the restart across two roots and two
  acceleration settings;
- 8,000 direct production-writer calls with absolute paths passed after the
  restart; and
- focused persistence tests passed.

This evidence makes a deterministic schema, serialization, or internal
same-process writer race unlikely. It does not identify which external process
or Windows subsystem temporarily denied the replacements before the restart.

## Scope

This was a diagnostic-only slice. It made no changes to:

- application or simulator code;
- persistence behavior or retry policy;
- tests or accepted baselines;
- firmware, protocol, updater, Pi, or hardware behavior.

Generated investigation reports remain under ignored verification output roots.
Local-path comparison evidence remains under
`%LOCALAPPDATA%\LabCraft\SIL-investigation`.

## Checkpoint Call Path

The relevant completion path is:

```text
simulated command completion
  -> Controller completion handling
  -> ExperimentModel.create_progress_file(...)
  -> ExperimentModel._write_progress_payload(...)
  -> ExperimentModel._atomic_write_text(...)
  -> tempfile.mkstemp + flush + fsync + os.replace
  -> ExperimentModel.complete_execution_print_intent(...)
  -> ExperimentModel._save_active_execution_resume(...)
  -> ExecutionResumeStore.save_execution_resume(...)
  -> tempfile.mkstemp + flush + fsync + os.replace
```

Command creation and command-sequence attachment also save
`execution_resume.json` through the same resume writer. The writers create the
temporary file in the destination directory, flush and `fsync` it, and then
call `os.replace`. They clean up their temporary file and propagate an
exception when replacement fails.

The Controller converts these failures into a fail-closed execution state:

- a failed progress write blocks printing because completion is ambiguous;
- a failed resume write after progress blocks printing because the durable
  intent cannot be reconciled; and
- a failed command-boundary resume write blocks printing rather than treating
  the command as safely checkpointed.

This behavior worked as intended in all three retained failures.

## Retained Pre-Restart Failures

### Resume command-boundary replacement

Report:

```text
verification_reports/virtual_workflows/
  slice0_c393f5d888b9/
  virtual_print_array_24_v1/
  20260729T004611585040Z_c393f5d888b9/report.json
```

The scenario stopped at 19/24 completions. Windows denied replacement of a
same-directory `._tmp_*.json` file with `execution_resume.json`.

### Progress replacement

Report:

```text
verification_reports/virtual_workflows/
  slice0_c393f5d888b9_retry/
  print_array_multi_stock_24x2_v1/
  20260729T004713914562Z_c393f5d888b9/report.json
```

The scenario stopped at 8/48 stock/well completions. Performance evidence
recorded:

```text
name: persistence.write_progress
outcome: exception
error_type: PermissionError
phase_id: 157
thread_id: 18868
duration_ms: 12.964
```

### Resume completion replacement

Report:

```text
verification_reports/virtual_workflows/
  slice0_c393f5d888b9_reload/
  authoritative_reload_resume_24_v1/
  20260729T005201068331Z_c393f5d888b9/report.json
```

Progress reached 24/24, but completion of the durable print intent failed.
Performance evidence recorded:

```text
name: persistence.save_resume
outcome: exception
error_type: PermissionError
phase_id: 478
thread_id: 17644
duration_ms: 11.6949
```

The enclosing `persistence.complete_intent` phase failed on the same thread.

## Filesystem Characterization

The repository root is on the local `C:` NTFS volume. Windows reported:

```text
FileSystem: NTFS
HealthStatus: Healthy
OperationalStatus: OK
LinkType: none
```

The repository directory has Windows directory, archive, read-only, and
provider-style pinned attribute bits. A directory read-only bit is not itself
proof of denied file replacement, and the root is not a symlink or reparse
target. The provider-style attribute is a reason to prefer a dedicated local
application-data session root, but it does not establish the root cause.

## Post-Restart Composed Controls

All 28 composed runs passed with no checkpoint access errors.

| Scenario/control | Repository root | Local AppData | Total |
| --- | ---: | ---: | ---: |
| 24-well smoke at 1000x | 5/5 | 5/5 | 10/10 |
| two-stock 24x2 at 1000x | 3/3 | 3/3 | 6/6 |
| authoritative reload/resume at 1000x | 3/3 | 3/3 | 6/6 |
| 24-well smoke at 100x | 3/3 | 3/3 | 6/6 |
| **Total** | **14/14** | **14/14** | **28/28** |

The multi-stock controls each performed 144 resume fsyncs and 48 progress
fsyncs. The reload/resume controls each performed 75 resume fsyncs and 24
progress fsyncs.

Repository evidence roots:

```text
verification_reports/virtual_workflows/slice01_postrestart_workspace_smoke
verification_reports/virtual_workflows/slice01_postrestart_workspace_multi_1
verification_reports/virtual_workflows/slice01_postrestart_workspace_multi_2
verification_reports/virtual_workflows/slice01_postrestart_workspace_multi_3
verification_reports/virtual_workflows/slice01_postrestart_workspace_reload_1
verification_reports/virtual_workflows/slice01_postrestart_workspace_reload_2
verification_reports/virtual_workflows/slice01_postrestart_workspace_reload_3
verification_reports/virtual_workflows/slice01_postrestart_workspace_speed100
```

The matching Local AppData roots use the same final root names under:

```text
%LOCALAPPDATA%\LabCraft\SIL-investigation
```

The scenario configuration resolves output and report directories before
assigning experiment paths. These runs therefore exercised absolute
destination paths like normal application-owned experiment paths.

## Direct Atomic-Writer Controls

The production resume writer and the Model progress text writer were each
called 2,000 times in each location using absolute source and destination
paths.

| Root | Resume writes | Progress writes | Result | Temporary leftovers |
| --- | ---: | ---: | --- | ---: |
| repository verification root | 2,000 | 2,000 | pass | 0 |
| Local AppData | 2,000 | 2,000 | pass | 0 |
| **Total** | **4,000** | **4,000** | **8,000/8,000 pass** | **0** |

Both locations ended with identical hashes:

```text
execution_resume.json:
  05190aef83f6c6409a7af546b86e5560f8502f07275a2167363441ed0ddc64c3
progress.json:
  d058b430000d9bb9679dd6c4a84063b7b20bbfc6d685d12a39358bf03db957da
```

An initial diagnostic accidentally supplied an absolute temporary source and
a relative destination to `os.replace`. That mixed-path control intermittently
produced `WinError 5`: two batches failed and a later 2,000-write batch passed.
The composed runner does not use that operand combination, so this result is a
harness warning rather than a production-path failure. Future direct writer
stress must resolve both operands first.

## Focused Test Result

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_execution_resume_store.py `
  tests\test_model_atomic_writes.py `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_authoritative_execution_load.py
```

Result:

```text
27 passed in 4.50s
```

The full Slice 0 regression result remains:

```text
3655 passed, 38 skipped, 80 warnings in 1497.63s
```

## Root-Cause Assessment

Most likely classification:

```text
transient Windows or external-process denial of atomic replacement
```

Plausible sources include a temporary file handle held by security, indexing,
backup, or storage-provider software, or the broader computer malfunction that
preceded the restart. The current evidence does not distinguish among them.

Less likely explanations:

- malformed JSON or invalid checkpoint state, because serialization and
  validation completed before `os.replace`;
- cross-volume replacement, because temporary and destination files share a
  directory;
- deterministic permission configuration, because clean retries and thousands
  of later writes passed;
- an application writer race, because the failed instrumented phases were
  serialized on one thread.

The confidence in the environmental classification is moderate, not
conclusive. The process that held or denied access was not observed while the
failure was active, and a restart removes that evidence.

## Gate And Recommendation

Slice 0.1 does not block Milestone 1 planning.

Milestone 1 should retain these requirements:

- default interactive session data to a contained local application-data root;
- allow an explicit retained-root override;
- use resolved absolute experiment and checkpoint paths;
- preserve fail-closed checkpoint behavior;
- do not silently retry or mask an ambiguous production checkpoint write;
- retain the operation, source/destination paths, exception, checkpoint phase,
  and state when a write fails; and
- keep repository and Local AppData repetition controls available.

Before declaring the Milestone 1 Windows launcher stable, require on the target
Windows host:

1. five clean 24-well smoke runs;
2. three clean two-stock runs;
3. three clean reload/resume runs;
4. no unexpected `PermissionError` or checkpoint dialog; and
5. valid terminal plan/progress/resume reconciliation for every run.

If an absolute-path failure recurs after the restart:

1. preserve the failed report and experiment directory;
2. record the exact source, destination, operation, and Windows error;
3. inspect the active handle owner and relevant security/storage-provider
   events before restarting;
4. compare the same bounded run in Local AppData; and
5. open a focused persistence/environment issue before changing retry policy.

## Rollback

This slice added only this investigation record and ignored diagnostic output.
Rollback removes this document and, if desired, the specifically named
`slice01_postrestart_*` investigation roots. It must not remove the retained
pre-restart failure reports, production experiment data, accepted baselines,
release metadata, tags, or history.
