# Calibration Recording Store Migration: Milestone 2 Completion Record

Status: Complete

Prepared: 2026-08-15

## Outcome

Milestone 2 adds an always-attempted, non-authoritative canonical recording
store in shadow mode. The current `calibration.json` writer and every existing
reader remain authoritative. The operator recorder toggle still controls
diagnostic analysis, events, verdicts, and captures; it no longer determines
whether structured canonical persistence is attempted.

The host storage contract, failure injection, fresh-reload lifecycle, and
frozen 8-head x 25-run workload pass. The qualified Raspberry Pi 5 comparison
also passes against the Milestone 1 current-writer candidate limits, and a
tracked Milestone 2 candidate baseline is frozen.

No firmware, device protocol, camera/image-analysis implementation, motion,
dispense, balance, GPIO, or physical pressure behavior changed. No historical
or production experiment was read or modified.

## Implemented contract

- `CalibrationRecordingStore` owns canonical JSON normalization and hashing,
  per-process `updates.jsonl`, immutable `result.json`, schema-v2
  `run_meta.json`, and the append-only `calibration_index.jsonl` projection.
- Updates are appended, flushed, and fsynced before the unchanged legacy
  in-memory append and atomic whole-file rewrite. Diagnostic analysis remains
  optional and non-authoritative.
- Terminal ordering is recorder drain, result atomic commit, index append,
  then final run metadata. Identical retries are idempotent; conflicting
  result/index identities fail visibly.
- Truncated final JSONL lines can be ignored during explicit recovery;
  interior corruption, invalid hashes, broken identity linkage, duplicate
  events, and conflicting content are rejected. The index can be rebuilt
  deterministically from valid result bundles without changing those bundles.
- Shadow failures are recorded as manager diagnostics while legacy process
  completion/error/stop behavior continues. A completed calibration with no
  canonical update is represented as `storage_error`, not a valid result.
- The developer rollback switch is
  `LABCRAFT_CALIBRATION_STORE_SHADOW=0`. It is separate from the recorder UI
  and is not the Milestone 3 capture-retention policy.
- Production processes that do not yet declare a terminal-result adapter are
  written with `result_kind=none` plus `terminal_adapter_pending_m3`; the store
  is not read by production or UI consumers in this milestone.

## SIL and automated evidence

The registered `calibration_storage_shadow_contract_v1` journey reuses the
seven reviewed Milestone 1 fixture families and proves 16 process lifecycles,
17 ordered updates, exact fixture/legacy/recorder/canonical parity, 16 terminal
results and index events, multi-head isolation, capture proxies, fresh MVC
reload, and unchanged UI selection/application through legacy source
coordinates.

The registered `calibration_storage_shadow_8x25_v1` workload proves, per run:

| Evidence | Exact value |
| --- | ---: |
| Process runs | 200 |
| Legacy updates | 232 |
| Canonical updates | 232 |
| Canonical results | 200 |
| Index events | 200 |
| Diagnostic recording directories | 200 |
| Workload captures | 0 |
| Separate key-evidence drain probe | 2 frames |

Failure coverage includes typed filesystem failures at run creation, update
append/flush/fsync, result write/flush/fsync/replace, index
append/flush/fsync, and final metadata; result/index retry idempotency;
collision/corruption rejection; and manager continuity when canonical update
append fails.

Final host validation:

```text
133 passed: focused store, failure, manager, baseline, manifest, and Pi-wrapper contracts
1 passed in 9.08s: shadow lifecycle SIL
1 passed in 130.37s: shadow 8x25 stress SIL
17 passed in 2.22s: final explicit-identity/native-stderr Pi wrapper contract
142 passed in 9.43s: final baseline, registry, selection, and Pi-wrapper contracts
4737 passed, 139 skipped, 503 warnings in 227.40s: final full Python suite
```

## Pi qualification

| Field | Qualified value |
| --- | --- |
| Source commit | `0f93e037c26c8fa8d165e433a129f918b671643e` (clean) |
| Target | Raspberry Pi 5 Model B Rev 1.0, aarch64 |
| OS | Linux `6.12.20+rpt-rpi-2712` |
| Storage | NVMe, ext4, `/dev/nvme0n1p2` bind-mounted report root |
| Runtime | Python 3.11.2, PySide6 6.7.1, Qt 6.7.1, offscreen |
| Isolation | Bubblewrap private `/dev`, read-only root, network unshared |
| Report set | `verification_reports/virtual_workflows/pi-sil/calibration_storage_shadow_8x25_v1/20260815T072739869392Z_0f93e037c26c_report_set/report_set.json` |
| Report-set SHA-256 | `bcb074155830a0b43e08251ef6d1c466d668974392c8ab7ccd0ce7edd048e005` |
| Retrieved archive SHA-256 | `f7ee8e2eade3eda4d66bb0a11c4a597187bf06f5d4f1f6a25097dc192af29182` |
| Legacy baseline SHA-256 | `236b15ee5addcaec26621072fb6cbd8672337a098bf77f93e948a5805cae86b5` |
| Tracked shadow baseline | `tests/performance/baselines/calibration_storage_shadow_pi5_v1.json` |
| Shadow baseline SHA-256 | `6557555ddf84e3e56f97f39510039d4894a1ce20c4b6b48670e102ee50b83108` |

Raw evidence:

| Role | Run ID | Report SHA-256 | Duration |
| --- | --- | --- | ---: |
| Warmup | `dbf3609f-6644-4cd6-afc0-1b3102e46d4c` | `679b14bd509f140366e2b28b23c65b803d60cbf18a24a0dc78299c96e2abaafd` | 226.91 s |
| Measured | `cce40a1a-d3f5-4273-910d-bd9fffe8d06c` | `457c8e6939531132c7513bb516468796c380c2accd6e26f49138e91c16b82786` | 232.05 s |
| Measured | `054e517b-6ae6-46cd-ad2d-eda79c1f3950` | `c4a032ea76e40d83eab850034431cb1d41f466c1d36ec00a6728cb4f3a192f34` | 233.51 s |
| Measured | `88396cd3-aa6b-433d-8563-31072242bbb3` | `cd142a570b9659cf75943a58c9f1a1e43353dd78456774a04a4dc76f8b7312e5` | 233.78 s |

All common comparisons passed:

| Metric | Measured values | Milestone 1 upper limit |
| --- | --- | ---: |
| Legacy rewrite p95 | 398.99, 399.85, 400.22 ms | 496.50 ms |
| Recorder append p95 | 2.271, 2.272, 2.299 ms | 3.831 ms |
| Update latency p95 | 400.11, 400.92, 401.13 ms | 498.60 ms |
| Process finalize p95 | 100.99, 100.66, 101.54 ms | 121.24 ms |
| First-quartile update p95 | 110.82, 110.45, 110.99 ms | 113.75 ms |
| Last-quartile update p95 | 461.65, 449.44, 462.59 ms | 538.51 ms |
| History load p95 | 2.539, 2.504, 2.572 ms | 4.474 ms |
| Fresh reload | 250.90, 280.32, 75.03 ms | 431.24 ms |
| Peak RSS | 476,790,784; 525,664,256; 573,898,752 B | 862,846,976 B |
| RSS growth | 16,302,080; 16,875,520; 18,268,160 B | 22,380,544 B |

New canonical candidate limits are derived from the three run-level p95 values
using the frozen maximum-plus-margin policy:

| Metric | Measured p95 values | Candidate upper limit |
| --- | --- | ---: |
| Canonical update append | 13.607, 13.767, 14.072 ms | 17.514 ms |
| Result finalize | 0.276, 0.272, 0.276 ms | 1.276 ms |
| Index append | 3.378, 3.416, 3.411 ms | 4.416 ms |

Each measured run retained 7,840,095 bytes of legacy `calibration.json` and
30,021,683 total scenario bytes. The corresponding Milestone 1 scenario total
was 26,367,422 bytes, so dual-write mode adds 3,654,261 bytes (about 13.9%) for
this workload. Additive artifact growth is measured but deliberately not gated
against the legacy total-byte limit because both stores coexist in Milestone 2.

## Source coordination and restoration

The Pi originally contained the clean tracked Milestone 1 commit plus
pre-existing untracked HIL helpers/artifacts. Those three top-level targets
were moved to an explicit directory outside the checkout for measurement,
then restored. Before staging and after restoration, their deterministic tar
SHA-256 was
`1d491082fe8f55967b971ae19a2d3a2b74a670171fea667aeb6074136694a843`;
their sizes remained 17,082 bytes (`flash_and_test.sh`), 5,664,043 bytes
(`hil_staging`), and 82,020 bytes (`run_selftest.py`). The Pi tracked checkout
was fast-forwarded with locally verified Git bundles; no external branch push
or firmware operation was used.

## Risks, limitations, and rollback

Shadow storage remains non-authoritative and therefore cannot yet eliminate
the growing whole-file legacy rewrite. Existing readers cannot use canonical
terminal filtering or stable result identity until later milestones. The
production terminal adapters and operator capture-retention policy remain
Milestone 3 work. Image analysis remains deferred.

Operational rollback is to set `LABCRAFT_CALIBRATION_STORE_SHADOW=0` before
application launch; legacy persistence and readers remain intact. Code rollback
removes the store, manager shadow hooks, SIL scenarios/tests, Pi wrapper
extensions, baseline, and documentation. Canonical shadow artifacts may then
be retained as non-authoritative evidence or removed by an explicit operator
decision. No firmware, protocol, motion, pressure, or hardware recovery is
required.
