# Machine-Data Update and Rollback Runbook

This runbook applies to `v1.3.0-rc.2` and later. It describes the updater
preservation boundary; it does not authorize firmware changes or physical
machine operation.

## Normal forward update

Use the Firmware tab's `Check for Updates` and `Update App` controls. The
running authorized app supplies the updater with the exact external root,
machine UUID/ID, activation and migration IDs, active-pointer hash, current
version/commit, and a unique request ID. Do not reconstruct or shorten that
command for routine updates.

After the main app closes, the updater:

1. re-resolves the selected release without changing `HEAD`;
2. acquires `update.lock` and then `configuration.lock`;
3. proves the launch binding still names the active machine;
4. captures all active machine files except `locks/**` and
   `update_history/**`;
5. creates, reopens, and hash-verifies an external ZIP backup;
6. applies the verified tag with a fast-forward-only merge;
7. verifies target `HEAD` and exact protected bytes; and
8. writes an immutable relaunch receipt and advances the deployment anchor.

Only the final receipt enables normal relaunch. Fetching tags may happen
before the backup; merging or resetting Git may not.

The first update from `v1.2.0-rc.6`, `v1.2.0`, or `v1.3.0-rc.1` to rc.2 is
the one exception: those old updaters cannot run future M6 code. That move is
protected by the Milestone 0 off-device copy and the M2/M3 first-start
migration. The first valid rc.2 start creates the one permitted genesis
deployment anchor. Every later update requires M6 evidence.

## Evidence locations

For active machine UUID `<uuid>`, evidence is under:

```text
<machine-data-root>/machines/<uuid>/update_history/
```

Important entries are:

- `deployment_anchor.json`: current app/store authorization;
- `latest_result.json`: hash-bound pointer to the latest immutable terminal
  receipt;
- `latest_ui_result.json`: disposable operator summary;
- `updater_logs/` and `launcher_logs/`: diagnostic logs; and
- `transactions/<update-id>/`: intent, manifest, verified backup, Git result,
  post-check, relaunch/recovery receipt, and optional legacy evidence.

Do not delete, edit, or move these files during incident response. Copy the
whole transaction directory and logs to the support evidence location before
investigation. Coordinates are sensitive machine data and must not be pasted
into public issues.

## Stop conditions

Stop and contact support when any of these occurs:

- `machine_data_protection_failed`: Git was not intentionally changed; retain
  the log and transaction evidence. Reopen is offered only when the current
  deployment still validates.
- `recovery_required`: Git or protected state may have changed. Keep hardware
  stopped. The updater intentionally does not offer normal relaunch.
- startup reports a deployment-anchor mismatch, unfinished update, or legacy
  conflict: do not bypass bootstrap or start an older checkout manually.
- a backup, active pointer, identity, target commit, post-update hash, or
  firmware attestation differs.

Never use an ad hoc `git reset --hard`, copy a saved `local/` over the
canonical store, remove a lock because it looks old, delete an update receipt,
or use another worktree to bypass recovery. Preserve the Milestone 0 Desktop
and external-drive copies.

## Support evidence checklist

Collect read-only evidence before deciding recovery:

```bash
cd /home/labcraft/LabCraft_printer
git status --short
git rev-parse HEAD
cat VERSION
printf '%s\n' "$LABCRAFT_MACHINE_DATA_ROOT"
pgrep -af 'FreeRTOS-interface/[A]pp.py'
```

Also collect the updater path shown in its window, the referenced
`transactions/<update-id>/` directory, `deployment_anchor.json`,
`latest_result.json`, and the release manifest for the selected target. Hash
the copies after collection. A blank environment variable does not authorize
guessing a root; obtain it from the launch binding/receipt or the authorized
app context.

Before reopening a pre-Git failure, support must prove current `HEAD`, active
pointer, deployment anchor, and live protected inventory still match. After a
post-Git failure, recovery must establish both current and target commits,
verify the archived backup, and resolve the immutable stage chain. Automatic
rollback is prohibited.

## Declared schema transition

A release may declare `transition: bootstrap_recovery` with an exact reviewed
adapter ID. The updater first verifies unchanged pre-transition bytes, then
runs only the target-side hardware-free adapter while holding both locks. The
adapter may write governed JSON only through the M4 transaction service. It
must append one configuration event and prove unchanged machine identity,
pointer, coordinates, obstacles, hardware profile, target values, and target
authorization. An unknown adapter or any semantic drift remains
`recovery_required`.

The rc.2 release itself declares `transition: none`.

## Legacy rollback

The normal UI deliberately disables one-click rollback when the target lacks
the M6 machine-data contract. Legacy rollback is limited to the exact reviewed
tags `v1.2.0-rc.6`, `v1.2.0`, and `v1.3.0-rc.1`; tag commit and canonical
release-manifest hash must match the tracked compatibility catalog.

Support must first confirm the machine is idle, preserve external evidence,
verify every saved motion target is current, determine the required firmware
pairing, and record:

- operator name;
- reason;
- service-record reference;
- exact machine-ID confirmation; and
- reviewed firmware-pairing attestation.

Use the full command produced from an authorized launch binding and add all
of these support-only flags:

```text
--rollback
--allow-legacy-rollback
--support-operator <name>
--support-reason <reason>
--support-reference <record>
--machine-id-confirmation <exact-machine-id>
--firmware-attestation <reviewed-pairing-record>
```

The required binding flags are `--machine-data-root`, `--machine-uuid`,
`--machine-id`, `--activation-id`, `--migration-id`,
`--active-pointer-sha256`, `--source-app-version`, `--source-commit`, and
`--update-request-id`. There is intentionally no force/bypass flag.

Before Git reset, the support path verifies the canonical backup, archives any
existing checkout `local/`, exports the exact legacy layout, reopens and hashes
it, and writes an unresolved external legacy-session record. A missing
attestation, unverified target, unknown tag, export fault, or hash mismatch
issues zero reset commands.

## Returning from a legacy release

The legacy app writes only checkout-local `local/`; canonical data stays
frozen. On return to an M6-capable release, bootstrap compares every exported
legacy byte with its baseline before MVC or hardware construction:

- exact unchanged bytes close the session and authorize the M6 deployment;
- additions, deletions, formatting-only rewrites, coordinate changes, and
  calibration changes are all recorded as differences and enter recovery;
- `keep canonical` requires a fresh legacy backup plus operator, reason, and
  service-record evidence; and
- legacy changes are never copied automatically into canonical data.

Governed changes that must be adopted require a separate reviewed M5 preview
and M4 transaction. Opaque calibration-file adoption remains blocked until a
specific support plan exists.

## Rollback of this implementation

Before any M6 record exists, the implementation commit can be reverted in
development. After genesis enrollment or any update transaction, preserve
`update_history/` and use the qualified M6 recovery/compatibility path. Do not
delete the anchor or receipts to make older code start.
