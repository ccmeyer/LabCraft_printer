from __future__ import annotations

import json
from pathlib import Path


PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "virtual_workflows"
    / "fixtures"
    / "calibration_storage_secondary_consumers_v1.json"
)


def test_secondary_consumer_inventory_has_no_pending_dispositions():
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    assert payload["schema_name"] == "labcraft.calibration_secondary_consumer_inventory"
    assert payload["schema_version"] == 1
    rows = payload["consumers"]
    assert len(rows) == 13
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["disposition"] and row["disposition"] != "pending" for row in rows)
    assert all(row["fallback"] for row in rows)
