import json
from pathlib import Path

import pandas as pd
import pytest

from Model import Model


def _configure_design(em):
    em.factors = []
    em.add_additive("AddA", [0.5, 1.0], "mM", 10.0, starting_conc=0.2)
    em.add_choice_group("Choice")
    em.add_choice_option("Choice", "Opt1", [0.0, 0.5], "mM", 10.0, starting_conc=0.1)
    em.add_choice_option("Choice", "Opt2", [0.0, 0.5], "mM", 10.0, starting_conc=0.05)
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


def _stock_lookup_by_sid(em):
    out = {}
    for row in em.get_stock_table_rows(include_fill=True):
        name = row.get("option_name") or row.get("factor_name") or ""
        sid = f"{name}_{float(row.get('stock_concentration', 0.0)):.2f}_{row.get('units', '')}"
        out[sid] = row
    return out


def _well_with_reaction(well_plate):
    for well in well_plate.get_all_wells():
        if well.get_assigned_reaction() is not None:
            return well
    raise AssertionError("No assigned well found")


def test_progress_json_matches_runtime_assigned_reactions(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    progress_path = Path(em.progress_file_path)
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    data.pop("__plate__", None)

    runtime_wells = [w for w in model.well_plate.get_all_wells() if w.get_assigned_reaction() is not None]
    assert set(data.keys()) == {w.well_id for w in runtime_wells}
    for w in runtime_wells:
        rxn = w.get_assigned_reaction()
        entry = data[w.well_id]
        assert entry["reaction_id"] == rxn.unique_id
        for sid, reagent in rxn.get_all_reagents().items():
            assert entry["reagents"][sid]["target_droplets"] == reagent.get_target_droplets()


def test_key_csv_rows_and_counts_match_progress_data(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    progress.pop("__plate__", None)
    key_df = pd.read_csv(em.key_file_path).set_index("Well ID")
    sid_lookup = _stock_lookup_by_sid(em)

    assert set(key_df.index.astype(str)) == set(progress.keys())
    for well_id, entry in progress.items():
        row = key_df.loc[well_id].fillna(0)
        expected_cols = {}
        for sid, reagent_data in entry["reagents"].items():
            dv = float(sid_lookup[sid]["droplet_volume_nL"])
            col = f"{sid}_{dv:.1f}nL"
            expected_cols[col] = int(reagent_data["target_droplets"])
            assert int(row[col]) == int(reagent_data["target_droplets"])

        for col, value in row.items():
            if col not in expected_cols:
                assert int(value) == 0


def test_concentration_key_matches_starting_plus_added_contributions(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    progress.pop("__plate__", None)
    conc_df = pd.read_csv(em.concentration_key_file_path).set_index("Well ID").fillna(0.0)
    sid_lookup = _stock_lookup_by_sid(em)
    v_final = float(em.metadata["final_reaction_volume_nL"])
    start_lookup = {"AddA_mM": 0.2, "Opt1_mM": 0.1, "Opt2_mM": 0.05}

    well_id = None
    for wid in sorted(progress.keys()):
        reagents = progress[wid]["reagents"]
        if any(sid.startswith("Opt1_") or sid.startswith("Opt2_") for sid in reagents):
            well_id = wid
            break
    assert well_id is not None
    row = conc_df.loc[well_id]
    expected_add_a = start_lookup["AddA_mM"]
    present_choice = set()

    for sid, details in progress[well_id]["reagents"].items():
        reagent_name, _conc_str, units = sid.rsplit("_", 2)
        stock_conc = float(sid_lookup[sid]["stock_concentration"])
        drops = int(details["target_droplets"])
        dv = float(sid_lookup[sid]["droplet_volume_nL"])
        contrib = stock_conc * (drops * dv) / v_final
        col = f"{reagent_name}_{units}"
        if col == "AddA_mM":
            expected_add_a += contrib
        if col in ("Opt1_mM", "Opt2_mM"):
            present_choice.add(col)

    assert row["AddA_mM"] == pytest.approx(expected_add_a, abs=1e-4)
    assert len(present_choice) == 1
    for col in ("Opt1_mM", "Opt2_mM"):
        if col in present_choice:
            assert row[col] >= start_lookup[col]


def test_write_keys_now_rebuilds_progress_before_writing_csvs(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_design(em)
    assert em.optimize_stock_solutions()["best"]
    em.generate_experiment()
    Model.load_experiment_from_model(model, load_progress=False)

    well = _well_with_reaction(model.well_plate)
    rxn = well.get_assigned_reaction()
    sid, reagent = next(iter(rxn.get_all_reagents().items()))
    new_target = reagent.get_target_droplets() + 3
    reagent.set_target_droplets(new_target, preserve_progress=False)
    em.progress_data = {}

    em.write_keys_now()

    progress = json.loads(Path(em.progress_file_path).read_text(encoding="utf-8"))
    progress.pop("__plate__", None)
    assert progress[well.well_id]["reagents"][sid]["target_droplets"] == new_target

    key_df = pd.read_csv(em.key_file_path).set_index("Well ID")
    sid_lookup = _stock_lookup_by_sid(em)
    dv = float(sid_lookup[sid]["droplet_volume_nL"])
    col = f"{sid}_{dv:.1f}nL"
    assert int(key_df.loc[well.well_id, col]) == new_target
