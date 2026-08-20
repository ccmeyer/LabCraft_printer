# Machine Data Migration Milestone 5 Completion Record

Status: `verified`

Verified: 2026-08-20

Implementation commit:
`8b50872d344fa5a4dcf4a96890d8438b610238af`

Policy SHA-256:
`7f724af4b2e88ab3d46d774f38bb6be8cdd6b82240027e04785bc80b9cfa4274`

Parent documents:

- `docs/machine_data_migration_and_location_safety_plan.md`
- `docs/machine_data_migration_milestone_5_implementation_plan.md`

## Result

Milestone 5 is verified. The guarded-change implementation was committed,
pushed, fast-forwarded into a clean target-Pi checkout, and qualified without
launching production `App.py` or connecting physical serial, camera, balance,
GPIO, homing, pressure, or motion interfaces.

The Pi qualification used two fresh copies of the previously verified
Milestone 4 sequence-zero baseline under
`/tmp/labcraft-m5-qualification.OUptr0`. The original baseline and production
machine-data store were not modified.

## Qualified behavior

- The untouched M4 copy opened under the M5 policy as `ready` without creating
  a history head, event, backup, or configuration-byte change.
- The tracked policy hash matched on Windows and the Pi.
- A fresh, homed, idle, queue-empty synthetic status snapshot was capture-ready.
  Stale, not-homed, queue-nonempty, recovery-active, and
  expected-position-mismatch cases failed closed.
- Simulated Pi status delivery used a 100 ms cadence. The retained 2,500 ms
  freshness ceiling is 25 times that interval and the 2,501 ms case rejected
  all three axes. This is software timing evidence, not a physical-device
  measurement.
- A synthetic Camera Y change of 250 steps required strong confirmation. Its
  cancel event changed neither configuration nor authorization. Its accepted
  transaction recorded policy/proposal evidence, revoked Camera authorization,
  created a backup, and restored the exact prior bytes without motion.
- An out-of-bounds Camera endpoint, reversed rack pair, and self-intersecting
  plate quartet produced audited rejections and changed no configuration bytes.
- Valid synthetic rack and plate aggregate translations of 10 steps required
  strong confirmation, committed as single aggregate transactions, revoked
  affected targets, and exact-restored to baseline bytes.
- The final disposable history contained ten chained events in the expected
  order: one cancellation, three changes, three restores, and three
  rejections. It retained six verified backups and no pending transaction.
- All five final governed configuration files and `active_machine.json` were
  byte-identical to the untouched M4 baseline.
- Primary and detached checkouts reopened identical sequence-10 history and
  identical restored configuration hashes.
- The qualification harness recorded zero hardware commands and loaded no
  `Machine_FreeRTOS` or GPIO driver. Importing `Controller.py` imports pyserial
  support modules, so the final gate records those imports separately from
  actual port access. The repository's independent traced safety proof found
  no private-device access.

## Automated validation

Local validation completed before the implementation commit:

- new M5 focused tests: `14 passed`;
- combined M4/M5 focused tests: `66 passed`;
- complete Python suite: `5,377 passed, 156 skipped`;
- contained `virtual_print_array_96_v1`: `96 / 96`, seed 1;
- changed-module compilation and `git diff --check`: passed.

Target-Pi validation at the exact implementation commit:

- complete M5 focused inventory: `168 passed`, 130 deprecation warnings;
- contained simulation-only `virtual_print_array_96_v1`: `96 / 96`, seed 1;
- repository Pi SIL preflight and traced hardware-isolation proof: passed;
- traced safety-proof audit journey: `96 / 96`, seed 1;
- full disposable transaction harness: exit `0`;
- detached-checkout reopen: exit `0`;
- final immutable-byte and no-pending closeout gates: passed.

The warnings are existing Qt Charts deprecations and did not affect the safety
or persistence assertions.

## Qualification-harness corrections

Two failed harness attempts are retained for transparency. Neither exposed a
product defect or touched production data:

1. The first stopped during the untouched-copy read because the evidence
   script attempted to JSON-encode a read-only `mappingproxy`.
2. The second completed the transaction scenarios and exact restores, then
   incorrectly treated pyserial module import as a physical-port access.

The final harness normalized read-only mappings and distinguished imported
support modules from actual hardware-driver/port access. The final mutating
run used a new sequence-zero transaction copy.

## Evidence

The private qualification evidence remains outside Git under:

`verification_reports/machine_data_migration/milestone5/pi-20260820T154232Z/`

The checked manifest covers 53 retained evidence files. The compressed archive
is:

`labcraft-milestone5-pi-qualification-8b50872d.tar.gz`

Archive SHA-256:

`03c2de79df6e23b75c708c6aa023b88d7c8c58b0b2e625edc176c717fd6f95ff`

The hash was generated on the Pi and independently revalidated after copying
the archive to Windows.

## Safety boundary and remaining work

This qualification proves software rejection, proposal binding, transactional
persistence, audit history, authorization revocation, exact restore,
cross-checkout reuse, and zero physical command dispatch in the qualified
lane. It does not establish unmeasured obstacle geometry, route clearance, or
physical calibration accuracy.

The all-strong policy remains the approved rc.2 fallback. No numeric routine
threshold, obstacle exclusion, rack tolerance, or plate tolerance was inferred
from this single machine. Any future relaxation requires reviewed fleet and
attended physical evidence. Milestone 7 retains the attended HIL and staged
deployment boundary.

## Rollback

Before deployment, the implementation can be rolled back with a normal review
of a revert of commit `8b50872d`. After an M5 store has recorded guarded
events, preserve the external canonical store and its evidence; do not delete
or rewrite history and do not operate production hardware by silently moving
back to an unguarded M4 application. Use the controlled compatibility/update
path planned for Milestone 6.
