from types import SimpleNamespace
from unittest.mock import Mock

from View import MainWindow


def test_complete_experiment_design_calls_model_load_from_model():
    main_window = MainWindow.__new__(MainWindow)
    load_mock = Mock()
    main_window.model = SimpleNamespace(
        load_experiment_from_model=load_mock,
        experiment_model=SimpleNamespace(metadata={"plate_name": "96well-8x12"}),
    )

    MainWindow.complete_experiment_design(main_window)

    load_mock.assert_called_once_with(plate_name="96well-8x12")
