import pytest
from PySide6 import QtCharts, QtCore

from utilities import (
    apply_pressure_plot_style,
    pressure_series_pen,
    resolve_pressure_plot_style,
)


def test_pressure_plot_tokens_resolve_palette_and_thin_channel_pens():
    style = resolve_pressure_plot_style(
        {
            "light_blue": "#123456",
            "white": "#fefefe",
            "light_gray": "#abcdef",
            "mid_gray": "#654321",
        }
    )

    assert style.print_color.name() == "#123456"
    assert style.refuel_color.name() == "#fefefe"
    assert style.print_color.alphaF() == pytest.approx(1.0)
    assert style.refuel_color.alphaF() == pytest.approx(1.0)
    assert style.grid_color.alpha() == 64
    measured_print = pressure_series_pen(style, "print")
    target_print = pressure_series_pen(style, "print", target=True)
    measured_refuel = pressure_series_pen(style, "refuel")
    assert measured_print.widthF() == pytest.approx(1.25)
    assert target_print.widthF() == pytest.approx(1.25)
    assert measured_print.style() == QtCore.Qt.PenStyle.SolidLine
    assert target_print.style() == QtCore.Qt.PenStyle.DashLine
    assert measured_print.color() == target_print.color()
    assert measured_refuel.color().name() == "#fefefe"


def test_pressure_plot_tokens_use_app_palette_fallbacks():
    style = resolve_pressure_plot_style(
        {"light_blue": "invalid", "white": "invalid"}
    )

    assert style.print_color.name() == "#275fb8"
    assert style.refuel_color.name() == "#ffffff"


def test_apply_pressure_plot_style_hides_only_target_legend_entries(qapp):
    chart = QtCharts.QChart()
    axes = (QtCharts.QValueAxis(), QtCharts.QValueAxis())
    chart.addAxis(axes[0], QtCore.Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(axes[1], QtCore.Qt.AlignmentFlag.AlignLeft)
    series = [QtCharts.QLineSeries() for _ in range(4)]
    for item in series:
        chart.addSeries(item)
        item.attachAxis(axes[0])
        item.attachAxis(axes[1])

    apply_pressure_plot_style(
        chart,
        axes,
        colors={},
        print_series=series[0],
        refuel_series=series[1],
        target_print_series=series[2],
        target_refuel_series=series[3],
    )

    assert chart.animationOptions() == QtCharts.QChart.AnimationOption.NoAnimation
    assert chart.legend().isVisible()
    assert chart.legend().alignment() == QtCore.Qt.AlignmentFlag.AlignBottom
    assert chart.legend().font().pointSize() == 8
    assert chart.property("pressureLegendEntries") == ["Print", "Refuel"]
    view = QtCharts.QChartView(chart)
    view.show()
    qapp.processEvents()
    assert {
        marker.label(): marker.isVisible()
        for marker in chart.legend().markers()
    } == {
        "Print": True,
        "Refuel": True,
        "Print target": False,
        "Refuel target": False,
    }
    view.close()
    assert axes[0].gridLinePen().color().alpha() == 64
