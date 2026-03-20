from types import SimpleNamespace

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QTableWidget

from Model import PrinterHead, StockSolutionManager
from View import RackBox, WellPlateWidget


def _make_stock_manager():
    manager = StockSolutionManager()
    manager.add_stock_solution("ReagentA", 3.465, "mM")
    manager.add_stock_solution("ReagentB", 99.696, "mM")
    return manager


def test_stock_solution_manager_display_names_use_three_significant_figures():
    manager = _make_stock_manager()

    names = manager.get_stock_solution_names_formated()
    reagent_a_id = manager._make_stock_id("ReagentA", 3.465, "mM")
    reagent_b_id = manager._make_stock_id("ReagentB", 99.696, "mM")

    assert "ReagentA - 3.47 mM" in names
    assert "ReagentB - 99.7 mM" in names
    assert manager.get_formatted_from_stock_id(reagent_a_id) == "ReagentA - 3.47 mM"
    assert manager.get_formatted_from_stock_id(reagent_b_id) == "ReagentB - 99.7 mM"
    assert manager.get_stock_id_from_formatted("ReagentA - 3.47 mM") == reagent_a_id
    assert manager.get_stock_id_from_formatted("ReagentB - 99.7 mM") == reagent_b_id


def test_wellplate_widget_populates_and_selects_display_formatted_stock_names(qapp):
    manager = _make_stock_manager()
    reagent_a = manager.get_stock_solution("ReagentA", 3.465, "mM")
    head = PrinterHead(reagent_a, color="#224466")
    reagent_a_id = manager._make_stock_id("ReagentA", 3.465, "mM")
    reagent_b_id = manager._make_stock_id("ReagentB", 99.696, "mM")

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.reagent_selection = QComboBox()
    widget.update_well_colors = lambda *args: None
    widget.model = SimpleNamespace(
        stock_solutions=manager,
        rack_model=SimpleNamespace(gripper_printer_head=head),
    )

    WellPlateWidget.on_experiment_loaded(widget)
    assert widget.reagent_selection.itemText(0) == "ReagentA - 3.47 mM"
    assert widget.reagent_selection.itemText(1) == "ReagentB - 99.7 mM"
    assert widget.reagent_selection.itemData(0) == reagent_a_id
    assert widget.reagent_selection.itemData(1) == reagent_b_id

    widget.reagent_selection.setCurrentIndex(1)
    WellPlateWidget.gripper_update_handler(widget)

    assert widget.reagent_selection.currentText() == "ReagentA - 3.47 mM"
    assert widget.reagent_selection.currentData() == reagent_a_id


def test_rack_box_displays_stock_names_with_three_significant_figures(qapp):
    manager = _make_stock_manager()
    reagent_a = manager.get_stock_solution("ReagentA", 3.465, "mM")
    reagent_b = manager.get_stock_solution("ReagentB", 99.696, "mM")
    slot_head = PrinterHead(reagent_a, color="#224466")
    unassigned_head = PrinterHead(reagent_b, color="#662244")

    combined_button = QPushButton()
    combined_button.clicked.connect(lambda: None)
    slot_label = QLabel()
    volume_label = QLabel()
    swap_dropdown = QComboBox()
    unassigned_table = QTableWidget(0, 1)
    unassigned_table.setColumnCount(1)
    gripper_label = QLabel()
    gripper_volume_label = QLabel()

    slot = SimpleNamespace(
        printer_head=slot_head,
        confirmed=False,
        locked=False,
        is_locked=lambda: False,
        number=0,
    )

    box = RackBox.__new__(RackBox)
    box.color_dict = {
        "dark_blue": "#1b3a57",
        "dark_red": "#8a0303",
        "dark_gray": "#444444",
        "darker_gray": "#222222",
        "light_gray": "#cccccc",
        "white": "#ffffff",
    }
    box.model = SimpleNamespace(
        well_plate=SimpleNamespace(get_all_wells=lambda: []),
        printer_head_manager=SimpleNamespace(get_unassigned_printer_heads=lambda: [unassigned_head]),
    )
    box.rack_model = SimpleNamespace(
        slots=[slot],
        gripper_printer_head=slot_head,
        get_all_slots=lambda: [slot],
    )
    box.slot_widgets = [(slot_label, volume_label, combined_button, swap_dropdown)]
    box.gripper_label = gripper_label
    box.gripper_volume_label = gripper_volume_label
    box.unassigned_table = unassigned_table
    box.create_combined_button_callback = lambda _slot_number: (lambda: None)

    RackBox.update_slot(box, 0)
    RackBox.update_gripper(box)
    RackBox.update_unassigned_printer_heads(box)

    assert slot_label.text() == "ReagentA\n3.47 mM"
    assert gripper_label.text() == "ReagentA\n3.47 mM"
    assert swap_dropdown.itemText(1) == "ReagentB - 99.7 mM"
    assert unassigned_table.item(0, 0).text() == "ReagentB - 99.7 mM"
