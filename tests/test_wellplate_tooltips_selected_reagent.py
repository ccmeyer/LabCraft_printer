from types import SimpleNamespace

from View import WellPlateWidget


class _Label:
    def __init__(self):
        self.tooltip = ""
        self.style = ""
        self.update_calls = 0

    def setStyleSheet(self, s):
        self.style = s

    def setToolTip(self, t):
        self.tooltip = t

    def update(self):
        self.update_calls += 1


class _BatchingWidget:
    _suspend_well_plate_repaints = WellPlateWidget._suspend_well_plate_repaints
    _resume_well_plate_repaints = WellPlateWidget._resume_well_plate_repaints
    _well_display_context = WellPlateWidget._well_display_context
    _update_well_label = WellPlateWidget._update_well_label
    _incremental_well = WellPlateWidget._incremental_well

    def __init__(self):
        self._updates_enabled = True
        self.update_enabled_calls = []
        self.update_calls = 0

    def updatesEnabled(self):
        return self._updates_enabled

    def setUpdatesEnabled(self, enabled):
        enabled = bool(enabled)
        self.update_enabled_calls.append(enabled)
        self._updates_enabled = enabled

    def update(self):
        self.update_calls += 1


def test_update_well_colors_batches_qt_repaints():
    rxn = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 7,
        check_stock_complete=lambda sid: False,
    )
    well = SimpleNamespace(well_id="A1", row_num=0, col=1, assigned_reaction=rxn)

    widget = _BatchingWidget()
    widget.well_labels = [[_Label()]]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemData=lambda i: "ReagentA_1.00_mM",
    )
    widget.model = SimpleNamespace(
        reaction_collection=SimpleNamespace(is_empty=lambda: False, get_max_droplets=lambda sid: 10),
        stock_solutions=SimpleNamespace(get_stock_by_id=lambda _: SimpleNamespace(units="mM")),
        printer_head_manager=SimpleNamespace(get_printer_head_by_id=lambda _: SimpleNamespace(get_color=lambda: "blue")),
        well_plate=SimpleNamespace(get_all_wells=lambda: [well], get_plate_dimensions=lambda: (16, 24)),
        get_well_stock_final_concentration=lambda wid, sid: 0.1234,
    )

    WellPlateWidget.update_well_colors(widget)

    assert widget.update_enabled_calls == [False, True]
    assert widget.update_calls == 1


def test_update_well_colors_only_touches_named_well():
    complete = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 7,
        check_stock_complete=lambda sid: True,
    )
    incomplete = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 7,
        check_stock_complete=lambda sid: False,
    )
    wells = {
        "A1": SimpleNamespace(
            well_id="A1",
            row_num=0,
            col=1,
            assigned_reaction=complete,
        ),
        "A2": SimpleNamespace(
            well_id="A2",
            row_num=0,
            col=2,
            assigned_reaction=incomplete,
        ),
    }
    widget = _BatchingWidget()
    widget.well_labels = [[_Label(), _Label()]]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemData=lambda i: "ReagentA_1.00_mM",
    )
    widget.model = SimpleNamespace(
        reaction_collection=SimpleNamespace(
            is_empty=lambda: False,
            get_max_droplets=lambda sid: 10,
        ),
        stock_solutions=SimpleNamespace(
            get_stock_by_id=lambda _: SimpleNamespace(units="mM"),
        ),
        printer_head_manager=SimpleNamespace(
            get_printer_head_by_id=lambda _: SimpleNamespace(
                get_color=lambda: "blue"
            )
        ),
        well_plate=SimpleNamespace(
            get_plate_dimensions=lambda: (16, 24),
            get_well=lambda well_id: wells.get(well_id),
            get_all_wells=lambda: (_ for _ in ()).throw(
                AssertionError("incremental update scanned the whole plate")
            ),
        ),
        get_well_stock_final_concentration=lambda wid, sid: 0.1234,
    )

    WellPlateWidget.update_well_colors(widget, "A1")

    assert "border: 1px solid white" in widget.well_labels[0][0].style
    assert widget.well_labels[0][0].update_calls == 1
    assert widget.well_labels[0][1].style == ""
    assert widget.well_labels[0][1].update_calls == 0
    assert widget.update_enabled_calls == []
    assert widget.update_calls == 0


def test_completed_view_uses_detached_display_head_for_complete_well_color():
    reaction = SimpleNamespace(
        get_target_droplets_for_stock=lambda _stock_id: 7,
        check_stock_complete=lambda _stock_id: True,
    )
    well = SimpleNamespace(
        well_id="A1",
        row_num=0,
        col=1,
        assigned_reaction=reaction,
    )
    display_head = SimpleNamespace(
        get_stock_id=lambda: "ReagentA_1.00_mM",
        get_color=lambda: "#224466",
    )
    widget = _BatchingWidget()
    widget.well_labels = [[_Label()]]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemData=lambda _index: "ReagentA_1.00_mM",
    )
    widget.model = SimpleNamespace(
        is_completed_execution_view_active=lambda: True,
        get_completed_execution_display_heads=lambda: (display_head,),
        reaction_collection=SimpleNamespace(
            is_empty=lambda: False,
            get_max_droplets=lambda _stock_id: 7,
        ),
        stock_solutions=SimpleNamespace(
            get_stock_by_id=lambda _stock_id: SimpleNamespace(units="mM"),
        ),
        printer_head_manager=SimpleNamespace(
            get_printer_head_by_id=lambda _stock_id: (_ for _ in ()).throw(
                AssertionError("completed view consulted physical rack heads")
            )
        ),
        well_plate=SimpleNamespace(
            get_plate_dimensions=lambda: (8, 12),
            get_all_wells=lambda: [well],
        ),
        get_well_stock_final_concentration=lambda _well_id, _stock_id: 0.25,
    )

    WellPlateWidget.update_well_colors(widget)

    assert "rgba(34,68,102" in widget.well_labels[0][0].style
    assert "border: 1px solid white" in widget.well_labels[0][0].style


def test_unknown_well_id_falls_back_to_batched_full_refresh():
    rxn = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 7,
        check_stock_complete=lambda sid: False,
    )
    wells = [
        SimpleNamespace(
            well_id=f"A{column}",
            row_num=0,
            col=column,
            assigned_reaction=rxn,
        )
        for column in (1, 2)
    ]
    widget = _BatchingWidget()
    widget.well_labels = [[_Label(), _Label()]]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemData=lambda i: "ReagentA_1.00_mM",
    )
    widget.model = SimpleNamespace(
        reaction_collection=SimpleNamespace(
            is_empty=lambda: False,
            get_max_droplets=lambda sid: 10,
        ),
        stock_solutions=SimpleNamespace(
            get_stock_by_id=lambda _: SimpleNamespace(units="mM"),
        ),
        printer_head_manager=SimpleNamespace(
            get_printer_head_by_id=lambda _: SimpleNamespace(
                get_color=lambda: "blue"
            )
        ),
        well_plate=SimpleNamespace(
            get_plate_dimensions=lambda: (16, 24),
            get_well=lambda _well_id: None,
            get_all_wells=lambda: wells,
        ),
        get_well_stock_final_concentration=lambda wid, sid: 0.1234,
    )

    WellPlateWidget.update_well_colors(widget, "Z99")

    assert all(label.style for label in widget.well_labels[0])
    assert widget.update_enabled_calls == [False, True]
    assert widget.update_calls == 1


def test_update_well_colors_sets_tooltip_with_droplets_and_concentration():
    rxn = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 7,
        check_stock_complete=lambda sid: False,
    )
    well = SimpleNamespace(well_id="A1", row_num=0, col=1, assigned_reaction=rxn)

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.well_labels = [[_Label()]]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemText=lambda i: "ReagentA - 1.00 mM",
        setCurrentIndex=lambda _: None,
        findText=lambda _: 0,
    )
    widget.model = SimpleNamespace(
        reaction_collection=SimpleNamespace(is_empty=lambda: False, get_max_droplets=lambda sid: 10),
        stock_solutions=SimpleNamespace(
            get_stock_id_from_formatted=lambda _: "ReagentA_1.00_mM",
            get_formatted_from_stock_id=lambda _: "ReagentA - 1.00 mM",
            get_stock_solution_names=lambda: ["ReagentA_1.00_mM"],
            get_stock_by_id=lambda _: SimpleNamespace(units="mM"),
        ),
        printer_head_manager=SimpleNamespace(get_printer_head_by_id=lambda _: SimpleNamespace(get_color=lambda: "blue")),
        well_plate=SimpleNamespace(get_all_wells=lambda: [well], get_plate_dimensions=lambda: (16, 24)),
        get_well_stock_final_concentration=lambda wid, sid: 0.1234,
    )

    WellPlateWidget.update_well_colors(widget, "A1")

    tip = widget.well_labels[0][0].tooltip
    assert "Target droplets: 7" in tip
    assert "Final concentration: 0.1234 mM" in tip


def test_update_well_colors_disables_tooltips_for_plates_larger_than_384():
    rxn = SimpleNamespace(
        get_target_droplets_for_stock=lambda sid: 3,
        check_stock_complete=lambda sid: True,
    )
    well = SimpleNamespace(well_id="AA1", row_num=26, col=1, assigned_reaction=rxn)

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.well_labels = [[_Label()] for _ in range(32)]
    widget.reagent_selection = SimpleNamespace(
        currentIndex=lambda: 0,
        itemText=lambda i: "ReagentA - 1.00 mM",
        setCurrentIndex=lambda _: None,
        findText=lambda _: 0,
    )
    widget.model = SimpleNamespace(
        reaction_collection=SimpleNamespace(is_empty=lambda: False, get_max_droplets=lambda sid: 10),
        stock_solutions=SimpleNamespace(
            get_stock_id_from_formatted=lambda _: "ReagentA_1.00_mM",
            get_formatted_from_stock_id=lambda _: "ReagentA - 1.00 mM",
            get_stock_solution_names=lambda: ["ReagentA_1.00_mM"],
            get_stock_by_id=lambda _: SimpleNamespace(units="mM"),
        ),
        printer_head_manager=SimpleNamespace(get_printer_head_by_id=lambda _: SimpleNamespace(get_color=lambda: "blue")),
        well_plate=SimpleNamespace(get_all_wells=lambda: [well], get_plate_dimensions=lambda: (32, 48)),
        get_well_stock_final_concentration=lambda wid, sid: 0.12,
    )

    WellPlateWidget.update_well_colors(widget)

    assert widget.well_labels[26][0].tooltip == ""
