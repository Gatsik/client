from collections.abc import Iterable
from typing import TypedDict
from typing import Unpack

lazy import pyqtgraph as pg


class BarGraphOptions(TypedDict):
    x: Iterable[float]
    height: Iterable[float]
    width: float
    brush: str | tuple[int, int, int]
    name: str


class LabeledBarGraphItem:
    def __init__(self, categories: list[str], **opts: Unpack[BarGraphOptions]) -> None:
        self.item = pg.BarGraphItem(**opts)
        self.item.hoverEvent = self.hoverEvent
        self.categories = categories
        self.tooltip: pg.TextItem | None = None

    def hoverEvent(self, ev: pg.GraphicsScene.mouseEvents.HoverEvent) -> None:
        if ev.isExit():
            self.hide_tooltip()
        else:
            pos = ev.pos()
            for i, height in enumerate(self.item.opts["height"]):
                x = self.item.opts["x"][i]
                w = self.item.opts["width"]

                if x - w/2 <= pos.x() <= x + w/2:
                    self.show_tooltip(f"{self.categories[i]}: {height:,.2f}", pos)
                    break

    def show_tooltip(self, text: str, pos: pg.Point) -> None:
        if (view := self.item.getViewBox()) is None:
            return

        if self.tooltip is None:
            self.tooltip = pg.TextItem(
                anchor=(0.5, 1.0),
                border=pg.mkPen((255, 255, 255, 100)),
                fill=pg.mkBrush((0, 0, 0, 200)),
            )
            self.tooltip.setZValue(1000)
            parent = view.parentItem()
            assert parent is not None
            parent.addItem(self.tooltip)
            self.tooltip.hide()

        self.tooltip.setPos(pos)
        self.tooltip.setText(text)
        self.tooltip.show()

    def hide_tooltip(self) -> None:
        if self.tooltip is not None:
            self.tooltip.hide()
