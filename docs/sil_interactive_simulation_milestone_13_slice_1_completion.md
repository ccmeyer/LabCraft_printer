# Milestone 13 Slice 13.1 Completion Record

Status: `complete`

Budget note: Slice 13.3 subsequently qualified the illegal/recovery corpus and
versioned the action cap from the Slice 13.2 legal-only value of 64 to 80 per
sequence (480 per campaign). The normalized sequences and their hashes did not
change; current catalog/campaign hashes are recorded in the Slice 13.3
completion record.

Completed: 2026-08-09

## Outcome

Slice 13.1 added the execution-disabled, separately versioned
`design_calibration_lifecycle_v1` planning contract. It freezes a 12-state
semantic model, 26-operation oracle-admission ledger, six reviewed frozen
sequences, two explicit seed tiers, durable fixture identities, all numeric
budgets, canonical hashes, additive campaign discovery, and v2 dry-run plans.
No generated fixture was materialized, no Qt or simulator path ran, and no
authoritative experiment state or user data was opened or changed.

The Milestone 8 `editor_prepared_guard_v1` generator remains unchanged. Its
seeds, ten sequences, normalized plans, fixtures, schema v1 execution path,
and catalog SHA-256 remain compatible. The only shared-module change is
additive dispatch/discovery for the new campaign.

## Frozen contract

Slice 13.2's entrance review replaced the provisional maximum-valued workload
projection (`3/12/120`) with the exact reviewed compact fixture projection
(`2/8/44`). Qualification then replaced the provisional 48-row action cap with
the measured strict 64-row cap after the reusable real-Qt lifecycle proved it
requires 56 pre-teardown rows. These fail-closed corrections preceded the first
qualifying Milestone 13 pass. The six normalized sequence, frozen-set, fixture,
catalog, and campaign hashes below are the resulting reviewed identities; the
state, operation, and oracle-ledger hashes did not change.

- state-model SHA-256:
  `71e7ca63e564a3a841bb95f9bf157fb3d491dbf2e4b80cdf027c956dab884cc8`;
- operation-catalog SHA-256:
  `9445809961d52f0a92cd004d374fbc38b2fc20c688ef337ff0d90ba09f8ca88d`;
- oracle-ledger SHA-256:
  `7ca216df7d28fd8c01e94efebb5c51ba0db249a8fde3dfa6385de5381d77351e`;
- ordered frozen-set SHA-256:
  `1b4a2b4f9b56295428f9b2565ba048960ba0957b282e1c3d7296e57908a14a4e`;
- compact fixture-projection SHA-256:
  `5687adab7dabbe7d94112fb18b2c8eb8e8740b655c47b2352010c635cf028043`;
- catalog SHA-256:
  `995d29b97ba051a1184d6633353a74feff6a6d2390b149e25d776f83f989209d`;
- campaign SHA-256:
  `2e9806130983df06764cf4008eb21f6d1ea3954a4525736e185612929e8f1ce0`.

The ordered frozen sequence hashes for seeds 13, 29, 47, 83, 131, and 197
are respectively:

```text
992abf215250df32bbe9a23d47aba3b26faab96964082d66a29a4dd14f0d1fdd
d07f1d44869e0849cfd652e09c6b2adc1c6bfd05f70512a166deb823113ee6f4
776c9e7670a5022954cefd753a0aad3d059fe4c04738a1ea926e9177cd9564f7
065a1d08c1de18eaf271faccee302e33cd3b58c70786e734c2c6ae5ee1d9c3e4
38963d167b14115254282dc81bec8eddb05c0fb845d1e9790f2c5be6f96ce9e5
faf4de186bbf103db5a46ec62b8dba60ad53771bfcd46907d3eda827618306fe
```

All 26 admitted operations are covered across the frozen set. Every rejected
operation retains the same modeled base state and requires its literal M12
typed rejection plus shared no-mutation/no-dispatch oracle. The complete state
denominator is also reached. Seed 47 is the largest normalized sequence at 16
operations and 46 projected action rows, below the 18/64 caps.

Diagnostic seeds require `--seed-tier diagnostic` and at least one explicit
`--diagnostic-seed`; the invocation cap is four unique non-negative seeds.
Diagnostic plans are labeled `release_gate_affected=false` and cannot alter
the frozen catalog or hashes. Seeds 1 and 101 remain compatibility samples,
not frozen Milestone 13 seeds.

## Validation

The passed start-boundary evidence is recorded in the Slice 13.1
implementation plan and retained under
`verification_reports/milestone_13_start/`.

Slice-focused qualification passed:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list explorations
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration editor_prepared_guard_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_13_legal_design_calibration_terminal --timeout-seconds 270 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --seed-tier diagnostic --diagnostic-seed 1 --diagnostic-seed 101 --timeout-seconds 270 --dry-run
.\env\Scripts\python.exe -m pytest -q tests\test_virtual_workflow_exploration_m13.py tests\test_virtual_workflow_exploration.py tests\test_virtual_workflow_exploration_runner.py tests\test_virtual_workflow_contract_freeze.py
git diff --check
```

Result: 34 focused tests passed in 0.50 seconds. Both campaign listings and
dry-run plans were canonical, the Milestone 8 catalog remained
`7cfb5efa7e36175504a2fa04a6483add993f6db13d25bdd183dcd0d6809925e8`,
and diagnostic seeds 1/101 remained nonblocking. `git diff --check` passed
with only Windows line-ending notices. The post-slice source identity was 919
files with SHA-256
`23e99c9874218d637977d11f100fb2f67bac159f499d082e581d75d268703e90`
at base commit `cc9656e3` and an expected dirty worktree.

No real Qt/system/visible execution was authorized or performed in this pure
contract slice. No generated evidence artifact or cleanup action was needed.
Analysis-pipeline tests were not run because that code did not change.

## Files changed

- `tools/virtual_workflows/exploration_m13.py`
- `tools/virtual_workflows/exploration.py`
- `tools/run_virtual_workflow.py`
- `tests/test_virtual_workflow_exploration_m13.py`
- the Milestone 13 master/execution/Slice 13.1 documentation records

## Risks, exclusions, and rollback

The frozen hash checks intentionally fail import if a reviewed contract drifts.
They do not prove execution behavior; Slices 13.2-13.4 must connect every row
to real Qt actions and retained evidence without weakening its deterministic
oracle. Full 360-reaction execution remains an independent compatibility
control. Refill/resume, active-authority mutation, firmware/protocol/hardware,
`pi_stress`, and the known 384x10 mismatch remain excluded.

Rollback removes the Milestone 13 module, additive selector/CLI options,
focused tests, and Slice 13.1 records. It does not modify Milestone 8 or any
Milestone 9-12/11A deterministic contract, and requires no data deletion.
