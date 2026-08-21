# Droplet Printer Repository - Agent Instructions

## Mission

This repository controls a physical droplet printer. Changes must be safe,
minimal, reviewable, and verifiable. Maintain high confidence in both the
Python application under `FreeRTOS-interface/` and the STM32 firmware under
`firmware/`.

## Instruction routing

Instructions are layered. Before changing a scoped area, read its nested file
even when the agent session started at the repository root:

- `FreeRTOS-interface/AGENTS.md` for application, MVC, machine-data, motion,
  pressure, camera, balance, or hardware-composition changes.
- `firmware/AGENTS.md` for anything under `firmware/` or any firmware build,
  artifact, flash, self-test, or HIL tooling.
- `tools/AGENTS.md` for Pi development wrappers, firmware-state tooling,
  migration/update tooling, remote workers, or operational evidence.

The root rules continue to apply unless a nested file explicitly specializes
them.

## Repository map

- `FreeRTOS-interface/`: Qt application, MVC layers, machine communication,
  configuration, calibration, and development/production composition.
- `firmware/`: STM32CubeIDE project, host tests, build scripts, HIL support,
  and the tracked deployable binary.
- `tools/`: development workflow, firmware-state, update/migration, test, and
  operational wrappers.
- `tests/`: Python unit, integration, SIL, and workflow tests.
- `docs/`: release, migration, development-workflow, and implementation plans.
- `Documentation/`: operator and hardware documentation.

## Non-negotiable safety rules

- Never propose or perform a destructive action that could risk hardware or
  machine-specific data.
- Do not change device protocol formats, opcodes, payload layouts, or parsing
  rules unless the user explicitly requests a protocol change.
- Do not bypass dirty-tree, identity, data-root, artifact, process,
  firmware-state, recovery, or authorization blockers.
- Do not treat a Git checkout as evidence of installed firmware.
- Do not manually edit durable machine-data pointers, manifests, receipts, or
  firmware-state JSON to force a workflow to pass.
- Prefer small, incremental diffs. Preserve unrelated user changes.
- Motion, homing, pressure, pumps, valves, dispensing, cameras, balances, and
  timing-sensitive behavior require explicit verification and rollback plans.

## Required working method

For each implementation task:

1. Inspect the relevant call path and current state.
2. Before editing, state a plan of at most eight steps and list expected files.
3. Implement the smallest viable slice with failure-path coverage.
4. Run focused tests for the affected behavior.
5. Run broader or full-suite validation only for final integration/release
   gates, when the risk warrants it, or when the user explicitly requests it.
6. Summarize files changed, validation, risks/edge cases, and rollback steps.

If the task crosses application layers, follow the detailed call-path rules in
`FreeRTOS-interface/AGENTS.md`.

## Windows and Pi development model

Windows is the source of development commits. Pi development uses a separate
linked worktree and external machine data. The deployed production checkout is
not a general development checkout.

Authoritative operational documentation:

- `README.md`: current copyable wrapper commands and prerequisites.
- `docs/pi_development_workflow_plan.md`: complete safety contract, evidence,
  recovery procedure, and attended campaign.
- `docs/release_process.md`: release metadata, validation, and tag procedure.

Stable Pi roles:

- Protected production worktree: `/home/labcraft/LabCraft_printer`.
- Isolated development worktree: `/home/labcraft/LabCraft_printer-dev`.
- Shared interpreter: production `env/bin/python`, reused read-only only while
  dependency declarations match.
- Development machine data and workflow configuration: external to every Git
  worktree and selected through the persisted development-workflow binding.

### Development rules

- Commit and push the exact Windows development revision before Pi sync or
  qualification.
- Use `tools/run_pi_development.ps1` for status, sync, validation, and
  no-hardware launches. Do not manually fetch, checkout, switch, reset, clean,
  or write inside the protected production worktree.
- The Pi development worktree must be clean and detached at the exact pushed
  commit. Do not repurpose or remove retained worktrees.
- Never install, remove, or update packages in the shared production virtual
  environment. Dependency drift is a blocker, not permission to mutate it.
- Development must use the configured external development machine-data store.
  Never fall back to, seed from, or write through production machine data
  during a development launch.
- Use `Status -> Sync -> Validate` before a Pi development launch. Resolve any
  blocker rather than bypassing it. An explicitly documented retained-worktree
  warning is not itself a blocker.
- Use wrapper-generated external evidence. Do not place logs, uploads, runtime
  files, reports, or firmware state in either Git worktree.

### Qualification lanes

| Lane | Physical capability | Authority | Required ending state |
| --- | --- | --- | --- |
| Windows focused tests | None | Normal development | Pi unchanged |
| Pi no-hardware launch | Simulated machine only | Normal development | Released firmware unchanged |
| Firmware SAFE roundtrip | DFU/reset/serial and non-actuating SAFE only | Explicit SAFE-flash authority | Exact released firmware plus SAFE |
| Hardware-capable launch | Real hardware factories available | Fresh attended confirmation for that campaign | Exact released firmware plus SAFE |

- No-hardware is the default Pi application lane.
- Use `tools/run_pi_development_firmware.ps1` only within the authority granted
  for the current task. Autonomous work may use only the fixed SAFE roundtrip
  and must restore released firmware before yielding.
- Use `tools/run_pi_development_hardware.ps1` for hardware preflight,
  cancellation, and attended launch. Do not invoke the hardware-capable
  development launcher directly.
- Never run FULL or an actuating HIL profile unattended.
- Hardware-capable development requires a fresh operator identity and exact
  attended confirmation from the human for the current campaign. Do not reuse
  a confirmation from another campaign or infer authority for motion,
  pressure, dispensing, camera, or balance operations.
- After any attended development activation or hardware launch, immediately
  run exact released restoration and a final read-only status check.
- If released restoration cannot reach verified released plus SAFE, do not
  launch either application. Preserve evidence and request assistance.

## Python commands

Use the repository Windows environment directly:

- Focused tests: `.\env\Scripts\python.exe -m pytest -q <test paths>`
- Default full suite: `.\env\Scripts\python.exe -m pytest -q`
- Analysis-pipeline lane, only when applicable:
  `.\env\Scripts\python.exe -m pytest -q --run-analysis-pipeline tests\test_plate_reader_analysis.py`

Use a unique OS temporary directory outside the repository for pytest
`--basetemp` when SIL/workflow tests create session roots. Allow at least 15
minutes for a full-suite tool timeout. Do not use `py -m pytest` unless the
Windows launcher has first been proven usable in the current environment.

Do not invoke the Pi production application directly for development. Use the
documented wrapper so code, data, runtime mode, and evidence remain explicit.

## Firmware routing

Before any firmware source, build, artifact, flash, self-test, or HIL-tool
edit, read `firmware/AGENTS.md` and restate its validation commands. The
mandatory local firmware gate is:

`powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`

Every firmware milestone commit must include
`firmware/artifacts/LabCraft_firmware.bin` rebuilt from the same source and
configuration. Other build outputs remain untracked.

## Documentation and release policy

- Update `README.md` or the relevant scoped README when test/build/workflow
  tooling, prerequisites, commands, evidence, or recovery behavior changes.
- Before changing `VERSION`, `CHANGELOG.md`, `releases/latest.json`, release
  manifests, update bundles, or release tags, read `docs/release_process.md`.
- Never move, delete, or retarget an existing release tag.
- Do not push `main`, `stable`, or a release tag unless the user explicitly
  authorizes that release operation.

## Git and artifact discipline

- One milestone or coherent fix per commit. Keep messages specific.
- Do not commit virtual environments, `__pycache__`, logs, IDE/workspace
  metadata, pytest output, or transient evidence.
- Preserve a dirty worktree and unrelated edits. Do not reset, clean, or
  overwrite them to simplify a task.

## Code review rules

Flag the following as safety regressions and identify the stated safe path:

- Development code or data can fall back to production. Safe path: require the
  exact detached development commit and explicit external development store.
- A tool writes inside or changes the protected production worktree. Safe path:
  use read-only inventory and external development-workflow locations.
- Cleanup can signal a process it did not create. Safe path: record and manage
  only the owned process group with bounded escalation.
- SAFE/FULL selection is ambiguous or an actuating profile is a default. Safe
  path: fixed SAFE-only autonomous inventory; attended explicit scope for any
  actuation.
- Firmware readiness is inferred from Git or state validation is bypassed.
  Safe path: verify durable state, artifact bytes, flash evidence, and SAFE.
- A development flash or hardware launch lacks mandatory released restoration.
  Safe path: prevalidate recovery and restore/SAFE before completion.
- Configuration or calibration can be silently overwritten. Safe path: guarded
  transactions, verification, history, and external backups.

## If uncertain

Stop and report what was inspected, two or three plausible interpretations,
and the information needed to disambiguate. Do not guess when the choice could
change hardware behavior, machine data, firmware recovery, or release state.

## Definition of done

- Focused automated tests for the affected area pass.
- Required scoped firmware/application/tool instructions were followed.
- Higher-level validation is completed when required by risk or release scope.
- Pi qualifications, when authorized, preserve protected invariants, evidence,
  released firmware, and zero related processes.
- Protocol/schema and operator-facing behavior changes are documented.
- The handoff reports changes, validation, risks, rollback, and next steps.
