from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from PySide6 import QtCharts, QtCore, QtGui


@dataclass(frozen=True)
class PressurePlotStyle:
    """Resolved, shared visual tokens for pressure plots."""

    print_color: QtGui.QColor
    refuel_color: QtGui.QColor
    axis_text_color: QtGui.QColor
    axis_line_color: QtGui.QColor
    grid_color: QtGui.QColor
    line_width: float = 1.25
    axis_line_width: float = 1.0
    legend_point_size: int = 8


def _resolved_color(
    colors: Mapping[str, str],
    key: str,
    fallback: str,
    *,
    alpha: int = 255,
) -> QtGui.QColor:
    color = QtGui.QColor(str(colors.get(key) or fallback))
    if not color.isValid():
        color = QtGui.QColor(fallback)
    color.setAlpha(int(alpha))
    return color


def resolve_pressure_plot_style(
    colors: Mapping[str, str] | None,
) -> PressurePlotStyle:
    palette = dict(colors or {})
    return PressurePlotStyle(
        print_color=_resolved_color(palette, "light_blue", "#275fb8"),
        refuel_color=_resolved_color(palette, "white", "#ffffff"),
        axis_text_color=_resolved_color(palette, "light_gray", "#c4c4c4"),
        axis_line_color=_resolved_color(palette, "mid_gray", "#6e6e6e"),
        grid_color=_resolved_color(
            palette,
            "light_gray",
            "#c4c4c4",
            alpha=64,
        ),
    )


def pressure_series_pen(
    style: PressurePlotStyle,
    channel: str,
    *,
    target: bool = False,
) -> QtGui.QPen:
    color = style.refuel_color if str(channel).lower() == "refuel" else style.print_color
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(float(style.line_width))
    pen.setStyle(
        QtCore.Qt.PenStyle.DashLine
        if target
        else QtCore.Qt.PenStyle.SolidLine
    )
    return pen


def apply_pressure_plot_style(
    chart: QtCharts.QChart,
    axes: Iterable[QtCharts.QAbstractAxis],
    *,
    colors: Mapping[str, str] | None,
    print_series: QtCharts.QLineSeries,
    refuel_series: QtCharts.QLineSeries | None,
    target_print_series: QtCharts.QLineSeries,
    target_refuel_series: QtCharts.QLineSeries | None,
) -> PressurePlotStyle:
    """Apply identical channel, target, legend, and axis styling to a chart."""

    style = resolve_pressure_plot_style(colors)
    series_specs = (
        (print_series, "Print", "print", False),
        (refuel_series, "Refuel", "refuel", False),
        (target_print_series, "Print target", "print", True),
        (target_refuel_series, "Refuel target", "refuel", True),
    )
    for series, name, channel, target in series_specs:
        if series is None:
            continue
        series.setName(name)
        series.setPen(pressure_series_pen(style, channel, target=target))

    axis_line_pen = QtGui.QPen(QtGui.QColor(style.axis_line_color))
    axis_line_pen.setWidthF(float(style.axis_line_width))
    grid_pen = QtGui.QPen(QtGui.QColor(style.grid_color))
    grid_pen.setWidthF(float(style.axis_line_width))
    for axis in axes:
        axis.setLabelsColor(QtGui.QColor(style.axis_text_color))
        axis.setTitleBrush(QtGui.QBrush(QtGui.QColor(style.axis_text_color)))
        axis.setLinePen(axis_line_pen)
        axis.setGridLinePen(grid_pen)

    chart.setAnimationOptions(QtCharts.QChart.AnimationOption.NoAnimation)
    legend = chart.legend()
    legend.setVisible(True)
    legend.setAlignment(QtCore.Qt.AlignmentFlag.AlignBottom)
    legend_font = legend.font()
    legend_font.setPointSize(int(style.legend_point_size))
    legend.setFont(legend_font)
    legend_entries = []
    for measured_series in (print_series, refuel_series):
        if measured_series is None:
            continue
        legend_entries.append(measured_series.name())
        for marker in legend.markers(measured_series):
            marker.setVisible(True)
    for target_series in (target_print_series, target_refuel_series):
        if target_series is None:
            continue
        for marker in legend.markers(target_series):
            marker.setVisible(False)
    chart.setProperty("pressureLegendEntries", legend_entries)
    return style
