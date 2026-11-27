from typing import NamedTuple

lazy import pyqtgraph as pg

from src.util import THEME

SECTION = "StatsPlot::custom"


class PlotColors(NamedTuple):
    background: str
    text: str
    axis: str
    palette: tuple[str, ...]

    @classmethod
    def from_theme(cls) -> PlotColors:
        palette = THEME.find_stylesheet_attribute(
            SECTION,
            "palette",
            fallback="#4C9AFF #F2685F #3DD68C #F5B841 #A78BFA #2EC4D6",
        )
        return cls(
            background=THEME.find_stylesheet_attribute(SECTION, "background-color", "#202025"),
            text=THEME.find_stylesheet_attribute(SECTION, "text-color", "#C9CDD4"),
            axis=THEME.find_stylesheet_attribute(SECTION, "axis-color", "#4A4D55"),
            palette=tuple(palette.split()),
        )


def apply_colors(plot: pg.PlotWidget) -> None:
    colors = PlotColors.from_theme()
    plot.setBackground(colors.background)
    item = plot.getPlotItem()
    if title := item.titleLabel.text:
        item.setTitle(title, color=colors.text)
    for name in ("left", "bottom"):
        axis = item.getAxis(name)
        axis.setPen(pg.mkPen(colors.axis))
        axis.setTextPen(pg.mkPen(colors.text))
    if item.legend is not None:
        item.legend.setLabelTextColor(colors.text)
        for _, label in item.legend.items:
            label.setText(label.text)
