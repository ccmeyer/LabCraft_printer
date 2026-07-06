# Release-Aware App Update Rollout Plan

## Purpose

Move LabCraft application updates from "advance to the head of `stable`" to
"install a named, documented release" while preserving the conservative update
behavior that deployed machines already use.

This plan builds on `docs/app_update_plan.md`. The existing updater already
does the right kind of safety work: it checks for local changes, refuses
diverged histories, uses fast-forward-only movement for normal updates, logs
before/after commits, and supports offline Git bundles. The next step is to add
release metadata, release-target selection, and explicit rollback.

## Current Context

Known release markers:

- `v1.1.0`: current deployed `stable` baseline.
- `v1.1.1`: current `main` bugfix state before the camera/refuel release.
- `v1.2.0-rc.1`: current release candidate after merging `camera_refactor` into
  `main`.

Important branch implication:

- Current `main` includes the camera/refuel release-candidate work.
- The release-aware updater bootstrap should be built from `v1.1.1`, not current
  `main`, so deployed machines can receive updater improvements without also
  receiving the larger camera/refuel changes.

Recommended branch for the bootstrap work:

```powershell
git switch -c release/v1.1.2-updater-bootstrap v1.1.1
```

Expected release sequence:

```text
v1.1.0        deployed stable baseline
v1.1.1        UI bugfix release
v1.1.2        release-aware updater bootstrap
v1.2.0-rc.1   camera/refuel release candidate without bootstrap updater work
v1.2.0-rc.2   camera/refuel release candidate with bootstrap updater work merged in
v1.2.0        final camera/refuel release after validation
```

## Target Call Path

Current application update path:

```text
Firmware tab UI
-> MainWindow.request_app_update_check() / request_app_update()
-> Controller.start_app_update_check() / launch_app_updater()
-> tools/update_and_restart.py
-> tools/update_window.py
-> Git remote branch or offline Git bundle
```

Current offline bundle creation path:

```text
tools/create_update_bundle.py
-> .bundle + .json manifest under local/LabCraftUpdates/
-> tools/update_and_restart.py --offline-manifest <manifest>
```

The release-aware work should not change Model, comms, firmware handlers, device
protocol messages, opcodes, motion control, pressure control, or firmware
flashing behavior.

## Design Principles

- Tags are immutable deployment anchors. Do not move a tag after sharing it.
- Branches may move. Deployed release identity should come from tags and release
  manifests, not from branch heads.
- Normal updates should remain forward-only and fast-forward-only.
- Rollback should be a separate explicit action, because it intentionally moves
  backward.
- Offline bundles should identify the release they install, not only the commit
  they contain.
- Deployed machines need a bootstrap release because they currently only know
  how to update to the head of their configured branch.

## Release Metadata Files

Add these files in the bootstrap release:

```text
VERSION
CHANGELOG.md
releases/
  latest.json
  v1.1.0.json
  v1.1.1.json
  v1.1.2.json
```

Later releases should add one JSON file per deployed release and update
`latest.json`.

Suggested `VERSION` contents:

```text
v1.1.2
```

Suggested `releases/latest.json` contents:

```json
{
  "schema_version": "labcraft_release_index_v1",
  "stable": "v1.1.2",
  "release_candidate": "v1.2.0-rc.1",
  "releases": [
    "v1.1.2",
    "v1.1.1",
    "v1.1.0"
  ]
}
```

Suggested per-release manifest:

```json
{
  "schema_version": "labcraft_release_v1",
  "version": "v1.1.2",
  "commit": "<full commit sha>",
  "tag": "v1.1.2",
  "channel": "stable",
  "previous_version": "v1.1.1",
  "rollback_version": "v1.1.1",
  "requires_firmware": null,
  "summary": "Adds release metadata and prepares the updater for version-aware releases.",
  "notes": [
    "Adds VERSION, CHANGELOG.md, and release manifests.",
    "Keeps existing branch-head update behavior for bootstrap compatibility."
  ],
  "validation": [
    ".\\env\\Scripts\\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_create_update_bundle.py tests/test_app_update_request.py"
  ]
}
```

`previous_version` is historical. `rollback_version` is operational. They are
often the same, but they should remain separate so a release can recommend
rolling back to a known-good stable release instead of a release candidate.

## Implementation Slices

### Slice 0: Planning

Purpose:

- Document the release-aware rollout before changing updater behavior.

Files:

- `docs/release_update_rollout_plan.md`

Validation:

- Read-only review of the plan.
- No automated tests required.

Rollback:

- Delete or revert this document.

### Slice 1: Bootstrap Metadata Only

Branch:

- `release/v1.1.2-updater-bootstrap`, created from `v1.1.1`.

Purpose:

- Add release metadata without changing update behavior.
- Give support and the app a stable place to read the installed version.

Likely files:

- `VERSION`
- `CHANGELOG.md`
- `releases/latest.json`
- `releases/v1.1.0.json`
- `releases/v1.1.1.json`
- `releases/v1.1.2.json`
- Tests only if helper code is added.

Behavior:

- Existing online update still checks/pulls the configured upstream branch.
- Existing offline update still consumes current bundle manifests.
- The app can continue to run exactly as before.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_create_update_bundle.py tests/test_app_update_request.py
```

Done when:

- Metadata files exist and describe `v1.1.0`, `v1.1.1`, and `v1.1.2`.
- `CHANGELOG.md` contains release notes for those versions.
- Existing updater tests still pass.

### Slice 2: Display Installed Version

Purpose:

- Let operators and support see the installed LabCraft app version.

Likely files:

- `FreeRTOS-interface/View.py`
- Optional small helper module, for example `FreeRTOS-interface/AppVersion.py`
- `tests/test_app_update_request.py` or a new focused version helper test.

Behavior:

- Read `VERSION` from the repo root.
- Fall back to a short Git SHA when `VERSION` is missing.
- Display the current version in the Application Update area or a support/about
  surface.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py
```

Done when:

- Support can ask an operator for a version string instead of a commit SHA.
- Missing or malformed `VERSION` does not break app startup.

### Slice 3: Release-Aware Online Check

Purpose:

- Change the update check from "commits behind upstream" to "new stable release
  available."

Likely files:

- `tools/update_and_restart.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/View.py`
- `tests/test_update_and_restart.py`
- `tests/test_app_update_request.py`

Behavior:

- Fetch the remote with tags.
- Read `releases/latest.json` from the fetched target or a configured local
  release index.
- Resolve the target release tag to a commit.
- Compare `HEAD` with the target release commit.
- Report update availability with version names and release notes.
- Keep the existing dirty-worktree and diverged-history blockers.

Candidate Git operations:

```text
git fetch --prune --tags
git rev-parse <target-tag>^{commit}
git merge-base --is-ancestor HEAD <target-tag>
git log --oneline HEAD..<target-tag>
```

Normal update application should use an explicit target instead of branch head:

```text
git merge --ff-only <target-tag>
```

Do not use rollback or detached checkout in this slice.

Done when:

- The UI says, for example, `v1.1.2 is available`, not just `N commits
  available`.
- A machine already at the target release reports up to date.
- A machine with local changes is still blocked before any update is applied.

### Slice 4: Release-Aware Offline Bundles

Purpose:

- Make offline bundles self-describing release installers.

Likely files:

- `tools/create_update_bundle.py`
- `tools/update_and_restart.py`
- `tests/test_create_update_bundle.py`
- `tests/test_update_and_restart.py`
- `README.md`

Manifest additions:

```json
{
  "release_version": "v1.1.2",
  "release_tag": "v1.1.2",
  "rollback_version": "v1.1.1",
  "release_manifest": {
    "schema_version": "labcraft_release_v1"
  }
}
```

Behavior:

- Bundle creation accepts `--release v1.1.2`.
- The bundle target commit must match the release tag commit.
- Incremental release bundles include required tags by default.
- Offline update check displays release name and notes.
- Offline update application merges the fetched release target fast-forward-only.

Done when:

- Support can create:

```powershell
.\env\Scripts\python.exe tools/create_update_bundle.py --release v1.1.2
```

- The app can show the operator which release the offline bundle installs.

### Slice 5: Explicit Offline Install Flow

Purpose:

- Let users install an offline bundle intentionally, not only when the online
  remote cannot be reached.

Likely files:

- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/Controller.py`
- `tools/update_and_restart.py`
- `tests/test_app_update_request.py`

Behavior:

- Add a separate `Install Offline Bundle` action.
- Let the operator select a manifest JSON from a USB drive or folder.
- Validate and display release details before closing the app.
- Reuse the existing external updater process and safe close/disconnect path.

Done when:

- Online machines can still install a support-provided offline bundle.
- The automatic offline fallback remains available for network failures.

### Slice 6: Explicit Rollback

Purpose:

- Add a deliberate operator-supported path back to a known release.

Likely files:

- `tools/update_and_restart.py`
- `tools/update_window.py`
- `FreeRTOS-interface/View.py`
- `FreeRTOS-interface/Controller.py`
- `tests/test_update_and_restart.py`
- `tests/test_app_update_request.py`
- `README.md`

Behavior:

- Rollback target comes from the current release manifest's
  `rollback_version`, or from an explicitly selected offline release bundle.
- Rollback is blocked if:
  - worktree is dirty,
  - print/calibration/capture/firmware update is active,
  - rollback target is missing,
  - rollback target is not a known release tag,
  - rollback target cannot be verified.
- Rollback confirmation must name both versions.
- Rollback should record before/after versions and commits in the update log.

Important design decision:

- Rollback cannot be implemented as `git pull --ff-only` because it moves
  backward.
- Prefer supportable Git operations that target a known release tag, but keep
  them isolated from normal update code.
- Decide during implementation whether rollback should use a technical support
  workflow first, then become an operator button after field validation.

Done when:

- A test checkout can move from `v1.2.0` back to the configured
  `rollback_version`.
- The UI clearly distinguishes update from rollback.

### Slice 7: Merge Bootstrap Into Camera Release Candidate

Purpose:

- Bring the release-aware updater bootstrap into the camera/refuel release line.

Workflow:

```powershell
git switch main
git merge release/v1.1.2-updater-bootstrap
.\env\Scripts\python.exe -m pytest -q
git tag -a v1.2.0-rc.2 -m "LabCraft v1.2.0 release candidate 2"
git push origin main v1.2.0-rc.2
```

Conflict guidance:

- Conflicts are possible but expected if both branches touched update UI,
  controller update wiring, or docs.
- A conflict does not damage the repo; Git pauses the merge.
- If the merge feels wrong, stop with:

```powershell
git merge --abort
```

Done when:

- `v1.2.0-rc.2` contains both camera/refuel work and release-aware updater
  bootstrap work.
- Test machines can move from `v1.1.2` to `v1.2.0-rc.2` by explicit release.

## Bootstrap Deployment Plan

1. Create `release/v1.1.2-updater-bootstrap` from `v1.1.1`.
2. Implement slices 1 and 2 at minimum.
3. Optionally include slice 3 if it is ready and well tested.
4. Tag `v1.1.2`.
5. Fast-forward `stable` to `v1.1.2`.
6. Deployed machines use the old update method one last time: they pull the head
   of `stable`.
7. After that update, deployed machines have the release metadata and any
   release-aware updater behavior included in `v1.1.2`.
8. Future updates should target named releases.

Recommended minimum bootstrap:

- Include metadata and installed-version display.
- Keep the old updater behavior until release-aware check/apply has focused
  tests.

More aggressive bootstrap:

- Include release-aware online check/apply in `v1.1.2`.
- This reduces the number of field updates but increases the blast radius of the
  bootstrap release.

## Validation Matrix

Metadata/doc-only slices:

- Manual review.
- No automated tests required unless helper code is added.

Updater/backend slices:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_create_update_bundle.py
```

UI/controller slices:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_app_update_request.py
```

Full Python validation before tagging a deployable release:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Manual validation:

- Check update availability while already on the latest release.
- Check update availability while one release behind.
- Confirm dirty worktree blocks update.
- Confirm offline bundle validation rejects wrong repo, wrong branch/release, bad
  SHA-256, missing bundle, and unsupported manifest schema.
- Confirm update logs include source, before/after commits, and version names.
- Confirm app update does not flash firmware.

Firmware validation:

- Not required unless files under `firmware/` change.

## Risks And Mitigations

- Risk: deploying camera/refuel changes before the updater bootstrap is ready.
  Mitigation: build `v1.1.2` from `v1.1.1`, not current `main`.

- Risk: merge conflicts when bringing bootstrap work back into `main`.
  Mitigation: keep bootstrap changes focused and merge back before additional
  unrelated updater/UI work accumulates.

- Risk: tags and release manifests disagree.
  Mitigation: tests should validate that `manifest["commit"]` matches
  `git rev-parse <manifest["tag"]>^{commit}`.

- Risk: rollback becomes an unsafe hidden reset.
  Mitigation: keep rollback separate from normal update, require a known release
  tag, and require explicit confirmation.

- Risk: offline bundles do not contain needed tags.
  Mitigation: release-aware offline bundles should include the release tag by
  default, including incremental bundles.

## Rollback Plan For The Rollout

Documentation-only slice:

- Revert `docs/release_update_rollout_plan.md`.

Metadata-only bootstrap:

- Revert `VERSION`, `CHANGELOG.md`, and `releases/`.
- Do not move existing shared tags.

Release-aware check/apply:

- Revert updater changes to the branch-head implementation from
  `docs/app_update_plan.md`.
- Keep release metadata files if they remain useful for support.

Explicit offline install:

- Hide or remove the explicit offline install UI.
- Keep backend offline manifest support if existing fallback still needs it.

Rollback feature:

- Hide the operator rollback button first.
- Keep support-only rollback documentation if it is useful and validated.

Bad field release:

- Publish or provide the release's configured `rollback_version`.
- Use an offline rollback bundle if the machine cannot reach the remote.
- Keep the bad release tag in place for auditability; do not retag it.

## Open Decisions

- Should `v1.1.2` include release-aware online apply, or only metadata and
  installed-version display?
- Should release manifests live only in Git, or should support also host
  `latest.json` at a stable URL later?
- Should release candidates be visible to normal machines, or only when a
  support/operator setting selects an RC channel?
- Should operator rollback ship in the first release-aware updater, or should it
  start as a support-only command until validated on test machines?
- Should offline bundles contain the full `releases/` directory snapshot or only
  the target release manifest?
