# Milestone 8 Slice 2 — Manual Suite and Capability Selection

Status: implemented and focused validation complete (2026-08-07)

## Scope

Add a read-only selection layer over the validated SIL capability manifest.
Operators can list the catalog, dry-run deterministic scenario/suite/capability
plans, or request changed-source recommendations. Multi-scenario execution is
reserved for Slice 3, so suite and capability selectors fail closed unless
`--dry-run` is present. Direct `--scenario` execution remains compatible.

The selection call path is:

`CLI selector → validated manifest → typed resolver → deterministic JSON`

It returns before Qt, application, Controller, Model, simulator, protocol,
firmware, Pi operations, or physical hardware construction. The existing
execution path remains:

`--scenario → registry → environment/Pi validation → existing workflow runner`

## Implementation

1. Add typed suite, capability, direct-scenario, catalog, and changed-source
   resolution with manifest identity/hash and deterministic JSON output.
2. Add mutually exclusive CLI selectors and ensure planning returns before Qt
   or application imports.
3. Reject planned/deferred selections, unsupported platforms, missing Pi
   evidence, and conflicting modes before execution.
4. Freeze the `standard` suite at one smoke scenario, order 1, seed 1, and a
   60-second timeout.
5. Convert manifest schedules to operator-initiated `on_demand` / `manual`
   declarations; evidence-age values remain informational.
6. Add focused resolver, parser, manifest, recommendation, import-boundary,
   and direct-run compatibility tests.
7. Run only the targeted tests and existing smoke SIL node, then update README,
   roadmap, and the Slice 2 completion record.

## Files

- `tools/virtual_workflows/selection.py`
- `tools/run_virtual_workflow.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_selection.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan and the completion record

## Gates, risks, and rollback

Focused unit/contract tests must prove deterministic ordering, fail-closed
selection, no report writes, no Qt/application imports, source matching, and
legacy direct execution. The existing 24-well smoke system test must still pass.
No full suite or Pi run is authorized for this slice.

The primary risk is a planning option accidentally reaching execution. Every
planning payload therefore records `execution_authorized: false`, and the CLI
returns immediately after printing it. Rollback removes the new resolver and
CLI options and restores prior schedule metadata; no experiment data, report
schema, MVC behavior, simulator behavior, protocol, firmware, or hardware state
is changed.
