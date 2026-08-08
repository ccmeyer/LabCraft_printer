# Milestone 9 Slice 9.6 Completion Record

Status: complete (2026-08-08)

## Outcome

Milestone 9 is complete. The source-current eight-case calibration
requantization catalog, preserved eight-case mixed-mode catalog, lifecycle
suite, 96-well host regression, visible count boundaries, exact replays, and
default Python suite all pass.

Qualification was restarted from the beginning after the independently
reviewed cross-session evidence correction in commit `792a7b0`. All accepted
aggregate children identify full commit
`792a7b06a4bb8088319f522622dfd8a9e06dbd3b` and source-tree SHA-256
`763666af01fb4ddff53865af1c2628dcea068e35051487541f4742ccbcd7bdc1`.
The implementation-plan document was the only untracked file and is excluded
from that execution-input fingerprint.

No production MVC, simulator behavior, firmware, protocol, tracked fixture,
report-v1, matrix-plan, aggregate-schema, or catalog behavior changed during
closeout.

## Frozen contracts

- `calibration_requantization_v1`: eight cases, catalog SHA-256
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`.
- `mixed_mode_calibration_v1`: eight cases, catalog SHA-256
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.
- Report-v1 and matrix plan/aggregate schemas remain version 1.

Both deterministic dry-run plans retained the expected eight-case order and
catalog identity before execution.

## Complete aggregate qualification

| Qualification | Result | Aggregate | SHA-256 |
| --- | --- | --- | --- |
| requantization matrix | 8/8 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T192137967177Z_28123f78-6f9/aggregate.json` | `dbe0b76eb7e4c3665ce54a7f1e7ac789db0d1c45b012cd88eb97ab3eb18ebd9c` |
| requantization exact replay | 8/8 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T192239012758Z_758f88dc-0ec/aggregate.json` | `c3e0c12206687ebc07766679a3c29a6b3621da86fbfd4e976f2fec90cdb44724` |
| mixed-mode matrix | 8/8 pass | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T192339735376Z_77ec949f-923/aggregate.json` | `ac912cd0bfefa9b861253590f0aa4504d9db7009cf3211c934ddd8832cc45743` |
| mixed-mode exact replay | 8/8 pass | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T192448326808Z_f277aea9-54a/aggregate.json` | `d2be4d447c85aecac9cfbff6132f27fb529951600f53594883d517adca69c17b` |
| lifecycle suite | 8/8 pass | `verification_reports/suites/lifecycle/20260808T192709333121Z_b7557bb7-31a/aggregate.json` | `32c9bb9126002fb56f70bce4d3443b5b0c7fde5219ca6f187dc8e5368c1e39a6` |
| lifecycle exact replay | 8/8 pass | `verification_reports/suites/lifecycle/20260808T192804476634Z_42afb291-7cd/aggregate.json` | `543cdfba9bb03da9faf2833fffa8c55f90ca85123fa64cda3814a402fb977b4a` |
| host regression | 1/1 pass; 96 wells | `verification_reports/suites/host_regression/20260808T192858912938Z_f0154276-a8e/aggregate.json` | `d024f882d492e316d4297eb3b9f77a63565cf8f3126215f53337e3aa9eff9f9b` |
| host-regression exact replay | 1/1 pass; 96 wells | `verification_reports/suites/host_regression/20260808T192914732059Z_962e2fe2-591/aggregate.json` | `f30655043c6557ed154fddb2e47ab134e4b47674462443c37fab3e7a965d03d0` |

Every aggregate child returned zero, avoided timeout/termination, produced
exactly one matching passing report, and agreed with the parent outcome. All
children share the same corrected source identity.

## Visible Windows qualification

Both boundary cases used `QT_QPA_PLATFORM=windows`, `--visible`, 20× speed,
and a 120-second watchdog.

| Case | Result | Report | SHA-256 |
| --- | --- | --- | --- |
| `droplet_volume_increase_10_to_9` | pass; 24/24, 9 drops/well | `verification_reports/matrices/calibration_requantization_v1/20260808T192605448252Z_composed/report.json` | `a38b28afeae5ddac13c6c7107490e76ea477c2d7b3cbbe6b18b81f0242a76751` |
| increase exact replay | pass; 24/24, 9 drops/well | `verification_reports/matrices/calibration_requantization_v1/20260808T192619386749Z_composed/report.json` | `9bb8c8723c762ae9b37eaf29a08fe11aa68b97bb2f5a23a224ca2fdb179fb5c9` |
| `droplet_volume_decrease_10_to_11` | pass; 24/24, 11 drops/well | `verification_reports/matrices/calibration_requantization_v1/20260808T192634732480Z_composed/report.json` | `4c690ffd221bfb74794c2f474d44109ce984336c082421184dcdb247b972ae01` |
| decrease exact replay | pass; 24/24, 11 drops/well | `verification_reports/matrices/calibration_requantization_v1/20260808T192648861369Z_composed/report.json` | `bc2e17b2cd8ebe80503f933c4197d063164f4ea528acdaf24231f4316a217757` |

All four reports pass `execution.dispense_counts_reconciled` with zero
workflow errors or unexpected dialogs.

## Representative evidence inspection

The complete requantization replay proves:

- all seven positive execution cases pass exact catalog-owned reconciliation;
- cases 1-3 complete 24 intents, case 4 completes 36, cases 5-6 complete 48,
  and case 8 completes 48;
- `stream_to_droplet_40_to_10_8` passes
  `execution.completed_terminal_reload_exact`; representative report SHA-256
  `7df197964eb54bc3a7f418fca21c1f57f2c10240846c6949faecbcc0671f737e`;
- `zero_fill_missing_fill_rejected` passes all ten safeguard checks with a
  byte-identical authoritative boundary and zero begins, attachments,
  completions, or simulator dispenses; representative report SHA-256
  `5ea7d1f3310eb27d3b5188396f13f380748cf8a28ec7fef06c8cfb05ceda0757`;
- `two_reagent_second_1_to_2_isolated` passes all twelve isolation checks,
  completes 48 intents, and commands exactly 72 droplets; representative
  report SHA-256
  `4043afc4728b6416a1fe0197dce40070a40a18c9d35b543c687ee00683ad4456`.

The mixed-mode replay preserves all positive and safe-block outcomes. Its
zero-completion unclear-refuel representative passes the expected matrix
outcome and manual-refuel assertions; report SHA-256
`e76f2016da9d7637e304b305e809d922112ce13eb6f27dbee763b05c5cc6e4c4`.

The lifecycle replay passes all eight scenarios, including source-current
authoritative reload/resume with two application sessions and exact no-replay
reconciliation; representative report SHA-256
`0029d9dba9630dba5c56793a80ebe231e1c8ea12fed7a60602cf0cb066e8e380`.
The host-regression replay completes its 96-well workload; representative
report SHA-256
`1a41d9f6fe17a3b7add568f570061e319c11f2bd00bffe2942314238bce0074a`.

No accepted representative contains prohibited hardware access, queue
starvation, timeout, ambiguous report selection, unexpected dialog, workflow
error, or unsafe teardown.

## Complete Python suite

The default suite ran exactly once with external temporary root
`C:\Users\conar\AppData\Local\Temp\LabCraft\pytest-m9-s96-20260808122936`:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp C:\Users\conar\AppData\Local\Temp\LabCraft\pytest-m9-s96-20260808122936
```

Result: `4123 passed, 78 skipped, 389 warnings in 243.24s`.

Warnings are existing Qt deprecation warnings. The unrelated opt-in analysis
pipeline was not enabled.

## Scope, risk, and rollback

This milestone proves application SIL behavior through the real Qt,
Controller, Model, durable-intent, and hardware-isolated simulator paths. It
does not claim firmware, serial protocol, physical motion, pressure response,
droplet quality, camera, balance, or real printer-head coverage.

Host stress, Pi qualification, firmware checks, release operations, and
physical hardware were not run. Refill-required/resume remains deferred while
authoritative volume tracking is disabled; existing soft-stop and reload
lifecycle checks do not change that scope.

Rollback reverts the Slice 9.6 documentation closeout commit. The independently
useful Slices 9.1-9.5 and correction commit `792a7b0` remain intact, and
retained historical evidence requires no deletion or migration.
