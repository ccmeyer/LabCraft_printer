import pandas as pd
import numpy as np

from dataclasses import dataclass, field
from math import gcd
from functools import reduce
from typing import List, Dict, Tuple, Optional, Any, Set

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
from PySide6.QtStateMachine import QStateMachine, QState, QFinalState, QSignalTransition
import json
import tempfile
import heapq
import os
import csv
import cv2
import itertools
from itertools import combinations_with_replacement, product
import joblib
from scipy.optimize import minimize, fsolve
from scipy.signal import find_peaks
from skimage.metrics import structural_similarity as ssim

import random
import pyDOE3
import time
from datetime import datetime, timezone
import glob
import shutil
import csv
import math
import re
import matplotlib.pyplot as plt
from enum import Enum
import CalibrationClasses
import importlib
from CalibrationMemoryStore import CalibrationMemoryStore

from hardware.profile import CURRENT_PROFILE, HardwareProfile

def find_key_points(columns, line_values):
    """
    Identifies two low points and the high point between them in the data.

    Args:
        columns (np.array): The column indices (x-axis values).
        line_values (np.array): The pixel sum values (y-axis values).

    Returns:
        tuple: (low1_index, high_index, low2_index)
            Indices of the first low point, the high point, and the second low point.
    """
    # Negate the line_values to find minima using find_peaks
    inverted_values = -line_values
    low_points_indices = find_peaks(inverted_values)[0]  # Indices of local minima

    # Find the first two minima (low points)
    if len(low_points_indices) < 2:
        # ValueError("Not enough local minima found to identify two low points.")
        return None,None,None

    low1_index = low_points_indices[0]
    low2_index = low_points_indices[1]

    # Ensure the first low point comes before the second
    if low1_index > low2_index:
        low1_index, low2_index = low2_index, low1_index

    # Find the local maximum (high point) between the two low points
    high_point_indices = find_peaks(line_values)[0]  # Indices of local maxima
    high_index = None

    for idx in high_point_indices:
        if low1_index < idx < low2_index:
            high_index = idx
            break

    if high_index is None:
        raise ValueError("No local maximum found between the two low points.")

    return low1_index, high_index, low2_index
    
def find_low_point(rows,row_values):
    inverted_values = -row_values
    all_peaks = find_peaks(inverted_values)
    if len(all_peaks) > 0:
        if len(all_peaks[0]) > 0:
            lowest_point = all_peaks[0][0]
        else:
            lowest_point = None
    else:
        lowest_point = None
    return lowest_point
    
def calculate_rate_of_change(x, y):
    """
    Calculates the rate of change (first derivative) of y with respect to x.

    Args:
        x (np.array): Array of x values.
        y (np.array): Array of y values.

    Returns:
        np.array: Rate of change values.
        np.array: Midpoint x values where rate of change is calculated.
    """
    rate_of_change = np.diff(y) / np.diff(x)  # First derivative
    mid_x = (x[:-1] + x[1:]) / 2  # Midpoints between consecutive x values
    return rate_of_change

def find_largest_prominent_peak(rate_of_change):
    """
    Finds the largest peak based on prominence or width in the rate of change.

    Args:
        rate_of_change (np.array): Array of rate of change values.

    Returns:
        int: Index of the largest prominent peak.
    """
    peaks, _ = find_peaks(np.abs(rate_of_change))  # Find peaks of absolute rate of change
    if len(peaks) == 0:
        #raise ValueError("No peaks found in rate of change.")
        return None
    largest_peak_index = peaks[np.argmax(np.abs(rate_of_change[peaks]))]

    return largest_peak_index

# --------------------------
# Data structures
# --------------------------

@dataclass
class OptionSpec:
    name: str
    targets: List[float]           # desired final concentrations for this option
    units: str                     # e.g. 'mM'
    droplet_nL: float              # droplet volume for this reagent
    starting_conc: float = 0.0     # starting concentration for this reagent
    reagent_id: str | None = None
    reagent_display_name: str | None = None
    intended_head_type_id: str | None = None
    intended_head_type_display_name: str | None = None


@dataclass
class FactorSpec:
    name: str                      # factor/group name
    kind: str                      # 'additive' or 'choice'
    options: List[OptionSpec] = field(default_factory=list)


# --------------------------
# Numeric helpers (grid-based)
# --------------------------

def _quantize(x: float, q: float) -> float:
    return round(x / q) * q

def _gcd_float(values: List[float], quantum: float) -> float:
    """GCD for floats on a quantum grid. Returns k * quantum."""
    ints = [int(round(abs(v) / quantum)) for v in values if abs(v) > 0]
    if not ints:
        return quantum
    g = 0
    for n in ints:
        g = math.gcd(g, n)
    return max(g, 1) * quantum

def _base_step_for_targets(targets: List[float], quantum: float) -> float:
    """
    Smallest delta that can be used by a single stock to reach ALL targets
    as integer multiples from zero. This is the GCD over the targets
    themselves on the quantum grid (zeros are ignored).
    """
    xs = sorted(set(_quantize(t, quantum) for t in targets))
    # integers on the quantum grid
    ints = [int(round(abs(x) / quantum)) for x in xs if abs(x) > 0]
    if not ints:
        return quantum
    g = 0
    for n in ints:
        g = math.gcd(g, n)
    return max(g, 1) * quantum

def _is_multiple_of(delta: float, t: float, tol: float = 1e-9) -> bool:
    if delta <= 0:
        return False
    k = t / delta
    return abs(k - round(k)) <= tol

def _int_ratio(delta: float, t: float) -> int:
    return int(round(t / delta))


# --------------------------
# Plan containers
# --------------------------

@dataclass
class SingleStockPlan:
    delta_per_drop: float
    stock_concentration: float      # final stock conc chosen
    droplet_nL: float
    units: str
    droplets_per_target: Dict[float, int]    # target -> drops
    max_volume_nL: float             # worst-case (drops*drop_nL)
    n_stocks: int = 1

@dataclass
class TwoStockPlan:
    deltas: Tuple[float, float]               # (delta1, delta2)
    stock_concs: Tuple[float, float]          # (c1, c2)
    droplet_nL: float
    units: str
    droplets_per_target: Dict[float, Tuple[int, int]]  # target -> (a,b)
    max_volume_nL: float
    conc_sum: float
    n_stocks: int = 2


# --------------------------
# Experiment Model (v2)
# --------------------------

class ExperimentModel(QObject):
    # Signals to mirror the classic API
    stock_updated = Signal()
    experiment_generated = Signal(int, float)  # (n_reactions, worst_nonfill_volume_nL)
    targets_unreachable = Signal(object)  # list[dict]

    def __init__(self, prof=None):
        super().__init__()
        # Factors (additive & choice groups)
        self.factors: List[FactorSpec] = []

        self.legacy_mode = prof.name == "legacy" if prof else True


        # Metadata
        # Format date-time for metadata
        temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")

        if self.legacy_mode:
            fill_droplet_volume_nL = 40.0
        else:
            fill_droplet_volume_nL = 10.0
            
        self.metadata: Dict = {
            "name": temp_name,
            "replicates": 1,
            "use_subset_design": False,
            "reduction_factor": 1,  # reserved; current generate is full factorial
            "target_reaction_volume_nL": 500.0, # PRINTED volume budget
            "final_reaction_volume_nL": 500.0, # includes non-printed (fill) volume
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": fill_droplet_volume_nL,
            "randomize_assignments": False,
            "random_seed": None,
            "start_row": 0,
            "start_col": 0, 
        }

        # Results of optimization
        # key for additives: (factor_name, None)
        # key for options in groups: (group_name, option_name)
        self.plans_per_option: Dict[Tuple[str, Optional[str]], Dict] = {}
        self._unreachable_preview_map: Dict[Tuple[str, Optional[str]], List[float]] = {}

        # Cached stock rows for the UI stock table
        self._stock_rows_cache: List[Dict] = []
        self._fill_row_cache: Optional[Dict] = None

        # Last computed grid
        self._reactions_df: pd.DataFrame = pd.DataFrame()
        self._last_worst_nonfill_volume_nL: Optional[float] = None

                # ---- paths & persistence ----
        self.experiment_dir_path: Optional[str] = None
        self.experiment_file_path: Optional[str] = None
        self.progress_file_path: Optional[str] = None
        self.key_file_path: Optional[str] = None
        self.concentration_key_file_path: Optional[str] = None
        self.calibration_file_path: Optional[str] = None
        self.progress_data: Dict[str, Dict] = {}
        self.unsaved_changes: bool = False

        # optional dependency (if you have one); safe to ignore if None
        self._calibration_manager = None

        # runtime context provided by Model for progress/key creation
        self._runtime_well_plate = None
        self._runtime_reaction_collection = None

        # --- uploaded design support ---
        # If not None: a list of dicts representing explicit reactions
        # keyed by (factor_name, None) -> final target conc.
        self._uploaded_reactions: list[dict[tuple[str, Optional[str]], float]] | None = None
        # Remember source file (optional, for UI / save)
        self._uploaded_design_source: str | None = None
        # optional explicit well assignment, one per uploaded reaction row
        self._uploaded_well_ids: list[Optional[str]] | None = None

    # ------------- Factor management -------------

    def add_additive(
        self,
        name: str,
        targets: List[float],
        units: str,
        droplet_nL: float,
        starting_conc: float = 0.0,
        forced_stock_conc: float | None = None,
        reagent_id: str | None = None,
        reagent_display_name: str | None = None,
        intended_head_type_id: str | None = None,
        intended_head_type_display_name: str | None = None,
    ):
        o = OptionSpec(name=f"{name}",
                    targets=list(targets), units=units,
                    droplet_nL=float(droplet_nL),
                    starting_conc=float(starting_conc or 0.0),
                    reagent_id=reagent_id,
                    reagent_display_name=reagent_display_name,
                    intended_head_type_id=intended_head_type_id,
                    intended_head_type_display_name=intended_head_type_display_name)
        if forced_stock_conc is not None:
            try:
                setattr(o, "forced_stock_conc", float(forced_stock_conc))
            except Exception:
                setattr(o, "forced_stock_conc", None)
        self.factors.append(FactorSpec(
            name=name, kind="additive", options=[o]
        ))

    def add_choice_group(self, group_name: str):
        self.factors.append(FactorSpec(name=group_name, kind="choice", options=[]))

    def add_choice_option(
        self,
        group_name: str,
        option_name: str,
        targets: List[float],
        units: str,
        droplet_nL: float,
        starting_conc: float = 0.0,
        forced_stock_conc: float | None = None,
        reagent_id: str | None = None,
        reagent_display_name: str | None = None,
        intended_head_type_id: str | None = None,
        intended_head_type_display_name: str | None = None,
    ):
        for f in self.factors:
            if f.name == group_name and f.kind == "choice":
                o = OptionSpec(option_name, list(targets), units,
                            float(droplet_nL), float(starting_conc or 0.0),
                            reagent_id=reagent_id,
                            reagent_display_name=reagent_display_name,
                            intended_head_type_id=intended_head_type_id,
                            intended_head_type_display_name=intended_head_type_display_name)
                if forced_stock_conc is not None:
                    try:
                        setattr(o, "forced_stock_conc", float(forced_stock_conc))
                    except Exception:
                        setattr(o, "forced_stock_conc", None)
                f.options.append(o)
                return
        self.add_choice_group(group_name)
        self.add_choice_option(
            group_name,
            option_name,
            targets,
            units,
            droplet_nL,
            starting_conc,
            forced_stock_conc,
            reagent_id,
            reagent_display_name,
            intended_head_type_id,
            intended_head_type_display_name,
        )
    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)

    def _iter_factor_options(self):
        for factor in self.factors:
            for option in factor.options:
                yield factor, option

    def _get_option_spec_for_stock_row(self, factor_name: str, option_name: str | None):
        opt_name = (option_name or "").strip()
        for factor, option in self._iter_factor_options():
            if factor.name != factor_name:
                continue
            if factor.kind == "additive":
                return option
            if option.name == opt_name:
                return option
        return None

    def _build_stock_row(
        self,
        *,
        factor_name: str,
        option_name: str,
        stock_concentration: float,
        delta_per_drop: float,
        units: str,
        droplet_volume_nL: float,
    ) -> Dict[str, Any]:
        option = self._get_option_spec_for_stock_row(factor_name, option_name)
        row = {
            "factor_name": factor_name,
            "option_name": option_name,
            "stock_concentration": stock_concentration,
            "delta_per_drop": delta_per_drop,
            "units": units,
            "droplet_volume_nL": droplet_volume_nL,
            "reagent_id": getattr(option, "reagent_id", None) if option is not None else None,
            "reagent_display_name": getattr(option, "reagent_display_name", None) if option is not None else None,
            "intended_head_type_id": getattr(option, "intended_head_type_id", None) if option is not None else None,
            "intended_head_type_display_name": getattr(option, "intended_head_type_display_name", None) if option is not None else None,
        }
        return row

    def get_random_seed(self) -> Optional[int]:
        """Only return a seed when randomization is enabled."""
        return self.metadata.get("random_seed", None) if self.metadata.get("randomize_assignments", False) else None

    def get_start_row(self) -> int:
        return int(self.metadata.get("start_row", 0))

    def get_start_col(self) -> int:
        return int(self.metadata.get("start_col", 0))

    # ------------- Candidate builders -------------

    def _enumerate_single_stock_candidates(
        self,
        targets: List[float],
        droplet_nL: float,
        units: str,
        *,
        final_volume_nL: float,
        quantum: float = 0.1,
        max_refine: int = 50,
        min_delta: float = 1e-6
    ) -> List[SingleStockPlan]:
        xs = sorted(set(_quantize(t, quantum) for t in targets))
        base = _base_step_for_targets(xs, quantum)
        cands: List[SingleStockPlan] = []
        for m in range(1, max_refine + 1):
            delta = base / m
            if delta < min_delta:
                break
            if any(not _is_multiple_of(delta, t, tol=1e-9) for t in xs):
                continue
            drops = {t: _int_ratio(delta, t) for t in xs}
            max_vol = max(d * droplet_nL for d in drops.values()) if drops else 0.0
            stock_c = (delta * final_volume_nL) / droplet_nL
            cands.append(SingleStockPlan(
                delta_per_drop=delta,
                stock_concentration=stock_c,
                droplet_nL=droplet_nL,
                units=units,
                droplets_per_target=drops,
                max_volume_nL=max_vol,
                n_stocks=1
            ))
        # Lowest concentration first (smallest delta)
        cands.sort(key=lambda p: (p.stock_concentration, p.max_volume_nL))
        return cands

    def _enumerate_two_stock_candidates(
        self,
        targets: List[float],
        droplet_nL: float,
        units: str,
        *,
        final_volume_nL: float,
        volume_budget_nL: float,
        quantum: float = 0.1,
        max_refine: int = 30,
        kmax_multiples: int = 12,
        max_pairs: int = 300
    ) -> List[TwoStockPlan]:
        """
        Enumerate feasible 2-stock pairs. We consider a broad set of deltas:
        - fractions of the base (base / m)
        - multiples of the base (k * base), k=1..kmax_multiples
        - per-target divisors t / k up to a hard drop cap

        Then solve two-coin change on the integer grid (quantum) and
        keep non-dominated pairs by (conc_sum, max_volume_nL).
        """
        xs = sorted(set(_quantize(t, quantum) for t in targets))
        if not xs:
            return []

        base = _base_step_for_targets(xs, quantum)

        # Cap on drops if this reagent alone filled the volume.
        max_drops_cap = max(1, int(math.floor(volume_budget_nL / max(droplet_nL, 1e-9))))

        # Build delta set on the quantum grid
        delta_set: Set[float] = set()

        # (a) Fractions of base
        for m in range(1, max_refine + 1):
            d = _quantize(base / m, quantum)
            if d > 0:
                delta_set.add(d)

        # (b) Multiples of base
        for k in range(1, kmax_multiples + 1):
            d = _quantize(base * k, quantum)
            if d > 0:
                delta_set.add(d)

        # (c) Per-target divisors
        for t in xs:
            if t <= 0:
                continue
            for k in range(1, max_drops_cap + 1):
                d = _quantize(t / k, quantum)
                if d > 0:
                    delta_set.add(d)

        deltas = sorted(delta_set)
        if not deltas:
            return []

        # Integerize
        s = int(round(1.0 / quantum))
        int_targets = [int(round(t * s)) for t in xs]
        int_deltas = [int(round(d * s)) for d in deltas]

        pairs: List[TwoStockPlan] = []

        for i in range(len(int_deltas)):
            for j in range(i + 1, len(int_deltas)):
                di, dj = int_deltas[i], int_deltas[j]
                if di <= 0 or dj <= 0:
                    continue

                # gcd feasibility: each target must be multiple of gcd(di, dj)
                g = math.gcd(di, dj)
                if any((t % g) != 0 for t in int_targets):
                    continue

                # Two-coin change per target: minimize a+b
                drops_map: Dict[float, Tuple[int, int]] = {}
                max_drops = 0
                feasible = True
                for t_int, t_real in zip(int_targets, xs):
                    best_ab = None
                    a_max = t_int // di
                    for a in range(a_max + 1):
                        rem = t_int - a * di
                        if rem < 0:
                            break
                        if rem % dj == 0:
                            b = rem // dj
                            if best_ab is None or (a + b) < (best_ab[0] + best_ab[1]):
                                best_ab = (a, b)
                    if best_ab is None:
                        feasible = False
                        break
                    drops_map[t_real] = best_ab
                    max_drops = max(max_drops, best_ab[0] + best_ab[1])

                if not feasible:
                    continue

                # ---- NEW: skip degenerate pairs (one stock never used across all targets)
                all_a_zero = all(ab[0] == 0 for ab in drops_map.values())
                all_b_zero = all(ab[1] == 0 for ab in drops_map.values())
                if all_a_zero or all_b_zero:
                    continue
                # ---- end NEW

                d1 = deltas[i]
                d2 = deltas[j]
                c1 = (d1 * final_volume_nL) / droplet_nL
                c2 = (d2 * final_volume_nL) / droplet_nL
                conc_sum = c1 + c2
                max_vol = max_drops * droplet_nL

                pairs.append(TwoStockPlan(
                    deltas=(d1, d2),
                    stock_concs=(c1, c2),
                    droplet_nL=droplet_nL,
                    units=units,
                    droplets_per_target=drops_map,
                    max_volume_nL=max_vol,
                    conc_sum=conc_sum,
                    n_stocks=2
                ))

        if not pairs:
            return []

        # Pareto-prune by (conc_sum, max_volume_nL)
        pairs.sort(key=lambda p: (p.conc_sum, p.max_volume_nL))
        pruned: List[TwoStockPlan] = []
        best_vol = float("inf")
        for p in pairs:
            if p.max_volume_nL + 1e-12 < best_vol:
                pruned.append(p)
                best_vol = p.max_volume_nL

        return pruned[:max_pairs]

    # ------------- Optimization -------------

    def optimize_stock_solutions(
        self,
        *,
        quantum: float = 0.1,
        max_refine: int = 50,
        two_max_refine: int = 30,
        allow_two: bool = True
    ) -> Dict:

        def _adj_targets(opt) -> List[float]:
            s = float(getattr(opt, "starting_conc", 0.0) or 0.0)
            # clamp negatives if user set starting > some target
            return sorted(set(max(0.0, float(t) - s) for t in opt.targets))
        
        # V_print = how much volume we are allowed to PRINT (old meaning of target)
        V_print = float(self.metadata.get("target_reaction_volume_nL", 500.0))
        # V_final = the actual final well volume after prefill + printing
        V_final = float(self.metadata.get("final_reaction_volume_nL", V_print))

        # Safety: never allow printed budget to exceed final volume (quiet clamp)
        if V_print > V_final:
            V_print = V_final

        # Build candidate lists + handle forced stocks
        self._unreachable_preview_map = {}

        additives: List[Tuple[str, List[SingleStockPlan], List[TwoStockPlan]]] = []
        choice_groups: Dict[str, List[Tuple[str, List[SingleStockPlan], List[TwoStockPlan]]]] = {}

        def _adj_targets_for_opt(opt) -> List[float]:
            s = float(getattr(opt, "starting_conc", 0.0) or 0.0)
            return sorted(set(max(0.0, float(t) - s) for t in opt.targets))

        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                t_adj = _adj_targets_for_opt(o)
                forced = getattr(o, "forced_stock_conc", None)
                if forced is not None and forced > 0:
                    # Forced single stock plan
                    dv = float(o.droplet_nL)
                    delta = (float(forced) * dv) / V_final if V_final > 0 else 0.0
                    dp: Dict[float, int] = {}
                    unreachable_final: List[float] = []
                    # Build mapping strictly for integer multiples of delta (on the quantum grid)
                    for t_final in o.targets:
                        t_add = max(0.0, float(t_final) - float(getattr(o, "starting_conc", 0.0) or 0.0))
                        t_add_q = _quantize(t_add, quantum)
                        if delta > 0 and _is_multiple_of(delta, t_add_q, tol=1e-9):
                            k = _int_ratio(delta, t_add_q)
                            dp[t_add_q] = int(k)
                        else:
                            # zero is always reachable as 0 drops
                            if t_add_q > 0:
                                unreachable_final.append(float(t_final))
                    # Record preview
                    if unreachable_final:
                        self._unreachable_preview_map[(f.name, None)] = unreachable_final

                    max_vol = max((k * dv for k in dp.values()), default=0.0)
                    singles = [SingleStockPlan(
                        delta_per_drop=delta,
                        stock_concentration=float(forced),
                        droplet_nL=dv,
                        units=o.units,
                        droplets_per_target=dp,
                        max_volume_nL=max_vol,
                        n_stocks=1
                    )]
                    additives.append((f.name, singles, []))  # no two-stock for forced
                else:
                    # Normal enumeration path
                    singles = self._enumerate_single_stock_candidates(
                        t_adj, o.droplet_nL, o.units,
                        final_volume_nL=V_final, quantum=quantum, max_refine=max_refine
                    )
                    twos = self._enumerate_two_stock_candidates(
                        t_adj, o.droplet_nL, o.units,
                        final_volume_nL=V_final, volume_budget_nL=V_print,
                        quantum=quantum, max_refine=two_max_refine
                    ) if allow_two else []
                    if not singles and not twos:
                        return {"best": None, "reason": f"No feasible plan (single or two-stock) for additive '{f.name}'."}
                    additives.append((f.name, singles, twos))
            else:
                bucket = []
                for opt in f.options:
                    t_adj = _adj_targets_for_opt(opt)
                    forced = getattr(opt, "forced_stock_conc", None)
                    if forced is not None and forced > 0:
                        dv = float(opt.droplet_nL)
                        delta = (float(forced) * dv) / V_final if V_final > 0 else 0.0
                        dp: Dict[float, int] = {}
                        unreachable_final: List[float] = []
                        for t_final in opt.targets:
                            t_add = max(0.0, float(t_final) - float(getattr(opt, "starting_conc", 0.0) or 0.0))
                            t_add_q = _quantize(t_add, quantum)
                            if delta > 0 and _is_multiple_of(delta, t_add_q, tol=1e-9):
                                k = _int_ratio(delta, t_add_q)
                                dp[t_add_q] = int(k)
                            else:
                                if t_add_q > 0:
                                    unreachable_final.append(float(t_final))
                        if unreachable_final:
                            self._unreachable_preview_map[(f.name, opt.name)] = unreachable_final

                        max_vol = max((k * dv for k in dp.values()), default=0.0)
                        singles = [SingleStockPlan(
                            delta_per_drop=delta,
                            stock_concentration=float(forced),
                            droplet_nL=dv,
                            units=opt.units,
                            droplets_per_target=dp,
                            max_volume_nL=max_vol,
                            n_stocks=1
                        )]
                        bucket.append((opt.name, singles, []))
                    else:
                        singles = self._enumerate_single_stock_candidates(
                            t_adj, opt.droplet_nL, opt.units,
                            final_volume_nL=V_final, quantum=quantum, max_refine=max_refine
                        )
                        twos = self._enumerate_two_stock_candidates(
                            t_adj, opt.droplet_nL, opt.units,
                            final_volume_nL=V_final, volume_budget_nL=V_print,
                            quantum=quantum, max_refine=two_max_refine
                        ) if allow_two else []
                        if not singles and not twos:
                            return {"best": None, "reason": f"No feasible plan (single or two-stock) for option '{f.name}/{opt.name}'."}
                        bucket.append((opt.name, singles, twos))
                choice_groups[f.name] = bucket

        # Selection indices (single-stock arrays)
        add_idx = {name: 0 for name, singles, _ in additives if singles}
        ch_idx: Dict[Tuple[str, str], int] = {}
        for gname, bucket in choice_groups.items():
            for oname, singles, _ in bucket:
                if singles:
                    ch_idx[(gname, oname)] = 0

        # Two-stock selections (index into twos), None means single-stock
        add_two_idx: Dict[str, Optional[int]] = {}
        for name, singles, twos in additives:
            add_two_idx[name] = 0 if (not singles and twos) else None

        ch_two_idx: Dict[Tuple[str, str], Optional[int]] = {}
        for gname, bucket in choice_groups.items():
            for oname, singles, twos in bucket:
                ch_two_idx[(gname, oname)] = 0 if (not singles and twos) else None

        # Helpers
        def selection_counts() -> Tuple[int, float]:
            tot_stocks = 0
            sum_conc = 0.0
            for name, singles, twos in additives:
                if add_two_idx[name] is not None:
                    p2 = twos[add_two_idx[name]]
                    tot_stocks += 2
                    sum_conc += p2.conc_sum
                else:
                    p1 = singles[add_idx[name]]
                    tot_stocks += 1
                    sum_conc += p1.stock_concentration
            for gname, bucket in choice_groups.items():
                for oname, singles, twos in bucket:
                    if ch_two_idx[(gname, oname)] is not None:
                        p2 = twos[ch_two_idx[(gname, oname)]]
                        tot_stocks += 2
                        sum_conc += p2.conc_sum
                    else:
                        p1 = singles[ch_idx[(gname, oname)]]
                        tot_stocks += 1
                        sum_conc += p1.stock_concentration
            return tot_stocks, sum_conc

        def worst_case_nonfill_volume() -> float:
            total = 0.0
            for name, singles, twos in additives:
                total += (twos[add_two_idx[name]].max_volume_nL
                        if add_two_idx[name] is not None
                        else singles[add_idx[name]].max_volume_nL)
            for gname, bucket in choice_groups.items():
                m = 0.0
                for oname, singles, twos in bucket:
                    v = (twos[ch_two_idx[(gname, oname)]].max_volume_nL
                        if ch_two_idx[(gname, oname)] is not None
                        else singles[ch_idx[(gname, oname)]].max_volume_nL)
                    if v > m:
                        m = v
                total += m
            return total

        # ---- NEW: tie-aware, look-ahead bump for choice options ----
        def bump_gain_opt(gname: str, oname: str) -> Tuple[float, float]:
            """
            Returns (effective_volume_reduction, effective_conc_increase).

            Cases:
            1) Not at group max => no immediate reduction (0, Δconc_next).
            2) Unique argmax and next step goes below others_max => true drop.
            3) Tied at group max:
            - If next step crosses below others => true drop.
            - Else use a proxy gain: (local_drop / tie_count, Δconc_next),
                so ties get "shared" credit and the loop will invest here.
            4) Unique argmax but next step not enough => look ahead to first
            k where volume < others_max and charge total Δconc to get there.
            """
            bucket = choice_groups[gname]

            # current volumes for each option
            vols: List[Tuple[str, float]] = []
            for n, singles, twos in bucket:
                v = (twos[ch_two_idx[(gname, n)]].max_volume_nL
                    if ch_two_idx[(gname, n)] is not None
                    else singles[ch_idx[(gname, n)]].max_volume_nL)
                vols.append((n, v))

            cur_max = max(v for _, v in vols)
            tie_names = [n for n, v in vols if abs(v - cur_max) <= 1e-9]
            tie_count = len(tie_names)
            others_max = max((v for n, v in vols if n != oname), default=0.0)

            # current & next single for this option
            singles_this = next(s for n, s, _ in bucket if n == oname)
            i = ch_idx[(gname, oname)]
            cur = singles_this[i]
            nxt = singles_this[i + 1] if (i + 1) < len(singles_this) else None
            if nxt is None:
                return (0.0, float("inf"))

            conc_inc_next = max(1e-12, nxt.stock_concentration - cur.stock_concentration)

            # Not at group max => can't reduce group max
            if cur.max_volume_nL < cur_max - 1e-9:
                return (0.0, conc_inc_next)

            # If the very next step produces an immediate drop of the group max
            new_max = max(others_max, nxt.max_volume_nL)
            if new_max < cur_max - 1e-12:
                return (cur_max - new_max, conc_inc_next)

            # If we are tied at the max and one step doesn't break the tie,
            # allocate a proxy "shared" gain to avoid starving the group.
            if oname in tie_names and tie_count > 1:
                local_drop = max(0.0, cur.max_volume_nL - nxt.max_volume_nL)
                if local_drop > 1e-12:
                    return (local_drop / tie_count, conc_inc_next)

                # If local_drop is (almost) zero, look a bit further ahead for a real drop,
                # still sharing by tie_count.
                k = i + 1
                while k < len(singles_this) and singles_this[k].max_volume_nL >= cur_max - 1e-9:
                    k += 1
                if k < len(singles_this):
                    ahead_drop = max(0.0, cur.max_volume_nL - singles_this[k].max_volume_nL)
                    total_conc = max(1e-12, singles_this[k].stock_concentration - cur.stock_concentration)
                    return (ahead_drop / tie_count, total_conc)

                # Can't make progress within available singles
                return (0.0, conc_inc_next)

            # Unique argmax but next step still above others_max: look ahead to first k < others_max
            k = i + 1
            while k < len(singles_this) and singles_this[k].max_volume_nL >= others_max - 1e-9:
                k += 1
            if k < len(singles_this):
                drop = max(0.0, cur_max - max(others_max, singles_this[k].max_volume_nL))
                total_conc = max(1e-12, singles_this[k].stock_concentration - cur.stock_concentration)
                return (drop, total_conc)

            return (0.0, conc_inc_next)
        # ------------------------------------------------------------

        # Single-stock bump helper for additives
        def bump_gain_add(name: str) -> Tuple[float, float]:
            singles = dict((n, s) for n, s, _ in additives)[name]
            i = add_idx[name]
            if i + 1 >= len(singles):
                return (0.0, float("inf"))
            cur = singles[i]
            nxt = singles[i + 1]
            return (max(0.0, cur.max_volume_nL - nxt.max_volume_nL),
                    max(1e-12, nxt.stock_concentration - cur.stock_concentration))

        def can_bump_add(name: str) -> bool:
            singles = dict((n, s) for n, s, _ in additives)[name]
            return add_two_idx[name] is None and (add_idx[name] + 1 < len(singles))

        def can_bump_opt(gname: str, oname: str) -> bool:
            if ch_two_idx[(gname, oname)] is not None:
                return False
            singles_this = None
            for g, bucket in choice_groups.items():
                if g == gname:
                    for n, s, _ in bucket:
                        if n == oname:
                            singles_this = s
                            break
            return singles_this is not None and (ch_idx[(gname, oname)] + 1 < len(singles_this))

        # -----------------------------
        # Step 1: single-stock only
        # -----------------------------
        while True:
            worst = worst_case_nonfill_volume()
            if worst <= V_print + 1e-6:
                break

            best_ratio = 0.0
            best_next_conc = float("inf")  # tie-breaker: prefer smaller resulting conc
            best_key = None
            best_kind = None

            # Additives
            for name, singles, _ in additives:
                if not can_bump_add(name):
                    continue
                vol_red, conc_inc = bump_gain_add(name)
                ratio = vol_red / conc_inc if conc_inc > 0 else 0.0
                next_conc = singles[add_idx[name] + 1].stock_concentration
                if (ratio > best_ratio + 1e-12) or (abs(ratio - best_ratio) <= 1e-12 and next_conc < best_next_conc - 1e-12):
                    best_ratio = ratio
                    best_next_conc = next_conc
                    best_key = name
                    best_kind = "add"

            # Choice options (tie-aware)
            for gname, bucket in choice_groups.items():
                for oname, singles, _ in bucket:
                    if not can_bump_opt(gname, oname):
                        continue
                    vol_red_eff, conc_eff = bump_gain_opt(gname, oname)
                    ratio = vol_red_eff / conc_eff if conc_eff > 0 else 0.0
                    next_conc = singles[ch_idx[(gname, oname)] + 1].stock_concentration
                    if (ratio > best_ratio + 1e-12) or (abs(ratio - best_ratio) <= 1e-12 and next_conc < best_next_conc - 1e-12):
                        best_ratio = ratio
                        best_next_conc = next_conc
                        best_key = (gname, oname)
                        best_kind = "opt"

            if best_key is None:
                break
            if best_kind == "add":
                add_idx[best_key] += 1
            else:
                g, o = best_key
                ch_idx[(g, o)] += 1

        # -----------------------------
        # Step 2: two-stock switches
        # -----------------------------
        if worst_case_nonfill_volume() > V_print + 1e-6 and allow_two:
            while True:
                worst = worst_case_nonfill_volume()
                if worst <= V_print + 1e-6:
                    break

                best_gain = 0.0
                best_penalty = float("inf")
                best_switch = None  # ("add", name, idx2) or ("opt", g, o, idx2)

                # Additives
                for name, singles, twos in additives:
                    if not twos:
                        continue
                    cur_v = singles[add_idx[name]].max_volume_nL if add_two_idx[name] is None else twos[add_two_idx[name]].max_volume_nL
                    for i2, p2 in enumerate(twos):
                        if add_two_idx[name] is not None and add_two_idx[name] == i2:
                            continue
                        vol_red_local = max(0.0, cur_v - p2.max_volume_nL)
                        if vol_red_local <= 1e-9:
                            continue
                        penalty = p2.conc_sum - (singles[add_idx[name]].stock_concentration if add_two_idx[name] is None else twos[add_two_idx[name]].conc_sum)
                        if (vol_red_local > best_gain + 1e-9) or (abs(vol_red_local - best_gain) <= 1e-9 and penalty < best_penalty):
                            best_gain = vol_red_local
                            best_penalty = penalty
                            best_switch = ("add", name, i2)

                # Choice groups (+ tie-break same as before)
                tie_switch = None
                best_tie_gain = 0.0
                best_tie_penalty = float("inf")
                for gname, bucket in choice_groups.items():
                    vols = []
                    for oname, singles, twos in bucket:
                        v = twos[ch_two_idx[(gname, oname)]].max_volume_nL if ch_two_idx[(gname, oname)] is not None else singles[ch_idx[(gname, oname)]].max_volume_nL
                        vols.append((oname, v))
                    cur_group_max = max(v for _, v in vols)
                    tie_count = sum(1 for _, v in vols if abs(v - cur_group_max) <= 1e-9)
                    others_max = {oname: (max(x for n, x in vols if n != oname) if len(vols) > 1 else 0.0) for oname, _ in vols}

                    for oname, singles, twos in bucket:
                        if not twos:
                            continue
                        cur_v = twos[ch_two_idx[(gname, oname)]].max_volume_nL if ch_two_idx[(gname, oname)] is not None else singles[ch_idx[(gname, oname)]].max_volume_nL
                        is_argmax = abs(cur_v - cur_group_max) <= 1e-9

                        for i2, p2 in enumerate(twos):
                            if ch_two_idx[(gname, oname)] is not None and ch_two_idx[(gname, oname)] == i2:
                                continue
                            new_group_max = max(others_max[oname], p2.max_volume_nL) if is_argmax else cur_group_max
                            vol_red_local = max(0.0, cur_group_max - new_group_max)
                            penalty = p2.conc_sum - (twos[ch_two_idx[(gname, oname)]].conc_sum if ch_two_idx[(gname, oname)] is not None else singles[ch_idx[(gname, oname)]].stock_concentration)

                            if (vol_red_local > best_gain + 1e-9) or (abs(vol_red_local - best_gain) <= 1e-9 and penalty < best_penalty):
                                best_gain = vol_red_local
                                best_penalty = penalty
                                best_switch = ("opt", gname, oname, i2)

                            if tie_count > 1 and is_argmax:
                                local_drop = max(0.0, cur_v - p2.max_volume_nL)
                                if (local_drop > best_tie_gain + 1e-9) or (abs(local_drop - best_tie_gain) <= 1e-9 and penalty < best_tie_penalty):
                                    best_tie_gain = local_drop
                                    best_tie_penalty = penalty
                                    tie_switch = ("opt", gname, oname, i2)

                if best_switch is None and tie_switch is not None:
                    best_switch = tie_switch
                if best_switch is None:
                    return {"best": None, "reason": "Volume budget too tight even after two-stock exploration."}

                if best_switch[0] == "add":
                    _, name, i2 = best_switch
                    add_two_idx[name] = i2
                else:
                    _, g, o, i2 = best_switch
                    ch_two_idx[(g, o)] = i2

                if worst_case_nonfill_volume() <= V_print + 1e-6:
                    break

        # -----------------------------
        # De-escalate two-stocks & cool-down (unchanged)
        # -----------------------------
        def current_worst() -> float:
            return worst_case_nonfill_volume()

        def is_two_plan_degenerate(p2: TwoStockPlan) -> bool:
            a_zero = all(ab[0] == 0 for ab in p2.droplets_per_target.values())
            b_zero = all(ab[1] == 0 for ab in p2.droplets_per_target.values())
            return a_zero or b_zero

        # Additives
        for idx, (name, singles, twos) in enumerate(additives):
            if add_two_idx.get(name) is None:
                continue
            p2 = twos[add_two_idx[name]]
            if is_two_plan_degenerate(p2):
                use_leg = 0 if all(ab[1] == 0 for ab in p2.droplets_per_target.values()) else 1
                drops = {float(t): ab[use_leg] for t, ab in p2.droplets_per_target.items()}
                max_vol = max((k * p2.droplet_nL for k in drops.values()), default=0.0)
                fake_single = SingleStockPlan(
                    delta_per_drop=p2.deltas[use_leg],
                    stock_concentration=p2.stock_concs[use_leg],
                    droplet_nL=p2.droplet_nL,
                    units=p2.units,
                    droplets_per_target=drops,
                    max_volume_nL=max_vol,
                    n_stocks=1,
                )
                saved_two = add_two_idx[name]
                add_two_idx[name] = None
                singles = [fake_single] + singles
                add_idx[name] = 0
                if current_worst() > V_print + 1e-6:
                    add_two_idx[name] = saved_two
                else:
                    additives[idx] = (name, singles, twos)
                    continue

            saved_two = add_two_idx[name]
            best_i = None
            for i, p1 in enumerate(singles):
                add_two_idx[name] = None
                add_idx[name] = i
                if current_worst() <= V_print + 1e-6:
                    best_i = i
                    break
            if best_i is None:
                add_two_idx[name] = saved_two

        # Choice groups
        for gname, bucket in list(choice_groups.items()):
            new_bucket = []
            for oname, singles, twos in bucket:
                key = (gname, oname)
                if ch_two_idx.get(key) is None:
                    new_bucket.append((oname, singles, twos))
                    continue
                p2 = twos[ch_two_idx[key]]
                if is_two_plan_degenerate(p2):
                    use_leg = 0 if all(ab[1] == 0 for ab in p2.droplets_per_target.values()) else 1
                    drops = {float(t): ab[use_leg] for t, ab in p2.droplets_per_target.items()}
                    max_vol = max((k * p2.droplet_nL for k in drops.values()), default=0.0)
                    fake_single = SingleStockPlan(
                        delta_per_drop=p2.deltas[use_leg],
                        stock_concentration=p2.stock_concs[use_leg],
                        droplet_nL=p2.droplet_nL,
                        units=p2.units,
                        droplets_per_target=drops,
                        max_volume_nL=max_vol,
                        n_stocks=1,
                    )
                    saved_two = ch_two_idx[key]
                    ch_two_idx[key] = None
                    singles = [fake_single] + singles
                    ch_idx[key] = 0
                    if current_worst() > V_print + 1e-6:
                        ch_two_idx[key] = saved_two

                if ch_two_idx[key] is not None:
                    saved_two = ch_two_idx[key]
                    best_i = None
                    for i, p1 in enumerate(singles):
                        ch_two_idx[key] = None
                        ch_idx[key] = i
                        if current_worst() <= V_print + 1e-6:
                            best_i = i
                            break
                    if best_i is None:
                        ch_two_idx[key] = saved_two
                new_bucket.append((oname, singles, twos))
            choice_groups[gname] = new_bucket

        # Single-stock cool-down (unchanged)
        if worst_case_nonfill_volume() <= V_print + 1e-6:
            changed = True
            while changed:
                changed = False
                for name, singles, _ in additives:
                    if add_two_idx[name] is not None:
                        continue
                    i = add_idx[name]
                    while i > 0:
                        prev_i = i - 1
                        add_idx[name] = prev_i
                        if worst_case_nonfill_volume() <= V_print + 1e-6:
                            changed = True
                            i = prev_i
                        else:
                            add_idx[name] = i
                            break
                for gname, bucket in choice_groups.items():
                    for oname, singles, _ in bucket:
                        key = (gname, oname)
                        if ch_two_idx[key] is not None:
                            continue
                        i = ch_idx[key]
                        while i > 0:
                            prev_i = i - 1
                            ch_idx[key] = prev_i
                            if worst_case_nonfill_volume() <= V_print + 1e-6:
                                changed = True
                                i = prev_i
                            else:
                                ch_idx[key] = i
                                break

        # Materialize plans
        self.plans_per_option.clear()
        stock_rows = []

        for name, singles, twos in additives:
            if add_two_idx[name] is not None:
                p2 = twos[add_two_idx[name]]
                self.plans_per_option[(name, None)] = {
                    "n_stocks": 2,
                    "stocks": [
                        {
                            "delta_per_drop": p2.deltas[0],
                            "stock_concentration": p2.stock_concs[0],
                            "droplet_volume_nL": p2.droplet_nL,
                            "units": p2.units,
                            "droplets_per_target": {float(t): ab[0] for t, ab in p2.droplets_per_target.items()},
                            "quantum": quantum
                         },
                        {
                            "delta_per_drop": p2.deltas[1],
                            "stock_concentration": p2.stock_concs[1],
                            "droplet_volume_nL": p2.droplet_nL,
                            "units": p2.units,
                            "droplets_per_target": {float(t): ab[1] for t, ab in p2.droplets_per_target.items()},
                            "quantum": quantum
                        },
                    ]
                }
                stock_rows.append(self._build_stock_row(
                    factor_name=name,
                    option_name="",
                    stock_concentration=p2.stock_concs[0],
                    delta_per_drop=p2.deltas[0],
                    units=p2.units,
                    droplet_volume_nL=p2.droplet_nL,
                ))
                stock_rows.append(self._build_stock_row(
                    factor_name=name,
                    option_name="",
                    stock_concentration=p2.stock_concs[1],
                    delta_per_drop=p2.deltas[1],
                    units=p2.units,
                    droplet_volume_nL=p2.droplet_nL,
                ))
            else:
                p1 = singles[add_idx[name]]
                self.plans_per_option[(name, None)] = {
                    "n_stocks": 1,
                    "stocks": [
                        {
                            "delta_per_drop": p1.delta_per_drop, 
                            "stock_concentration": p1.stock_concentration,
                            "droplet_volume_nL": p1.droplet_nL,
                            "units": p1.units,
                            "droplets_per_target": {float(t): int(d) for t, d in p1.droplets_per_target.items()},
                            "quantum": quantum,
                        }
                    ]
                }
                stock_rows.append(self._build_stock_row(
                    factor_name=name,
                    option_name="",
                    stock_concentration=p1.stock_concentration,
                    delta_per_drop=p1.delta_per_drop,
                    units=p1.units,
                    droplet_volume_nL=p1.droplet_nL,
                ))

        for gname, bucket in choice_groups.items():
            for oname, singles, twos in bucket:
                key = (gname, oname)
                if ch_two_idx[key] is not None:
                    p2 = twos[ch_two_idx[key]]
                    self.plans_per_option[key] = {
                        "n_stocks": 2,
                        "stocks": [
                            {
                                "delta_per_drop": p2.deltas[0],
                                "stock_concentration": p2.stock_concs[0],
                                "droplet_volume_nL": p2.droplet_nL,
                                "units": p2.units,
                                "droplets_per_target": {float(t): ab[0] for t, ab in p2.droplets_per_target.items()},
                                "quantum": quantum
                            },
                            {
                                "delta_per_drop": p2.deltas[1],
                                "stock_concentration": p2.stock_concs[1],
                                "droplet_volume_nL": p2.droplet_nL,
                                "units": p2.units,
                                "droplets_per_target": {float(t): ab[1] for t, ab in p2.droplets_per_target.items()},
                                "quantum": quantum
                            },
                        ]
                    }
                    stock_rows.append(self._build_stock_row(
                        factor_name=gname,
                        option_name=oname,
                        stock_concentration=p2.stock_concs[0],
                        delta_per_drop=p2.deltas[0],
                        units=p2.units,
                        droplet_volume_nL=p2.droplet_nL,
                    ))
                    stock_rows.append(self._build_stock_row(
                        factor_name=gname,
                        option_name=oname,
                        stock_concentration=p2.stock_concs[1],
                        delta_per_drop=p2.deltas[1],
                        units=p2.units,
                        droplet_volume_nL=p2.droplet_nL,
                    ))
                else:
                    p1 = singles[ch_idx[key]]
                    self.plans_per_option[key] = {
                        "n_stocks": 1,
                        "stocks": [
                            {
                                "delta_per_drop": p1.delta_per_drop,
                                "stock_concentration": p1.stock_concentration,
                                "droplet_volume_nL": p1.droplet_nL,
                                "units": p1.units,
                                "droplets_per_target": {float(t): int(d) for t, d in p1.droplets_per_target.items()},
                                "quantum": quantum
                            },
                        ]
                    }
                    stock_rows.append(self._build_stock_row(
                        factor_name=gname,
                        option_name=oname,
                        stock_concentration=p1.stock_concentration,
                        delta_per_drop=p1.delta_per_drop,
                        units=p1.units,
                        droplet_volume_nL=p1.droplet_nL,
                    ))

        self._stock_rows_cache = stock_rows
        self._fill_row_cache = None
        self._last_worst_nonfill_volume_nL = worst_case_nonfill_volume()

        self.stock_updated.emit()
        return {
            "best": True,
            "stocks": selection_counts()[0],
            "sum_conc": selection_counts()[1],
            "worst_nonfill_nL": self._last_worst_nonfill_volume_nL
        }

    # ------------- Generation & summaries -------------

    def _enumerate_reactions(self) -> List[Dict]:
        """
        Build the list of reactions.
        - If use_subset_design + reduction>1: use pyDOE3.gsd() to generate a balanced
        generalized subset design over multi-level factors (additives + choice groups).
        - Else: fall back to the existing full-factorial enumeration.
        Returns a list of dicts mapping:
        (additive_name, None) -> target
        (group_name, option_name) -> target
        """

        # ---------- Uploaded design path ----------
        if self._uploaded_reactions is not None:
            # Each entry is already a mapping (factor_name, None) -> final target conc
            # just return a shallow copy to avoid accidental mutation.
            return [dict(r) for r in self._uploaded_reactions]

        # ---- Gather factors ----
        additives = [f for f in self.factors if f.kind == "additive"]
        choices   = [f for f in self.factors if f.kind == "choice"]

        use_gsd = bool(self.metadata.get("use_subset_design", False))
        reduction = int(self.metadata.get("reduction_factor", 1))
        print(f"[ExperimentModel] Enumerating reactions: use_gsd={use_gsd}, reduction={reduction}")

        # ---------- GSD path ----------
        if use_gsd and reduction > 1:
            try:
                from pyDOE3 import gsd  # pip install pyDOE3
                import numpy as np

                # Build a list of "factor descriptors"
                # For additives: levels = [target1, target2, ...]
                # For each choice group: levels = [(option_name, target), ...] across all options
                facs = []

                # Additives
                for f in additives:
                    opt = f.options[0]
                    levels = sorted(set(float(t) for t in opt.targets))
                    facs.append({
                        "kind": "additive",
                        "key":  (f.name, None),
                        "levels": levels,  # e.g., [0.0, 1.0, 2.0]
                    })

                # Choice groups
                for f in choices:
                    lvls = []
                    for opt in f.options:
                        for t in opt.targets:
                            lvls.append((opt.name, float(t)))
                    facs.append({
                        "kind": "choice",
                        "group": f.name,
                        "levels": lvls,    # e.g., [("A",0.0),("A",1.0),("B",0.0),...]
                    })

                level_counts = [len(fd["levels"]) for fd in facs]
                if not level_counts:   # No factors configured
                    return []

                # Use pyDOE3 to get a balanced subset of factor-level combinations
                # Returns an array of 0-based level indices per factor
                design = gsd(level_counts, reduction)   # e.g., shape (n_runs, n_factors)
                design = np.atleast_2d(design).astype(int)

                reactions: List[Dict] = []
                for row in design:
                    sel = {}
                    for fd, idx in zip(facs, row.tolist()):
                        if fd["kind"] == "additive":
                            t = fd["levels"][int(idx)]
                            sel[fd["key"]] = t
                        else:
                            oname, t = fd["levels"][int(idx)]
                            # one option per group by construction
                            sel[(fd["group"], oname)] = t
                    reactions.append(sel)

                return reactions

            except Exception as e:
                # Safety: fall back silently, but leave a breadcrumb in logs
                print(f"[ExperimentModel] GSD failed or unavailable; falling back to full factorial. Reason: {e}")

        # ---------- Full-factorial fallback (your original logic) ----------
        # (unchanged from your current implementation)
        additives_list = additives
        choices_list = choices

        # Cartesian for additives
        add_target_lists = []
        add_keys = []
        for f in additives_list:
            opt = f.options[0]
            add_target_lists.append(opt.targets)
            add_keys.append((f.name, None))

        add_combos = list(itertools.product(*add_target_lists)) if add_target_lists else [()]

        # For choices, each group contributes a sum over options (option, target) tuples
        choice_lists = []
        for f in choices_list:
            tuples = []  # ( (group, option), targets list )
            for opt in f.options:
                tuples.append(((f.name, opt.name), opt.targets))
            choice_lists.append(tuples)

        # Build per-group choice sets
        per_group_choices: List[List[Tuple[Tuple[str, str], float]]] = []
        for tuples in choice_lists:
            one_group = []
            for key, tlist in tuples:
                for t in tlist:
                    one_group.append((key, t))
            per_group_choices.append(one_group)

        reactions = []
        for add_selection in add_combos:
            if not per_group_choices:
                selections = {}
                for k, t in zip(add_keys, add_selection):
                    selections[k] = t
                reactions.append(selections)
            else:
                for picks in itertools.product(*per_group_choices):
                    selections = {}
                    for k, t in zip(add_keys, add_selection):
                        selections[k] = t
                    for (g, o), t in picks:
                        if not any(key[0] == g for key in selections.keys() if key[1] is not None):
                            selections[(g, o)] = t
                    reactions.append(selections)

        return reactions

    def _resolve_drops_for_target(self, st: dict, target: float):
        """
        Robustly resolve droplet count for 'target' using the per-stock mapping.
        Returns (drops: int, matched_key: float|None, unreachable: bool, nearest_key: float|None).
        """
        dp = st.get("droplets_per_target", {}) or {}
        if not dp:
            return 0, None, (abs(target) > 1e-12), None

        t_raw = float(target)
        # Exact fast path
        if t_raw in dp:
            return int(dp[t_raw]), t_raw, False, t_raw

        q = float(st.get("quantum", 0.1))
        # Snap to same grid used during optimization
        t_q = round(t_raw / q) * q
        # Normalize to avoid repr noise
        t_q = float(f"{t_q:.12g}")

        # Try direct with snapped value
        if t_q in dp:
            return int(dp[t_q]), t_q, False, t_q

        # Near-match within half-quantum (and small epsilon)
        half = q * 0.5 + 1e-12
        for k in dp.keys():
            if abs(k - t_raw) <= half or abs(k - t_q) <= 1e-12:
                return int(dp[k]), k, False, k

        # As a last resort, nearest key within tiny epsilon (float dust)
        nearest_key = min(dp.keys(), key=lambda k: abs(k - t_raw))
        if abs(nearest_key - t_raw) <= 1e-6:
            return int(dp[nearest_key]), nearest_key, False, nearest_key

        # Zero target is always "reachable" as 0 drops even if not stored explicitly
        if abs(t_raw) <= 1e-12:
            return 0, 0.0, False, 0.0

        # True unreachable for this stock's mapping
        return 0, None, True, nearest_key

    # -----------------------------
    # Uploaded design API
    # -----------------------------
    def has_uploaded_design(self) -> bool:
        return self._uploaded_reactions is not None

    def clear_uploaded_design(self):
        """Reset back to normal (factor-defined) design."""
        self._uploaded_reactions = None
        self._uploaded_design_source = None
        self._uploaded_well_ids = None

        # Keep factors; UI will rebuild them as usual.
        # Recompute plans/grid on next optimize/generate.
        self.plans_per_option.clear()
        self._stock_rows_cache.clear()
        self._fill_row_cache = None
        self._reactions_df = pd.DataFrame()
        self._last_worst_nonfill_volume_nL = None
        self.stock_updated.emit()

    def set_uploaded_design_from_dataframe(
        self,
        df: "pd.DataFrame",
        *,
        units_default: str = "",
        droplet_nL_default: float = 10.0,
        starting_conc_default: float = 0.0,
        source_path: str | None = None,
    ):
        """
        Interpret a wide DataFrame where each row is one reaction and each column
        is a reagent with embedded units in the header.

        Optionally, a column named something like "Well", "Well ID", "well_id", etc.
        can be present to explicitly pin reactions to wells (e.g., "A1", "B3", ...).

        Expected reagent column header format (flexible):

            <ReagentName> [<units>]

        Examples:
            "NaCl mM"
            "MgCl2 (mM)"
            "Buffer"
        """
        import re

        # Work on a copy so we don't mutate the caller's DataFrame
        df_in = df.copy()

        # -------- 0) Optional well-assignment column --------
        well_col = None
        for col in df_in.columns:
            name = str(col).strip().lower()
            if name in ("well", "well id", "well_id", "wellid", "well position", "well_position"):
                well_col = col
                break

        uploaded_well_ids: list[Optional[str]] | None = None
        if well_col is not None:
            wells_raw = df_in[well_col].tolist()
            uploaded_well_ids = []
            for v in wells_raw:
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    uploaded_well_ids.append(None)
                else:
                    s = str(v).strip()
                    uploaded_well_ids.append(s if s else None)

            # Drop the well column from the design matrix before parsing reagents
            df_in = df_in.drop(columns=[well_col])

            # If all entries are None/blank, treat as "no explicit assignments"
            if not any(w for w in uploaded_well_ids):
                uploaded_well_ids = None

        # Store (or clear) well assignments for this uploaded design
        self._uploaded_well_ids = uploaded_well_ids

        # -------- 1) Parse reagent columns → (name, units) --------
        col_specs: list[tuple[str, str, str]] = []   # (col_name, reagent_name, units)
        for col in df_in.columns:
            raw = str(col).strip()
            if not raw:
                continue

            units = units_default
            name = raw

            # Try parentheses first: "Name (units)"
            m = re.match(r"^(.*)\((.+)\)\s*$", raw)
            if m:
                name = m.group(1).strip()
                units = m.group(2).strip()
            else:
                # Fall back to last token heuristic: "Name units"
                parts = raw.split()
                if len(parts) > 1:
                    name = " ".join(parts[:-1]).strip()
                    units = parts[-1].strip()

            if not name:
                name = raw
            col_specs.append((col, name, units))

        # -------- 2) Build factors list from these reagent columns --------
        self.factors.clear()
        for _, reagent_name, units in col_specs:
            fac = FactorSpec(
                name=reagent_name,
                kind="additive",
                options=[
                    OptionSpec(
                        name=reagent_name,
                        targets=[],  # fill shortly
                        units=units or units_default or "arb",
                        droplet_nL=float(droplet_nL_default),
                        starting_conc=float(starting_conc_default),
                    )
                ],
            )
            self.factors.append(fac)

        # Map reagent_name -> OptionSpec to fill targets
        opt_by_name: dict[str, OptionSpec] = {}
        for f in self.factors:
            if f.kind == "additive" and f.options:
                opt_by_name[f.name] = f.options[0]

        # -------- 3) Pre-collect column values as floats --------
        col_values: dict[str, list[float]] = {}
        for col_name, reagent_name, _units in col_specs:
            vals: list[float] = []
            for v in df_in[col_name].tolist():
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    vals.append(0.0)
                else:
                    try:
                        vals.append(float(v))
                    except Exception:
                        vals.append(0.0)
            col_values[reagent_name] = vals

        n_rows = len(df_in.index)

        # Fill targets list with unique values per reagent (final concentrations)
        for reagent_name, vals in col_values.items():
            opt = opt_by_name.get(reagent_name)
            if not opt:
                continue
            uniq = sorted(set(float(v) for v in vals))
            opt.targets = uniq

        # -------- 4) Build per-row reactions --------
        uploaded_reactions: list[dict[tuple[str, Optional[str]], float]] = []

        for i in range(n_rows):
            rxn: dict[tuple[str, Optional[str]], float] = {}
            for reagent_name, vals in col_values.items():
                v = float(vals[i]) if i < len(vals) else 0.0
                key = (reagent_name, None)  # additive style
                rxn[key] = v
            uploaded_reactions.append(rxn)

        # -------- 5) Store uploaded design state and clear caches --------
        self._uploaded_reactions = uploaded_reactions
        self._uploaded_design_source = source_path

        self.plans_per_option.clear()
        self._stock_rows_cache.clear()
        self._fill_row_cache = None
        self._reactions_df = pd.DataFrame()
        self._last_worst_nonfill_volume_nL = None
        self.stock_updated.emit()
    
    def has_explicit_well_assignments(self) -> bool:
        """
        True if the uploaded design included a well column with at least one
        non-empty entry.
        """
        return bool(self._uploaded_well_ids and any(w is not None for w in self._uploaded_well_ids))

    def get_explicit_well_assignments(self) -> list[Optional[str]] | None:
        """
        Returns a shallow copy of the uploaded well IDs, one per base reaction
        (before replicates), or None if no explicit well mapping exists.
        """
        if not self.has_explicit_well_assignments():
            return None
        return list(self._uploaded_well_ids)

    def generate_experiment(self):
        """Enumerate the reaction space, compute droplet counts per stock, fill volumes,
        and aggregate totals. Emits experiment_generated(n, worst_nonfill_nL)."""
        V = float(self.metadata.get("target_reaction_volume_nL", 500.0))
        fill_dv = float(self.metadata.get("fill_droplet_volume_nL", 10.0))
        reps = int(self.metadata.get("replicates", 1))

        reactions = self._enumerate_reactions()
        if not reactions:
            self._reactions_df = pd.DataFrame()
            self._last_worst_nonfill_volume_nL = 0.0
            self.experiment_generated.emit(0, 0.0)
            return

        rows = []
        issues = []
        worst_nonfill = 0.0

        # Map (factor, option_or_None) -> starting_conc and units
        start_lookup: Dict[Tuple[str, Optional[str]], Tuple[float, str]] = {}
        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                start_lookup[(f.name, None)] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)
            else:
                for o in f.options:
                    start_lookup[(f.name, o.name)] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)

        # Per-stock totals and per-reaction maxima
        # key: (factor, option_or_empty, stock_conc)
        stock_totals: Dict[Tuple[str, str, float], int] = {}
        stock_max_per_rxn_drops: Dict[Tuple[str, str, float], int] = {}
        stock_drop_vol_nL: Dict[Tuple[str, str, float], float] = {}  # remember droplet nL per stock
        fill_total_drops = 0

        for rxn in reactions:
            used_nL = 0.0

            # per reaction, per stock droplet usage (to compute per-reaction maxima)
            per_rxn_drops: Dict[Tuple[str, str, float], int] = {}

            for key, target in rxn.items():
                plan = self.plans_per_option.get(key)
                if plan is None:
                    continue

                n_stocks = plan["n_stocks"]
                if n_stocks == 1:
                    st = plan["stocks"][0]
                    # k = int(st["droplets_per_target"].get(float(target), 0))
                    s, _u = start_lookup.get(key, (0.0, ""))   # key is (factor, option_or_None)
                    t_add = max(0.0, float(target) - float(s))
                    k, mk, unreachable, nearest = self._resolve_drops_for_target(st, t_add)
                    used_nL += k * st["droplet_volume_nL"]
                    tot_key = (key[0], key[1] or "", st["stock_concentration"])
                    stock_totals[tot_key] = stock_totals.get(tot_key, 0) + k
                    per_rxn_drops[tot_key] = per_rxn_drops.get(tot_key, 0) + k
                    stock_drop_vol_nL[tot_key] = float(st["droplet_volume_nL"])
                    if unreachable:
                        issues.append({
                            "where": key,  # (factor, option or None)
                            "target": float(target),
                            "stock_concentration": float(st["stock_concentration"]),
                            "units": st.get("units", ""),
                            "suggested_nearest": float(nearest) if nearest is not None else None,
                        })
                else:
                    st1, st2 = plan["stocks"]
                    s, _u = start_lookup.get(key, (0.0, ""))   # key is (factor, option_or_None)
                    t_add = max(0.0, float(target) - float(s))
                    k1, mk1, un1, nearest1 = self._resolve_drops_for_target(st1, t_add)
                    k2, mk2, un2, nearest2 = self._resolve_drops_for_target(st2, t_add)

                    used_nL += (k1 + k2) * st1["droplet_volume_nL"]  # same dv for both legs
                    tot_key1 = (key[0], key[1] or "", st1["stock_concentration"])
                    tot_key2 = (key[0], key[1] or "", st2["stock_concentration"])
                    stock_totals[tot_key1] = stock_totals.get(tot_key1, 0) + k1
                    stock_totals[tot_key2] = stock_totals.get(tot_key2, 0) + k2
                    per_rxn_drops[tot_key1] = per_rxn_drops.get(tot_key1, 0) + k1
                    per_rxn_drops[tot_key2] = per_rxn_drops.get(tot_key2, 0) + k2
                    stock_drop_vol_nL[tot_key1] = float(st1["droplet_volume_nL"])
                    stock_drop_vol_nL[tot_key2] = float(st2["droplet_volume_nL"])
                    if (un1 and abs(float(target)) > 1e-12) or (un2 and abs(float(target)) > 1e-12):
                        issues.append({
                            "where": key,
                            "target": float(target),
                            "stock_concentration": (float(st1["stock_concentration"]), float(st2["stock_concentration"])),
                            "units": st1.get("units", ""),
                            "suggested_nearest": (float(nearest1) if nearest1 is not None else None,
                                                float(nearest2) if nearest2 is not None else None),
                        })

            # update per-stock per-reaction maxima
            for k, drops in per_rxn_drops.items():
                stock_max_per_rxn_drops[k] = max(stock_max_per_rxn_drops.get(k, 0), drops)

            worst_nonfill = max(worst_nonfill, used_nL)

            # fill reagent for this reaction
            remaining_nL = max(0.0, V - used_nL)
            fill_drops = int(round(remaining_nL / fill_dv))
            fill_total_drops += fill_drops

            rows.append({
                "nonfill_volume_nL": used_nL,
                "fill_drops": fill_drops
            })

        # apply replicates to totals (per-reaction maxima do NOT scale with reps)
        for k in list(stock_totals.keys()):
            stock_totals[k] *= reps
        fill_total_drops *= reps

        # Build stock rows cache (with totals AND per-reaction max volume)
        stock_table = []
        for row in self._stock_rows_cache:
            tot_key = (row["factor_name"], row["option_name"], row["stock_concentration"])
            drops = stock_totals.get(tot_key, 0)
            dv_nL = float(row["droplet_volume_nL"])
            vol_uL = drops * dv_nL / 1000.0

            max_drops_one_rxn = stock_max_per_rxn_drops.get(tot_key, 0)
            max_vol_nL = max_drops_one_rxn * dv_nL

            stock_table.append({
                **row,
                "total_droplets": int(drops),
                "total_volume_uL": round(vol_uL, 3),
                "max_per_rxn_nL": float(max_vol_nL),
            })
        self._stock_rows_cache = stock_table

        # Fill reagent row (total) – keep as before; leave max_per_rxn_nL blank
        fill_uL = fill_total_drops * fill_dv / 1000.0
        self._fill_row_cache = {
            "factor_name": self.metadata.get("fill_reagent_name", "Water"),
            "option_name": "",
            "stock_concentration": 1.0,
            "delta_per_drop": 0.0,
            "units": "--",
            "droplet_volume_nL": fill_dv,
            "total_droplets": int(fill_total_drops),
            "total_volume_uL": round(fill_uL, 3),
            "max_per_rxn_nL": "",
            "reagent_id": None,
            "reagent_display_name": None,
            "intended_head_type_id": None,
            "intended_head_type_display_name": None,
        }
        # --- replicate-expand the row list so _reactions_df matches actual run order ---
        base_rows = rows
        rows = []
        n_base = len(base_rows)
        for r in range(reps):
            for i, row in enumerate(base_rows):
                rows.append({
                    **row,
                    "replicate": r + 1,            # 1-based replicate index (optional)
                    "reaction_index": i,           # index within base design (optional)
                    "global_index": r * n_base + i # absolute run index (optional)
                })
        self._reactions_df = pd.DataFrame(rows)
        self._last_worst_nonfill_volume_nL = worst_nonfill
        if issues:
            # Fire a signal so the UI can pop a warning dialog/banner.
            self.targets_unreachable.emit(issues)
        self.experiment_generated.emit(len(reactions) * reps, float(worst_nonfill))

    def find_option_by_reagent_name(self, reagent_name: str) -> tuple[tuple[str, Optional[str]], OptionSpec] | None:
        """
        Return ((factor_name, option_or_None), OptionSpec) for a reagent display name.
        Additives encode option.name == factor.name.
        Choice groups use option.name.
        """
        if not reagent_name:
            return None
        # Additives
        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                if o.name == reagent_name or f.name == reagent_name:
                    return ((f.name, None), o)
        # Choices
        for f in self.factors:
            if f.kind == "choice":
                for o in f.options:
                    if o.name == reagent_name:
                        return ((f.name, o.name), o)
        return None


    def get_targets_for_key(self, key: tuple[str, Optional[str]]) -> list[float]:
        """Return raw *final* targets as authored in the design (no starting subtraction)."""
        fac, opt = key
        for f in self.factors:
            if f.name != fac:
                continue
            if f.kind == "additive":
                return list(f.options[0].targets)
            else:
                for o in f.options:
                    if o.name == opt:
                        return list(o.targets)
        return []


    def get_plan_for_key(self, key: tuple[str, Optional[str]]) -> dict | None:
        """Ensure plans exist and return plans_per_option[key]."""
        if not self.plans_per_option:
            # Safe: compute plans if caller came in early
            self.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
        return self.plans_per_option.get(key)


    def _nearest_two_stock(self, t_add: float, d1: float, d2: float) -> tuple[int, int, float]:
        """
        Solve min |a*d1 + b*d2 - t_add| over nonnegative ints (a,b) with a simple bounded search.
        Returns (a,b, err). Bound a to reasonable limit to keep fast.
        """
        if d1 <= 0 or d2 <= 0:
            return (0, 0, abs(t_add))
        a_max = int(round(t_add / d1)) + 6  # small slack
        best = (0, 0, float("inf"))
        for a in range(max(0, a_max + 1)):
            rem = t_add - a * d1
            b = 0 if rem <= 0 else int(round(rem / d2))
            b = max(0, b)
            err = abs(a * d1 + b * d2 - t_add)
            # tie-break on smaller (a+b) to keep printed volume small
            if (err < best[2] - 1e-12) or (abs(err - best[2]) <= 1e-12 and (a + b) < (best[0] + best[1])):
                best = (a, b, err)
        return best


    def preview_requantized_for_option(
        self,
        key: tuple[str, Optional[str]],
        new_droplet_nL: float,
        *,
        quantum: float = 0.1
    ) -> dict:
        """
        PREVIEW ONLY. Keep existing stock concentration(s) for 'key' but recompute the mapping
        using 'new_droplet_nL'. Returns dict with per-target rows and summary.
        """
        plan = self.get_plan_for_key(key)
        if not plan:
            return {"ok": False, "reason": "No stock plan available for this reagent."}

        # starting conc & units for this option
        start_lookup = {}
        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                start_lookup[(f.name, None)] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)
            else:
                for o in f.options:
                    start_lookup[(f.name, o.name)] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)

        starting, units = start_lookup.get(key, (0.0, ""))

        V_final = float(self.metadata.get("final_reaction_volume_nL", self.metadata.get("target_reaction_volume_nL", 500.0)))
        if V_final <= 0 or new_droplet_nL <= 0:
            return {"ok": False, "reason": "Invalid volumes."}

        # current (original) droplet volume per this plan (all legs share the same nL)
        old_dv = None
        if plan["n_stocks"] == 1:
            old_dv = float(plan["stocks"][0]["droplet_volume_nL"])
        else:
            old_dv = float(plan["stocks"][0]["droplet_volume_nL"])

        targets_final = self.get_targets_for_key(key)
        rows = []
        max_printed_nL_new = 0.0

        def _orig_k_for(t_final: float, st: dict) -> int:
            # helper to compute original k from the saved mapping (t_add grid)
            t_add = max(0.0, float(t_final) - float(starting))
            k, _, _, _ = self._resolve_drops_for_target(st, t_add)
            return int(k)

        if plan["n_stocks"] == 1:
            st0 = plan["stocks"][0]
            c_stock = float(st0["stock_concentration"])
            d_new = (c_stock * new_droplet_nL) / V_final  # new delta per drop (final-units)
            for t in targets_final:
                t_add = max(0.0, float(t) - float(starting))
                k_new = int(round(t_add / d_new)) if d_new > 0 else 0
                k_new = max(0, k_new)
                achieved_add = k_new * d_new
                achieved_final = starting + achieved_add
                err = achieved_final - float(t)
                printed_nL_new = k_new * new_droplet_nL
                printed_nL_old = _orig_k_for(t, st0) * old_dv
                rows.append({
                    "target_final": float(t),
                    "starting": float(starting),
                    "delta_per_drop": float(d_new),
                    "achieved_final": float(achieved_final),
                    "error": float(err),
                    "drops": int(k_new),
                    "printed_nL_new": float(printed_nL_new),
                    "printed_nL_old": float(printed_nL_old),
                    "printed_nL_shift": float(printed_nL_new - printed_nL_old),
                    "units": units,
                })
                max_printed_nL_new = max(max_printed_nL_new, printed_nL_new)
            return {"ok": True, "n_stocks": 1, "rows": rows, "max_printed_nL_new": max_printed_nL_new, "units": units, "new_droplet_nL": float(new_droplet_nL)}

        # two-stock case
        st1, st2 = plan["stocks"]
        c1 = float(st1["stock_concentration"]); d1 = (c1 * new_droplet_nL) / V_final
        c2 = float(st2["stock_concentration"]); d2 = (c2 * new_droplet_nL) / V_final
        for t in targets_final:
            t_add = max(0.0, float(t) - float(starting))
            a, b, err_add = self._nearest_two_stock(t_add, d1, d2)
            achieved_add = a * d1 + b * d2
            achieved_final = starting + achieved_add
            # compute old printed volume (sum of legs)
            k1_old = _orig_k_for(t, st1)
            k2_old = _orig_k_for(t, st2)
            printed_nL_old = (k1_old + k2_old) * old_dv
            printed_nL_new = (a + b) * new_droplet_nL
            rows.append({
                "target_final": float(t),
                "starting": float(starting),
                "delta_per_drop_leg1": float(d1),
                "delta_per_drop_leg2": float(d2),
                "achieved_final": float(achieved_final),
                "error": float(achieved_final - float(t)),
                "drops": (int(a), int(b)),
                "printed_nL_new": float(printed_nL_new),
                "printed_nL_old": float(printed_nL_old),
                "printed_nL_shift": float(printed_nL_new - printed_nL_old),
                "units": units,
            })
            max_printed_nL_new = max(max_printed_nL_new, printed_nL_new)
        return {"ok": True, "n_stocks": 2, "rows": rows, "max_printed_nL_new": max_printed_nL_new, "units": units, "new_droplet_nL": float(new_droplet_nL)}

    def find_key_for_reagent(self, reagent_name: str, group_name: str | None = None) -> tuple[str, str | None]:
        """
        Resolve a reagent into the (factor_name, option_name_or_None) key used in plans_per_option.
        - For additives, reagent_name == factor name, option is None.
        - For choice groups, reagent_name == option name. If group_name is given, prefer that group.
        Raises ValueError if not uniquely resolvable.
        """
        matches: list[tuple[str, str | None]] = []

        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                if o.name == reagent_name or f.name == reagent_name:
                    matches.append((f.name, None))
            else:  # choice
                for o in f.options:
                    if o.name == reagent_name:
                        if group_name is None or group_name == f.name:
                            matches.append((f.name, o.name))

        if not matches:
            raise ValueError(f"Reagent '{reagent_name}' not found in design.")
        # If multiple matches (same option name across groups), require group_name
        if len(matches) > 1 and group_name is None:
            raise ValueError(f"Reagent '{reagent_name}' matches multiple groups; pass group_name.")
        return matches[0]


    # ---------- apply a new droplet size while keeping stock concentration fixed ----------
    def apply_droplet_volume_for_option(
        self,
        factor_name: str,
        option_name: str | None,
        new_droplet_nL: float,
        *,
        write_keys_if_assigned: bool = True,
    ) -> dict:
        """
        Rebind a specific option (or additive) to a NEW droplet volume, but KEEP the
        already-chosen stock concentration the same. We recompute the droplets-per-target
        mapping by rounding to the nearest integer multiple of delta:

            delta = stock_concentration * new_droplet_nL / final_reaction_volume_nL

        Rounding to nearest ensures the per-reagent printed-volume change is ≤ 0.5 drop, and the
        fill reagent will absorb the difference so well volume stays at V.

        Returns a small summary dict for UI debug/logging.
        """
        key = (factor_name, option_name)
        plan = self.plans_per_option.get(key)
        if not plan:
            raise ValueError(f"No stock plan for {key}; run optimize_stock_solutions() first.")

        if plan.get("n_stocks", 1) != 1:
            # (You can extend this to 2-stock later; see note below.)
            raise NotImplementedError("Step 2 currently supports single-stock reagents only.")

        # ---- Fetch the OptionSpec so we can update its droplet_nL persistently ----
        opt_obj = None
        for f in self.factors:
            if f.name == factor_name:
                if f.kind == "additive":
                    opt_obj = f.options[0]
                else:
                    for o in f.options:
                        if o.name == option_name:
                            opt_obj = o
                            break
                break
        if opt_obj is None:
            raise ValueError(f"Design contains no OptionSpec for {key}")

        # ---- Inputs for delta ----
        st = plan["stocks"][0]
        c_stock = float(st["stock_concentration"])
        units = st.get("units", opt_obj.units)
        V_final = float(self.metadata.get("final_reaction_volume_nL",
                                        self.metadata.get("target_reaction_volume_nL", 500.0)))
        new_dv = float(new_droplet_nL)
        if new_dv <= 0.0 or V_final <= 0.0:
            raise ValueError("new_droplet_nL and final_reaction_volume_nL must be positive.")

        delta = c_stock * new_dv / V_final

        # ---- Targets & starting concentration (convert "final targets" → additive-only targets) ----
        s_start = float(getattr(opt_obj, "starting_conc", 0.0) or 0.0)
        # Exact t_add values must match what generate_experiment() computes.
        targets_final = [float(t) for t in opt_obj.targets]
        t_add_list = [max(0.0, t - s_start) for t in targets_final]

        # ---- Rebuild droplets_per_target: key WITH t_add so resolve is exact ---
        # Use rounding to nearest integer; guarantees ≤ 0.5 drop volume deviation.
        dp: dict[float, int] = {}
        for t_add in t_add_list:
            k = 0 if delta <= 0 else int(round(t_add / delta))
            k = max(0, k)
            # normalize key to avoid float dust and to match resolve path
            key_t = float(f"{t_add:.12g}")
            dp[key_t] = k

        # ---- Patch the live plan & stock table cache ----
        st["droplet_volume_nL"] = new_dv
        st["delta_per_drop"] = delta
        st["units"] = units
        st["droplets_per_target"] = dp
        # keep quantum small so future near-match logic is permissive but irrelevant (we use exact t_add keys)
        st["quantum"] = 1e-6

        # Update the persistent design object so saves/loads reflect the new dv
        opt_obj.droplet_nL = new_dv

        # Update the cached stock rows so UI tables reflect new dv
        updated_row = None
        for r in self._stock_rows_cache:
            if (
                r.get("factor_name") == factor_name
                and (r.get("option_name") or "") == (option_name or "")
                and float(r.get("stock_concentration", -1)) == c_stock
            ):
                r["droplet_volume_nL"] = new_dv
                r["delta_per_drop"] = delta
                updated_row = r
                break

        # ---- Recompute the experiment so droplet counts and fill update everywhere ----
        self.generate_experiment()

        # ---- Rebind per-well droplet counts to match the new mapping ----
        if self._has_runtime_assignments():
            self._rebind_runtime_assignments_to_current_plans()

        # Optionally rewrite keys immediately if wells are assigned (so conc_key reflects new final concs)
        if write_keys_if_assigned and self._has_runtime_assignments():
            self.write_keys_now()

        # mark unsaved since design object changed
        self.unsaved_changes = True

        return {
            "factor": factor_name,
            "option": option_name,
            "stock_concentration": c_stock,
            "units": units,
            "new_droplet_nL": new_dv,
            "delta_per_drop": delta,
            "example_map": dict(list(dp.items())[: min(5, len(dp))]),
            "stock_row_updated": bool(updated_row),
            "worst_nonfill_after_nL": float(self._last_worst_nonfill_volume_nL or 0.0),
        }


    # ------------- Public getters for the UI -------------

    def get_stock_table_rows(self, include_fill: bool = True) -> List[Dict]:
        rows = list(self._stock_rows_cache)
        if include_fill and self._fill_row_cache is not None:
            rows = rows + [self._fill_row_cache]
        return rows

    def get_worst_nonfill_volume_nL(self) -> Optional[float]:
        return self._last_worst_nonfill_volume_nL

    def get_reactions_dataframe(self) -> pd.DataFrame:
        return self._reactions_df.copy()
    
    def get_random_seed(self):
        return self.metadata.get("random_seed", None)

    def get_start_row(self) -> int:
        return int(self.metadata.get("start_row", 0))

    def get_start_col(self) -> int:
        return int(self.metadata.get("start_col", 0))


    # ---------- enumerate reactions as stock-droplet lists ----------
    def iter_reaction_stock_droplets(self):
        reactions = self._enumerate_reactions()
        reps = int(self.metadata.get("replicates", 1))

        def _reagent_name_from_key(key: tuple[str, object]) -> str:
            return key[0] if key[1] is None else key[1]

        # starting conc lookup (same as in generate_experiment)
        start_lookup: Dict[Tuple[str, Optional[str]], float] = {}
        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                start_lookup[(f.name, None)] = float(getattr(o, "starting_conc", 0.0) or 0.0)
            else:
                for o in f.options:
                    start_lookup[(f.name, o.name)] = float(getattr(o, "starting_conc", 0.0) or 0.0)

        for r in range(reps):
            for rxn in reactions:
                items = []
                for key, target in rxn.items():
                    plan = self.plans_per_option.get(key)
                    if not plan:
                        continue
                    s = start_lookup.get(key, 0.0)
                    t_add = max(0.0, float(target) - float(s))
                    if plan["n_stocks"] == 1:
                        st = plan["stocks"][0]
                        drops, _, _, _ = self._resolve_drops_for_target(st, t_add)
                        if drops > 0:
                            items.append((_reagent_name_from_key(key),
                                        float(st["stock_concentration"]),
                                        st["units"],
                                        drops))
                    else:
                        st1, st2 = plan["stocks"]
                        k1, _, _, _ = self._resolve_drops_for_target(st1, t_add)
                        k2, _, _, _ = self._resolve_drops_for_target(st2, t_add)
                        if k1 > 0:
                            items.append((_reagent_name_from_key(key),
                                        float(st1["stock_concentration"]),
                                        st1["units"],
                                        k1))
                        if k2 > 0:
                            items.append((_reagent_name_from_key(key),
                                        float(st2["stock_concentration"]),
                                        st2["units"],
                                        k2))
                yield items
                
    # ------------- Save/Load (optional; keep simple) -------------

    def to_dict(self) -> Dict:
        """
        Serialize the design input (metadata + factors) plus, if present,
        any explicit uploaded/manual reaction set.
        """
        data: Dict[str, object] = {
            "metadata": self.metadata,
            "factors": [
                {
                    "name": f.name,
                    "kind": f.kind,
                    "options": [
                        {
                            "name": o.name,
                            "targets": list(o.targets),
                            "units": o.units,
                            "droplet_nL": float(o.droplet_nL),
                            "starting_conc": float(getattr(o, "starting_conc", 0.0) or 0.0),
                            "reagent_id": getattr(o, "reagent_id", None),
                            "reagent_display_name": getattr(o, "reagent_display_name", None),
                            "intended_head_type_id": getattr(o, "intended_head_type_id", None),
                            "intended_head_type_display_name": getattr(o, "intended_head_type_display_name", None),
                            "forced_stock_conc": (
                                float(getattr(o, "forced_stock_conc"))
                                if getattr(o, "forced_stock_conc", None) is not None
                                else None
                            ),
                        }
                        for o in f.options
                    ],
                }
                for f in self.factors
            ],
        }

        # If this design is driven by an explicit uploaded reaction list,
        # serialize it as well so we can restore it on load.
        if self._uploaded_reactions is not None:
            import os

            serialized_rxns: list[list[dict]] = []
            for rxn in self._uploaded_reactions:
                row: list[dict] = []
                for (fac, opt), val in rxn.items():
                    row.append(
                        {
                            "factor": fac,
                            "option": opt,
                            "target": float(val),
                        }
                    )
                serialized_rxns.append(row)

            csv_name = None
            if self._uploaded_design_source:
                try:
                    csv_name = os.path.basename(self._uploaded_design_source)
                except Exception:
                    csv_name = self._uploaded_design_source

            data["uploaded_design"] = {
                "reactions": serialized_rxns,
                # Just the filename; full path is reconstructed using experiment_dir_path
                "csv_filename": csv_name,
                # persist well IDs (or None)
                "well_ids": (
                    list(self._uploaded_well_ids)
                    if self._uploaded_well_ids is not None
                    else None
                ),
            }

        return data

    def from_dict(self, d: Dict):
        """
        Rehydrate metadata, factors, and (optionally) an uploaded/manual
        reaction list from a design dictionary.
        """
        import os

        # --- metadata + factors (existing behavior) ---
        self.metadata = d.get("metadata", self.metadata)
        self.factors = []

        for f in d.get("factors", []):
            fs = FactorSpec(name=f["name"], kind=f["kind"], options=[])
            for o in f.get("options", []):
                opt = OptionSpec(
                    name=o["name"],
                    targets=list(o.get("targets", [])),
                    units=o.get("units", ""),
                    droplet_nL=float(o.get("droplet_nL", 10.0)),
                    starting_conc=float(o.get("starting_conc", 0.0)),
                    reagent_id=o.get("reagent_id"),
                    reagent_display_name=o.get("reagent_display_name"),
                    intended_head_type_id=o.get("intended_head_type_id"),
                    intended_head_type_display_name=o.get("intended_head_type_display_name"),
                )
                if "forced_stock_conc" in o and o["forced_stock_conc"] is not None:
                    try:
                        setattr(opt, "forced_stock_conc", float(o["forced_stock_conc"]))
                    except Exception:
                        setattr(opt, "forced_stock_conc", None)
                fs.options.append(opt)
            self.factors.append(fs)

        # --- clear derived caches ---
        self.plans_per_option.clear()
        self._stock_rows_cache.clear()
        self._fill_row_cache = None
        self._reactions_df = pd.DataFrame()
        self._last_worst_nonfill_volume_nL = None

        # --- uploaded/manual design state ---
        self._uploaded_reactions = None
        self._uploaded_design_source = None
        self._uploaded_well_ids = None

        ud = d.get("uploaded_design")
        if isinstance(ud, dict):
            raw_rxns = ud.get("reactions") or []
            uploaded_reactions: list[dict[tuple[str, Optional[str]], float]] = []

            for rxn_list in raw_rxns:
                # Expect a list of {factor, option, target}
                rxn_map: dict[tuple[str, Optional[str]], float] = {}
                if isinstance(rxn_list, list):
                    for spec in rxn_list:
                        if not isinstance(spec, dict):
                            continue
                        fac = spec.get("factor")
                        if not fac:
                            continue
                        opt = spec.get("option", None)
                        tgt = spec.get("target", 0.0)
                        try:
                            v = float(tgt)
                        except Exception:
                            v = 0.0
                        rxn_map[(fac, opt)] = v
                if rxn_map:
                    uploaded_reactions.append(rxn_map)

            if uploaded_reactions:
                self._uploaded_reactions = uploaded_reactions

            # restore well IDs, if present
            well_ids = ud.get("well_ids")
            if isinstance(well_ids, list):
                normalized: list[Optional[str]] = []
                for w in well_ids:
                    if w is None:
                        normalized.append(None)
                    else:
                        s = str(w).strip()
                        normalized.append(s or None)
                # Only keep if at least one non-None
                self._uploaded_well_ids = (
                    normalized if any(x is not None for x in normalized) else None
                )
            else:
                self._uploaded_well_ids = None

            csv_fn = ud.get("csv_filename")
            if csv_fn:
                if self.experiment_dir_path:
                    self._uploaded_design_source = os.path.join(self.experiment_dir_path, csv_fn)
                else:
                    # Design-only load (no experiment dir yet) – store as-is
                    self._uploaded_design_source = csv_fn

        # Notify UI that the stock table needs rebuilding
        self.stock_updated.emit()

    # -----------------------------
    # Runtime context / calibration
    # -----------------------------
    def set_runtime_context(self, well_plate, reaction_collection):
        """Model will set these right before we write progress/key."""
        self._runtime_well_plate = well_plate
        self._runtime_reaction_collection = reaction_collection

    def set_calibration_manager(self, mgr):
        """Optional; if your app has a calibration manager, wire it here."""
        self._calibration_manager = mgr
        if self.calibration_file_path and hasattr(mgr, "update_calibration_file_path"):
            mgr.update_calibration_file_path(self.calibration_file_path)

    # -----------------------------
    # Simple getters used by Model
    # -----------------------------
    def get_number_of_reactions(self) -> int:
        """Total reactions including replicates."""
        if hasattr(self, "_reactions_df") and not self._reactions_df.empty:
            return len(self._reactions_df)
        # Fallback if generate_experiment() hasn't been called yet
        reps = int(self.metadata.get("replicates", 1))
        return reps * len(self._enumerate_reactions())

    def get_random_seed(self) -> Optional[int]:
        return self.metadata.get("random_seed")

    def get_start_row(self) -> int:
        return int(self.metadata.get("start_row", 0))

    def get_start_col(self) -> int:
        return int(self.metadata.get("start_col", 0))

    def get_calibration_file_path(self) -> Optional[str]:
        return self.calibration_file_path

    def get_unreachable_preview_map(self) -> Dict[Tuple[str, Optional[str]], List[float]]:
        return dict(self._unreachable_preview_map)

    # -----------------------------
    # JSON helpers
    # -----------------------------
    def convert_to_serializable(self, obj):
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()          # ndarray -> list
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    def _default_fill_droplet_volume_nl(self) -> float:
        return 40.0 if self.legacy_mode else 10.0

    def _atomic_json_dump(self, path: str, payload: Dict):
        import json
        import os
        import tempfile

        directory = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix="._tmp_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, default=self.convert_to_serializable)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            raise

    # -----------------------------
    # Path setup / initialization
    # -----------------------------
    def initialize_experiment(self, base_dir: Optional[str] = None):
        """Create Experiments/<name> dir and seed files. Only write key CSVs once wells are assigned."""
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_experiment_dir = base_dir or os.path.join(script_dir, "Experiments")
        if not os.path.exists(base_experiment_dir):
            os.makedirs(base_experiment_dir)
        temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")
        exp_name = self.metadata.get("name", temp_name)
        self.experiment_dir_path = os.path.join(base_experiment_dir, exp_name)
        if not os.path.exists(self.experiment_dir_path):
            os.makedirs(self.experiment_dir_path)
        self.update_all_paths()

        # if this design uses an uploaded/manual reaction list,
        # write a CSV representation into the experiment directory.
        if self._uploaded_reactions is not None:
            self._materialize_uploaded_design_csv()

        # Always save the design and seed a progress.json (may be empty now)
        self.save_experiment()
        self.create_progress_file()

        # Only write key CSVs if we already have assignments
        if self._has_runtime_assignments():
            self._ensure_design_ready()
            self._ensure_progress_populated()
            self.create_key_file()
            self.create_concentration_key_file()

        # optional calibration file
        if self.calibration_file_path and not os.path.exists(self.calibration_file_path):
            with open(self.calibration_file_path, "w") as f:
                f.write("{}")
        if self._calibration_manager is not None:
            if hasattr(self._calibration_manager, "begin_session"):
                self._calibration_manager.begin_session(self.calibration_file_path)

    def update_all_paths(self):
        """Update file paths based on current experiment_dir_path."""
        import os
        if not self.experiment_dir_path:
            return
        self.experiment_file_path   = os.path.join(self.experiment_dir_path, "experiment_design.json")
        self.progress_file_path     = os.path.join(self.experiment_dir_path, "progress.json")
        self.calibration_file_path  = os.path.join(self.experiment_dir_path, "calibration.json")
        self.key_file_path          = os.path.join(self.experiment_dir_path, "key.csv")
        self.concentration_key_file_path = os.path.join(self.experiment_dir_path, "concentration_key.csv")
        if self._calibration_manager is not None and hasattr(self._calibration_manager, "update_calibration_file_path"):
            self._calibration_manager.update_calibration_file_path(self.calibration_file_path)

    # -----------------------------
    # Save / Load design
    # -----------------------------
    def save_experiment(self):
        """Persist metadata + factors (inputs). Derived plans are recomputed on load."""
        data = self.to_dict()  # you already have to_dict() for v2
        self._atomic_json_dump(self.experiment_file_path, data)
        self.unsaved_changes = False

    def load_experiment(self, filename: str, experiment_dir: str):
        """Load factors + metadata; recompute plans and grid."""
        import json, os
        self.experiment_file_path = filename
        self.experiment_dir_path = experiment_dir
        self.update_all_paths()

        with open(filename, "r") as f:
            data = json.load(f)

        # Rehydrate
        self.from_dict(data)  # resets caches/signals
        
        # If this design has an uploaded/manual reaction list, make sure a CSV
        # exists in the experiment directory for the user to re-import later.
        if self._uploaded_reactions is not None and self.experiment_dir_path:
            if not self._uploaded_design_source or not os.path.exists(self._uploaded_design_source):
                self._materialize_uploaded_design_csv()

        # Recompute plans & grid
        res = self.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
        if not res.get("best"):
            # surface an error in your UI as you prefer
            print("Optimization on load failed:", res.get("reason", "Unknown"))
            return
        self.generate_experiment()  # fills caches, worst-case, etc.

        # If a progress file already exists, read it (Model later applies it)
        if os.path.exists(self.progress_file_path):
            self.read_progress_file(self.progress_file_path)

    # -----------------------------
    # Progress & Key files
    # -----------------------------
    def create_progress_file(self, file_name: Optional[str] = None):
        """Write a `progress.json` snapshot from current well assignments."""
        if file_name is not None:
            self.progress_file_path = file_name

        if self._runtime_well_plate is None:
            # No wells assigned yet – write empty structure
            self._atomic_json_dump(self.progress_file_path, {})
            self.progress_data = {}
            return

        progress = {}
        for well in self._runtime_well_plate.get_all_wells():
            rxn = well.get_assigned_reaction()
            if rxn is None:
                continue
            progress[well.well_id] = {
                "reaction_id": rxn.unique_id,
                "reagents": {
                    stock_id: {
                        "target_droplets": reagent.get_target_droplets(),
                        "added_droplets": reagent.added_droplets
                    }
                    for stock_id, reagent in rxn.get_all_reagents().items()
                },
                "completed": rxn.check_all_complete()
            }

        self.progress_data = progress
        plate_meta = {
            "name": self._runtime_well_plate.get_current_plate_name(),
            "rows": self._runtime_well_plate.get_num_rows(),
            "columns": self._runtime_well_plate.get_num_cols(),
            "schema_version": 1,
        }
        payload = dict(progress)
        payload["__plate__"] = plate_meta
        self._atomic_json_dump(self.progress_file_path, payload)

    def progress_to_key(self) -> "pd.DataFrame":
        """
        Make a wide CSV with wells as rows, stock_id-with-droplet-volume as columns,
        and target droplets as values.

        Column header format:
        <reagent>_<conc(2dp)>_<units>_<nL_per_drop(1dp)>nL
        e.g., "NaCl_25.00_mM_10.0nL"
        """
        # 1) Lookup of nL_per_drop for each stock_id from the stock table (includes Fill)
        stock_rows = self.get_stock_table_rows(include_fill=True)

        def _base_sid(row: dict) -> str:
            name = row.get("option_name") or row.get("factor_name") or ""
            units = row.get("units", "")
            conc = row.get("stock_concentration", 0.0)
            try:
                conc2 = f"{float(conc):.2f}"
            except Exception:
                conc2 = str(conc)
            return f"{name}_{conc2}_{units}"

        dv_lookup = {
            _base_sid(r): float(r.get("droplet_volume_nL", 0.0))
            for r in stock_rows
        }
        dv_fallback = float(self.metadata.get("fill_droplet_volume_nL", 10.0))

        # 2) Build the table: one value (drops) per (well, stock-with-dv)
        data = {}
        for well_id, entry in self.progress_data.items():
            reagents = entry.get("reagents", {})
            row = {}
            for base_sid, details in reagents.items():
                drops = int(details.get("target_droplets", 0))
                nL_per_drop = dv_lookup.get(base_sid, dv_fallback)
                # Append droplet volume to the ID (single-level header)
                sid_with_dv = f"{base_sid}_{nL_per_drop:.1f}nL"
                row[sid_with_dv] = drops
            data[well_id] = row

        df = pd.DataFrame.from_dict(data, orient="index")

        # Stable column ordering: group by base id, then by nL value
        def _split_key(k: str):
            # "<name>_<conc>_<units>_<dv>nL" → (name_conc_units, dv_float)
            parts = k.rsplit("_", 1)
            base = parts[0] if parts else k
            dv = parts[1][:-2] if len(parts) > 1 and parts[1].endswith("nL") else "0"
            try:
                dvf = float(dv)
            except Exception:
                dvf = 0.0
            return base, dvf

        if not df.empty:
            df = df.reindex(sorted(df.columns, key=lambda c: _split_key(str(c))), axis=1)

        return df
    
    def create_key_file(self, file_name: Optional[str] = None):
        if file_name is not None:
            self.key_file_path = file_name
        # Make sure we have plans, reactions, and progress
        self._ensure_design_ready()
        self._ensure_progress_populated()
        df = self.progress_to_key()
        if df.empty:
            # Nothing assigned yet; don't write a misleading header-only CSV
            return
        df.to_csv(self.key_file_path, index_label="Well ID")

    def progress_to_concentration_key(self) -> "pd.DataFrame":
        """
        Wide CSV with wells as rows and columns "<reagent_name>_<units>",
        containing the final concentrations in each well = starting + added.
        """
        V_final_nL = float(self.metadata.get(
            "final_reaction_volume_nL",
            self.metadata.get("target_reaction_volume_nL", 500.0)
        ))

        # Stock rows (includes Fill)
        stock_rows = self.get_stock_table_rows(include_fill=True)

        def _base_sid(row: dict) -> str:
            name  = row.get("option_name") or row.get("factor_name") or ""
            units = row.get("units", "")
            conc  = row.get("stock_concentration", 0.0)
            try:
                conc2 = f"{float(conc):.2f}"
            except Exception:
                conc2 = str(conc)
            return f"{name}_{conc2}_{units}"

        # base_sid -> stock metadata for 'added' part
        stock_info = {}
        for r in stock_rows:
            sid = _base_sid(r)
            stock_info[sid] = {
                "reagent_name": (r.get("option_name") or r.get("factor_name") or ""),
                "units": r.get("units", ""),
                "stock_conc": float(r.get("stock_concentration", 0.0)),
                "dv_nL": float(r.get("droplet_volume_nL", 0.0)),
            }

        # Build lookups for starting conc, by reagent name (additives) or option name (choices)
        starting_by_reagent: Dict[str, Tuple[float, str]] = {}
        # Also track groups → options for inference
        group_to_options: Dict[str, List[str]] = {}

        for f in self.factors:
            if f.kind == "additive":
                o = f.options[0]
                starting_by_reagent[o.name] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)
            else:
                group_to_options[f.name] = [o.name for o in f.options]
                for o in f.options:
                    starting_by_reagent[o.name] = (float(getattr(o, "starting_conc", 0.0) or 0.0), o.units)

        data = {}
        for well_id, entry in (self.progress_data or {}).items():
            reagents = entry.get("reagents", {})
            row = {}

            # 1) Added concentration from actual drops
            for base_sid, details in reagents.items():
                drops = int(details.get("target_droplets", 0))
                info = stock_info.get(base_sid)
                if not info or drops <= 0:
                    continue
                c_stock = info["stock_conc"]
                dv = info["dv_nL"]
                if dv <= 0.0 or V_final_nL <= 0.0:
                    continue
                contrib = c_stock * (drops * dv) / V_final_nL
                col = f'{info["reagent_name"]}_{info["units"]}'.strip("_")
                row[col] = row.get(col, 0.0) + contrib

            # 2) Add starting concentrations.
            #    For additives: always add (they're present in every well).
            #    For choices: add only for the option present in this well. We infer presence
            #    if any stock for that option is listed in reagents (even with 0 drops).
            present_reagent_names = set()
            for base_sid in reagents.keys():
                info = stock_info.get(base_sid)
                if info:
                    present_reagent_names.add(info["reagent_name"])

            # Additives: defined as those options whose name equals factor name (your encoding)
            for f in self.factors:
                if f.kind == "additive":
                    o = f.options[0]
                    s_val, s_units = starting_by_reagent.get(o.name, (0.0, ""))
                    if s_val != 0.0:
                        col = f"{o.name}_{s_units}".strip("_")
                        row[col] = row.get(col, 0.0) + s_val

            # Choices: exactly one option per group should be present in each well.
            for f in self.factors:
                if f.kind != "choice":
                    continue
                chosen = None
                for o in f.options:
                    if o.name in present_reagent_names:
                        chosen = o
                        break
                # Fallback: if none detected (e.g., all zero drops and omitted),
                # we can't unambiguously assign; skip silently.
                if chosen is None:
                    continue
                s_val, s_units = starting_by_reagent.get(chosen.name, (0.0, ""))
                if s_val != 0.0:
                    col = f"{chosen.name}_{s_units}".strip("_")
                    row[col] = row.get(col, 0.0) + s_val

            data[well_id] = row

        df = pd.DataFrame.from_dict(data, orient="index")

        # Stable column ordering
        def _split_col(c: str):
            parts = str(c).rsplit("_", 1)
            name = parts[0] if parts else c
            units = parts[1] if len(parts) > 1 else ""
            return (name.lower(), units.lower())

        if not df.empty:
            df = df.reindex(sorted(df.columns, key=_split_col), axis=1)

        return df
    
    def create_concentration_key_file(self, file_name: Optional[str] = None, decimals: int = 4):
        if file_name is not None:
            self.concentration_key_file_path = file_name
        # Make sure we have plans, reactions, and progress
        self._ensure_design_ready()
        self._ensure_progress_populated()
        df = self.progress_to_concentration_key()
        if df.empty:
            # Nothing assigned yet; don't write a misleading header-only CSV
            return
        if decimals is not None and isinstance(decimals, int):
            df = df.round(decimals)
        df.to_csv(self.concentration_key_file_path, index_label="Well ID")
    
    def write_keys_now(self):
        """
        Public convenience: rebuild progress from current assignments, then write both CSVs.
        """
        self._ensure_design_ready()
        # Always rebuild snapshot from the live reaction collection
        self.create_progress_file()
        if not self.progress_data:
            return
        self.create_key_file()
        self.create_concentration_key_file()

    def _materialize_uploaded_design_csv(self) -> Optional[str]:
        """
        If we have an uploaded/manual design (self._uploaded_reactions),
        write a canonical CSV representation into the experiment directory.

        If explicit well IDs were supplied originally, they will be written
        as a "Well ID" column.
        """
        if self._uploaded_reactions is None:
            return None
        if not self.experiment_dir_path:
            return None

        try:
            import os
            import pandas as pd  # safe even if already imported

            # Collect all (factor, option) keys that appear in any reaction
            all_keys: set[tuple[str, Optional[str]]] = set()
            for rxn in self._uploaded_reactions:
                all_keys.update(rxn.keys())
            if not all_keys:
                return None

            # Consistent ordering: by factor name then option name (if any)
            sorted_keys = sorted(all_keys, key=lambda k: (k[0], k[1] or ""))

            # Build column headers: use current factors/options to get display name + units
            key_to_col: Dict[tuple[str, Optional[str]], str] = {}
            for fac, opt in sorted_keys:
                display_name = None
                units = ""

                for f in self.factors:
                    if f.name != fac:
                        continue
                    if f.kind == "additive":
                        if not f.options:
                            continue
                        o = f.options[0]
                        display_name = o.name
                        units = o.units
                    else:
                        for o in f.options:
                            if opt is None or o.name == opt:
                                display_name = o.name
                                units = o.units
                                break
                    if display_name is not None:
                        break

                if display_name is None:
                    # Fallback: something deterministic
                    display_name = fac if opt is None else f"{fac}/{opt}"

                header = display_name
                if units:
                    header = f"{header} {units}"
                key_to_col[(fac, opt)] = header

            # Build rows; include Well ID if available
            rows: list[dict[str, object]] = []
            well_ids = self._uploaded_well_ids or []
            for idx, rxn in enumerate(self._uploaded_reactions):
                row: dict[str, object] = {}
                # Optional "Well ID" column
                if well_ids and idx < len(well_ids):
                    row["Well ID"] = well_ids[idx] or ""
                for key in sorted_keys:
                    header = key_to_col[key]
                    v = float(rxn.get(key, 0.0))
                    row[header] = v
                rows.append(row)

            df = pd.DataFrame(rows)

            dest = os.path.join(self.experiment_dir_path, "uploaded_design.csv")
            df.to_csv(dest, index=False)

            # Remember this path so it can be reported / re-encoded in the JSON
            self._uploaded_design_source = dest
            return dest

        except Exception as e:
            print(f"[ExperimentModel] WARNING: could not materialize uploaded design CSV: {e}")
            return None
    
    def _has_runtime_assignments(self) -> bool:
        """
        Returns True if we have a live reaction collection to update.
        Duck-typed to work with your existing object.
        """
        rc = getattr(self, "_runtime_reaction_collection", None)
        if rc is None:
            return False

        # Common patterns we’ve seen in your codebase:
        if hasattr(rc, "get_num_reactions") and callable(rc.get_num_reactions):
            try:
                return rc.get_num_reactions() > 0
            except Exception:
                pass
        if hasattr(rc, "size"):
            try:
                return int(rc.size) > 0
            except Exception:
                pass
        # Fallback: assume if object exists, it’s in use
        return True

    def _ensure_design_ready(self):
        """
        Make sure stock plans and reactions exist before writing key files.
        Safe to call multiple times.
        """
        if not self.plans_per_option:
            res = self.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
            if not res.get("best"):
                raise RuntimeError(f"Optimization failed: {res.get('reason', 'Unknown')}")
        if self._reactions_df.empty:
            self.generate_experiment()

    def _ensure_progress_populated(self):
        """
        Ensure self.progress_data reflects current well assignments.
        If assignments exist and progress is empty, rebuild it now.
        """
        if self.progress_data:
            return
        # if a progress.json already exists with {}, we still prefer to rebuild from runtime
        if self._has_runtime_assignments():
            self.create_progress_file()   # will repopulate from current assignments

    def _has_runtime_assignments(self) -> bool:
        """
        Heuristic check: do we have a runtime reaction collection / assignments?
        Safe even if those objects are missing or have different APIs.
        """
        rc = getattr(self, "_runtime_reaction_collection", None)
        if rc is None:
            return False
        try:
            # Prefer explicit counters if present
            if hasattr(rc, "n_assigned"):
                return bool(rc.n_assigned)
            if hasattr(rc, "size"):
                return rc.size > 0
            if hasattr(rc, "get_number_of_reactions"):
                return rc.get_number_of_reactions() > 0
        except Exception:
            pass
        # Fallback: presence of the object is good enough
        return True


    def _rebind_runtime_assignments_to_current_plans(self) -> bool:
        """
        Force per-well droplet counts in the runtime collection to match the
        current plans_per_option mapping. Tries several common method names
        so this stays robust across small interface differences.
        Returns True if we successfully pushed new counts; False otherwise.
        """
        rc = getattr(self, "_runtime_reaction_collection", None)
        if rc is None:
            return False

        it = self.iter_reaction_stock_droplets()

        try:
            # Most explicit: set each reaction's items
            if hasattr(rc, "set_reaction_items_for_index"):
                for idx, items in enumerate(it):
                    rc.set_reaction_items_for_index(idx, items)
                return True

            # Bulk reset from an iterator
            if hasattr(rc, "reset_from_iterator"):
                rc.reset_from_iterator(self.iter_reaction_stock_droplets())
                return True

            # Bulk replace with a list
            if hasattr(rc, "replace_all_reaction_items"):
                rc.replace_all_reaction_items(list(self.iter_reaction_stock_droplets()))
                return True

            # Clear + append pattern
            if hasattr(rc, "clear") and hasattr(rc, "append_reaction_items"):
                rc.clear()
                for items in self.iter_reaction_stock_droplets():
                    rc.append_reaction_items(items)
                return True

        except Exception as e:
            print(f"[ExperimentModel] WARNING: rebind of runtime assignments failed: {e}")

        return False

    def get_fill_reagent_name(self) -> str:
        return str(self.metadata.get("fill_reagent_name", "Water"))

    def preview_fill_requantized(self, new_fill_droplet_nL: float) -> dict:
        """
        Preview effect of changing ONLY the fill droplet size on total drop counts.
        Does not mutate state.
        """
        try:
            new_fill_droplet_nL = float(new_fill_droplet_nL)
        except Exception:
            return {"ok": False, "reason": "Invalid fill droplet volume."}
        if new_fill_droplet_nL <= 0:
            return {"ok": False, "reason": "Fill droplet volume must be > 0."}

        # Ensure we have a current reactions frame with nonfill volumes.
        if self._reactions_df is None or self._reactions_df.empty or "nonfill_volume_nL" not in self._reactions_df.columns:
            # Safe regen using current plans/metadata; this uses current fill dv (old)
            self.generate_experiment()

        df = self._reactions_df
        if df is None or df.empty or "nonfill_volume_nL" not in df.columns:
            return {"ok": False, "reason": "No reaction grid available to preview."}

        V_print = float(self.metadata.get("target_reaction_volume_nL", 500.0))
        old_fill_dv = float(self.metadata.get("fill_droplet_volume_nL", 10.0))

        # Per-reaction calculation of old/new fill drops
        remaining = (V_print - df["nonfill_volume_nL"]).clip(lower=0.0)
        drops_old = (remaining / old_fill_dv).round().astype(int)
        drops_new = (remaining / new_fill_droplet_nL).round().astype(int)

        total_old = int(drops_old.sum())
        total_new = int(drops_new.sum())

        printed_nL_old = float(total_old * old_fill_dv)
        printed_nL_new = float(total_new * new_fill_droplet_nL)

        # Construct a lightweight, table-friendly "rows" payload (single summary row)
        rows = [{
            "target_final": None,
            "achieved_final": None,
            "error": 0.0,
            "drops": total_new,
            "delta_per_drop": new_fill_droplet_nL,    # repurpose this column to show nL/drop for fill
            "printed_nL_new": printed_nL_new,
            "printed_nL_old": printed_nL_old,
            "printed_nL_shift": printed_nL_new - printed_nL_old,
            "units": "--",
        }]

        return {
            "ok": True,
            "is_fill": True,
            "rows": rows,
            "new_fill_droplet_nL": new_fill_droplet_nL,
            "total_drops_old": total_old,
            "total_drops_new": total_new,
            "total_drops_delta": total_new - total_old,
        }

    def apply_fill_droplet_volume(self, new_fill_droplet_nL: float, *, write_keys_if_assigned: bool = True) -> dict:
        """
        Set the fill droplet size and recompute experiment so all totals refresh.
        """
        new_fill_droplet_nL = float(new_fill_droplet_nL)
        if new_fill_droplet_nL <= 0.0:
            raise ValueError("Fill droplet volume must be > 0.")

        old = float(self.metadata.get("fill_droplet_volume_nL", 10.0))

        # Preview before we apply, so we can report useful deltas after recompute
        prev = self.preview_fill_requantized(new_fill_droplet_nL)
        # Apply
        self.metadata["fill_droplet_volume_nL"] = new_fill_droplet_nL
        self.generate_experiment()

        # If wells are already assigned and you want the CSVs to reflect the new totals immediately:
        if write_keys_if_assigned and self._has_runtime_assignments():
            self.write_keys_now()

        self.unsaved_changes = True
        return {
            "old_fill_nL": old,
            "new_fill_nL": new_fill_droplet_nL,
            "total_drops_old": prev.get("total_drops_old"),
            "total_drops_new": prev.get("total_drops_new"),
            "total_drops_delta": prev.get("total_drops_delta"),
        }


    def read_progress_file(self, progress_file: str):
        import json
        self.progress_file_path = progress_file
        try:
            with open(progress_file, "r") as f:
                payload = json.load(f)
                if isinstance(payload, dict):
                    # strip metadata envelope key if present
                    payload.pop("__plate__", None)
                    # Backward-compatible legacy progress structure
                    self.progress_data = payload
                else:
                    self.progress_data = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.progress_data = {}

    def return_progress_data(self) -> Dict:
        import json
        if not self.progress_file_path:
            return {}
        try:
            with open(self.progress_file_path, "r") as f:
                payload = json.load(f)
                if isinstance(payload, dict):
                    payload.pop("__plate__", None)
                    return payload
                return {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def load_progress(self):
        """Apply progress.json into live ReactionComposition objects (requires runtime context)."""
        if self._runtime_well_plate is None:
            return
        # Plate compatibility check (for new structured progress payloads)
        try:
            with open(self.progress_file_path, "r") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and "__plate__" in payload and isinstance(payload["__plate__"], dict):
                plate = payload["__plate__"]
                expected_name = self._runtime_well_plate.get_current_plate_name()
                expected_rows = self._runtime_well_plate.get_num_rows()
                expected_cols = self._runtime_well_plate.get_num_cols()
                if (
                    plate.get("name") != expected_name
                    or int(plate.get("rows", -1)) != int(expected_rows)
                    or int(plate.get("columns", -1)) != int(expected_cols)
                ):
                    raise ValueError(
                        "progress.json plate metadata does not match current well plate "
                        f"({plate.get('name')} {plate.get('rows')}x{plate.get('columns')} vs "
                        f"{expected_name} {expected_rows}x{expected_cols})."
                    )
        except FileNotFoundError:
            pass
        data = self.return_progress_data()
        if not data:
            self.create_progress_file()
            return

        # Apply to each well's reaction
        for well_id, entry in data.items():
            well = self._runtime_well_plate.get_well(well_id)
            if well is None:
                continue
            rxn = well.get_assigned_reaction()
            if rxn is None or rxn.unique_id != entry.get("reaction_id"):
                continue
            for stock_id, rd in entry.get("reagents", {}).items():
                try:
                    reagent = rxn.get_reagent_by_id(stock_id)
                except KeyError:
                    continue
                reagent.added_droplets = rd.get("added_droplets", 0)
                reagent.completed = reagent.is_complete()
            if entry.get("completed"):
                # notify listeners if you want (well emits on record)
                pass

    # -----------------------------
    # Rename / duplicate
    # -----------------------------
    def rename_experiment(self, new_name: str) -> bool:
        """Rename experiment dir (if it does not already exist)."""
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_experiment_dir = os.path.join(script_dir, "Experiments")
        new_dir = os.path.join(base_experiment_dir, new_name)
        if os.path.exists(new_dir):
            return False
        os.rename(self.experiment_dir_path, new_dir)
        self.metadata["name"] = new_name
        self.experiment_dir_path = new_dir
        self.update_all_paths()
        self.save_experiment()
        return True

    def duplicate_experiment(self, new_name: str, new_experiment_path: str, copy_calibrations: bool = False) -> bool:
        """Copy just the design; progress is new; calibration optionally copied."""
        import os, json
        self.metadata["name"] = new_name
        self.experiment_dir_path = new_experiment_path
        if not os.path.exists(self.experiment_dir_path):
            os.makedirs(self.experiment_dir_path)
        self.update_all_paths()

        # also materialize the uploaded design CSV into the new folder, if any
        if self._uploaded_reactions is not None:
            self._materialize_uploaded_design_csv()

        self.save_experiment()
        self.create_progress_file()
        self.create_key_file()
        self.create_concentration_key_file()
        # calibration handling
        if not copy_calibrations:
            with open(self.calibration_file_path, "w") as f:
                f.write("{}")
        else:
            # if you have a manager, ask it to save here
            if self._calibration_manager is not None and hasattr(self._calibration_manager, "save_calibration_data"):
                self._calibration_manager.update_calibration_file_path(self.calibration_file_path)
                self._calibration_manager.save_calibration_data(self.calibration_file_path)
        return True

    # -----------------------------
    # Reset (fresh design session)
    # -----------------------------
    def reset_experiment_model(self):
        """Reset v2 design to a fresh state (keeps class methods)."""
        import time
        self.factors = []
        temp_name = "Untitled-" + time.strftime("%Y%m%d_%H%M%S")
        self.metadata = {
            "name": temp_name,
            "replicates": 1,
            "use_subset_design": False,   # <-- keep key consistent
            "reduction_factor": 1,
            "target_reaction_volume_nL": 500.0,
            "final_reaction_volume_nL": 500.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": self._default_fill_droplet_volume_nl(),
            "randomize_assignments": False,
            "random_seed": None,
            "start_row": 0,
            "start_col": 0,
        }
        self.plans_per_option.clear()
        self._stock_rows_cache.clear()
        self._fill_row_cache = None
        self._reactions_df = pd.DataFrame()
        self._last_worst_nonfill_volume_nL = None

        self.experiment_dir_path = None
        self.experiment_file_path = None
        self.progress_file_path = None
        self.progress_data = {}
        self.calibration_file_path = None
        self.key_file_path = None

        # clear any uploaded/manual reaction list state
        self._uploaded_reactions = None
        self._uploaded_design_source = None


        self.unsaved_changes = False
        self.stock_updated.emit()

class StockSolution(QObject):
    '''
    Represents a specific instance of a reagent at a certain concentration
    Each stock solution can be assigned to a printer head.
    '''
    def __init__(self, stock_id, reagent_name,concentration,units, required_volume=None):
        super().__init__()
        self.stock_id = stock_id
        self.reagent_name = reagent_name
        self.concentration = f"{float(concentration):.2f}"
        # self.concentration = concentration
        self.units = units
        self.required_volume = required_volume
        self.reagent_id = None
        self.display_name = None
        self.reagent_family = None
        self.glycerol_percent = None
        self.tags = []
        self.notes = ""
        self.intended_head_type_id = None
        self.intended_head_type_display_name = None
        self.intended_nominal_nozzle_diameter_um = None
        self.intended_head_type_tags = []
        self.intended_head_type_notes = ""

    def get_stock_id(self):
        return self.stock_id
    
    def get_reagent_name(self):
        return self.reagent_name
    
    def get_stock_concentration(self):
        return self.concentration
    
    def get_stock_name(self,new_line=False):
        if self.units == '--':
            return f"{self.reagent_name}"
        elif new_line:
            return f"{self.reagent_name}\n{self.concentration} {self.units}"
        else:
            return f"{self.reagent_name} - {self.concentration} {self.units}"

    def set_reagent_identity(
        self,
        *,
        reagent_id=None,
        display_name=None,
        reagent_family=None,
        glycerol_percent=None,
        tags=None,
        notes=None,
    ):
        self.reagent_id = reagent_id
        self.display_name = display_name
        self.reagent_family = reagent_family
        self.glycerol_percent = glycerol_percent
        self.tags = list(tags or [])
        self.notes = "" if notes is None else str(notes)

    def get_reagent_identity(self):
        return {
            "reagent_id": self.reagent_id,
            "display_name": self.display_name,
            "reagent_family": self.reagent_family,
            "glycerol_percent": self.glycerol_percent,
            "tags": list(self.tags or []),
            "notes": self.notes,
        }

    def set_intended_head_type(
        self,
        *,
        head_type_id=None,
        display_name=None,
        nominal_nozzle_diameter_um=None,
        tags=None,
        notes=None,
    ):
        self.intended_head_type_id = head_type_id
        self.intended_head_type_display_name = display_name
        self.intended_nominal_nozzle_diameter_um = nominal_nozzle_diameter_um
        self.intended_head_type_tags = list(tags or [])
        self.intended_head_type_notes = "" if notes is None else str(notes)

    def get_intended_head_type(self):
        return {
            "head_type_id": self.intended_head_type_id,
            "display_name": self.intended_head_type_display_name,
            "nominal_nozzle_diameter_um": self.intended_nominal_nozzle_diameter_um,
            "tags": list(self.intended_head_type_tags or []),
            "notes": self.intended_head_type_notes,
        }


class Reagent(QObject):
    '''
    Represents an amount of a stock solution that should be added to a specific reaction
    A reaction composition is comprised of one or more Reagents that when mixed together creates the target composition
    Contains the stock solution, the number of droplets needed and tracks how much of the reagent has been added
    '''
    def __init__(self, stock_solution, droplets):
        super().__init__()
        self.stock_solution = stock_solution
        self.target_droplets = droplets     # Number of droplets to be added to the reaction
        self.added_droplets = 0             # Number of droplets that have already been added
        self.completed = False              # States whether all required droplets have been added

    def get_target_droplets(self):
        return self.target_droplets
    
    def get_remaining_droplets(self):
        return self.target_droplets - self.added_droplets
    
    def add_droplets(self, droplets):
        self.added_droplets += droplets

    def is_complete(self):
        if self.added_droplets == self.target_droplets:
            self.completed = True
            return True
        else:
            self.completed = False
            return False

    def set_target_droplets(self, droplets: int, *, preserve_progress: bool = True):
        """Update the target count; optionally clamp or reset progress."""
        new_target = int(max(0, droplets))
        self.target_droplets = new_target
        if preserve_progress:
            # If we've already printed more than the new target, clamp down.
            self.added_droplets = min(self.added_droplets, self.target_droplets)
        else:
            self.added_droplets = 0
        self.completed = self.is_complete()
    
class StockSolutionManager(QObject):
    '''
    Manages all the stock solutions that are included in the experiment
    When a new stock solution is to be added, it creates a new instance of the StockSolution class and assigns it a unique id
    This class is mostly used to coordinate which stock solutions go to which printer head
    '''
    def __init__(self):
        super().__init__()
        self.stock_solutions = {}

    def add_all_stock_solutions(self,stock_solution_list):
        for stock_id in stock_solution_list:
            reagent_name, concentration_str, units = stock_id.split('_')
            concentration = float(concentration_str[:])  # Remove 'M' and convert to float
            if stock_id in self.stock_solutions.keys():
                print('Duplicate stock solution found:',stock_id)
            else:
                self.stock_solutions.update({stock_id:StockSolution(stock_id,reagent_name,concentration,units)})

    def add_stock_solution(self, reagent_name, concentration, units, required_volume=None):
        stock_id = self._make_stock_id(reagent_name, concentration, units)
        print('Adding stock solution:',stock_id)
        self.stock_solutions.update({
            stock_id: StockSolution(stock_id, reagent_name, float(concentration), units, required_volume=required_volume)
        })

    def get_stock_solution(self, reagent_name, concentration, units):
        """Retrieve a reagent-concentration pair."""
        stock_id = self._make_stock_id(reagent_name, concentration, units)
        return self.stock_solutions.get(stock_id)
        
    def get_stock_by_id(self, stock_id):
        return self.stock_solutions[stock_id]
    
    def get_all_stock_solutions(self):
        return self.stock_solutions.values()

    def get_stock_solution_names(self):
        return list(self.stock_solutions.keys())
    
    def get_formatted_from_stock_id(self,stock_id):
        stock = self.get_stock_by_id(stock_id)
        return stock.get_stock_name()

    def get_stock_solution_names_formated(self):
        return [stock.get_stock_name() for stock_id,stock in self.stock_solutions.items()]
    
    def get_stock_id_from_formatted(self,formatted_name):
        for stock_id,stock in self.stock_solutions.items():
            if formatted_name == stock.get_stock_name():
                return stock_id
        return None
    
    def clear_all_stock_solutions(self):
        self.stock_solutions = {}

    def _make_stock_id(self, reagent_name, concentration, units):
        conc_str = f"{float(concentration):.2f}"   # <-- 2 decimals, zero-padded
        return "_".join([reagent_name, conc_str, units])


class ReactionComposition(QObject):
    '''
    Represents a reaction composition which will be assigned to a well
    It is comprised of multiple Reagent objects which represent how many droplets of each stock solution need to be added to the reaction
    Each reaction composition should only have one Reagent instance per stock solution
    '''
    def __init__(self, unique_id):
        super().__init__()
        self.unique_id = unique_id
        self.reagents = {}  # Dictionary to hold Reagent objects with the required number of droplets
    
    def add_reagent(self, stock_solution,droplets):
        """
        Create an instance of the Reagent class using a StockSolution instance and the target number of droplets.
        Reagents are stored in a dictionary using the stock id to reference them
        """
        self.reagents.update({stock_solution.stock_id:Reagent(stock_solution,droplets)})
    
    def get_all_reagents(self):
        """Get all reagents and their concentrations in this reaction."""
        return self.reagents
    
    def get_all_target_droplets(self):
        return {stock_id: reagent.get_target_droplets() for stock_id, reagent in self.reagents.items()}

    def get_target_droplets_for_stock(self, stock_id):
        # If a stock isn’t part of this reaction, required droplets are 0
        r = self.reagents.get(stock_id)
        return r.get_target_droplets() if r is not None else 0

    def get_remaining_droplets_for_stock(self, stock_id):
        r = self.reagents.get(stock_id)
        return r.get_remaining_droplets() if r is not None else 0

    def record_stock_print(self, stock_id, droplets):
        # Ignore prints for stocks not present in this reaction
        r = self.reagents.get(stock_id)
        if r is not None:
            r.add_droplets(droplets)

    def check_stock_complete(self, stock_id):
        # If a stock isn’t part of this reaction, it’s “complete” by definition
        r = self.reagents.get(stock_id)
        return True if r is None else r.is_complete()
    
    def check_all_complete(self):
        for reagent in self.reagents.values():
            if not reagent.is_complete():
                return False
        else:
            return True
        
    def reset_all_reagents(self):
        for reagent in self.reagents.values():
            reagent.added_droplets = 0
            reagent.completed = False

    def reset_reagent_by_id(self,stock_id):
        self.reagents[stock_id].added_droplets = 0
        self.reagents[stock_id].completed = False

    def get_reagent_by_id(self,stock_id):
        return self.reagents[stock_id]

    def set_reagent_target_droplets(self, stock_id: str, droplets: int, *, preserve_progress: bool = True) -> bool:
        r = self.reagents.get(stock_id)
        if r is None:
            # We assume the reagent set doesn't change when dv changes; silently ignore.
            return False
        r.set_target_droplets(droplets, preserve_progress=preserve_progress)
        return True
    


class ReactionCollection(QObject):
    '''
    Represents the collection of all reactions that make up an experiment.
    The reaction collection contains all the specific reaction composition objects.
    It also allows for general information to be extracted from the pool of reactions.
    '''
    def __init__(self):
        super().__init__()
        self.reactions = {}  # Dictionary to hold ReactionComposition objects by name

    def add_reaction(self, reaction):
        """Add a unique reaction to the collection."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must add a ReactionComposition object.")
        if reaction.unique_id not in self.reactions:
            self.reactions[reaction.unique_id] = reaction
        else:
            raise ValueError(f"Reaction '{reaction.name}' already exists in the collection.")

    def remove_reaction(self, name):
        """Remove a reaction from the collection by its name."""
        if name in self.reactions:
            del self.reactions[name]
        else:
            raise ValueError(f"Reaction '{name}' not found in the collection.")

    def is_empty(self):
        """Check if the collection is empty."""
        return len(self.reactions) == 0

    def get_reaction(self, name):
        """Get a reaction by its name."""
        return self.reactions.get(name, None)

    def get_all_reactions(self):
        """Get all reactions in the collection."""
        return list(self.reactions.values())
    
    def get_max_droplets(self, stock_id):
        """Get the maximum concentration of a specific reagent across all reactions."""
        max_droplets = None
        for reaction in self.get_all_reactions():
            droplets = reaction.get_target_droplets_for_stock(stock_id)
            if droplets is not None:
                if max_droplets is None or droplets > max_droplets:
                    max_droplets = droplets
        return max_droplets

    def clear_all_reactions(self):
        """Clear all reactions from the collection."""
        self.reactions = {}

    # ---- helpers -------------------------------------------------
    @staticmethod
    def _stock_id_from_tuple(reagent_name: str, concentration: float, units: str) -> str:
        # Must match StockSolutionManager._make_stock_id format exactly
        conc_str = f"{float(concentration):.2f}"
        return "_".join([reagent_name, conc_str, units])

    def _reaction_by_index(self, index: int) -> ReactionComposition | None:
        rxns = list(self.reactions.values())
        if 0 <= index < len(rxns):
            return rxns[index]
        return None

    # ---- APIs ExperimentModel._rebind_runtime_assignments_to_current_plans() tries ----
    def set_reaction_items_for_index(self, index: int, items: list[tuple[str, float, str, int]],
                                     *, preserve_progress: bool = True) -> bool:
        """
        items: [(reagent_name, stock_conc, units, drops), ...] for one reaction.
        Only updates targets for reagents that already exist in the reaction.
        """
        rxn = self._reaction_by_index(index)
        if rxn is None:
            return False

        # Update provided items
        for reagent_name, conc, units, drops in items:
            sid = self._stock_id_from_tuple(reagent_name, conc, units)
            rxn.set_reagent_target_droplets(sid, int(drops), preserve_progress=preserve_progress)

        # Re-validate completion flags for this reaction
        rxn.check_all_complete()
        return True

    def reset_from_iterator(self, iterator, *, preserve_progress: bool = True) -> bool:
        """Batch update: iterator yields items for reaction 0, 1, 2, ..."""
        for idx, items in enumerate(iterator):
            self.set_reaction_items_for_index(idx, items, preserve_progress=preserve_progress)
        return True

    def replace_all_reaction_items(self, items_list: list[list[tuple[str, float, str, int]]],
                                   *, preserve_progress: bool = True) -> bool:
        """Batch update from a materialized list."""
        for idx, items in enumerate(items_list):
            self.set_reaction_items_for_index(idx, items, preserve_progress=preserve_progress)
        return True
    
class Well(QObject):
    '''
    Represents a single well in a well plate.
    The object is instantiated with an identifier such as "A1" or "B2".
    Each well can only be assigned a single reaction composition.
    '''
    state_changed = Signal(str)  # Signal to notify when the state of the well changes, sending the well ID
    @staticmethod
    def row_label_to_index(row_label: str) -> int:
        """Convert Excel-style row label (A..Z, AA..) to zero-based index."""
        s = str(row_label or "").strip().upper()
        if not s or not s.isalpha():
            raise ValueError(f"Invalid row label '{row_label}'.")
        value = 0
        for ch in s:
            value = value * 26 + (ord(ch) - ord('A') + 1)
        return value - 1

    @staticmethod
    def index_to_row_label(row_index: int) -> str:
        """Convert zero-based row index to Excel-style row label."""
        if int(row_index) < 0:
            raise ValueError(f"Row index must be >= 0, got {row_index}.")
        n = int(row_index) + 1
        out = []
        while n > 0:
            n, rem = divmod(n - 1, 26)
            out.append(chr(ord('A') + rem))
        return ''.join(reversed(out))

    @staticmethod
    def parse_well_id(well_id: str) -> tuple[str, int]:
        s = str(well_id or "").strip().upper()
        m = re.fullmatch(r"([A-Z]+)(\d+)", s)
        if not m:
            raise ValueError(f"Invalid well ID '{well_id}'.")
        row_label, col_s = m.groups()
        col = int(col_s)
        if col <= 0:
            raise ValueError(f"Invalid column index in well ID '{well_id}'.")
        return row_label, col

    def __init__(self, well_id):
        super().__init__()
        self.well_id = str(well_id).strip().upper()  # Unique identifier for the well (e.g., "A1", "AA2")
        self.row, self.col = self.parse_well_id(self.well_id)
        self.row_num = self.row_label_to_index(self.row)  # Row number (0-indexed)
        self.assigned_reaction = None  # The reaction assigned to this well
        self.coordinates = None  # The x, y, and z coordinates of the well on the plate

    def assign_reaction(self, reaction):
        """Assign a reaction to the well."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must assign a ReactionComposition object.")
        self.assigned_reaction = reaction

    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the well."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the well."""
        return self.coordinates

    def get_target_droplets(self,stock_id):
        return self.assigned_reaction.get_target_droplets_for_stock(stock_id)

    def get_remaining_droplets(self,stock_id):
        return self.assigned_reaction.get_remaining_droplets_for_stock(stock_id)
    
    def get_assigned_reaction(self):
        return self.assigned_reaction

    def record_stock_print(self,stock_id,droplets):
        self.assigned_reaction.record_stock_print(stock_id,droplets)
        print('emitting state changed',self.well_id)
        self.state_changed.emit(self.well_id)

    def check_stock_complete(self,stock_id):
        return self.assigned_reaction.check_stock_complete(stock_id)

    def check_all_complete(self):
        return self.assigned_reaction.check_all_complete() if self.assigned_reaction else True

class WellPlate(QObject):
    well_state_changed_signal = Signal(str)  # Signal to notify when the state of a well changes, sending the well ID
    clear_all_wells_signal = Signal()  # Signal to notify when all wells are cleared
    plate_format_changed_signal = Signal()  # Signal to notify when the well plate is updated
    plate_summary_changed_signal = Signal(str, int, int)  # name, rows, cols

    def __init__(self, all_plate_data,plates_path):
        super().__init__()
        self.all_plate_data = all_plate_data
        self.plates_path = plates_path
        self.current_plate_data = self.get_default_plate_data()
        self.calibrations = self.current_plate_data['calibrations']
        self.rows = self.current_plate_data['rows']
        self.cols = self.current_plate_data['columns']
        self.wells = self.create_wells()
        self.excluded_wells = set()

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

    @staticmethod
    def _normalize_well_id(well_id):
        row, col = Well.parse_well_id(str(well_id).strip().upper())
        return f"{row}{col}"

    @staticmethod
    def _well_id_from_row_col(row: int, col: int) -> str:
        return f"{Well.index_to_row_label(int(row))}{int(col) + 1}"

    def normalize_excluded_wells(self):
        """Canonicalize exclusions to a set[str] of existing well IDs."""
        normalized = set()
        for item in set(getattr(self, "excluded_wells", set())):
            if isinstance(item, Well):
                wid = item.well_id
            else:
                try:
                    wid = self._normalize_well_id(item)
                except ValueError:
                    continue
            if wid in self.wells:
                normalized.add(wid)
        self.excluded_wells = normalized
        return normalized

    def validate_start_position(self, start_row=0, start_col=0):
        if int(start_row) < 0 or int(start_row) >= self.rows:
            raise ValueError(
                f"start_row {start_row} out of bounds for plate with {self.rows} rows."
            )
        if int(start_col) < 0 or int(start_col) >= self.cols:
            raise ValueError(
                f"start_col {start_col} out of bounds for plate with {self.cols} columns."
            )

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']

    def iter_well_ids(self):
        """Yield well IDs in deterministic row-major order."""
        for row in range(self.rows):
            for col in range(self.cols):
                yield self._well_id_from_row_col(row, col)

    def iter_rows(self):
        """Yield row labels in plate order (A..Z, AA..)."""
        for row in range(self.rows):
            yield Well.index_to_row_label(row)
    
    def get_all_current_plate_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates
    
    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def get_plate_data_by_name(self, plate_name):
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                return plate_data
        raise ValueError(f"Plate format '{plate_name}' not found.")        

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        plate_name = self.get_current_plate_name()
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                new_cals = self.temp_calibration_data.copy()
                plate_data['calibrations'] = new_cals
                self.current_plate_data['calibrations'] = new_cals  # be explicit
                self.calibrations = new_cals
                self.temp_calibration_data.clear()
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")

    def save_calibrations_to_file(self, file_path=None):
        """Save the current calibration data to a JSON file."""
        path = file_path or self.plates_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"

        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.all_plate_data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)  # atomic on POSIX/Windows 10+
            # print(f"Calibration data saved to {path}")
        except Exception as e:
            # If something goes wrong, don't hide it—surface it so you can fix it.
            print(f"Error saving calibration data to file '{path}': {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def get_default_plate_data(self):
        """Get the data for the plate set to default"""
        for plate_data in self.all_plate_data:
            if plate_data['default']:
                return plate_data

    def get_all_plate_names(self):
        return [plate_data['name'] for plate_data in self.all_plate_data]
    
    def get_current_plate_name(self):
        return self.current_plate_data['name']
    
    def create_wells(self):
        """Create wells based on the plate format."""
        wells = {}
        for row in range(self.rows):
            for col in range(self.cols):
                well_id = self._well_id_from_row_col(row, col)
                well = Well(well_id)
                well.state_changed.connect(self.well_state_changed)
                wells[well_id] = well
        return wells
    
    def set_plate_format(self, plate_name):
        """Set the plate format based on the selected name."""
        for plate_data in self.all_plate_data:
            if plate_data['name'] == plate_name:
                self.current_plate_data = plate_data
                self.rows = plate_data['rows']
                self.cols = plate_data['columns']
                self.wells = self.create_wells()
                self.calibrations = plate_data['calibrations']
                self.calibration_applied = False
                self.normalize_excluded_wells()
                self.apply_calibration_data()
                self.plate_format_changed_signal.emit()
                self.plate_summary_changed_signal.emit(self.get_current_plate_name(), self.rows, self.cols)
                return
        raise ValueError(f"Plate format '{plate_name}' not found.")
    
    def get_plate_dimensions(self):
        return self.rows,self.cols
    
    def get_coords(self,coords):
        return np.array(list(coords.values()))
    
    def calculate_plate_matrix(self):
        """Calculate the transformation matrix for the plate."""
        self.corners = np.array([
            [self.get_coords(self.calibrations['top_left'])[0:2]],
            [self.get_coords(self.calibrations['top_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_right'])[0:2]],
            [self.get_coords(self.calibrations['bottom_left'])[0:2]]
        ], dtype = "float32")

        self.max_columns = self.cols - 1
        self.max_rows = self.rows - 1
        self.plate_width = self.max_columns * self.current_plate_data['spacing']
        self.plate_depth = self.max_rows * self.current_plate_data['spacing']

        self.plate_dimensions = np.array([
            [0, 0],
            [0, self.plate_width],
            [self.plate_depth, self.plate_width],
            [self.plate_depth, 0]
        ], dtype = "float32")

        self.generate_transformation_matrix()

        self.row_z_step = (self.calibrations['bottom_left']['Z'] - self.calibrations['top_left']['Z']) / (self.rows)
        self.col_z_step =  (self.calibrations['top_right']['Z'] - self.calibrations['top_left']['Z']) / (self.cols)

        well_coords_df = self.calculate_all_well_positions()
        return well_coords_df

    def generate_transformation_matrix(self):
        '''
        Performs a 4-point transformation of the coordinate plane using the
        experimentally derived plate corners. This takes the machine coordinates
        and finds the matrix required to convert them into the coordinate plane
        that matches the defined geometry of the plate. This matrix can then be
        reversed and used to take the positions where wells should be and
        convert them into the corresponding dobot coordinates.

        This transformation accounts for the deviations in the machine coordinate
        system but only applies to the X and Y dimensions.
        '''
        self.trans_matrix = cv2.getPerspectiveTransform(self.corners, self.plate_dimensions)
        self.inv_trans_matrix = np.linalg.pinv(self.trans_matrix)
    
    def correct_xy_coords(self,x,y):
        '''
        Uses the transformation matrix to correct the XY coordinates
        '''
        target = np.array([[x,y]], dtype = "float32")
        target_transformed = cv2.perspectiveTransform(np.array(target[None,:,:]), self.inv_trans_matrix)
        return target_transformed[0][0]

    def get_well_coords(self,row,column):
        '''
        Uses the well indices to determine the dobot coordinates of the well
        '''
        x,y = self.correct_xy_coords(row*self.current_plate_data['spacing'],column*self.current_plate_data['spacing'])
        z = self.calibrations['top_left']['Z'] + (row * self.row_z_step) + (column * self.col_z_step)
        x = int(round(x,0))
        y = int(round(y,0))
        z = int(round(z,0))
        return {'X':x, 'Y':y, 'Z':z}
    
    def calculate_all_well_positions(self):
        # Create an empty list for the well positions
        well_positions = []

        # Iterate over all the rows and columns of the plate
        for row in range(self.rows):
            for column in range(self.cols):
                # Calculate the corrected coordinates for the well
                coords = self.get_well_coords(row, column)

                # Add the well position to the list
                well_positions.append({
                    'row': row,
                    'column': column,
                    'X': coords['X'],
                    'Y': coords['Y'],
                    'Z': coords['Z']
                })

        # Create a DataFrame from the list
        well_positions_df = pd.DataFrame(well_positions)
        return well_positions_df
    
    def assign_well_coordinates(self, well_id, x, y,z):
        """Assign coordinates to a specific well."""
        well = self.wells.get(well_id)
        if well is not None:
            well.assign_coordinates(x,y,z)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def assign_well_coordinates_by_row_col(self, row, col, x, y,z):
        """Assign coordinates to a well by its row and column."""
        well_id = f"{chr(row + 65)}{col + 1}"
        self.assign_well_coordinates(well_id, x, y,z)

    def assign_all_well_coordinates(self, well_coords_df):
        """Assign coordinates to all wells in the plate."""
        for i,row in well_coords_df.iterrows():
            well_id = f"{chr(row['row'] + 65)}{row['column'] + 1}"
            self.assign_well_coordinates(well_id, row['X'], row['Y'],row['Z'])

    def apply_calibration_data(self):
        if len(list(self.calibrations)) < 4:
            self.calibration_applied = False
            #print(f"Calibration is incomplete. Need at least 4 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            well_coords_df = self.calculate_plate_matrix()
            self.assign_all_well_coordinates(well_coords_df)
            self.calibration_applied = True

    def get_num_rows(self):
        """Get the number of rows in the plate."""
        return self.rows
    
    def get_num_cols(self):
        """Get the number of columns in the plate."""
        return self.cols

    def exclude_well(self, well_id):
        """Exclude a well from being used."""
        wid = self._normalize_well_id(well_id)
        if wid in self.wells:
            self.excluded_wells.add(wid)
        else:
            raise ValueError(f"Well '{wid}' does not exist in the plate.")

    def include_well(self, well_id):
        """Include an excluded well back into use."""
        self.excluded_wells.discard(self._normalize_well_id(well_id))

    def get_well(self, well_id):
        """Retrieve a specific well by its ID."""
        try:
            wid = self._normalize_well_id(well_id)
        except ValueError:
            return None
        return self.wells.get(wid, None)

    def zigzag_order(self,wells, fill_by="columns"):
        """
        Return wells ordered in a zigzag pattern.

        Args:
            wells (list of Well): The list of wells to be ordered.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: The list of wells ordered in a zigzag pattern.
        """
        def row_to_num(row):
            """Convert the row letter to a number (e.g., 'A' -> 0, 'B' -> 1)."""
            return Well.row_label_to_index(row)

        if fill_by == "rows":
            # Sort by row first (converted to number), and by column within each row, alternating the column order
            wells.sort(key=lambda w: (row_to_num(w.row), w.col if row_to_num(w.row) % 2 == 0 else -w.col))
        else:  # fill_by == "columns"
            # Sort by column first, and by row (converted to number) within each column, starting with A1
            wells.sort(key=lambda w: (w.col, -row_to_num(w.row) if w.col % 2 == 0 else row_to_num(w.row)))

        return wells

    def get_available_wells(self, fill_by="columns",start_row=0,start_col=0):
        """
        Get a list of available wells, sorted by rows or columns in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of available wells.
        """
        if fill_by not in ["rows", "columns"]:
            raise ValueError("fill_by must be 'rows' or 'columns'.")
        self.validate_start_position(start_row=start_row, start_col=start_col)
        self.normalize_excluded_wells()

        available_wells = [well for well in self.wells.values() if well.well_id not in self.excluded_wells and well.assigned_reaction is None]
        available_wells = [well for well in available_wells if well.row_num >= start_row and well.col >= start_col+1]
        return self.zigzag_order(available_wells, fill_by=fill_by)
    
    def get_all_wells(self):
        """Get a list of all wells."""
        return list(self.wells.values())

    def clear_all_wells(self):
        """Clear all wells and reset their status."""
        self.wells = {}
        self.excluded_wells = set()
        self.wells = self.create_wells()
        self.clear_all_wells_signal.emit()

    def clear_all_reaction_assignments(self):
        """
        Remove the assigned reaction from every well without recreating the wells
        or touching calibration / excluded_well state.
        """
        for well in self.wells.values():
            well.assigned_reaction = None

    def assign_reactions_to_specific_wells(self, reactions, well_ids):
        """
        Assign each reaction to an explicit well ID.

        Args:
            reactions (list[ReactionComposition]): reactions in the desired order.
            well_ids (list[str]): same-length list of well IDs (e.g. ['A1','B1',...]).

        Returns:
            dict: {reaction.unique_id: well_id}
        """
        if len(reactions) != len(well_ids):
            raise ValueError(
                f"Number of reactions ({len(reactions)}) does not match "
                f"number of well IDs ({len(well_ids)})."
            )

        reaction_assignment = {}

        for reaction, well_id in zip(reactions, well_ids):
            wid = str(well_id).strip().upper()
            well = self.wells.get(wid)

            if well is None:
                raise ValueError(f"Well '{wid}' does not exist in the current plate.")

            if wid in self.excluded_wells:
                raise ValueError(f"Well '{wid}' is in the excluded_wells set.")

            if well.assigned_reaction is not None:
                raise ValueError(
                    f"Well '{wid}' already has an assigned reaction "
                    f"('{well.assigned_reaction.unique_id}')."
                )

            well.assign_reaction(reaction)
            reaction_assignment[reaction.unique_id] = wid

        return reaction_assignment

    def reset_all_wells_for_stock(self,stock_id):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_reagent_by_id(stock_id)
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')
        
    def reset_all_wells(self):
        for well in self.wells.values():
            if well.assigned_reaction is not None:
                well.assigned_reaction.reset_all_reagents()
                # well.state_changed.emit(well.well_id)
        self.well_state_changed_signal.emit('all')

    def get_plate_status(self):
        """Get the status of the entire well plate."""
        status = {}
        for well_id, well in self.wells.items():
            status[well_id] = well.get_status()
        return status

    def assign_reactions_to_wells(self, reactions, fill_by="columns",start_row=0,start_col=0):
        """
        Systematically assign reactions to available wells.

        Args:
            reactions (list of ReactionComposition): The reactions to assign to wells.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            dict: A dictionary mapping reaction names to well IDs.
        """
        available_wells = self.get_available_wells(fill_by=fill_by,start_row=start_row,start_col=start_col)
        reaction_assignment = {}

        if len(reactions) > len(available_wells):
            raise ValueError("Not enough available wells to assign all reactions.")
        #print(f"Assigning {len(reactions)} reactions to {len(available_wells)} available wells.")
        for i, reaction in enumerate(reactions):
            well = available_wells[i]
            well.assign_reaction(reaction)
            reaction_assignment[reaction.unique_id] = well.well_id
            # print(f"Assigned reaction '{reaction.unique_id}' to well '{well.well_id}'.")

        return reaction_assignment
    
    def get_all_wells_with_reactions(self, fill_by="columns"):
        """
        Get all wells that have been assigned a reaction, sorted in a zigzag pattern.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of wells with assigned reactions.
        """
        wells_with_reactions = [well for well in self.wells.values() if well.assigned_reaction is not None]

        return self.zigzag_order(wells_with_reactions, fill_by=fill_by)
    
    def well_state_changed(self, well_id):
        """Handle changes in the state of a well."""
        self.well_state_changed_signal.emit(well_id)

class PrinterHead(QObject):
    """
    Represents a printer head in a system.
    reagent (str): The reagent in the printer head.
    concentration (float): The concentration of the reagent.
    color (str): The color of the printer head.
    Methods:
    change_reagent(new_reagent): Changes the reagent in the printer head.
    change_concentration(new_concentration): Changes the concentration of the reagent.
    change_color(new_color): Changes the color of the printer head.
    """
    volume_changed_signal = Signal(str) # Signal to notify when the volume of the printer head changes
    def __init__(self, stock_solution,color='Blue',calibration_chip=False):
        super().__init__()
        self.stock_solution = stock_solution
        self.color = color
        self.confirmed = False
        self.completed = False
        self.current_volume = None
        self.effective_resistance = None
        self.bias = None
        self.target_droplet_volume = None
        self.calibration_chip = calibration_chip
        self.predictive_model = None
        self.resistance_pulse_width = None
        self.printer_head_id = None
        self.head_type_id = None
        self.display_name = None
        self.nominal_nozzle_diameter_um = None
        self.measured_nozzle_diameter_um = None
        self.manufacturer_batch = None
        self.identity_tags = []
        self.identity_notes = ""

    def record_droplet_volume_lost(self,droplet_count):
        if self.target_droplet_volume is not None:
            self.current_volume -= (droplet_count * self.target_droplet_volume) / 1000
            self.volume_changed_signal.emit(self.stock_solution.get_stock_id())
        else:
            print('No target droplet volume set for printer head:',self.stock_solution.get_stock_id())

    def set_absolute_volume(self,volume):            
        self.current_volume = volume
        self.volume_changed_signal.emit(self.stock_solution.get_stock_id())

    def change_volume(self,volume):
        if self.current_volume is None:
            self.current_volume = volume
        self.current_volume += volume
        self.volume_changed_signal.emit(self.stock_solution.get_stock_id())

    def is_calibration_chip(self):
        return self.calibration_chip
    
    def get_current_volume(self):
        return self.current_volume
    
    def get_target_droplet_volume(self):
        return self.target_droplet_volume

    def get_stock_solution(self):
        return self.stock_solution

    def get_stock_id(self):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_stock_id()
    
    def get_reagent_name(self):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_reagent_name()
    
    def get_stock_concentration(self):
        if self.stock_solution is None:
            return '--'
        return self.stock_solution.get_stock_concentration()
    
    def get_stock_name(self,new_line=False):
        if self.stock_solution is None:
            return 'Calibration'
        return self.stock_solution.get_stock_name(new_line=new_line)

    def get_color(self):
        return self.color

    def change_stock_solution(self, stock_solution):
        self.stock_solution = stock_solution
    
    def change_color(self, new_color):
        self.color = new_color

    def mark_complete(self):
        self.completed = True

    def mark_incomplete(self):
        self.completed = False

    def check_complete(self,well_plate):
        '''Check the stock solution to see if all droplets have been added'''
        stock_id = self.get_stock_id()
        print('Checking stock complete:',stock_id)
        for well in well_plate.get_all_wells():
            if well.assigned_reaction is not None:
                if not well.check_stock_complete(stock_id):
                    self.mark_incomplete()
                    return False
        if not self.calibration_chip:
            self.mark_complete()
        return True

    def check_calibration_complete(self):
        '''Check if the calibration data has been set for the printer head'''
        if self.effective_resistance is not None and self.bias is not None and self.target_droplet_volume is not None and self.predictive_model is not None and self.resistance_model is not None:
            return True
        else:
            return False
    
    def set_calibration_data(self, resistance, bias, target_droplet_volume,predictive_model,resistance_model,resistance_pulse_width):
        #print(f'Calibration data set for printer head {self.stock_solution.get_stock_id()}, R:{resistance}, B:{bias}, V:{target_droplet_volume}')
        self.effective_resistance = resistance
        self.bias = bias
        self.target_droplet_volume = target_droplet_volume
        self.predictive_model = predictive_model
        self.resistance_model = resistance_model
        self.resistance_pulse_width = resistance_pulse_width

    def get_prediction_data(self):
        return self.current_volume,self.effective_resistance, self.target_droplet_volume, self.bias, self.predictive_model, self.resistance_pulse_width

    def set_identity_metadata(
        self,
        *,
        printer_head_id=None,
        head_type_id=None,
        display_name=None,
        nominal_nozzle_diameter_um=None,
        measured_nozzle_diameter_um=None,
        manufacturer_batch=None,
        tags=None,
        notes=None,
    ):
        self.printer_head_id = printer_head_id
        self.head_type_id = head_type_id
        self.display_name = display_name
        self.nominal_nozzle_diameter_um = nominal_nozzle_diameter_um
        self.measured_nozzle_diameter_um = measured_nozzle_diameter_um
        self.manufacturer_batch = manufacturer_batch
        self.identity_tags = list(tags or [])
        self.identity_notes = "" if notes is None else str(notes)

    def get_identity_metadata(self):
        return {
            "printer_head_id": self.printer_head_id,
            "head_type_id": self.head_type_id,
            "display_name": self.display_name,
            "nominal_nozzle_diameter_um": self.nominal_nozzle_diameter_um,
            "measured_nozzle_diameter_um": self.measured_nozzle_diameter_um,
            "manufacturer_batch": self.manufacturer_batch,
            "tags": list(self.identity_tags or []),
            "notes": self.identity_notes,
        }


class PrinterHeadManager(QObject):
    """
    Manages all printer heads in the system, including tracking, assignment, and swapping.

    Attributes:
    - printer_heads (list): List of all printer heads created from the reaction collection.
    - assigned_printer_heads (dict): Mapping of slot numbers to assigned printer heads.
    - unassigned_printer_heads (list): List of printer heads that have not yet been assigned to any slot.
    """
    volume_changed_signal = Signal()
    def __init__(self,color_dict,rack_model):
        super().__init__()
        self.print_head_colors = color_dict
        self.rack_model = rack_model
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []
        self.create_calibration_chip()
        calibration_chip = self.get_calibration_chip()
        self.swap_printer_head(4,calibration_chip)


    def create_printer_heads(self, stock_solutions_manager):
        """
        Create printer heads based on the reagents and concentrations in the reaction collection.
        
        Args:
        - reaction_collection (ReactionCollection): The collection of reactions from which to create printer heads.
        """
        stock_solutions = stock_solutions_manager.get_all_stock_solutions()
        for stock_solution in stock_solutions:
            printer_head = PrinterHead(stock_solution, color=self.generate_color())
            printer_head.volume_changed_signal.connect(self.volume_changed)
            self.printer_heads.append(printer_head)
            self.unassigned_printer_heads.append(printer_head)
        #print(f"Created {len(self.printer_heads)} printer heads.")

    def create_calibration_chip(self):
        '''Create a calibration chip printer head'''
        calibration_chip = PrinterHead(None,color="#000000",calibration_chip=True)
        self.printer_heads.append(calibration_chip)
        self.unassigned_printer_heads.append(calibration_chip)
        print('Created calibration chip printer head.')

    def get_calibration_chip(self):
        for printer_head in self.printer_heads:
            if printer_head.is_calibration_chip():
                print('Found calibration chip printer head')
                return printer_head
        print('No calibration chip printer head found.')
        return None

    def volume_changed(self,stock_id):
        print(f'Volume changed for printer head {stock_id}')
        self.volume_changed_signal.emit()


    def assign_printer_head_to_slot(self, slot_number):
        """
        Assign an available printer head to a specified slot in the rack.

        Args:
        - slot_number (int): The slot number where the printer head should be assigned.
        - rack_model (RackModel): The rack model where the slot is located.
        
        Returns:
        - bool: True if a printer head was successfully assigned, False if no more unassigned printer heads are available.
        """
        if self.unassigned_printer_heads:
            printer_head = self.unassigned_printer_heads.pop(0)
            self.rack_model.update_slot_with_printer_head(slot_number, printer_head)
            self.assigned_printer_heads[slot_number] = printer_head
            print(f"Assigned printer head '{printer_head.get_stock_id()}' to slot {slot_number}.")
            return True
        else:
            print("No more unassigned printer heads available.")
            return False

    def swap_printer_head(self, slot_number, new_printer_head):
        """
        Swap the printer head in the specified slot with the provided unassigned printer head.
        """
        old_printer_head = self.rack_model.slots[slot_number].printer_head
        if old_printer_head:
            self.unassigned_printer_heads.append(old_printer_head)
            self.unassigned_printer_heads.remove(new_printer_head)
            self.rack_model.update_slot_with_printer_head(slot_number, new_printer_head)
            self.assigned_printer_heads[slot_number] = new_printer_head
            print(f"Swapped printer head in slot {slot_number} with '{new_printer_head.get_stock_id()}'.")
        else:
            self.rack_model.update_slot_with_printer_head(slot_number, new_printer_head)
            self.assigned_printer_heads[slot_number] = new_printer_head
            self.unassigned_printer_heads.remove(new_printer_head)
            print(f"No printer head in slot {slot_number} to swap.")


    def generate_color(self):
        """
        Generate a color for the printer head. This is a placeholder function.
        
        Returns:
        - str: The color code or name.
        """
        colors = list(self.print_head_colors.values())
        return colors[len(self.printer_heads) % len(colors)]

    def get_all_printer_heads(self):
        """
        Get all printer heads managed by this class.

        Returns:
        - list: List of all printer heads.
        """
        return self.printer_heads

    def get_unassigned_printer_heads(self):
        """
        Get all unassigned printer heads.

        Returns:
        - list: List of unassigned printer heads.
        """
        return self.unassigned_printer_heads

    def get_assigned_printer_heads(self):
        """
        Get all assigned printer heads.

        Returns:
        - dict: Dictionary mapping slot numbers to assigned printer heads.
        """
        return self.assigned_printer_heads
    
    def get_printer_head_by_id(self, stock_id):
        for printer_head in self.printer_heads:
            if printer_head.get_stock_id() == stock_id:
                return printer_head
        return None
    
    def clear_all_printer_heads(self):
        """
        Clear all printer heads and reset the assignment status.
        """
        self.printer_heads = []
        self.assigned_printer_heads = {}
        self.unassigned_printer_heads = []

class Slot(QObject):
    """
    Represents a slot in a system.

    Attributes:
        number (int): The slot number.
        printer_head (PrinterHead): The printer head in the slot.
        confirmed (bool): Indicates if the slot has been confirmed.
    """

    def __init__(self, number, printer_head):
        super().__init__()
        self.number = number
        self.printer_head = printer_head
        self.confirmed = False
        self.locked = False
        self.coordinates = None

    def set_locked(self, locked):
        self.locked = locked

    def is_locked(self):
        return self.locked
    
    def assign_coordinates(self, x, y,z):
        """Assign coordinates to the slot."""
        self.coordinates = {'X':x, 'Y':y, 'Z':z}

    def get_coordinates(self):
        """Get the coordinates of the slot."""
        return self.coordinates
    
    def change_printer_head(self, new_printer_head,returned=False):
        self.printer_head = new_printer_head
        if not returned:
            self.unconfirm()
    
    def confirm(self):
        """
        Confirms the slot.
        """
        self.confirmed = True

    def unconfirm(self):
        """
        Unconfirms the slot.
        """
        self.confirmed = False


class RackModel(QObject):
    """
    Model for all data related to the rack state.

    Attributes:
    - slots (list of Slot): List of slots in the rack.
    - gripper_printer_head (PrinterHead): The printer head currently held by the gripper.
    - gripper_slot_number (int): The original slot number from which the printer head was loaded.

    Signals:
    - slot_updated: Emitted when a slot is updated.
    - slot_confirmed: Emitted when a slot is confirmed.
    - gripper_updated: Emitted when the gripper state changes.
    - error_occurred: Emitted when an invalid operation is attempted.
    """

    slot_updated = Signal()
    gripper_updated = Signal()
    error_occurred = Signal(str)
    rack_calibration_updated_signal = Signal()

    def __init__(self, num_slots,location_data=None):
        super().__init__()
        self.slots = [Slot(i, None) for i in range(num_slots)]
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        # --- expected rack state (used for planning / queuing) ---
        self.expected_slot_printer_heads = [None for _ in range(num_slots)]
        self.expected_gripper_printer_head = None
        self.expected_gripper_slot_number = None

        self.calibrations = {}
        if location_data is not None:
            self.process_location_data(location_data)

        self.calibration_applied = False
        self.temp_calibration_data = {}
    
        self.apply_calibration_data()

        # keep expected in sync on startup
        self.sync_expected_to_actual()

    def sync_expected_to_actual(self):
        """Force expected rack contents to match the current (actual) rack model."""
        self.expected_slot_printer_heads = [s.printer_head for s in self.slots]
        self.expected_gripper_printer_head = self.gripper_printer_head
        self.expected_gripper_slot_number = self.gripper_slot_number

    def _get_state(self, use_expected: bool):
        if use_expected:
            slot_heads = self.expected_slot_printer_heads
            gripper_head = self.expected_gripper_printer_head
            gripper_slot = self.expected_gripper_slot_number
        else:
            slot_heads = [s.printer_head for s in self.slots]
            gripper_head = self.gripper_printer_head
            gripper_slot = self.gripper_slot_number
        return slot_heads, gripper_head, gripper_slot

    def apply_calibration_data(self):
        if self.calibrations['rack_position_Left'] == {} or self.calibrations['rack_position_Right'] == {}:
            self.calibration_applied = False
            #print(f"Calibration is incomplete. Need at least 2 calibration points, but only {len(list(self.calibrations))} provided.")
            return
        else:
            slot_positions = self.calculate_slot_positions()
            self.assign_slot_positions(slot_positions)
            self.calibration_applied = True
        
    def calculate_slot_positions(self):
        '''
        Calculate the positions of the slots based on the calibration data
        '''
        slot_positions = []
        left_calibration = self.calibrations['rack_position_Left']
        right_calibration = self.calibrations['rack_position_Right']

        x_diff = right_calibration['X'] - left_calibration['X']
        y_diff = right_calibration['Y'] - left_calibration['Y']
        z_diff = right_calibration['Z'] - left_calibration['Z']
        num_slots = self.get_num_slots()

        slot_depth = x_diff / (num_slots + 1)
        slot_width = y_diff / (num_slots + 1)
        slot_height = z_diff / (num_slots + 1)
        for i in range(1,num_slots+1):
            slot_positions.append({
                'X': int(round(left_calibration['X'] + (i * slot_depth),0)),
                'Y': int(round(left_calibration['Y'] + (i * slot_width),0)),
                'Z': int(round(left_calibration['Z'] + (i * slot_height),0))
            })
        return slot_positions
    
    def assign_slot_positions(self,slot_positions):
        for i,slot in enumerate(self.slots):
            slot.assign_coordinates(slot_positions[i]['X'],slot_positions[i]['Y'],slot_positions[i]['Z'])

    def process_location_data(self,location_data):
        if location_data.get('rack_position_Right',None) is not None:
            self.calibrations['rack_position_Right'] = location_data['rack_position_Right']
        else:
            self.calibrations['rack_position_Right'] = {}
        if location_data.get('rack_position_Left',None) is not None:
            self.calibrations['rack_position_Left'] = location_data['rack_position_Left']
        else:
            self.calibrations['rack_position_Left'] = {}

    def get_all_current_rack_calibrations(self):
        return self.calibrations
    
    def get_calibration_by_name(self, name):
        return self.calibrations.get(name, None)
    
    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name, None)
    
    def set_calibration_position(self, position_name, coordinates):
        """Set a temporary calibration position."""
        self.temp_calibration_data[position_name] = coordinates

    def store_calibrations(self):
        """Save the temporary calibration data to the main calibration data."""
        for position_name, coords in self.temp_calibration_data.items():
            self.calibrations[position_name] = coords
        self.temp_calibration_data.clear()

    def discard_temp_calibrations(self):
        """Discard the temporary calibration data."""
        self.temp_calibration_data.clear()

    def update_calibration_data(self):
        """Run the full update of all calibration data."""
        self.store_calibrations()
        self.save_calibrations_to_file()
        self.apply_calibration_data()

    def save_calibrations_to_file(self):
        self.rack_calibration_updated_signal.emit()

    def check_calibration_applied(self):
        return self.calibration_applied
    
    def get_slot_coordinates(self,slot_number):
        return self.slots[slot_number].get_coordinates()

    def get_num_slots(self):
        return len(self.slots)
    
    def get_all_slots(self):
        return self.slots

    def update_slot_with_printer_head(self, slot_number, printer_head):
        """
        Update a slot with a new printer head.

        Args:
        - slot_number (int): The slot number to update.
        - printer_head (PrinterHead): The printer head to place in the slot.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            slot.change_printer_head(printer_head)
            slot.set_locked(False)
            self.slot_updated.emit()
            self.sync_expected_to_actual()
            #print(f"Slot {slot_number} updated with printer head: {printer_head.get_stock_id()}, {printer_head.color}")

    def lock_slot(self, slot_number):
        """
        Lock a slot when its printer head is in the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(True)
        self.slot_updated.emit()

    def unlock_slot(self, slot_number):
        """
        Unlock a slot when its printer head is returned from the gripper.
        """
        slot = self.slots[slot_number]
        slot.set_locked(False)
        self.slot_updated.emit()
    
    def confirm_slot(self, slot_number):
        """
        Confirm a slot.

        Args:
        - slot_number (int): The slot number to confirm.
        """
        if 0 <= slot_number < len(self.slots):
            if self.slots[slot_number].printer_head is not None:
                self.slots[slot_number].confirm()
                self.slot_updated.emit()
                self.gripper_updated.emit()
                #print(f"Slot {slot_number} confirmed.")
            else:
                error_msg = f"Slot {slot_number} has no printer head to confirm."
                self.error_occurred.emit(error_msg)
                print(error_msg)

    def clear_all_slots(self):
        """
        Clear all slots in the rack.
        """
        for slot in self.slots:
            slot.change_printer_head(None)
            slot.unconfirm()
        self.gripper_printer_head = None
        self.gripper_slot_number = None
        self.slot_updated.emit()
        self.gripper_updated.emit()
        self.sync_expected_to_actual()
        print("All slots cleared.")
    
    def verify_transfer_to_gripper(self, slot_number, use_expected: bool = False):
        """
        Verify if the transfer of the printer head from a slot to the gripper is valid.

        Args:
        - slot_number (int): The slot number to transfer from.

        Returns:
        - bool: True if the transfer is valid, False otherwise.
        - str: Error message if the transfer is not valid, empty string otherwise.
        """
        if 0 <= slot_number < len(self.slots):
            slot_heads, gripper_head, _ = self._get_state(use_expected)
            slot = self.slots[slot_number]

            if slot_heads[slot_number] is not None and slot.confirmed:
                if gripper_head is None:
                    return True, ""
                return False, "Gripper is already holding a printer head."
            return False, f"Slot {slot_number} is not confirmed or empty."
        return False, f"Slot number {slot_number} is out of range."


    def transfer_to_gripper(self, slot_number):
        """
        Transfer the printer head from a slot to the gripper if the transfer is valid.

        Args:
        - slot_number (int): The slot number to transfer from.
        """
        is_valid, error_msg = self.verify_transfer_to_gripper(slot_number)
        if is_valid:
            slot = self.slots[slot_number]
            self.gripper_printer_head = slot.printer_head
            self.gripper_slot_number = slot_number
            slot.change_printer_head(None,returned=True)
            self.lock_slot(slot_number)
            self.slot_updated.emit()
            self.gripper_updated.emit()
            # expected should now match actual at this point
            self.sync_expected_to_actual()
            #print(f"Printer head from slot {slot_number} transferred to gripper.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

    def verify_transfer_from_gripper(self, slot_number, use_expected: bool = False):
        """
        Verify if the transfer of the printer head from the gripper to a slot is valid.

        Args:
        - slot_number (int): The slot number to transfer to.

        Returns:
        - bool: True if the transfer is valid, False otherwise.
        - str: Error message if the transfer is not valid, empty string otherwise.
        """
        if 0 <= slot_number < len(self.slots):
            slot_heads, gripper_head, gripper_slot = self._get_state(use_expected)

            if gripper_slot is None or gripper_head is None:
                return False, "Gripper is empty."
            if slot_number != gripper_slot:
                return False, f"Printer head can only be unloaded to its original slot {gripper_slot}."
            if slot_heads[slot_number] is not None:
                return False, "Slot is already occupied."
            return True, ""
        return False, f"Slot number {slot_number} is out of range."
    
    # ---------- planning transitions (expected-only) ----------
    def plan_transfer_to_gripper(self, slot_number):
        ok, msg = self.verify_transfer_to_gripper(slot_number, use_expected=True)
        if not ok:
            return False, msg

        # move head from expected slot -> expected gripper
        self.expected_gripper_printer_head = self.expected_slot_printer_heads[slot_number]
        self.expected_gripper_slot_number = slot_number
        self.expected_slot_printer_heads[slot_number] = None
        return True, ""

    def plan_transfer_from_gripper(self, slot_number):
        ok, msg = self.verify_transfer_from_gripper(slot_number, use_expected=True)
        if not ok:
            return False, msg

        # move head from expected gripper -> expected slot
        self.expected_slot_printer_heads[slot_number] = self.expected_gripper_printer_head
        self.expected_gripper_printer_head = None
        self.expected_gripper_slot_number = None
        return True, ""

    def transfer_from_gripper(self, slot_number):
        """
        Transfer the printer head from the gripper to a slot if the transfer is valid.

        Args:
        - slot_number (int): The slot number to transfer to.
        """
        is_valid, error_msg = self.verify_transfer_from_gripper(slot_number)
        if is_valid:
            slot = self.slots[slot_number]
            slot.change_printer_head(self.gripper_printer_head,returned=True)
            self.unlock_slot(slot_number)
            self.gripper_printer_head = None
            self.gripper_slot_number = None
            self.slot_updated.emit()
            self.gripper_updated.emit()
            # expected should now match actual at this point
            self.sync_expected_to_actual()
            #print(f"Printer head transferred from gripper to slot {slot_number}.")
        else:
            self.error_occurred.emit(error_msg)
            print(error_msg)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap the printer heads between two slots and emit signals.
        """
        slot_1 = self.slots[slot_number_1]
        slot_2 = self.slots[slot_number_2]
        origial_slot_1_printer_head = slot_1.printer_head
        slot_1.change_printer_head(slot_2.printer_head)
        slot_2.change_printer_head(origial_slot_1_printer_head)
        self.slot_updated.emit()

    def get_slot_info(self, slot_number):
        """
        Get information about a slot.

        Args:
        - slot_number (int): The slot number to get information from.

        Returns:
        - dict: A dictionary containing the slot's information.
        """
        if 0 <= slot_number < len(self.slots):
            slot = self.slots[slot_number]
            printer_head_info = None
            if slot.printer_head is not None:
                if slot.printer_head.is_calibration_chip():
                    printer_head_info = {
                        "reagent": "Calibration",
                        "concentration": "--",
                        "color": slot.printer_head.color
                    }
                else:
                    printer_head_info = {
                        "reagent": slot.printer_head.reagent,
                        "concentration": slot.printer_head.concentration,
                        "color": slot.printer_head.color
                    }
            return {
                "slot_number": slot.number,
                "confirmed": slot.confirmed,
                "printer_head": printer_head_info
            }
        return None

    def get_gripper_info(self):
        """
        Get information about the printer head in the gripper.

        Returns:
        - dict: A dictionary containing the printer head's information or None if empty.
        """
        if self.gripper_printer_head is not None:
            return {
                "reagent": self.gripper_printer_head.get_reagent_name(),
                "concentration": self.gripper_printer_head.get_stock_concentration(),
                "color": self.gripper_printer_head.color
            }
        return None
    
    def get_gripper_printer_head(self):
        return self.gripper_printer_head
    
    def assign_reagents_to_printer_heads(self, reaction_collection):
        """
        Assigns reagents from the reaction collection to printer heads and places them in available slots.
        """
        slot_index = 0
        for reagent_name,concentration in reaction_collection.get_unique_reagent_conc_pairs():
            if slot_index >= len(self.slots):
                raise ValueError("Not enough slots to assign all reagents.")
            
            # Create a PrinterHead for this reagent and concentration
            printer_head = PrinterHead(reagent=reagent_name, concentration=concentration, color=self.generate_color(slot_index))
            
            # Assign the PrinterHead to the current slot and confirm the slot
            self.update_slot_with_printer_head(slot_index, printer_head)
            
            slot_index += 1

    def generate_color(self, slot_index):
        """
        Generate a color for the printer head based on the slot index. This is a placeholder function.
        """
        colors = ["red", "green", "blue", "yellow", "purple", "orange"]
        return colors[slot_index % len(colors)]

class LocationModel(QObject):
    """
    Model for managing location data, including reading and writing to a JSON file.

    Attributes:
    - locations: A dictionary of location names and their XYZ coordinates.
    """

    locations_updated = Signal()  # Signal to notify when locations are updated
    current_location_updated = Signal(str)  # Signal to notify when the current location is updated

    def __init__(self, json_file_path=None, obstacle_path=None):
        super().__init__()

        # Resolve canonical, OS-agnostic default paths next to your app
        script_dir = os.path.dirname(os.path.abspath(__file__))
        presets_dir = os.path.join(script_dir, "Presets")

        self.json_file_path = json_file_path or os.path.join(presets_dir, "Locations.json")
        self.obstacle_path  = obstacle_path  or os.path.join(presets_dir, "Obstacles.json")

        self.locations = {}
        self.boundaries = []
        self.obstacles = []

    # === Atomic file utility ===
    def _atomic_write_json(self, path: str, obj: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on modern Windows & POSIX


    # === Load / Save Locations ===
    def load_locations(self):
        """Load locations from a JSON file."""
        try:
            with open(self.json_file_path, "r", encoding="utf-8") as file:
                self.locations = json.load(file)
            self.locations_updated.emit()
        except FileNotFoundError:
            self.locations = {}
        except json.JSONDecodeError:
            self.locations = {}
        except Exception as e:
            print(f"Failed to load locations '{self.json_file_path}': {e}")
            self.locations = {}

    def save_locations(self):
        """Save locations to a JSON file atomically."""
        try:
            self._atomic_write_json(self.json_file_path, self.locations)
        except Exception as e:
            print(f"Failed to save locations '{self.json_file_path}': {e}")
            # consider re-raising if you want calling code to handle it

    # === Obstacles / Boundaries ===
    def load_obstacles(self):
        """Load boundaries and obstacles from a JSON file."""
        try:
            with open(self.obstacle_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            self.boundaries = data.get("boundaries", [])
            self.obstacles = data.get("obstacles", [])
        except FileNotFoundError:
            self.boundaries, self.obstacles = [], []
        except json.JSONDecodeError:
            self.boundaries, self.obstacles = [], []
        except Exception as e:
            print(f"Failed to load obstacles '{self.obstacle_path}': {e}")
            self.boundaries, self.obstacles = [], []

    def get_obstacles(self):
        return self.obstacles
    
    def get_boundaries(self):
        return self.boundaries

    def add_location(self, name, x, y, z):
        """Add a new location or update an existing one."""
        self.locations[name] = {'X': x, 'Y': y, 'Z': z}
        self.locations_updated.emit()
        #print(f"Location '{name}' added/updated.")

    def update_location(self, name, x, y, z):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = {'X': x, 'Y': y, 'Z': z}
            self.current_location_updated.emit(name)
            self.locations_updated.emit()
            #print(f"Location '{name}' updated.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def update_current_location(self,name):
        if name in self.locations:
            self.current_location_updated.emit(name)
            print(f"Current location updated to '{name}'.")
        else:
            print(f'-Location {name} not found in locations')
            self.current_location_updated.emit(name)

    def update_location_coords(self, name, coords):
        """Update an existing location by name."""
        if name in self.locations:
            self.locations[name] = coords
            self.locations_updated.emit()
            #print(f"Location '{name}' updated.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def remove_location(self, name):
        """Remove a location by name."""
        if name in self.locations:
            del self.locations[name]
            self.locations_updated.emit()
            #print(f"Location '{name}' removed.")
        else:
            pass
            #print(f"Location '{name}' not found.")

    def get_location(self, name):
        """Get a location's coordinates by name in an array [x,y,z]."""
        if name in self.locations:
            loc = self.locations[name]
            return [loc['X'], loc['Y'], loc['Z']]
        return None
    
    def get_location_dict(self, name):
        """Get a location's coordinates by name in a dictionary."""
        if name in self.locations:
            return self.locations[name]
        else:
            return None
        
    def get_all_locations(self):
        """Get all locations."""
        return self.locations

    def get_location_names(self):
        """Get a list of all location names."""
        return list(self.locations.keys())
    
    def post_calibration_update(self,calibration_data):
        self.update_pause_location(calibration_data)
        self.update_plate_location(calibration_data)
        self.save_locations()
    
    def update_pause_location(self,coords):
        offset_coords = {'X':coords['X']-500,'Y':coords['Y']-500,'Z':coords['Z']}
        self.update_location_coords('pause',offset_coords)
        #print(f"Pause location updated.")

    def update_plate_locatin(self,coords):
        self.update_location_coords('plate',coords)
        #print(f"Plate location updated.")

class MachineModel(QObject):
    '''
    Model for all data related to the machine state
    Data includes:
    - Current position of all motors
    - Target position of all motors
    - Current pressure
    - Target pressure

    Methods include:
    - Update position
    - Update pressure
    - Update target position
    - Update target pressure
    '''
    step_size_changed = QtCore.Signal(int)  # Signal to notify when step size changes
    machine_state_updated = QtCore.Signal(bool)  # Signal to notify when machine state changes
    balance_state_updated = QtCore.Signal(bool)  # Signal to notify when balance state changes
    motor_state_changed = QtCore.Signal(bool)  # Signal to notify when motor state changes
    regulation_state_changed = QtCore.Signal(bool)  # Signal to notify when pressure regulation state changes
    pressure_updated = Signal()  # Signal to emit when print pressure readings are updated
    printing_parameters_updated = Signal()  # Signal to emit when printing parameters are updated
    ports_updated = Signal(list)  # Signal to notify view of available ports update
    connection_requested = Signal(str, str)  # Signal to request connection
    gripper_state_changed = Signal(bool)  # Signal to notify when gripper state changes
    speeds_changed = Signal(int,int,int)  # Signal to notify when speeds change
    accelerations_changed = Signal(int,int,int)
    machine_paused = Signal()  # Signal to notify when machine is paused
    home_status_signal = Signal()
    command_numbers_updated = Signal()
    reset_report_updated = Signal()

    def __init__(self):
        super().__init__()
        self.available_ports = []
        self.machine_connected = False
        self.balance_connected = False
        # self.machine_port = "Virtual"
        # self.balance_port = "Virtual"

        self.motors_enabled = False
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0
        self.target_r = 0

        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_p = 0
        self.current_r = 0

        self.x_max_hz = 0
        self.y_max_hz = 0
        self.z_max_hz = 0

        self.x_accel = 0
        self.y_accel = 0
        self.z_accel = 0

        self.motors_homed = False
        self.current_location = "Unknown"
        self.paused = False
        self.machine_free = True
        self.current_command_num = 0
        self.last_completed_command_num = 0
        self.current_micros = 0

        self.gripper_open = False
        self.gripper_active = False

        self.step_num = 4
        self.possible_steps = [2,10,50,250,500,1000,2000]
        self.step_size = self.possible_steps[self.step_num]

        self.current_print_pressure = 0
        self.print_pressure_readings = np.zeros(100)  # Array to store the last 100 pressure readings
        self.current_refuel_pressure = 0
        self.refuel_pressure_readings = np.zeros(100)  # Array to store the last 100 pressure readings
        
        self.target_print_pressure = 0
        self.target_refuel_pressure = 0
        self.print_pulse_width = 0
        self.refuel_pulse_width = 0

        self.gripper_refresh_period = 0
        self.gripper_pulse_duration = 0

        # self.fss = 6553
        # self.psi_offset = 8192
        self.fss = 13107
        self.psi_offset = 1638
        self.psi_max = 15

        self.P_MAX = 5.0
        self.P_MIN = 0.3

        self.regulating_print_pressure = False
        self.regulating_refuel_pressure = False

        self.max_cycle = 0
        self.cycle_count = 0
        self.last_reset_report = None
        self.last_reset_summary = ""
        self.last_reset_report_active = False

    def update_ports(self, ports):
        self.available_ports = ports
        self.ports_updated.emit(self.available_ports)

    def connect_machine(self):
        print("Model connect")
        self.machine_connected = True
        self.machine_state_updated.emit(self.machine_connected)

    def disconnect_machine(self):
        self.machine_connected = False
        self.machine_state_updated.emit(self.machine_connected)
        self.motors_enabled = False
        self.motor_state_changed.emit(self.motors_enabled)
        self.regulating_print_pressure = False
        self.regulating_refuel_pressure = False
        self.regulation_state_changed.emit(self.regulating_print_pressure)
        self.reset_home_status()
        self.home_status_signal.emit()
        self.clear_last_reset_report()

    def recover_after_board_reset(self):
        self.machine_connected = False
        self.machine_state_updated.emit(self.machine_connected)
        self.motors_enabled = False
        self.motor_state_changed.emit(self.motors_enabled)
        self.regulating_print_pressure = False
        self.regulating_refuel_pressure = False
        self.regulation_state_changed.emit(self.regulating_print_pressure)
        self.paused = False
        self.machine_paused.emit()
        self.machine_free = True
        self.current_command_num = 0
        self.last_completed_command_num = 0
        self.command_numbers_updated.emit()
        self.gripper_active = False
        self.reset_home_status()
        self.home_status_signal.emit()

    def update_last_reset_report(self, report):
        self.last_reset_report = dict(report)
        self.last_reset_summary = str(report.get("summary", ""))
        self.last_reset_report_active = True
        self.reset_report_updated.emit()
        self.machine_state_updated.emit(self.machine_connected)

    def clear_last_reset_report(self):
        self.last_reset_report = None
        self.last_reset_summary = ""
        self.last_reset_report_active = False
        self.reset_report_updated.emit()
        self.machine_state_updated.emit(self.machine_connected)

    def connect_balance(self):
        self.balance_connected = True
        self.balance_state_updated.emit(True)

    def disconnect_balance(self):
        self.balance_connected = False
        self.balance_state_updated.emit(False)
    
    def is_connected(self):
        return self.machine_connected
    
    # def is_balance_connected(self):
    #     return self.balance_connected
    
    def motors_are_enabled(self):
        return self.motors_enabled
    
    def motors_are_homed(self):
        return self.motors_homed

    # def connect_balance(self, port):
    #     self.balance_port = port
    #     self.balance_connected = True
    #     self.balance_state_updated.emit(self.balance_connected)

    # def disconnect_balance(self):
    #     self.balance_connected = False
    #     self.balance_state_updated.emit(self.balance_connected)

    def pause_commands(self):
        self.paused = True
        self.machine_paused.emit()

    def resume_commands(self):
        self.paused = False
        self.machine_paused.emit()

    def clear_command_queue(self):
        self.paused = False
        self.machine_paused.emit()

    def open_gripper(self):
        self.gripper_open = True
        self.gripper_active = True
        self.gripper_state_changed.emit(self.gripper_open)
    
    def close_gripper(self):
        self.gripper_open = False
        self.gripper_active = True
        self.gripper_state_changed.emit(self.gripper_open)

    def gripper_off(self):
        self.gripper_active = False
    
    def convert_to_psi(self,pressure):
        return round(((float(pressure) - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((float(psi) / self.psi_max) * self.fss + self.psi_offset)

    def set_step_size(self, new_step_size):
        """Set the step size and emit a signal if it changes."""
        if self.step_size != new_step_size:
            self.step_size = new_step_size
            self.step_num = self.possible_steps.index(new_step_size)
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size set to {self.step_size}")

    def increase_step_size(self):
        """Increase the step size if possible."""
        if self.step_num < len(self.possible_steps) - 1:
            self.step_num += 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size increased to {self.step_size}")

    def decrease_step_size(self):
        """Decrease the step size if possible."""
        if self.step_num > 0:
            self.step_num -= 1
            self.step_size = self.possible_steps[self.step_num]
            self.step_size_changed.emit(self.step_size)
            #print(f"Step size decreased to {self.step_size}")
    
    def toggle_motor_state(self):
        """Toggle the motor state and emit a signal."""
        self.motors_enabled = not self.motors_enabled
        if not self.motors_enabled:
            self.regulating_print_pressure = False
            self.regulating_refuel_pressure = False
            self.regulation_state_changed.emit(self.regulating_print_pressure)
        self.motor_state_changed.emit(self.motors_enabled)
        #print(f"Motors {'enabled' if self.motors_enabled else 'disabled'}")

    def toggle_regulation_state(self):
        """Toggle the motor state and emit a signal."""
        self.regulating_print_pressure = not self.regulating_print_pressure
        self.regulating_refuel_pressure = not self.regulating_refuel_pressure
        self.regulation_state_changed.emit(self.regulating_print_pressure)
        #print(f"Pressure regulation {'enabled' if self.regulating_pressure else 'disabled'}")

    def update_command_numbers(self, current_command_num, last_completed_command_num):
        self.current_command_num = current_command_num
        self.last_completed_command_num = last_completed_command_num
        if self.last_completed_command_num != self.current_command_num:
            self.machine_free = False
            # #print(f"Machine busy. Current command: {self.current_command_num}, Last completed command: {self.last_completed_command_num}")
        else:
            self.machine_free = True
            # #print(f"Machine free. Current command: {self.current_command_num}, Last completed command: {self.last_completed_command_num}")
        self.command_numbers_updated.emit()

    def get_command_numbers(self):
        return self.current_command_num, self.last_completed_command_num
    
    def update_target_position(self, x, y, z):
        self.target_x = int(x)
        self.target_y = int(y)
        self.target_z = int(z)

    def update_target_p_motor(self, p):
        self.target_p = int(p)
    
    def update_target_r_motor(self, r):
        self.target_r = int(r)

    def update_current_position(self, x, y, z):
        self.current_x = int(x)
        self.current_y = int(y)
        self.current_z = int(z)

    def update_current_p_motor(self, p):
        self.current_p = int(p)

    def update_current_r_motor(self, r):
        self.current_r = int(r)
    
    def update_target_print_pressure(self, pressure):
        self.target_print_pressure = self.convert_to_psi(pressure)
        self.printing_parameters_updated.emit()
    
    def update_target_refuel_pressure(self, pressure):
        self.target_refuel_pressure = self.convert_to_psi(pressure)
        self.printing_parameters_updated.emit()

    def update_print_pressure(self, new_pressure):
        """Update the print pressure readings with a new value."""
        # Shift the existing readings and add the new reading
        converted_pressure = self.convert_to_psi(new_pressure)
        self.current_print_pressure = converted_pressure
        self.print_pressure_readings = np.roll(self.print_pressure_readings, -1)
        self.print_pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit()

    def update_refuel_pressure(self,new_pressure):
        """Update the print pressure readings with a new value."""
        # Shift the existing readings and add the new reading
        converted_pressure = self.convert_to_psi(new_pressure)
        self.current_refuel_pressure = converted_pressure
        self.refuel_pressure_readings = np.roll(self.refuel_pressure_readings, -1)
        self.refuel_pressure_readings[-1] = converted_pressure
        self.pressure_updated.emit()

    def update_all_speeds(self, x, y, z):
        self.x_max_hz = x
        self.y_max_hz = y
        self.z_max_hz = z
        self.speeds_changed.emit(self.x_max_hz, self.y_max_hz, self.z_max_hz)

    def update_all_accelerations(self, x, y, z):
        self.x_accel = x
        self.y_accel = y
        self.z_accel = z
        self.accelerations_changed.emit(self.x_accel, self.y_accel, self.z_accel)

    def update_gripper_refresh_period(self, period):
        self.gripper_refresh_period = int(period)
        self.printing_parameters_updated.emit()

    def update_gripper_pulse_duration(self, duration):
        self.gripper_pulse_duration = int(duration)
        self.printing_parameters_updated.emit()

    def get_print_pressure_bounds(self):
        return self.P_MIN, self.P_MAX

    def get_gripper_settings(self):
        return self.gripper_refresh_period, self.gripper_pulse_duration

    def get_current_speeds(self):
        return self.x_max_hz, self.y_max_hz, self.z_max_hz

    def get_current_accelerations(self):
        return self.x_accel, self.y_accel, self.z_accel

    def get_print_pressure_readings(self):
        return self.print_pressure_readings
    
    def get_refuel_pressure_readings(self):
        return self.refuel_pressure_readings
    
    def update_current_micros(self, micros):
        self.current_micros = micros

    def get_current_print_pressure(self):
        return self.current_print_pressure
    
    def get_current_refuel_pressure(self):
        return self.current_refuel_pressure
    
    def get_target_print_pressure(self):
        return self.target_print_pressure
    
    def get_target_refuel_pressure(self):
        return self.target_refuel_pressure
    
    def get_print_pulse_width(self):
        return self.print_pulse_width

    def get_refuel_pulse_width(self):
        return self.refuel_pulse_width
    
    def get_current_p_motor(self):
        return self.current_p
    
    def get_current_r_motor(self):
        return self.current_r
    
    def update_print_pulse_width(self,pulse_width):
        self.print_pulse_width = int(pulse_width)
        self.printing_parameters_updated.emit()
    
    def update_refuel_pulse_width(self,pulse_width):
        self.refuel_pulse_width = int(pulse_width)
        self.printing_parameters_updated.emit()

    def update_cycle_count(self,cycle_count):
        self.cycle_count = int(cycle_count)

    def update_max_cycle(self,max_cycle):
        self.max_cycle = int(max_cycle)

    def get_current_position(self):
        return [self.current_x, self.current_y, self.current_z]

    def get_current_position_dict(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def get_current_position_dict_capital(self):
        return {"X": self.current_x, "Y": self.current_y, "Z": self.current_z}

    def handle_home_complete(self):
        self.motors_homed = True
        self.current_location = "Home"
        self.home_status_signal.emit()
        print("Motors homed.")

    def reset_home_status(self):
        self.motors_homed = False
        self.current_location = "Unknown"

    def get_current_location(self):
        return self.current_location

    def update_current_location(self, location):
        self.current_location = location

    def is_busy(self):
        return not self.machine_free



class Model(QObject):
    '''
    Model class for the MVC architecture
    '''
    machine_state_updated = Signal()  # Signal to notify the view of state changes
    experiment_loaded = Signal()  # Signal to notify the view of an experiment being loaded

    def __init__(self,profile: HardwareProfile = CURRENT_PROFILE):
        super().__init__()
        self.profile = profile
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.locations_path = os.path.join(self.script_dir, 'Presets','Locations.json')
        self.plates_path = os.path.join(self.script_dir, 'Presets','Plates.json')
        self.colors_path = os.path.join(self.script_dir, 'Presets','Printer_head_colors.json')
        self.settings_path = os.path.join(self.script_dir, 'Presets','Settings.json')
        self.obstacles_path = os.path.join(self.script_dir, 'Presets','Obstacles.json')
        self.predictive_model_dir = os.path.join(self.script_dir, 'Presets','Predictive_models')
        self.pixel_step_conv_path = os.path.join(self.script_dir, 'Presets','step_conv_250813.json')
        # self.prediction_model_path = os.path.join(self.script_dir, 'Presets','150um_50per_large_lr_pipeline.pkl')
        # self.resistance_model_path = os.path.join(self.script_dir, 'Presets','150um_50per_large_resistance_pipeline.pkl')
    
        self.printer_head_colors = self.load_colors(self.colors_path)
        self.settings = self.load_settings(self.settings_path)
        self.machine_model = MachineModel()
        self.num_slots = 5
        self.location_data = self.load_all_location_data(self.locations_path)
        self.rack_model = RackModel(self.num_slots,location_data=self.location_data)
        self.location_model = LocationModel(json_file_path=self.locations_path,obstacle_path=self.obstacles_path)
        self.location_model.load_locations()  # Load locations at startup
        self.location_model.load_obstacles()
        self.all_plate_data = self.load_all_plate_data(self.plates_path)
        self.well_plate = WellPlate(self.all_plate_data,self.plates_path)
        self.stock_solutions = StockSolutionManager()
        self.reaction_collection = ReactionCollection()
        self.printer_head_manager = PrinterHeadManager(self.printer_head_colors,self.rack_model)

        # self.calibration_model = MassCalibrationModel(self.machine_model,self.printer_head_manager,self.rack_model,self.predictive_model_dir)
        self.experiment_file_path = None
        self.refuel_camera_model = CalibrationClasses.RefuelCameraModel()
        self.droplet_camera_model = CalibrationClasses.DropletCameraModel(self.pixel_step_conv_path)
        self.calibration_manager = CalibrationClasses.CalibrationManager(self)
        # self.experiment_model = ExperimentModel(self.well_plate,self.calibration_manager)
        self.experiment_model = ExperimentModel(prof=self.profile)
        self.calibration_memory_store = None
        self._disposable_printer_head_counter = 0
        self._initialize_calibration_memory_store()

        self.well_plate.plate_format_changed_signal.connect(self.update_well_plate)
        self.rack_model.rack_calibration_updated_signal.connect(self.update_rack_calibration)
        self.location_model.current_location_updated.connect(self.machine_model.update_current_location)
        self.droplet_camera_model.record_metadata_signal.connect(self.record_image_metadata)

    def reload_refuel_model(self):
        importlib.reload(CalibrationClasses.Model)
        importlib.reload(CalibrationClasses)
        self.refuel_camera_model = CalibrationClasses.RefuelCameraModel()

    def reload_droplet_model(self):
        self.droplet_camera_model.record_metadata_signal.disconnect()

        importlib.reload(CalibrationClasses.Model)
        importlib.reload(CalibrationClasses)
        self.droplet_camera_model = CalibrationClasses.DropletCameraModel(self.pixel_step_conv_path)
        self.calibration_manager = CalibrationClasses.CalibrationManager(self)
        self._initialize_calibration_memory_store()
        self.droplet_camera_model.record_metadata_signal.connect(self.record_image_metadata)

    def _initialize_calibration_memory_store(self):
        try:
            store = getattr(self, "calibration_memory_store", None)
            if isinstance(store, CalibrationMemoryStore):
                store.set_model(self)
            else:
                store = CalibrationMemoryStore(model=self)
            store.ensure_initialized()
            self.calibration_memory_store = store
        except Exception as e:
            print(f"[CalibrationMemory] Failed to initialize store: {e}")
            self.calibration_memory_store = None

    @staticmethod
    def _clean_identity_text(value):
        if value is None:
            return None
        out = str(value).strip()
        return out or None

    @classmethod
    def _slugify_identity_token(cls, value):
        value = cls._clean_identity_text(value)
        if value is None:
            return None
        chars = []
        prev_us = False
        for ch in value.lower():
            if ch.isalnum():
                chars.append(ch)
                prev_us = False
            else:
                if not prev_us:
                    chars.append("_")
                    prev_us = True
        slug = "".join(chars).strip("_")
        return slug or None

    def _get_calibration_identity_registry(self):
        store = getattr(self, "calibration_memory_store", None)
        return getattr(store, "identity_registry", None) if store is not None else None

    def list_known_reagent_identities(self):
        registry = self._get_calibration_identity_registry()
        if registry is None:
            return []
        try:
            items = list((registry.load_reagents() or {}).values())
        except Exception as e:
            print(f"[CalibrationMemory] Failed to load reagent identities: {e}")
            return []
        payloads = []
        for item in items:
            payloads.append({
                "reagent_id": item.reagent_id,
                "display_name": item.display_name,
                "aliases": list(item.aliases or []),
                "stock_ids": list(item.stock_ids or []),
                "reagent_family": item.reagent_family,
                "glycerol_percent": item.glycerol_percent,
                "tags": list(item.tags or []),
                "notes": item.notes,
            })
        payloads.sort(key=lambda row: ((row.get("display_name") or "").lower(), row.get("reagent_id") or ""))
        return payloads

    def list_known_printer_head_types(self):
        registry = self._get_calibration_identity_registry()
        if registry is None:
            return []
        try:
            items = list((registry.load_printer_head_types() or {}).values())
        except Exception as e:
            print(f"[CalibrationMemory] Failed to load printer head types: {e}")
            return []
        payloads = []
        for item in items:
            payloads.append({
                "head_type_id": item.head_type_id,
                "display_name": item.display_name,
                "nominal_nozzle_diameter_um": item.nominal_nozzle_diameter_um,
                "tags": list(item.tags or []),
                "notes": item.notes,
            })
        payloads.sort(
            key=lambda row: (
                float(row.get("nominal_nozzle_diameter_um")) if row.get("nominal_nozzle_diameter_um") is not None else 1e9,
                (row.get("display_name") or "").lower(),
            )
        )
        return payloads

    def resolve_design_reagent_identity(self, *, reagent_name=None, reagent_id=None, stock_label=None):
        registry = self._get_calibration_identity_registry()
        raw_name = self._clean_identity_text(reagent_name) or self._clean_identity_text(stock_label)
        explicit_reagent_id = self._slugify_identity_token(reagent_id)

        if registry is None:
            derived_id = explicit_reagent_id or self._slugify_identity_token(raw_name)
            return {
                "reagent_id": derived_id,
                "display_name": raw_name,
                "reagent_family": None,
                "glycerol_percent": None,
                "tags": [],
                "notes": "",
                "known": False,
                "quality": {
                    "stock_id": "unknown",
                    "reagent_id": "explicit" if explicit_reagent_id else ("inferred" if derived_id else "unknown"),
                },
                "match_source": "unavailable",
            }

        resolved = None
        if explicit_reagent_id:
            item = registry.get_reagent(explicit_reagent_id)
            if item is not None:
                resolved = {
                    "reagent_id": item.reagent_id,
                    "display_name": item.display_name,
                    "reagent_family": item.reagent_family,
                    "glycerol_percent": item.glycerol_percent,
                    "tags": list(item.tags or []),
                    "notes": item.notes,
                    "quality": {"stock_id": "unknown", "reagent_id": "explicit"},
                    "match_source": "reagent_id",
                    "known": True,
                }

        if resolved is None:
            try:
                resolved = dict(registry.resolve_reagent(reagent_name=raw_name) or {})
            except Exception as e:
                print(f"[CalibrationMemory] Failed to resolve reagent identity: {e}")
                resolved = {}

        resolved.setdefault("reagent_id", explicit_reagent_id or self._slugify_identity_token(raw_name))
        resolved["display_name"] = self._clean_identity_text(
            resolved.get("display_name") or raw_name or resolved.get("reagent_id")
        )
        resolved.setdefault("reagent_family", None)
        resolved.setdefault("glycerol_percent", None)
        resolved.setdefault("tags", [])
        resolved.setdefault("notes", "")
        quality = dict(resolved.get("quality") or {})
        quality.setdefault("stock_id", "unknown")
        quality.setdefault(
            "reagent_id",
            "explicit" if explicit_reagent_id else ("inferred" if resolved.get("reagent_id") else "unknown"),
        )
        resolved["quality"] = quality
        if explicit_reagent_id and not resolved.get("reagent_id"):
            resolved["reagent_id"] = explicit_reagent_id
        if explicit_reagent_id:
            resolved["reagent_id"] = explicit_reagent_id
        match_source = str(resolved.get("match_source") or "")
        resolved["known"] = bool(
            registry.get_reagent(resolved.get("reagent_id")) is not None
            or match_source in {"alias", "stock_id", "reagent_id", "runtime_reagent_id"}
        )
        return resolved

    def preview_experiment_design_prior(
        self,
        *,
        reagent_name=None,
        reagent_id=None,
        head_type_id=None,
        target_volume_nl=None,
        stock_label=None,
    ):
        resolved_reagent = self.resolve_design_reagent_identity(
            reagent_name=reagent_name,
            reagent_id=reagent_id,
            stock_label=stock_label,
        )
        clean_head_type_id = self._slugify_identity_token(head_type_id)
        head_type = None
        registry = self._get_calibration_identity_registry()
        if registry is not None and clean_head_type_id:
            try:
                head_type = registry.get_head_type(clean_head_type_id)
            except Exception:
                head_type = None

        if clean_head_type_id is None:
            return {
                "status": "head_type_missing",
                "status_label": "Head type not set",
                "prior": None,
                "resolved_reagent": resolved_reagent,
                "head_type": head_type.to_dict() if head_type is not None else None,
            }

        store = getattr(self, "calibration_memory_store", None)
        if store is None:
            return {
                "status": "memory_unavailable",
                "status_label": "Memory unavailable",
                "prior": None,
                "resolved_reagent": resolved_reagent,
                "head_type": head_type.to_dict() if head_type is not None else {
                    "head_type_id": clean_head_type_id,
                    "display_name": clean_head_type_id,
                },
            }

        prior = None
        try:
            prior = store.get_best_prior(
                {
                    "reagent_id": resolved_reagent.get("reagent_id"),
                    "reagent_family": resolved_reagent.get("reagent_family"),
                    "printer_head_id": None,
                    "head_type_id": clean_head_type_id,
                },
                target_volume_nl=target_volume_nl,
            )
        except Exception as e:
            print(f"[CalibrationMemory] Failed to preview design prior: {e}")

        if prior is None:
            return {
                "status": "none",
                "status_label": "No prior",
                "prior": None,
                "resolved_reagent": resolved_reagent,
                "head_type": head_type.to_dict() if head_type is not None else {
                    "head_type_id": clean_head_type_id,
                    "display_name": clean_head_type_id,
                },
            }

        confidence = prior.get("recommendation_confidence_adjusted", prior.get("recommendation_confidence"))
        try:
            confidence = float(confidence) if confidence is not None else None
        except Exception:
            confidence = None
        level = str(prior.get("aggregation_level") or "")
        strong = level in {"exact_pair", "exact_reagent_head_type"} and confidence is not None and confidence >= 0.75
        status = "strong" if strong else "some"
        return {
            "status": status,
            "status_label": "Strong prior" if strong else "Some prior",
            "prior": dict(prior),
            "resolved_reagent": resolved_reagent,
            "head_type": head_type.to_dict() if head_type is not None else {
                "head_type_id": clean_head_type_id,
                "display_name": clean_head_type_id,
            },
        }

    def register_experiment_design_reagents(self, experiment_model=None):
        registry = self._get_calibration_identity_registry()
        model = experiment_model or self.experiment_model
        if registry is None or model is None:
            return []

        registered = []
        for factor in getattr(model, "factors", []):
            for option in getattr(factor, "options", []):
                display_name = self._clean_identity_text(
                    getattr(option, "reagent_display_name", None) or getattr(option, "name", None)
                )
                resolved = self.resolve_design_reagent_identity(
                    reagent_name=display_name,
                    reagent_id=getattr(option, "reagent_id", None),
                    stock_label=getattr(option, "name", None),
                )
                reagent_id = self._slugify_identity_token(resolved.get("reagent_id"))
                if reagent_id is None or display_name is None:
                    continue
                existing = registry.get_reagent(reagent_id)
                aliases = []
                if existing is not None:
                    aliases.extend(list(existing.aliases or []))
                aliases.extend([display_name, getattr(option, "name", None)])
                aliases = [alias for alias in dict.fromkeys(self._clean_identity_text(item) for item in aliases) if alias]
                payload = {
                    "reagent_id": reagent_id,
                    "display_name": display_name,
                    "stock_ids": list(getattr(existing, "stock_ids", []) or []),
                    "aliases": aliases,
                    "reagent_family": resolved.get("reagent_family") if existing is None else existing.reagent_family,
                    "glycerol_percent": resolved.get("glycerol_percent") if existing is None else existing.glycerol_percent,
                    "tags": list(getattr(existing, "tags", []) or resolved.get("tags", []) or []),
                    "notes": getattr(existing, "notes", "") or resolved.get("notes", ""),
                }
                try:
                    saved = registry.upsert_reagent(payload)
                except Exception as e:
                    print(f"[CalibrationMemory] Failed to upsert reagent '{reagent_id}': {e}")
                    continue
                option.reagent_id = saved.reagent_id
                option.reagent_display_name = saved.display_name
                registered.append(saved.reagent_id)
        return registered

    def _apply_design_identity_to_stock_solution(self, stock_solution, stock_row):
        if stock_solution is None or not isinstance(stock_row, dict):
            return

        registry = self._get_calibration_identity_registry()
        reagent_id = self._slugify_identity_token(stock_row.get("reagent_id"))
        reagent_display_name = self._clean_identity_text(stock_row.get("reagent_display_name"))
        if reagent_id or reagent_display_name:
            reagent_payload = None
            if registry is not None and reagent_id:
                try:
                    reagent_payload = registry.get_reagent(reagent_id)
                except Exception:
                    reagent_payload = None
            stock_solution.set_reagent_identity(
                reagent_id=reagent_id or getattr(reagent_payload, "reagent_id", None),
                display_name=reagent_display_name or getattr(reagent_payload, "display_name", None),
                reagent_family=getattr(reagent_payload, "reagent_family", None),
                glycerol_percent=getattr(reagent_payload, "glycerol_percent", None),
                tags=list(getattr(reagent_payload, "tags", []) or []),
                notes=getattr(reagent_payload, "notes", ""),
            )

        head_type_id = self._slugify_identity_token(stock_row.get("intended_head_type_id"))
        head_type_display_name = self._clean_identity_text(stock_row.get("intended_head_type_display_name"))
        if head_type_id or head_type_display_name:
            head_type_payload = None
            if registry is not None and head_type_id:
                try:
                    head_type_payload = registry.get_head_type(head_type_id)
                except Exception:
                    head_type_payload = None
            stock_solution.set_intended_head_type(
                head_type_id=head_type_id or getattr(head_type_payload, "head_type_id", None),
                display_name=head_type_display_name or getattr(head_type_payload, "display_name", None),
                nominal_nozzle_diameter_um=getattr(head_type_payload, "nominal_nozzle_diameter_um", None),
                tags=list(getattr(head_type_payload, "tags", []) or []),
                notes=getattr(head_type_payload, "notes", ""),
            )

    def _generate_disposable_printer_head_id(self, head_type_id=None):
        self._disposable_printer_head_counter = int(getattr(self, "_disposable_printer_head_counter", 0)) + 1
        head_token = self._slugify_identity_token(head_type_id) or "unknown_head_type"
        exp_token = self._slugify_identity_token(
            getattr(getattr(self, "experiment_model", None), "metadata", {}).get("name")
        ) or "experiment"
        ts_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{head_token}__{exp_token}__{ts_token}__{self._disposable_printer_head_counter:03d}"

    def _apply_runtime_printer_head_identity(self, printer_head):
        if printer_head is None or getattr(printer_head, "calibration_chip", False):
            return
        stock_solution = None
        try:
            stock_solution = printer_head.get_stock_solution()
        except Exception:
            stock_solution = getattr(printer_head, "stock_solution", None)
        head_type_id = self._slugify_identity_token(getattr(stock_solution, "intended_head_type_id", None))
        registry = self._get_calibration_identity_registry()
        head_type_payload = None
        if registry is not None and head_type_id:
            try:
                head_type_payload = registry.get_head_type(head_type_id)
            except Exception:
                head_type_payload = None
        printer_head_id = self._generate_disposable_printer_head_id(head_type_id=head_type_id)
        printer_head.set_identity_metadata(
            printer_head_id=printer_head_id,
            head_type_id=head_type_id,
            display_name=printer_head_id,
            nominal_nozzle_diameter_um=(
                getattr(head_type_payload, "nominal_nozzle_diameter_um", None)
                if head_type_payload is not None
                else getattr(stock_solution, "intended_nominal_nozzle_diameter_um", None)
            ),
            measured_nozzle_diameter_um=None,
            manufacturer_batch=None,
            tags=list(getattr(head_type_payload, "tags", []) or getattr(stock_solution, "intended_head_type_tags", []) or []),
            notes=getattr(head_type_payload, "notes", "") or getattr(stock_solution, "intended_head_type_notes", ""),
        )

    def load_colors(self, file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_all_plate_data(self,file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
        if not isinstance(data, list) or not data:
            raise ValueError("Plates.json must be a non-empty list of plate definitions.")

        required = {"name", "rows", "columns", "spacing", "default", "calibrations"}
        names = set()
        default_count = 0
        for i, plate in enumerate(data):
            if not isinstance(plate, dict):
                raise ValueError(f"Plate entry at index {i} must be an object.")
            missing = required - set(plate.keys())
            if missing:
                raise ValueError(f"Plate entry '{plate}' missing required keys: {sorted(missing)}")
            name = str(plate["name"])
            if name in names:
                raise ValueError(f"Duplicate plate name '{name}' in Plates.json.")
            names.add(name)
            if int(plate["rows"]) <= 0 or int(plate["columns"]) <= 0:
                raise ValueError(f"Plate '{name}' must have positive rows/columns.")
            if float(plate["spacing"]) <= 0:
                raise ValueError(f"Plate '{name}' must have positive spacing.")
            if bool(plate["default"]):
                default_count += 1
            if not isinstance(plate.get("calibrations", {}), dict):
                raise ValueError(f"Plate '{name}' calibrations must be an object.")

        if default_count != 1:
            raise ValueError(f"Plates.json must define exactly one default plate; found {default_count}.")
        return data
        
    def load_all_location_data(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def load_settings(self,file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
        
    def get_default_machine_port(self):
        return self.settings['MACHINE_PORT']
    
    def get_default_balance_port(self):
        return self.settings['BALANCE_PORT']
        
    def update_rack_calibration(self):
        print('\n---Updating rack calibration')
        self.location_model.update_location_coords('rack_position_Left',self.rack_model.get_calibration_by_name('rack_position_Left'))
        self.location_model.update_location_coords('rack_position_Right',self.rack_model.get_calibration_by_name('rack_position_Right'))
        self.location_model.save_locations()

    def update_state(self, status_dict):
        '''
        Update the state of the machine model
        '''
        status_keys = status_dict.keys()
        self.machine_model.update_current_position(status_dict.get('X', self.machine_model.current_x),
                                                   status_dict.get('Y', self.machine_model.current_y),
                                                   status_dict.get('Z', self.machine_model.current_z))
        
        self.machine_model.update_current_p_motor(status_dict.get('P', self.machine_model.current_p))
        self.machine_model.update_current_r_motor(status_dict.get('R', self.machine_model.current_r))   
        self.machine_model.update_target_position(status_dict.get('Tar_X', self.machine_model.target_x),
                                                  status_dict.get('Tar_Y', self.machine_model.target_y),
                                                  status_dict.get('Tar_Z', self.machine_model.target_z))
        self.machine_model.update_target_p_motor(status_dict.get('Tar_P', self.machine_model.target_p))
        self.machine_model.update_target_r_motor(status_dict.get('Tar_R', self.machine_model.target_r))
        if 'Pressure_P' in status_keys:
            self.machine_model.update_print_pressure(status_dict['Pressure_P'])
        if 'Pressure_R' in status_keys:
            self.machine_model.update_refuel_pressure(status_dict['Pressure_R'])
        if 'Tar_print' in status_keys:
            self.machine_model.update_target_print_pressure(status_dict['Tar_print'])
        if 'Tar_refuel' in status_keys:
            self.machine_model.update_target_refuel_pressure(status_dict['Tar_refuel'])
        if 'Cycle_count' in status_keys:
            self.machine_model.update_cycle_count(status_dict['Cycle_count'])
        if 'Max_cycle' in status_keys:
            self.machine_model.update_max_cycle(status_dict['Max_cycle'])
        if 'Print_width' in status_keys:
            self.machine_model.update_print_pulse_width(status_dict['Print_width'])
        if 'Refuel_width' in status_keys:
            self.machine_model.update_refuel_pulse_width(status_dict['Refuel_width'])
        if 'Micros' in status_keys:
            self.machine_model.update_current_micros(status_dict['Micros'])
        if 'Flashes' in status_keys:
            self.droplet_camera_model.update_num_flashes(status_dict['Flashes'])
        if 'Flash_width' in status_keys:
            self.droplet_camera_model.update_flash_duration(status_dict['Flash_width'])
        if 'Flash_delay' in status_keys:
            self.droplet_camera_model.update_flash_delay(status_dict['Flash_delay'])
        if 'Flash_droplets' in status_keys:
            self.droplet_camera_model.update_num_droplets(status_dict['Flash_droplets'])
        if 'Ext_counter' in status_keys:
            self.droplet_camera_model.update_trigger_counter(status_dict['Ext_counter'])
        if 'X_max_hz' in status_keys:
            self.machine_model.update_all_speeds(status_dict['X_max_hz'], status_dict['Y_max_hz'], status_dict['Z_max_hz'])
        if 'X_accel' in status_keys:
            self.machine_model.update_all_accelerations(status_dict['X_accel'], status_dict['Y_accel'], status_dict['Z_accel'])

        if 'Grip_pulse' in status_keys:
            self.machine_model.update_gripper_pulse_duration(status_dict['Grip_pulse'])
        if 'Grip_period' in status_keys:
            self.machine_model.update_gripper_refresh_period(status_dict['Grip_period'])

        self.machine_model.update_command_numbers(status_dict.get('Current_command', self.machine_model.current_command_num),
                                                    status_dict.get('Last_completed', self.machine_model.last_completed_command_num))
        self.machine_state_updated.emit()
    
    def load_reactions_from_csv(self,csv_file_path):
        """
        Load reactions from a CSV file and return a ReactionCollection.
        
        The CSV should have a 'reaction_id' column followed by columns for each reagent with target concentrations.
        """
        df = pd.read_csv(csv_file_path)
        stock_solutions = StockSolutionManager()
        stock_names = [c for c in df.columns if c != 'reaction_id']
        stock_solutions.add_all_stock_solutions(stock_names)
        
        reaction_collection = ReactionCollection()

        for _, row in df.iterrows():
            reaction_name = row['reaction_id']
            reaction = ReactionComposition(reaction_name)

            for stock_id, droplets in row.items():
                if stock_id != 'reaction_id':  # Skip the 'reaction_id' column
                    current_stock = stock_solutions.get_stock_by_id(stock_id)
                    reaction.add_reagent(current_stock, droplets)
            
            reaction_collection.add_reaction(reaction)

        return stock_solutions,reaction_collection
    
    def load_experiment_from_file(self, file_path, plate_name=None):
        """Load an experiment from a CSV file. Remove any existing experiment data."""
        if not file_path.endswith('.csv'):
            raise ValueError("Invalid file format. Please load a CSV file.")
        if len(self.reaction_collection.get_all_reactions()) > 0:
            self.stock_solutions = StockSolutionManager()
            self.reaction_collection = ReactionCollection()
            self.well_plate.clear_all_wells()
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
        self.stock_solutions, self.reaction_collection = self.load_reactions_from_csv(file_path)
        #print(f'Stock Solutions:{self.stock_solutions.get_stock_solution_names()}')
        self.well_plate.assign_reactions_to_wells(self.reaction_collection.get_all_reactions())
        self.assign_printer_heads()
        self.experiment_loaded.emit()
        self.experiment_file_path = file_path

    def load_reactions_from_model(self):
        """
        Build StockSolutionManager and ReactionCollection from the new ExperimentModel.
        Includes the Fill reagent as a stock and as a reagent in every reaction.
        """
        from math import isfinite, ceil

        ssm = StockSolutionManager()
        stock_row_lookup = {}

        def _stock_lookup_key(reagent_name, concentration, units):
            try:
                return (
                    str(reagent_name),
                    f"{float(concentration):.2f}",
                    str(units),
                )
            except Exception:
                return (str(reagent_name), str(concentration), str(units))

        # ---------- 1) STOCKS (include fill) ----------
        stock_rows = self.experiment_model.get_stock_table_rows(include_fill=True)

        for row in stock_rows:
            reagent_name = row.get("option_name") or row.get("factor_name") or ""
            conc = float(row.get("stock_concentration", 0.0))
            units = row.get("units", "mM")
            stock_row_lookup[_stock_lookup_key(reagent_name, conc, units)] = dict(row)

            total_uL = row.get("total_volume_uL", None)
            if total_uL is None:
                drops = int(row.get("total_droplets", 0))
                dv_nL = float(row.get("droplet_volume_nL", 0.0))
                total_uL = (drops * dv_nL) / 1000.0

            if reagent_name:
                ssm.add_stock_solution(
                    reagent_name, conc, units,
                    required_volume=(total_uL if isfinite(total_uL) else None)
                )
                stock = ssm.get_stock_solution(reagent_name, conc, units)
                self._apply_design_identity_to_stock_solution(stock, row)

        # ---------- 2) REACTIONS (non-fill + fill) ----------
        rc = ReactionCollection()

        # Non-fill parts come from the model helper (your existing function)
        parts_list = list(self.experiment_model.iter_reaction_stock_droplets())

        # Build fill sequence to match reaction count
        df = self.experiment_model.get_reactions_dataframe()
        base_fill = [int(x) for x in df["fill_drops"].tolist()] if not df.empty else []
        reps = int(self.experiment_model.metadata.get("replicates", 1))
        # Repeat the base_fill for replicates
        fill_seq = base_fill * max(1, reps)

        # If counts don't perfectly match, extend/cycle safely
        if len(fill_seq) and len(parts_list) > len(fill_seq):
            times = ceil(len(parts_list) / len(fill_seq))
            fill_seq = (fill_seq * times)[:len(parts_list)]
        elif len(fill_seq) < len(parts_list):
            # no fill info -> default to 0
            fill_seq = [0] * len(parts_list)

        fill_name = self.experiment_model.metadata.get("fill_reagent_name", "Water")
        fill_units = "--"
        fill_conc = 1.0  # how the ExperimentModel encodes fill stock

        for idx, parts in enumerate(parts_list):
            rxn = ReactionComposition(unique_id=f"R{idx+1}")

            # Non-fill reagents
            for reagent_name, conc, units, drops in parts:
                stock = ssm.get_stock_solution(reagent_name, conc, units)
                if stock is None:
                    ssm.add_stock_solution(reagent_name, conc, units)
                    stock = ssm.get_stock_solution(reagent_name, conc, units)
                    self._apply_design_identity_to_stock_solution(
                        stock,
                        stock_row_lookup.get(_stock_lookup_key(reagent_name, conc, units), {}),
                    )
                rxn.add_reagent(stock, int(drops))

            # Fill reagent
            fill_drops = int(fill_seq[idx]) if idx < len(fill_seq) else 0
            if fill_drops > 0:
                fill_stock = ssm.get_stock_solution(fill_name, fill_conc, fill_units)
                if fill_stock is None:
                    # Safety net; should exist from stock table, but add if needed
                    ssm.add_stock_solution(fill_name, fill_conc, fill_units)
                    fill_stock = ssm.get_stock_solution(fill_name, fill_conc, fill_units)
                    self._apply_design_identity_to_stock_solution(
                        fill_stock,
                        stock_row_lookup.get(_stock_lookup_key(fill_name, fill_conc, fill_units), {}),
                    )
                rxn.add_reagent(fill_stock, fill_drops)

            rc.add_reaction(rxn)

        return ssm, rc

    def load_experiment_from_model(self, plate_name=None, load_progress=False):
        # Bail if nothing was generated
        if self.experiment_model.get_number_of_reactions() == 0:
            print("No reactions in the experiment model.")
            return

        preserved_exclusions = set(getattr(self.well_plate, "excluded_wells", set()))
        self.clear_experiment()
        self.well_plate.excluded_wells = preserved_exclusions
        if plate_name is not None:
            self.well_plate.set_plate_format(plate_name)
            self.experiment_model.metadata["plate_name"] = self.well_plate.get_current_plate_name()
            self.experiment_model.metadata["plate_rows"] = self.well_plate.get_num_rows()
            self.experiment_model.metadata["plate_columns"] = self.well_plate.get_num_cols()

        stock_solutions, reaction_collection = self.load_reactions_from_model()
        if stock_solutions is None or reaction_collection is None:
            print("No stock solutions or reactions found in the experiment model.")
            self.clear_experiment()
            return

        self.stock_solutions = stock_solutions
        self.reaction_collection = reaction_collection
        self.experiment_model.metadata["plate_name"] = self.well_plate.get_current_plate_name()
        self.experiment_model.metadata["plate_rows"] = self.well_plate.get_num_rows()
        self.experiment_model.metadata["plate_columns"] = self.well_plate.get_num_cols()

        # Randomization (handled earlier via seed in ExperimentModel->load_reactions_from_model)
        all_reactions = self.reaction_collection.get_all_reactions()
        
        # ---- 1) Check for manual well assignments ----
        manual_well_ids = self._get_manual_well_assignments()
        using_manual_assignments = manual_well_ids is not None

        if using_manual_assignments:
            # Enforce 1:1 mapping between reactions and wells
            if len(manual_well_ids) != len(all_reactions):
                raise ValueError(
                    f"Manual well assignments ({len(manual_well_ids)}) "
                    f"must match the number of reactions ({len(all_reactions)})."
                )

            # When manual well assignments are used, treat "replicates" as 0
            # so the runtime / metadata clearly reflect that layout is explicit.
            try:
                original_reps = int(self.experiment_model.metadata.get("replicates", 1))
            except Exception:
                original_reps = self.experiment_model.metadata.get("replicates", 1)

            # Preserve original value for reference if you want it later
            if "_original_replicates" not in self.experiment_model.metadata:
                self.experiment_model.metadata["_original_replicates"] = original_reps

            self.experiment_model.metadata["replicates"] = 0

            # IMPORTANT: do NOT randomize when manual assignments are provided.
            # The user expects the i-th reaction to go to the i-th specified well.
        else:
            # ---- 2) Automatic mode: optional randomization as before ----
            random_seed = self.experiment_model.get_random_seed()
            if random_seed is not None:
                import random
                random.Random(random_seed).shuffle(all_reactions)

        # ---- 3) Assign reactions to wells ----
        start_row = self.experiment_model.get_start_row()
        start_col = self.experiment_model.get_start_col()

        if using_manual_assignments:
            # Explicit reaction → well mapping
            self.well_plate.assign_reactions_to_specific_wells(
                all_reactions,
                manual_well_ids
            )
        else:
            # Existing automatic zig-zag behaviour
            self.well_plate.assign_reactions_to_wells(
                all_reactions,
                start_row=start_row,
                start_col=start_col
            )

        # Apply calibration & printer head assignment as before
        self.well_plate.apply_calibration_data()
        self.assign_printer_heads()

        # Ensure experiment folder exists and paths are known
        if not self.experiment_model.experiment_dir_path:
            self.experiment_model.initialize_experiment()
        else:
            self.experiment_model.update_all_paths()

        # Give ExperimentModel a runtime view so it can build progress/key files
        self.experiment_model.set_runtime_context(self.well_plate, self.reaction_collection)

        # Progress/key/concentration key files
        if load_progress:
            print("Loading progress in load_experiment_from_model()")
            self.experiment_model.load_progress()
        else:
            print("Creating new progress file from load_experiment_from_model()")
            self.experiment_model.create_progress_file()

        self.experiment_model.create_key_file()
        self.experiment_model.create_concentration_key_file()

        self.experiment_loaded.emit()

    def get_well_stock_final_concentration(self, well_id: str, stock_id: str):
        """
        Return estimated final concentration contribution for a specific stock in a well.
        Uses target droplets and stock concentration against final reaction volume metadata.
        """
        well = self.well_plate.get_well(well_id)
        if well is None or well.get_assigned_reaction() is None:
            return None
        rxn = well.get_assigned_reaction()
        reagent = rxn.get_all_reagents().get(stock_id)
        if reagent is None:
            return 0.0
        try:
            drops = float(reagent.get_target_droplets())
            c_stock = float(reagent.stock_solution.get_stock_concentration())
            v_final = float(self.experiment_model.metadata.get(
                "final_reaction_volume_nL",
                self.experiment_model.metadata.get("target_reaction_volume_nL", 500.0),
            ))
            dv = float(self.experiment_model.metadata.get("fill_droplet_volume_nL", 10.0))
            # Prefer design stock table droplet volume if available
            for row in self.experiment_model.get_stock_table_rows(include_fill=True):
                name = row.get("option_name") or row.get("factor_name") or ""
                units = row.get("units", "")
                sid = f"{name}_{float(row.get('stock_concentration', 0.0)):.2f}_{units}"
                if sid == stock_id:
                    dv = float(row.get("droplet_volume_nL", dv))
                    break
            if v_final <= 0:
                return 0.0
            return c_stock * (drops * dv) / v_final
        except Exception:
            return None


    # ----------------- helper: manual well assignments -----------------
    def _get_manual_well_assignments(self):
        """
        Return a list of well IDs (e.g. ['A1','B1',...]) in reaction order,
        or None if manual assignments are not being used.

        This is intentionally defensive and will work with either:
        - ExperimentModel.get_explicit_well_assignments() / has_explicit_well_assignments()
        - or an attribute `manual_well_assignments` (list of well IDs).
        """
        em = self.experiment_model

        # Preferred explicit API
        has_manual = getattr(em, "has_explicit_well_assignments", None)
        if callable(has_manual) and not has_manual():
            return None

        get_manual = getattr(em, "get_explicit_well_assignments", None)
        if callable(get_manual):
            wells = get_manual()
            print(f"Using manual well assignments from has_explicit_well_assignments(): {wells}")
        else:
            # Fallback: plain attribute
            wells = getattr(em, "_uploaded_well_ids", None)

        if not wells:
            return None
        print(f"Using manual well assignments: {wells}")
        # Normalize to list of upper-case strings
        normalized = [str(w).strip().upper() for w in wells if w is not None and str(w).strip()]
        return normalized if normalized else None

    def reload_experiment(self, plate_name=None):
        """Reload the experiment from the last loaded file."""
        if self.experiment_file_path is not None:
            self.load_experiment_from_file(self.experiment_file_path,plate_name=plate_name)
        else:
            print("No experiment file path found. Please load an experiment file.")

    def update_well_plate(self):
        """
        Rebuild well → reaction assignments using either:
        - manual assignments, if present, or
        - automatic zig-zag from start_row/start_col, as before.
        """
        if self.reaction_collection is None:
            print("No experiment data loaded.")
            return

        all_reactions = self.reaction_collection.get_all_reactions()
        manual_well_ids = self._get_manual_well_assignments()
        using_manual_assignments = manual_well_ids is not None

        # Clear only reaction assignments (keep calibrations & excluded_wells)
        self.well_plate.clear_all_reaction_assignments()

        if using_manual_assignments:
            if len(manual_well_ids) != len(all_reactions):
                raise ValueError(
                    f"Manual well assignments ({len(manual_well_ids)}) "
                    f"must match the number of reactions ({len(all_reactions)}) "
                    f"in update_well_plate()."
                )
            self.well_plate.assign_reactions_to_specific_wells(
                all_reactions,
                manual_well_ids
            )
        else:
            start_row = self.experiment_model.get_start_row()
            start_col = self.experiment_model.get_start_col()
            self.well_plate.assign_reactions_to_wells(
                all_reactions,
                start_row=start_row,
                start_col=start_col
            )

        self.experiment_loaded.emit()

    def clear_experiment(self):
        """Clear all experiment data and reset the well plate."""
        if self.stock_solutions is not None:
            self.stock_solutions.clear_all_stock_solutions()
        if self.reaction_collection is not None:
            self.reaction_collection.clear_all_reactions()
        
        self.well_plate.clear_all_wells()
        self.printer_head_manager.clear_all_printer_heads()
        self.rack_model.clear_all_slots()
        self.experiment_loaded.emit()
        self.printer_head_manager.create_calibration_chip()
        calibration_chip = self.printer_head_manager.get_calibration_chip()
        self.printer_head_manager.swap_printer_head(4,calibration_chip)

    def assign_printer_heads(self):
        """Assign printer heads to the slots in the rack."""
        # Create and assign printer heads for each unique pair
        self.printer_head_manager.create_printer_heads(self.stock_solutions)
        for printer_head in list(getattr(self.printer_head_manager, "unassigned_printer_heads", []) or []):
            if getattr(printer_head, "calibration_chip", False):
                continue
            if getattr(printer_head, "printer_head_id", None):
                continue
            self._apply_runtime_printer_head_identity(printer_head)
        for i in range(self.rack_model.get_num_slots()):
            current_slot = self.rack_model.get_slot_info(i)
            if current_slot['printer_head'] != None:
                if current_slot['printer_head']['reagent'] == 'Calibration':
                    print('Skipping slot:',i)
                    continue
            if not self.printer_head_manager.assign_printer_head_to_slot(i):
                break  # Stop assigning if there are no more unassigned printer heads

    def record_image_metadata(self,timestamp):
        """Record metadata for the droplet images."""
        num_flashes, flash_duration, flash_delay, num_droplets, exposure_time = self.droplet_camera_model.get_image_metadata()
        current_position = self.machine_model.get_current_position_dict()
        print_width = self.machine_model.get_print_pulse_width()
        refuel_width = self.machine_model.get_refuel_pulse_width()
        print_pressure = self.machine_model.get_current_print_pressure()
        refuel_pressure = self.machine_model.get_current_refuel_pressure()

        file_dir = os.path.join(self.droplet_camera_model.save_dir, "metadata.csv")
        # Prepare metadata
        metadata = [
            timestamp,
            flash_duration,
            flash_delay,
            num_droplets,
            exposure_time,
            current_position['X'],
            current_position['Y'],
            current_position['Z'],
            print_width,
            refuel_width,
            print_pressure,
            refuel_pressure,
        ]

        # Save metadata to CSV
        if not os.path.isfile(file_dir):
            with open(file_dir, 'w', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["timestamp", "flash_duration", "flash_delay", "num_droplets", "exposure_time", "X_position", "Y_position", "Z_position", "print_pulse_width", "refuel_pulse_width", "print_pressure", "refuel_pressure"])
                writer.writerow(metadata)
        else:
            with open(file_dir, 'a', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(metadata)
        
        print(f"Metadata saved to {file_dir}")

    # def start_nozzle_calibration(self):
    #     nozzle_step = NozzlePositionStep(self.calibration_manager, self)
    #     self.calibration_manager.add_step(nozzle_step)
    #     self.calibration_manager.start()

    # def stop_calibration(self):
    #     self.calibration_manager.stop()


if __name__ == "__main__":
    model = Model()
    model.load_experiment_from_file('mock_reaction_compositions.csv')
