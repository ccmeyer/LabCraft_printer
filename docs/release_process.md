# LabCraft Release Process

This runbook is the source of truth for preparing LabCraft app releases,
release candidates, release metadata, update bundles, and rollback metadata.
Follow it before editing `VERSION`, `CHANGELOG.md`, `releases/latest.json`, or
`releases/<version>.json`.

## Core Rules

- Never move, delete, or retarget an existing release tag.
- Do not advertise a release tag in `releases/latest.json` until that tag exists
  or will be pushed before the branch that advertises it.
- Keep `stable` for deployed stable app releases only.
- Keep `main` as the active release-candidate line for the next feature release.
- Use feature branches for app changes, then merge them into `main`.
- Use release branches for stable release prep when practical, then fast-forward
  or merge them into `stable`.
- Do not merge release-candidate-only code into `stable`.
- Do not include known bad or metadata-incomplete tags in `releases/latest.json`
  such as `v1.1.15`.
- For normal app releases, update all release metadata in the same commit that
  will be tagged.
- Run `.\env\Scripts\python.exe tools\validate_release_metadata.py` before
  tagging any release metadata commit. After creating tags, run it again with
  `--check-tags` before pushing.
- Run the focused updater tests for metadata/updater-only releases and the full
  Python suite before tagging a new release candidate or promoting stable.

## Release Metadata Contract

Every tagged app release must have:

```text
VERSION
CHANGELOG.md
releases/latest.json
releases/<version>.json
```

`VERSION` contains exactly the target version string, for example:

```text
v1.2.0-rc.7
```

`releases/<version>.json` uses this schema:

```json
{
  "schema_version": "labcraft_release_v1",
  "version": "v1.2.0-rc.7",
  "tag": "v1.2.0-rc.7",
  "channel": "release_candidate",
  "release_date": "2026-07-13",
  "previous_version": "v1.2.0-rc.6",
  "rollback_version": "v1.1.17",
  "requires_firmware": null,
  "machine_data": {
    "preservation_contract": "labcraft.machine_data_update.v1",
    "data_schema_version": 1,
    "transition": "none",
    "transition_id": null
  },
  "summary": "Short release summary.",
  "notes": ["Operator-facing release note."],
  "validation": [
    ".\\env\\Scripts\\python.exe -m pytest -q",
    "git diff --check",
    "Get-ChildItem releases\\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }"
  ]
}
```

Use `channel: "stable"` for stable releases and
`channel: "release_candidate"` for RC releases.

Use `requires_firmware: null` unless the release intentionally changes the
firmware artifact. If firmware changed, use:

```json
{
  "artifact": "firmware/artifacts/LabCraft_firmware.bin",
  "note": "Firmware was updated on this release line."
}
```

Starting with `v1.3.0-rc.2`, every release manifest must include the exact
`machine_data` declaration shown above. Use `transition: "none"` unless the
release includes and qualifies a target-side hardware-free schema adapter.
An intentional transition uses `transition: "bootstrap_recovery"` and an
exact reviewed `transition_id`; it must pass the Milestone 6 transition and
recovery gates before tagging. Never omit the declaration to make an update
compatible with an older updater.

`releases/latest.json` is the app's release index. Stable machines read this
from their upstream branch during online update checks.

Current shape:

```json
{
  "schema_version": "labcraft_release_index_v1",
  "stable": "v1.1.17",
  "release_candidate": "v1.2.0-rc.6",
  "releases": ["v1.2.0-rc.6", "v1.1.17", "v1.1.16"]
}
```

When the updater version supports release-candidate series discovery, stable
metadata may also include:

```json
{
  "release_candidate": "v1.2.0-rc.6",
  "release_candidate_series": {
    "tag_prefix": "v1.2.0-rc.",
    "minimum": "v1.2.0-rc.6"
  }
}
```

This lets machines that opt into release candidates discover future
`v1.2.0-rc.N` tags without requiring a new stable metadata release for every RC.
The updater still validates the selected tag and its release manifest before
applying anything.

## Branch Model

Use this model unless a maintainer explicitly chooses a different flow:

```text
stable    deployed stable update line
main      active next-release / release-candidate line
feature/* individual app changes branched from main
release/* stable release-prep branches branched from stable
```

Examples:

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/fix-something
```

For stable metadata or stable hotfix prep:

```powershell
git switch stable
git pull --ff-only origin stable
git switch -c release/v1.1.18-brief-description
```

## Workflow: New Release Candidate

Use this when `main` is not ready to become final `v1.2.0` yet and you need a
new RC such as `v1.2.0-rc.7`.

1. Start from current `main`.

   ```powershell
   git switch main
   git pull --ff-only origin main
   git status --short
   ```

2. Create and work on a feature branch.

   ```powershell
   git switch -c feature/<short-name>
   ```

3. Implement the app change on the feature branch and run focused tests.

4. Merge the feature branch into `main`.

   ```powershell
   git switch main
   git merge --no-ff feature/<short-name>
   ```

5. Add the RC metadata commit on `main`.

   Update:

   ```text
   VERSION
   CHANGELOG.md
   releases/latest.json
   releases/v1.2.0-rc.7.json
   ```

   Required values for an RC after `v1.2.0-rc.6`:

   ```text
   VERSION: v1.2.0-rc.7
   latest.json stable: current stable, for example v1.1.17
   latest.json release_candidate: v1.2.0-rc.7
   release manifest previous_version: v1.2.0-rc.6
   release manifest rollback_version: current stable, for example v1.1.17
   release manifest channel: release_candidate
   ```

6. Validate before tagging.

   ```powershell
   .\env\Scripts\python.exe -m pytest -q
   .\env\Scripts\python.exe tools\validate_release_metadata.py
   git diff --check
   Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
   ```

7. Commit, tag, and push.

   ```powershell
   git add CHANGELOG.md VERSION releases\latest.json releases\v1.2.0-rc.7.json
   git commit -m "docs: add v1.2.0-rc.7 release metadata"
   git tag -a v1.2.0-rc.7 -m "LabCraft v1.2.0 release candidate 7"
   .\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
   git push origin main v1.2.0-rc.7
   ```

## Workflow: Metadata-Only Stable Release

Use this when stable machines need new release metadata but no app logic change,
for example to advertise a newer release candidate or RC series.

1. Branch from `stable`.

   ```powershell
   git switch stable
   git pull --ff-only origin stable
   git switch -c release/v1.1.18-rc-pointer
   ```

2. Update only release metadata.

   ```text
   VERSION
   CHANGELOG.md
   releases/latest.json
   releases/v1.1.18.json
   ```

   Required values:

   ```text
   VERSION: v1.1.18
   latest.json stable: v1.1.18
   latest.json release_candidate: current RC, for example v1.2.0-rc.7
   release manifest previous_version: previous stable, for example v1.1.17
   release manifest rollback_version: previous stable, for example v1.1.17
   release manifest channel: stable
   requires_firmware: null
   ```

3. If the stable release should allow future RC discovery, add:

   ```json
   "release_candidate_series": {
     "tag_prefix": "v1.2.0-rc.",
     "minimum": "v1.2.0-rc.7"
   }
   ```

4. Run focused validation.

   ```powershell
   .\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py tests/test_update_window.py
   .\env\Scripts\python.exe tools\validate_release_metadata.py
   git diff --check
   Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
   ```

5. Commit and tag locally.

   ```powershell
   git add CHANGELOG.md VERSION releases\latest.json releases\v1.1.18.json
   git commit -m "docs: update stable release metadata"
   git tag -a v1.1.18 -m "LabCraft v1.1.18"
   .\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
   ```

6. If `latest.json` advertises a release-candidate tag that does not yet exist
   on the remote, push only the stable tag first.

   ```powershell
   git push origin v1.1.18
   ```

7. After the advertised RC tag exists on the remote, promote stable.

   ```powershell
   git switch stable
   git merge --ff-only release/v1.1.18-rc-pointer
   git push origin stable
   ```

## Workflow: Stable Hotfix Release

Use this for stable bug fixes that deployed machines should receive, such as
updater fixes.

1. Branch from `stable`.

   ```powershell
   git switch stable
   git pull --ff-only origin stable
   git switch -c release/v1.1.18-hotfix-description
   ```

2. Implement the smallest safe fix.

3. Update release metadata for the new stable version.

   ```text
   VERSION
   CHANGELOG.md
   releases/latest.json
   releases/v1.1.18.json
   ```

4. Run focused tests for the changed area and the updater tests.

   ```powershell
   .\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py tests/test_update_window.py
   .\env\Scripts\python.exe tools\validate_release_metadata.py
   git diff --check
   Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
   ```

5. Run the full Python suite before advancing `stable` if the hotfix touches
   shared app behavior.

   ```powershell
   .\env\Scripts\python.exe -m pytest -q
   ```

6. Commit, tag, and push.

   ```powershell
   git add <changed-files> CHANGELOG.md VERSION releases\latest.json releases\v1.1.18.json
   git commit -m "fix: concise stable hotfix summary"
   git tag -a v1.1.18 -m "LabCraft v1.1.18"
   .\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
   git push origin release/v1.1.18-hotfix-description v1.1.18
   ```

7. Promote stable after validation.

   ```powershell
   git switch stable
   git merge --ff-only release/v1.1.18-hotfix-description
   git push origin stable
   ```

8. Merge the stable hotfix line into `main` so future RCs include it.

   ```powershell
   git switch main
   git pull --ff-only origin main
   git merge stable
   ```

   Resolve conflicts with the intended `main`/RC values, then create the next
   RC metadata commit and tag.

## Workflow: Promote Release Candidate To Final Stable

Use this only when the RC line is accepted as the final feature release, for
example `v1.2.0`.

1. Verify the accepted RC tag and commit.

   ```powershell
   git fetch origin --tags
   git show --stat v1.2.0-rc.7
   ```

2. Create a final release metadata commit on `main`.

   Required values:

   ```text
   VERSION: v1.2.0
   latest.json stable: v1.2.0
   latest.json release_candidate: null or the next planned RC line
   releases/v1.2.0.json channel: stable
   releases/v1.2.0.json previous_version: v1.2.0-rc.7
   releases/v1.2.0.json rollback_version: previous stable, for example v1.1.18
   ```

3. Run full validation.

   ```powershell
   .\env\Scripts\python.exe -m pytest -q
   .\env\Scripts\python.exe tools\validate_release_metadata.py
   git diff --check
   Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
   ```

4. Commit, tag, and push.

   ```powershell
   git add CHANGELOG.md VERSION releases\latest.json releases\v1.2.0.json
   git commit -m "docs: add v1.2.0 release metadata"
   git tag -a v1.2.0 -m "LabCraft v1.2.0"
   .\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
   git push origin main v1.2.0
   ```

5. Promote stable to the final release only after validation and any required
   deployment decision.

   ```powershell
   git switch stable
   git merge --ff-only v1.2.0
   git push origin stable
   ```

## Offline Update Bundles

Create release-aware bundles from a checkout that has the target tag.

Full release bundle:

```powershell
.\env\Scripts\python.exe tools\create_update_bundle.py --release v1.1.18
```

Incremental bundle from a known machine commit:

```powershell
.\env\Scripts\python.exe tools\create_update_bundle.py --release v1.1.18 --since <offline-head-sha>
```

Approximate smaller bundle when support is confident the target machine is
within the last 20 commits:

```powershell
.\env\Scripts\python.exe tools\create_update_bundle.py --release v1.1.18 --last 20
```

Legacy branch bundle, only when intentionally supporting old branch-based
offline update behavior:

```powershell
.\env\Scripts\python.exe tools\create_update_bundle.py --branch stable
```

Copy both generated files from `local/LabCraftUpdates/` to the USB drive:

```text
*.bundle
*.json
```

For automatic offline bundle discovery, place the files directly under:

```text
LabCraftUpdates/
```

Nested version folders require manual manifest selection from the app.

## Online Rollback And Offline Rollback

Release manifests must define `rollback_version` deliberately.

Stable releases normally roll back to the previous stable release.

Release candidates normally roll back to the current stable release, not to the
previous RC, unless support specifically wants RC-to-RC rollback.

For M6-capable releases, do not run a shortened backend rollback command. It
lacks the authorized machine/root binding and will fail closed. Normal
M6-to-M6 rollback is launched by the authorized app UI. Rollback to a legacy
checkout-local release requires the exact-profile support procedure in
`docs/machine_data_update_and_rollback_runbook.md`.

Pre-M6 backend rollback command (legacy documentation only):

```powershell
.\env\Scripts\python.exe tools\update_and_restart.py --repo-root . --rollback --no-relaunch --record-result
```

Offline rollback with a selected release-aware bundle:

```powershell
.\env\Scripts\python.exe tools\update_and_restart.py --repo-root . --rollback --offline-manifest path\to\manifest.json --no-relaunch --record-result
```

The app UI also supports:

```text
Check Rollback
Restore Previous App Version
Restore From Offline Rollback Bundle
```

`Check Rollback` tries the online configured rollback target first. If online
tag fetch fails, it scans removable drives for `LabCraftUpdates/*.json`.
When the resolved target has no M6 preservation contract, the check remains
read-only and the normal restore button is disabled with support required.

## Validation Checklist

Use focused validation for metadata-only or updater-only changes:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_update_and_restart.py tests/test_app_update_request.py tests/test_update_window.py
.\env\Scripts\python.exe tools\validate_release_metadata.py
git diff --check
Get-ChildItem releases\*.json | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
```

After creating release tags locally and before pushing them:

```powershell
.\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
```

Use the full Python suite before tagging RCs, final releases, or stable releases
that include app behavior changes:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

If firmware files are changed, read `firmware/AGENTS.md` and run the firmware
validation command required there before tagging.

Manual metadata sanity checks:

```powershell
git tag --list v1.1.*
git tag --list v1.2.0-rc.*
Get-Content VERSION
Get-Content releases\latest.json
Get-Content releases\<version>.json
```

On a target Pi:

```bash
cd ~/LabCraft_printer
git branch --show-current
git rev-parse --short HEAD
cat VERSION
git status --short
git rev-parse --abbrev-ref --symbolic-full-name @{u}
```

## Common Failure Modes

- `latest.json` advertises an RC tag that has not been pushed yet.
- `VERSION` and `releases/<version>.json` disagree.
- A release manifest `tag` field differs from its filename.
- `rollback_version` points to an untagged or inappropriate target.
- A release candidate manifest uses `channel: "stable"`.
- A stable manifest uses `channel: "release_candidate"`.
- A branch bundle was created when a release-aware bundle was needed.
- A USB drive contains `LabCraftUpdates/<version>/*.json`; automatic scanning
  only checks `LabCraftUpdates/*.json`.
- A known bad or incomplete tag is included in `releases/latest.json`.
- `stable` is pushed before an advertised RC tag exists on the remote.

## Recovery Notes

If a release metadata commit is wrong but not tagged or pushed, amend or replace
the commit normally.

If a release metadata commit is tagged locally but not pushed:

```powershell
git tag -d <tag>
```

Then fix the metadata, recommit, and recreate the tag.

If a wrong tag was already pushed, do not move it. Create a new version tag with
correct metadata, then update `releases/latest.json` in a new release.

If a deployed machine needs an immediate exact release target, support can run:

```bash
cd ~/LabCraft_printer
git fetch origin --tags
./env/bin/python -u tools/update_and_restart.py \
  --repo-root . \
  --python ./env/bin/python \
  --no-relaunch \
  --record-result \
  --target-release <version>
```

That shortened command applies only to pre-M6 development/recovery contexts.
For rc.2 and later, use the authorized app-generated command or follow
`docs/machine_data_update_and_rollback_runbook.md`; direct apply requires all
machine-data binding fields and has no force bypass.
