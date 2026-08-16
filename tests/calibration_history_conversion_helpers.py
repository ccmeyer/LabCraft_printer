from __future__ import annotations

import json
from pathlib import Path


def step(*, run_id="legacy-session-1", mean_volume=10.0):
    return {
        "timestamp": "2025-01-02T03:04:05Z",
        "settings": {"print_width": 1400, "print_pressure": 1.2},
        "meta": {
            "run_id": run_id,
            "printer_head_id": "head-1",
            "stock_id": "stock-1",
        },
        "phase": "pressure_sweep_characterization",
        "result": {
            "pressures": [
                {
                    "pressure": 1.2,
                    "mean_volume": mean_volume,
                    "cv_volume_percent": 3.0,
                    "valid": True,
                }
            ]
        },
    }


def experiment(tmp_path: Path, *, steps=None, outcome="completed") -> Path:
    root = tmp_path / "historical-experiment"
    root.mkdir()
    document = {
        "schema_version": 1,
        "runs": [
            {
                "run_id": "legacy-session-1",
                "started_at": "2025-01-02T03:00:00Z",
                "ended_at": "2025-01-02T03:05:00Z",
                "outcome": outcome,
                "printer_head_id": "head-1",
                "stock_id": "stock-1",
                "reagent_name": "Synthetic Reagent",
                "steps": {
                    "pressure_sweep_characterization": steps or [step()],
                },
            }
        ],
    }
    (root / "calibration.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    return root
