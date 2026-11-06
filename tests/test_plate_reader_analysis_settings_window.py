from PySide6 import QtWidgets

from PlateReaderAnalysisSettingsDialog import PlateReaderAnalysisSettingsDialog
from tests.test_plate_reader_analysis_window import _make_window, _validate_window_preview
from tests.test_plate_reader_analysis_settings import reviewed_settings
from tools.data_analysis.analysis_settings import SETTINGS_FILENAME, save_settings


def test_settings_dialog_expands_ranges_and_requires_a_reason(qapp):
    dialog = PlateReaderAnalysisSettingsDialog(reviewed_settings())
    dialog.exclusions_table.item(0, 0).setText("N1:P4")
    assert len(dialog.collect_settings()["excluded_wells"]) == 12
    dialog.exclusions_table.item(0, 1).setText("")
    dialog._apply()
    assert dialog.result() != QtWidgets.QDialog.Accepted
    assert "reason" in dialog.error_label.text()
    dialog.close()


def test_settings_dialog_reports_conflicting_reasons_and_allows_exact_mode(qapp):
    dialog = PlateReaderAnalysisSettingsDialog(reviewed_settings())
    dialog._add_rule("N1", "different reason")
    dialog._apply()
    assert "Conflicting" in dialog.error_label.text()
    dialog.exclusions_table.removeRow(1)
    dialog.group_targets.setChecked(False)
    assert dialog.collect_settings()["nominal_targets"] == {}
    assert not dialog.targets_table.isEnabled()
    dialog.close()


def test_window_reloads_saved_choices_and_settings_edits_invalidate_preview(tmp_path, qapp, monkeypatch):
    window, controller, experiment, *_ = _make_window(tmp_path, qapp)
    settings = reviewed_settings()
    save_settings(experiment / SETTINGS_FILENAME, settings)
    window._on_experiment_dir_changed(str(experiment))
    assert window._build_config().analysis_settings == settings
    assert "1 manually excluded" in window.settings_summary.text()
    _validate_window_preview(window, controller, experiment, qapp)
    assert window.run_button.isEnabled()
    old_signature = window._preview_signature
    updated = {**settings, "excluded_wells": {"N1": "missing", "N2": "missing"}}
    class AppliedDialog:
        def __init__(self, *_args, **_kwargs):
            self.settings = updated
        def exec(self):
            return QtWidgets.QDialog.Accepted
    monkeypatch.setattr("PlateReaderAnalysisSettingsDialog.PlateReaderAnalysisSettingsDialog", AppliedDialog)
    window._edit_analysis_settings()
    assert not window.run_button.isEnabled()
    assert window._config_signature(window._build_config()) != old_signature
    assert window._build_config().analysis_settings == updated
    assert "2 manually excluded" in window.settings_summary.text()
    window.close()


def test_window_does_not_ignore_invalid_saved_settings(tmp_path, qapp):
    window, controller, experiment, *_ = _make_window(tmp_path, qapp)
    (experiment / SETTINGS_FILENAME).write_text('{"schema_version":"future"}')
    window._on_experiment_dir_changed(str(experiment))
    window._on_validate_preview_clicked()
    assert "Invalid analysis settings" == window.status_label.text()
    assert "Unsupported" in window.preview_messages.toPlainText()
    assert controller.started_preview_config is None
    window.close()
