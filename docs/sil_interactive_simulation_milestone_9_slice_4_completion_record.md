# Milestone 9 Slice 4 Completion Record

Status: complete (2026-08-08)

## Outcome

Slice 9.4 extends `calibration_requantization_v1` from three to six ordered,
immutable cases without changing production MVC, simulator, firmware,
protocol, fixture, report-v1, matrix-plan, or aggregate schemas. The three new
cases execute through the real editor and calibration UI, Controller/Model,
durable intent boundary, `Machine_FreeRTOS` dispense call, and
`SimulatedMachine` completion.

The catalog now proves:

- alternating multi-target non-fill counts `1 -> 1` and `10 -> 9`, with fill
  `8 -> 8` on odd wells and explicit zero/absent dispatch on even wells;
- an executed stream `40 nL / 4 drops -> droplet 10.8 nL / 15 drops`
  transition while support fill remains at 121 drops;
- fill `12 nL / 4 drops -> 9 nL / 5 drops` while non-fill remains at 6.

The cases complete exactly 36, 48, and 48 positive stock/well intents. Every
joined simulator command is a completed, non-manual `DISPENSE` with the
catalog-owned count.

## Implementation

- Added frozen grouped count, calibration-step, and composite requantization
  descriptors with exact `Fraction` validation, complete stock/well
  membership, deterministic preview rows, primary-transition validation,
  minimum rounding margins, and explicit zero clamping.
- Kept the original `RequantizationCase` normalized payloads and case hashes
  unchanged. The unchanged tracked 24x2 reference fixture is still transformed
  only in memory.
- Generalized editor input for target lists, reaction cardinality, fill mode
  and volume, and fill-role stocks. Fill stocks remain outside reagent rows but
  participate in calibration, plan evidence, and execution.
- Generalized stock passes for separate prepared/applied modes, confirmation
  of stream-to-droplet switching, case-local in-memory print profiles, ordered
  primary/support calibrations, positive-oracle completion boundaries, fill
  Apply confirmation, and omission of zero-count dispatch.
- Added grouped oracle schema 2 reconciliation across prepared plan, visible
  target/fill previews, calibrated plan and revisions, zero progress, runtime,
  intents, simulator commands, and terminal persisted targets/additions.
  Schema 1 remains unchanged for the first three cases and Slice 9.2
  self-consistency users.
- Added `experiment.inspect_completed_via_ui`, the
  `terminal_reloaded` screenshot, and required assertion
  `execution.completed_terminal_reload_exact`. The stream case closes its first
  application, launches a fresh application composition on the retained SIL
  root, selects the completed experiment through the real Qt folder dialog,
  performs no activation, and compares the authoritative tree byte for byte.
- Updated focused catalog, action, assertion, page-driver, composition,
  contract, and fresh-process system coverage plus the README and operator
  runbook.

## Terminal eligibility clarification

The approved plan described a reloaded completed execution as eligibility
`complete`. The production authoritative loader intentionally maps a plan that
has already transitioned to `COMPLETED` to `analysis_only`; `complete` is the
pre-terminal eligibility used when no droplets remain. No production behavior
was changed. The reload assertion instead requires all of the stronger
terminal facts together:

- plan state `completed` and all saved targets exactly satisfied;
- eligibility `analysis_only` with start, resume, and activation all denied;
- runtime inactive, no runtime projection activated, zero durable intents;
- disabled `Execution Locked` action and visible read-only/hardware-blocked
  guidance;
- exact plan identity/revision, design hash, revision history, assignments,
  calibration/head linkage, progress, and authoritative file hashes.

## Frozen identities

- Expanded requantization catalog SHA-256:
  `668249dabdf29e7201cb439d349e789d68e12b8513dd24622e756eafb6627eac`
- Original mixed-mode catalog SHA-256 remains:
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`
- Original representative mixed-mode plan SHA-256 remains:
  `543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`
- Original three requantization case hashes remain:
  `714f1c212bef572de306a7f2b35d47e28c477477467dc36cec4c4acf2ec8d98f`,
  `f9bc246789292641551a4606bf6bfcff233bdebf741215c10e1e836e9a18bd99`,
  and `028cc1b70dd6023a40596b0fef21704bddfde8fa95c72406ad8a8b3cfbf5c35d`.
- New case hashes are:
  `98912b757f51b31d8246e1c52b78e5b163d4f3ae76ca380b87380318bf485e62`,
  `dd066433aa0888bc24bf70479e9ebf3651a428dbb35dc526c0e8441056a846e1`,
  and `793b4f28bbb8ea691d8ed3b595d8a0ee4f100e08bf111b5701f16500ec8a0467`.
- Representative new-case plan hashes at seed 7, timeout 12, unauthorized are:
  `4e29a7892b0a5985f3023b611d2630f42f5015d3d775d0206a9fe6ce4f9ba5e6`,
  `a9e002c603ad9f24cc2a8d953051f635f2c4d47a97c212f76fa19abe906ced3f`,
  and `dac3a0780fd17442c9ca2c820d972e93493b03080bfd432d3646c3c925f3847c`.

## Validation

Targeted unit/contract selection:

```text
170 passed in 7.06s
```

Targeted fresh-process system selection, with the repository's required
opt-in gate:

```text
3 passed, 2 deselected in 24.76s
```

The same selection without `--run-sil-lifecycle` correctly reported three
skips. No complete six-case matrix, mixed-mode matrix, lifecycle/host suite,
or unselected `pytest -q` was run; those remain deferred to Slice 9.6.

Retained qualification:

| Evidence | Result | Report SHA-256 |
|---|---|---|
| multi-target offscreen | 36/36 pass, previews `1`, `9`, fill total `96` | `e3bc05869ab53418d77fb44346b9515326182d409fe23a6a640c1f3a398c40d8` |
| multi-target retained replay | 36/36 pass | `a35fe1643f574a3a358cf958cfb8af7618e3b35f38b40460703d1f20045998e6` |
| stream transition offscreen | 48/48 pass, previews `15`, fill total `2904`, reload pass | `85ef9c41fafb50d73ad0663cb046a5dd331f747cf679dd63faeb7b43ca70ab9e` |
| stream retained replay | 48/48 pass, reload pass | `d0194d485f8819df72cf45b6ae7f8162004433b21cb695c257e727e24dda644d` |
| fill transition offscreen | 48/48 pass, previews `6`, fill total `120` | `53e94eacf9528e9020f772f8493b4c0d4215ed046ffbbc2fffa061d2b765ddd3` |
| fill retained replay | 48/48 pass | `3dc95487292938e096cd4243fe5652674018c363bcef9cd76f5888c98db54963` |
| stream visible Windows | 48/48 pass, reload pass | `dd60b765f9adfa37848393e41b5182640928c2de42f0396e716f0cbb4bc6fd89` |
| stream visible retained replay | 48/48 pass, reload pass | `303f9acf9964b8bd6b3c8f52b94c489d1fb0b0b846a0631fea9a69b839ab16b9` |

The primary report paths are under
`verification_reports/matrices/calibration_requantization_v1/` with run IDs
`20260808T165541610319Z_composed`, `20260808T165443313467Z_composed`,
`20260808T165554082059Z_composed`, `20260808T165640787548Z_composed`, and
their retained replay run IDs recorded in the table hashes above.

`git diff --check` passed. Generated evidence remains local and untracked.

## Risk and rollback

Risk remains bounded to SIL catalog, UI-driving, evidence, and tests. The
case-local stream calibration profile is installed only in the isolated SIL
model instance and is not persisted as an application setting. No physical
hardware behavior is inferred from this evidence.

Rollback reverts the Slice 9.4 commit, removing the three appended cases,
grouped-oracle support, editor/pass generalizations, completed-terminal
inspection, tests, and documentation. Slices 9.1-9.3 and historical reports
remain usable; no data migration or cleanup is required.
