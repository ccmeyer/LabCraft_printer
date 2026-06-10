import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Model import (
    EJECTION_VOLUME_HARD_MAX_NL,
    EJECTION_VOLUME_HARD_MIN_NL,
    ExperimentModel,
    printing_mode_allowed_range_nl,
)


class _SignalRecorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def test_refresh_runtime_after_plan_change_rebinds_keys_and_emits_well_refresh():
    stock_updated = _SignalRecorder()
    well_state_changed = _SignalRecorder()
    write_calls = []
    rebind_calls = []

    em = SimpleNamespace(
        _has_runtime_assignments=lambda: True,
        _rebind_runtime_assignments_to_current_plans=lambda: rebind_calls.append(True) or True,
        write_keys_now=lambda: write_calls.append(True),
        stock_updated=stock_updated,
        _runtime_well_plate=SimpleNamespace(well_state_changed_signal=well_state_changed),
    )
    em._refresh_runtime_after_plan_change = (
        ExperimentModel._refresh_runtime_after_plan_change.__get__(em, ExperimentModel)
    )

    refreshed = em._refresh_runtime_after_plan_change(write_keys_if_assigned=True)

    assert refreshed is True
    assert rebind_calls == [True]
    assert write_calls == [True]
    assert stock_updated.calls == [()]
    assert well_state_changed.calls == [("all",)]


def test_apply_droplet_volume_for_option_refreshes_runtime_after_apply():
    refresh_calls = []
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=10.0,
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
        "units": "mM",
        "droplets_per_target": {},
    }
    stock_row = {
        "factor_name": "glycerol",
        "option_name": "",
        "stock_concentration": 10.0,
        "droplet_volume_nL": 10.0,
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[stock_row],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )

    result = em.apply_droplet_volume_for_option("glycerol", None, 12.0, write_keys_if_assigned=False)

    assert refresh_calls == [{"write_keys_if_assigned": False}]
    assert option.droplet_nL == 12.0
    assert option.intended_droplet_nL == 10.0
    assert option.forced_stock_conc == 10.0
    assert stock["droplet_volume_nL"] == 12.0
    assert stock_row["droplet_volume_nL"] == 12.0
    assert em.unsaved_changes is True
    assert result["stock_row_updated"] is True
    assert result["saved_experiment"] is False


def test_apply_fill_droplet_volume_refreshes_runtime_after_apply():
    refresh_calls = []
    generate_calls = []

    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 10.0},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: generate_calls.append(True),
        _refresh_runtime_after_plan_change=lambda **kwargs: refresh_calls.append(kwargs) or True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    result = em.apply_fill_droplet_volume(12.0, write_keys_if_assigned=True)

    assert generate_calls == [True]
    assert refresh_calls == [{"write_keys_if_assigned": True}]
    assert em.metadata["intended_fill_droplet_volume_nL"] == 10.0
    assert em.unsaved_changes is True
    assert result["new_fill_nL"] == 12.0
    assert result["total_drops_new"] == 42
    assert result["saved_experiment"] is False


def test_printing_mode_volume_range_uses_shared_hard_envelope():
    assert EJECTION_VOLUME_HARD_MIN_NL == pytest.approx(1.0)
    assert EJECTION_VOLUME_HARD_MAX_NL == pytest.approx(250.0)
    assert printing_mode_allowed_range_nl("droplet") == (
        EJECTION_VOLUME_HARD_MIN_NL,
        EJECTION_VOLUME_HARD_MAX_NL,
    )
    assert printing_mode_allowed_range_nl("stream") == (
        EJECTION_VOLUME_HARD_MIN_NL,
        EJECTION_VOLUME_HARD_MAX_NL,
    )


def _build_apply_droplet_volume_model(*, printing_mode="droplet", current_volume=10.0):
    option = SimpleNamespace(
        name="glycerol",
        droplet_nL=float(current_volume),
        units="mM",
        targets=[0.5],
        starting_conc=0.0,
        printing_mode=printing_mode,
    )
    factor = SimpleNamespace(name="glycerol", kind="additive", options=[option])
    stock = {
        "stock_concentration": 10.0,
        "droplet_volume_nL": float(current_volume),
        "units": "mM",
        "droplets_per_target": {},
    }

    em = SimpleNamespace(
        plans_per_option={("glycerol", None): {"stocks": [stock], "n_stocks": 1}},
        factors=[factor],
        metadata={"final_reaction_volume_nL": 500.0},
        _stock_rows_cache=[],
        _normalize_target_key=lambda value: round(float(value), 6),
        _refresh_plan_preview_maps=lambda: None,
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        _last_worst_nonfill_volume_nL=0.0,
        unsaved_changes=False,
    )
    em._evaluate_single_forced_target = (
        ExperimentModel._evaluate_single_forced_target.__get__(em, ExperimentModel)
    )
    em.apply_droplet_volume_for_option = (
        ExperimentModel.apply_droplet_volume_for_option.__get__(em, ExperimentModel)
    )
    return em, option


@pytest.mark.parametrize(
    ("new_volume", "printing_mode"),
    [
        (60.0, "droplet"),
        (10.0, "stream"),
        (30.0, "stream"),
        (30.0, "droplet"),
    ],
)
def test_apply_droplet_volume_for_option_accepts_explicit_mode_inside_hard_envelope(
    new_volume,
    printing_mode,
):
    em, option = _build_apply_droplet_volume_model(printing_mode=printing_mode)

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        new_volume,
        write_keys_if_assigned=False,
        printing_mode=printing_mode,
    )

    assert option.droplet_nL == pytest.approx(new_volume)
    assert option.printing_mode == printing_mode
    assert result["new_droplet_nL"] == pytest.approx(new_volume)
    assert result["applied_printing_mode"] == printing_mode


@pytest.mark.parametrize(
    ("new_volume", "printing_mode", "match"),
    [
        ("not-a-number", "droplet", "must be numeric"),
        (0.0, "droplet", "outside the allowed range for droplet mode"),
        (-1.0, "stream", "outside the allowed range for stream mode"),
        (float("inf"), "stream", "outside the allowed range for stream mode"),
        (250.1, "stream", "outside the allowed range for stream mode"),
    ],
)
def test_apply_droplet_volume_for_option_rejects_values_outside_hard_envelope(
    new_volume,
    printing_mode,
    match,
):
    em, _option = _build_apply_droplet_volume_model(printing_mode=printing_mode)

    with pytest.raises(ValueError, match=match):
        em.apply_droplet_volume_for_option(
            "glycerol",
            None,
            new_volume,
            write_keys_if_assigned=False,
            printing_mode=printing_mode,
        )


@pytest.mark.parametrize(
    ("new_volume", "printing_mode"),
    [
        (10.0, "stream"),
        (30.0, "stream"),
        (30.0, "droplet"),
    ],
)
def test_apply_fill_droplet_volume_accepts_explicit_mode_inside_hard_envelope(
    new_volume,
    printing_mode,
):
    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 12.0, "fill_printing_mode": printing_mode},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    result = em.apply_fill_droplet_volume(
        new_volume,
        write_keys_if_assigned=True,
        printing_mode=printing_mode,
    )

    assert em.metadata["fill_droplet_volume_nL"] == pytest.approx(new_volume)
    assert em.metadata["fill_printing_mode"] == printing_mode
    assert result["new_fill_nL"] == pytest.approx(new_volume)
    assert result["applied_printing_mode"] == printing_mode


@pytest.mark.parametrize(
    ("new_volume", "printing_mode", "match"),
    [
        ("not-a-number", "droplet", "must be numeric"),
        (0.0, "droplet", "outside the allowed range for droplet mode"),
        (-1.0, "stream", "outside the allowed range for stream mode"),
        (float("inf"), "stream", "outside the allowed range for stream mode"),
        (250.1, "stream", "outside the allowed range for stream mode"),
    ],
)
def test_apply_fill_droplet_volume_rejects_values_outside_hard_envelope(
    new_volume,
    printing_mode,
    match,
):
    em = SimpleNamespace(
        metadata={"fill_droplet_volume_nL": 60.0, "fill_printing_mode": printing_mode},
        preview_fill_requantized=lambda new_fill: {
            "total_drops_old": 50,
            "total_drops_new": 42,
            "total_drops_delta": -8,
        },
        generate_experiment=lambda: None,
        _refresh_runtime_after_plan_change=lambda **kwargs: True,
        unsaved_changes=False,
    )
    em.apply_fill_droplet_volume = (
        ExperimentModel.apply_fill_droplet_volume.__get__(em, ExperimentModel)
    )

    with pytest.raises(ValueError, match=match):
        em.apply_fill_droplet_volume(
            new_volume,
            write_keys_if_assigned=True,
            printing_mode=printing_mode,
        )


def _configure_calibrated_volume_design(em):
    em.factors = []
    em.add_additive(
        "glycerol",
        [0.9],
        "mM",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    em.save_experiment()


def _first_option_payload(payload, factor_name):
    for factor in payload["factors"]:
        if factor["name"] == factor_name:
            return factor["options"][0]
    raise AssertionError(f"Factor {factor_name!r} not found")


def _first_saved_target(em, factor_name):
    stock = em.plans_per_option[(factor_name, None)]["stocks"][0]
    return next(iter(stock["droplets_per_target"].values()))


def _stock_id_for_design_row(em, factor_name, option_name=None):
    for row in em.get_stock_table_rows(include_fill=True):
        if row.get("factor_name") == factor_name and (row.get("option_name") or None) == option_name:
            return em._stock_row_base_id(row)
    raise AssertionError(f"Stock row for {factor_name!r}/{option_name!r} not found")


def _printer_head(stock_id, *, printer_head_id="head-1", printing_mode="droplet"):
    return SimpleNamespace(
        get_stock_id=lambda: stock_id,
        printer_head_id=printer_head_id,
        get_printing_mode=lambda: printing_mode,
    )


def _machine_model_for_calibration(*, pw_us=1450, pressure_psi=1.35):
    return SimpleNamespace(
        get_print_pulse_width=lambda: pw_us,
        get_current_print_pressure=lambda: pressure_psi,
        get_target_print_pressure=lambda: pressure_psi,
    )


def test_apply_droplet_volume_for_option_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    option = _first_option_payload(payload, "glycerol")
    assert option["droplet_nL"] == 30.0
    assert option["printing_mode"] == "droplet"
    assert option["intended_droplet_nL"] == 10.0
    assert option["forced_stock_conc"] == result["stock_concentration"]
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


def test_apply_droplet_volume_for_option_can_switch_printing_mode(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    stock_id = _stock_id_for_design_row(em, "glycerol")
    head = _printer_head(stock_id, printing_mode="stream")

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 30.0,
            "pw_us": 1800,
            "pressure_psi": 1.80,
            "run_id": "stream-run",
            "phase": "stream",
            "timestamp": "2026-03-18T10:00:00Z",
            "source_row_fingerprint": ("stream-run", "stream", "2026-03-18T10:00:00Z", 1800, 1.80, 30.0),
        },
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    option = _first_option_payload(payload, "glycerol")
    assert option["droplet_nL"] == 30.0
    assert option["printing_mode"] == "stream"
    assert option["intended_droplet_nL"] == 10.0
    assert option["intended_printing_mode"] == "droplet"
    assert result["original_printing_mode"] == "droplet"
    assert result["applied_printing_mode"] == "stream"

    record = em.get_applied_imaging_calibration(printer_head=head)
    assert record["printing_mode"] == "stream"
    assert record["original_printing_mode"] == "droplet"
    assert record["applied_printing_mode"] == "stream"
    assert record["run_id"] == "stream-run"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    reloaded_option = reloaded.factors[0].options[0]
    assert reloaded_option.droplet_nL == 30.0
    assert reloaded_option.printing_mode == "stream"
    assert reloaded_option.intended_droplet_nL == 10.0
    assert reloaded_option.intended_printing_mode == "droplet"

    validation = reloaded.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(pw_us=1800, pressure_psi=1.80),
    )
    assert validation["ok"] is True


def test_apply_fill_droplet_volume_persists_effective_and_intended_volume(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_fill_droplet_volume(30.0, write_keys_if_assigned=False)

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["fill_droplet_volume_nL"] == 30.0
    assert payload["metadata"]["fill_printing_mode"] == "droplet"
    assert payload["metadata"]["intended_fill_droplet_volume_nL"] == 10.0
    assert result["saved_experiment"] is True
    assert em.unsaved_changes is False


def test_apply_fill_droplet_volume_can_switch_printing_mode(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)

    result = em.apply_fill_droplet_volume(
        30.0,
        write_keys_if_assigned=False,
        printing_mode="stream",
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["fill_droplet_volume_nL"] == 30.0
    assert payload["metadata"]["fill_printing_mode"] == "stream"
    assert payload["metadata"]["intended_fill_droplet_volume_nL"] == 10.0
    assert payload["metadata"]["intended_fill_printing_mode"] == "droplet"
    assert result["original_printing_mode"] == "droplet"
    assert result["applied_printing_mode"] == "stream"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)
    assert reloaded.metadata["fill_droplet_volume_nL"] == 30.0
    assert reloaded.metadata["fill_printing_mode"] == "stream"
    assert reloaded.metadata["intended_fill_droplet_volume_nL"] == 10.0
    assert reloaded.metadata["intended_fill_printing_mode"] == "droplet"


def test_reloading_after_calibrated_volume_apply_uses_saved_effective_counts(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    original_target = _first_saved_target(em, "glycerol")
    original_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]

    em.apply_droplet_volume_for_option("glycerol", None, 15.0, write_keys_if_assigned=False)
    calibrated_target = _first_saved_target(em, "glycerol")
    calibrated_stock_concentration = em.plans_per_option[("glycerol", None)]["stocks"][0]["stock_concentration"]
    assert calibrated_target != original_target
    assert calibrated_stock_concentration == original_stock_concentration

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    assert reloaded.factors[0].options[0].droplet_nL == 15.0
    assert reloaded.factors[0].options[0].intended_droplet_nL == 10.0
    assert reloaded.factors[0].options[0].forced_stock_conc == calibrated_stock_concentration
    assert _first_saved_target(reloaded, "glycerol") == calibrated_target


def test_applied_imaging_calibration_records_serialize_through_save_and_load(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"))
    emitted_records = []
    em.applied_imaging_calibration_changed.connect(lambda record: emitted_records.append(dict(record)))

    result = em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 15.0,
            "pw_us": 1450,
            "pressure_psi": 1.35,
            "run_id": "run-2",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:02:00Z",
            "source_row_fingerprint": ("run-2", "pressure_sweep", "2026-03-18T09:02:00Z", 1450, 1.35, 15.0),
        },
    )

    payload = json.loads(Path(em.experiment_file_path).read_text(encoding="utf-8"))
    applied = payload["applied_imaging_calibrations"]
    assert applied["schema_version"] == 1
    record = next(iter(applied["records"].values()))
    assert record["stock_id"] == head.get_stock_id()
    assert record["printer_head_id"] == "head-1"
    assert record["applied_design_volume_nL"] == 15.0
    assert record["measured_volume_nL"] == 15.0
    assert record["pw_us"] == 1450
    assert record["pressure_psi"] == 1.35
    assert result["applied_imaging_calibration_recorded"] is True
    assert len(emitted_records) == 1
    assert emitted_records[0]["stock_id"] == head.get_stock_id()
    assert emitted_records[0]["run_id"] == "run-2"

    reloaded_model = experiment_model_factory()
    reloaded = reloaded_model.experiment_model
    reloaded.load_experiment(em.experiment_file_path, em.experiment_dir_path)

    validation = reloaded.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(),
    )
    assert validation["ok"] is True
    assert validation["record"]["run_id"] == "run-2"


def test_apply_fill_droplet_volume_records_applied_imaging_calibration(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "Water"), printer_head_id="fill-head")

    result = em.apply_fill_droplet_volume(
        12.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 12.0,
            "pw_us": 1500,
            "pressure_psi": 1.10,
            "run_id": "fill-run",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:05:00Z",
            "source_row_fingerprint": ("fill-run", "pressure_sweep", "2026-03-18T09:05:00Z", 1500, 1.10, 12.0),
        },
    )

    record = em.get_applied_imaging_calibration(printer_head=head)
    assert result["applied_imaging_calibration_recorded"] is True
    assert record["is_fill"] is True
    assert record["factor_name"] == "Water"
    assert record["applied_design_volume_nL"] == 12.0
    assert record["printer_head_id"] == "fill-head"


def test_changing_design_volume_after_apply_invalidates_print_readiness(
    experiment_model_factory,
):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_calibrated_volume_design(em)
    head = _printer_head(_stock_id_for_design_row(em, "glycerol"))
    em.apply_droplet_volume_for_option(
        "glycerol",
        None,
        15.0,
        write_keys_if_assigned=False,
        applied_calibration={
            "printer_head": head,
            "measured_volume_nL": 15.0,
            "pw_us": 1450,
            "pressure_psi": 1.35,
            "run_id": "run-2",
            "phase": "pressure_sweep_characterization",
            "timestamp": "2026-03-18T09:02:00Z",
            "source_row_fingerprint": ("run-2", "pressure_sweep", "2026-03-18T09:02:00Z", 1450, 1.35, 15.0),
        },
    )

    em.apply_droplet_volume_for_option("glycerol", None, 14.0, write_keys_if_assigned=False)

    validation = em.validate_applied_imaging_calibration_for_print(
        printer_head=head,
        machine_model=_machine_model_for_calibration(),
    )
    assert validation["ok"] is False
    assert "stale" in validation["message"]
