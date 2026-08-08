# Milestone 8 Slice 7 — Manual Raspberry Pi Suite Integration

Status: complete (2026-08-07)
(2026-08-07)

Baseline: clean commit `63af6cab8414a32e7c1a3dd5b7b7808ad496ef7f`.

## Goal and call path

Expose only the registered `pi_primary` and `pi_stress` suites through the
existing isolated suite runner and the established fail-closed Raspberry Pi SIL
boundary:

`run_pi_virtual_workflow.ps1 -Suite` → SSH → Pi preflight and traced 96-well
proof → Bubblewrap private `/dev`/network namespace → suite selection → fresh
Python child per selected scenario → QTest → View → Controller → Model →
SimulatedMachine → aggregate → validated artifact bundle and retrieval.

Pi capability selectors remain planning-only so a capability cannot launch the
long stress scenario indirectly. `pi_stress` remains explicitly opt-in and is
not part of Slice 7 qualification.

## Contract

- `labcraft.virtual_workflow_aggregate` remains schema v1. Its platform may be
  `windows_sil` or `pi_sil`; Pi aggregates add bounded `run.pi_safety` identity.
- Every Pi child receives one validated preflight/proof pair and must report the
  same source, Qt platform, proof, trace, sandbox protections, workload, and
  seed.
- The Windows wrapper adds mutually exclusive legacy `-Scenario` and new
  `-Suite pi_primary|pi_stress` modes. `-ReplaySuite` executes the exact,
  strictly allowlisted replay from the first aggregate.
- `labcraft.pi_sil_artifact_bundle` v2 contains one or two suite aggregates and
  their shared safety evidence. Existing report-set bundle v1 remains readable.
- New suite evidence is retained remotely by default. Cleanup is never invoked
  automatically by suite mode.
- Exit codes remain 0 for pass/warning, 2 for a completed failing aggregate,
  and 3 for orchestration/evidence failure.

## Implementation and validation

1. Generalize the aggregate runner and CLI without adding another runner
   family or changing Windows aggregate behavior.
2. Extend Pi artifact transport with aggregate-v2 bundling, safe extraction,
   and strictly validated replay.
3. Add suite mode to both remote wrappers while retaining legacy scenario,
   report-set, baseline, and comparison behavior.
4. Cover selection, platform identity, Pi evidence mismatch, fresh children,
   replay allowlisting, v1/v2 bundles, path/hash/symlink/overwrite failures,
   dry-run behavior, Windows compatibility, and Pi coverage ingestion.
5. Run only focused unit/system tests and both wrapper dry runs. The complete
   pytest suite remains deferred to Milestone 8 Slice 8.
6. Pause after local qualification. Remote access requires separate operator
   authorization and exact-source confirmation. Slice 7 closes only after an
   authorized `pi_primary` run and exact replay both pass and their single v2
   bundle validates locally.

## Exclusions, risks, and rollback

No production View, Controller, Model, simulator, tracked fixture, manifest,
protocol, firmware, scheduler, Pi configuration, physical hardware, baseline,
matrix, or exploration behavior changes.

Primary risks are accidental stress selection, sandbox/evidence identity drift,
unsafe replay, duplicate retrieval paths, and source mismatch. They are bounded
by suite allowlisting, per-child proof checks, replay-token validation, a single
multi-aggregate bundle, fail-closed path/hash validation, and an explicit remote
authorization boundary.

Rollback restores Windows-only aggregate execution and removes suite replay and
bundle-v2 support. Legacy direct Pi scenario collection and bundle v1 remain
usable. No persisted-data migration, firmware rollback, Pi reconfiguration, or
hardware action is required.

## Local implementation checkpoint

Focused unit/contract validation passed 81 tests. Focused Pi-lane and real
Windows suite system validation passed 14 tests. Python compilation and
`git diff --check` passed; the checkout's expected LF-to-CRLF notices remain.
Both `pi_primary -ReplaySuite -DryRun` and `pi_stress -DryRun` printed the
expected preflight, proof, collect, replay (primary only), aggregate-v2 bundle,
and retrieval commands without contacting a Pi or invoking cleanup. The local
host has no `bash` executable, so shell syntax is covered by the static Pi-lane
contract test and must also be checked by the Pi before remote qualification.

No full pytest suite or Pi stress, firmware, protocol, or physical-hardware
operation was performed during local qualification.

## Authorized Pi qualification

The operator authorized `labcraft@192.168.0.33`. The clean Pi checkout and
local branch were aligned at `a7fd7b5a844fb88ce1c2fd2fdbe98bfe783beeb8`
after two bounded orchestration corrections recorded separately: composed
Linux ARM proof-audit classification and virtual-environment executable
preservation.

The final `pi_primary` aggregate and its exact allowlisted replay both passed
96/96 completions. Both used source-tree SHA-256
`fb2875ac4039fc83e1d7049da3d221c3a6534bb28145a138a1ffb94b343789d1`,
proof SHA-256
`04bd01c4a0d7e77f7a36e9709a493ee576eb00983788f95be39a5c3e8d39cfa7`,
and trace SHA-256
`ff00486d407e0653dd0b07b353dd7caa91686682885e9146b6a96858c8502059`.
The aggregate SHA-256 values are
`25ec6c8389564041531e354892dbbb165db87bf453f189b4b0a70ffc995f5060`
and `16799d1e19973d6a23e3b30ba4c81f500cb118993e81b663f3204f5dd5cd486b`.
The locally validated two-aggregate bundle SHA-256 is
`ecb9fccc83017583eb2660f93db6fb89ffa2794aac864080505e4190d3927e09`.
Remote evidence remains retained; no cleanup was invoked. See the Slice 7
completion record for exact paths and inspection results.
