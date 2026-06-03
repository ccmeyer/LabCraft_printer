import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from Model import AdditionalConditionSpec, CURRENT_PROFILE, ExperimentModel, Model


def _make_model():
    return ExperimentModel(prof=CURRENT_PROFILE)


def _target_map(condition):
    return dict(condition.targets)


def _configure_generation_design(em, *, replicates=2):
    em.factors = []
    em.add_additive(
        "Signal",
        [0.0, 1.0],
        "mM",
        10.0,
        forced_stock_conc=50.0,
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=replicates,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )


def _configure_auto_signal_design(em, *, targets=(0.0, 1.0), target_volume=500.0, final_volume=500.0):
    em.factors = []
    em.add_additive("Signal", list(targets), "mM", 10.0)
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=float(target_volume),
        final_reaction_volume_nL=float(final_volume),
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )


def test_new_experiment_model_starts_without_additional_conditions():
    em = _make_model()

    assert em.has_additional_conditions() is False
    assert em.get_additional_conditions() == []
    assert em.to_dict()["additional_conditions"] == {
        "schema_version": 1,
        "conditions": [],
    }


def test_set_additional_conditions_normalizes_values_and_clears_derived_state():
    em = _make_model()
    em.plans_per_option[("GFP", None)] = {"placeholder": True}
    em._unreachable_preview_map[("GFP", None)] = [1.0]
    em._target_preview_map[("GFP", None)] = [{"requested_final": 1.0}]
    em._stock_rows_cache = [{"factor_name": "GFP"}]
    em._fill_row_cache = {"factor_name": "Water"}
    em._reactions_df = pd.DataFrame([{"fill_drops": 1}])
    em._last_worst_nonfill_volume_nL = 123.0
    em.unsaved_changes = False

    em.set_additional_conditions(
        [
            {
                "label": "  No signal control  ",
                "replicates": "3",
                "targets": [
                    {"factor": " GFP ", "option": None, "target": 0.0},
                    {"factor": " PURE mix ", "option": "  high ", "target": "1.25"},
                    {"factor": "", "option": None, "target": 9.0},
                    {"factor": " Bad numeric ", "target": float("nan")},
                ],
            },
            AdditionalConditionSpec(
                label=" ",
                replicates=0,
                targets={
                    ("Buffer", " "): "not numeric",
                    ("Salt", " option A "): 2.5,
                    ("", None): 7.0,
                },
            ),
        ]
    )

    conditions = em.get_additional_conditions()
    assert [condition.label for condition in conditions] == ["No signal control", "Condition 2"]
    assert [condition.replicates for condition in conditions] == [3, 1]
    assert _target_map(conditions[0]) == {
        ("GFP", None): 0.0,
        ("PURE mix", "high"): 1.25,
        ("Bad numeric", None): 0.0,
    }
    assert _target_map(conditions[1]) == {
        ("Buffer", None): 0.0,
        ("Salt", "option A"): 2.5,
    }

    assert em.plans_per_option == {}
    assert em._unreachable_preview_map == {}
    assert em._target_preview_map == {}
    assert em._stock_rows_cache == []
    assert em._fill_row_cache is None
    assert em._reactions_df.empty
    assert em._last_worst_nonfill_volume_nL is None
    assert em.unsaved_changes is True


def test_get_additional_conditions_returns_independent_copies():
    em = _make_model()
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Control",
                replicates=2,
                targets={("GFP", None): 0.0},
            )
        ]
    )

    returned = em.get_additional_conditions()
    returned[0].label = "Mutated"
    returned[0].replicates = 99
    returned[0].targets[("GFP", None)] = 42.0
    returned[0].targets[("New", None)] = 1.0

    fresh = em.get_additional_conditions()
    assert fresh[0].label == "Control"
    assert fresh[0].replicates == 2
    assert fresh[0].targets == {("GFP", None): 0.0}


def test_additional_conditions_round_trip_through_to_dict_and_from_dict():
    em = _make_model()
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="No signal control",
                replicates=3,
                targets={
                    ("GFP", None): 0.0,
                    ("PURE mix", None): 1.0,
                },
            )
        ]
    )

    payload = em.to_dict()
    additional = payload["additional_conditions"]
    assert additional["schema_version"] == 1
    assert additional["conditions"][0]["label"] == "No signal control"
    assert additional["conditions"][0]["replicates"] == 3
    serialized_targets = {
        (target["factor"], target["option"]): target["target"]
        for target in additional["conditions"][0]["targets"]
    }
    assert serialized_targets == {
        ("GFP", None): 0.0,
        ("PURE mix", None): 1.0,
    }

    restored = _make_model()
    restored.from_dict(payload)

    conditions = restored.get_additional_conditions()
    assert len(conditions) == 1
    assert conditions[0].label == "No signal control"
    assert conditions[0].replicates == 3
    assert conditions[0].targets == {
        ("GFP", None): 0.0,
        ("PURE mix", None): 1.0,
    }


def test_from_dict_handles_legacy_payload_without_additional_conditions():
    em = _make_model()

    em.from_dict(
        {
            "metadata": {
                "name": "legacy",
                "fill_droplet_volume_nL": 10.0,
            },
            "factors": [],
        }
    )

    assert em.has_additional_conditions() is False
    assert em.get_additional_conditions() == []


def test_from_dict_normalizes_malformed_additional_condition_entries():
    em = _make_model()

    em.from_dict(
        {
            "metadata": {
                "name": "partial",
                "fill_droplet_volume_nL": 10.0,
            },
            "factors": [],
            "additional_conditions": {
                "schema_version": 1,
                "conditions": [
                    {
                        "label": " ",
                        "replicates": "bad",
                        "targets": [
                            {"factor": " A ", "target": "bad"},
                            {"factor": None, "target": 5.0},
                            {"factor": " B ", "option": " opt ", "target": float("inf")},
                        ],
                    },
                    "not a condition",
                    {
                        "label": "Dict target",
                        "replicates": 2,
                        "targets": {"C": 1.5},
                    },
                ],
            },
        }
    )

    conditions = em.get_additional_conditions()
    assert [condition.label for condition in conditions] == ["Condition 1", "Dict target"]
    assert [condition.replicates for condition in conditions] == [1, 2]
    assert conditions[0].targets == {
        ("A", None): 0.0,
        ("B", "opt"): 0.0,
    }
    assert conditions[1].targets == {("C", None): 1.5}


def test_clear_and_reset_additional_conditions():
    em = _make_model()
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Control",
                replicates=1,
                targets={("GFP", None): 0.0},
            )
        ]
    )

    em.clear_additional_conditions()

    assert em.has_additional_conditions() is False
    assert em.get_additional_conditions() == []
    assert em.unsaved_changes is True

    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Control",
                replicates=1,
                targets={("GFP", None): 0.0},
            )
        ]
    )

    em.reset_experiment_model()

    assert em.has_additional_conditions() is False
    assert em.get_additional_conditions() == []
    assert em.unsaved_changes is False


def test_base_design_generation_count_is_unchanged_without_additional_conditions():
    em = _make_model()
    _configure_generation_design(em, replicates=2)

    assert em.get_number_of_reactions() == 4
    assert em.optimize_stock_solutions(allow_two=False)["best"]

    em.generate_experiment()

    df = em.get_reactions_dataframe()
    assert em.get_number_of_reactions() == 4
    assert len(df) == 4
    assert df["design_source"].tolist() == ["base", "base", "base", "base"]
    assert df["additional_condition_label"].tolist() == ["", "", "", ""]


def test_additional_conditions_append_to_generated_run_order():
    em = _make_model()
    _configure_generation_design(em, replicates=2)
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="No signal control",
                replicates=3,
                targets={("Signal", None): 0.0},
            ),
            AdditionalConditionSpec(
                label="Known response",
                replicates=1,
                targets={("Signal", None): 1.0},
            ),
        ]
    )

    assert em.get_number_of_reactions() == 8
    assert em.optimize_stock_solutions(allow_two=False)["best"]

    em.generate_experiment()

    df = em.get_reactions_dataframe()
    assert len(df) == 8
    assert em.get_number_of_reactions() == 8
    assert df["global_index"].tolist() == list(range(8))
    assert df["design_source"].tolist() == [
        "base",
        "base",
        "base",
        "base",
        "additional_condition",
        "additional_condition",
        "additional_condition",
        "additional_condition",
    ]
    assert df["additional_condition_label"].tolist() == [
        "",
        "",
        "",
        "",
        "No signal control",
        "No signal control",
        "No signal control",
        "Known response",
    ]
    assert df["replicate"].tolist() == [1, 1, 2, 2, 1, 2, 3, 1]
    assert df["reaction_index"].tolist() == [0, 1, 0, 1, 0, 0, 0, 1]
    assert df["nonfill_volume_nL"].tolist() == pytest.approx(
        [0.0, 10.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0]
    )
    assert df["fill_drops"].tolist() == [50, 49, 50, 49, 50, 50, 50, 49]

    parts = list(em.iter_reaction_stock_droplets())
    assert len(parts) == len(df)
    assert parts[0] == []
    assert parts[1] == [("Signal", 50.0, "mM", 1)]
    assert parts[4] == []
    assert parts[7] == [("Signal", 50.0, "mM", 1)]


def test_zero_only_choice_option_is_unique_condition_only_in_base_generation():
    em = _make_model()
    em.factors = []
    em.add_additive("Activator", [0.0, 1.0], "mM", 10.0, forced_stock_conc=50.0)
    em.add_choice_group("DNA")
    em.add_choice_option("DNA", "Main DNA", [0.0, 5.0], "nM", 10.0, forced_stock_conc=50.0)
    em.add_choice_option("DNA", "Negative DNA", [0.0], "nM", 10.0, forced_stock_conc=50.0)
    em.set_metadata(
        randomize_assignments=False,
        replicates=2,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Negative DNA control",
                replicates=2,
                targets={
                    ("Activator", None): 0.0,
                    ("DNA", "Main DNA"): 0.0,
                    ("DNA", "Negative DNA"): 5.0,
                },
            )
        ]
    )

    assert em.get_number_of_reactions() == 10
    assert em.optimize_stock_solutions(allow_two=False)["best"]
    assert 5.0 in em.plans_per_option[("DNA", "Negative DNA")]["stocks"][0]["droplets_per_target"]

    em.generate_experiment()

    df = em.get_reactions_dataframe()
    assert len(df) == 10
    assert df["design_source"].tolist() == ["base"] * 8 + ["additional_condition"] * 2
    assert df["replicate"].tolist() == [1, 1, 1, 1, 2, 2, 2, 2, 1, 2]
    assert df["reaction_index"].tolist() == [0, 1, 2, 3, 0, 1, 2, 3, 0, 0]

    preview = em.get_reaction_preview_dataframe()
    base_rows = preview[preview["design_source"] == "base"]
    control_rows = preview[preview["design_source"] == "additional_condition"]
    assert "DNA/Negative DNA (nM)" in preview.columns
    assert base_rows["DNA/Main DNA (nM)"].tolist() == pytest.approx([0.0, 5.0, 0.0, 5.0] * 2)
    assert base_rows["DNA/Negative DNA (nM)"].tolist() == pytest.approx([0.0] * 8)
    assert control_rows["additional_condition_label"].tolist() == ["Negative DNA control", "Negative DNA control"]
    assert control_rows["DNA/Main DNA (nM)"].tolist() == pytest.approx([0.0, 0.0])
    assert control_rows["DNA/Negative DNA (nM)"].tolist() == pytest.approx([5.0, 5.0])


def test_all_zero_choice_group_contributes_one_empty_base_reaction_per_replicate():
    em = _make_model()
    em.factors = []
    em.add_choice_group("DNA")
    em.add_choice_option("DNA", "Blank A", [0.0], "nM", 10.0, forced_stock_conc=50.0)
    em.add_choice_option("DNA", "Blank B", [0.0], "nM", 10.0, forced_stock_conc=50.0)
    em.set_metadata(
        randomize_assignments=False,
        replicates=3,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )

    assert em.get_number_of_reactions() == 3

    em.generate_experiment()

    df = em.get_reactions_dataframe()
    preview = em.get_reaction_preview_dataframe()
    assert len(df) == 3
    assert df["design_source"].tolist() == ["base", "base", "base"]
    assert df["reaction_index"].tolist() == [0, 0, 0]
    assert preview["DNA/Blank A (nM)"].tolist() == pytest.approx([0.0, 0.0, 0.0])
    assert preview["DNA/Blank B (nM)"].tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_zero_only_choice_option_is_filtered_in_subset_design_path(monkeypatch):
    em = _make_model()
    em.factors = []
    em.add_choice_group("DNA")
    em.add_choice_option("DNA", "Main DNA", [0.0, 5.0], "nM", 10.0)
    em.add_choice_option("DNA", "Negative DNA", [0.0], "nM", 10.0)
    em.set_metadata(use_subset_design=True, reduction_factor=2, replicates=1)
    captured_level_counts = []

    def fake_gsd(level_counts, reduction):
        captured_level_counts.append(list(level_counts))
        assert reduction == 2
        return [[0], [1]]

    monkeypatch.setitem(sys.modules, "pyDOE3", SimpleNamespace(gsd=fake_gsd))

    reactions = em._enumerate_reactions()

    assert captured_level_counts == [[2]]
    assert reactions == [
        {("DNA", "Main DNA"): 0.0},
        {("DNA", "Main DNA"): 5.0},
    ]


def test_uploaded_design_reactions_do_not_apply_zero_only_choice_filter():
    em = _make_model()
    em.set_metadata(
        randomize_assignments=False,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_uploaded_design_from_dataframe(
        pd.DataFrame(
            {
                "Main DNA (nM)": [0.0, 5.0],
                "Negative DNA (nM)": [0.0, 0.0],
            }
        ),
        droplet_nL_default=10.0,
        starting_conc_default=0.0,
    )

    preview = em.get_reaction_preview_dataframe()

    assert em.get_number_of_reactions() == 2
    assert preview["Main DNA (nM)"].tolist() == pytest.approx([0.0, 5.0])
    assert preview["Negative DNA (nM)"].tolist() == pytest.approx([0.0, 0.0])


def test_runtime_handoff_includes_additional_condition_runs(experiment_model_factory):
    model = experiment_model_factory()
    em = model.experiment_model
    _configure_generation_design(em, replicates=1)
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Known response",
                replicates=2,
                targets={("Signal", None): 1.0},
            )
        ]
    )
    assert em.optimize_stock_solutions(allow_two=False)["best"]
    em.generate_experiment()

    expected_n = em.get_number_of_reactions()

    Model.load_experiment_from_model(model, load_progress=False)

    assigned = [
        well.get_assigned_reaction()
        for well in model.well_plate.get_all_wells()
        if well.get_assigned_reaction() is not None
    ]
    assert len(assigned) == expected_n
    assert len(model.reaction_collection.get_all_reactions()) == expected_n


def test_optimizer_includes_additional_only_targets_in_stock_lookup_and_generation():
    em = _make_model()
    _configure_auto_signal_design(em, targets=(0.0, 1.0))
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Midpoint response",
                replicates=1,
                targets={("Signal", None): 0.5},
            )
        ]
    )

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert result["best"]
    stock = em.plans_per_option[("Signal", None)]["stocks"][0]
    assert 0.5 in stock["droplets_per_target"]

    em.generate_experiment()

    df = em.get_reactions_dataframe()
    assert df.iloc[-1]["design_source"] == "additional_condition"
    assert df.iloc[-1]["additional_condition_label"] == "Midpoint response"
    assert df.iloc[-1]["nonfill_volume_nL"] > 0.0
    assert list(em.iter_reaction_stock_droplets())[-1]


def test_forced_stock_preview_includes_additional_only_targets():
    em = _make_model()
    em.factors = []
    em.add_additive("Signal", [0.0, 1.0], "mM", 10.0, forced_stock_conc=25.0)
    em.set_metadata(
        randomize_assignments=False,
        replicates=1,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Half signal",
                replicates=1,
                targets={("Signal", None): 0.5},
            )
        ]
    )

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert result["best"]
    preview = em.get_target_preview_map()[("Signal", None)]
    by_target = {row["requested_final"]: row for row in preview}
    assert sorted(by_target.keys()) == [0.0, 0.5, 1.0]
    assert by_target[0.5]["reachable"] is True
    assert by_target[0.5]["droplets"] == 1
    assert by_target[0.5]["achieved_final"] == pytest.approx(0.5)
    assert 0.5 in em.plans_per_option[("Signal", None)]["stocks"][0]["droplets_per_target"]


def test_additional_only_targets_do_not_mutate_serialized_factor_targets():
    em = _make_model()
    _configure_auto_signal_design(em, targets=(0.0, 1.0))
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Midpoint response",
                replicates=1,
                targets={("Signal", None): 0.5},
            )
        ]
    )

    assert em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)["best"]

    assert em.factors[0].options[0].targets == [0.0, 1.0]
    assert em.to_dict()["factors"][0]["options"][0]["targets"] == [0.0, 1.0]


def test_unknown_nonzero_additional_target_fails_but_unknown_zero_target_is_allowed():
    em = _make_model()
    _configure_auto_signal_design(em, targets=(0.0, 1.0))
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Bad target",
                replicates=1,
                targets={("Missing", None): 1.0},
            )
        ]
    )

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = result["issues_by_key"][("__additional_conditions__", None)][0]
    assert issue["code"] == "unknown_additional_condition_target"
    assert issue["targets"][0]["label"] == "Missing"

    zero_target = _make_model()
    _configure_auto_signal_design(zero_target, targets=(0.0, 1.0))
    zero_target.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Zero missing target",
                replicates=1,
                targets={("Missing", None): 0.0},
            )
        ]
    )

    assert zero_target.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=False,
    )["best"]


def test_additional_condition_row_volume_can_drive_budget_diagnostic():
    em = _make_model()
    em.factors = []
    em.add_choice_group("Reporter")
    em.add_choice_option(
        "Reporter",
        "A",
        [0.0, 5.0],
        "mM",
        10.0,
        forced_stock_conc=10.0,
        max_stock_conc=20.0,
    )
    em.add_choice_option(
        "Reporter",
        "B",
        [0.0, 5.0],
        "mM",
        10.0,
        forced_stock_conc=10.0,
        max_stock_conc=20.0,
    )
    em.set_metadata(
        randomize_assignments=False,
        replicates=1,
        target_reaction_volume_nL=550.0,
        final_reaction_volume_nL=1000.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Both reporters",
                replicates=1,
                targets={
                    ("Reporter", "A"): 5.0,
                    ("Reporter", "B"): 5.0,
                },
            )
        ]
    )

    result = em.optimize_stock_solutions(quantum=0.1, max_refine=20, two_max_refine=20, allow_two=False)

    assert not result.get("best")
    issue = result["issues_by_key"][("__additional_conditions__", None)][0]
    assert issue["code"] == "selected_plan_volume_budget_exceeded"
    assert issue["field"] == "volume_budget"
    assert issue["row_label"] == "additional condition 'Both reporters'"
    assert issue["required_volume_nL"] == pytest.approx(1000.0)
    assert issue["allowed_volume_nL"] == pytest.approx(550.0)
    assert {row["label"] for row in issue["contributors"]} == {"Reporter/A", "Reporter/B"}
