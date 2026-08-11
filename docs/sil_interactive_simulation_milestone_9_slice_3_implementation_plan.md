# Milestone 9 Slice 3 Implementation Plan

Status: implementation authorized (2026-08-08)

## Objective

Register `calibration_requantization_v1` with three immutable droplet-mode
cases that independently freeze prepared and requantized droplet counts. Run
each case through the real editor and calibration UI, authoritative execution,
durable intents, the hardware-isolated simulator, and terminal persistence.

The call path is:

```text
CLI matrix selection
-> generic matrix registry and fresh-process runner
-> calibration_requantization journey dispatch
-> real editor creates a prepared 24-well plan
-> real calibration preview and Apply
-> authoritative plan/progress/runtime retargeting
-> durable intents and simulator DISPENSE commands
-> terminal persisted count reconciliation
```

No production MVC, firmware, protocol, hardware behavior, report schema,
aggregate schema, or existing fixture will change.

## Frozen cases

| Case | Prepared | Calibrated | Printed | Prepared count | Final count | Boundary margin |
|---|---:|---:|---:|---:|---:|---:|
| `droplet_idempotent_10_to_10` | 9.0 nL | 9.0 nL | 90 nL | 10 | 10 | `1/2` drop |
| `droplet_volume_increase_10_to_9` | 8.0 nL | 9.0 nL | 80 nL | 10 | 9 | `7/18` drop |
| `droplet_volume_decrease_10_to_11` | 10.0 nL | 9.0 nL | 100 nL | 10 | 11 | `7/18` drop |

All cases use stock identity `Virtual Requantization Stock_10.00_mM`, wells
`A1` through `A24`, droplet mode, a 1300 us pulse, 1.2 psi pressure, and 24
completed stock/well intents. Exact `Fraction` validation rejects half ties,
margins below one third of a drop, inconsistent count direction, invalid
profiles, and identity/cardinality drift without calling the production
requantization implementation.

## Implementation

1. Add a frozen `RequantizationCase`, its three cases, catalog metadata, an
   in-memory builder derived from the unchanged multi-stock reference fixture,
   and a second production `MatrixDefinition`.
2. Permit a fixture lifecycle to override the editor's printed/final design
   volume while preserving the existing default, and allow prepared-plan
   assertions to receive exact expected stock counts.
3. Extend `execution.dispense_counts_reconciled` with a catalog-owned oracle:
   prepared counts remain 10, while every post-Apply layer must equal the
   catalog's 10, 9, or 11 count.
4. Generalize matrix parameter/outcome assertions to validate registered
   catalog identity and dynamic stock/pass cardinality while preserving all
   mixed-mode blocked behavior.
5. Add `calibration_requantization` journey dispatch using the shared
   multi-stock calibration body and dynamic action, assertion, and screenshot
   contracts.
6. Add focused unit, contract, CLI, and fresh-process system coverage and
   update operator documentation.
7. Run only targeted Slice 9.3 validation, inspect the retained matrix and
   visible boundary evidence, create the completion record, and commit the
   slice independently.

## Compatibility gates

- Matrix plan and aggregate schemas remain version 1; report-v1 is unchanged.
- The mixed-mode catalog hash remains
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.
- Its representative dry-run plan hash remains
  `543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`.
- No-argument matrix helpers continue to select `mixed_mode_calibration_v1`.
- Multi-target, stream-to-droplet, fill, missing-fill, and two-reagent cases
  remain deferred to Slices 9.4 and 9.5.

## Validation policy

Run focused matrix, runner, count, assertion, phase, composition,
contract-freeze, and selected fresh-process system tests. Qualify the complete
three-case requantization matrix and its retained replay offscreen, then run
and replay the two boundary cases on the visible Qt platform. Run
`git diff --check`.

Do not run the eight-case mixed-mode matrix or the unselected full Python
suite. The complete Milestone 9 matrix, lifecycle/host regressions, and full
suite remain reserved for Slice 9.6.

## Rollback

Revert the requantization definition, journey dispatch, oracle-specific
generalizations, tests, and Slice 9.3 documentation together. Retain the
generic Slice 9.1 registry and backward-compatible Slice 9.2 evidence.
Historical reports require no deletion or migration.
