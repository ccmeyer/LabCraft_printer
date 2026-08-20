"""Read-only presentation helpers for configuration transaction history."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from MachineDataTransactions import parse_configuration_event, read_governed_documents


@dataclass(frozen=True)
class ConfigurationHistoryRow:
    sequence: int
    event_id: str
    transaction_id: str
    created_at_utc: str
    operator: str
    os_account: str
    workflow: str
    event_type: str
    outcome: str
    reason: str
    summary: str
    event_path: str
    payload: Mapping[str, object]


def _change_summary(changes) -> str:
    labels = []
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        target = change.get("target_key")
        if isinstance(target, str) and target:
            labels.append(target)
        elif isinstance(change.get("affected_files"), list):
            labels.extend(str(item) for item in change["affected_files"])
        elif change.get("stage"):
            labels.append(str(change["stage"]))
    unique = list(dict.fromkeys(labels))
    return ", ".join(unique) if unique else "No governed values changed"


class ConfigurationHistoryReader:
    def __init__(self, transaction_service):
        if transaction_service is None:
            raise ValueError("Configuration history requires a transaction service.")
        self.service = transaction_service

    def read_rows(self) -> list[ConfigurationHistoryRow]:
        state = self.service.refresh(allow_pending=False)
        rows = []
        for sequence in range(1, state.sequence + 1):
            matches = sorted(
                self.service.paths.configuration_events_root.glob(
                    f"{sequence:020d}-*.json"
                )
            )
            if len(matches) != 1:
                raise ValueError(f"History sequence {sequence} has an invalid inventory.")
            path = matches[0]
            payload = parse_configuration_event(
                json.loads(path.read_text(encoding="utf-8"))
            )
            actor = payload["actor"]
            rows.append(
                ConfigurationHistoryRow(
                    sequence=sequence,
                    event_id=payload["event_id"],
                    transaction_id=payload["transaction_id"],
                    created_at_utc=payload["created_at_utc"],
                    operator=actor["operator"],
                    os_account=actor["os_account"],
                    workflow=payload["workflow"],
                    event_type=payload["event_type"],
                    outcome=payload["outcome"],
                    reason=payload["reason"],
                    summary=_change_summary(payload["changes"]),
                    event_path=path.relative_to(
                        self.service.paths.machine_root
                    ).as_posix(),
                    payload=copy.deepcopy(payload),
                )
            )
        return rows

    def current_target_values(self) -> dict[str, object]:
        from MachineDataVerification import build_target_snapshot_from_documents

        documents = read_governed_documents(self.service.paths)
        snapshot = build_target_snapshot_from_documents(
            documents["Locations.json"],
            documents["Plates.json"],
            documents["Settings.json"],
        )
        return {key: copy.deepcopy(value[2]) for key, value in snapshot.items()}

    def build_markdown(self) -> str:
        state = self.service.refresh(allow_pending=False)
        rows = self.read_rows()
        lines = [
            "# LabCraft Configuration History",
            "",
            f"Machine: {self.service.identity.machine_id}",
            f"Machine UUID: {self.service.identity.machine_uuid}",
            f"Activation ID: {self.service.active.activation_id}",
            f"Integrity: verified through event {state.sequence}",
            "",
        ]
        if not rows:
            lines.append("No post-activation configuration events.")
            lines.append("")
            return "\n".join(lines)
        for row in rows:
            lines.extend(
                [
                    f"## {row.sequence}. {row.event_type} — {row.outcome}",
                    "",
                    f"- Time: {row.created_at_utc}",
                    f"- Operator: {row.operator}",
                    f"- OS account: {row.os_account}",
                    f"- Workflow: {row.workflow}",
                    f"- Reason: {row.reason}",
                    f"- Summary: {row.summary}",
                    f"- Transaction ID: {row.transaction_id}",
                    f"- Event ID: {row.event_id}",
                    "",
                    "```json",
                    json.dumps(row.payload, indent=2, sort_keys=True, ensure_ascii=False),
                    "```",
                    "",
                ]
            )
        return "\n".join(lines)

    def export_markdown(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(self.build_markdown(), encoding="utf-8")
        return target

    def export_json(self, path: str | Path) -> Path:
        target = Path(path)
        payload = {
            "machine_id": self.service.identity.machine_id,
            "machine_uuid": self.service.identity.machine_uuid,
            "activation_id": self.service.active.activation_id,
            "events": [copy.deepcopy(dict(row.payload)) for row in self.read_rows()],
        }
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target


__all__ = ["ConfigurationHistoryReader", "ConfigurationHistoryRow"]
