# Machine Data Migration Milestone 1: Contract Implementation Plan

Status: `implementation_complete`

Prepared: 2026-08-19

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 1 will add an inert, testable contract for locating and describing
external machine-owned data. It will not change the production configuration
path, create external production directories, migrate files, show UI, connect
hardware, or authorize movement.

At the end of Milestone 1:

- code can deterministically describe the external data root for the current
  OS account;
- two checkouts given the same application-local data location resolve the
  same machine-data base;
- canonical machine directories are keyed by stable machine UUID;
- active-machine and identity payloads have versioned schemas and validators;
- dangerous or checkout-contained path overrides are rejected;
- the authoritative list of machine configuration files can be queried
  without duplicating `LocalConfig` knowledge;
- current production startup still uses `<repo>/local` exactly as before.

## Relationship to later milestones

Milestone 1 defines paths and schemas only.

```text
Milestone 1
  pure path and metadata contract
  no production activation
        |
        v
Milestone 2
  backup, candidate, hashing, staged-copy, and migration engine
        |
        v
Milestone 3
  first-start UI, operator verification, production cutover, and motion gate
```

Keeping Milestone 1 inert makes its rollback trivial and prevents a partially
implemented migration from affecting a printer.

## Current call path and preserved behavior

Current production remains:

```text
App.main()
-> get_machine_config_path("Settings.json")
-> LocalConfig.LOCAL_DIR == <repo>/local
-> production_dependencies()
-> ApplicationRoots.production() with None roots
-> Model(config_root=None)
-> LocalConfig default paths under <repo>/local
```

Milestone 1 adds only this unused contract path:

```text
explicit caller/test
-> MachineData.resolve_machine_data_base(...)
-> MachineData.build_machine_data_paths(...)
-> immutable path values / validated metadata
```

The following must remain true through Milestone 1:

- `App.py` does not import or call the new machine-data module.
- `ApplicationRoots.production()` continues to return `None` roots.
- `Model(config_root=None)` continues to use `LocalConfig.LOCAL_DIR`.
- `get_machine_config_path()` retains current default seeding behavior only for
  the still-active legacy root. Milestone 3 removes that behavior from the new
  production canonical root.
- Simulation and virtual-workflow explicit roots remain unchanged.

## Scope

### In scope

- External base-root resolution contract.
- Environment/explicit override validation.
- Machine UUID and display-ID validation.
- Active-machine schema.
- Canonical identity schema compatible with the existing qualification
  identity fields.
- Immutable canonical path layout.
- Public read-only inventory/validation helpers for LocalConfig-managed data.
- Configuration-lock path contract.
- Focused unit tests and production-non-regression tests.
- Documentation of assumptions, limitations, and later integration points.

### Out of scope

- Reading or writing the deployed Pi backup.
- Creating the production external directory.
- Selecting a candidate or copying configuration.
- Hashing, ZIP creation, or migration receipts.
- First-start UI.
- Production `App.py`, Model, Controller, or View integration.
- Acquiring the canonical configuration lock.
- Location verification or movement blocking.
- Configuration audit events.
- Updater or rollback changes.
- Firmware, device protocol, motion, pressure, or timing changes.

## Frozen Milestone 1 decisions

These are the recommended implementation decisions. Review them before coding;
record any accepted revision in the parent decision log.

### 1. Default base comes from Qt application-local data

Use the value returned by:

```text
QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
```

after `configure_app_identity(app)` has set:

```text
organization: LabCraft
application: LabCraft Printer
```

The canonical base is:

```text
<AppLocalDataLocation>/machine-data
```

Rationale:

- the current app already uses this Qt location for its checkout-independent
  single-instance lock;
- it is writable without administrator privileges for the current deployment
  account;
- it is stable across clones and worktrees launched by the same OS account;
- it avoids hard-coding Windows- or Pi-specific home paths;
- it does not require a new runtime dependency in the contract module.

Milestone 1's core module will not import Qt. It receives the application-local
path as an explicit argument. Milestone 3 will add the small Qt adapter in
`App.py`.

### 2. Scope is one OS account

The rc.2 default guarantees sharing across checkouts/worktrees launched by the
same OS account. It does not promise that two different Windows/Linux users
share a machine-data root.

If the launcher account changes, the new account resolves a different root.
Milestone 3 must fail closed and run source selection/migration again.

System-wide storage can be considered later only with an installer/service
permission contract and migration plan.

### 3. Explicit override is supported but constrained

The contract supports:

```text
LABCRAFT_MACHINE_DATA_ROOT
```

and a direct `explicit_root` argument for tests, support tooling, and managed
deployments.

Precedence:

```text
explicit_root argument
-> LABCRAFT_MACHINE_DATA_ROOT
-> <AppLocalDataLocation>/machine-data
```

Override rules:

- must be absolute after `expanduser`;
- must not be a filesystem root, the user's home itself, the repository root,
  or any directory beneath the repository root;
- must resolve symlinks/normal components as far as the host allows;
- may be nonexistent in Milestone 1 because resolution has no write side
  effects;
- is recorded as override provenance by later milestones;
- must not point to a removable backup for normal production use.

The resolver accepts an injected environment mapping. Tests do not mutate the
real process environment.

### 4. Machine directory is keyed by UUID

Canonical path:

```text
<base>/machines/<canonical-machine-uuid>/
```

The editable/display machine ID such as `LC-001` is metadata, not a path key.
Changing a label therefore does not move the machine's data.

The UUID must parse using Python's `uuid.UUID` and is serialized in canonical
lowercase hyphenated form.

### 5. Reuse existing identity semantics

The existing qualification identity contains:

```text
machine_id
machine_uuid
assigned_at
notes
```

The canonical identity adds explicit schema fields while retaining those
values:

```json
{
  "schema_name": "labcraft.machine_identity",
  "schema_version": 1,
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "assigned_at": "2026-08-19T12:00:00Z",
  "notes": ""
}
```

Milestone 1 validates both canonical payloads and legacy candidate identity
payloads. It does not rewrite the legacy identity.

`LC-UNASSIGNED` may be read as legacy evidence but cannot become an active
canonical machine without an explicit later operator assignment.

### 6. One active-machine pointer per account

Proposed `active_machine.json`:

```json
{
  "schema_name": "labcraft.active_machine",
  "schema_version": 1,
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "selected_at_utc": "2026-08-19T12:00:00Z",
  "selection_source": "migration"
}
```

The display ID is duplicated for diagnostics but the UUID is authoritative.
Milestone 1 parses/serializes the record without writing it in production.

### 7. Preserve legacy file shapes

Canonical config files retain existing top-level shapes:

| File | Top-level type |
| --- | --- |
| `Settings.json` | object |
| `Plates.json` | array |
| `Locations.json` | object |
| `Obstacles.json` | object |
| `RegulatorProfiles.json` | object |

Metadata does not get embedded into these files. Later migration, verification,
and audit state use sidecars.

### 8. No path creation during resolution

Path resolution and dataclass construction are pure. They do not call
`mkdir`, write metadata, seed presets, or test writability.

Milestone 2 owns staged directory creation and write/durability probes.

### 9. Lock path is part of the contract

Each machine layout exposes:

```text
<machine-root>/locks/configuration.lock
```

Milestone 1 defines the path only. Milestone 2/3 will use `QLockFile` for the
exclusive migration/configuration transaction lock and will specify acquisition
lifetimes and failure UI.

The existing app-wide lock remains the first guard preventing two normal app
instances. The configuration lock additionally coordinates migration, updater,
support, and transaction tools that may run outside the normal main process.

## Proposed path layout

```text
<AppLocalDataLocation>/
  machine-data/
    active_machine.json
    machines/
      <machine_uuid>/
        config/
          Locations.json
          Settings.json
          Plates.json
          Obstacles.json
          RegulatorProfiles.json
        CalibrationMemory/
        metadata/
          machine_identity.json
          verification.json
          migration_receipt.json
        history/
          configuration_events/
          pending_transactions/
        backups/
          migration/
          edits/
          updates/
          rollback_exports/
        update_history/
        locks/
          configuration.lock
```

Milestone 1 describes every path but writes none of them in production.

## Proposed Python contract

### Exceptions

```python
class MachineDataContractError(ValueError):
    pass


class MachineDataPathError(MachineDataContractError):
    pass


class MachineIdentityError(MachineDataContractError):
    pass


class ActiveMachineError(MachineDataContractError):
    pass
```

Errors must identify the invalid field/path without including unrelated
environment contents.

### Base paths

```python
@dataclass(frozen=True)
class MachineDataBasePaths:
    root: Path
    active_machine_path: Path
    machines_root: Path
```

Construction guarantees:

- all values are absolute normalized `Path` objects;
- `active_machine_path` and `machines_root` are direct descendants of root;
- no filesystem write occurs.

### Per-machine paths

```python
@dataclass(frozen=True)
class MachineDataPaths:
    base: MachineDataBasePaths
    machine_uuid: str
    machine_root: Path
    config_root: Path
    calibration_memory_root: Path
    metadata_root: Path
    identity_path: Path
    verification_path: Path
    migration_receipt_path: Path
    history_root: Path
    configuration_events_root: Path
    pending_transactions_root: Path
    backups_root: Path
    update_history_root: Path
    locks_root: Path
    configuration_lock_path: Path
```

Construction validates UUID canonicalization and containment beneath
`base.machines_root`.

### Resolution API

Recommended signatures:

```python
def resolve_machine_data_base(
    *,
    app_local_data_root: str | Path,
    repo_root: str | Path,
    explicit_root: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> MachineDataBasePaths:
    ...


def build_machine_data_paths(
    base: MachineDataBasePaths,
    machine_uuid: str,
) -> MachineDataPaths:
    ...
```

The function requires `app_local_data_root` even when an override is present so
callers always make the application context explicit and tests cover the same
interface.

### Identity API

Recommended immutable values and helpers:

```python
@dataclass(frozen=True)
class MachineIdentity:
    machine_id: str
    machine_uuid: str
    assigned_at: str
    notes: str = ""

    def to_payload(self) -> dict[str, object]:
        ...


def parse_machine_identity(
    payload: object,
    *,
    allow_legacy: bool,
    allow_unassigned: bool,
) -> MachineIdentity:
    ...
```

Validation:

- payload must be a JSON object;
- canonical schema/version must match exactly;
- legacy payload is accepted only when `allow_legacy=True`;
- `machine_id` is stripped and nonempty;
- `LC-UNASSIGNED` is rejected unless `allow_unassigned=True`;
- UUID is valid and canonicalized;
- assignment timestamp is nonempty UTC/RFC3339 text;
- notes defaults to empty text.

Milestone 1 does not generate a new UUID or timestamp. Generation belongs to an
explicit identity-assignment workflow in Milestone 3.

### Active-machine API

```python
@dataclass(frozen=True)
class ActiveMachine:
    machine_id: str
    machine_uuid: str
    selected_at_utc: str
    selection_source: str

    def to_payload(self) -> dict[str, object]:
        ...


def parse_active_machine(payload: object) -> ActiveMachine:
    ...
```

Allowed initial `selection_source` values:

- `migration`
- `operator_selection`
- `managed_deployment`
- `test`

Unknown sources fail validation rather than being silently normalized.

## LocalConfig contract cleanup

`LocalConfig` currently owns the required top-level types and calibration-memory
seed inventory in private module dictionaries. Milestone 2 needs that knowledge
without copying it into a second module.

Milestone 1 should expose read-only helpers while preserving current behavior:

```python
def machine_config_top_level_types() -> Mapping[str, type]:
    ...


def calibration_memory_seed_top_level_types() -> Mapping[str, type]:
    ...


def validate_machine_config_file(path: str | Path, filename: str):
    ...
```

Implementation options:

- return `MappingProxyType` views over immutable module-owned mappings; or
- return defensive dictionary copies.

Do not expose mutable dictionaries that callers can use to change validation
at runtime.

The existing private names may remain temporarily to avoid an unrelated broad
test rewrite. New code uses only the public helpers.

## Existing direct-local inventory

Milestone 1 documents but does not redirect these paths:

| Consumer | Current ownership | Planned milestone |
| --- | --- | --- |
| `LocalConfig.LOCAL_DIR` configs | Machine configuration | M3 cutover |
| `RegulatorProfiles.default_local_profile_path()` | Machine configuration | M3 cutover |
| Model config and CalibrationMemory roots | Machine configuration | M3 cutover |
| Qualification `machine_identity.json` | Machine identity | M3/M7 integration |
| Controller qualification identity path | Machine identity | M3/M7 integration |
| Droplet-imager optics JSON | Machine calibration; scope needs explicit confirmation | M1 finding/M3 decision |
| Regulator optimization output | Machine calibration/diagnostics; classify before cutover | M1 finding/M3 decision |
| Updater logs/results | Update provenance | M6 external history |
| Downloaded `LabCraftUpdates` | Reproducible package cache | Remains checkout-local initially |
| HIL/qualification reports | Repository evidence/output | No automatic relocation in this plan |

Before Milestone 1 implementation is marked verified, rerun a repository-wide
direct-local search and add any missed machine-owned path to the parent findings
log. Do not expand Milestone 1 into redirecting those consumers.

## Implementation slices

Milestone 1 is one reviewable milestone commit, implemented in the following
internal order.

### Slice 1: Pure path contract

Add `FreeRTOS-interface/MachineData.py` with:

- constants for schema names, versions, directory names, and override name;
- contract exceptions;
- immutable base/per-machine path dataclasses;
- base resolution and containment validation;
- UUID-keyed path construction;
- no Qt import and no filesystem writes.

Add path-focused tests first.

### Slice 2: Identity and active-machine schemas

Add immutable identity/active-machine values, strict parsers, and serializers.
Lock canonical payload examples with golden tests. Lock legacy identity parsing
without modifying `tools/qualification/identity.py` yet.

### Slice 3: LocalConfig public inventory

Add public read-only inventory and validation helpers. Preserve every current
default path and seeding behavior. Expand `tests/test_local_config.py` to prove
the returned mappings cannot mutate module behavior.

### Slice 4: Production non-activation guards

Add/extend tests proving:

- `ApplicationRoots.production()` still has `None` roots;
- default `LocalConfig` paths remain `<repo>/local`;
- explicit simulation/test roots remain isolated;
- `App.py` has not begun calling MachineData;
- resolving a contract path creates no directories.

### Slice 5: Documentation and closeout

Update the parent plan with accepted decisions, newly found direct-local paths,
implementation commit, exact validation, and Milestone 1 status.

## Exact expected file list

Files expected to change in Milestone 1:

- New `FreeRTOS-interface/MachineData.py`.
- `FreeRTOS-interface/LocalConfig.py`.
- New `tests/test_machine_data_contract.py`.
- `tests/test_local_config.py`.
- `tests/test_safe_application_construction.py` only if an additional explicit
  production-non-activation assertion is necessary.
- Parent living plan and this implementation plan.

Files explicitly not expected to change:

- `FreeRTOS-interface/App.py`.
- `FreeRTOS-interface/ApplicationComposition.py` unless a test-only type import
  is proven necessary; the preferred plan is no change.
- `FreeRTOS-interface/Model.py`.
- `FreeRTOS-interface/Controller.py`.
- `FreeRTOS-interface/View.py`.
- `FreeRTOS-interface/RegulatorProfiles.py`.
- `tools/update_and_restart.py`.
- Firmware and protocol files.
- Release metadata.

Reconfirm this list immediately before implementation. If application code
outside the expected list becomes necessary, update the parent plan before
editing.

## Detailed test matrix

### Base resolution

| Case | Expected result |
| --- | --- |
| No override | `<app-local>/machine-data` |
| Explicit absolute override | Explicit root selected |
| Environment absolute override | Environment root selected |
| Explicit plus environment | Explicit wins |
| Relative override | `MachineDataPathError` |
| Filesystem root override | Rejected |
| User-home override | Rejected |
| Repository root override | Rejected |
| Descendant of repository | Rejected |
| Nonexistent valid external root | Accepted without creation |
| Different checkout roots, same app-local | Same base result |
| Empty app-local without override | Rejected |

### Per-machine layout

| Case | Expected result |
| --- | --- |
| Canonical UUID | Expected contained paths |
| Uppercase UUID input | Canonical lowercase UUID path |
| Braced UUID input | Canonical UUID or explicit rejection; freeze one behavior in tests |
| Invalid UUID | `MachineIdentityError` or path contract error |
| Machine label containing separators | Never used in path |
| Path object construction | No directories created |

Recommended behavior: accept any value parseable by `uuid.UUID`, serialize and
use only the canonical lowercase hyphenated form.

### Identity

| Case | Expected result |
| --- | --- |
| Valid canonical payload | Immutable identity |
| Valid legacy payload with flag | Immutable identity |
| Legacy payload without flag | Rejected |
| Missing ID/UUID/timestamp | Rejected |
| Invalid UUID | Rejected |
| `LC-UNASSIGNED`, activation mode | Rejected |
| `LC-UNASSIGNED`, legacy-inspection mode | Accepted as unassigned evidence |
| Unknown canonical schema/version | Rejected |
| Serializer round trip | Exact canonical payload |

### Active machine

| Case | Expected result |
| --- | --- |
| Valid payload | Immutable active-machine value |
| Unknown selection source | Rejected |
| Machine ID empty | Rejected |
| UUID invalid | Rejected |
| Serializer round trip | Exact canonical payload |

### LocalConfig

| Case | Expected result |
| --- | --- |
| Public inventory | Exact five managed config files/types |
| Returned mapping mutation attempt | Cannot alter module contract |
| Public validation of valid files | Existing payload returned |
| Public validation of wrong type | Existing fail-fast error |
| Default config root | Still `<repo>/local` |
| Explicit config root | Still honored |
| CalibrationMemory default/explicit roots | Unchanged |

### Non-activation

| Case | Expected result |
| --- | --- |
| Production roots | Still all `None` |
| App startup source | No MachineData bootstrap/call yet |
| Simulation construction | All writes under supplied roots |
| Contract import | No directory creation and no hardware imports |

## Validation commands

Focused during implementation:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_machine_data_contract.py `
  tests\test_local_config.py `
  tests\test_safe_application_construction.py `
  tests\test_view_window_icon_contract.py
```

Full Python gate before marking Milestone 1 verified:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Static/documentation checks:

```powershell
git diff --check
git status --short
```

No hardware command, firmware flash, firmware build, or HIL run is required for
this inert contract milestone.

## Review checklist

- [x] New module has no Qt, MVC, hardware, updater, or firmware import.
- [x] Resolver has no filesystem write side effects.
- [x] Default path is derived from an explicitly supplied app-local path.
- [x] Override precedence and containment are locked by tests.
- [x] Repository-contained and broad destructive roots are rejected.
- [x] UUID, not display label, owns the directory key.
- [x] Existing identity fields remain representable.
- [x] Unassigned identity cannot become active silently.
- [x] Canonical schemas reject unknown versions.
- [x] LocalConfig inventory has one source of truth.
- [x] Legacy LocalConfig default behavior is unchanged.
- [x] Simulation roots are unchanged.
- [x] Existing application-wide single-instance tests still pass.
- [x] Direct-local inventory has been refreshed and findings recorded.
- [x] Full Python suite passes.
- [ ] Parent plan contains the dedicated commit and validation evidence.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Contract accidentally changes production root early | No App/Model integration; explicit non-activation tests |
| Qt path differs by checkout | App identity is common; same supplied app-local path test |
| OS account changes | Explicit same-account scope; later startup fails closed and migrates |
| Override points inside repo | Resolve and reject repo/root/home containment |
| Display machine ID changes | UUID keys machine directory |
| Legacy identity is unassigned | Accept only as evidence; block active assignment |
| Duplicate config inventory diverges | Public LocalConfig helpers remain source of truth |
| New module creates directories during import | Pure contract and no-side-effect tests |
| Direct local consumer is missed | Repository-wide search and parent findings update |
| Path schema changes later | Stable directory names and versioned metadata schemas |

## Rollback plan

Milestone 1 is inert. To roll it back:

1. Revert the Milestone 1 commit.
2. Remove the unused `MachineData.py` contract and its focused tests.
3. Restore LocalConfig private-only helpers if necessary.
4. Confirm production still resolves `<repo>/local`.
5. Run `tests/test_local_config.py` and
   `tests/test_safe_application_construction.py`.

No deployed configuration or external data should exist solely because of
Milestone 1, so rollback does not copy, move, or delete machine files.

## Exit criteria

Milestone 1 is `verified` only when:

1. Path, identity, active-machine, and layout contracts are implemented.
2. All contracts are side-effect-free and independently testable.
3. Same-account, cross-checkout root equality is proven.
4. Unsafe path overrides are rejected.
5. Canonical machine paths are UUID-keyed and contained.
6. LocalConfig exposes one read-only managed-file inventory.
7. Production default paths and simulation explicit paths remain unchanged.
8. Direct-local inventory is refreshed and recorded.
9. Focused and full Python suites pass.
10. Parent decisions/findings/progress and validation records are updated.

## Implementation record

- 2026-08-19: Implementation started on the inert path/schema contract. No
  production activation is authorized in this milestone.
- 2026-08-19: Added `FreeRTOS-interface/MachineData.py` with side-effect-free
  root resolution, immutable and self-validating UUID-keyed path values,
  versioned machine-identity and active-machine parsing/serialization, and the
  configuration-lock path contract.
- 2026-08-19: Exposed read-only LocalConfig inventories and the existing
  machine-config validator through public helpers without changing legacy
  default roots or preset seeding.
- 2026-08-19: Added focused path, identity, active-machine, LocalConfig, and
  production-non-activation tests. `App.py`, application composition, MVC,
  updater, firmware, protocol, motion behavior, and release metadata remain
  unchanged.
- Work is complete on branch `update_bug_fix`; the dedicated Milestone 1
  commit is pending.

## Validation record

- Focused command:

  ```powershell
  .\env\Scripts\python.exe -m pytest -q `
    tests\test_machine_data_contract.py `
    tests\test_local_config.py `
    tests\test_safe_application_construction.py `
    tests\test_view_window_icon_contract.py
  ```

  Result: 101 passed; 110 existing Qt deprecation warnings; 5.86 seconds.

- Full Python gate:

  ```powershell
  .\env\Scripts\python.exe -m pytest -q
  ```

  Result: 5,100 passed, 152 skipped; 585 existing deprecation warnings;
  266.06 seconds.

- No hardware command, firmware flash/build, HIL run, protocol change, or
  motion test was required because the new module has no production caller.
- `git diff --check` passed for tracked changes. A separate scan found no
  trailing whitespace in all six Milestone 1 files and confirmed balanced
  Markdown fences in both plan documents.

## Findings discovered during planning

1. `platformdirs` is listed in `requirements.txt`, but the active repository
   virtual environment used during planning did not expose it. The proposed
   contract therefore relies on the already-used Qt app-local location supplied
   by the application adapter and adds no path-library dependency.
2. The existing app-wide single-instance lock already uses
   `QStandardPaths.AppLocalDataLocation`, which supports a consistent
   same-account path convention across checkouts.
3. Machine identity is currently owned by qualification tooling and may be
   absent or `LC-UNASSIGNED`; canonical activation must remain an explicit
   later workflow.
4. Additional machine-owned direct-local files exist outside LocalConfig,
   including droplet-imager optics configuration and regulator-optimization
   data. They require classification before Milestone 3 cutover but must not
   expand this inert milestone into a production migration.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-19 | Created the concrete inert contract implementation plan for Milestone 1. |
| 2026-08-19 | Recorded the completed implementation and focused/full validation; retained implementation-complete status until the dedicated milestone commit exists. |
