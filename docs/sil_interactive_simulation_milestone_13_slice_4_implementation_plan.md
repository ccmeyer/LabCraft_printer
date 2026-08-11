# Milestone 13 Slice 13.4 Implementation Plan

Status: `complete`

Started: 2026-08-09

## Objective and call paths

Add schema-v2 fresh-process aggregation, exact retained-plan/sequence replay,
semantic coverage, immutable original-failure evidence, and diagnostic-tier
isolation around the six already-qualified generated journeys. Preserve the
Milestone 8 schema-v1 runner and campaign byte-for-byte.

```text
CLI frozen/diagnostic selection or retained plan
-> v2 plan/hash/budget validation
-> immutable normalized sequence file
-> fresh child CLI consuming that file
-> real Qt journey -> Controller/Model -> authority -> simulator
-> report/ledgers/screenshots/cleanup
-> parent report/hash/budget validation
-> semantic coverage + original-failure index + aggregate
```

Aggregate replay reads the retained `exploration_plan.json`; every child reads
its retained normalized sequence JSON and rejects any difference from the
versioned generator. Coverage is computed only from reached transitions in
passing child reports, never from seed or action counts. A failed original is
retained unchanged with logs, reached prefix, report/cleanup when available,
and an exact rerun command.

## Scope and exclusions

The slice adds a separate M13 v2 runner, narrow CLI replay arguments, diagnostic
sequence resolution, and focused/system tests. Deterministic reduction is
omitted. No aggregate registers capability evidence, weakens a scenario
oracle, mutates an active authoritative file, retries with a larger budget, or
changes a frozen sequence after execution begins.

M8 runner/schema/CLI behavior, M9-12/11A scenarios, production MVC, simulator
protocol, firmware, hardware, refill/resume, scheduling, and the known 384x10
fixture mismatch remain out of scope.

## Implementation plan

1. Authorize only explicit M13 v2 plans and exact normalized-sequence loading.
2. Reuse isolated-child, atomic-write, containment, hashing, and report-v1
   primitives in a separate schema-v2 runner.
3. Validate strict child/campaign action, session, screenshot, evidence, and
   runtime budgets with no retry growth.
4. Emit versioned state/transition/operation/rejection coverage from passing
   reached-transition evidence.
5. Retain every original normalized sequence before launch and index failures
   without mutation or replacement.
6. Keep diagnostic aggregates non-gating and bounded to four explicit seeds.
7. Test fresh PID, continuation, timeout/kill, exact replay, coverage mutation,
   original immutability, and diagnostic isolation.
8. Qualify frozen aggregate/replay and one diagnostic run, audit evidence, and
   write the completion record.

## Files likely to change

- `tools/virtual_workflows/exploration_m13.py`
- new `tools/virtual_workflows/exploration_runner_m13.py`
- narrow M13 branches in `tools/run_virtual_workflow.py` and
  `tools/virtual_workflows/journeys.py`
- M13 runner, CLI, and system tests
- Milestone 13 master/execution/Slice 13.4 records

## Budgets, acceptance, risks, and rollback

Each child is capped at 18 semantic operations, 80 action rows, three sessions,
two rotations, four screenshots, 256 files/48 MiB, 270 seconds in-scenario,
and a 300-second external watchdog. The frozen aggregate is capped at six
children, 108 semantic operations, 480 action rows, 18 sessions, 12 rotations,
24 screenshots, 1,600 files/320 MiB, 1,800 seconds, and `24/12/48/264` compact
work totals. Diagnostics accept at most four explicit seeds and have release
gate status `not_applicable`.

Acceptance requires 6/6 fresh children, complete semantic coverage, aggregate
exact replay of all retained originals, deterministic diagnostic isolation,
injected-failure original preservation, M8 runner compatibility, focused and
system tests, exact cleanup, and `git diff --check`.

Risks are replay accidentally regenerating, coverage using planned rather than
reached transitions, evidence-size accounting drift, and a diagnostic result
affecting the frozen gate. Hash/path/tier/budget tests fail closed for each.
Rollback removes only the v2 runner and M13 CLI/journey extensions, restores
the explicit-sequence Slice 13.3 boundary, and leaves M8 plus all retained
child evidence readable.
