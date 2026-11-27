from functools import partial
from typing import Any

from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QCursor
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QToolTip
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget
lazy import numpy as np
lazy import pyqtgraph as pg

from src.api.ApiBase import ReplyGroup
from src.api.stats_api import GamePlayerStatsApiConnector
from src.util import THEME
from src.util import strtodate

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
PERIODS = (("Last 3 months", 90), ("Last year", 365), ("All time", None))


def parse_game_times(entries: list[dict[str, Any]]) -> np.ndarray:
    times = np.empty((len(entries), 3), dtype=np.int64)
    for row, entry in enumerate(entries):
        local = strtodate(entry["attributes"]["scoreTime"])
        times[row] = (local.toSecsSinceEpoch(), local.date().dayOfWeek() - 1, local.time().hour())
    return times


def count_by_weekday_hour(times: np.ndarray, since: float = 0) -> np.ndarray:
    times = times[times[:, 0] >= since]
    counts = np.zeros((7, 24), dtype=np.int64)
    np.add.at(counts, (times[:, 1], times[:, 2]), 1)
    return counts


class ActivityHeatmap(QWidget):
    def __init__(self, player_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player_id = player_id
        self.api = GamePlayerStatsApiConnector()
        self.replies = ReplyGroup(self)
        self.times = np.empty((0, 3), dtype=np.int64)
        self.counts = np.zeros((7, 24), dtype=np.int64)
        self.total_games: int | None = None
        self.oldest: str | None = None
        self.covered_since = float("inf")
        self.shown_period: tuple[str, int] | None = None
        self.loading = False
        self.error = ""

        self.load_more_button = QPushButton("Load more")
        self.load_more_button.clicked.connect(self.load_more)
        self.period_buttons: list[QPushButton] = []
        for name, days in PERIODS:
            button = QPushButton(name)
            button.clicked.connect(partial(self.show_period, name, days))
            self.period_buttons.append(button)
        self.status = QLabel()
        self.summary = QLabel()

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.load_more_button)
        for button in self.period_buttons:
            buttons_layout.addWidget(button)
        buttons_layout.addStretch()

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(300)
        background = THEME.find_stylesheet_attribute("RatingPlotWidget::custom", "background-color")
        self.plot.setBackground(background or "#202025")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.invertY(True)
        self.plot.getAxis("bottom").setTicks([[(h + 0.5, f"{h:02}") for h in range(24)]])
        self.plot.getAxis("left").setTicks([[(d + 0.5, name) for d, name in enumerate(WEEKDAYS)]])
        self.plot.setRange(xRange=(0, 24), yRange=(0, 7), padding=0)

        self.image = pg.ImageItem(axisOrder="row-major")
        self.image.setColorMap(pg.colormap.get("viridis"))
        self.plot.addItem(self.image)
        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Activity</b> (games by local time)"))
        layout.addLayout(buttons_layout)
        layout.addWidget(self.plot)
        layout.addWidget(self.summary)
        layout.addWidget(self.status)
        self._update_controls()

    @property
    def complete(self) -> bool:
        return self.covered_since <= 0

    def load_more(self) -> None:
        self.shown_period = None
        self._request(None)

    def show_period(self, name: str, days: int | None) -> None:
        since = None if days is None else QDateTime.currentDateTimeUtc().addDays(-days)
        self.shown_period = (name, 0 if since is None else since.toSecsSinceEpoch())
        if self.covered_since <= self.shown_period[1]:
            self.redraw()
        else:
            self._request(since)

    def _request(self, since: QDateTime | None) -> None:
        self.loading = True
        self.error = ""
        self._update_controls()
        handler = partial(self._on_games, since)
        reply = self.api.get_score_times(self.player_id, handler, self.on_error, self.oldest, since)
        self.replies.add(reply)

    def on_error(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.OperationCanceledError:
            self.error = reply.errorString()
        self.loading = False
        self.shown_period = None
        self._update_controls()
        self.redraw()

    def _on_games(self, since: QDateTime | None, message: dict[str, Any]) -> None:
        entries = message["data"]
        self.times = np.concatenate((self.times, parse_game_times(entries)))
        matching = message["meta"]["page"]["totalRecords"]
        if self.total_games is None:
            self.total_games = matching

        if entries:
            self.oldest = entries[-1]["attributes"]["scoreTime"]
        exhausted = len(entries) >= matching
        if exhausted:
            self.covered_since = 0 if since is None else since.toSecsSinceEpoch()
        else:
            self.covered_since = self.times[-1, 0]

        if not exhausted and self.shown_period is not None:
            self._request(since)
        else:
            self.loading = False
        self._update_controls()
        self.redraw()

    def _update_controls(self) -> None:
        self.load_more_button.setEnabled(not self.loading and not self.complete)
        for button in self.period_buttons:
            button.setEnabled(not self.loading)
        total = "?" if self.total_games is None else self.total_games
        games = f"{len(self.times)} of {total} games"
        self.status.setToolTip(self.error)
        if self.error:
            self.status.setText("Failed to load games (hover for details)")
        elif self.loading:
            self.status.setText(f"Loading… {games}")
        else:
            self.status.setText(f"{games} loaded")

    def redraw(self) -> None:
        since = 0 if self.shown_period is None else self.shown_period[1]
        self.counts = count_by_weekday_hour(self.times, since)
        self.image.setImage(self.counts, levels=(0, max(1, self.counts.max())))
        self.image.setRect(0, 0, 24, 7)
        self.summary.setText(self._summary_text())

    def _range_text(self) -> str:
        if self.shown_period is not None:
            return self.shown_period[0]
        if self.complete:
            return "All time"
        if len(self.times) == 0:
            return ""
        oldest = QDateTime.fromSecsSinceEpoch(int(self.times[-1, 0])).toString("dd MMM yyyy")
        return f"Most recent {len(self.times)} games (since {oldest})"

    def _summary_text(self) -> str:
        games = int(self.counts.sum())
        if games == 0:
            return "" if self.loading else "No games in this period"
        weekday, hour = np.unravel_index(self.counts.argmax(), self.counts.shape)
        busiest_day = WEEKDAYS[self.counts.sum(axis=1).argmax()]
        busiest_hour = self.counts.sum(axis=0).argmax()
        return (
            f"{self._range_text()}: {games} games<br>"
            f"Busiest slot: <b>{WEEKDAYS[weekday]} {hour:02}:00</b> "
            f"({self.counts[weekday, hour]} games)<br>"
            f"Busiest day: <b>{busiest_day}</b>, "
            f"busiest hour: <b>{busiest_hour:02}:00–{(busiest_hour + 1) % 24:02}:00</b>"
        )

    def on_mouse_moved(self, pos: QPointF) -> None:
        point = self.plot.getPlotItem().getViewBox().mapSceneToView(pos)
        hour, weekday = int(point.x()), int(point.y())
        if not (0 <= point.x() < 24 and 0 <= point.y() < 7):
            QToolTip.hideText()
            return
        games = self.counts[weekday, hour]
        text = f"{WEEKDAYS[weekday]} {hour:02}:00–{(hour + 1) % 24:02}:00: {games} games"
        QToolTip.showText(QCursor.pos(), text, self.plot)
