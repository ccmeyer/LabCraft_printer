# Milestone 9 Slice 3 Completion Record

Status: complete (2026-08-08)

## Scope and implementation

Slice 9.3 registered the production `calibration_requantization_v1` matrix
with three immutable droplet-mode cases: idempotent `10 -> 10`, volume
increase `10 -> 9`, and volume decrease `10 -> 11`. The catalog uses exact
rational nearest-integer validation, rejects half ties and margins below one
third of a drop, and freezes the expected prepared and requantized counts
without calling the production requantization implementation.

Each case is derived in memory from the unchanged
`print_array_multi_stock_24x2_v1.json` reference fixture. The real editor
creates a one-stock 24-well design, the real calibration dialog generates and
applies the 9 nL synthetic result, and the shared journey executes the
authoritative plan through durable intents and the hardware-isolated
simulator.

The existing `execution.dispense_counts_reconciled` assertion now supports a
catalog-owned oracle while retaining its Slice 9.2 internal-self-consistency
fallback. For requantization cases it requires 10 prepared droplets and the
catalog's 10, 9, or 11 count in every later layer: visible preview, calibrated
plan, zero-progress targets, runtime, durable intent, simulator command,
terminal target, and terminal added count. Matrix assertions also prove that
the lifecycle oracle is linked to the registered normalized case, case hash,
stock identity, and exact authoritative well membership.

The registry now lists two production matrices in deterministic ID order. The
new catalog SHA-256 is
`d36330cddd7f3e168c2802314371837d96c9d4393021c338d487ff27e0c8ada8`;
the frozen idempotent dry-run plan SHA-256 is
`54bc74e13e9eb82b84105d0cc94cf3472b693b7969fffb4908db5e7d837dec98`.
The mixed-mode catalog and representative plan hashes remain exactly
`d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`
and
`543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`.

No production MVC, simulator behavior, firmware, protocol, existing fixture,
report-v1, matrix-plan, or aggregate schema changed.

## Validation

Focused unit and contract validation passed 99 tests across the matrix
registry/runner, count extraction and reconciliation, assertions, journey
phases, composition, CLI contracts, and contract freeze. The selected
fresh-process system test passed and executed all three requantization cases.
The complete mixed-mode matrix and full Python suite were intentionally not
run; both remain reserved for Slice 9.6.

One final-source mixed-mode baseline case passed with 48/48 completions,
confirming the generic assertion and journey refactor retained the existing
path:

- `verification_reports/matrices/mixed_mode_calibration_v1/20260808T162345770102Z_composed/report.json`
- SHA-256 `2a17badcdeb5509c3430d50c0c49d1a9bdc98dedbcd880ab5855b861b5716ee0`

## Retained qualification evidence

| Qualification | Result | Evidence | SHA-256 |
|---|---|---|---|
| complete offscreen matrix | 3/3 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162207172193Z_d0f72e60-6f6/aggregate.json` | `93d28e4d6d3f26d30c56d28768660c9033f0b9216acebfed48576480260c0341` |
| retained aggregate replay | 3/3 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162227696265Z_260ea788-03c/aggregate.json` | `7d3166f06a15741e0cb4ad8117a83395c8e77d11fc5e840d6ad070fb4c982c26` |
| visible `10 -> 9` | 24/24 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162251963499Z_composed/report.json` | `d76e4f27a30f0c101b5ae05004dfe2657a7145197ec019c4afdb28c05037e60d` |
| visible `10 -> 11` | 24/24 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162303461159Z_composed/report.json` | `8b1fcc75f35ad9fac070463c2b7aaaed3a6d00db5bd695fedf59a4511eed6c66` |
| visible `10 -> 9` replay | 24/24 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162316344556Z_composed/report.json` | `9deac2bfea2710a88995c4a5ba75cc72818e520f8edc070be5e046c291adab62` |
| visible `10 -> 11` replay | 24/24 pass | `verification_reports/matrices/calibration_requantization_v1/20260808T162329654990Z_composed/report.json` | `bbc94a029fc7e32566645c9ca5781272cdd4521e00a857ed6e1154919475ec2c` |

Inspection of all four visible reports confirmed:

- `oracle_scope` is `calibration_requantization_v1_catalog_oracle`;
- the preview visibly reports 9 or 11 drops as expected;
- all nine count layers reconcile exactly;
- each case has 24 joined non-manual completed simulator dispenses and zero
  unattached dispenses;
- catalog-to-case oracle linkage is true;
- terminal completion is 24/24 with zero retained errors;
- no fill dispense, hardware access, timeout, or process/report disagreement
  occurred.

During final hardening, an over-strict positional well-order comparison exposed
that the catalog uses natural plate order while the authoritative plan uses
canonical serialization order. The check was corrected to require identical
unique well membership; every count remains keyed and compared by exact
`(stock_id, well_id)`. This was a harness correction, not a production defect.

Native Windows qualification used the existing `--visible` interface. The CLI
correctly rejected the non-contract `--qt-platform windows` spelling before
application construction; `--qt-platform` remains limited to `offscreen` and
`minimal`.

## Risks and rollback

Slice 9.3 is intentionally limited to one target, one non-fill stock, and
droplet-to-droplet calibration. Multi-target, stream-to-droplet, fill,
missing-fill, and two-reagent isolation cases remain in Slices 9.4 and 9.5.

Rollback reverts the requantization definition, journey dispatch,
oracle-specific assertion generalizations, tests, and documentation while
retaining the Slice 9.1 registry and Slice 9.2 bounded evidence. Retained
reports remain historical and require no migration or cleanup.
