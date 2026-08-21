"""Validate LabCraft's non-actuating firmware SAFE HIL contract.

This module is intentionally dependency-free so the Windows workflow and the
Pi supervisor can run the exact validator from a committed development tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA_NAME = "labcraft.safe_hil_validation"
SCHEMA_VERSION = 1

SAFE_TEST_IDS = frozenset(
    {
        1001, 1002, 1003, 1004, 1005, 1006, 1007,
        1010, 1011, 1012, 1013, 1020, 1021, 1030,
        1040, 1041, 1042, 1043, 1044,
    }
)
GATED_ACTUATION_METRICS = {
    2001: "motion",
    2002: "motion",
    2007: "motion",
    2008: "motion",
    2003: "pressure",
    2201: "pressure",
    2202: "pressure",
    2203: "pressure",
    2004: "valves",
    2005: "pulses",
    2006: "abort",
}
EXPECTED_TEST_IDS = SAFE_TEST_IDS | frozenset(GATED_ACTUATION_METRICS)


class SafeHilValidationError(RuntimeError):
    """Raised when evidence does not prove a plain non-actuating SAFE run."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise SafeHilValidationError(f"{label} must be an integer, not boolean.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SafeHilValidationError(f"{label} must be an integer.") from exc
    return parsed


def _metrics(result: Mapping[str, Any], test_id: int) -> Mapping[str, Any]:
    metrics = result.get("metrics")
    if not isinstance(metrics, Mapping):
        raise SafeHilValidationError(f"SAFE result {test_id} has no metrics object.")
    return metrics


def _require_metric(
    metrics: Mapping[str, Any], test_id: int, name: str, expected: Any
) -> None:
    if name not in metrics:
        raise SafeHilValidationError(
            f"SAFE result {test_id} is missing required metric {name}."
        )
    actual = metrics[name]
    if isinstance(expected, int):
        actual = _integer(actual, f"SAFE result {test_id} metric {name}")
    else:
        actual = str(actual)
    if actual != expected:
        raise SafeHilValidationError(
            f"SAFE result {test_id} metric {name} is {actual!r}, expected {expected!r}."
        )


def validate_safe_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return sealed validation evidence or fail closed.

    A plain SAFE run has a fixed inventory. Extra result IDs are rejected so a
    selector, benchmark, or newly introduced test cannot silently broaden this
    unattended lane.
    """

    if not isinstance(payload, Mapping):
        raise SafeHilValidationError("SAFE report must be a JSON object.")
    if payload.get("profile") != "SAFE":
        raise SafeHilValidationError("HIL report profile is not exactly SAFE.")
    if payload.get("aborted") is not False:
        raise SafeHilValidationError("SAFE HIL report is absent, incomplete, or aborted.")

    summary = payload.get("summary")
    results = payload.get("results")
    if not isinstance(summary, Mapping) or not isinstance(results, list):
        raise SafeHilValidationError("SAFE report summary/results are malformed.")

    by_id: dict[int, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            raise SafeHilValidationError("SAFE result entry is not an object.")
        test_id = _integer(result.get("test_id"), "SAFE result test_id")
        if test_id in by_id:
            raise SafeHilValidationError(f"SAFE report contains duplicate test ID {test_id}.")
        if result.get("pass") is not True:
            raise SafeHilValidationError(f"SAFE result {test_id} did not pass.")
        by_id[test_id] = result

    actual_ids = frozenset(by_id)
    missing = sorted(EXPECTED_TEST_IDS - actual_ids)
    extra = sorted(actual_ids - EXPECTED_TEST_IDS)
    if missing or extra:
        raise SafeHilValidationError(
            f"Plain SAFE inventory differs from contract; missing={missing}, extra={extra}."
        )

    total = _integer(summary.get("total"), "SAFE summary total")
    passed = _integer(summary.get("passed"), "SAFE summary passed")
    failed = _integer(summary.get("failed"), "SAFE summary failed")
    expected_count = len(EXPECTED_TEST_IDS)
    if (total, passed, failed, len(results)) != (
        expected_count, expected_count, 0, expected_count
    ):
        raise SafeHilValidationError(
            "SAFE summary does not prove every expected result passed exactly once."
        )

    for test_id, zero_metric in GATED_ACTUATION_METRICS.items():
        metrics = _metrics(by_id[test_id], test_id)
        _require_metric(metrics, test_id, "profile", "SAFE")
        _require_metric(metrics, test_id, "executed", 0)
        _require_metric(metrics, test_id, "fixture_required", 1)
        _require_metric(metrics, test_id, zero_metric, 0)
        _require_metric(metrics, test_id, "gate", "safe_only")

    flash_metrics = _metrics(by_id[1007], 1007)
    _require_metric(flash_metrics, 1007, "cycles_timeout", 0)
    _require_metric(flash_metrics, 1007, "ft_acc_delta", 0)
    skipped_no_flash_task = _integer(
        flash_metrics.get("skipped_no_flash_task"),
        "SAFE result 1007 metric skipped_no_flash_task",
    )
    if skipped_no_flash_task == 1:
        # The protocol bounds the metrics payload, so the later arm-state fields
        # are not transmitted on this branch. Absence of the task plus zero
        # start/output counters is direct proof that no flash dispatch occurred.
        for metric in (
            "cycles_started",
            "ext_delta",
            "flash_ack_delta",
            "flash_task_wake_delta",
            "flash_task_done_delta",
            "ft_ign_dis_delta",
        ):
            _require_metric(flash_metrics, 1007, metric, 0)
        flash_contract = "no_flash_task_zero_dispatch"
    elif skipped_no_flash_task == 0:
        # If a flash task exists, fail closed unless the report includes the
        # later explicit disarm/fault and timeout fields.
        for metric in (
            "ft_rel_to_delta",
            "ft_ack_to_delta",
            "ft_print_to_delta",
            "flash_session_armed",
            "flash_fault_latched",
            "flash_output_armed",
        ):
            _require_metric(flash_metrics, 1007, metric, 0)
        flash_contract = "present_task_explicitly_disarmed"
    else:
        raise SafeHilValidationError(
            "SAFE result 1007 skipped_no_flash_task must be exactly 0 or 1."
        )

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "profile": "SAFE",
        "run_id": payload.get("run_id"),
        "result_count": expected_count,
        "test_ids": sorted(actual_ids),
        "gated_actuation_test_ids": sorted(GATED_ACTUATION_METRICS),
        "flash_non_actuation_contract": flash_contract,
    }


def load_and_validate_safe_report(path: Path) -> dict[str, Any]:
    path = path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeHilValidationError(f"Cannot read SAFE report {path}: {exc}") from exc
    validation = validate_safe_report(payload)
    validation.update({"report_path": str(path), "report_sha256": _sha256(path)})
    return validation


def validate_safe_source_contract(repo_root: Path) -> dict[str, Any]:
    """Prove this commit still maps plain SAFE to the non-actuating inventory."""

    root = repo_root.resolve()
    paths = {
        "diagnostics": root / "firmware/Core/Src/Diagnostics.cpp",
        "orchestrator": root / "firmware/Core/Src/Orchestrator.cpp",
        "runner": root / "tools/run_selftest.py",
    }
    try:
        texts = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    except OSError as exc:
        raise SafeHilValidationError(f"Cannot inspect SAFE source contract: {exc}") from exc

    descriptor_pattern = re.compile(
        r'\{(\d+)u,\s*"[^"]+",\s*"[^"]+",\s*"(SAFE|FULL)",\s*"([^"]+)"\}'
    )
    descriptors = {
        int(test_id): (profile, gate)
        for test_id, profile, gate in descriptor_pattern.findall(texts["diagnostics"])
    }
    for test_id in SAFE_TEST_IDS:
        if descriptors.get(test_id) not in {
            ("SAFE", "always"),
            ("SAFE", "compile_gate"),
            ("SAFE", "safe_terminal"),
        }:
            raise SafeHilValidationError(
                f"SAFE source descriptor {test_id} is missing or no longer non-actuating."
            )
    for test_id in GATED_ACTUATION_METRICS:
        if descriptors.get(test_id) != ("FULL", "safe_gate_or_full"):
            raise SafeHilValidationError(
                f"Actuation descriptor {test_id} is no longer FULL with a SAFE gate."
            )

    diagnostics = texts["diagnostics"]
    for test_id, metric in GATED_ACTUATION_METRICS.items():
        required = (
            f'profile=SAFE;executed=0;fixture_required=1;{metric}=0;gate=safe_only'
        )
        if required not in diagnostics:
            raise SafeHilValidationError(
                f"Actuation descriptor {test_id} lacks the required SAFE skip metrics."
            )
    if 'profile_map = {"SAFE": 0, "FULL": 1}' not in texts["runner"]:
        raise SafeHilValidationError("Host runner no longer maps SAFE to profile value 0.")
    if "request.fullProfile = (cmd.p1Len > 0u) && (cmd.p1u() == 1u);" not in texts["orchestrator"]:
        raise SafeHilValidationError("Firmware no longer enables FULL only for profile value 1.")

    return {
        "schema_name": "labcraft.safe_hil_source_contract",
        "schema_version": 1,
        "status": "passed",
        "safe_test_ids": sorted(SAFE_TEST_IDS),
        "gated_actuation_test_ids": sorted(GATED_ACTUATION_METRICS),
        "source_sha256": {name: _sha256(path) for name, path in paths.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", type=Path)
    group.add_argument("--source-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.report is not None:
            evidence = load_and_validate_safe_report(args.report)
        else:
            evidence = validate_safe_source_contract(args.source_root)
    except SafeHilValidationError as exc:
        print(f"SAFE HIL validation failed: {exc}")
        return 2
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
