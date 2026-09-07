"""Authored qualification inputs and independent composition/count checks.

Real recipes stay external. This module never generates expectations using the
production optimizer or reaction enumerator.
"""
from dataclasses import dataclass, field
from itertools import product
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import re
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "tests/fixtures/optimizer_real_designs.json").read_text())
REFINEMENT = dict(quantum=0.1, max_refine=60, two_max_refine=40)
LEVELS = (0.25, 0.5, 1., 2., 5., 10., 20., 21.)
MANUAL_IDS = ("manual_5", "manual_8", "manual_groups", "three_pairs")
SYNTHETIC_IDS = tuple(f"dense_{rows}_{n}" for rows in (96, 384) for n in (5, 8, 10))
CASE_IDS = tuple(MANIFEST["cases"]) + SYNTHETIC_IDS + MANUAL_IDS + ("groups_import",)


def require_external(path):
    resolved = Path(path).resolve()
    inventory = subprocess.check_output(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], text=True)
    roots = [Path(line[len("worktree "):]).resolve() for line in inventory.splitlines() if line.startswith("worktree ")]
    if any(resolved.is_relative_to(root) for root in roots):
        raise ValueError("Qualification fixtures and evidence must be outside every Git worktree")
    return resolved


@dataclass
class Reagent:
    name: str
    targets: tuple
    group: str | None = None
    units: str = "mM"
    droplet: float = 10.
    maximum: float | None = 2000.
    fixed: float | None = None


@dataclass
class Case:
    name: str
    reagents: list = field(default_factory=list)
    design: object = None
    stock_frame: object = None
    printed: float = 1000.
    final: float = 5000.
    tolerance: float = 0.
    replicates: int = 1
    additional: list = field(default_factory=list)
    hashes: dict = field(default_factory=dict)

    @property
    def imported(self):
        return self.design is not None

    def compositions(self):
        if self.imported:
            return [{r.name: float(row[r.name + " " + r.units]) for r in self.reagents}
                    for row in self.design.to_dict("records")]
        dimensions = []
        groups = []
        for reagent in self.reagents:
            if reagent.group:
                if reagent.group in groups:
                    continue
                groups.append(reagent.group)
                dimensions.append([{r.name: t} for r in self.reagents if r.group == reagent.group
                                   for t in r.targets])
            else:
                dimensions.append([{reagent.name: t} for t in reagent.targets])
        base = [dict(item for part in parts for item in part.items()) for parts in product(*dimensions)]
        return [dict(row) for row in base for _ in range(self.replicates)] + [dict(r) for r in self.additional]

    def metadata(self, allow_two):
        return dict(name=self.name, target_reaction_volume_nL=self.printed, final_reaction_volume_nL=self.final,
                    printed_volume_tolerance_nL=self.tolerance, fill_droplet_volume_nL=10.,
                    replicates=self.replicates, allow_two_stock_solutions=allow_two,
                    allow_avoidable_target_grouping=False, randomize_assignments=False)

    def describe(self):
        rows = self.compositions()
        names = [r.name for r in self.reagents]
        levels = {n: sorted({row[n] for row in rows if n in row}) for n in names}
        active = [sum(v > 0 for v in row.values()) for row in rows]
        encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"))
        return dict(case=self.name, family="real_import" if self.hashes else "explicit_import" if self.imported else "manual",
                    authored_rows=len(rows), unique_compositions=len({tuple(sorted(r.items())) for r in rows}),
                    reagent_count=len(names), varying_reagent_count=sum(len(v) > 1 for v in levels.values()),
                    distinct_targets={k: len(v) for k, v in levels.items()},
                    nonzero_reagents_per_row={"min": min(active), "max": max(active)},
                    groups={g: [r.name for r in self.reagents if r.group == g]
                            for g in sorted({r.group for r in self.reagents if r.group})},
                    volumes=self.metadata(False), composition_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                    fixture_hashes=self.hashes)


def well_ids(count):
    return [f"{chr(65 + i // 24)}{i % 24 + 1}" for i in range(count)]


def as_import(case, name):
    rows = case.compositions()
    frame = pd.DataFrame({r.name + " " + r.units: [row.get(r.name, 0.) for row in rows]
                          for r in case.reagents})
    frame.insert(0, "Well", well_ids(len(rows)))
    reagents = [Reagent(r.name, tuple(sorted(set(frame[r.name + " " + r.units]))),
                         units=r.units, droplet=r.droplet, maximum=r.maximum, fixed=r.fixed)
                for r in case.reagents]
    stocks = pd.DataFrame([dict(reagent=r.name, stock_conc=r.fixed or r.maximum, units=r.units,
                                print_mode="Droplet", droplet_volume_nL=r.droplet) for r in reagents])
    return Case(name, reagents, frame, stocks, case.printed, case.final, case.tolerance)


def load_case(name, fixture_root=None):
    if name in MANIFEST["cases"]:
        if fixture_root is None:
            raise ValueError("Real designs require --fixture-root (external, hash-verified CSVs).")
        root = require_external(fixture_root)
        spec = MANIFEST["cases"][name]
        frames, hashes = {}, {}
        for kind in ("design", "stocks"):
            path = (root / spec["directory"] / spec[kind]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Fixture escapes its external root.")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != spec[kind + "_sha256"]:
                raise ValueError(f"Fixture hash mismatch: {path.name}")
            hashes[kind] = digest
            frames[kind] = pd.read_csv(path)
        frame = frames["design"]
        assert len(frame) == spec["rows"]
        reagents, rename = [], {}
        for col in frame.columns:
            if col.casefold() == "well":
                continue
            match = re.fullmatch(r"(.+?)\s+(?:\(([^)]+)\)|(\S+))", col)
            assert match, col
            label, units = match[1], match[2] or match[3]
            rename[col] = label + " " + units
            reagents.append(Reagent(label, tuple(sorted(set(frame[col].astype(float)))), units=units, maximum=None))
        assert len(reagents) == 9
        return Case(name, reagents, frame.rename(columns=rename), frames["stocks"],
                    spec["printed_nL"], 10000., spec["tolerance_nL"], hashes=hashes)
    if name in SYNTHETIC_IDS:
        _, row_count, count = name.split("_")
        row_count, count = int(row_count), int(count)
        rng = random.Random(5976 + row_count + 100 * count)
        reagents, data = [], {"Well": well_ids(row_count)}
        for j in range(count):
            scale = (1, 2, 4)[j % 3]
            targets = tuple(scale * t for t in LEVELS[:3 + j % 6])
            reagent = Reagent(f"Reagent{j + 1}", targets, maximum=2000. * scale)
            reagents.append(reagent)
            values = [targets[i % len(targets)] for i in range(row_count)]
            rng.shuffle(values)
            data[reagent.name + " mM"] = values
        case = Case(name, reagents, pd.DataFrame(data), printed=100. * count)
        case.stock_frame = pd.DataFrame([dict(reagent=r.name, stock_conc=r.maximum, units="mM",
                                              print_mode="Droplet", droplet_volume_nL=10.) for r in reagents])
        assert case.describe()["unique_compositions"] >= 0.9 * row_count
        return case
    if name == "groups_import":
        return as_import(load_case("manual_groups"), name)
    if name not in MANUAL_IDS:
        raise ValueError(f"Unknown workload: {name}")
    varying, fixed = {"manual_5": (5, 0), "manual_8": (4, 4),
                      "manual_groups": (1, 5), "three_pairs": (3, 2)}[name]
    reagents = [Reagent(f"Signal{j + 1}", tuple((1, 2, 4)[j % 3] * t for t in
                 ((.5, 1., 5.) if name == "manual_5" else (.5, 1., 5., 20.))),
                 maximum=2000. * (1, 2, 4)[j % 3]) for j in range(varying)]
    if name == "manual_groups":
        reagents += [Reagent(f"Group{g}_{option}", (.5, 1., 5.), group=f"Group{g}")
                     for g in (1, 2) for option in ("A", "B")]
    reagents += [Reagent(f"Fixed{j + 1}", (.01,), fixed=5.) for j in range(fixed)]
    return Case(name, reagents, printed=240. if name == "three_pairs" else 100. * len(reagents))


def populate_model(case, allow_two):
    """Synchronous model-only route; UI qualification uses the controls instead."""
    if case.hashes:
        raise ValueError("Real designs must use the import report's parsed stock settings")
    from Model import ExperimentModel
    model = ExperimentModel()
    model.set_metadata(**case.metadata(allow_two))
    if case.imported:
        model.set_uploaded_design_from_dataframe(case.design, droplet_nL_default=10.)
        for factor, reagent in zip(model.factors, case.reagents):
            factor.options[0].max_stock_conc = reagent.maximum
        return model
    groups = set()
    for r in case.reagents:
        kw = dict(units=r.units, droplet_nL=r.droplet, max_stock_conc=r.maximum, forced_stock_conc=r.fixed)
        if r.group:
            if r.group not in groups:
                model.add_choice_group(r.group)
                groups.add(r.group)
            model.add_choice_option(r.group, r.name, list(r.targets), **kw)
        else:
            model.add_additive(r.name, list(r.targets), **kw)
    return model


def allocation_evidence(model, result):
    """Stable JSON projection; diagnostic timing never participates in equality."""
    from tests.test_stock_optimizer_performance import _public_result_rank
    plans = repr(sorted(model.plans_per_option.items(), key=lambda row: str(row[0])))
    work = {k: v for k, v in result.items() if ("work" in k or k.endswith("_evaluated")
            or k.endswith("_pruned") or k == "stock_allocation_stop_reason")
            and not any(word in k for word in ("elapsed", "time", "ms"))}
    return dict(allocation_sha256=hashlib.sha256(plans.encode()).hexdigest(),
                rank=list(_public_result_rank(model, result)), selected_rank=result.get("optimizer_selected_rank"),
                two_stock_keys=[list(k) for k,p in model.plans_per_option.items() if p["n_stocks"] == 2],
                work=work, stock_ids=[model.build_stock_prep_stock_id(r) for r in model.get_stock_table_rows(include_fill=False)])


def assert_physical_allocation(case, model):
    """Recompute volume/concentration arithmetic from raw stored count maps."""
    expected = case.compositions()
    actual = [{key[1] or key[0]: value for key, value in spec["reaction"].items()}
              for spec in model._iter_reaction_run_specs()]
    normalize = lambda rows: Counter(tuple(sorted((k, round(v, 6)) for k,v in row.items())) for row in rows)
    assert normalize(actual) == normalize(expected), "Authored reaction compositions changed"
    assert len(model._reactions_df) == len(expected)
    if case.imported:
        assert [tuple(sorted((k, round(v, 6)) for k,v in r.items())) for r in actual] == [
            tuple(sorted((k, round(v, 6)) for k,v in r.items())) for r in expected], "Uploaded row order changed"
        assert list(model._uploaded_well_ids) == list(case.design["Well"])
    options = {(f.name, r.name if f.kind == "choice" else None): r for f in model.factors for r in f.options}
    previews = model.get_target_preview_map()
    for spec, row in zip(model._iter_reaction_run_specs(), model._reactions_df.to_dict("records")):
        volume = 0.
        for key, target in spec["reaction"].items():
            plan = model.plans_per_option[key]
            achieved = float(options[key].starting_conc or 0.)
            additive = max(0., target - achieved)
            for stock in plan["stocks"]:
                mapping = stock["droplets_per_target"]
                matches = [count for t,count in mapping.items() if math.isclose(float(t), additive, abs_tol=1e-6)]
                assert len(matches) == 1, "Missing/ambiguous exact target mapping"
                count = matches[0]
                assert count >= 0 and int(count) == count
                dv, concentration = stock["droplet_volume_nL"], stock["stock_concentration"]
                bound = options[key].max_stock_conc
                assert bound is None or concentration <= bound + 1e-9
                volume += count * dv
                achieved += count * dv * concentration / case.final
            preview = next(p for p in previews[key] if math.isclose(p["requested_final"], target, abs_tol=1e-6))
            assert math.isclose(achieved, preview["achieved_final"], rel_tol=1e-8, abs_tol=1e-6)
        assert math.isclose(volume, row["nonfill_volume_nL"], abs_tol=1e-6)
        fill_dv = float(model.metadata["fill_droplet_volume_nL"])
        cap = min(case.printed, case.final) + case.tolerance
        expected_fill = min(max(0, int(round((case.printed-volume)/fill_dv))),
                            max(0, int(math.floor((cap-volume+1e-9)/fill_dv))))
        assert row["fill_drops"] == expected_fill
        assert volume + row["fill_drops"] * fill_dv <= cap + 1e-6
