# Machine Data Migration Milestone 4 Completion Record

Status: `verified`

Verified: 2026-08-20

Target release: `v1.3.0-rc.2`

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Implementation plan:
`docs/machine_data_migration_milestone_4_implementation_plan.md`

## Qualified implementation

- Transactional configuration history implementation: commit `6925d029`
  (`feat: Added transaction history`).
- Exact-byte backup restoration correction: commit
  `f6d65fd94a9ee1fd1f6bd488b44a1c2c78b0506f`
  (`fix: restore exact configuration backup bytes`).
- Target Pi checkout and detached cross-checkout were clean and resolved the
  same corrective commit.

## Qualification outcome

The fresh target-Pi qualification passed against a disposable copy of the
previously verified Milestone 3 machine-data store. The normal application
entry point was not launched, physical hardware access was disabled, and all
configuration writes were confined to
`/tmp/labcraft-m4-corrected.thNIP1/machine-data`.

The qualification proved:

- all seven immutable activation-evidence files remained byte-for-byte equal
  to the baseline;
- all five governed configuration files finished byte-for-byte equal to their
  noncanonical legacy baselines after the edit and exact-restore exercises;
- the real Camera value was never changed and remained motion-authorized;
- named-location change, exact verification, rack-pair change, plate-quartet
  change, and exact restoration produced seven chained events and six verified
  pre-change backup manifests;
- the final configuration sequence was 7 with no pending transaction;
- primary and detached checkouts resolved byte-identical history output;
- four injected interruptions at journal, configuration replacement, event,
  and head boundaries recovered deterministically to the expected state;
- the Pi focused gate passed 61 tests and the zero-command safety gate passed
  10 tests; and
- the contained `virtual_print_array_96_v1` SIL completed 96/96 wells with
  seed 1, classification `pass`, and GPIO, MCU, balance, camera, firmware
  update, and serial access all disabled.

The disposable source store, the normal machine-data root, and the repository
checkout were not mutated by the qualification.

## Durable evidence

The Pi closeout sealed 56 evidence files in a self-checking SHA-256 manifest.
Every entry rechecked successfully before packaging. The package contains
those sealed files plus the closeout manifest, its verification output, and
the package file list, for 59 archived paths total.

The archive was copied to the ignored local evidence directory:

`verification_reports/machine_data_migration_milestone_4_pi/f6d65fd9/labcraft-m4-corrected-f6d65fd9-evidence.tar.gz`

Archive SHA-256:

`26ab07e544294b2af395a23155e4f65b93949b21c7b6cacdccc1f439cddc799a`

The archive is 293,677 bytes. Its checksum and complete member listing were
verified again after transfer. It remains excluded from Git because the
sealed evidence contains disposable copies derived from real machine
configuration. This completion record intentionally contains no location
coordinates or raw machine configuration.

## Exit decision

Every Milestone 4 definition-of-done gate has passed on Windows and the target
Pi. Transactional configuration history and exact backup restoration are
therefore `verified` for incorporation into `v1.3.0-rc.2`.

Milestone 5 may begin. Milestone 4 history and authorization remain the durable
foundation for Milestone 5 previews, delta thresholds, hard bounds, and
stronger operator confirmation. No production deployment is authorized by
this record alone; Milestones 5 through 7 and the release gates remain open.

## Rollback boundary

Before the first configuration event, an untouched Milestone 3 store retains
its documented pre-event rollback option. After any Milestone 4 event, do not
run older code directly against or delete history from the canonical store.
Preserve the complete external machine-data root and use the controlled
compatibility/export process planned for Milestone 6.
