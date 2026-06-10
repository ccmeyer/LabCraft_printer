from types import SimpleNamespace

from CalibrationIdentity import CalibrationIdentityRegistry, normalize_legacy_context


class _DummyStockSolution:
    def __init__(self, stock_id="Water_0.00_--", reagent_name="Water"):
        self.stock_id = stock_id
        self.reagent_name = reagent_name
        self.reagent_id = None
        self.display_name = None
        self.reagent_family = None
        self.glycerol_percent = None
        self.tags = []
        self.notes = ""

    def get_stock_id(self):
        return self.stock_id

    def get_reagent_name(self):
        return self.reagent_name

    def set_reagent_identity(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _DummyPrinterHead:
    def __init__(self):
        self.printer_head_id = None
        self.head_type_id = None
        self.display_name = None
        self.nominal_nozzle_diameter_um = None
        self.measured_nozzle_diameter_um = None
        self.manufacturer_batch = None
        self.identity_tags = []
        self.identity_notes = ""
        self.serial = None
        self.id = None

    def set_identity_metadata(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_identity_registry_loads_seeded_defaults_and_roundtrips_updates(tmp_path):
    registry = CalibrationIdentityRegistry(str(tmp_path / "CalibrationMemory"))
    registry.ensure_initialized()

    reagents = registry.load_reagents()
    head_types = registry.load_printer_head_types()
    printer_heads = registry.load_printer_heads()

    assert set(reagents.keys()) == {"water", "glycerol_25pct", "glycerol_50pct"}
    assert set(head_types.keys()) == {"nozzle_80um", "nozzle_100um", "nozzle_120um"}
    assert len(printer_heads) == 15
    assert head_types["nozzle_80um"].default_droplet_ejection_volume_nL == 7.0
    assert head_types["nozzle_80um"].default_stream_ejection_volume_nL == 35.0
    assert head_types["nozzle_100um"].default_droplet_ejection_volume_nL == 9.0
    assert head_types["nozzle_100um"].default_stream_ejection_volume_nL == 60.0
    assert head_types["nozzle_120um"].default_droplet_ejection_volume_nL == 12.0
    assert head_types["nozzle_120um"].default_stream_ejection_volume_nL == 80.0

    updated = registry.upsert_reagent(
        {
            "reagent_id": "water",
            "display_name": "Water",
            "stock_ids": ["Water_0.00_--"],
            "aliases": ["water", "Water"],
            "reagent_family": "aqueous",
            "glycerol_percent": 0.0,
            "tags": ["baseline_study", "mapped_stock_id"],
            "notes": "test update",
        }
    )
    assert updated.stock_ids == ["Water_0.00_--"]
    assert registry.get_reagent("water").stock_ids == ["Water_0.00_--"]

    updated_head_type = registry.upsert_printer_head_type(
        {
            "head_type_id": "nozzle_100um",
            "display_name": "100 um nozzle",
            "nominal_nozzle_diameter_um": 100.0,
            "default_droplet_ejection_volume_nL": 9.5,
            "default_stream_ejection_volume_nL": 62.5,
        }
    )
    assert updated_head_type.default_droplet_ejection_volume_nL == 9.5
    assert updated_head_type.default_stream_ejection_volume_nL == 62.5
    assert registry.get_head_type("nozzle_100um").default_droplet_ejection_volume_nL == 9.5
    assert registry.get_head_type("nozzle_100um").to_dict()["default_stream_ejection_volume_nL"] == 62.5


def test_identity_registry_resolves_reagent_explicit_and_inferred_paths(tmp_path):
    registry = CalibrationIdentityRegistry(str(tmp_path / "CalibrationMemory"))
    registry.ensure_initialized()
    registry.upsert_reagent(
        {
            "reagent_id": "water",
            "display_name": "Water",
            "stock_ids": ["Water_0.00_--"],
            "aliases": ["water", "Water"],
            "reagent_family": "aqueous",
            "glycerol_percent": 0.0,
            "tags": ["baseline_study"],
            "notes": "",
        }
    )

    resolved_explicit = registry.resolve_reagent(
        stock_solution=_DummyStockSolution(stock_id="Water_0.00_--", reagent_name="Water")
    )
    assert resolved_explicit["reagent_id"] == "water"
    assert resolved_explicit["quality"]["stock_id"] == "explicit"
    assert resolved_explicit["quality"]["reagent_id"] == "explicit"

    resolved_inferred = registry.resolve_reagent(
        stock_solution=_DummyStockSolution(stock_id="Unknown_0.00_--", reagent_name="25% glycerol")
    )
    assert resolved_inferred["reagent_id"] == "glycerol_25pct"
    assert resolved_inferred["quality"]["reagent_id"] == "inferred"


def test_identity_registry_resolves_printer_head_explicit_and_weak_fallback(tmp_path):
    registry = CalibrationIdentityRegistry(str(tmp_path / "CalibrationMemory"))
    registry.ensure_initialized()

    explicit_head = _DummyPrinterHead()
    explicit_head.set_identity_metadata(
        printer_head_id="nozzle_100um_h03",
        head_type_id="nozzle_100um",
        display_name="100 um H03",
        nominal_nozzle_diameter_um=100.0,
    )
    explicit = registry.resolve_printer_head(printer_head=explicit_head, slot_number=2)
    assert explicit["printer_head_id"] == "nozzle_100um_h03"
    assert explicit["head_type_id"] == "nozzle_100um"
    assert explicit["quality"]["printer_head_id"] == "explicit"
    assert explicit["quality"]["head_type_id"] == "explicit"

    weak_head = _DummyPrinterHead()
    weak = registry.resolve_printer_head(printer_head=weak_head, slot_number=4)
    assert weak["printer_head_id"] == "gripper_slot_4"
    assert weak["quality"]["printer_head_id"] == "inferred"
    assert weak["quality"]["head_type_id"] == "unknown"


def test_identity_registry_assign_helpers_and_legacy_quality_normalization(tmp_path):
    registry = CalibrationIdentityRegistry(str(tmp_path / "CalibrationMemory"))
    registry.ensure_initialized()

    stock = _DummyStockSolution(stock_id="Any_0.00_--", reagent_name="Water")
    registry.assign_reagent_identity(stock, "glycerol_50pct")
    assert stock.reagent_id == "glycerol_50pct"
    assert stock.display_name == "50% Glycerol"

    printer_head = _DummyPrinterHead()
    registry.assign_printer_head_identity(printer_head, "nozzle_120um_h05")
    assert printer_head.printer_head_id == "nozzle_120um_h05"
    assert printer_head.head_type_id == "nozzle_120um"

    legacy = normalize_legacy_context(
        {
            "reagent_id": "water",
            "identity_quality": {
                "reagent_id": "derived",
                "printer_head_id": "missing",
            },
            "nozzle_diameter_um": 100.0,
        }
    )
    assert legacy["identity_quality"]["reagent_id"] == "inferred"
    assert legacy["identity_quality"]["printer_head_id"] == "unknown"
    assert legacy["nominal_nozzle_diameter_um"] == 100.0
