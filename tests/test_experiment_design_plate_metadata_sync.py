from types import SimpleNamespace

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

from View import ExperimentDesignDialog


class _ExperimentModelStub:
    def __init__(self):
        self.metadata = {}

    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)


def test_update_metadata_syncs_plate_dimensions_with_selected_plate(qapp):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _ExperimentModelStub()

    dialog.exp_name_edit = QLineEdit()
    dialog.exp_name_edit.setText("plate-meta-test")
    dialog.rep_spin = QSpinBox()
    dialog.rep_spin.setValue(1)
    dialog.v_spin = QDoubleSpinBox()
    dialog.v_spin.setValue(500.0)
    dialog.fill_name_edit = QLineEdit()
    dialog.fill_name_edit.setText("Water")
    dialog.fill_dv_spin = QDoubleSpinBox()
    dialog.fill_dv_spin.setValue(10.0)
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.final_v_spin.setValue(500.0)
    dialog.allow_two_chk = QCheckBox()
    dialog.allow_two_chk.setChecked(True)
    dialog.randomize_chk = QCheckBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.subset_chk = QCheckBox()
    dialog.reduction_spin = QSpinBox()
    dialog.start_col_spin = QSpinBox()
    dialog.start_row_spin = QSpinBox()

    dialog.plate_format_combo = QComboBox()
    dialog.plate_format_combo.addItems(["96well-8x12", "50well-5x10"])
    dialog.plate_format_combo.setCurrentText("96well-8x12")

    plate_defs = {
        "96well-8x12": {"rows": 8, "columns": 12},
        "50well-5x10": {"rows": 5, "columns": 10},
    }
    dialog.main_window = SimpleNamespace(
        model=SimpleNamespace(
            well_plate=SimpleNamespace(
                get_plate_data_by_name=lambda name: plate_defs[name],
            )
        )
    )

    ExperimentDesignDialog._update_metadata_from_controls(dialog)
    assert dialog.model.metadata["allow_two_stock_solutions"] is True
    assert dialog.model.metadata["plate_name"] == "96well-8x12"
    assert dialog.model.metadata["plate_rows"] == 8
    assert dialog.model.metadata["plate_columns"] == 12

    dialog.plate_format_combo.setCurrentText("50well-5x10")
    ExperimentDesignDialog._update_metadata_from_controls(dialog)
    assert dialog.model.metadata["plate_name"] == "50well-5x10"
    assert dialog.model.metadata["plate_rows"] == 5
    assert dialog.model.metadata["plate_columns"] == 10
