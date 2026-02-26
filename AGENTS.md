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
  - `python -m pytest -q` (primary)
  - `python -m pytest` (for full output)

---

## Firmware note
If you modify anything under `firmware/`, follow `firmware/AGENTS.md`.
Firmware changes must pass:
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
(or run unit tests + headless build separately if needed).
Before editing anything under firmware/, read firmware/AGENTS.md and restate the validation commands you will run.

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
  - Python: `python -m pytest -q`
  - Firmware: host tests + headless build as applicable
- Any protocol/schema changes documented (if explicitly requested)
- Summary includes:
  - files changed
  - risk assessment
  - validation steps
  - rollback steps
  - recommended next steps