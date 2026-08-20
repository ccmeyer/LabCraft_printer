"""Versioned ownership policy for legacy files not canonicalized by migration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath


OWNERSHIP_SCHEMA_NAME = "labcraft.machine_data_ownership_rules"
OWNERSHIP_SCHEMA_VERSION = 1
DEFAULT_OWNERSHIP_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "Presets"
    / "machine_data_ownership_rules.json"
)


class OwnershipPolicyError(ValueError):
    """Raised when the checked-in policy is malformed or ambiguous."""


class OwnershipClassification(str, Enum):
    CANONICAL = "canonical"
    ARCHIVE_ONLY = "archive_only"
    PROHIBITED = "prohibited"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class OwnershipRule:
    rule_id: str
    match_kind: str
    pattern: str
    classification: OwnershipClassification
    reason: str
    canonical_destination: str | None = None


@dataclass(frozen=True)
class OwnershipDecision:
    relative_path: str
    classification: OwnershipClassification
    rule_id: str | None
    reason: str
    canonical_destination: str | None = None

    @property
    def activation_allowed(self) -> bool:
        return self.classification in {
            OwnershipClassification.CANONICAL,
            OwnershipClassification.ARCHIVE_ONLY,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "classification": self.classification.value,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "canonical_destination": self.canonical_destination,
        }


def normalize_legacy_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OwnershipPolicyError("Ownership paths must be nonempty text.")
    text = value.replace("\\", "/").strip()
    pure = PurePosixPath(text)
    if (
        pure.as_posix() == "."
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise OwnershipPolicyError(f"Unsafe ownership path: {value!r}")
    return pure.as_posix()


@dataclass(frozen=True)
class MachineDataOwnershipPolicy:
    rules: tuple[OwnershipRule, ...]
    schema_version: int = OWNERSHIP_SCHEMA_VERSION

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_OWNERSHIP_CATALOG_PATH,
    ) -> "MachineDataOwnershipPolicy":
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OwnershipPolicyError(f"Cannot load ownership catalog {source}: {exc}") from exc
        if not isinstance(payload, dict):
            raise OwnershipPolicyError("Ownership catalog must be an object.")
        if payload.get("schema_name") != OWNERSHIP_SCHEMA_NAME:
            raise OwnershipPolicyError("Unknown ownership catalog schema_name.")
        if payload.get("schema_version") != OWNERSHIP_SCHEMA_VERSION:
            raise OwnershipPolicyError("Unknown ownership catalog schema_version.")
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            raise OwnershipPolicyError("Ownership rules must be a list.")

        rules: list[OwnershipRule] = []
        ids: set[str] = set()
        signatures: set[tuple[str, str]] = set()
        for raw in raw_rules:
            if not isinstance(raw, dict):
                raise OwnershipPolicyError("Each ownership rule must be an object.")
            rule_id = raw.get("rule_id")
            match_kind = raw.get("match_kind")
            pattern = raw.get("pattern")
            reason = raw.get("reason")
            destination = raw.get("canonical_destination")
            if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in ids:
                raise OwnershipPolicyError("Ownership rule IDs must be unique nonempty text.")
            if match_kind not in {"exact", "prefix"}:
                raise OwnershipPolicyError(f"Unsupported match_kind for {rule_id}.")
            if not isinstance(pattern, str):
                raise OwnershipPolicyError(f"Missing pattern for {rule_id}.")
            normalized = normalize_legacy_relative_path(pattern.rstrip("/"))
            if match_kind == "prefix":
                normalized += "/"
            if not isinstance(reason, str) or not reason.strip():
                raise OwnershipPolicyError(f"Missing reason for {rule_id}.")
            try:
                classification = OwnershipClassification(raw.get("classification"))
            except ValueError as exc:
                raise OwnershipPolicyError(f"Invalid classification for {rule_id}.") from exc
            if classification is OwnershipClassification.UNCLASSIFIED:
                raise OwnershipPolicyError("Catalog rules cannot declare unclassified paths.")
            if classification is OwnershipClassification.CANONICAL:
                if not isinstance(destination, str):
                    raise OwnershipPolicyError(
                        f"Canonical rule {rule_id} requires canonical_destination."
                    )
                destination = normalize_legacy_relative_path(destination)
            elif destination is not None:
                raise OwnershipPolicyError(
                    f"Noncanonical rule {rule_id} cannot set canonical_destination."
                )
            signature = (match_kind, normalized.casefold())
            if signature in signatures:
                raise OwnershipPolicyError("Ownership rules cannot duplicate a match.")
            ids.add(rule_id)
            signatures.add(signature)
            rules.append(
                OwnershipRule(
                    rule_id=rule_id,
                    match_kind=match_kind,
                    pattern=normalized,
                    classification=classification,
                    reason=reason.strip(),
                    canonical_destination=destination,
                )
            )

        # Reject rule pairs that can both match one path. This keeps policy
        # review deterministic and prevents rule-order authority.
        for index, first in enumerate(rules):
            for second in rules[index + 1 :]:
                first_base = first.pattern.rstrip("/").casefold()
                second_base = second.pattern.rstrip("/").casefold()
                if first_base == second_base or (
                    first.match_kind == "prefix"
                    and (second_base + "/").startswith(first_base + "/")
                ) or (
                    second.match_kind == "prefix"
                    and (first_base + "/").startswith(second_base + "/")
                ):
                    raise OwnershipPolicyError(
                        f"Ownership rules overlap: {first.rule_id}, {second.rule_id}."
                    )
        return cls(tuple(rules))

    def classify(self, relative_path: str) -> OwnershipDecision:
        normalized = normalize_legacy_relative_path(relative_path)
        folded = normalized.casefold()
        matches = []
        for rule in self.rules:
            pattern = rule.pattern.casefold()
            if rule.match_kind == "exact" and folded == pattern:
                matches.append(rule)
            elif rule.match_kind == "prefix" and folded.startswith(pattern):
                matches.append(rule)
        if len(matches) > 1:
            raise OwnershipPolicyError(f"Ambiguous ownership path: {normalized}")
        if not matches:
            return OwnershipDecision(
                normalized,
                OwnershipClassification.UNCLASSIFIED,
                None,
                "No reviewed ownership rule matches this legacy path.",
            )
        rule = matches[0]
        return OwnershipDecision(
            normalized,
            rule.classification,
            rule.rule_id,
            rule.reason,
            rule.canonical_destination,
        )

    def classify_all(self, paths: tuple[str, ...]) -> tuple[OwnershipDecision, ...]:
        decisions = tuple(self.classify(path) for path in paths)
        folded = [item.relative_path.casefold() for item in decisions]
        if len(folded) != len(set(folded)):
            raise OwnershipPolicyError("Unclassified source inventory has duplicates.")
        return decisions


__all__ = [
    "DEFAULT_OWNERSHIP_CATALOG_PATH",
    "MachineDataOwnershipPolicy",
    "OWNERSHIP_SCHEMA_NAME",
    "OWNERSHIP_SCHEMA_VERSION",
    "OwnershipClassification",
    "OwnershipDecision",
    "OwnershipPolicyError",
    "OwnershipRule",
    "normalize_legacy_relative_path",
]
