from types import SimpleNamespace

from View import WellPlateWidget


class _Label:
    def __init__(self):
        self.tooltip = ""
        self.style = ""

    def setStyleSheet(self, s):
        self.style = s

    def setToolTip(self, t):
        self.tooltip = t


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
        well_plate=SimpleNamespace(get_all_wells=lambda: [well]),
        get_well_stock_final_concentration=lambda wid, sid: 0.1234,
    )

    WellPlateWidget.update_well_colors(widget, "A1")

    tip = widget.well_labels[0][0].tooltip
    assert "Target droplets: 7" in tip
    assert "Final concentration: 0.1234 mM" in tip
