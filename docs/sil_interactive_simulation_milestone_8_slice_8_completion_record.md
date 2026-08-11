# Milestone 8 Slice 8 Completion Record

Status: complete (2026-08-07)

## Scope and source identity

Slice 8 completed the operator runbook, final evidence refresh, representative
evidence audit, focused validation, complete default Python suite, and fresh
authorized Raspberry Pi primary qualification. It added no runner interface,
production MVC behavior, simulator behavior, fixture, manifest, protocol,
firmware, Pi configuration, or hardware behavior.

The final Windows execution-input fingerprint contains 888 files and is
`bd2fb283c348f1bd8585079f2287f180223bfea4b058448899e6c138a2ace5d9`.
The bounded page-driver corrections and Slice 8 documentation were committed
as `1e7efa86f95461a2865c075c717f06af06ae28cd` before Pi deployment.

The final Pi execution-input fingerprint contains 888 files and is
`8d1dc93d9a9fdd60c1fbba8bfba890d29ee7c5250b36abbc20f48fd8952bb108`.
The different Windows/Linux hashes are retained platform-specific source-tree
identities; both reports identify the same tracked commit.

## Windows workflow evidence

| Gate | Result | Aggregate path | SHA-256 |
|---|---|---|---|
| standard | 1/1 pass | `verification_reports/suites/standard/20260808T020751830138Z_2294a513-ef4/aggregate.json` | `6957582c844ad7678fda32a1402aa28b4c02caf70824f2e138a054df4984c7e8` |
| lifecycle | 8/8 pass | `verification_reports/suites/lifecycle/20260808T020801568267Z_80d1b8a0-4ac/aggregate.json` | `524e09a4304a50bb1e37acd741403881a72c7c8d816061ba18c8002437a47ac2` |
| matrix | 8/8 pass | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T020853898332Z_e8e0fcc7-d8a/aggregate.json` | `4ad41a4c02ec709c13c4b32a745c7a31923968c4635c7650151daad6dc3cde8e` |
| exploration | 10/10 pass | `verification_reports/exploration/editor_prepared_guard_v1/20260808T021000616940Z_07ecfa29-f23/aggregate.json` | `cf272de4ec5bd1e57a7c3e1db78ef27e100052f2ece0028c8d3e31db73ad9731` |
| host regression | 96/96 pass | `verification_reports/suites/host_regression/20260808T021046458346Z_a0ce4c94-0b9/aggregate.json` | `ba0945acf393bff69528c054e9524fc81bcd01d2b1371cd78e2c1248c0c20921` |
| host stress | 3,840/3,840 and ten head lifecycles; informational warning | `verification_reports/suites/host_stress/20260808T021103311974Z_01cb0966-74b/aggregate.json` | `c3a06fdc74bc76de57b6d9feda6bacf6fc4a7b93f2354fb8e72e419057afd748` |
| visible standard | 1/1 pass | `verification_reports/suites/standard/20260808T021828253242Z_5908b3e2-f50/aggregate.json` | `57b671b51142f71f73fa1c158f874839e9282f24bbc474d9fbf7e823f743e3f4` |
| visible exact replay | 1/1 pass | `verification_reports/suites/standard/20260808T021842873690Z_c8ef2397-679/aggregate.json` | `e1be36825b6bca7865b6759e489d691c9abcfe0b88088038c94a5ca324db5914` |

Stress recorded zero failed actions/assertions, zero starvation, zero
unexpected dialogs, a drained queue, and clean teardown. Its event-loop,
pressure-render, and RSS reasons remain informational rather than failed hard
gates.

Coverage generation and its exact replay each reported 21 passing Windows
capabilities with zero failed, stale, or missing Windows entries. Their hashes
are `a9d28cb54f2adf95322c9934f87766ccae1f73464d5bc7124f562718322f5723`
and `35b8233500fe03ca4e73493d51cae7f4627be21400077aa0b83822dc17b24532`.
The three Pi-only layers remained incomplete in that intentionally
Windows-only evaluation and were validated separately below.

Representative screenshots and ledgers were inspected for visible standard,
mixed droplet/stream calibration and manual refuel, matrix safe blocking,
illegal exploration recovery, 96-well regression, and 384x10 rack exchange
and completion.

## Automated validation

- Focused unit/contract validation: 189 passed.
- Focused real-process system validation: 18 passed.
- Complete default suite: 4,080 passed, 72 intentionally skipped, 389
  warnings, zero failures in 218.64 seconds.
- The complete suite used a unique basetemp beneath
  `C:\Users\conar\AppData\Local\Temp\LabCraft`; an in-repository basetemp is
  correctly rejected by the SIL session repository-overlap guard.

## Fresh Raspberry Pi qualification

The operator authorized deployment and execution against
`labcraft@192.168.0.33`. The Pi's existing
`/home/labcraft/LabCraft_printer` checkout remained on
`feature/balance_integration` and was not switched or modified. Commit
`1e7efa86f95461a2865c075c717f06af06ae28cd` was deployed to the separate,
clean, detached worktree
`/home/labcraft/LabCraft_printer-m8s8-sil-1e7efa8`. Its ignored `env/`
facade references the existing repository virtual environment; no packages or
Pi configuration were changed.

The first wrapper attempt stopped fail-closed during preflight because the
initial environment facade did not expose the virtual environment metadata and
therefore could not import PySide6. No proof, workflow child, replay, bundle,
hardware access, or cleanup ran. Completing the ignored facade restored the
existing `PySide6 6.7.1` environment, and a standalone safety preflight passed
before the authorized suite was restarted. No tracked source changed.

The restarted command was:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\run_pi_virtual_workflow.ps1 `
  -PiHost 192.168.0.33 `
  -PiUser labcraft `
  -RemoteRepo /home/labcraft/LabCraft_printer-m8s8-sil-1e7efa8 `
  -Suite pi_primary `
  -Seed 1 `
  -SpeedMultiplier 100 `
  -ReplaySuite
```

The wrapper completed the primary and exact allowlisted replay in 78.5
seconds. Both aggregates are `pass`, each contains one fresh child with 96/96
completions, process/report agreement, no timeout/termination, zero unexpected
dialogs/errors, and clean teardown:

| Run | Parent/child PID | Aggregate path | SHA-256 |
|---|---|---|---|
| primary | 2 / 3 | `verification_reports/virtual_workflows/pi-sil/pi_primary/20260808T023359006532Z_21a5f2b5-804/aggregate.json` | `c884a480054f31fff6d435e5cb0aae7efd9223d6525bff342ca9c2af1baa25f8` |
| exact replay | 3 / 4 | `verification_reports/virtual_workflows/pi-sil/pi_primary/20260808T023420832299Z_d5b95258-f29/aggregate.json` | `228fd7aad64d28d03a93511cdd37791825737e70ccfddba11261c7c3293172a6` |

Both aggregates bind to Raspberry Pi 5, offscreen Qt, Bubblewrap private
`/dev`, no network namespace, read-only root, clean source, and the same safety
evidence:

- preflight SHA-256:
  `5287ed38afd1e2f0e395897a251876290376144e1414267ba9d94b1a8617e8e0`;
- hardware proof SHA-256:
  `1c1ee0533332f29e5bd44b31d7818880970fdea3883c9ae93193e9eaf357e19c`;
- hardware access trace SHA-256:
  `fd1f93f95c072769e84326558a8a3b959106f2e33c761f1a1206197a33f88b6a`.

The locally retrieved 53-member bundle is
`verification_reports/virtual_workflows/pi-pulls/pi-suite-20260808T023327Z.zip`.
Its SHA-256 is
`785bcbbc8e6d6e34eff13c11fd7fcc4f20c1afa54b349d53810e89deae7b8ff0`.
The wrapper validated the archive sidecar, every member hash and size, both
aggregates, child reports, and shared proof/trace linkage before returning
success.

All remote evidence and the isolated deployed worktree remain retained. No
cleanup was invoked, `pi_stress` was not selected, and no physical hardware
claim is made.

## Risks, limitations, and rollback

The SIL evidence qualifies application workflows and fail-closed hardware
isolation; it does not qualify physical droplet accuracy, motion, pressure,
firmware, or protocol behavior. The stress warnings remain informational and
should be revisited only if their thresholds become acceptance gates.

Rollback reverts the Slice 8 documentation and the two bounded reusable
page-driver corrections in commit `1e7efa86`. Generated local and remote
evidence is deliberately retained and becomes historical. Do not delete the
Pi worktree or evidence without a separate, manifest-bounded cleanup review.
