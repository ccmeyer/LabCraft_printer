import copy
import json

from ConfigurationHistoryReader import ConfigurationHistoryReader
from tests.test_machine_data_transactions import _active_context


def test_history_reader_reports_actor_values_and_deterministic_export(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        locations_path = context.paths.config_root / "Locations.json"
        locations = json.loads(locations_path.read_text(encoding="utf-8"))
        locations["camera"]["Y"] += 25
        changed = context.configuration_transactions.commit_documents(
            {"Locations.json": locations},
            operator="Alice",
            reason="Camera recalibration",
            workflow="named_location_modify",
        )
        reader = ConfigurationHistoryReader(context.configuration_transactions)
        rows = reader.read_rows()

        assert len(rows) == 1
        assert rows[0].operator == "Alice"
        assert rows[0].workflow == "named_location_modify"
        assert rows[0].transaction_id == changed.transaction_id
        assert "location:camera" in rows[0].summary
        markdown_a = reader.build_markdown()
        markdown_b = reader.build_markdown()
        assert markdown_a == markdown_b
        assert "Camera recalibration" in markdown_a
        assert f'"Y": {locations["camera"]["Y"]}' in markdown_a
    finally:
        context.close()


def test_current_target_values_are_copies(tmp_path):
    _base, context = _active_context(tmp_path)
    try:
        reader = ConfigurationHistoryReader(context.configuration_transactions)
        first = reader.current_target_values()
        original = copy.deepcopy(first["location:camera"])
        first["location:camera"]["Y"] += 100
        assert reader.current_target_values()["location:camera"] == original
    finally:
        context.close()
