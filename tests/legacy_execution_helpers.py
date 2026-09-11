"""Synthetic legacy inputs shared by reconstruction and migration tests."""
import json
from pathlib import Path

PURE_VOLUME_NL = 143.59278258103592
UTP_VOLUME_NL = 10.5
HISTORICAL_NONFILL_NL = 2559.9845212965747


def _design(*, applied=True, include_exact_volumes=True, uploaded=False):
    pure_option = {
        "name": "PURE MM",
        "targets": [1.0],
        "units": "x",
        "printing_mode": "stream",
        "forced_stock_conc": 1.11,
    }
    utp_option = {
        "name": "UTP (dil)",
        "targets": [10000.0],
        "units": "nM",
        "printing_mode": "droplet",
        "forced_stock_conc": 95000.0,
    }
    if include_exact_volumes:
        pure_option["droplet_nL"] = PURE_VOLUME_NL
        pure_option["intended_droplet_nL"] = 60.0
        utp_option["droplet_nL"] = UTP_VOLUME_NL
    payload = {
        "metadata": {
            "name": "legacy-synthetic",
            "replicates": 1,
            "target_reaction_volume_nL": 2500.0,
            "printed_volume_tolerance_nL": 50.0,
            "final_reaction_volume_nL": 2500.0,
            "fill_reagent_name": "Water",
            "fill_printing_mode": "droplet",
            "fill_droplet_volume_nL": 10.0,
            "plate_name": "test-plate",
            "plate_rows": 8,
            "plate_columns": 12,
        },
        "factors": [
            {"name": "PURE MM", "kind": "additive", "options": [pure_option]},
            {"name": "UTP", "kind": "choice", "options": [utp_option]},
        ],
        "applied_imaging_calibrations": {
            "schema_version": 1,
            "records": (
                {
                    "pure-record": {
                        "stock_id": "PURE MM_1.11_x",
                        "printer_head_id": "head-pure",
                        "applied_design_volume_nL": 143.6,
                        "recorded_at": "2026-01-02T00:00:00Z",
                    },
                    "utp-record": {
                        "stock_id": "UTP (dil)_95000.00_nM",
                        "printer_head_id": "head-utp",
                        "applied_design_volume_nL": 10.4,
                        "recorded_at": "2026-01-02T00:01:00Z",
                    },
                }
                if applied
                else {}
            ),
        },
    }
    if uploaded:
        payload["uploaded_design"] = {
            "reactions": [
                [
                    {"factor": "PURE MM", "option": None, "target": 1.0},
                    {"factor": "UTP", "option": "UTP (dil)", "target": 10000.0},
                ]
            ],
            "csv_filename": "missing-upload.csv",
            "well_ids": ["A1"],
        }
    return payload


def _progress(*, pure_target=16, utp_target=25, added=True):
    return {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                "PURE MM_1.11_x": {
                    "target_droplets": pure_target,
                    "added_droplets": pure_target if added else 0,
                },
                "UTP (dil)_95000.00_nM": {
                    "target_droplets": utp_target,
                    "added_droplets": utp_target if added else 0,
                },
            },
            "completed": bool(added),
        },
        "__plate__": {
            "schema_version": 1,
            "name": "test-plate",
            "rows": 8,
            "columns": 12,
        },
    }


def _write_folder(
    directory: Path,
    *,
    design=None,
    progress=None,
    key_pure=16,
    key_utp=25,
    audit_events=None,
):
    directory.mkdir()
    design = _design() if design is None else design
    (directory / "experiment_design.json").write_text(
        json.dumps(design, indent=2), encoding="utf-8"
    )
    if progress is not None:
        (directory / "progress.json").write_text(
            json.dumps(progress, indent=2), encoding="utf-8"
        )
    if key_pure is not None:
        (directory / "key.csv").write_text(
            "Well ID,PURE MM_1.11_x_143.6nL,UTP (dil)_95000.00_nM_10.4nL\n"
            f"A1,{float(key_pure):.1f},{float(key_utp):.1f}\n",
            encoding="utf-8",
        )
    if audit_events:
        (directory / "experiment_audit.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in audit_events),
            encoding="utf-8",
        )
    (directory / "concentration_key.csv").write_text(
        "Well ID,PURE MM_x\nA1,1\n", encoding="utf-8"
    )
    return design
