import pandas as pd
import pytest

from Model import AdditionalConditionSpec, CURRENT_PROFILE, ExperimentModel


def _make_model():
    return ExperimentModel(prof=CURRENT_PROFILE)


def _target_map(condition):
    return dict(condition.targets)


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
