from bisect import bisect_left
from typing import Any

from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import QPointF
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox
lazy import numpy as np
lazy import pyqtgraph as pg

from src.util import THEME


class Crosshairs:
    COLOR = THEME.find_stylesheet_attribute(
        "RatingPlotCrosshairs::custom",
        "line-color",
    )
    TEXT_COLOR = THEME.find_stylesheet_attribute(
        "RatingPlotCrosshairs::custom",
        "text-color",
    )
    BACKGROUND_COLOR = THEME.find_stylesheet_attribute(
        "RatingPlotCrosshairs::custom",
        "background-color",
    )

    def __init__(
        self,
        plotwidget: pg.PlotWidget,
        series: LineSeries,
        visibility_box: QCheckBox,
    ) -> None:
        self.plotwidget = plotwidget
        self.plotwidget.scene().sigMouseMoved.connect(self.update_lines_and_text)

        self.series = series

        pen = pg.mkPen(self.COLOR, width=1, style=Qt.PenStyle.DashLine)
        self.xLine = pg.InfiniteLine(angle=90, pen=pen)
        self.yLine = pg.InfiniteLine(angle=0, pen=pen)

        self.plotwidget.addItem(self.xLine, ignoreBounds=True)
        self.plotwidget.addItem(self.yLine, ignoreBounds=True)

        self.xText = pg.TextItem(color=self.TEXT_COLOR)
        self.yText = pg.TextItem(color=self.TEXT_COLOR)

        self.plotwidget.scene().addItem(self.xText)
        self.plotwidget.scene().addItem(self.yText)

        self.plotwidget.plotItem.getAxis("left").setWidth(40)

        self.visibility_box = visibility_box
        self.set_visible(self.visibility_box.isChecked())
        self.visibility_box.toggled.connect(self.change_visibility)

    def set_series(self, series: LineSeries) -> None:
        self.series = series

    def set_visible(self, visible: bool) -> None:
        self.xLine.setVisible(visible)
        self.yLine.setVisible(visible)
        self.xText.setVisible(visible)
        self.yText.setVisible(visible)

    def display(self, *, seen: bool) -> None:
        if not self.visibility_box.isChecked():
            return
        self.set_visible(seen)

    def hide(self) -> None:
        self.set_visible(False)

    def show(self) -> None:
        self.set_visible(True)

    def change_visibility(self, visible: bool) -> None:
        self.set_visible(visible)

    def toggle_visibility(self) -> None:
        self.visibility_box.toggle()

    def _closest_index(self, lst: np.typing.NDArray[np.float64], value: float) -> int:
        pos = bisect_left(lst, value)
        if pos == 0:
            return pos
        if pos == len(lst):
            return pos - 1

        before = lst[pos - 1]
        after = lst[pos]
        if after - value < value - before:
            return pos
        else:
            return pos - 1

    def map_to_data(self, pos: QPointF) -> QPointF:
        view = self.plotwidget.plotItem.getViewBox()
        value_pos = view.mapSceneToView(pos)
        point_index = self._closest_index(self.series.x(), value_pos.x())
        return self.series.point_at(point_index)

    def get_xtext_pos(self, scene_point: QPointF) -> tuple[float, float]:
        scene_width = self.plotwidget.sceneBoundingRect().width()
        text_width = self.xText.boundingRect().width()
        text_height = self.xText.boundingRect().height()
        padding = 3

        left_margin = self.plotwidget.plotItem.getAxis("left").width() - padding
        right_margin = scene_width - text_width + padding

        x = max(left_margin, scene_point.x() - text_width / 2)
        x = min(x, right_margin)
        y = self.plotwidget.sceneBoundingRect().bottom() - text_height + padding
        return x, y

    def get_ytext_pos(self, scene_point: QPointF) -> tuple[float, float]:
        padding = 3
        x = self.plotwidget.sceneBoundingRect().left() - padding
        y = scene_point.y() - self.yText.boundingRect().height() / 2
        return x, y

    def update_lines_and_text(self, pos: QPointF) -> None:
        if len(self.series.x()) == 0:
            return

        data_point = self.map_to_data(pos)
        view = self.plotwidget.plotItem.getViewBox()
        scene_point = view.mapViewToScene(data_point)

        left_margin = self.plotwidget.plotItem.getAxis("left").width()
        if scene_point.x() < left_margin or scene_point.y() < 0:
            return

        self.update_lines(pos, data_point)
        self.update_text(scene_point, data_point)
        self.show_at_pos(scene_point)

    def update_text(self, scene_point: QPointF, data_point: QPointF) -> None:
        date = QDateTime.fromSecsSinceEpoch(round(data_point.x())).toString("dd-MM-yyyy hh:mm")
        self.xText.setHtml(f"<div style='background-color: {self.BACKGROUND_COLOR};'>{date}</div>")
        self.xText.setPos(*self.get_xtext_pos(scene_point))
        self.yText.setHtml(
            f"<div style='background-color: {self.BACKGROUND_COLOR};'>{data_point.y():.2f}</div>",
        )
        self.yText.setPos(*self.get_ytext_pos(scene_point))

    def update_lines(self, pos: QPointF, data_point: QPointF) -> None:
        if self.plotwidget.sceneBoundingRect().contains(pos):
            self.xLine.setPos(data_point.x())
            self.yLine.setPos(data_point.y())

    def show_at_pos(self, pos: QPointF) -> None:
        seen = self.plotwidget.sceneBoundingRect().contains(pos)
        self.display(seen=seen)


class LineSeries:
    def __init__(self, size: int = 0) -> None:
        self._x: np.typing.NDArray[np.float64] = np.zeros(size)
        self._y: np.typing.NDArray[np.float64] = np.zeros(size)

    def x(self) -> np.typing.NDArray[np.float64]:
        return self._x

    def y(self) -> np.typing.NDArray[np.float64]:
        return self._y

    def set_point(self, index: int, point: QPointF) -> None:
        self._x[index] = point.x()
        self._y[index] = point.y()

    def extend(self, series: LineSeries) -> None:
        self._x = np.append(self._x, series.x())
        self._y = np.append(self._y, series.y())

    def prextend(self, series: LineSeries) -> None:
        self._x = np.append(series.x(), self._x)
        self._y = np.append(series.y(), self._y)

    def point_at(self, index: int) -> QPointF:
        return QPointF(self._x[index], self._y[index])


class MaxRatingLabel:
    def __init__(self, line: pg.InfiniteLine, **opts: Any) -> None:
        self.label = pg.InfLineLabel(line, **opts)

    def setRating(self, rating: float, iso_date: str) -> None:
        date = QDateTime.fromString(iso_date, Qt.DateFormat.ISODate).toString("dd-MM-yyyy")
        self.label.setText(f"{rating:g}\n({date})")


class PlotController:
    MAX_RATING_COLOR = THEME.find_stylesheet_attribute(
        "RatingPlotWidget::custom",
        "max-rating-color",
        fallback="c",
    )

    def __init__(
        self,
        widget: pg.PlotWidget,
        crosshair_box: QCheckBox,
        max_rating_box: QCheckBox,
    ) -> None:
        self.widget = widget
        background = THEME.find_stylesheet_attribute(
            "RatingPlotWidget::custom",
            "background-color",
        )
        self.widget.setBackground(background)
        self.widget.setAxisItems({"bottom": pg.DateAxisItem()})
        self.series = LineSeries()
        self.crosshairs = Crosshairs(self.widget, self.series, crosshair_box)

        self.max_rating_box = max_rating_box
        self.max_rating_box.toggled.connect(self.change_max_rating_visibility)

        self.hide_scene_actions()
        self.hide_irrelevant_plot_actions()
        self.add_custom_menu_actions()
        pen_color = THEME.find_stylesheet_attribute(
            "RatingPlotWidget::custom",
            "color",
        )
        self.plot_item: pg.PlotDataItem = self.widget.plot(pen=pg.mkPen(pen_color))

        self.max_rating_line = self.widget.addLine(
            y=0,
            angle=0,
            pen=pg.mkPen(self.MAX_RATING_COLOR, style=Qt.PenStyle.DashLine),
        )
        self.max_rating_line.hide()
        self.max_rating_label = MaxRatingLabel(
            self.max_rating_line,
            **{"position": 0.1, "movable": True},
        )

    def clear(self) -> None:
        self.widget.clear()

    def update(self) -> None:
        self.plot_item.setData(self.series.x(), self.series.y())
        self.widget.autoRange()

    def add_data(self, series: LineSeries) -> None:
        self.series.extend(series)

    def prepend_data(self, series: LineSeries) -> None:
        self.series.prextend(series)

    def set_max_rating(self, rating: float, iso_date: str) -> None:
        self.max_rating_line.setVisible(self.max_rating_box.isChecked())
        self.max_rating_line.setValue(rating)
        self.max_rating_label.setRating(rating, iso_date)
        self.widget.autoRange()

    def hide_scene_actions(self) -> None:
        # hide the 'Export...' action
        scene_menu = self.widget.scene().contextMenu
        for action in scene_menu:
            action.setVisible(False)

    def hide_irrelevant_plot_actions(self) -> None:
        for action in ("Transforms", "Downsample", "Average", "Alpha", "Points"):
            self.widget.plotItem.setContextMenuActionVisible(action, visible=False)

    def add_custom_menu_actions(self) -> None:
        viewbox = self.widget.plotItem.getViewBox()
        if viewbox is None:
            return

        menu = viewbox.getMenu(ev=None)
        if menu is None:
            return

        menu.addAction("Show/Hide crosshair", self.crosshairs.toggle_visibility)
        menu.addAction("Show/Hide max rating", self.toggle_max_rating_visibility)

    def toggle_max_rating_visibility(self) -> None:
        self.max_rating_box.toggle()

    def change_max_rating_visibility(self, visible: bool) -> None:
        self.max_rating_line.setVisible(visible)
        self.widget.autoRange()
