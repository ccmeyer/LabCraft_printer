# Pi Development Worktree and Qualification Workflow

Status: `in_progress` for Slices 5-7

Prepared: 2026-08-21

Current implementation target: Slices 5-7; Slices 1-4 remain verified

## Purpose

This is the live implementation and qualification plan for running arbitrary
development commits on LC-001 without moving or modifying the protected
production checkout. It covers the Windows wrapper, the linked Pi development
worktree, the shared read-only Python environment, explicit development
machine-data binding, later firmware HIL integration, and safe restoration to
a released firmware state.

Update this document whenever a slice begins, implementation decisions change,
unexpected findings appear, validation is run, or a slice is completed. A
slice is not verified until its implementation commit and exact validation
evidence are recorded here.

## Status definitions

- `planned`: scope and exit criteria are defined; implementation has not begun.
- `in_progress`: implementation or validation is active.
- `implementation_complete`: code is committed, but a required gate remains.
- `verified`: every exit criterion and required validation gate passed.
- `blocked`: progress requires user input, additional authority, or an external
  state change.
- `deferred`: removed from the current target with a recorded reason.

## Slice status

| Slice | Scope | Status | Implementation | Validation |
| --- | --- | --- | --- | --- |
| 1 | Read-only Windows/Pi status and preflight | `verified` | `e58129b3` | 24 focused and 5,485 full-suite tests; clean/pushed Pi Preflight and exact read-only invariance passed |
| 2 | Create and synchronize the Pi development worktree | `verified` | `4bef5790` | 32 focused tests; Pi create, idempotent reuse, unregistered-path refusal, and protected invariance passed |
| 3 | Bind the shared interpreter and development machine data | `verified` | `733f9e77`, `fd2fc5e4`, `6756b5a0` | 45 focused tests; Pi create/reuse/path-free validation, dependency/environment/data invariance passed |
| 4 | Launch and qualify the no-hardware development app | `verified` | `c9ed2fda`, `eb4d8fcd` | 72 focused and 5,522 full-suite tests; exact-commit offscreen/visible no-hardware Pi launches and protected invariance passed |
| 5 | Build, flash, and qualify committed development firmware | `verified` | `3719838c`, `816e0e70` | 74 post-commit focused tests; 461 firmware host tests; headless build; exact Pi development SAFE -> rc.5 restore SAFE and protected invariance passed |
| 6 | Launch an attended real-hardware development session | `in_progress` | Concrete plan recorded | Focused implementation/refusal qualification pending; attended success deferred |
| 7 | Track and restore released firmware state | `planned` | Not started | Not run |
| 8 | Complete the end-to-end workflow qualification and runbook | `planned` | Not started | Not run |

## Current verified baseline

The following state was observed read-only on 2026-08-21. Implementation must
reinspect it rather than assuming that it remains unchanged.

- Windows repository: branch `main`, commit
  `45071568d7112b5246a19960545fc82c4ad16ffb`, clean and synchronized with
  `origin/main`.
- Pi: `labcraft@192.168.0.33` using
  `verification_reports/pi_sil_codex_network_ed25519` from the Windows
  checkout.
- Protected Pi worktree: `/home/labcraft/LabCraft_printer`, branch
  `protected-update-rc5`, commit
  `34841fe0c9f54c6e1c1ceaad2b797ab661084430`, clean.
- Intended persistent development worktree:
  `/home/labcraft/LabCraft_printer-dev`; it does not yet exist.
- Retained qualification worktrees exist at
  `/home/labcraft/LabCraft_printer-m8s8-sil-1e7efa8` and
  `/tmp/labcraft-m4-corrected.thNIP1/second-checkout`. They are out of scope
  and must not be removed or reused by this workflow.
- Shared interpreter:
  `/home/labcraft/LabCraft_printer/env/bin/python`, Python 3.11.2.
- Existing development machine-data store:
  `/home/labcraft/.local/share/LabCraft/LabCraft Printer/development/main-65ba38df-machine-data`.
- No production or development LabCraft application process was running.

## Architecture and call paths

### Application development

```text
Windows tools/run_pi_development.ps1
  -> Windows repository Python
  -> tools/pi_development_workflow.py
  -> SSH to the Pi
  -> /home/labcraft/LabCraft_printer-dev at an exact commit
  -> /home/labcraft/LabCraft_printer/env/bin/python (read-only dependencies)
  -> development tools/run_development_app.py
  -> explicit LABCRAFT_MACHINE_DATA_ROOT and development mode
  -> development FreeRTOS-interface/App.py
  -> machine-data bootstrap
  -> ApplicationComposition.development_dependencies()
  -> Controller / Model / View
  -> SimulatedMachine for Slices 1-4
```

### Firmware development, beginning in Slice 5

```text
Windows wrapper
  -> local firmware unit tests and STM32CubeIDE build
  -> committed firmware/artifacts/LabCraft_firmware.bin
  -> exact Pi development commit and binary hash
  -> firmware/hil/flash_and_test.sh
  -> dfu_update.py
  -> STM32
  -> firmware self-test or qualification
  -> report downloaded and bound to commit plus binary hash
```

## Safety and isolation invariants

1. `/home/labcraft/LabCraft_printer` remains the protected released checkout.
   Development synchronization never switches its branch, moves its HEAD,
   changes its index, or writes tracked or untracked files into it.
2. `/home/labcraft/LabCraft_printer-dev` is the only persistent code worktree
   managed by this workflow. It uses a detached exact commit for qualification.
3. Windows remains the source of development commits. The Pi workflow does not
   create commits.
4. The shared production virtual environment is read-only. Development may
   execute its interpreter but may not install, remove, or update packages in
   it.
5. Reuse of the shared interpreter is allowed only when the production and
   development dependency declarations match and the environment passes its
   integrity checks.
6. Development launch always passes an explicit, validated external
   development machine-data root. It never falls back to production data or a
   checkout-local `local/` directory.
7. Slices 1-4 cannot construct or access serial, cameras, GPIO, the balance,
   physical motion, pressure hardware, firmware/DFU, or the application
   updater.
8. A dirty or ambiguous worktree is a stop condition. Automation never runs
   `git reset --hard`, `git clean`, or an automatic deletion to recover it.
9. Reports, logs, session files, and future HIL staging stay outside tracked
   worktree paths or beneath existing ignored report roots.
10. Checking out a firmware binary does not flash it. Firmware flashing starts
    only in Slice 5 with separate attended authorization and rollback.
11. No release metadata, release tag, `main`, `stable`, device protocol,
    firmware behavior, motion behavior, or pressure behavior is changed by
    Slices 1-4.

## Slice 1 - Read-only status and preflight

Status: `verified`

### Objective

Add a Windows entry point that inventories the Windows checkout and Pi,
classifies readiness for Slice 2, and writes local evidence without modifying
either machine.

### Public interface

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_pi_development.ps1 `
  -Action Status `
  -PiHost 192.168.0.33 `
  -SshIdentityFile verification_reports\pi_sil_codex_network_ed25519
```

Parameters:

- `-Action Status|Preflight`, default `Status`.
- Mandatory `-PiHost`; accept a hostname/IP or `user@host`.
- `-PiUser`, default `labcraft`.
- Optional `-SshIdentityFile`.
- `-ProductionRepo`, default `/home/labcraft/LabCraft_printer`.
- `-DevelopmentRepo`, default `/home/labcraft/LabCraft_printer-dev`.
- `-SharedPython`, default
  `/home/labcraft/LabCraft_printer/env/bin/python`.
- Optional `-DevelopmentMachineDataRoot`. When omitted, Slice 1 may discover
  candidates for reporting but cannot persist or launch one.
- `-OutputRoot`, default
  `verification_reports/development-workflow/status`.
- `-DryRun`, which prints sanitized planned commands, performs no SSH call,
  and writes no report.

Exit behavior:

- `Status` returns 0 after complete collection even if blockers are reported.
- `Preflight` returns 0 when ready for Slice 2 and 2 for policy blockers.
- Local Git, tooling, SSH, remote collection, or malformed-output failures
  return 1.

### Implementation

1. Add a thin PowerShell wrapper that resolves
   `env\Scripts\python.exe`, validates OpenSSH and the optional identity,
   preserves host-key checking, uses `BatchMode=yes`, and propagates the Python
   core's exit code.
2. Add a Python orchestration core. Keep Git inspection, classification, JSON
   serialization, and human output in pure functions behind one injectable
   subprocess boundary.
3. Resolve the Windows HEAD, branch, upstream, ahead/behind counts, clean
   state, origin, and whether HEAD is reachable through its upstream.
4. Execute one read-only Pi collector with `ssh ... python3 -`. Pass its
   configuration as encoded JSON and source through stdin so no collector file
   is written on the Pi and shell interpolation is avoided.
5. Inspect Pi worktrees, production status, intended development path,
   additional worktrees, shared Python, relevant application processes, and
   development-store marker/pointer evidence.
6. Write an atomic JSON report under
   `verification_reports/development-workflow/status/<timestamp>_<short-head>/status.json`
   and print a concise human summary.

Planned files:

- `tools/run_pi_development.ps1`
- `tools/pi_development_workflow.py`
- `tests/test_pi_development_workflow.py`
- this live document and `README.md`

### Status schema

Schema name: `labcraft.pi_development_status`

Schema version: 1

The report contains:

- Collection ID, UTC timestamp, action, `ready|warning|blocked`, warnings, and
  blockers.
- Local root, branch, HEAD, upstream, ahead/behind counts, clean state, origin,
  and pushed/reachable state.
- Pi hostname and SSH target, excluding identity-file contents and full key
  paths.
- Production worktree path, HEAD, branch/detached state, validity, and clean
  state.
- Intended development-worktree state:
  `absent|registered_clean|registered_dirty|unregistered_path|invalid`.
- Other worktrees as informational entries.
- Shared-interpreter path, existence, executable state, and version.
- Relevant LabCraft processes.
- Development-store selection source
  `explicit|single_candidate|none|ambiguous`, marker/pointer validity, store
  ID, machine ID, and path separation.

### Readiness classification

Block `Preflight` for:

- Dirty or detached Windows HEAD.
- Missing upstream or a local HEAD not yet reachable from that upstream.
- Missing/invalid/dirty production checkout.
- Unsafe intended development path, dirty registered development worktree, or
  an existing unregistered path at the target.
- Running production, development, updater, or workflow application process.
- Missing or non-executable shared Python.
- Missing, malformed, ambiguous, or unsafe development machine-data evidence.

Do not block for:

- The intended development worktree being absent before Slice 2.
- Additional retained worktrees; report them as warnings.
- A local branch behind its upstream when its exact HEAD is already pushed;
  report it as a warning.

### Tests and qualification

- Unit-test every readiness classification and report schema field.
- Test PowerShell argument forwarding, `user@host`, identity validation,
  `BatchMode`, quoting, dry-run behavior, and exit-code propagation.
- Test fake-SSH success with benign stderr, nonzero failure, malformed JSON,
  and absence of secret material in reports.
- Run `tests/test_pi_development_workflow.py`, then the complete default Python
  suite.
- On the Pi, hash/capture production HEAD/status, worktree registration,
  machine-data marker/pointer, interpreter, and process state before and after
  `Status` and `Preflight`; require exact invariance.
- No hardware authorization is required because Slice 1 is read-only.

### Implementation record

Implemented and published in `e58129b3` on
`feature/pi-development-workflow`. The implementation adds the thin PowerShell wrapper, Python
status/preflight core, stdin-only remote collector, atomic ignored reports,
failure-path tests, and README usage.

### Validation record

- `env\\Scripts\\python.exe -m pytest -q tests\\test_pi_development_workflow.py`:
  24 passed in 3.59 seconds after the completion audit added absolute/disjoint
  remote-path and missing-OpenSSH coverage.
- `env\\Scripts\\python.exe -m pytest -q`: 5,485 passed, 156 skipped, 605
  warnings in 356.06 seconds.
- A live read-only `Status` collection correctly identified LC-001, the clean
  protected rc.5 worktree, absent development worktree, two preserved retained
  worktrees, Python 3.11.2, and the authorized development store. It correctly
  blocked the initial uncommitted/no-upstream candidate.
- Clean/published `Preflight` at `e58129b3` exited 0. Evidence:
  `verification_reports/development-workflow/status/20260821T151655634251Z_e58129b345a0/status.json`.
  It reported only the expected absent-development-worktree and two retained
  worktree warnings.
- The canonical SHA-256 of the complete Pi section matched before and after
  publication/Preflight:
  `bfc6596e7b2ab6bfec037c8fcae7cebb3ed07d62106ee713bd8873dcccfe629a`.
  Production remained clean at `34841fe0`, no application process appeared,
  Python remained 3.11.2, and the LC-001 development store ID remained
  `be5f7305-9046-4d62-8f7a-4e493859fc80`.

## Slice 2 - Development worktree creation and synchronization

Status: `verified`

### Objective

Add an explicit `Sync` action that creates or reuses only
`/home/labcraft/LabCraft_printer-dev` and selects the exact pushed Windows
commit without modifying the production checkout.

### Required behavior

- Reuse Slice 1 preflight and require a clean, pushed Windows commit.
- Create the target with `git worktree add --detach` only when the path is
  absent and Git does not already register it.
- On reuse, require a clean registered worktree before selecting the requested
  detached commit.
- Fetch only through the shared Pi repository and verify the requested full
  hash exists before changing the development worktree.
- Capture production HEAD/status before synchronization and prove they are
  unchanged afterward.
- Keep reports outside both worktrees.
- Fail closed for stale registration, an unexpected existing path, dirty
  files, an active application, missing remote commit, or mismatched final
  HEAD.

### Exit criteria

- First creation and repeated synchronization are idempotent.
- Moving between two pushed development commits changes only the development
  worktree.
- Dirty, unpublished, missing, and ambiguous cases are automatically tested.
- Pi qualification proves the protected worktree, retained worktrees,
  machine data, and shared environment remain unchanged.

### Implementation record

Implemented and published in `4bef5790`. `Sync` reuses Slice 1 readiness, fetches the exact upstream
branch into shared Git metadata, creates or retargets only the clean detached
development worktree, and proves protected Pi invariants before reporting
success.

### Validation record

- `env\\Scripts\\python.exe -m pytest -q tests\\test_pi_development_workflow.py`:
  32 passed in 3.92 seconds.
- Per the operator's 2026-08-21 validation-policy update, the in-progress full
  suite was stopped and complete regression is deferred to final Slice 4
  validation.
- First-create evidence:
  `verification_reports/development-workflow/status/20260821T152545384794Z_4bef5790e5af/status.json`.
  It created `/home/labcraft/LabCraft_printer-dev` detached at exact commit
  `4bef5790e5af816b21dd47b657977ee464e2c677`.
- Idempotent reuse evidence:
  `verification_reports/development-workflow/status/20260821T152558118430Z_4bef5790e5af/status.json`.
  It reported `unchanged` at the same commit.
- Both successful Sync runs recorded equal pre/post protected invariant hash
  `53a406659b9fe422227289e2f6f4c1fd8397a7435176135cf8ec9fd451dd0fe7`.
- A non-mutating Sync attempt using existing unregistered `/tmp` failed closed
  with `development_worktree_unsafe`; subsequent intended-path Preflight passed
  in `20260821T152645686823Z_4bef5790e5af/status.json`.
- Production remained clean at `34841fe0`; both retained worktrees, Python
  3.11.2, no-process state, and development store ID
  `be5f7305-9046-4d62-8f7a-4e493859fc80` were preserved.

## Slice 3 - Shared runtime and development-data binding

Status: `verified`

### Objective

Validate and reuse the existing production virtual environment without
mutating it, and persist an explicit external development-store selection for
all later development launches.

### Required behavior

- Add `Configure` and `Validate` workflow actions, or equivalent explicit
  sub-actions, without changing `Status`/`Preflight` compatibility.
- Compare dependency declaration hashes between the protected production
  commit and selected development commit. Refuse shared-environment reuse when
  they differ.
- Run the shared interpreter's version check, `pip check`, and bounded imports
  without installing or updating anything.
- Store only workflow paths/identifiers in an atomic external configuration at
  `/home/labcraft/.config/LabCraft/development_workflow.json`.
- Validate `development_store.json`, the active pointer, machine identity,
  disjoint paths, and the existing development-store source evidence.
- Always invoke `tools/run_development_app.py` with the explicit validated
  `--machine-data-root`; never export a persistent shell variable or call the
  development `App.py` directly.
- Reject production data, checkout-local data, missing markers, multiple
  candidates, dependency mismatch, or shared-environment drift.

### Implementation

Call path:

```text
Windows run_pi_development.ps1 Configure|Validate
  -> pi_development_workflow.py local and Pi preflight
  -> exact detached development commit
  -> tracked dependency-manifest comparison
  -> shared production Python read-only checks
  -> development-store marker, active pointer, and identity checks
  -> atomic external workflow configuration
  -> postflight and protected-invariant comparison
```

1. Extend the wrapper and Python CLI with explicit `Configure` and `Validate`
   actions, workflow-config path, operator identity, and sanitized dry-run
   output.
2. Extend read-only Pi collection to inspect the external configuration and use
   its exact store path after configuration; never silently fall back when an
   existing configuration is invalid.
3. Require a clean detached development worktree at the exact clean/pushed
   Windows commit and no relevant application or hardware workflow process.
4. Compare the complete tracked root dependency-file inventory and SHA-256
   evidence between production and development before sharing the interpreter.
5. Run version, `pip check`, bounded imports, and installed-distribution
   fingerprints without invoking any install/update/remove operation.
6. Revalidate the store marker provenance, authorized active pointer, matching
   machine identity, UUIDs, hashes, and path separation at the write boundary.
7. Atomically create the external schema-v1 binding, refuse to overwrite a
   differing or invalid binding, and prove production/data/environment
   invariants in local JSON evidence.

Planned files:

- `tools/run_pi_development.ps1`
- `tools/pi_development_workflow.py`
- `tests/test_pi_development_workflow.py`
- this live document and `README.md`

### Exit criteria

- Same-dependency development commits reuse
  `/home/labcraft/LabCraft_printer/env/bin/python` read-only.
- Dependency changes fail with a clear instruction that a later dedicated
  environment workflow is required.
- Reopening the workflow selects the same explicit development store without
  discovery or fallback.
- Pi qualification proves no package, production data, or production checkout
  change.

### Implementation record

Implementation commit `733f9e77` exposed a Pi-only virtual-environment symlink
defect during qualification: resolving `env/bin/python` to `/usr/bin/python3.11`
lost the venv package context. The correction preserves the absolute lexical
venv path in `fd2fc5e4` while retaining resolved-path checks for code and data.
Commit `6756b5a0` adds direct content fingerprints for the complete production
source and development data trees, making data invariance direct. Configure and
Validate now bind the shared venv and one external LC-001 development store
without fallback or package mutation.

### Validation record

- `env\\Scripts\\python.exe -m pytest -q --basetemp verification_reports\\development-workflow\\pytest-temp\\slice3-tree-evidence-20260821-01 tests\\test_pi_development_workflow.py`:
  45 passed in 1.48 seconds.
- The complete default suite remains deferred to final Slice 4 validation per
  the operator's 2026-08-21 direction.
- Initial Configure evidence:
  `verification_reports/development-workflow/status/20260821T154234736074Z_733f9e77cb6e/status.json`.
  It failed before writing configuration because the venv interpreter symlink
  had been resolved to the system interpreter and PySide6 was unavailable.
- Read-only post-failure evidence:
  `20260821T154357969595Z_733f9e77cb6e/status.json`. It proved the external
  configuration remained absent, production remained clean at `34841fe0`, and
  the intended lexical venv path remained available.
- Corrected external-binding creation:
  `20260821T154500724544Z_fd2fc5e4bce4/status.json`. It recorded action
  `created`, matching protected pre/post hash
  `a1277ae068c88fbc4091e86dd40e9ac4296e3735ee7baf1ff2150b7a6fa439d7`,
  Python 3.11.2, `pip check` success, required imports, and equal before/after
  environment fingerprint
  `8821c025a91b16710c92c2224516be791553b08064e8ca9c34225db8ad4dab6a`
  across 311 distributions.
- Path-free `Validate` and idempotent `Configure` passed in
  `20260821T154513555804Z_fd2fc5e4bce4/status.json` and
  `20260821T154527950330Z_fd2fc5e4bce4/status.json`; selection source was
  `configured` without supplying a machine-data root, and the repeated
  Configure action was `unchanged`.
- Final exact-commit Sync and Validate evidence:
  `20260821T154811189188Z_6756b5a099d2/status.json` and
  `20260821T154823375283Z_6756b5a099d2/status.json`. Sync pre/post hash matched
  at `a224373b55fa736975e86e50e6b7801a6a31146c2bbf1461c3c98d680e4e86e0`;
  Validate pre/post hash matched at
  `8271bac9a60af0221253cbf7e697769a7fe0371299eca3ba613d05bef516df31`.
  The production tree remained 66 files at
  `7b168d3c442618c31f0f880b15a093a1f59b9c02deeb2ed025dc681ba933e3bf`
  and the development tree remained 58 files at
  `106baab78923f31026ad9c1c797e1f1ea9a3ffafd7cb384deec1ddc1169a35a6`.
- The external configuration is a mode-600 file owned by `labcraft`, SHA-256
  `35541800b8b15f5d38d3336f397e6996017e44b71c2c1b24e554a0b8ffddf9d7`.
  Production remained clean at `34841fe0`, development was clean/detached at
  `6756b5a0`, both retained worktrees were preserved, and no relevant process
  was running.

## Slice 4 - No-hardware development launch

Status: `verified`

### Objective

Provide the normal Windows-to-Pi development launch using the exact synced
commit, shared interpreter, explicit development data, and simulated machine.

### Required behavior

- Add `Launch` with no-hardware mode as the only supported Slice 4 launch.
- Re-run worktree, dependency, interpreter, data, and process preflight before
  every launch.
- Start the development `tools/run_development_app.py`, not `App.py` directly,
  and preserve the existing persistent development banner.
- Capture the local/Pi commit, production baseline, interpreter, store ID,
  process ID, session evidence path, logs, start/end time, and exit code.
- Provide reliable clean close/teardown behavior without terminating unrelated
  processes.
- Prove serial, cameras, GPIO, balance, firmware/DFU, updater, motion, and
  pressure factories remain blocked and that failure cannot fall back to real
  hardware.
- Do not add or expose an attended hardware switch in this slice.

### Implementation

Call path:

```text
Windows run_pi_development.ps1 Launch
  -> pi_development_workflow.py exact-commit and Slice 3 validation
  -> traced Pi launch supervisor
  -> shared production venv (lexical path, read-only packages)
  -> development worktree tools/run_development_app.py
  -> explicit development machine-data root and hardware-disabled environment
  -> development App.py / authorized bootstrap
  -> development_dependencies(..., hardware_enabled=False)
  -> SimulatedMachine / blocked peripheral factories / updater-disabled UI
  -> clean close, runtime receipt, trace proof, and protected postflight
```

1. Add `Launch` with `Visible|Offscreen` launch modes and bounded timeout/
   auto-close controls; expose no hardware-enable parameter.
2. Reuse Slice 3 validation and require the persisted binding, exact clean
   commits, valid dependency/runtime/store evidence, and no relevant process.
3. Isolate Qt data/config/cache under the development store, report the child
   process, and support development-only qualification auto-close.
4. Assert `SimulatedMachine`, hardware-disabled, and updater-disabled state
   before showing the UI; write structured runtime evidence linked to the
   development-session receipt.
5. Supervise the exact development launcher, preserving external logs, PIDs,
   timestamps, exit status, receipt hashes, and cleanup limited to its own
   process group.
6. Run offscreen qualification in a no-network Bubblewrap sandbox with private
   `/dev`, read-only host root, explicit writable development/session roots,
   and `strace`; trace visible launches without granting hardware mode.
7. Reject forbidden serial, GPIO, camera, I2C, USB/DFU, updater, motion, or
   pressure access and allow only declared development-session/runtime writes.
8. Run focused tests, exact-commit offscreen and visible Pi qualification, then
   the deferred complete default Python suite as the final Slices 1-4 gate.

Planned files:

- `tools/pi_development_workflow.py`
- `tools/run_pi_development.ps1`
- `tools/run_development_app.py`
- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/MachineDataDevelopment.py`
- `tests/test_pi_development_workflow.py`
- `tests/test_development_app_launcher.py`
- `tests/test_app_machine_data_bootstrap.py`
- `tests/test_machine_data_development.py`
- this live document and `README.md`

### Exit criteria

- The Pi displays the application from the exact development commit using the
  existing development store and simulated machine.
- A safe automated/offscreen smoke lane can launch and close without manual
  input; a visible Pi smoke confirms the banner and main window.
- Session evidence names the exact commit and development-store ID.
- Production HEAD/status, machine data, environment, and hardware-access proof
  remain invariant.

### Implementation record

Implemented by `c9ed2fda` with the eager-DFU-probe correction in `eb4d8fcd`.

- Added a Windows `Launch` action with visible and offscreen modes, bounded
  timeout/qualification auto-close controls, persisted-binding-only selection,
  and no hardware-enable option.
- Added a Pi launch supervisor that revalidates the exact commit/config/store,
  runs the development launcher with the shared interpreter, records external
  logs/PIDs/receipts, and limits timeout cleanup to its owned process group.
- The offscreen lane uses Bubblewrap (`--unshare-all`, private `/dev`, read-only
  host root) and both lanes use `strace` to reject physical-device/DFU access.
- The application records a runtime receipt only after proving
  `SimulatedMachine`, all seven blocked peripheral factories, no hardware
  authorization, and updater-disabled composition. Qt state is isolated under
  the development store.
- Local postflight includes the production checkout/source machine data,
  development checkout, retained worktrees, shared interpreter, persisted
  binding, and process state. Only declared development session/runtime files
  may change.

### Validation record

- Focused Windows validation passed before the Pi run (`70 passed in 2.72s`)
  and after the DFU-probe correction (`72 passed in 2.96s`) across
  `test_controller_static_guards.py`,
  `test_pi_development_workflow.py`, `test_development_app_launcher.py`,
  `test_machine_data_development.py`, and
  `test_app_machine_data_bootstrap.py`.
- First exact-commit offscreen attempt reached `SimulatedMachine`, created both
  receipts, auto-closed with exit 0, and preserved production/data/environment,
  but failed closed because the trace found an eager `dfu-util` executable
  availability probe. Root cause: `Controller` imported the DFU implementation
  at module load only to obtain an unused symbol. The eager import was removed
  in `eb4d8fcd`; a static behavior lock prevents its return.
- Corrected offscreen qualification passed with exit 0, no timeout, an empty
  forbidden-hardware match set, and Bubblewrap proving a no-network namespace,
  private `/dev`, and read-only host root. Pi report:
  `20260821T161121Z_7cc6f6af-9649-4f27-b848-69ea56dbc16b/launch.json`,
  SHA-256 `9e26a4587a53a92d4f09421e58582ace0af9c4ebd6399ef71dce53a955cc5f3d`.
- Visible Pi qualification passed with exit 0, no timeout, and an empty
  forbidden-hardware match set. Pi report:
  `20260821T161150Z_10f943b6-2bb5-4f6c-b233-9620bf6718a4/launch.json`,
  SHA-256 `15bd6a5863e223338f4ec9241704fd5e793d9044baeaedcd5849953c991dbfe3`.
- Both passing launches were bound to exact commit `eb4d8fcd`, store
  `be5f7305-9046-4d62-8f7a-4e493859fc80`, and `SimulatedMachine`. Production
  stayed clean at `34841fe0`; environment fingerprint stayed
  `8821c025a91b16710c92c2224516be791553b08064e8ca9c34225db8ad4dab6a`;
  production source machine-data stayed
  `95ec35376ea0e99da1cf5d3c852d57765451a529f153292fb0ef8d5b2fe1198a`.
  The local protected launch invariant matched before/after at
  `f539fe72518bf27bad662c5a52b03475e0639dbf92da7687c3d2faa64ffe3e38`.
  Only declared session/runtime/cache paths changed and no relevant process
  remained.
- The first final-suite invocation incorrectly placed `--basetemp` inside the
  repository, so 33 SIL tests correctly rejected overlapping session roots
  (`5,489 passed`, `156 skipped`). A representative failure passed under the OS
  temporary directory. The corrected single final gate then passed:
  `5,522 passed, 156 skipped` in `360.84s`.

## Slice 5 - Isolated development firmware HIL

Status: `in_progress`

Harden the existing Windows firmware HIL path so it uses the committed binary
from the exact development worktree, verifies Windows/Pi SHA-256 identity,
writes reports outside Git, defaults to SAFE, and never uploads or writes into
the production checkout. This is the first slice allowed to flash firmware and
uses the operator-authorized unattended SAFE-only lane, and requires a
known-good released binary for rollback.

### Call path

```text
Windows development-firmware wrapper
  -> exact clean/pushed feature commit and tracked artifact
  -> external-evidence SSH supervisor
  -> clean/detached Pi development worktree at the exact commit
  -> development flash_and_test.sh with exact SAFE-only arguments
  -> DFU BOOT/RESET and exact development firmware artifact
  -> tools/run_selftest.py --profile SAFE
  -> strict SAFE report/gated-actuation validator
  -> verified rc.5 tag/protected recovery artifact
  -> second DFU flash and SAFE validation
  -> released-firmware postcondition and protected invariance
```

### Concrete implementation plan

1. Add a strict SAFE contract/report validator that requires profile `SAFE`, a
   passing non-aborted report, the known non-actuating result inventory, and
   `profile=SAFE`, `executed=0`, `gate=safe_only` plus zero actuation metrics
   for every motion/pressure/valve/pulse/FULL gate.
2. Add a Windows-to-Pi firmware supervisor and PowerShell wrapper that expose
   only the autonomous round-trip action and write all session inputs, logs,
   reports, and receipts beneath external development-workflow roots.
3. Require a clean/pushed Windows commit, clean/detached exact Pi development
   commit, tracked byte-identical Windows/Pi development artifact, and a
   release tag/manifest/protected-checkout recovery artifact with matching
   SHA-256 before the first flash.
4. Reuse the Slice 1-4 production/data/environment/process inventory and fail
   closed on dirty worktrees, ambiguous bindings, package drift, or a running
   app/updater/DFU/HIL process.
5. Invoke only the exact development `flash_and_test.sh` with `--profile SAFE`,
   no selector/benchmark/FULL flags, explicit artifact/report/log/DFU paths,
   and bounded timeouts; validate its structured report.
6. Once a development flash starts, always attempt the prevalidated released
   artifact restore and require a second valid SAFE report before returning
   success or moving to another slice.
7. Add focused success, provenance/hash/refusal, mislabeled-actuation,
   development-failure, restore-failure, process, and invariance tests; update
   operator documentation and set the legacy general HIL wrapper default to
   SAFE.
8. Run focused tests and required firmware checks/build, commit/push/sync the
   exact feature revision, then perform the autonomous LC-001 development SAFE
   and released-restore SAFE qualification with sealed evidence.

Planned files:

- `tools/firmware_safe_hil.py`
- `tools/pi_development_firmware.py`
- `tools/run_pi_development_firmware.ps1`
- `firmware/scripts/run_fw_hil_windows.ps1`
- `tests/test_firmware_safe_hil.py`
- `tests/test_pi_development_firmware.py`
- `README.md`
- this live document

### Implementation record

- Added `tools/firmware_safe_hil.py`, a dependency-free validator for both the
  committed source contract and the exact plain-SAFE report inventory. It
  rejects FULL, selectors/extra IDs, missing terminal rows, failed/aborted
  runs, any executed FULL gate, any nonzero actuation metric, and an armed or
  faulted flash path.
- Added `tools/pi_development_firmware.py` and the PowerShell wrapper. They bind
  the Windows artifact to exact HEAD, the recovery artifact to the rc.5 tag,
  release manifest, and protected-checkout bytes, then supervise only a fixed
  development SAFE -> released restore SAFE sequence with external evidence.
- The remote supervisor rechecks clean exact worktrees, the persisted workflow
  binding, interpreter, serial port, `dfu-util`, artifact bytes, release
  provenance, and conflicting processes immediately before flashing. Once the
  development stage starts, released restoration runs from `finally` even when
  development flash/SAFE fails.
- Changed the legacy general HIL wrapper default from FULL to SAFE and
  documented why it remains unsuitable for the isolated autonomous lane.
- Added focused behavior-lock tests for the SAFE inventory, gate/flash metrics,
  release provenance, external paths, fixed remote command, mandatory restore,
  wrapper dry-run, and legacy default.

### Validation record

- Read-only baseline:
  `verification_reports/development-workflow/status/20260821T172150640478Z_e74a4d19c7d1/status.json`.
- Development, protected-checkout, and rc.5-tag artifacts are currently
  byte-identical at SHA-256
  `eda070ce734d5167f0795faf30df461c8a07341e09ca698de9d850315b0d5884`.
- Source inspection proves default SAFE selects profile value `0`; firmware
  treats only value `1` as FULL. SAFE reports the eleven FULL actuation rows as
  `executed=0` with zero motion/pressure/valve/pulse/abort metrics.
- Focused Slice 5 tests: 19 passed. The first combined rerun reached 18 passes
  before Windows denied pytest's shared temporary root; the exact rerun with a
  unique explicit test-data directory passed 19/19.
- Existing workflow plus SAFE-contract regression gate: 64 passed.
- Required firmware checks: 461/461 host tests passed; Debug headless build
  completed with zero errors and copied the same-build artifact to the tracked
  artifact path. The sandboxed first attempt was blocked by Visual Studio
  FileTracker access; the identical approved unsandboxed command passed.
- The rebuilt development artifact SHA-256 is
  `f8aa5080f387b8abb982e8afda156550295d0992b8e2ac919dd7b101da207842`;
  the independently bound rc.5 recovery artifact remains
  `eda070ce734d5167f0795faf30df461c8a07341e09ca698de9d850315b0d5884`.
- Exact commit/push/sync and autonomous Pi development SAFE -> released SAFE
  qualification initially ran from `3719838c`. Both flash commands exited zero
  and both reports passed 30/30, but the new validator rejected both because it
  required late flash metrics beyond the protocol's bounded metrics payload.
  The supervisor therefore conservatively reported `recovery-required` at
  `verification_reports/development-workflow/firmware/20260821T173630117947Z_85732caa-0bcc-4a03-b1a0-700268826daf/roundtrip.json`.
- The sealed development and released reports both state
  `skipped_no_flash_task=1`, `cycles_started=0`, `cycles_timeout=0`, and zero
  transmitted flash/output counters. The corrected validator accepts that
  direct no-task/zero-dispatch contract; if a flash task exists it still
  requires the later explicit session/output-disarmed fields and fails closed
  when bounded evidence omits them. Both sealed reports now validate, proving
  the failed transaction ended on the exact rc.5 artifact with passing SAFE,
  unchanged protected invariants, and no related process.
- Corrective focused tests: 20 passed. A clean exact-commit rerun passed from
  `816e0e70` at
  `verification_reports/development-workflow/firmware/20260821T174039746624Z_6f17c466-125f-4057-b1bb-50837e3f2c03/roundtrip.json`.
  Development artifact `f8aa...` and rc.5 artifact `eda0...` each flashed with
  exit 0 and passed the exact 30-result SAFE inventory using the
  no-flash-task/zero-dispatch contract. The final role is released, no related
  process remains, and pre/post protected invariant SHA-256 values are equal at
  `52611856026f53872a86b5159bf5d21f09922a37527644a9dcb34f965b33e80b`.

## Slice 6 - Attended hardware development launch

Status: `in_progress` (successful hardware launch remains attended/deferred)

Add an explicit attended hardware launch that requires operator identity,
exact hardware confirmation, a clear motion envelope, and firmware evidence
matching the development commit when firmware changed. Real hardware may be
used, but configuration/history remain in the development store and updater
and in-app DFU remain blocked.

### Call path

```text
Windows hardware-development wrapper
  -> exact clean/pushed feature commit and tracked firmware artifact
  -> external-evidence Pi policy supervisor
  -> clean/detached exact development worktree + persisted store binding
  -> durable firmware-state reader and commit/artifact compatibility policy
  -> exact attended + clear-envelope authorization receipt
  -> shared production interpreter (read only)
  -> tools/run_development_app.py --enable-hardware
  -> App.py development bootstrap
  -> MachineDataDevelopment authorization/state recheck
  -> ApplicationComposition.development_dependencies(hardware_enabled=True)
  -> real Machine/serial/camera factories with updater/DFU still blocked
  -> View connection request -> Controller.connect_machine
  -> Machine_FreeRTOS.connect_board -> firmware protocol session
```

Autonomous Slice 6 qualification stops before the authorization-receipt and
successful launch steps. It does not connect the board or call any firmware
handler.

### Concrete implementation plan

1. Add a strict read-only firmware-state schema/compatibility reader. If the
   development and released artifacts differ, only exact development role,
   commit, artifact, flash transaction, and SAFE evidence may authorize launch;
   unknown/recovery-required/stale/corrupt state blocks.
2. Add a short-lived external hardware-authorization receipt bound to operator,
   exact commit, development store/root, firmware-state file/hash, artifact,
   and hashes of both exact confirmation phrases.
3. Harden `run_development_app.py` and `MachineDataDevelopment` so hardware mode
   requires and independently revalidates that receipt, the clear-envelope
   confirmation, and current firmware-state bytes; no-hardware behavior remains
   unchanged and updater access remains false.
4. Add a Windows/Pi hardware-development supervisor and PowerShell wrapper for
   `preflight`, `cancel`, and `launch`; reuse exact commit/store/environment/
   process/protected-invariant checks and expose no fallback data/code paths.
5. For launch, create evidence externally, use the shared interpreter, supervise
   only the owned process group with a bounded timeout, record normal/canceled/
   failed cleanup, and compare protected postflight before success.
6. Add focused tests for missing/expired/tampered authorization, missing clear
   envelope, stale/unknown/recovery firmware, released/development compatibility,
   mismatched commit/artifact/store/operator, cancellation, no-hardware misuse,
   process conflict, timeout ownership, updater/DFU blocking, and invariance.
7. Commit/push/sync the exact Slice 6 revision and qualify dry-run, preflight,
   missing-confirmation, stale/mismatched state, cancellation, and no-hardware
   rejection paths on the Pi without starting the hardware-enabled app.
8. Mark Slice 6 `implementation_complete`; defer its one successful visible
   hardware-enabled launch to the final attended campaign after Slice 7 can
   durably set and restore firmware state.

Planned files:

- `tools/firmware_state.py`
- `FreeRTOS-interface/DevelopmentHardwareAuthorization.py`
- `FreeRTOS-interface/MachineDataDevelopment.py`
- `tools/run_development_app.py`
- `tools/pi_development_hardware.py`
- `tools/run_pi_development_hardware.ps1`
- `tests/test_firmware_state.py`
- `tests/test_development_hardware_authorization.py`
- `tests/test_machine_data_development.py`
- `tests/test_development_app_launcher.py`
- `tests/test_pi_development_hardware.py`
- `README.md`
- this live document

### Implementation record

- Added the strict schema-v1 firmware-state reader and hardware-compatibility
  policy. It never infers installed firmware from Git and blocks unknown,
  recovery-required, wrong-machine, stale-commit, or mismatched-artifact state.
  Released state is accepted only when development/released bytes are
  identical; different firmware requires exact development role and commit.
- Added a five-minute external authorization receipt bound to operator, commit,
  store ID/root, current firmware-state path/hash, development/released artifact
  hashes, and both confirmation hashes. App bootstrap rehashes the firmware
  state immediately before composing hardware-capable dependencies.
- Hardened the development launcher and environment parser. Hardware mode now
  requires exact attended and clear-envelope confirmations, exact commit, and
  external authorization; supplying hardware inputs in no-hardware mode is
  rejected. Session evidence records the authorization ID and updater access
  remains disabled.
- Added the Windows/Pi `preflight`, `cancel`, and explicit `launch --execute`
  supervisor. It reuses exact checkout/store/environment/process checks,
  rehashes both Pi artifacts, writes only external evidence, owns only its
  launched process group, and checks protected postflight.
- Added focused schema, compatibility, expiry/tamper, launcher, composition,
  wrapper, and supervisor construction/refusal tests.

### Validation record

- Slice 5 final released-state evidence is the starting firmware precondition.
- Successful hardware-enabled application launch is explicitly deferred.
- Focused Slice 6 automated gate: 37 passed.
- Exact commit/push/sync and Pi refusal qualification remain pending.

## Slice 7 - Firmware state and production restoration

Status: `planned`

Record when development firmware is active, prevent the workflow from
declaring production readiness in that state, and add a released-firmware
restore action that verifies the release artifact, flashes it, runs its SAFE
self-test, and clears the development marker only after success. A future
released production startup guard will consume this state.

## Slice 8 - End-to-end qualification and runbook

Status: `planned`

Run the complete failure/success matrix on Windows and LC-001, seal evidence,
and document daily no-hardware development, firmware HIL, attended hardware
testing, failure recovery, and released-firmware restoration.

## Decision log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-08-21 | Keep production and development code in separate linked Pi worktrees. | Each worktree has independent files, index, and HEAD while sharing Git history; experimental commits never replace the protected checkout. |
| 2026-08-21 | Use detached exact commits on the Pi development worktree. | Qualification remains bound to an immutable commit even if the Windows branch later advances. |
| 2026-08-21 | Reuse the production virtual environment read-only when dependency declarations match. | Avoids repeated Pi environment creation while preventing development package changes from altering production. |
| 2026-08-21 | Keep machine data outside all worktrees and pass the development root explicitly. | Worktree switching cannot select or seed machine-specific configuration. |
| 2026-08-21 | Make no-hardware the only launch through Slice 4. | Worktree/runtime/data orchestration can be qualified before any physical capability is introduced. |
| 2026-08-21 | Keep firmware flashing separate from the development app launcher. | The installed STM32 image is global machine state and requires an attended HIL and rollback path. |
| 2026-08-21 | Permit unattended firmware flashing only for exact development/released artifacts followed by the non-actuating SAFE profile and mandatory released restore. | The operator explicitly authorized DFU/BOOT/RESET/serial SAFE access while continuing to prohibit FULL, motion, pressure, camera, and balance activity. |
| 2026-08-21 | Run focused tests for each remaining slice and defer the next complete default suite to final Slice 4 validation. | Avoid repeated six-minute full-suite runs while preserving one final broad regression gate. |
| 2026-08-21 | Hash the complete production and development machine-data trees during workflow collection. | The current stores are only 4.3 MB/66 files and 3.2 MB/58 files, so direct content evidence is inexpensive and stronger than relying on creation-time marker provenance. |

## Findings log

| Date | Finding | Impact |
| --- | --- | --- |
| 2026-08-21 | Existing development-store and launcher code already provide verified cloning, explicit root selection, no-hardware defaults, hardware confirmation, and session evidence. | Slices 1-4 should orchestrate these controls rather than replace them. |
| 2026-08-21 | Existing PowerShell SSH workflows already provide strict mode, shell literal handling, identity support, BatchMode, dry-run support, and fake-SSH tests. | Reuse their conventions and test patterns. |
| 2026-08-21 | The existing firmware HIL wrapper defaults to `/home/labcraft/LabCraft_printer` and uploads tracked files there. | It must not be used for development until Slice 5 isolates it from production. |
| 2026-08-21 | Direct `.ps1` execution is disabled by the current Windows execution policy. | Documentation and qualification use `powershell -ExecutionPolicy Bypass -File`, matching existing repository workflows. |
| 2026-08-21 | `Path.resolve()` turns the Pi venv's `env/bin/python` symlink into `/usr/bin/python3.11`; invoking that resolved target bypasses the venv. | Preserve the absolute lexical interpreter path for execution and configuration, while resolving repository/data paths for separation checks. |
| 2026-08-21 | No-hardware startup still imported `dfu_update.py`, whose module-level executable discovery probed `dfu-util`. | Remove the unused eager import; the trace now proves neither DFU executable discovery nor physical-device access occurs during development startup. |
| 2026-08-21 | SIL tests reject pytest session roots located beneath the repository. | Final full-suite runs must use a unique OS temporary directory, not an in-repository `--basetemp`. |

## Change log

| Date | Change |
| --- | --- |
| 2026-08-21 | Created the live eight-slice workflow, concrete Slice 1 plan, Slices 2-4 implementation contract, and continuous Goal prompt. |
| 2026-08-21 | Began Slice 1 implementation on `feature/pi-development-workflow`. |
| 2026-08-21 | Completed Slice 1 implementation and automated validation; clean/pushed Pi invariance qualification remains. |
| 2026-08-21 | Published `e58129b3` and marked Slice 1 verified after clean/pushed Preflight and exact Pi-state invariance passed. |
| 2026-08-21 | Began Slice 2 exact-commit development-worktree synchronization implementation. |
| 2026-08-21 | Completed Slice 2 implementation and focused validation; deferred the full suite to final Slice 4 per operator direction. |
| 2026-08-21 | Published `4bef5790` and marked Slice 2 verified after Pi create/reuse/refusal and protected-invariance gates passed. |
| 2026-08-21 | Began Slice 3 shared-runtime and external development-data binding; focused validation passed and Pi qualification remains. |
| 2026-08-21 | Slice 3 Pi Configure failed safely before writing configuration, revealing and correcting venv-symlink resolution; focused correction tests passed. |
| 2026-08-21 | Verified Slice 3 after corrected create, path-free validation, idempotent reuse, shared-environment fingerprinting, and direct production/development data-tree invariance passed on LC-001. |
| 2026-08-21 | Began Slice 4 no-hardware development launch implementation with offscreen sandbox/trace proof and a visible traced smoke lane. |
| 2026-08-21 | Published `c9ed2fda`, found and corrected the fail-closed eager DFU probe in `eb4d8fcd`, then passed focused, offscreen, visible, protected-invariance, and corrected full-suite gates; marked Slice 4 verified. |
| 2026-08-21 | Began Slice 5 isolated SAFE-only development-firmware round-trip implementation after confirming exact artifact and SAFE non-actuation contracts. |

## Goal prompt for Slices 1-4

Copy the complete prompt below into a new request when ready to begin. It
explicitly authorizes continuous progress through Slices 1-4; no additional
prompt is required between slices.

```text
Create and pursue a goal to plan, implement, test, commit, and qualify Slices
1 through 4 of docs/pi_development_workflow_plan.md sequentially. Continue
autonomously from one verified slice to the next without waiting for another
prompt. Use the live document as the authoritative contract and update its
status, implementation commit, validation commands/results, findings,
decisions, and change log as work progresses.

For each slice:

1. Reinspect the relevant code and current Windows/Pi state, restate the call
   path, create a decision-complete implementation plan of no more than eight
   steps, and list the exact files before editing.
2. Implement the smallest safe slice with behavior-lock and failure-path tests.
3. Run focused tests for each slice and the complete default Python suite once
   at final Slice 4 validation. Diagnose and fix in-scope failures instead of
   stopping at the first failure.
4. Run the slice's specified qualification on LC-001 over SSH, prove all
   production invariants, and preserve the resulting evidence.
5. Update the live document and create one dedicated descriptive commit for
   that slice only.
6. Push only the dedicated feature branch when the Pi needs the new exact
   commit. Never push main, stable, or a release tag. Continue immediately to
   the next slice after the commit and required qualification pass.

Start from the current clean Windows repository. Create and use a dedicated
feature branch named feature/pi-development-workflow unless an equivalent
dedicated branch is already active. You are authorized to commit each slice
and push that feature branch to origin so the Pi can fetch its exact commits.

Use LC-001 at labcraft@192.168.0.33 with the Windows identity file
verification_reports\pi_sil_codex_network_ed25519. You are authorized to
perform the following bounded Pi changes required by Slices 1-4:

- Create and register /home/labcraft/LabCraft_printer-dev as a linked,
  detached development worktree.
- Fetch and select exact pushed feature-branch commits only in that worktree.
- Create the external development-workflow configuration required by Slice 3.
- Reuse /home/labcraft/LabCraft_printer/env/bin/python strictly read-only.
- Validate and use the existing development machine-data store at
  /home/labcraft/.local/share/LabCraft/LabCraft Printer/development/main-65ba38df-machine-data.
- Launch and close the Slice 4 development application only in its no-hardware
  simulated mode.
- Write ignored/local development reports, logs, and session evidence in the
  locations defined by the live plan.

The following boundaries are mandatory throughout this goal:

- Do not move, switch, reset, clean, update, or write into the protected
  /home/labcraft/LabCraft_printer worktree.
- Do not remove or repurpose any existing retained worktree.
- Do not install, remove, or update packages in the shared virtual environment.
- Do not read or write production machine data through the development app,
  and do not copy development changes back into production data.
- Do not access serial, cameras, GPIO, balance, firmware/DFU, updater, motion,
  pressure, or any other physical-hardware factory. Slices 1-4 are strictly
  no-hardware.
- Do not flash firmware, change the device protocol, change release metadata,
  create or move tags, publish a release, or push main/stable.
- Do not use destructive Git or filesystem recovery. If a worktree is dirty or
  a target path is ambiguous, fail closed and investigate without deleting or
  resetting user data.
- Do not treat a Git checkout as changing installed STM32 firmware.

Before and after every Pi mutation or launch, capture and compare the protected
production HEAD/status, registered worktrees, production and development
machine-data evidence, shared-environment evidence, and relevant processes.
Slice 4 must include automated hardware-access proof plus a no-hardware Pi
launch/close qualification. No motor-power or attended hardware authorization
is granted by this goal.

Provide concise commentary updates during long-running work. Ask for user input
only if progress requires authority outside the boundaries above, a genuinely
destructive action, physical hardware access, firmware flashing, a release
operation, credentials that are unavailable, or an ambiguity that cannot be
resolved safely from the repository and Pi. Test failures, implementation
difficulty, and the transition between slices are not reasons to pause.

Complete the goal only after Slices 1, 2, 3, and 4 are each marked verified in
the live document, each has its own commit, all required Windows and Pi gates
pass, the protected production checkout/data/environment remain invariant, and
the final handoff reports commits, tests, Pi evidence, risks, and rollback.
```
