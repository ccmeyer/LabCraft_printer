# Droplet Printer Repo — Agent Instructions (Root)

## Mission
This repository controls real hardware (droplet printer). Changes must be safe, minimal, and verifiable.
Primary current goal: **add automated tests** so future changes are safer and regressions are caught early.

## Repo layout
- `FreeRTOS-interface/`
  - `App.py` — application entry / orchestration (likely creates MVC objects and starts UI/event loop)
  - `Controller.py` — mediates View ↔ Model ↔ machine comms
  - `Model.py` — state, configuration, experiment definitions, business logic
  - `View.py` — UI layer (likely PySide6/Qt or similar)
- `firmware/`
  - `Inc/` — headers
  - `Src/` — source
- `Documentation/` — manuals/parts docs
- `requirements.txt`
- `README.md`

## Safety / guardrails (non-negotiable)
- **Never perform destructive actions** on the user’s machine. Do not propose anything that could risk hardware damage.
- **Do not change the device protocol** (message formats, opcodes, parsing) unless explicitly requested.
- Avoid large refactors. Prefer small, reviewable diffs.
- Any change that crosses MVC layers must begin with a short plan and a list of files to touch.
- If a change might affect motion/pressure control, include explicit verification steps and “how to revert”.

## Working style (required)
For each task:
1) **Locate call path first** (UI action → Controller → Model → comms → firmware handler).
2) Propose a plan (≤8 steps) and list files to touch **before editing**.
3) Implement the smallest viable slice.
4) Run tests (and/or provide a short manual checklist).
5) Summarize: what changed, why, how to validate, and any risks.

## Environment setup (Python)
Assume Windows + VS Code unless stated otherwise.

### Create venv (if needed)
- Windows PowerShell:
  - `py -m venv .venv`
  - `.\.venv\Scripts\Activate.ps1`
  - `python -m pip install -U pip`
  - `pip install -r requirements.txt`

### Run the app (fill in once confirmed)
Preferred: run using the selected VS Code interpreter (`.\.venv\Scripts\python.exe`).
- `<fill this in>` Example candidates:
  - `python FreeRTOS-interface/App.py`
  - `python -m FreeRTOS-interface.App` (only if it’s a package)
If uncertain, consult `README.md` and report what you found.

## Testing strategy (high priority)

### Guiding principles
- Start with **fast, deterministic tests** that run without hardware.
- Put the hardware boundary behind interfaces and use fakes/mocks.
- Favor tests of **Model + Controller logic** first; View/UI tests are optional later.
- Add regression tests for each bugfix (test fails before fix, passes after).

### Phase 1: Python unit tests (no hardware)
Goal: runnable test suite on every machine without needing the printer connected.

**Preferred framework:** `pytest` (recommended) or built-in `unittest` if adding deps is not allowed.
- If `pytest` is not in `requirements.txt`, propose adding:
  - `pytest`
  - optionally `pytest-mock` (helpful)
  - optionally `pytest-qt` if UI tests are later desired (do not add initially unless asked)

**Test folder convention**
- Add `tests/` at repo root OR `FreeRTOS-interface/tests/` (choose one and be consistent).
- Keep tests focused and name them `test_<thing>.py`.

**Hardware boundary**
- Identify the comms layer used to talk to the MCU (serial/USB/etc).
- Create a small interface/adapter (if not present) so Controller uses a `Comm` object with predictable methods.
- Provide a `FakeComm` for tests:
  - captures outgoing commands
  - can return canned status messages
  - can simulate timeouts/errors

**Core test targets (initial)**
- Model invariants:
  - configuration parsing/validation (JSON/settings files if any)
  - experiment state transitions
  - droplet calibration computations (pure functions)
- Controller logic:
  - correct commands enqueued for user actions
  - correct handling of status updates / error states
  - correct sequencing logic (queue ordering, retries, abort paths)
- Serialization/parsing (very important):
  - test encode/decode for each message type
  - golden test vectors stored in fixtures

### Phase 2: Integration tests (still no hardware)
- Run `App` in a “headless/simulated mode” if possible (no actual serial).
- Verify key workflows end-to-end using FakeComm:
  - connect → home → move → print sequence (simulated) → disconnect
- Validate that a status update from MCU correctly updates Model/UI state (as far as possible without rendering UI).

### Phase 3: Firmware tests (optional, later)
Firmware unit testing is valuable but usually heavier to bootstrap.
Do not start this unless requested; if requested, propose one of:
- Unity/Ceedling
- CppUTest
- PlatformIO native tests (if using PlatformIO)

Minimum firmware test targets:
- message parsing / command dispatch
- safety interlocks (limit switch logic, bounds checks)
- math-only utilities (timing, conversion, PID helpers)

## Command list for agents (keep updated)
If these aren’t available yet, agents should propose adding them.

### Tests
- `python -m pytest -q`  (if using pytest)
- OR `python -m unittest` (if using unittest)

### Lint/format (optional but recommended later)
Only propose once tests exist:
- `ruff` (lint + formatting) OR `black` + `flake8`
- Keep tooling minimal; avoid bikeshedding.

## Documentation expectations
- When adding a new test harness, update `README.md` with:
  - how to run tests
  - any environment requirements
- If you discover undocumented run steps, add them to `README.md`.

## Git / commits
- One milestone per commit.
- Keep commits small and descriptive, e.g.:
  - `test: add FakeComm and controller command tests`
  - `test: add protocol encode/decode golden vectors`
- Do not commit local artifacts:
  - `.venv/`, `__pycache__/`, logs, build outputs, device dumps

## What to do when uncertain
- If repo behavior is unclear (entrypoint, protocol formats, threading model), **stop and ask** by producing:
  - what you inspected
  - 2–3 plausible interpretations
  - what information would disambiguate

## Default “definition of done” for any PR
- Tests run locally and pass (or explain why hardware prevents it and propose a simulation test)
- No protocol changes unless explicitly requested
- Summary includes:
  - files changed
  - risk assessment
  - validation steps
  - rollback steps (how to revert)