import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone


SCHEMA_FAMILY = "labcraft.calibration_memory"
SCHEMA_VERSION = 1

QUALITY_EXPLICIT = "explicit"
QUALITY_INFERRED = "inferred"
QUALITY_UNKNOWN = "unknown"


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_str(value):
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _slugify(value):
    value = _clean_str(value)
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


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _list_of_str(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out = []
    for value in values:
        cleaned = _clean_str(value)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _normalize_quality(value):
    value = _clean_str(value)
    if value is None:
        return QUALITY_UNKNOWN
    value = value.lower()
    if value == "derived":
        return QUALITY_INFERRED
    if value == "missing":
        return QUALITY_UNKNOWN
    if value in (QUALITY_EXPLICIT, QUALITY_INFERRED, QUALITY_UNKNOWN):
        return value
    return QUALITY_UNKNOWN


def normalize_identity_quality_map(identity_quality):
    quality = dict(identity_quality or {})
    return {str(key): _normalize_quality(value) for key, value in quality.items()}


def normalize_legacy_context(context):
    out = dict(context or {})
    out["identity_quality"] = normalize_identity_quality_map(out.get("identity_quality", {}))
    if "reagent_display_name" not in out and out.get("display_name"):
        out["reagent_display_name"] = out.get("display_name")
    if "nominal_nozzle_diameter_um" not in out and out.get("nozzle_diameter_um") is not None:
        out["nominal_nozzle_diameter_um"] = out.get("nozzle_diameter_um")
    return out


def _write_json_atomic(path, payload):
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix="._tmp_",
        suffix=os.path.splitext(path)[1] or ".tmp",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
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


@dataclass
class ReagentIdentity:
    reagent_id: str
    display_name: str
    stock_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    reagent_family: str | None = None
    glycerol_percent: float | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, payload):
        reagent_id = _slugify(payload.get("reagent_id"))
        if reagent_id is None:
            raise ValueError("reagent_id is required")
        display_name = _clean_str(payload.get("display_name")) or reagent_id
        return cls(
            reagent_id=reagent_id,
            display_name=display_name,
            stock_ids=_list_of_str(payload.get("stock_ids")),
            aliases=_list_of_str(payload.get("aliases")),
            reagent_family=_clean_str(payload.get("reagent_family")),
            glycerol_percent=_float_or_none(payload.get("glycerol_percent")),
            tags=_list_of_str(payload.get("tags")),
            notes=_clean_str(payload.get("notes")) or "",
        )

    def to_dict(self):
        return {
            "reagent_id": self.reagent_id,
            "display_name": self.display_name,
            "stock_ids": list(self.stock_ids),
            "aliases": list(self.aliases),
            "reagent_family": self.reagent_family,
            "glycerol_percent": self.glycerol_percent,
            "tags": list(self.tags),
            "notes": self.notes,
        }


@dataclass
class PrinterHeadTypeIdentity:
    head_type_id: str
    display_name: str
    nominal_nozzle_diameter_um: float | None = None
    default_droplet_ejection_volume_nL: float | None = None
    default_stream_ejection_volume_nL: float | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, payload):
        head_type_id = _slugify(payload.get("head_type_id"))
        if head_type_id is None:
            raise ValueError("head_type_id is required")
        display_name = _clean_str(payload.get("display_name")) or head_type_id
        return cls(
            head_type_id=head_type_id,
            display_name=display_name,
            nominal_nozzle_diameter_um=_float_or_none(payload.get("nominal_nozzle_diameter_um")),
            default_droplet_ejection_volume_nL=_float_or_none(payload.get("default_droplet_ejection_volume_nL")),
            default_stream_ejection_volume_nL=_float_or_none(payload.get("default_stream_ejection_volume_nL")),
            tags=_list_of_str(payload.get("tags")),
            notes=_clean_str(payload.get("notes")) or "",
        )

    def to_dict(self):
        return {
            "head_type_id": self.head_type_id,
            "display_name": self.display_name,
            "nominal_nozzle_diameter_um": self.nominal_nozzle_diameter_um,
            "default_droplet_ejection_volume_nL": self.default_droplet_ejection_volume_nL,
            "default_stream_ejection_volume_nL": self.default_stream_ejection_volume_nL,
            "tags": list(self.tags),
            "notes": self.notes,
        }


@dataclass
class PrinterHeadIdentity:
    printer_head_id: str
    head_type_id: str | None = None
    display_name: str | None = None
    nominal_nozzle_diameter_um: float | None = None
    measured_nozzle_diameter_um: float | None = None
    manufacturer_batch: str | None = None
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, payload):
        printer_head_id = _clean_str(payload.get("printer_head_id"))
        if printer_head_id is None:
            raise ValueError("printer_head_id is required")
        return cls(
            printer_head_id=printer_head_id,
            head_type_id=_slugify(payload.get("head_type_id")),
            display_name=_clean_str(payload.get("display_name")) or printer_head_id,
            nominal_nozzle_diameter_um=_float_or_none(payload.get("nominal_nozzle_diameter_um")),
            measured_nozzle_diameter_um=_float_or_none(payload.get("measured_nozzle_diameter_um")),
            manufacturer_batch=_clean_str(payload.get("manufacturer_batch")),
            aliases=_list_of_str(payload.get("aliases")),
            tags=_list_of_str(payload.get("tags")),
            notes=_clean_str(payload.get("notes")) or "",
        )

    def to_dict(self):
        return {
            "printer_head_id": self.printer_head_id,
            "head_type_id": self.head_type_id,
            "display_name": self.display_name,
            "nominal_nozzle_diameter_um": self.nominal_nozzle_diameter_um,
            "measured_nozzle_diameter_um": self.measured_nozzle_diameter_um,
            "manufacturer_batch": self.manufacturer_batch,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
            "notes": self.notes,
        }


def _default_reagent_items():
    return [
        ReagentIdentity(
            reagent_id="water",
            display_name="Water",
            aliases=["water", "Water"],
            reagent_family="aqueous",
            glycerol_percent=0.0,
            tags=["baseline_study"],
        ),
        ReagentIdentity(
            reagent_id="glycerol_25pct",
            display_name="25% Glycerol",
            aliases=["glycerol_25pct", "25% glycerol", "25 percent glycerol"],
            reagent_family="aqueous_glycerol",
            glycerol_percent=25.0,
            tags=["baseline_study"],
        ),
        ReagentIdentity(
            reagent_id="glycerol_50pct",
            display_name="50% Glycerol",
            aliases=["glycerol_50pct", "50% glycerol", "50 percent glycerol"],
            reagent_family="aqueous_glycerol",
            glycerol_percent=50.0,
            tags=["baseline_study"],
        ),
    ]


def _default_head_type_items():
    return [
        PrinterHeadTypeIdentity(
            head_type_id="nozzle_80um",
            display_name="80 um nozzle",
            nominal_nozzle_diameter_um=80.0,
            default_droplet_ejection_volume_nL=7.0,
            default_stream_ejection_volume_nL=35.0,
            tags=["baseline_study"],
        ),
        PrinterHeadTypeIdentity(
            head_type_id="nozzle_100um",
            display_name="100 um nozzle",
            nominal_nozzle_diameter_um=100.0,
            default_droplet_ejection_volume_nL=9.0,
            default_stream_ejection_volume_nL=60.0,
            tags=["baseline_study"],
        ),
        PrinterHeadTypeIdentity(
            head_type_id="nozzle_120um",
            display_name="120 um nozzle",
            nominal_nozzle_diameter_um=120.0,
            default_droplet_ejection_volume_nL=12.0,
            default_stream_ejection_volume_nL=80.0,
            tags=["baseline_study"],
        ),
    ]


def _default_printer_head_items():
    items = []
    for nozzle_um in (80, 100, 120):
        head_type_id = f"nozzle_{nozzle_um}um"
        for idx in range(1, 6):
            printer_head_id = f"{head_type_id}_h{idx:02d}"
            items.append(
                PrinterHeadIdentity(
                    printer_head_id=printer_head_id,
                    head_type_id=head_type_id,
                    display_name=f"{nozzle_um} um H{idx:02d}",
                    nominal_nozzle_diameter_um=float(nozzle_um),
                    aliases=[printer_head_id],
                    tags=["baseline_study"],
                )
            )
    return items


class CalibrationIdentityRegistry:
    REAGENTS_SCHEMA = f"{SCHEMA_FAMILY}.reagents_registry"
    HEAD_TYPES_SCHEMA = f"{SCHEMA_FAMILY}.printer_head_types_registry"
    PRINTER_HEADS_SCHEMA = f"{SCHEMA_FAMILY}.printer_heads_registry"

    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)
        self.entities_dir = os.path.join(self.root_dir, "entities")
        self.reagents_path = os.path.join(self.entities_dir, "reagents.json")
        self.printer_head_types_path = os.path.join(self.entities_dir, "printer_head_types.json")
        self.printer_heads_path = os.path.join(self.entities_dir, "printer_heads.json")

    def ensure_initialized(self):
        os.makedirs(self.entities_dir, exist_ok=True)
        if not os.path.exists(self.reagents_path):
            self.save_reagents(_default_reagent_items())
        if not os.path.exists(self.printer_head_types_path):
            self.save_printer_head_types(_default_head_type_items())
        if not os.path.exists(self.printer_heads_path):
            self.save_printer_heads(_default_printer_head_items())

    def _load_registry(self, path, *, schema_name, item_cls, default_items):
        if not os.path.exists(path):
            items = list(default_items)
            self._save_registry(path, schema_name=schema_name, items=items)
            return {self._item_key(item): item for item in items}

        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if _clean_str(payload.get("schema_name")) != schema_name:
            raise ValueError(f"Unexpected schema_name in {path}")
        if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version in {path}")

        items = {}
        for raw_item in payload.get("items", []):
            item = item_cls.from_dict(raw_item)
            items[self._item_key(item)] = item
        return items

    @staticmethod
    def _item_key(item):
        if hasattr(item, "reagent_id"):
            return item.reagent_id
        if hasattr(item, "head_type_id") and not hasattr(item, "printer_head_id"):
            return item.head_type_id
        return item.printer_head_id

    def _save_registry(self, path, *, schema_name, items):
        payload = {
            "schema_name": schema_name,
            "schema_version": int(SCHEMA_VERSION),
            "updated_at_utc": _now_utc(),
            "items": [item.to_dict() for item in items],
        }
        _write_json_atomic(path, payload)

    def load_reagents(self):
        self.ensure_initialized()
        return self._load_registry(
            self.reagents_path,
            schema_name=self.REAGENTS_SCHEMA,
            item_cls=ReagentIdentity,
            default_items=_default_reagent_items(),
        )

    def save_reagents(self, items):
        norm_items = [item if isinstance(item, ReagentIdentity) else ReagentIdentity.from_dict(item) for item in items]
        self._save_registry(self.reagents_path, schema_name=self.REAGENTS_SCHEMA, items=norm_items)

    def load_printer_head_types(self):
        self.ensure_initialized()
        return self._load_registry(
            self.printer_head_types_path,
            schema_name=self.HEAD_TYPES_SCHEMA,
            item_cls=PrinterHeadTypeIdentity,
            default_items=_default_head_type_items(),
        )

    def save_printer_head_types(self, items):
        norm_items = [
            item if isinstance(item, PrinterHeadTypeIdentity) else PrinterHeadTypeIdentity.from_dict(item)
            for item in items
        ]
        self._save_registry(self.printer_head_types_path, schema_name=self.HEAD_TYPES_SCHEMA, items=norm_items)

    def load_printer_heads(self):
        self.ensure_initialized()
        return self._load_registry(
            self.printer_heads_path,
            schema_name=self.PRINTER_HEADS_SCHEMA,
            item_cls=PrinterHeadIdentity,
            default_items=_default_printer_head_items(),
        )

    def save_printer_heads(self, items):
        norm_items = [
            item if isinstance(item, PrinterHeadIdentity) else PrinterHeadIdentity.from_dict(item)
            for item in items
        ]
        self._save_registry(self.printer_heads_path, schema_name=self.PRINTER_HEADS_SCHEMA, items=norm_items)

    def get_reagent(self, reagent_id):
        return self.load_reagents().get(_slugify(reagent_id))

    def get_head_type(self, head_type_id):
        return self.load_printer_head_types().get(_slugify(head_type_id))

    def get_printer_head(self, printer_head_id):
        return self.load_printer_heads().get(_clean_str(printer_head_id))

    def upsert_reagent(self, payload):
        reagent = payload if isinstance(payload, ReagentIdentity) else ReagentIdentity.from_dict(payload)
        items = self.load_reagents()
        items[reagent.reagent_id] = reagent
        self.save_reagents(items.values())
        return reagent

    def upsert_printer_head_type(self, payload):
        head_type = payload if isinstance(payload, PrinterHeadTypeIdentity) else PrinterHeadTypeIdentity.from_dict(payload)
        items = self.load_printer_head_types()
        items[head_type.head_type_id] = head_type
        self.save_printer_head_types(items.values())
        return head_type

    def upsert_printer_head(self, payload):
        printer_head = payload if isinstance(payload, PrinterHeadIdentity) else PrinterHeadIdentity.from_dict(payload)
        items = self.load_printer_heads()
        items[printer_head.printer_head_id] = printer_head
        self.save_printer_heads(items.values())
        return printer_head

    def assign_reagent_identity(self, stock_solution, reagent_id):
        item = self.get_reagent(reagent_id)
        if item is None:
            raise KeyError(f"Unknown reagent_id: {reagent_id}")
        setter = getattr(stock_solution, "set_reagent_identity", None)
        if callable(setter):
            setter(
                reagent_id=item.reagent_id,
                display_name=item.display_name,
                reagent_family=item.reagent_family,
                glycerol_percent=item.glycerol_percent,
                tags=item.tags,
                notes=item.notes,
            )
        else:
            stock_solution.reagent_id = item.reagent_id
            stock_solution.display_name = item.display_name
            stock_solution.reagent_family = item.reagent_family
            stock_solution.glycerol_percent = item.glycerol_percent
            stock_solution.tags = list(item.tags)
            stock_solution.notes = item.notes
        return item

    def assign_printer_head_identity(self, printer_head, printer_head_id):
        item = self.get_printer_head(printer_head_id)
        if item is None:
            raise KeyError(f"Unknown printer_head_id: {printer_head_id}")
        setter = getattr(printer_head, "set_identity_metadata", None)
        if callable(setter):
            setter(
                printer_head_id=item.printer_head_id,
                head_type_id=item.head_type_id,
                display_name=item.display_name,
                nominal_nozzle_diameter_um=item.nominal_nozzle_diameter_um,
                measured_nozzle_diameter_um=item.measured_nozzle_diameter_um,
                manufacturer_batch=item.manufacturer_batch,
                tags=item.tags,
                notes=item.notes,
            )
        else:
            printer_head.printer_head_id = item.printer_head_id
            printer_head.head_type_id = item.head_type_id
            printer_head.display_name = item.display_name
            printer_head.nominal_nozzle_diameter_um = item.nominal_nozzle_diameter_um
            printer_head.measured_nozzle_diameter_um = item.measured_nozzle_diameter_um
            printer_head.manufacturer_batch = item.manufacturer_batch
            printer_head.identity_tags = list(item.tags)
            printer_head.identity_notes = item.notes
        return item

    def resolve_reagent(self, *, stock_solution=None, stock_id=None, reagent_name=None):
        items = self.load_reagents()

        if stock_id is None and stock_solution is not None:
            getter = getattr(stock_solution, "get_stock_id", None)
            if callable(getter):
                stock_id = _clean_str(getter())
            if stock_id is None:
                stock_id = _clean_str(getattr(stock_solution, "stock_id", None))

        if reagent_name is None and stock_solution is not None:
            getter = getattr(stock_solution, "get_reagent_name", None)
            if callable(getter):
                reagent_name = _clean_str(getter())
            if reagent_name is None:
                reagent_name = _clean_str(getattr(stock_solution, "reagent_name", None))

        explicit_reagent_id = _clean_str(getattr(stock_solution, "reagent_id", None)) if stock_solution is not None else None
        explicit_display_name = _clean_str(getattr(stock_solution, "display_name", None)) if stock_solution is not None else None
        explicit_family = _clean_str(getattr(stock_solution, "reagent_family", None)) if stock_solution is not None else None
        explicit_glycerol = _float_or_none(getattr(stock_solution, "glycerol_percent", None)) if stock_solution is not None else None
        explicit_tags = _list_of_str(getattr(stock_solution, "tags", None)) if stock_solution is not None else []
        explicit_notes = _clean_str(getattr(stock_solution, "notes", None)) if stock_solution is not None else None

        matched_item = None
        match_quality = QUALITY_UNKNOWN
        match_source = "unknown"

        if explicit_reagent_id:
            matched_item = items.get(_slugify(explicit_reagent_id))
            if matched_item is not None:
                match_quality = QUALITY_EXPLICIT
                match_source = "runtime_reagent_id"

        if matched_item is None and stock_id:
            for item in items.values():
                if stock_id in item.stock_ids:
                    matched_item = item
                    match_quality = QUALITY_EXPLICIT
                    match_source = "stock_id"
                    break

        reagent_name_slug = _slugify(reagent_name)
        if matched_item is None and reagent_name_slug:
            for item in items.values():
                aliases = {_slugify(alias) for alias in item.aliases}
                aliases.add(item.reagent_id)
                if reagent_name_slug in aliases:
                    matched_item = item
                    match_quality = QUALITY_INFERRED
                    match_source = "alias"
                    break

        reagent_id = None
        display_name = explicit_display_name or reagent_name
        reagent_family = explicit_family
        glycerol_percent = explicit_glycerol
        tags = list(explicit_tags)
        notes = explicit_notes or ""

        if matched_item is not None:
            reagent_id = matched_item.reagent_id
            display_name = explicit_display_name or matched_item.display_name or display_name
            reagent_family = matched_item.reagent_family or reagent_family
            glycerol_percent = matched_item.glycerol_percent if matched_item.glycerol_percent is not None else glycerol_percent
            tags = list(dict.fromkeys(list(matched_item.tags) + tags))
            notes = matched_item.notes or notes
        elif explicit_reagent_id:
            reagent_id = _slugify(explicit_reagent_id)
            match_quality = QUALITY_EXPLICIT
            match_source = "runtime_reagent_id_unregistered"
        elif reagent_name_slug:
            reagent_id = reagent_name_slug
            match_quality = QUALITY_INFERRED
            match_source = "derived_from_name"

        return {
            "reagent_id": reagent_id,
            "display_name": display_name,
            "reagent_family": reagent_family,
            "glycerol_percent": glycerol_percent,
            "tags": tags,
            "notes": notes,
            "stock_id": stock_id,
            "quality": {
                "stock_id": QUALITY_EXPLICIT if stock_id else QUALITY_UNKNOWN,
                "reagent_id": match_quality,
            },
            "match_source": match_source,
        }

    def resolve_printer_head(self, *, printer_head=None, slot_number=None):
        head_items = self.load_printer_heads()
        head_types = self.load_printer_head_types()

        explicit_head_id = _clean_str(getattr(printer_head, "printer_head_id", None)) if printer_head is not None else None
        explicit_head_type_id = _slugify(getattr(printer_head, "head_type_id", None)) if printer_head is not None else None
        explicit_display_name = _clean_str(getattr(printer_head, "display_name", None)) if printer_head is not None else None
        explicit_nominal = _float_or_none(getattr(printer_head, "nominal_nozzle_diameter_um", None)) if printer_head is not None else None
        explicit_measured = _float_or_none(getattr(printer_head, "measured_nozzle_diameter_um", None)) if printer_head is not None else None
        explicit_batch = _clean_str(getattr(printer_head, "manufacturer_batch", None)) if printer_head is not None else None
        explicit_tags = _list_of_str(getattr(printer_head, "identity_tags", None)) if printer_head is not None else []
        explicit_notes = _clean_str(getattr(printer_head, "identity_notes", None)) if printer_head is not None else None

        stable_alias_candidates = []
        alias_candidates = []
        if printer_head is not None:
            for attr_name in ("printer_head_id", "serial", "id"):
                vals = _list_of_str(getattr(printer_head, attr_name, None))
                stable_alias_candidates.extend(vals)
                alias_candidates.extend(vals)
            alias_candidates.extend(_list_of_str(getattr(printer_head, "display_name", None)))

        matched_head = None
        head_quality = QUALITY_UNKNOWN
        head_source = "unknown"

        if explicit_head_id:
            matched_head = head_items.get(explicit_head_id)
            if matched_head is not None:
                head_quality = QUALITY_EXPLICIT
                head_source = "runtime_printer_head_id"

        if matched_head is None:
            candidate_set = set(alias_candidates)
            for head in head_items.values():
                aliases = set(head.aliases)
                aliases.add(head.printer_head_id)
                if candidate_set.intersection(aliases):
                    matched_head = head
                    head_quality = QUALITY_EXPLICIT
                    head_source = "registry_alias"
                    break

        printer_head_id = explicit_head_id
        printer_head_display_name = explicit_display_name or explicit_head_id
        nominal_nozzle_diameter_um = explicit_nominal
        measured_nozzle_diameter_um = explicit_measured
        manufacturer_batch = explicit_batch
        tags = list(explicit_tags)
        notes = explicit_notes or ""

        if matched_head is not None:
            printer_head_id = matched_head.printer_head_id
            printer_head_display_name = matched_head.display_name or printer_head_display_name
            nominal_nozzle_diameter_um = (
                matched_head.nominal_nozzle_diameter_um
                if matched_head.nominal_nozzle_diameter_um is not None
                else nominal_nozzle_diameter_um
            )
            measured_nozzle_diameter_um = (
                matched_head.measured_nozzle_diameter_um
                if matched_head.measured_nozzle_diameter_um is not None
                else measured_nozzle_diameter_um
            )
            manufacturer_batch = matched_head.manufacturer_batch or manufacturer_batch
            tags = list(dict.fromkeys(list(matched_head.tags) + tags))
            notes = matched_head.notes or notes
        elif explicit_head_id:
            head_quality = QUALITY_EXPLICIT
            head_source = "runtime_printer_head_id_unregistered"
        elif stable_alias_candidates:
            printer_head_id = stable_alias_candidates[0]
            printer_head_display_name = printer_head_display_name or printer_head_id
            head_quality = QUALITY_EXPLICIT
            head_source = "runtime_alias_unregistered"
        elif slot_number is not None:
            printer_head_id = f"gripper_slot_{int(slot_number)}"
            printer_head_display_name = printer_head_id
            head_quality = QUALITY_INFERRED
            head_source = "gripper_slot"

        matched_head_type = None
        head_type_quality = QUALITY_UNKNOWN
        head_type_source = "unknown"

        if matched_head is not None and matched_head.head_type_id:
            matched_head_type = head_types.get(matched_head.head_type_id)
            explicit_head_type_id = matched_head.head_type_id
            head_type_quality = QUALITY_EXPLICIT
            head_type_source = "printer_head_registry"

        if matched_head_type is None and explicit_head_type_id:
            matched_head_type = head_types.get(explicit_head_type_id)
            head_type_quality = QUALITY_EXPLICIT
            head_type_source = "runtime_head_type_id"

        if matched_head_type is None and explicit_nominal is not None:
            for head_type in head_types.values():
                if head_type.nominal_nozzle_diameter_um == explicit_nominal:
                    matched_head_type = head_type
                    head_type_quality = QUALITY_INFERRED
                    head_type_source = "nominal_nozzle_diameter_um"
                    break

        head_type_id = explicit_head_type_id
        head_type_display_name = None
        if matched_head_type is not None:
            head_type_id = matched_head_type.head_type_id
            head_type_display_name = matched_head_type.display_name
            if nominal_nozzle_diameter_um is None:
                nominal_nozzle_diameter_um = matched_head_type.nominal_nozzle_diameter_um
        elif head_type_id:
            head_type_quality = QUALITY_EXPLICIT
            head_type_source = "runtime_head_type_id_unregistered"

        nozzle_quality = QUALITY_UNKNOWN
        if nominal_nozzle_diameter_um is not None:
            nozzle_quality = QUALITY_EXPLICIT if head_type_quality == QUALITY_EXPLICIT or explicit_nominal is not None else QUALITY_INFERRED

        return {
            "printer_head_id": printer_head_id,
            "display_name": printer_head_display_name,
            "head_type_id": head_type_id,
            "head_type_display_name": head_type_display_name,
            "nominal_nozzle_diameter_um": nominal_nozzle_diameter_um,
            "measured_nozzle_diameter_um": measured_nozzle_diameter_um,
            "manufacturer_batch": manufacturer_batch,
            "tags": tags,
            "notes": notes,
            "quality": {
                "printer_head_id": head_quality,
                "head_type_id": head_type_quality,
                "nominal_nozzle_diameter_um": nozzle_quality,
                "measured_nozzle_diameter_um": QUALITY_EXPLICIT if measured_nozzle_diameter_um is not None else QUALITY_UNKNOWN,
            },
            "match_source": {
                "printer_head": head_source,
                "head_type": head_type_source,
            },
        }
