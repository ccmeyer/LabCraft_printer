from types import SimpleNamespace

from View import WellPlateWidget


class _GridLayoutSpy:
    def __init__(self):
        self._items = []

    def setSpacing(self, _):
        return

    def addWidget(self, widget, row, col):
        self._items.append((widget, row, col))

    def count(self):
        return 0

    def takeAt(self, _):
        return None


def test_update_grid_places_row_and_column_headers(qapp):
    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.grid_layout = _GridLayoutSpy()
    widget.clear_grid = lambda: None
    widget.model = SimpleNamespace(
        well_plate=SimpleNamespace(
            get_plate_dimensions=lambda: (2, 3),
            iter_rows=lambda: iter(["A", "B"]),
        )
    )

    WellPlateWidget.update_grid(widget)

    # 3 column headers at row 0, col 1..3
    col_headers = [(w.text(), r, c) for (w, r, c) in widget.grid_layout._items if r == 0 and c >= 1]
    assert set(col_headers) >= {("1", 0, 1), ("2", 0, 2), ("3", 0, 3)}

    # 2 row headers at col 0, row 1..2
    row_headers = [(w.text(), r, c) for (w, r, c) in widget.grid_layout._items if c == 0 and r >= 1]
    assert set(row_headers) >= {("A", 1, 0), ("B", 2, 0)}
