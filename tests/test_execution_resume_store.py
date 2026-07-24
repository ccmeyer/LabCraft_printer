from dataclasses import replace
import json

import pytest

from ExecutionResumeStore import (
    ExecutionResumeDocument,
    add_pending_intent,
    attach_command_sequence,
    compact_completed_intents,
    complete_intent,
    discard_pending_intents,
    load_execution_resume,
    new_resume_document,
    save_execution_resume,
    synchronize_checkpoint,
)


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
SESSION_ID = "9cfe342a-2c86-4e50-906f-98e70f84de05"
NOW = "2026-07-17T12:00:00Z"


def _progress(added=0):
    return {
        "A1": {
            "reaction_id": "R1",
            "reagents": {
                "PURE MM_1.11_x": {
                    "target_droplets": 16,
                    "added_droplets": added,
                }
            },
            "completed": added >= 16,
        }
    }


def test_resume_intent_round_trip_retires_a_clean_command_boundary(tmp_path):
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=2,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    document = attach_command_sequence(document, intent.intent_id, 42, timestamp_utc=NOW)
    document = complete_intent(
        document,
        intent.intent_id,
        progress_wells=_progress(16),
        timestamp_utc=NOW,
    )
    path = tmp_path / "execution_resume.json"
    save_execution_resume(path, document)

    loaded = load_execution_resume(path)
    assert loaded == document
    assert loaded.state == "clean"
    assert loaded.intents == ()


def test_completion_retires_only_the_proven_intent():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=2,
        progress_wells={
            **_progress(),
            "A2": {
                "reaction_id": "R2",
                "reagents": {
                    "PURE MM_1.11_x": {
                        "target_droplets": 16,
                        "added_droplets": 0,
                    }
                },
                "completed": False,
            },
        },
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, first = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    document, second = add_pending_intent(
        document,
        well_id="A2",
        reaction_id="R2",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )

    updated = complete_intent(
        document,
        first.intent_id,
        progress_wells={
            **_progress(16),
            "A2": {
                "reaction_id": "R2",
                "reagents": {
                    "PURE MM_1.11_x": {
                        "target_droplets": 16,
                        "added_droplets": 0,
                    }
                },
                "completed": False,
            },
        },
        timestamp_utc=NOW,
    )

    assert updated.state == "printing"
    assert updated.intents == (second,)


def test_legacy_completed_intents_compact_only_when_progress_proves_them():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=2,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    legacy = replace(
        document,
        state="clean",
        active_stock_id=None,
        printer_head_id=None,
        intents=(
            replace(intent, status="completed", completed_at_utc=NOW),
        ),
    )

    compacted = compact_completed_intents(
        legacy,
        progress_wells=_progress(16),
        timestamp_utc=NOW,
    )

    assert compacted.state == "clean"
    assert compacted.intents == ()
    with pytest.raises(ValueError, match="does not prove"):
        compact_completed_intents(
            legacy,
            progress_wells=_progress(),
            timestamp_utc=NOW,
        )


def test_resume_schema_rejects_unknown_fields(tmp_path):
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    ).to_dict()
    document["future_field"] = True
    path = tmp_path / "execution_resume.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown field"):
        load_execution_resume(path)


def test_checkpoint_revision_cannot_change_with_pending_intent():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, _ = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )

    with pytest.raises(ValueError, match="pending intents"):
        synchronize_checkpoint(
            document,
            plan_revision=2,
            progress_wells=_progress(),
            timestamp_utc=NOW,
        )


def test_intent_cannot_complete_before_progress_reflects_command():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )

    with pytest.raises(ValueError, match="does not prove"):
        complete_intent(
            document,
            intent.intent_id,
            progress_wells=_progress(),
            timestamp_utc=NOW,
        )


def test_confirmed_queue_clear_discards_only_selected_pending_intents():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, first = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    other_progress = {
        "A2": {
            "reaction_id": "R2",
            "reagents": {
                "PURE MM_1.11_x": {
                    "target_droplets": 16,
                    "added_droplets": 0,
                }
            },
            "completed": False,
        }
    }
    document, second = add_pending_intent(
        document,
        well_id="A2",
        reaction_id="R2",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )

    updated = discard_pending_intents(
        document,
        [second.intent_id],
        progress_wells={**_progress(), **other_progress},
        timestamp_utc=NOW,
    )

    assert [intent.intent_id for intent in updated.intents] == [first.intent_id]
    assert updated.state == "printing"

    paused = discard_pending_intents(
        updated,
        [first.intent_id],
        progress_wells={**_progress(), **other_progress},
        timestamp_utc=NOW,
    )
    assert paused.intents == ()
    assert paused.state == "paused"
    assert paused.active_stock_id is None
    assert paused.printer_head_id is None


def test_queue_clear_cannot_discard_completed_or_unknown_intent():
    document = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=_progress(),
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    document, intent = add_pending_intent(
        document,
        well_id="A1",
        reaction_id="R1",
        stock_id="PURE MM_1.11_x",
        baseline_added=0,
        commanded_droplets=16,
        printer_head_id="head-1",
        timestamp_utc=NOW,
    )
    completed = complete_intent(
        document,
        intent.intent_id,
        progress_wells=_progress(16),
        timestamp_utc=NOW,
    )

    with pytest.raises(ValueError, match="existing pending"):
        discard_pending_intents(
            completed,
            [intent.intent_id],
            progress_wells=_progress(16),
            timestamp_utc=NOW,
        )
