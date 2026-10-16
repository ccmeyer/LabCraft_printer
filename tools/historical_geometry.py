"""Derive bounded replay geometry from original images, never expected tail labels."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests/fixtures/dense_tail_geometry_manifest.json"
EXPERIMENT = "Stream_characterization-20260327_225650"
RECEIPT = "dense_tail_geometry_provenance.json"
PARAMETERS = dict(roi_width_frac=0.35, roi_top_frac=0.1, roi_bottom_frac=1.0,
                  corridor_width_frac=0.7, nozzle_guard_px=2, min_component_area_px=120)
COLUMNS = ("capture_id", "flash_delay_us", "delay_from_emergence_us", "cutoff_y_px",
           "selected_component_top_y_px", "geometry_silhouette_status")


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def contained(root, relative):
    p = PurePosixPath(relative)
    if (p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative
            or p.as_posix() != relative):
        raise ValueError(f"Invalid geometry input path: {relative}")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Geometry input escapes root: {relative}")
    return result


def source_inventory(source, entries):
    """Read only manifest-selected features and their exact referenced captures."""
    inputs, runs = {}, {}
    for relative in sorted(entries):
        if not relative.endswith("/phase_features.csv"):
            continue
        feature = contained(source, relative)
        data = feature.read_bytes()
        if sha(data) != entries[relative]:
            raise ValueError(f"Historical feature hash mismatch: {relative}")
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        run_id = feature.parents[1].name
        images, captures = {}, set()
        for row in rows:
            capture = row["capture_id"]
            if not capture or capture in captures:
                raise ValueError(f"Duplicate/empty geometry capture: {run_id}/{capture}")
            captures.add(capture)
            image_relative = f"{EXPERIMENT}/calibration_recordings/DropletTimecourseProcess/{run_id}/{row['image_relpath']}"
            images[image_relative] = sha(contained(source, image_relative).read_bytes())
        if not rows:
            raise ValueError(f"Empty geometry run: {run_id}")
        inventory = {relative: sha(data), **images}
        inputs[run_id] = inventory
        runs[run_id] = (relative, rows)
    if not runs:
        raise ValueError("No manifest-selected dense geometry runs")
    return inputs, runs


def implementation():
    import cv2
    import numpy
    import scipy
    return {"algorithm": "direct_threshold_silhouette_geometry_v1", "parameters": PARAMETERS,
            # Git checkouts may use CRLF; pin the same LF-normalized source.
            "implementation_lf_sha256": {p: sha((ROOT / p).read_text(encoding="utf-8").encode("utf-8")) for p in
                ("tools/historical_geometry.py", "tools/stream_analysis/silhouette.py")},
            "dependencies": {"opencv": cv2.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__}}


def geometry_rows(source, run_id, rows):
    import cv2
    from tools.stream_analysis.silhouette import _analyze_stage3_gray
    result = []
    for row in rows:
        tracked = dict(row)
        for key in ("tracked_nozzle_x_px", "tracked_nozzle_y_px", "tracked_confidence"):
            tracked[key] = float(row[key])
            if not math.isfinite(tracked[key]):
                raise ValueError(f"Nonfinite geometry coordinate: {run_id}/{key}")
        frame = {**row, **{key: int(row[key]) for key in
                          ("flash_delay_us", "delay_from_emergence_us", "capture_index")}}
        relative = f"{EXPERIMENT}/calibration_recordings/DropletTimecourseProcess/{run_id}/{row['image_relpath']}"
        gray = cv2.imread(str(contained(source, relative)), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError(f"Cannot decode geometry image: {relative}")
        metric = _analyze_stage3_gray(run_id, frame, tracked, gray, **PARAMETERS)["metric_row"]
        result.append({"capture_id": row["capture_id"], "flash_delay_us": frame["flash_delay_us"],
                       "delay_from_emergence_us": frame["delay_from_emergence_us"],
                       "cutoff_y_px": metric.get("cutoff_y_px"),
                       "selected_component_top_y_px": metric.get("selected_component_top_y_px"),
                       "geometry_silhouette_status": metric["silhouette_status"]})
    return result


def derive(source, destination, entries, *, expected=None):
    inputs, runs = source_inventory(source, entries)
    recipe = implementation()
    source_hashes = {run: sha(canonical(inventory)) for run, inventory in inputs.items()}
    if expected is not None:
        if (expected["recipe"] != recipe or
                {k: v["source_inventory_sha256"] for k, v in expected["runs"].items()} != source_hashes):
            raise ValueError("Geometry source/implementation differs from pinned contract")
    receipt = {"schema_version": 1, "recipe": recipe, "source_files": inputs}
    outputs = {}
    for run_id, (relative, rows) in runs.items():
        target_relative = str(PurePosixPath(relative).with_name("tail_geometry.csv"))
        target = contained(destination, target_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(geometry_rows(source, run_id, rows))
        outputs[run_id] = {"path": target_relative, "sha256": sha(target.read_bytes()),
                           "row_count": len(rows), "source_inventory_sha256": source_hashes[run_id]}
        print(f"Derived geometry: {run_id} ({len(rows)} captures)", flush=True)
    # Rehash originals after extraction, detecting changes during analysis.
    after, _ = source_inventory(source, entries)
    if after != inputs:
        raise ValueError("Geometry source changed during derivation")
    receipt_bytes = canonical(receipt)
    (destination / RECEIPT).write_bytes(receipt_bytes)
    contract = {"schema_version": 1, "recipe": recipe, "runs": outputs,
                "receipt": {"path": RECEIPT, "sha256": sha(receipt_bytes)}}
    if expected is not None and expected != contract:
        raise ValueError("Derived geometry differs from pinned output contract")
    return contract


def validate_sources(source, entries, expected):
    inputs, _ = source_inventory(source, entries)
    if (expected["recipe"] != implementation() or
            {k: v["source_inventory_sha256"] for k, v in expected["runs"].items()} !=
            {k: sha(canonical(v)) for k, v in inputs.items()}):
        raise ValueError("Geometry source/implementation differs from pinned contract")


def merge_geometry(features, geometry_path):
    """Join measured geometry by capture and both times; never by row position."""
    with Path(geometry_path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("Missing or unexpected replay geometry columns")
        geometry = list(reader)

    def keyed(rows):
        result = {}
        for row in rows:
            key = (row["capture_id"], int(row["flash_delay_us"]), int(row["delay_from_emergence_us"]))
            if not key[0] or key in result:
                raise ValueError("Duplicate/empty replay geometry identity")
            result[key] = row
        return result

    source, measured = keyed(features), keyed(geometry)
    if source.keys() != measured.keys():
        raise ValueError("Replay geometry capture/time inventory mismatch")
    merged = []
    for key, feature in source.items():
        row = measured[key]
        for column in ("cutoff_y_px", "selected_component_top_y_px"):
            if row[column] and not math.isfinite(float(row[column])):
                raise ValueError("Nonfinite replay geometry")
            if row["geometry_silhouette_status"] == "ok" and not row[column]:
                raise ValueError("Missing accepted replay geometry")
        if not row["geometry_silhouette_status"]:
            raise ValueError("Missing replay geometry status")
        merged.append({**feature, **row})
    return merged


def load_contract():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("schema_version") != 1 or not contract.get("runs"):
        raise ValueError("Invalid geometry contract")
    return contract


def verify(root):
    from tools.historical_fixtures import verified_files
    contract = load_contract()
    entries = {r["path"]: r["sha256"] for r in contract["runs"].values()}
    entries[contract["receipt"]["path"]] = contract["receipt"]["sha256"]
    verified_files(root, entries)
    return contract


def main():
    from tools.historical_fixtures import external_root, load_manifest, verified_files
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True,
                        help="New external candidate directory; review candidate-contract.json before pinning")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = external_root(args.destination)
    if destination == source or destination.is_relative_to(source):
        raise ValueError("Geometry destination must be separate from source archive")
    entries = load_manifest()["dense_stream"]
    verified_files(source, entries)
    destination.mkdir(parents=True, exist_ok=False)
    contract = derive(source, destination, entries)
    (destination / "candidate-contract.json").write_bytes(canonical(contract))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()
