import pytest


def test_get_available_wells_validates_start_row_bounds(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    with pytest.raises(ValueError, match="start_row"):
        wp.get_available_wells(start_row=wp.get_num_rows())


def test_get_available_wells_validates_start_col_bounds(experiment_model_factory):
    model = experiment_model_factory()
    wp = model.well_plate

    with pytest.raises(ValueError, match="start_col"):
        wp.get_available_wells(start_col=wp.get_num_cols())
