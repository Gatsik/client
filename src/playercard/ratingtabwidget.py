from typing import Any

from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import QObject
from PyQt6.QtCore import QPointF
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QThread
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QSpinBox
from PyQt6.QtWidgets import QTabWidget
lazy import pyqtgraph as pg

from src.api.models.LeaderboardRating import LeaderboardRating
from src.api.stats_api import LeaderboardRatingJournalApiConnector
from src.config import Settings
from src.model.rating import Rating
from src.playercard.plot import LineSeries
from src.playercard.plot import PlotController


class LineSeriesParser(QThread):
    result_ready = pyqtSignal(LineSeries)

    def __init__(self, unparsed_api_response: dict) -> None:
        QThread.__init__(self)
        self.data = unparsed_api_response

    def run(self) -> None:
        self.parse()

    def parse(self) -> None:
        journal = self.data["data"]
        journal_leng = len(journal)

        if journal_leng == 0:
            self.result_ready.emit(LineSeries())
            return

        stats = self.data["included"]
        stats_leng = len(stats)

        series = LineSeries(stats_leng)

        stats_index = journal_index = 0
        while stats_index < stats_leng and journal_index < journal_leng:
            if (
                stats[stats_index]["id"]
                != journal[journal_index]["relationships"]["gamePlayerStats"]["data"]["id"]
            ):
                journal_index += 1
                continue

            score_time_str = stats[stats_index]["attributes"]["scoreTime"]
            score_time = QDateTime.fromString(score_time_str, Qt.DateFormat.ISODate)
            # not creating additional objects (like Rating and QPointF)
            # and not accessing their attributes in a loop will also give small
            # improvement, but not quite noticeable (a few hundreds of a second
            # per 10000 loop cycles -- ~10x less than API call deviation)
            rating = Rating(
                journal[journal_index]["attributes"]["meanAfter"],
                journal[journal_index]["attributes"]["deviationAfter"],
            )
            point = QPointF(
                score_time.toSecsSinceEpoch(),
                rating.displayed(),
            )
            series.set_point(stats_leng - stats_index - 1, point)
            stats_index += 1
            journal_index += 1

        self.result_ready.emit(series)


class RatingsPlotTab(QObject):
    name_changed = pyqtSignal(int, str)
    api_error = pyqtSignal(str)

    def __init__(
            self,
            index: int,
            player_id: str,
            rating: LeaderboardRating,
            plot: PlotController,
            default_pages_box: QSpinBox,
    ) -> None:
        super().__init__()
        self.index = index
        self.player_id = player_id
        self.rating = rating
        assert rating.leaderboard is not None
        self.leaderboard = rating.leaderboard
        self.ratings_history_api = LeaderboardRatingJournalApiConnector(
            player_id,
            self.leaderboard.technical_name,
        )
        self.ratings_history_api.ratings_ready.connect(self.process_rating_history)
        self.ratings_history_api.max_ready.connect(self.process_max_rating)
        self.ratings_history_api.api_error.connect(self.on_rating_api_error)
        self.plot = plot
        self.workers: list[LineSeriesParser] = []
        self._current_page = 0
        self._total_pages = 1
        self._running = False

        self.default_pages_box = default_pages_box
        self.default_pages_box.valueChanged.connect(self.on_default_pages_changed)
        self._default_pages = default_pages_box.value()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        self.ratings_history_api.abort()
        try:
            self.clear_threads()
        except RuntimeError:
            pass

    def on_default_pages_changed(self, new_default: int) -> None:
        if self._current_page == 0:
            self._default_pages = new_default

    def enter(self) -> None:
        if self._current_page == 0:
            self.load_ratings()
            self.ratings_history_api.get_max_rating()

    @property
    def _loaded(self) -> bool:
        return self._current_page >= self._default_pages

    def load_next_rating_page(self) -> None:
        if self._current_page >= self._total_pages:
            return
        if self._loaded:
            self._default_pages = self._current_page + 1
        self.load_ratings()

    def load_more_ratings(self) -> None:
        if self._loaded:
            self._default_pages = self._total_pages
        self.load_ratings()

    def load_ratings(self) -> None:
        if self._running or self._loaded:
            return
        self.name_changed.emit(self.index, "Loading...")
        self.ratings_history_api.get_history_page(self._current_page + 1)
        self._running = True

    def clear_threads(self) -> None:
        for worker in self.workers:
            if worker.isRunning():
                worker.quit()
        self.workers.clear()

    def finish(self) -> None:
        self._running = False
        self.clear_threads()
        name = self.leaderboard.pretty_name
        if self._current_page < self._total_pages:
            name += f" ({self._current_page}/{self._total_pages})"
        self.name_changed.emit(self.index, name)

    def process_rating_history(self, message: dict[str, Any]) -> None:
        meta = message["meta"]
        self._total_pages = meta["page"]["totalPages"]
        self._current_page = meta["page"]["number"]
        if self._total_pages < self._default_pages:
            self._default_pages = self._total_pages
        self.name_changed.emit(self.index, f"Loading... ({self._current_page}/{self._total_pages})")

        worker = LineSeriesParser(message)
        self.workers.append(worker)
        worker.result_ready.connect(self.data_parsed)
        worker.start()

        if not self._loaded:
            self.ratings_history_api.get_history_page(self._current_page + 1)

    def on_rating_api_error(self, message: str) -> None:
        self._running = False
        self.finish()
        self.api_error.emit(message)

    def data_parsed(self, series: LineSeries) -> None:
        self.plot.prepend_data(series)
        self.plot.update()
        if self._loaded:
            self.finish()

    def process_max_rating(self, message: dict[str, Any]) -> None:
        mx = -10_000
        date = ""

        journal = message["data"]
        journal_leng = len(journal)

        if journal_leng == 0:
            return

        stats = message["included"]
        stats_leng = len(stats)

        stats_index = journal_index = 0
        while stats_index < stats_leng and journal_index < journal_leng:
            if (
                stats[stats_index]["id"]
                != journal[journal_index]["relationships"]["gamePlayerStats"]["data"]["id"]
            ):
                journal_index += 1
                continue

            rating = Rating(
                journal[journal_index]["attributes"]["meanAfter"],
                journal[journal_index]["attributes"]["deviationAfter"],
            )
            if (est := rating.displayed()) >= mx:
                mx = est
                date = stats[stats_index]["attributes"]["scoreTime"]

            stats_index += 1
            journal_index += 1
        self.plot.set_max_rating(mx, date)


class RatingTabWidgetController:
    def __init__(
        self,
        player_id: str,
        tab_widget: QTabWidget,
        load_next_button: QPushButton,
        load_more_button: QPushButton,
        default_pages_box: QSpinBox,
    ) -> None:
        self.player_id = player_id
        self.widget = tab_widget
        self.widget.currentChanged.connect(self.on_tab_changed)
        load_next_button.clicked.connect(self.load_next_rating_page)
        load_more_button.clicked.connect(self.load_more_ratings)
        self.default_pages_box = default_pages_box

        self.crosshair_box = QCheckBox()
        self.crosshair_box.setChecked(
            Settings.get("playercard/plot/show_crosshair", True, type=bool),
        )
        self.crosshair_box.toggled.connect(
            lambda visible: Settings.set("playercard/plot/show_crosshair", visible),
        )

        self.max_rating_box = QCheckBox()
        self.max_rating_box.setChecked(
            Settings.get("playercard/plot/show_max_rating", True, type=bool),
        )
        self.max_rating_box.toggled.connect(
            lambda visible: Settings.set("playercard/plot/show_max_rating", visible),
        )

        self.tabs: dict[int, RatingsPlotTab] = {}

    def setup(self, ratings: list[LeaderboardRating]) -> None:
        for index, rating in enumerate(ratings):
            widget = pg.PlotWidget()
            tab = RatingsPlotTab(
                index,
                self.player_id,
                rating,
                PlotController(widget, self.crosshair_box, self.max_rating_box),
                self.default_pages_box,
            )
            tab.name_changed.connect(self.widget.setTabText)
            tab.api_error.connect(self.on_api_error)
            self.tabs[index] = tab
            assert rating.leaderboard is not None
            self.widget.insertTab(index, widget, rating.leaderboard.pretty_name)

    def load_next_rating_page(self) -> None:
        index = self.widget.currentIndex()
        self.tabs[index].load_next_rating_page()

    def load_more_ratings(self) -> None:
        index = self.widget.currentIndex()
        self.tabs[index].load_more_ratings()

    def close(self) -> None:
        for tab in self.tabs.values():
            tab.close()

    def on_tab_changed(self, index: int) -> None:
        self.tabs[index].enter()

    def on_api_error(self, message: str) -> None:
        text = "Too Many Requests" if "Too Many" in message else message
        QMessageBox.warning(self.widget, "API Error", text)
