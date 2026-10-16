# Parallel worktrees: evidence audit and merge review

Initial review: 2026-10-16. The three findings below describe the original
`3328b768` candidate. **They have been fixed at `aec12fa7`; all final
qualification gates passed.** See the remediation record at the end for
current status. The original inspection and failed evidence are retained.

## Candidate and review scope

- Branch: `codex/parallel-worktrees`.
- Reviewed HEAD: `3328b768248b157897c80397fa4194041cf36a18`.
- Local `main`/base: `84e0fa088cea2b0cb54c83db6e08e11de4d86a6e`.
- Eleven commits, 36 changed paths. The starting checkout and CppUTest were
  clean. No other worktree was modified by this audit.
- Qualification branches A and B remain at
  `027ed3763e2db67c37229b66f3a367c398c32095`. The final candidate differs only
  by removal of trailing blank lines from the extracted legacy test helper.

The review covered every changed text file and the tracked firmware artifact.
The main paths were PowerShell wrapper -> local Python supervisor -> environment
verification/subprocess -> external evidence; manifest -> fixture binding ->
replay helpers -> offline flow/tail analysis; and firmware build -> settings
preservation -> artifact publication. No Pi supervisor, physical factory, MCU
protocol, firmware runtime source, production data, release metadata, or
installed-firmware workflow is changed by this branch.

## Findings

### R1 — P2: the long configuration option bypasses the runner's guard

`tools/worktree_development.py:160-165` rejects `-c` but accepts pytest 9.1.1's
equivalent `--config-file`, including `--config-file=PATH`. A supplied config
can restore plugins and choose logging/cache paths despite the runner's stated
ownership of configuration and evidence paths.

The external scratch reproduction passed the actual argument guard, selected
an alternative config, and ran pytest successfully. It created both `custom.log`
and `.pytest_cache` in its working directory. In the real wrapper that directory
is the Git worktree. This is a demonstrated isolation gap, independent of
hardware access.

Required fix: reject both long-option forms alongside `-c`, or implement an
equally strict validated configuration contract. Add guard and subprocess
coverage showing that an alternate config cannot redirect outputs or load an
additional plugin. Preserve ordinary selectors and opt-in fixture arguments.

### R2 — P2: pytest's debug log escapes the external evidence root

The same guard accepts bare `--debug`, `--debug=PATH`, and the separate path
form. Pytest opens its debug file with truncation; bare `--debug` defaults to
`pytestdebug.log` in the current working directory. The controlled external
reproduction created that file. With this runner it would be written in the
worktree, or at a caller-selected location.

Required fix: refuse the debug option in all forms, or explicitly route it to
a unique runner-owned file below the external run directory and record it.
Cover bare, equals, and separate-argument forms. Do not rely on Git ignore rules
to establish output isolation.

### R3 — P2: the explicit dense-tail replay contract cannot pass as supplied

The branch now correctly fails instead of skipping when fewer than five usable
tail results are produced (`tests/test_stream_online_tail_replay.py:732`).
However, the supplied replay helper and dataset cannot exercise the intended
landmark/backtrack path. The fresh trace found **zero usable results across all
26 eligible runs**. There are two independent causes:

1. **Time-coordinate mismatch.** `_phase_features_by_delay` indexes rows by
   `delay_from_emergence_us`. `_replay_tail_result` generates absolute
   `scout_first_delay_us` values and passes them to that offset lookup. All
   260 scout requests miss. For the first run, emergence is 4,800 us, the first
   absolute scout time is 6,850 us, and the correct feature key is 2,050 us.
   Its feature offsets end at 5,950 us, so the existing 6,850 us lookup fails.
   Backtrack requests cross the same boundary and must be corrected together.
2. **Missing landmark evidence.** All 26 feature CSVs lack `cutoff_y_px` and
   `selected_component_top_y_px`, which `_feature_row_is_tail_landmark` requires.
   Converting the scout coordinates in an isolated diagnostic reduces missing
   lookups from 260 to 37, but still yields zero landmarks and zero usable
   results. The remaining missing lookups include requests beyond the captured
   range. Width collapse alone is deliberately insufficient under the current
   geometry requirement.

This is **not evidence of a new production tail-analysis regression**. AST
comparison shows that the four relevant replay helpers are identical to `main`;
`tools/stream_analysis/` has no branch changes. Executing the original `main`
test against the same verified external inputs reproduces its insufficient-set
skip. The branch exposes that existing problem by making explicit replay strict.

Required fix sequence:

1. Make the replay time contract explicit and validate each run's emergence
   reference. Convert at the feature-lookup boundary while retaining correct
   absolute and relative times in summaries, scout brackets, and backtracking.
   Add synthetic regression cases with a nonzero emergence time; the existing
   zero-origin synthetic cases do not detect this error.
2. Supply independently derived landmark evidence. Prefer a small, versioned,
   externally staged dataset derived offline from original captures, with
   source hashes, analysis parameters/version, required-column checks, and
   output hashes. A spot check confirms that the first run's 121 raw captures
   are still available in the original archive; availability and correctness
   for the complete replacement dataset have not yet been qualified.
3. Replay the enriched inputs and assess the unchanged numerical gates: at
   least five usable results, median error <=400 us, worst error <=700 us.
   Neither the coordinate probe nor this audit establishes those gates pass.

Do not substitute expected tail-start labels for observed geometry, enable
width-only landmarks merely to pass the test, lower thresholds, or restore the
silent skip. Extra CSVs with the same missing schema will not solve this failure.
No production analysis or calibration change is justified by this audit alone.

## Evidence audit

Fresh evidence is retained outside all worktrees, outside OS temporary storage:

`C:/Users/conar/.codex/visualizations/2026/10/16/01a1461e-ef4f-7131-a577-45ed406a81cb/parallel-worktrees-audit/`

The directory contains an evidence index with SHA-256 values, source-input
hashes, run metadata, pytest logs, JUnit reports, replay traces/probe source,
baseline comparison, controlled argument probes, and artifact inventory.
Raw recording copies remain external; they are not repository changes.

The original `qualification.md` is absent at its recorded temporary path.
All 32 discovered historical `labcraft-worktree-tests-*` directories lack
their top-level `run.json`, `junit.xml`, and `pytest.log`. Both old external
replay roots also lack all 175 manifest files. Remaining directories alone
are not qualification evidence.

The prior chat, **Investigate parallel worktrees**
(`01a08e03-6d58-7c80-9189-1b221007ee82`), still records these historical claims:

| Historical campaign at `027ed376` | Reported result per worktree |
| --- | --- |
| Default Python suite | 6,534 passed, 204 skipped |
| Concurrent functional/SIL selections | 165 passed |
| Concurrent firmware gate | 485 host tests and Debug build passed |

The chat summary is retained with attribution. These are historical reports,
not freshly verified raw campaign results. The old replay total of 25 passes
and one failure included two synthetic tests; the fresh marked-only selection
has 23 passes, one failure, and those two tests deselected.

The original archive's 175 selected files all matched the tracked manifest
before staging. New external copies were staged through the existing tool;
per-test integrity checks and post-audit checks preserve their hashes.
The manifest SHA-256 is
`c26ac257ade3aa0a9c3e4ae6e382e6495f1590255fca6dcbecb02fcafef7c507`.

## Fresh validation

All wrapper runs used this checkout's CPython 3.13.14 environment, offscreen
Qt, and unique external temporary/evidence roots. The setup check verified
pinned packages, dependency consistency, and required imports without changes.

| Check | Fresh result |
| --- | --- |
| `setup_worktree.ps1 -Python <absolute Python313 executable> -CheckOnly` | Passed |
| Worktree, historical-fixture, fake headless-build, Qt cleanup, manifest, legacy migration/reconstruction, association, and conversion tests | 91 passed in 9.79 s |
| Command queue, disconnect/reset, safe composition, composed SIL smoke, default tail replay selection | 90 passed, 9 historical tests skipped, in 25.76 s |
| Explicit historical selection across fit/tail/focus modules | 23 passed, 1 failed, 2 deselected, in 21.85 s |
| Original `main` dense-tail test with verified external inputs | Reproduced insufficient-result skip |
| Controlled configuration/debug argument probes | Both demonstrated output-isolation violations |

Qt deprecation warnings were recorded in the regression/SIL run. No threshold
or test assertion was changed. The 181 focused passes do not replace final
full-suite/concurrency qualification. No full suite or real firmware build was
repeated during this audit because concrete fixes remain outstanding. The three
fake headless-build tests exercised settings preservation and failure behavior.

## Firmware and retained worktrees

CppUTest is clean at the tracked commit
`79c066ef278263b25d7c4512ccddce81345050a3`. Both retained qualification worktrees
have only the expected tracked firmware binary modification. Their settings
match their committed files after CRLF normalization; no `local`, `logs`, or
`tools/__pycache__` directory is present in either qualification worktree.
The original checkout has pre-existing ignored output directories; they were
preserved and are not evidence of fresh-worktree isolation.

| Binary | SHA-256 | Embedded build date/time |
| --- | --- | --- |
| `main` | `1fec7c6c8d3c0022844695cdf51a860539bcfbda291bb18c12a99062c7a32577` | Aug 24 2026, 13:37:14 |
| Reviewed HEAD/current checkout | `13250f3dea364a6b493ecee5bacdfdd04526daa58b0f6871fd0bda19c1df631e` | Sep 10 2026, 18:40:42 |
| Worktree A and B build artifacts | `ffe70d3b53661023d072610c013dfdbe525fb0bb883150b0038a0e853eede109` | Sep 10 2026, 20:50:35 |

All are 367,968 bytes. Main differs from HEAD in ten bytes; A/B differ from HEAD
in five bytes. Masking only the build date/time strings makes each comparison
byte-identical. Runtime firmware source has no branch changes. The audit did
not rebuild, replace, reset, or flash any artifact. This establishes repository
artifact differences only, not installed firmware or production readiness.

## Original closeout requirements

1. Fix R1 and R2 in the supervisor and add refusal/subprocess regression tests.
2. Repair the offline dense-tail harness and qualify an adequate manifest-bound
   dataset, preserving its gates. Update the workflow guide's limitation with
   the actual cause and resolution.
3. On the final corrected candidate, refresh the required full-suite evidence
   in both independent worktrees and the overlapping functional/SIL campaign.
   Preserve existing qualification worktrees and artifacts; do not reset them
   to manufacture clean qualification inputs. Use fresh task-owned worktrees
   if clean inputs are required.
4. Complete the combined local firmware gate for final qualification:
   `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`.
   Follow the existing two-worktree concurrent-build acceptance plan, record
   artifact hashes, and retain source/configuration provenance. A build-tool
   implementation change requires the same-build tracked binary in its commit.
5. Retain logs/JUnit/metadata externally in durable storage, summarize their
   identities in the handoff, and review the final diff before publishing the
   feature branch/PR. This audit opens no PR and changes no Git refs.

Rollback for this audit is removal of this documentation addition. Future
tooling fixes should be separate coherent commits, reversible with ordinary
reverts. Preserve the archive, external evidence, and existing worktrees.
There is no machine-data migration, Pi deployment, physical qualification, or
installed-firmware rollback associated with the audit.

## Remediation record — 2026-10-16

Implementation commits:

- `2eabb36c`: reject configuration and debug output escapes, with real
  subprocess refusal coverage and documentation.
- `08e9a076`: repair replay coordinates and plateau anchoring, enforce the
  existing capture budget/compression, and derive/pin independent geometry.
- `aec12fa7`: make the documented staging CLI resolve its own repository
  imports from an unrelated working directory, with a regression test.

The final qualification source revision is
`aec12fa782497757396bd9cd5c44331dcf743d6f`. Production application/analysis code,
runtime firmware source, protocol, runtime dependency declarations, release
metadata, and the Pi workflow have no remediation changes. The numerical
dense-tail test's AST is identical to the reviewed `3328b768` version; its
minimum five usable results and 400/700 us error gates are unchanged.

### Resolution of R1 and R2

All separate/equals forms of `--config-file`, and bare/separate/equals forms
of `--debug`, fail before launching pytest. Subprocess tests verify rejection,
preservation of an existing log, and absence of plugin execution, debug logs,
and checkout caches. Selectors and supported opt-in arguments still pass.
The focused runner suite passed 35 tests.

### Resolution of R3

Replay validates a single explicit emergence reference, converts both scout
and backtrack requests at the feature-lookup boundary, and preserves absolute
times in missing-capture summaries. Synthetic tests cover zero and nonzero
emergence times, an inconsistent reference, missing capture timing, and a
successful scout/backtrack result at a 4,800 us origin.

The first geometry-enabled probe exposed a further existing harness omission:
it used the immediately preceding scout as the left endpoint even when that
scout was already collapsing. That probe produced 19 usable results, median
error 875 us and worst error 1,675 us, which fail the original gates. Its report
is retained as `repaired-replay-initial-results.json`.

The repaired helper uses the application's existing
`select_online_stream_tail_left_anchor` and
`compress_online_stream_tail_backtrack_plan` functions, and consumes the
existing hard budget for scout/backtrack captures. A dedicated nonzero-origin
regression verifies selection of the earlier plateau instead of a collapsed
scout. No production algorithm or policy was changed.

`tools/historical_geometry.py` derives geometry from all **3,146 original raw
captures across all 26 runs**, using the original recorded nozzle coordinates
and declared silhouette parameters. It does not select runs using expected
tail starts. The tracked geometry manifest pins parameters, dependency versions,
LF-normalized extraction/analyser source hashes, per-run source inventories,
output hashes, and a complete external provenance receipt. The original 175
input files are unchanged; 26 derived CSVs and one receipt make a **202-file**
external dataset. No raw archive or transient test report is committed.

Three candidate extractions produced identical geometry outputs; staging
through the documented CLI regenerated them and matched the pinned contract.
The complete source inventories were verified before and after extraction.
Tests exercise real synthetic pixels, source/output drift, path escape,
schema/capture/time mismatch, duplicate rows, missing/nonfinite geometry,
source preservation, and staging refusal before creating its destination.

Formal historical validation passed **24 tests, 7 deselected, in 73.39 s**.
The seven deselected tests are synthetic checks run separately. Dense replay
produced **20 captured results, median error 100 us, worst error 200 us**.
All 26 recordings remain in the dataset and are evaluated; six have no scout
landmark and remain outside the unchanged usable-result filter. This passes
the original statistical contract, not a claim that every recording resolves.

The initial synthetic-fixture failure and CLI import failure are also retained
in the development evidence. They were corrected before final qualification;
failed trials are not counted as passes.

### Fresh integration qualification

New managed worktrees C and D have distinct branches and independent pinned
CPython 3.13.14 environments. Their setup and firmware preflight passed.
They use the exact source revision above; old A/B worktrees and their retained
artifacts are preserved. Full suites ran sequentially; functional/SIL and
firmware campaigns then ran concurrently across C/D. Timing limits remain unchanged.

| Campaign | Current result |
| --- | --- |
| Focused geometry/fixture/synthetic replay checks after CLI fix | 35 passed, 9 historical tests deselected, 7.18 s |
| Full default suite C, short temporary base | 6,566 passed, 204 skipped, 845.49 s; exit 0 |
| Full default suite D, short temporary base | 6,566 passed, 204 skipped, 858.28 s; exit 0 |
| Overlapping functional/SIL C | 158 passed, 9 skipped, 24.25 s; exit 0 |
| Overlapping functional/SIL D | 158 passed, 9 skipped, 23.94 s; exit 0 |
| Combined firmware gate C | 485 host tests and Debug target build passed; exit 0, 56.08 s |
| Combined firmware gate D | 485 host tests and Debug target build passed; exit 0, 56.39 s |

The mandatory local firmware command remains:
`powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`.
No flashing, Pi launch, physical device access, installed-firmware assertion,
or machine-data mutation is part of this qualification.

The external evidence directory above contains the full source/dataset record,
preservation checks, setup logs, retained failed probes, and fresh runner
metadata/JUnit/logs. `final-qualification.json` binds the exact source revision,
test reports, worktrees, build intervals and selected artifact. This document
seals qualification before feature-branch PR publication; it does not authorize
a merge, release, deployment, or hardware operation.

The first full C trial completed with **6,535 passed, 31 failed, 204 skipped**
in 840.17 s. All failures were pushes to test-owned local bare repositories in
four update/rollback fixture modules. A controlled reproduction captured
`Filename too long` while writing Git quarantine objects. This was caused by
the audit's deep evidence directory being used as the temporary base, not by
a release-operation blocker or a changed application behavior. That run and
the reproduction are retained. Qualification now uses a short OS temporary
base and archives completed reports byte-for-byte in durable external storage.
No Git setting, assertion, or safety check is bypassed.
The affected four modules then passed **192 tests in 54.93 s** under the short
base. The complete repeated C run passed without source or test changes. Its
durable archive is `archives/full-c2/`, including an unmodified JUnit report
with SHA-256 `9198a2d74235d16bd3f1fba42f3bff1998e1529fcf06613218269f80e217e3b6`.
C remained clean afterward with no checkout-local `local`, `logs`, source
bytecode cache, pytest cache, or debug log.

### Final artifact, applicability, and rollback

The functional/SIL runs overlapped by 23.75 s, and the firmware gates overlapped
by 56.09 s. Both builds produced the same 367,968-byte artifact:
`ff40b46ff1a3273d6996bfafda04fea0f5971feac3563eef0468a900fc08fb45`,
embedding `Oct 16 2026 13:41:34`. It matches each worktree's actual Debug output.
Against the preceding tracked artifact, only the embedded build date/time
strings differ. The selected C artifact is included with this final validation
record; no runtime source, protocol, or build configuration changes accompany it.
The existing three target compiler warnings are retained in the build logs.

C/D settings match their committed versions after line-ending normalization.
CppUTest remains clean at the pinned gitlink; each qualification worktree has
only its retained rebuilt binary modification. Neither has checkout-local logs,
configuration, source bytecode, pytest cache, or debug output. A/B remain
untouched. No Pi operation, installed-firmware change, or machine-data write
occurred.

The final follow-up commit contains only this audit, the short-temporary-path
documentation, and the same-source rebuilt artifact. Python sources/tests,
fixture contracts, dependency declarations, and firmware source/configuration
remain identical to the fully tested `aec12fa7` revision; the recorded gates
therefore apply without another runtime rerun for documentation/build strings.

Durable JUnit identities:

| Campaign | JUnit SHA-256 |
| --- | --- |
| Full C | `9198a2d74235d16bd3f1fba42f3bff1998e1529fcf06613218269f80e217e3b6` |
| Full D | `9493b7efcf308f5851c099c837b03e3ba7c50e18eb9b6b9ec37ce73b01f707f6` |
| Concurrent C | `f0c4024506bdc188964809ceb9e07c737eecffe5193a498c87c13e6723f129ea` |
| Concurrent D | `ed34b4ae9fb417b8b61201362d53f67f42139004a0db07bb3a8d4ccaf0fa306b` |

The `archives/` receipts retain original run locations and hashes of the
unmodified metadata/log/JUnit copies. `evidence-index.json` indexes retained
evidence; raw recordings and transient reports stay out of Git.
Rollback uses ordinary coherent reverts of the remediation commits and final
artifact/documentation commit. Preserve old and new external datasets and
qualification evidence. No machine-data migration or installed-firmware
rollback is needed. Review and merge remain separate from this qualification.
