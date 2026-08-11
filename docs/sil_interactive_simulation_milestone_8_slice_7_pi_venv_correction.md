# Milestone 8 Slice 7 Pi Virtual-Environment Child Correction

## Scope

After the proof-bootstrap correction, the authorized `pi_primary` preflight,
traced 96-well audit, and hardware-isolation proof passed. The suite's fresh
child then exited before importing Qt, and the exact replay reproduced the same
failure:

`ModuleNotFoundError: No module named 'PySide6'`

The Pi repository interpreter is `env/bin/python`, a symlink to the system
Python binary. `AggregateRunConfig` resolved that symlink before constructing
the child command, changing the executable from the virtual-environment entry
point to `/usr/bin/python3.11`. The replay generator performed the same
resolution. Invoking the system binary directly bypassed the environment's
installed packages.

## Correction plan

1. Convert the selected Python executable to an absolute path without resolving
   its final symlink.
2. Preserve existing canonical resolution for the runner, output, evidence, and
   containment paths.
3. Generate Pi replay commands with the same absolute, symlink-preserving
   interpreter path. Replay validation continues to resolve both sides solely
   for executable-identity allowlisting before invoking the retained command.
4. Add regression coverage proving configuration and replay retain a virtual
   environment entry point even when its resolved target differs.
5. Run the focused suite-runner, selection, contract, Pi-lane, and real-process
   suite tests before deploying the exact commit.
6. Re-run only `pi_primary` and its exact replay; retain all evidence and do not
   run `pi_stress`.

## Exclusions, risks, and rollback

No View, Controller, Model, simulator, fixture, manifest, report schema,
protocol, firmware, Pi configuration, or physical-hardware behavior changes.
The executable must still be an existing file, and replay remains constrained
to an executable resolving to the current interpreter plus the existing strict
option and evidence allowlist.

Rollback restores executable symlink resolution and its prior tests. It
requires no data migration, Pi reconfiguration, firmware rollback, or hardware
action.

## Retained failed-attempt evidence

The original and replay aggregates are retained beneath
`verification_reports/virtual_workflows/pi-sil/pi_primary` with SHA-256 values
`117255c0ac97eed7947502ad214a90d7548eb0b93c3fe93e3909d1d7172a0faf`
and `ca19be99f7d4d18a0836ecf1516bf9ae5801da99a0caee3adfdb0b3fe37d01d2`.
Their validated bundle has SHA-256
`858ea2d7c2efb7ed908e5ac24302aa2720802be57f5161b080bafd53257ff4ca`.
