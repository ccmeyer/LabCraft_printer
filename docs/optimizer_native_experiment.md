# Isolated native optimizer experiment

This opt-in experiment profiles and compares the existing optimizer with one
compiled numerical kernel. The application never imports the adapter or kernel.
There are no dependency, persisted-schema, calibration, machine-communication,
or firmware changes. Revert the experiment commit to roll back; no data migration
or calibration-history rewrite is needed.

## Plan and scope

1. Profile the existing dense 17-target fixture and the realistic synthetic
   384-row/ten-reagent explicit import using `cProfile`.
2. Compile the dominant numerical routine behind an experiment-only adapter.
3. Compare edge cases, full computed outputs, exact mappings, and search work.
4. Alternate Python/native runs: one warm-up and five measured runs per backend.
5. Exercise the real Qt worker with early and active-solver cancellation.
6. Commit/push; use Pi Status -> Sync -> Validate before exact-revision runs.
7. Collect external evidence and final protected-state/process status.

The Windows profiles selected `ExperimentModel._nearest_two_stock`, the largest
self-time contributor in both cases (108,236 and 413,564 calls respectively).
The kernel searches droplet counts for a proposed pair; candidate enumeration,
ranking, validation, reaction generation, and publication remain Python.
This is a small C extension built with existing compilers/setuptools; it needs
neither Cython nor a package installation. It is an experiment, not a production
backend selection mechanism.

The path is simulated model inputs -> optimizer -> numerical adapter -> reaction
generation, plus the real Qt job manager and main-thread installation. The
explicit import uses the shared authored catalog and model dataframe route at
10 nL. It does not include wizard parsing, Import Apply, or table refresh, and
does not claim to resolve or requalify those previously reported UI issues.

## Numerical and cancellation contract

The C loop preserves ascending count order, floating-point operation order,
the 1e-12 tie tolerance, and the smaller-total-count tie-break. For nonnegative
residuals, rounding adds no candidate beyond floor and ceil. Strict floating
point flags prohibit fused contraction/fast-math. Python still computes the
outer bound using its own rounding. Unsupported numeric bounds and legacy
deadline callbacks use the original routine; fallback calls are recorded.

Each native call evaluates at most 256 counts and releases the GIL. The adapter
checks the existing computation control before and after each batch and retains
exact successful-run solver iteration counts. The global method replacement
exists only inside a scoped context in a dedicated experiment process; do not
run other optimizer clients concurrently in that process.

Equality covers every non-timing result field (excluding the diagnostic timing
warning), every computed output including plans/previews/reactions/fill,
allocation fingerprints, and deterministic counters. The imported case also
uses independent composition/volume checks. Cancellation checks unchanged
owner inputs and outputs and exactly one terminal result. Solver cancellation
is requested after at least 1,000 solver calls have actually occurred.

## Running

Use a fresh absolute output directory outside every Git worktree. Build objects,
extensions, profiles, test files, and reports stay external. Both platforms need
their existing Python development headers, setuptools, and C compiler (MSVC on
Windows; GCC on Pi). Missing prerequisites are blockers, not permission to install
into the shared Pi interpreter.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:LABCRAFT_NATIVE_EXPERIMENT = '1'
$experimentRoot = Join-Path $env:TEMP ('labcraft-native-' + [guid]::NewGuid().ToString('N'))
.\env\Scripts\python.exe -m pytest -q tests/test_optimizer_native_experiment.py `
  --basetemp "$experimentRoot\pytest"
.\env\Scripts\python.exe tools/experiment_optimizer_native.py --mode profile `
  --output "$experimentRoot\profiles"
.\env\Scripts\python.exe tools/experiment_optimizer_native.py --mode compare `
  --runs 5 --output "$experimentRoot\comparison"
```

`--case dense17` or `--case dense_384_10` selects a targeted rerun. The default
is both cases with two-stock mode enabled. Compiler-dependent tests explicitly
skip ordinary CI unless `LABCRAFT_NATIVE_EXPERIMENT=1` is supplied.

On the Pi use the README's wrapper Status -> Sync -> Validate workflow for the
exact clean pushed commit, existing persisted external development-store binding,
and read-only shared interpreter. Execute these commands from the validated
development checkout with `-B`, external output/cache/pytest directories, and
simulated dependencies. Run the wrapper offscreen smoke lane and final Status.
Record and clean up only owned experiment processes. Never terminate a Qt thread;
the harness cooperatively cancels on its 15-minute worker watchdog and drains
the thread before leaving the scoped adapter. A failure to unwind is an explicit
blocker requiring the owning process supervisor, not destruction of the thread.

## Evidence and interpretation

Profiles are deliberately separate from unprofiled timing runs. `results.json`
records revision, source hashes, build binary/hash/flags, actual selected stock
plans, work counters, warm-ups, measurements, cancellation phases, and errors.
`build/build.json` records each platform's build. Evidence is saved after each
trial; incomplete evidence is not a pass. Retain stdout/stderr externally too.

Complete model-call latency includes optimization, exact validation, and reaction
generation. Worker latency additionally includes snapshot submission, thread
startup, and main-thread publication, but excludes fixture creation and editor
tables. A 20 ms timer measures main-thread heartbeat gaps. Five early and five
active-solver cancellations run per backend/case. The existing 250 ms heartbeat
and 1,000 ms cancellation thresholds are reported, with no speedup threshold or
total-calculation deadline. Only a default five-run comparison supports the
recommendation; one-run probes are diagnostics. Compare same-host medians/maxima,
then compare exact plan fingerprints and counters across hosts. Windows results
do not establish Pi performance.
