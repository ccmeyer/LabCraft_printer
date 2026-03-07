import json
import os
import tempfile
from datetime import datetime, timezone
from statistics import median, pstdev

from CalibrationIdentity import (
    QUALITY_EXPLICIT,
    QUALITY_INFERRED,
    QUALITY_UNKNOWN,
    SCHEMA_FAMILY,
    SCHEMA_VERSION,
    normalize_identity_quality_map,
    normalize_legacy_context,
)


def _clean_str(value):
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def _parse_ts(value):
    value = _clean_str(value)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _iso_or_none(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return _clean_str(value)


def _sorted_unique(values):
    out = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _median_or_none(values):
    vals = [float(v) for v in values if _float_or_none(v) is not None]
    if not vals:
        return None
    return float(median(vals))


def _cv_percent(values):
    vals = [float(v) for v in values if _float_or_none(v) is not None]
    if len(vals) <= 1:
        return 0.0 if vals else None
    mean_val = sum(vals) / len(vals)
    if abs(mean_val) < 1e-9:
        return None
    return float(pstdev(vals) / abs(mean_val) * 100.0)


def _normalize_band(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lo = _float_or_none(value[0])
    hi = _float_or_none(value[1])
    if lo is None or hi is None:
        return None
    lo, hi = sorted((float(lo), float(hi)))
    return [lo, hi]


def _midpoint(value):
    band = _normalize_band(value)
    if band is None:
        return None
    return float((band[0] + band[1]) / 2.0)


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _json_default(obj):
    try:
        import numpy as _np

        if isinstance(obj, (_np.integer,)):
            return int(obj)
        if isinstance(obj, (_np.floating,)):
            return float(obj)
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    return str(obj)


class CalibrationMemoryAggregator:
    PAIR_MEMORY_SCHEMA = f"{SCHEMA_FAMILY}.pair_memory"
    PAIR_TYPE_MEMORY_SCHEMA = f"{SCHEMA_FAMILY}.pair_type_memory"
    REAGENT_MEMORY_SCHEMA = f"{SCHEMA_FAMILY}.reagent_memory"
    HEAD_TYPE_MEMORY_SCHEMA = f"{SCHEMA_FAMILY}.head_type_memory"
    RECOMMENDATION_INDEX_SCHEMA = f"{SCHEMA_FAMILY}.recommendation_index"

    AGGREGATION_LEVEL_EXACT_PAIR = "exact_pair"
    AGGREGATION_LEVEL_REAGENT_HEAD_TYPE = "exact_reagent_head_type"
    AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE = "reagent_family_head_type"
    AGGREGATION_LEVEL_REAGENT_ONLY = "reagent_only"
    AGGREGATION_LEVEL_HEAD_TYPE_ONLY = "head_type_only"

    FEATURE_EXTRACTION_VERSION = 1

    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)
        self.indices_dir = os.path.join(self.root_dir, "indices")
        self.runs_dir = os.path.join(self.root_dir, "runs")
        self.pair_memory_path = os.path.join(self.indices_dir, "pair_memory.json")
        self.pair_type_memory_path = os.path.join(self.indices_dir, "pair_type_memory.json")
        self.reagent_memory_path = os.path.join(self.indices_dir, "reagent_memory.json")
        self.head_type_memory_path = os.path.join(self.indices_dir, "head_type_memory.json")
        self.recommendation_index_path = os.path.join(self.indices_dir, "recommendation_index.json")

    def ensure_initialized(self):
        os.makedirs(self.indices_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)

    @staticmethod
    def _write_json_atomic(path, payload):
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix="._tmp_",
            suffix=os.path.splitext(path)[1] or ".tmp",
            dir=os.path.dirname(path),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=_json_default)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            raise

    @staticmethod
    def _load_json(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @classmethod
    def _latest_phase_result(cls, summary, authoritative_run, phase_names):
        if isinstance(authoritative_run, dict):
            steps = authoritative_run.get("steps") or {}
            for phase_name in phase_names:
                for step in reversed(list(steps.get(phase_name) or [])):
                    result = step.get("result")
                    if isinstance(result, dict):
                        return result

        process_results = summary.get("process_results") or {}
        for phase_name in phase_names:
            result = (process_results.get(phase_name) or {}).get("latest_result")
            if isinstance(result, dict):
                return result
        return {}

    @classmethod
    def _latest_phase_settings(cls, summary, authoritative_run, phase_names):
        if isinstance(authoritative_run, dict):
            steps = authoritative_run.get("steps") or {}
            for phase_name in phase_names:
                for step in reversed(list(steps.get(phase_name) or [])):
                    settings = step.get("settings")
                    if isinstance(settings, dict):
                        return settings

        process_results = summary.get("process_results") or {}
        for phase_name in phase_names:
            settings = (process_results.get(phase_name) or {}).get("latest_settings")
            if isinstance(settings, dict):
                return settings
        return {}

    @classmethod
    def _extract_pressure_sweep_rows(cls, summary, authoritative_run):
        rows = []
        seen = set()

        def _append_rows(result, settings, timestamp):
            result = result if isinstance(result, dict) else {}
            settings = settings if isinstance(settings, dict) else {}
            pulse_width_us = _coalesce(
                _int_or_none(result.get("print_pulse_width_us")),
                _int_or_none(settings.get("print_width")),
            )
            emergence_time_us = _coalesce(
                _int_or_none(result.get("emergence_time_us")),
                _int_or_none(result.get("sphere_delay_us")),
                _int_or_none(result.get("delay_us")),
            )
            for raw_row in list(result.get("pressures") or []):
                if not isinstance(raw_row, dict):
                    continue
                pressure = _float_or_none(raw_row.get("pressure"))
                mean_volume = _float_or_none(raw_row.get("mean_volume"))
                cv_pct = _float_or_none(raw_row.get("cv_volume_percent"))
                valid = raw_row.get("valid")
                if valid is None:
                    valid = mean_volume is not None
                key = (
                    pulse_width_us,
                    pressure,
                    mean_volume,
                    cv_pct,
                    bool(valid),
                    _clean_str(raw_row.get("invalid_reason")),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "pulse_width_us": pulse_width_us,
                        "pressure": pressure,
                        "mean_volume": mean_volume,
                        "cv_volume_percent": cv_pct,
                        "valid": bool(valid),
                        "invalid_reason": _clean_str(raw_row.get("invalid_reason")),
                        "timestamp": _clean_str(timestamp),
                        "emergence_time_us": emergence_time_us,
                    }
                )

        if isinstance(authoritative_run, dict):
            steps = authoritative_run.get("steps") or {}
            for step in list(steps.get("pressure_sweep_characterization") or []):
                _append_rows(step.get("result"), step.get("settings"), step.get("timestamp"))

        if rows:
            return rows

        process_result = cls._latest_phase_result(summary, None, ("pressure_sweep_characterization",))
        process_settings = cls._latest_phase_settings(summary, None, ("pressure_sweep_characterization",))
        timestamp = (summary.get("process_results") or {}).get("pressure_sweep_characterization", {}).get("latest_timestamp")
        _append_rows(process_result, process_settings, timestamp)
        return rows

    @classmethod
    def _preferred_sweep_row(cls, rows):
        valid_rows = [row for row in rows if bool(row.get("valid")) and row.get("pressure") is not None]
        if not valid_rows:
            return None
        median_pressure = _median_or_none([row.get("pressure") for row in valid_rows])

        def _key(row):
            cv_pct = _float_or_none(row.get("cv_volume_percent"))
            if cv_pct is None:
                cv_pct = 1e9
            distance = 0.0
            if median_pressure is not None and row.get("pressure") is not None:
                distance = abs(float(row["pressure"]) - median_pressure)
            vol_missing = 1 if row.get("mean_volume") is None else 0
            return (cv_pct, vol_missing, distance, float(row["pressure"]))

        return min(valid_rows, key=_key)

    @classmethod
    def _valid_pressure_band_from_rows(cls, rows):
        valid_pressures = sorted(
            float(row["pressure"])
            for row in rows
            if bool(row.get("valid")) and row.get("pressure") is not None
        )
        if not valid_pressures:
            return None
        return [float(valid_pressures[0]), float(valid_pressures[-1])]

    @classmethod
    def _run_status(cls, summary):
        status = _clean_str(summary.get("run_status"))
        if status:
            return status
        ended_at = _clean_str((summary.get("run_timing") or {}).get("ended_at_utc"))
        return "completed" if ended_at else "in_progress"

    @classmethod
    def extract_run_features(cls, summary, authoritative_run=None):
        summary = dict(summary or {})
        context = normalize_legacy_context(summary.get("context") or {})
        quality = normalize_identity_quality_map(context.get("identity_quality", {}))

        droplet_emergence = cls._latest_phase_result(summary, authoritative_run, ("droplet_emergence",))
        pressure_calibration = cls._latest_phase_result(summary, authoritative_run, ("pressure_calibration",))
        pressure_scan = cls._latest_phase_result(summary, authoritative_run, ("pressure_scan",))
        pressure_trajectory = cls._latest_phase_result(summary, authoritative_run, ("pressure_trajectory", "trajectory"))
        droplet_search = cls._latest_phase_result(summary, authoritative_run, ("droplet_search",))
        pressure_sweep_rows = cls._extract_pressure_sweep_rows(summary, authoritative_run)
        preferred_sweep_row = cls._preferred_sweep_row(pressure_sweep_rows)

        droplet_search_settings = cls._latest_phase_settings(summary, authoritative_run, ("droplet_search",))
        pressure_scan_settings = cls._latest_phase_settings(summary, authoritative_run, ("pressure_scan",))
        pressure_sweep_settings = cls._latest_phase_settings(summary, authoritative_run, ("pressure_sweep_characterization",))

        pulse_width_us = _coalesce(
            _int_or_none(droplet_search.get("print_pulse_width_us")),
            _int_or_none(droplet_search_settings.get("print_width")),
            _int_or_none(pressure_scan.get("pulse_width_us")),
            _int_or_none(pressure_scan_settings.get("print_width")),
            _int_or_none((preferred_sweep_row or {}).get("pulse_width_us")),
            _int_or_none(pressure_sweep_settings.get("print_width")),
            _int_or_none(
                ((summary.get("process_results") or {}).get("droplet_search", {}) or {}).get("latest_settings", {})
                .get("print_width")
            ),
        )

        primary_band = _normalize_band(_coalesce(pressure_scan.get("primary_band"), pressure_scan.get("raw_primary_band")))
        sweep_band = cls._valid_pressure_band_from_rows(pressure_sweep_rows)
        trajectory_band = _normalize_band(
            _coalesce(
                pressure_trajectory.get("trajectory_pressure_band"),
                pressure_trajectory.get("band_used"),
            )
        )
        if trajectory_band is None:
            valid_fit_pressures = [
                _float_or_none(value)
                for value in list(pressure_trajectory.get("valid_fit_pressures") or [])
                if _float_or_none(value) is not None
            ]
            if valid_fit_pressures:
                trajectory_band = [float(min(valid_fit_pressures)), float(max(valid_fit_pressures))]

        recommended_pressure_psi = None
        recommended_pressure_source = None
        droplet_search_valid = bool(droplet_search.get("valid", True))
        if droplet_search_valid and _float_or_none(droplet_search.get("pressure")) is not None:
            recommended_pressure_psi = _float_or_none(droplet_search.get("pressure"))
            recommended_pressure_source = "droplet_search"
        elif _float_or_none(pressure_calibration.get("pressure")) is not None:
            recommended_pressure_psi = _float_or_none(pressure_calibration.get("pressure"))
            recommended_pressure_source = "pressure_calibration"
        elif preferred_sweep_row is not None and preferred_sweep_row.get("pressure") is not None:
            recommended_pressure_psi = _float_or_none(preferred_sweep_row.get("pressure"))
            recommended_pressure_source = "pressure_sweep_characterization"
        elif trajectory_band is not None:
            recommended_pressure_psi = _midpoint(trajectory_band)
            recommended_pressure_source = "pressure_trajectory_band_midpoint"
        elif primary_band is not None:
            recommended_pressure_psi = _midpoint(primary_band)
            recommended_pressure_source = "pressure_scan_primary_band_midpoint"
        elif sweep_band is not None:
            recommended_pressure_psi = _midpoint(sweep_band)
            recommended_pressure_source = "pressure_sweep_valid_band_midpoint"

        expected_mean_volume_nl = None
        expected_cv_pct = None
        volume_source = None
        if droplet_search_valid and _float_or_none(droplet_search.get("mean_volume")) is not None:
            expected_mean_volume_nl = _float_or_none(droplet_search.get("mean_volume"))
            expected_cv_pct = _float_or_none(droplet_search.get("cv_volume_percent"))
            volume_source = "droplet_search"
        elif preferred_sweep_row is not None and _float_or_none(preferred_sweep_row.get("mean_volume")) is not None:
            expected_mean_volume_nl = _float_or_none(preferred_sweep_row.get("mean_volume"))
            expected_cv_pct = _float_or_none(preferred_sweep_row.get("cv_volume_percent"))
            volume_source = "pressure_sweep_characterization"

        emergence_time_us = _coalesce(
            _int_or_none(pressure_trajectory.get("emergence_time_us")),
            _int_or_none((preferred_sweep_row or {}).get("emergence_time_us")),
            _int_or_none(droplet_emergence.get("flash_delay")),
            _int_or_none(pressure_scan.get("delay_us")),
            _int_or_none(droplet_search.get("delay_us")),
        )
        emergence_time_source = None
        if emergence_time_us is not None:
            if _int_or_none(pressure_trajectory.get("emergence_time_us")) is not None:
                emergence_time_source = "pressure_trajectory"
            elif _int_or_none((preferred_sweep_row or {}).get("emergence_time_us")) is not None:
                emergence_time_source = "pressure_sweep_characterization"
            elif _int_or_none(droplet_emergence.get("flash_delay")) is not None:
                emergence_time_source = "droplet_emergence"
            elif _int_or_none(pressure_scan.get("delay_us")) is not None:
                emergence_time_source = "pressure_scan"
            else:
                emergence_time_source = "droplet_search"

        run_status = cls._run_status(summary)
        qualification_reasons = []
        if run_status != "completed":
            qualification_reasons.append("run_not_completed")
        if pulse_width_us is None:
            qualification_reasons.append("missing_pulse_width_us")
        if all(
            value is None
            for value in (
                recommended_pressure_psi,
                primary_band,
                sweep_band,
                trajectory_band,
                expected_mean_volume_nl,
            )
        ):
            qualification_reasons.append("missing_calibration_metrics")

        usable_for_aggregation = not qualification_reasons

        def _is_explicit(field_name):
            return quality.get(field_name) == QUALITY_EXPLICIT and _clean_str(context.get(field_name)) is not None

        def _is_known(field_name):
            return quality.get(field_name) in (QUALITY_EXPLICIT, QUALITY_INFERRED) and _clean_str(context.get(field_name)) is not None

        eligible_aggregation_levels = []
        if usable_for_aggregation:
            if _is_explicit("reagent_id") and _is_explicit("printer_head_id"):
                eligible_aggregation_levels.append(cls.AGGREGATION_LEVEL_EXACT_PAIR)
            if _is_explicit("reagent_id") and _is_explicit("head_type_id"):
                eligible_aggregation_levels.append(cls.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE)
            if _clean_str(context.get("reagent_family")) and _is_known("head_type_id"):
                eligible_aggregation_levels.append(cls.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE)
            if _is_known("reagent_id"):
                eligible_aggregation_levels.append(cls.AGGREGATION_LEVEL_REAGENT_ONLY)
            if _is_known("head_type_id"):
                eligible_aggregation_levels.append(cls.AGGREGATION_LEVEL_HEAD_TYPE_ONLY)

        valid_sweep_rows = [row for row in pressure_sweep_rows if bool(row.get("valid"))]
        return {
            "schema_name": f"{SCHEMA_FAMILY}.run_features",
            "schema_version": int(SCHEMA_VERSION),
            "feature_extraction_version": int(cls.FEATURE_EXTRACTION_VERSION),
            "run_id": _clean_str(summary.get("run_id")),
            "run_status": run_status,
            "usable_for_aggregation": bool(usable_for_aggregation),
            "qualification_reasons": qualification_reasons,
            "eligible_aggregation_levels": eligible_aggregation_levels,
            "pulse_width_us": pulse_width_us,
            "recommended_pressure_psi": recommended_pressure_psi,
            "recommended_pressure_source": recommended_pressure_source,
            "single_droplet_band_psi": _coalesce(primary_band, sweep_band),
            "single_droplet_band_source": (
                "pressure_scan_primary_band"
                if primary_band is not None
                else ("pressure_sweep_valid_band" if sweep_band is not None else None)
            ),
            "trajectory_pressure_band_psi": trajectory_band,
            "trajectory_pressure_band_source": "pressure_trajectory" if trajectory_band is not None else None,
            "emergence_time_us": emergence_time_us,
            "emergence_time_source": emergence_time_source,
            "expected_mean_volume_nL": expected_mean_volume_nl,
            "expected_cv_pct": expected_cv_pct,
            "volume_source": volume_source,
            "pressure_sweep": {
                "row_count": int(len(pressure_sweep_rows)),
                "valid_row_count": int(len(valid_sweep_rows)),
                "valid_pressure_band_psi": sweep_band,
                "preferred_pressure_psi": _float_or_none((preferred_sweep_row or {}).get("pressure")),
                "preferred_mean_volume_nL": _float_or_none((preferred_sweep_row or {}).get("mean_volume")),
                "preferred_cv_pct": _float_or_none((preferred_sweep_row or {}).get("cv_volume_percent")),
            },
        }

    def _iter_run_summary_paths(self):
        if not os.path.isdir(self.runs_dir):
            return []
        paths = []
        for run_name in sorted(os.listdir(self.runs_dir)):
            path = os.path.join(self.runs_dir, run_name, "run_summary.json")
            if os.path.exists(path):
                paths.append(path)
        return paths

    def _load_authoritative_run(self, summary, cache):
        refs = summary.get("authoritative_refs") or {}
        calibration_path = _clean_str(refs.get("calibration_json_path"))
        if calibration_path is None or not os.path.exists(calibration_path):
            return None

        payload = cache.get(calibration_path)
        if payload is None:
            try:
                payload = self._load_json(calibration_path)
            except Exception:
                cache[calibration_path] = False
                return None
            cache[calibration_path] = payload
        if payload is False:
            return None

        runs = list((payload or {}).get("runs") or [])
        run_id = _clean_str(refs.get("calibration_run_id")) or _clean_str(summary.get("run_id"))
        if run_id:
            for run in reversed(runs):
                if _clean_str(run.get("run_id")) == run_id:
                    return run
        run_index = refs.get("calibration_run_index")
        try:
            if run_index is not None:
                run_index = int(run_index)
                if 0 <= run_index < len(runs):
                    return runs[run_index]
        except Exception:
            pass
        return None

    def _build_run_records(self):
        cache = {}
        run_records = []
        for summary_path in self._iter_run_summary_paths():
            try:
                summary = self._load_json(summary_path)
            except Exception:
                continue
            if not isinstance(summary, dict):
                continue

            authoritative_run = self._load_authoritative_run(summary, cache)
            try:
                derived_metrics = self.extract_run_features(summary, authoritative_run=authoritative_run)
            except Exception:
                continue

            context = normalize_legacy_context(summary.get("context") or {})
            source_refs = dict(summary.get("source_refs") or {})
            source_refs.setdefault("run_summary_path", summary_path)
            source_refs.setdefault("observations_path", os.path.join(os.path.dirname(summary_path), "observations.jsonl"))
            run_records.append(
                {
                    "run_id": _clean_str(summary.get("run_id")),
                    "summary": summary,
                    "context": context,
                    "source_refs": source_refs,
                    "authoritative_refs": dict(summary.get("authoritative_refs") or {}),
                    "derived_metrics": derived_metrics,
                    "updated_at_utc": _coalesce(
                        _clean_str((summary.get("run_timing") or {}).get("ended_at_utc")),
                        _clean_str(summary.get("last_updated_at_utc")),
                    ),
                }
            )
        return run_records

    @staticmethod
    def _identity_quality_summary(run_records):
        fields = (
            "reagent_id",
            "stock_id",
            "printer_head_id",
            "head_type_id",
            "nominal_nozzle_diameter_um",
            "measured_nozzle_diameter_um",
        )
        summary = {}
        for field_name in fields:
            counts = {QUALITY_EXPLICIT: 0, QUALITY_INFERRED: 0, QUALITY_UNKNOWN: 0}
            for run_record in run_records:
                quality = normalize_identity_quality_map((run_record.get("context") or {}).get("identity_quality", {}))
                counts[quality.get(field_name, QUALITY_UNKNOWN)] += 1
            summary[field_name] = counts
        return summary

    @staticmethod
    def _source_run_refs(run_records):
        refs = []
        for run_record in run_records:
            refs.append(
                {
                    "run_id": run_record.get("run_id"),
                    "run_summary_path": _clean_str((run_record.get("source_refs") or {}).get("run_summary_path")),
                    "observations_path": _clean_str((run_record.get("source_refs") or {}).get("observations_path")),
                    "calibration_json_path": _clean_str((run_record.get("authoritative_refs") or {}).get("calibration_json_path")),
                    "ended_at_utc": _clean_str((run_record.get("summary") or {}).get("run_timing", {}).get("ended_at_utc")),
                }
            )
        refs.sort(key=lambda item: ((_clean_str(item.get("ended_at_utc")) or ""), (_clean_str(item.get("run_id")) or "")))
        return refs

    def _confidence_for_bucket(self, aggregation_level, run_records, bucket, dataset_latest_ts):
        base_by_level = {
            self.AGGREGATION_LEVEL_EXACT_PAIR: 0.82,
            self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE: 0.72,
            self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE: 0.58,
            self.AGGREGATION_LEVEL_REAGENT_ONLY: 0.48,
            self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY: 0.42,
        }
        relevant_fields = {
            self.AGGREGATION_LEVEL_EXACT_PAIR: ("reagent_id", "printer_head_id"),
            self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE: ("reagent_id", "head_type_id"),
            self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE: ("head_type_id",),
            self.AGGREGATION_LEVEL_REAGENT_ONLY: ("reagent_id",),
            self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY: ("head_type_id",),
        }

        weak_count = 0
        for run_record in run_records:
            quality = normalize_identity_quality_map((run_record.get("context") or {}).get("identity_quality", {}))
            if any(quality.get(field_name) != QUALITY_EXPLICIT for field_name in relevant_fields.get(aggregation_level, ())):
                weak_count += 1
        weak_fraction = float(weak_count) / float(len(run_records) or 1)

        run_support_adjustment = min(0.12, max(0, len(run_records) - 1) * 0.04)

        consistency_metric = _coalesce(
            _float_or_none(bucket.get("expected_cv_pct")),
            _float_or_none(bucket.get("run_to_run_volume_cv_pct")),
        )
        if consistency_metric is None:
            consistency_adjustment = -0.02
        elif consistency_metric <= 5.0:
            consistency_adjustment = 0.06
        elif consistency_metric <= 10.0:
            consistency_adjustment = 0.03
        elif consistency_metric <= 15.0:
            consistency_adjustment = 0.0
        elif consistency_metric <= 20.0:
            consistency_adjustment = -0.05
        else:
            consistency_adjustment = -0.1

        latest_ts = _parse_ts(bucket.get("updated_at_utc"))
        gap_days = 0.0
        if dataset_latest_ts is not None and latest_ts is not None:
            gap_days = max(0.0, (dataset_latest_ts - latest_ts).total_seconds() / 86400.0)

        if gap_days <= 30.0:
            recency_adjustment = 0.03
        elif gap_days <= 180.0:
            recency_adjustment = 0.0
        elif gap_days <= 365.0:
            recency_adjustment = -0.03
        else:
            recency_adjustment = -0.06

        identity_adjustment = -0.10 * weak_fraction
        confidence = base_by_level.get(aggregation_level, 0.25)
        confidence += run_support_adjustment
        confidence += identity_adjustment
        confidence += consistency_adjustment
        confidence += recency_adjustment
        confidence = max(0.05, min(0.99, confidence))

        return {
            "score": round(confidence, 4),
            "components": {
                "base": round(base_by_level.get(aggregation_level, 0.25), 4),
                "run_support_adjustment": round(run_support_adjustment, 4),
                "identity_adjustment": round(identity_adjustment, 4),
                "consistency_adjustment": round(consistency_adjustment, 4),
                "recency_adjustment": round(recency_adjustment, 4),
                "weak_identity_fraction": round(weak_fraction, 4),
                "latest_gap_days_from_dataset": round(gap_days, 4),
            },
        }

    @staticmethod
    def _count_sources(derived_items, field_name):
        counts = {}
        for item in derived_items:
            key = _clean_str(item.get(field_name)) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _build_pulse_bucket(self, aggregation_level, identity_keys, pulse_width_us, run_records, dataset_latest_ts):
        derived = [record.get("derived_metrics") or {} for record in run_records]
        pressure_values = [item.get("recommended_pressure_psi") for item in derived if item.get("recommended_pressure_psi") is not None]
        volume_values = [item.get("expected_mean_volume_nL") for item in derived if item.get("expected_mean_volume_nL") is not None]
        expected_cv_values = [item.get("expected_cv_pct") for item in derived if item.get("expected_cv_pct") is not None]
        emergence_values = [item.get("emergence_time_us") for item in derived if item.get("emergence_time_us") is not None]
        single_bands = [_normalize_band(item.get("single_droplet_band_psi")) for item in derived]
        single_bands = [band for band in single_bands if band is not None]
        trajectory_bands = [_normalize_band(item.get("trajectory_pressure_band_psi")) for item in derived]
        trajectory_bands = [band for band in trajectory_bands if band is not None]

        bucket = {
            "schema_version": int(SCHEMA_VERSION),
            "aggregation_level": aggregation_level,
            "pulse_width_us": int(pulse_width_us),
            "recommended_pressure_psi": _median_or_none(pressure_values),
            "recommended_pressure_band_psi": (
                [float(min(pressure_values)), float(max(pressure_values))]
                if pressure_values
                else None
            ),
            "emergence_time_us": _median_or_none(emergence_values),
            "stable_single_droplet_band_psi": (
                [
                    _median_or_none([band[0] for band in single_bands]),
                    _median_or_none([band[1] for band in single_bands]),
                ]
                if single_bands
                else None
            ),
            "trajectory_pressure_band_psi": (
                [
                    _median_or_none([band[0] for band in trajectory_bands]),
                    _median_or_none([band[1] for band in trajectory_bands]),
                ]
                if trajectory_bands
                else None
            ),
            "expected_mean_volume_nL": _median_or_none(volume_values),
            "expected_cv_pct": _median_or_none(expected_cv_values),
            "run_to_run_volume_cv_pct": _cv_percent(volume_values),
            "contributing_runs": int(len(run_records)),
            "sample_count": int(len(run_records)),
            "source_run_ids": _sorted_unique([record.get("run_id") for record in run_records if record.get("run_id")]),
            "source_run_refs": self._source_run_refs(run_records),
            "identity_quality_summary": self._identity_quality_summary(run_records),
            "identity_keys": dict(identity_keys),
            "recommendation_sources": {
                "recommended_pressure": self._count_sources(derived, "recommended_pressure_source"),
                "volume": self._count_sources(derived, "volume_source"),
            },
            "updated_at_utc": _iso_or_none(
                max(
                    (
                        _parse_ts(record.get("updated_at_utc"))
                        for record in run_records
                        if _parse_ts(record.get("updated_at_utc")) is not None
                    ),
                    default=None,
                )
            ),
        }
        confidence = self._confidence_for_bucket(aggregation_level, run_records, bucket, dataset_latest_ts)
        bucket["recommendation_confidence"] = confidence["score"]
        bucket["confidence_components"] = confidence["components"]
        return bucket

    def _build_entry(self, aggregation_level, entry_key, identity_keys, run_records, dataset_latest_ts):
        per_pulse = {}
        for pulse_width_us in sorted(
            {
                int(record["derived_metrics"]["pulse_width_us"])
                for record in run_records
                if _int_or_none((record.get("derived_metrics") or {}).get("pulse_width_us")) is not None
            }
        ):
            pulse_run_records = [
                record for record in run_records if _int_or_none((record.get("derived_metrics") or {}).get("pulse_width_us")) == pulse_width_us
            ]
            if not pulse_run_records:
                continue
            per_pulse[str(pulse_width_us)] = self._build_pulse_bucket(
                aggregation_level,
                identity_keys,
                pulse_width_us,
                pulse_run_records,
                dataset_latest_ts,
            )

        default_recommendation = None
        if per_pulse:
            default_recommendation = max(
                per_pulse.values(),
                key=lambda bucket: (
                    float(bucket.get("recommendation_confidence") or 0.0),
                    int(bucket.get("contributing_runs") or 0),
                    _clean_str(bucket.get("updated_at_utc")) or "",
                    -int(bucket.get("pulse_width_us") or 0),
                ),
            )

        return {
            "schema_version": int(SCHEMA_VERSION),
            "aggregation_level": aggregation_level,
            "entry_key": entry_key,
            "identity_keys": dict(identity_keys),
            "available_pulse_widths_us": [int(value) for value in sorted(int(key) for key in per_pulse.keys())],
            "contributing_run_count": int(len(run_records)),
            "source_run_ids": _sorted_unique([record.get("run_id") for record in run_records if record.get("run_id")]),
            "source_run_refs": self._source_run_refs(run_records),
            "identity_quality_summary": self._identity_quality_summary(run_records),
            "per_pulse_width": per_pulse,
            "default_recommendation": default_recommendation,
            "updated_at_utc": _iso_or_none(
                max(
                    (
                        _parse_ts(record.get("updated_at_utc"))
                        for record in run_records
                        if _parse_ts(record.get("updated_at_utc")) is not None
                    ),
                    default=None,
                )
            ),
        }

    def _build_aggregate_entries(self, run_records, aggregation_level):
        groups = {}
        for record in run_records:
            context = record.get("context") or {}
            derived = record.get("derived_metrics") or {}
            if not bool(derived.get("usable_for_aggregation")):
                continue
            if aggregation_level not in list(derived.get("eligible_aggregation_levels") or []):
                continue

            if aggregation_level == self.AGGREGATION_LEVEL_EXACT_PAIR:
                identity_keys = {
                    "reagent_id": context.get("reagent_id"),
                    "printer_head_id": context.get("printer_head_id"),
                    "head_type_id": context.get("head_type_id"),
                }
                entry_key = f"{identity_keys['reagent_id']}::{identity_keys['printer_head_id']}"
            elif aggregation_level == self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE:
                identity_keys = {
                    "reagent_id": context.get("reagent_id"),
                    "head_type_id": context.get("head_type_id"),
                }
                entry_key = f"{identity_keys['reagent_id']}::{identity_keys['head_type_id']}"
            elif aggregation_level == self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE:
                identity_keys = {
                    "reagent_family": context.get("reagent_family"),
                    "head_type_id": context.get("head_type_id"),
                }
                entry_key = f"{identity_keys['reagent_family']}::{identity_keys['head_type_id']}"
            elif aggregation_level == self.AGGREGATION_LEVEL_REAGENT_ONLY:
                identity_keys = {
                    "reagent_id": context.get("reagent_id"),
                    "reagent_family": context.get("reagent_family"),
                }
                entry_key = str(identity_keys["reagent_id"])
            elif aggregation_level == self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY:
                identity_keys = {
                    "head_type_id": context.get("head_type_id"),
                    "nominal_nozzle_diameter_um": context.get("nominal_nozzle_diameter_um"),
                }
                entry_key = str(identity_keys["head_type_id"])
            else:
                continue

            if any(value is None for key, value in identity_keys.items() if key in ("reagent_id", "printer_head_id", "head_type_id", "reagent_family")):
                continue

            groups.setdefault(entry_key, {"identity_keys": identity_keys, "run_records": []})
            groups[entry_key]["run_records"].append(record)

        dataset_latest_ts = max(
            (
                _parse_ts(record.get("updated_at_utc"))
                for record in run_records
                if _parse_ts(record.get("updated_at_utc")) is not None
            ),
            default=None,
        )

        entries = []
        for entry_key in sorted(groups):
            group = groups[entry_key]
            entries.append(
                self._build_entry(
                    aggregation_level,
                    entry_key,
                    group.get("identity_keys") or {},
                    group.get("run_records") or [],
                    dataset_latest_ts,
                )
            )
        return entries, dataset_latest_ts

    def _snapshot_payload(self, schema_name, entries, dataset_latest_ts):
        return {
            "schema_name": schema_name,
            "schema_version": int(SCHEMA_VERSION),
            "feature_extraction_version": int(self.FEATURE_EXTRACTION_VERSION),
            "entry_count": int(len(entries)),
            "updated_at_utc": _iso_or_none(dataset_latest_ts),
            "entries": entries,
        }

    def _build_recommendation_index(self, snapshots):
        entries = []
        order = (
            self.AGGREGATION_LEVEL_EXACT_PAIR,
            self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE,
            self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE,
            self.AGGREGATION_LEVEL_REAGENT_ONLY,
            self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY,
        )
        lookup_rank = {name: idx + 1 for idx, name in enumerate(order)}
        for snapshot in snapshots:
            for entry in list(snapshot.get("entries") or []):
                for pulse_key, bucket in sorted((entry.get("per_pulse_width") or {}).items(), key=lambda item: int(item[0])):
                    flat_entry = {
                        "schema_version": int(SCHEMA_VERSION),
                        "aggregation_level": entry.get("aggregation_level"),
                        "lookup_rank": int(lookup_rank.get(entry.get("aggregation_level"), 99)),
                        "entry_key": entry.get("entry_key"),
                        "identity_keys": dict(entry.get("identity_keys") or {}),
                        "available_pulse_widths_us": list(entry.get("available_pulse_widths_us") or []),
                        "pulse_width_us": _int_or_none(bucket.get("pulse_width_us")),
                        "recommended_pressure_psi": _float_or_none(bucket.get("recommended_pressure_psi")),
                        "recommended_pressure_band_psi": _normalize_band(bucket.get("recommended_pressure_band_psi")),
                        "stable_single_droplet_band_psi": _normalize_band(bucket.get("stable_single_droplet_band_psi")),
                        "trajectory_pressure_band_psi": _normalize_band(bucket.get("trajectory_pressure_band_psi")),
                        "emergence_time_us": _int_or_none(bucket.get("emergence_time_us")),
                        "expected_mean_volume_nL": _float_or_none(bucket.get("expected_mean_volume_nL")),
                        "expected_cv_pct": _float_or_none(bucket.get("expected_cv_pct")),
                        "run_to_run_volume_cv_pct": _float_or_none(bucket.get("run_to_run_volume_cv_pct")),
                        "contributing_runs": int(bucket.get("contributing_runs") or 0),
                        "sample_count": int(bucket.get("sample_count") or 0),
                        "source_run_ids": list(bucket.get("source_run_ids") or []),
                        "source_run_refs": list(bucket.get("source_run_refs") or []),
                        "identity_quality_summary": dict(bucket.get("identity_quality_summary") or {}),
                        "recommendation_confidence": _float_or_none(bucket.get("recommendation_confidence")),
                        "confidence_components": dict(bucket.get("confidence_components") or {}),
                        "updated_at_utc": _clean_str(bucket.get("updated_at_utc")),
                    }
                    entries.append(flat_entry)

        entries.sort(
            key=lambda item: (
                int(item.get("lookup_rank") or 99),
                _clean_str(item.get("entry_key")) or "",
                int(item.get("pulse_width_us") or 0),
            )
        )
        dataset_latest_ts = max((_parse_ts(item.get("updated_at_utc")) for item in entries if _parse_ts(item.get("updated_at_utc")) is not None), default=None)
        return {
            "schema_name": self.RECOMMENDATION_INDEX_SCHEMA,
            "schema_version": int(SCHEMA_VERSION),
            "feature_extraction_version": int(self.FEATURE_EXTRACTION_VERSION),
            "entry_count": int(len(entries)),
            "updated_at_utc": _iso_or_none(dataset_latest_ts),
            "entries": entries,
        }

    def rebuild(self):
        self.ensure_initialized()
        run_records = self._build_run_records()
        exact_pair_entries, dataset_latest_ts = self._build_aggregate_entries(run_records, self.AGGREGATION_LEVEL_EXACT_PAIR)
        pair_type_entries_exact, dataset_latest_ts_exact = self._build_aggregate_entries(run_records, self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE)
        pair_type_entries_family, dataset_latest_ts_family = self._build_aggregate_entries(run_records, self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE)
        reagent_entries, dataset_latest_ts_reagent = self._build_aggregate_entries(run_records, self.AGGREGATION_LEVEL_REAGENT_ONLY)
        head_type_entries, dataset_latest_ts_head = self._build_aggregate_entries(run_records, self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY)

        dataset_latest_ts = max(
            (ts for ts in (dataset_latest_ts, dataset_latest_ts_exact, dataset_latest_ts_family, dataset_latest_ts_reagent, dataset_latest_ts_head) if ts is not None),
            default=None,
        )

        pair_memory = self._snapshot_payload(self.PAIR_MEMORY_SCHEMA, exact_pair_entries, dataset_latest_ts)
        pair_type_memory = self._snapshot_payload(
            self.PAIR_TYPE_MEMORY_SCHEMA,
            pair_type_entries_exact + pair_type_entries_family,
            dataset_latest_ts,
        )
        reagent_memory = self._snapshot_payload(self.REAGENT_MEMORY_SCHEMA, reagent_entries, dataset_latest_ts)
        head_type_memory = self._snapshot_payload(self.HEAD_TYPE_MEMORY_SCHEMA, head_type_entries, dataset_latest_ts)
        recommendation_index = self._build_recommendation_index(
            [pair_memory, pair_type_memory, reagent_memory, head_type_memory]
        )

        self._write_json_atomic(self.pair_memory_path, pair_memory)
        self._write_json_atomic(self.pair_type_memory_path, pair_type_memory)
        self._write_json_atomic(self.reagent_memory_path, reagent_memory)
        self._write_json_atomic(self.head_type_memory_path, head_type_memory)
        self._write_json_atomic(self.recommendation_index_path, recommendation_index)

        return {
            "pair_memory_path": self.pair_memory_path,
            "pair_type_memory_path": self.pair_type_memory_path,
            "reagent_memory_path": self.reagent_memory_path,
            "head_type_memory_path": self.head_type_memory_path,
            "recommendation_index_path": self.recommendation_index_path,
            "entry_counts": {
                "pair_memory": int(pair_memory.get("entry_count") or 0),
                "pair_type_memory": int(pair_type_memory.get("entry_count") or 0),
                "reagent_memory": int(reagent_memory.get("entry_count") or 0),
                "head_type_memory": int(head_type_memory.get("entry_count") or 0),
                "recommendation_index": int(recommendation_index.get("entry_count") or 0),
            },
        }

    def load_recommendation_index(self):
        if not os.path.exists(self.recommendation_index_path):
            self.rebuild()
        return self._load_json(self.recommendation_index_path)

    @staticmethod
    def _entry_matches_context(entry, context, aggregation_level):
        identity_keys = dict(entry.get("identity_keys") or {})
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR:
            return (
                _clean_str(identity_keys.get("reagent_id")) == _clean_str(context.get("reagent_id"))
                and _clean_str(identity_keys.get("printer_head_id")) == _clean_str(context.get("printer_head_id"))
            )
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE:
            return (
                _clean_str(identity_keys.get("reagent_id")) == _clean_str(context.get("reagent_id"))
                and _clean_str(identity_keys.get("head_type_id")) == _clean_str(context.get("head_type_id"))
            )
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE:
            return (
                _clean_str(identity_keys.get("reagent_family")) == _clean_str(context.get("reagent_family"))
                and _clean_str(identity_keys.get("head_type_id")) == _clean_str(context.get("head_type_id"))
            )
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_ONLY:
            return _clean_str(identity_keys.get("reagent_id")) == _clean_str(context.get("reagent_id"))
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_HEAD_TYPE_ONLY:
            return _clean_str(identity_keys.get("head_type_id")) == _clean_str(context.get("head_type_id"))
        return False

    @staticmethod
    def _selection_kind_for_level(aggregation_level, pulse_distance_us):
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR and pulse_distance_us == 0:
            return "exact"
        if aggregation_level == CalibrationMemoryAggregator.AGGREGATION_LEVEL_EXACT_PAIR:
            return "near_exact"
        if aggregation_level in (
            CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE,
            CalibrationMemoryAggregator.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE,
        ):
            return "grouped"
        return "weak_fallback"

    @staticmethod
    def _pulse_penalty(target_pulse_width_us, candidate_pulse_width_us):
        target = _int_or_none(target_pulse_width_us)
        candidate = _int_or_none(candidate_pulse_width_us)
        if target is None or candidate is None:
            return 0.0
        distance = abs(int(target) - int(candidate))
        if distance == 0:
            return 0.0
        return min(0.15, 0.03 + (distance / 1000.0) * 0.08)

    @staticmethod
    def _volume_penalty(target_volume_nl, candidate_volume_nl):
        target = _float_or_none(target_volume_nl)
        candidate = _float_or_none(candidate_volume_nl)
        if target is None or candidate is None:
            return 0.0
        if abs(target) < 1e-9:
            return 0.0
        relative_error = abs(candidate - target) / abs(target)
        return min(0.12, relative_error * 0.08)

    def get_best_prior(self, context, target_pulse_width_us=None, target_volume_nl=None):
        context = normalize_legacy_context(context or {})
        recommendation_index = self.load_recommendation_index()
        entries = list(recommendation_index.get("entries") or [])
        if not entries:
            return None

        level_order = (
            self.AGGREGATION_LEVEL_EXACT_PAIR,
            self.AGGREGATION_LEVEL_REAGENT_HEAD_TYPE,
            self.AGGREGATION_LEVEL_REAGENT_FAMILY_HEAD_TYPE,
            self.AGGREGATION_LEVEL_REAGENT_ONLY,
            self.AGGREGATION_LEVEL_HEAD_TYPE_ONLY,
        )

        for level_rank, aggregation_level in enumerate(level_order, start=1):
            matches = [
                entry
                for entry in entries
                if entry.get("aggregation_level") == aggregation_level
                and self._entry_matches_context(entry, context, aggregation_level)
            ]
            if not matches:
                continue

            ranked = []
            for entry in matches:
                candidate_pulse = _int_or_none(entry.get("pulse_width_us"))
                pulse_distance = abs((_int_or_none(target_pulse_width_us) or candidate_pulse or 0) - (candidate_pulse or 0))
                exact_pulse = 1 if _int_or_none(target_pulse_width_us) is not None and pulse_distance == 0 else 0
                confidence = _float_or_none(entry.get("recommendation_confidence")) or 0.0
                adjusted_confidence = confidence
                adjusted_confidence -= self._pulse_penalty(target_pulse_width_us, candidate_pulse)
                adjusted_confidence -= self._volume_penalty(target_volume_nl, entry.get("expected_mean_volume_nL"))
                adjusted_confidence = max(0.01, round(adjusted_confidence, 4))
                ranked.append(
                    (
                        exact_pulse,
                        -pulse_distance,
                        adjusted_confidence,
                        int(entry.get("contributing_runs") or 0),
                        _clean_str(entry.get("updated_at_utc")) or "",
                        -int(candidate_pulse or 0),
                        entry,
                        pulse_distance,
                        adjusted_confidence,
                    )
                )

            ranked.sort(reverse=True)
            chosen = ranked[0][6]
            pulse_distance = ranked[0][7]
            adjusted_confidence = ranked[0][8]
            selection_kind = self._selection_kind_for_level(aggregation_level, pulse_distance)
            prior = dict(chosen)
            prior["match_type"] = selection_kind
            prior["pulse_match_type"] = "exact" if pulse_distance == 0 else "nearest"
            prior["pulse_distance_us"] = int(pulse_distance)
            prior["selection_order"] = int(level_rank)
            prior["selection_reason"] = (
                f"{aggregation_level} prior selected at pulse {prior.get('pulse_width_us')} us "
                f"from {prior.get('contributing_runs')} completed runs"
            )
            prior["recommendation_confidence_adjusted"] = adjusted_confidence
            prior["requested_context"] = {
                "reagent_id": context.get("reagent_id"),
                "reagent_family": context.get("reagent_family"),
                "printer_head_id": context.get("printer_head_id"),
                "head_type_id": context.get("head_type_id"),
                "target_pulse_width_us": _int_or_none(target_pulse_width_us),
                "target_volume_nl": _float_or_none(target_volume_nl),
            }
            prior["advisory_only"] = True
            prior["applied"] = False
            return prior

        return None
