# Droplet Printer Repo — Agent Instructions (Root)

## Mission
This repository controls real hardware (droplet printer). Changes must be safe, minimal, reviewable, and verifiable.
Primary goal: **maintain high confidence via automated tests** for both:
- the Python MVC application (`FreeRTOS-interface/`)
- the STM32 firmware (`firmware/`)

## Repo layout (high level)
- `FreeRTOS-interface/`
  - `App.py` — application entry/orchestration
  - `Controller.py` — mediates View ↔ Model ↔ comms
  - `Model.py` — state, configuration, experiment logic
  - `View.py` — UI layer (Qt/PySide-style)
  - `Machine_FreeRTOS` — Object responsible for communicating with the actual machine
- `firmware/`
  - STM32CubeIDE project (contains `.project/.cproject/.ioc` etc.)
  - `tests_host/` — host unit tests (CppUTest + CMake)
  - `third_party/cpputest/` — CppUTest framework (submodule/vendor)
  - `scripts/` — build and test scripts
  - `artifacts/` — copied firmware binaries (e.g., `LabCraft_firmware.bin`)
- `Documentation/` — manuals and parts docs
- `requirements.txt`
- `README.md`
- `AGENTS.md`

---

## Safety / guardrails (non-negotiable)
- **Never propose destructive actions** that could risk hardware damage.
- **Do not change the device protocol** (message formats/opcodes/parsing) unless explicitly requested.
- Avoid large refactors. Prefer small, incremental diffs.
- Any change crossing MVC layers must begin with:
  - the call path (UI → Controller → Model → comms → firmware handler)
  - a plan (≤8 steps)
  - a list of files to touch (before editing)
- If a change affects motion/pressure control or timing-sensitive behavior:
  - include explicit verification steps
  - include a rollback plan (how to revert)

---

## Working style (required)
For each task:
1) Locate call path first (UI → Controller → Model → comms → firmware handler)
2) Propose plan (≤8 steps) + list files to touch **before editing**
3) Implement the smallest viable slice (minimal diff)
4) Verify: run automated tests + provide short manual checklist if needed
5) Summarize:
   - what changed and why
   - how to validate
   - risks/edge cases
   - rollback steps

---

## Environment assumptions
Primary development environment: **Windows + VS Code**.
Prefer using the project interpreter/tools and repo scripts.

---

## Python (FreeRTOS-interface) commands
### Virtual environment (if needed)
- Create venv: `py -m venv .venv`
- Activate: `.\.venv\Scripts\Activate.ps1`
- Install deps: `python -m pip install -U pip` then `pip install -r requirements.txt`

### Run the app
- Use VS Code selected interpreter (`.\.venv\Scripts\python.exe`) then run:
  - `python FreeRTOS-interface/App.py`
  - (If README specifies a different entrypoint, follow README)

### Run Python tests
- Use the repo’s chosen test command (prefer `pytest` if configured):
  - `python -m pytest -q`
  - If `pytest` is not configured, use the repo’s documented command.

---

## Firmware commands (STM32)
Firmware must be validated in two ways:

### A) Host unit tests (fast, no hardware)
- Run host tests:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1`

### B) Headless CubeIDE build (compiles/links real firmware and produces `.bin`)
- Run headless build:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1`

### Recommended combined check
- Prefer one command after firmware edits (if present):
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1`
  - (If not present, run A then B)

### Firmware prerequisites
- CMake installed and on PATH (`cmake --version`)
- Visual Studio Build Tools present for host builds (MSVC)
- STM32CubeIDE installed for headless build
- CppUTest submodule/vendor present:
  - `git submodule update --init --recursive` (if using submodules)

---

## Firmware editing rules
- Treat the repo as the source of truth for the CubeIDE project.
- **Do not edit auto-generated CubeMX/CubeIDE code** outside `/* USER CODE BEGIN */ ... /* USER CODE END */` blocks.
- Prefer changes in:
  - application logic modules (protocol parsing, state machines, utilities)
  - not peripheral init code
- When adding new firmware logic, prefer isolating it into host-testable modules:
  - avoid hard dependencies on HAL/FreeRTOS headers in core logic
  - keep HAL/RTOS at the edges and call into pure functions

---

## Testing strategy (what to test first)
### Python (already in place)
- Keep tests deterministic and hardware-free where possible.
- Use fakes/mocks for comms.
- Add regression tests for each bugfix.

### Firmware (host-testable first)
Host unit tests (CppUTest) should cover:
- protocol encode/decode (golden vectors)
- framing/parsing and buffer edge cases
- state machines (homing/printing sequences) where possible
- math utilities and bounds checks

Headless build should be run after any firmware edits to catch:
- syntax errors, missing includes
- linker issues
- build configuration regressions

---

## What NOT to do
- Do not attempt to run hardware-in-the-loop tests unless explicitly requested and the workflow is clearly defined.
- Do not add heavy tooling (linting/formatting/build systems) unless requested.
- Do not restructure the repo or rename major components without discussion.

---

## Documentation expectations
When adding or changing test/build tooling:
- Update `README.md` (or `firmware/README.md`) with:
  - prerequisites
  - exact commands to run tests/build
  - known troubleshooting steps

---

## Git / commits
- One milestone per commit.
- Keep commits small and descriptive, e.g.:
  - `test: add protocol decode golden vectors (python)`
  - `test: add host firmware tests for parser edge cases`
  - `build: add headless firmware build script`
- Do not commit local artifacts:
  - `.venv/`, `__pycache__/`, logs, workspace metadata, IDE cache directories
- Firmware artifacts:
  - Only commit `.bin` files in `firmware/artifacts/` if the repo explicitly intends to version them.
  - Otherwise treat them as build outputs.

---

## If uncertain
Stop and ask by producing:
- what was inspected
- 2–3 plausible interpretations
- what info would disambiguate

---

## Definition of done (per task/PR)
- Automated tests pass for the affected area:
  - Python: `python -m pytest -q` (or repo equivalent)
  - Firmware: host tests + headless build as applicable
- Any protocol/schema changes documented (if explicitly requested)
- Summary includes:
  - files changed
  - risk assessment
  - validation steps
  - rollback steps
  - recommended next steps