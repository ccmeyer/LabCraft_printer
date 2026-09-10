# Dense plate refresh: rc.15 integration and release preparation

## Scope and reviewed application

- Application commit: `dfc32e2d317a4cbefa20238724a2c7620686e826`.
- Integration base: `dceed5b01797fbe3a1aa6f6a92c1c811cbac2436` (rc.14 main).
- Preparation branch: `codex/fix-plate-refresh-performance`.
- Intended release: `v1.3.0-rc.15`, schema v2, following rc.14.

The rc.12 concentration lookup calculated the entire execution plan for each
well in a full plate refresh. A 384-well redraw therefore recalculated 147,456
well records, with each record processing its allocations and factors. An
older head-pickup handler could request two full refreshes.

The fix adds a refresh-local model lookup and consumes its values in the plate
view. It preserves the existing authoritative concentration calculation and
legacy fallback. No persistent cache needs invalidation. Programmatic pickup
selection blocks its redundant selection signal and explicitly refreshes once.
Disabled tooltips skip concentration lookup; named-well updates remain local
to the existing label.

The relevant path is plate UI -> model reporting. Pickup enters that path from
machine status -> command completion -> controller pickup handler -> rack
signal -> plate view. No controller, transport, firmware, command format, or
dispatch safety guard changed. No nested event processing or worker-thread
access to widgets was introduced.

## Review and automated validation

Maintainer-agent review of the four application/test files found no actionable
regression. This is not an independent reviewer sign-off. Tests cover fresh
values after a plan revision/calibration, missing stock/well, zero projected
volume, empty requests, legacy/no-plan lookup, unassigned wells, read-only
display heads, failed snapshot calculation, and real QComboBox pickup signals.

- Application-focused validation: 166 tests passed, then 14 regression tests
  passed after two additional cases (168 distinct affected tests in total).
- Full Windows Python suite: **6512 passed, 180 skipped, 637 warnings**, zero
  failures/errors, in 874.24 seconds. This run included the rc.15 metadata and
  all release-metadata, updater, bundle and execution-data compatibility tests.
- Release metadata validator passed; strict JSON parsing (including duplicate
  key and nonfinite-number rejection) passed for all 38 release files.
- `git diff --check` passed. The firmware tree/artifact, dependency declarations,
  execution-data compatibility declaration and `releases/latest.json` have no
  diff from the integration base.
- External preparation evidence:
  `C:\Users\conar\AppData\Local\Temp\labcraft-rc15-prep-3911d58e8b294516b3883798d7a0deb1`.
  `full-suite.log` records the full run; `supporting-evidence/` retains copies of
  the benchmark, attended launch, restoration and final status reports with a
  SHA-256 inventory. Tag-free source/review artifacts and their exact commit
  binding are recorded in that directory's `readiness.json` after commit.

Use the repository Windows interpreter and a unique OS temporary `--basetemp`
outside all worktrees. Full-suite runs must be allowed at least 15 minutes.
Transient logs and reports remain external, not committed in this document.

## Measured display behavior

The user's `04_dense_384_10_design.csv` and `04_dense_384_10_stocks.csv` supplied
the 384-well/10-stock workload. The isolated Windows probe uses real Qt plate
methods with in-memory model records and benchmark-only assumptions of 5000 nL
final volume, 1000 nL printed volume and 10 nL droplets. It does not run the
import optimizer or reproduce the operator's saved experiment metadata.

| Display operation | Original callback median | Fixed callback median |
| --- | ---: | ---: |
| Full refresh | 953 ms | 15 ms |
| Stock selection | 933 ms | 15 ms |
| Pickup changes stock | 1889 ms | 15 ms |
| Experiment-loaded display callback | 919 ms | 15 ms |

Three runs per operation; all 3840 well/stock stylesheet and tooltip comparisons
matched. The original profile attributed 95% of callback time to whole-plan
concentration calculation. These are Windows display-path measurements, not Pi
timings or complete experiment-load measurements. The pre-existing rc.13
optimizer timing limitation remains out of scope. Long Pi memory qualification
was omitted at the operator's explicit request; no new memory claim is made.

## Attended Pi qualification and recovery

Operator `Conary-Codex` supplied fresh attended confirmation for this campaign.
The exact pushed application revision was synced into the clean detached
development worktree. Status, sync, runtime validation and hardware preflight
passed with the persisted isolated LC-001 development-store binding.

The operator reported that the test ran well and the fix addressed the issue,
then closed the app. Specific connected-motion, dispensing, or long-running
memory scenarios were not recorded and are not claimed as qualified.

External evidence for the 2026-09-10 campaign:

- Windows evidence root:
  `C:\Users\conar\AppData\Local\Temp\labcraft-plate-pi-dfc32e2d`.
- Hardware report: `hardware/20260910T162948199579Z_eff2b13d-c3c9-4516-aee3-c02fd62ceed8/roundtrip.json`.
- Remote hardware session: `2ae2237f-8904-408c-84e0-0ede2c107c77`.
- Restoration report: `firmware/20260910T163319809309Z_5530297e-cd5a-4109-9bd4-dcf04e98f99f/roundtrip.json`.
- Remote firmware session: `be2c5586-180b-4da4-b0c8-134660414504`.
- Final status: `status/20260910T163420272432Z_dfc32e2d317a/status.json`.

The app exited zero with `normal_exit`; protected pre/post hashes matched.
Exact released restoration passed and validated all 30 SAFE inventory results,
including all required non-actuating/skipped gates. Final durable firmware
revision 194 was `released`, `production_ready=true`; no related processes
remained. Production stayed clean at `dceed5b0`; the development checkout stayed
clean and detached at `dfc32e2d`. The two retained worktrees were preserved.

The durable known-good firmware anchor is rc.8, commit
`f611604346f1a5e64d8b5a1ecb115492a8960dc6`, with artifact SHA-256
`1fec7c6c8d3c0022844695cdf51a860539bcfbda291bb18c12a99062c7a32577`.
Its firmware bytes are identical to rc.14 and the fix. This is the existing
firmware recovery binding, not an application downgrade. The wrapper accepts
the anchor's schema-v1 firmware manifest; rc.14's schema-v2 application-only
manifest is not a firmware anchor.

## Release boundaries and remaining publication steps

`requires_firmware` and `rollback_version` remain null. No firmware, dependency,
machine-data schema, execution-data compatibility or legacy bridge change is
included. The stable route and exact rc.11 legacy pointer in `latest.json` stay
unchanged; modern RC discovery depends on publication of the future rc.15 tag.

Before publication, approve and integrate the reviewed branch into main, bind
the release metadata to the exact accepted revision, create the new rc.15 tag,
run release validation with `--check-tags`, and generate/verify the release-aware
bundle. A merge that changes application code requires renewed affected
validation. Until tag authority is granted, only a tag-free source archive and
Git review bundle may be prepared externally; neither is an installable update.

Code rollback before deployment is a revert of the display optimization. For
deployed machines, do not advertise an unqualified historical app rollback:
preserve version-4 execution history and use protected current-version or a
qualified compatible-bundle recovery path. Do not edit machine-data pointers,
firmware-state records, or protected production code manually.
