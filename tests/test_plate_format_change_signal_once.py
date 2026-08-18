import pytest

from Model import Model, WellPlate


def test_set_plate_format_emits_change_signal_once(tmp_path):
    plate_data = [
        {"name": "p1", "rows": 2, "columns": 2, "spacing": 10, "default": True, "calibrations": {}},
        {"name": "p2", "rows": 3, "columns": 3, "spacing": 10, "default": False, "calibrations": {}},
    ]
    plates_tmp = tmp_path / "Plates.json"
    plates_tmp.write_text("[]", encoding="utf-8")
    wp = WellPlate(plate_data, str(plates_tmp))

    calls = []
    wp.plate_format_changed_signal.connect(lambda: calls.append(1))

    wp.set_plate_format("p2")

    assert len(calls) == 1


def _alternate_plate_name(model):
    current = model.well_plate.get_current_plate_name()
    return next(
        plate["name"]
        for plate in model.well_plate.all_plate_data
        if plate["name"] != current
    )


def test_runtime_rebuild_preserves_plate_signal_but_suppresses_reassignment(
    experiment_model_factory,
):
    model = experiment_model_factory()
    model._well_plate_reassignment_suppression_depth = 0
    loaded_events = []
    ui_events = []
    model.experiment_loaded.emit = lambda: loaded_events.append("loaded")
    model.well_plate.plate_format_changed_signal.connect(model.update_well_plate)
    model.well_plate.plate_format_changed_signal.connect(
        lambda: ui_events.append("format_changed")
    )

    model._set_plate_format_for_runtime_rebuild(_alternate_plate_name(model))

    assert ui_events == ["format_changed"]
    assert loaded_events == []
    assert model._well_plate_reassignment_suppression_depth == 0


def test_runtime_rebuild_guard_is_nesting_safe_and_restores_after_failure(
    experiment_model_factory,
    monkeypatch,
):
    model = experiment_model_factory()
    model._well_plate_reassignment_suppression_depth = 0
    observed_depths = []

    def nested_failure(plate_name):
        observed_depths.append(model._well_plate_reassignment_suppression_depth)
        if plate_name == "outer":
            model._set_plate_format_for_runtime_rebuild("inner")
        else:
            raise RuntimeError("inner format failure")

    monkeypatch.setattr(model.well_plate, "set_plate_format", nested_failure)

    with pytest.raises(RuntimeError, match="inner format failure"):
        model._set_plate_format_for_runtime_rebuild("outer")

    assert observed_depths == [1, 2]
    assert model._well_plate_reassignment_suppression_depth == 0


def test_unsuppressed_format_change_retains_automatic_reassignment(
    experiment_model_factory,
):
    model = experiment_model_factory()
    model._well_plate_reassignment_suppression_depth = 0
    loaded_events = []
    model.experiment_loaded.emit = lambda: loaded_events.append("loaded")
    model.well_plate.plate_format_changed_signal.connect(model.update_well_plate)

    model.well_plate.set_plate_format(_alternate_plate_name(model))

    assert loaded_events == ["loaded"]
