import math
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from statistics import NormalDist

from PyQt6.QtCore import Qt
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget
lazy import numpy as np
lazy import pyqtgraph as pg

from src.api.models.Leaderboard import Leaderboard
from src.api.models.LeaderboardRating import LeaderboardRating
from src.api.stats_api import LeaderboardRatingApiConnector
from src.model.rating import Rating
from src.playercard.playerloginedit import PlayerLoginEdit
from src.util import THEME

BETA = 250
DEFAULT_RATING = Rating(1500, 500)
THEME_SECTION = "RatingComparisonPlot::custom"


def _spread(a: Rating, b: Rating) -> float:
    return 2 * BETA ** 2 + a.deviation ** 2 + b.deviation ** 2


def win_probability(a: Rating, b: Rating) -> float:
    return NormalDist().cdf((a.mean - b.mean) / math.sqrt(_spread(a, b)))


def match_quality(a: Rating, b: Rating) -> float:
    spread = _spread(a, b)
    return math.sqrt(2 * BETA ** 2 / spread) * math.exp(-((a.mean - b.mean) ** 2) / (2 * spread))


@dataclass
class Side:
    edit: PlayerLoginEdit
    color: str
    login: str = ""
    ratings: dict[str, LeaderboardRating] | None = None
    request_id: int = field(default=0)

    def rating(self, leaderboard: str) -> Rating | None:
        assert self.ratings is not None
        if (rating := self.ratings.get(leaderboard)) is None:
            return None
        return Rating(rating.mean, rating.deviation)


class RatingComparisonTab(QWidget):
    def __init__(self, logins: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ratings_api = LeaderboardRatingApiConnector()
        self.replies: list[QNetworkReply] = []

        self.sides = (
            Side(PlayerLoginEdit(known_logins=logins), self._color("player-color", "orange")),
            Side(PlayerLoginEdit(known_logins=logins), self._color("me-color", "#4C9AFF")),
        )
        for side in self.sides:
            side.edit.login_chosen.connect(partial(self.on_login_entered, side))

        swap_button = QPushButton("⇄")
        swap_button.setToolTip("Swap players")
        swap_button.setFixedWidth(40)
        swap_button.clicked.connect(self.swap)

        self.leaderboard_box = QComboBox()
        self.leaderboard_box.currentIndexChanged.connect(self.redraw)
        self.summary = QLabel()

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.sides[0].edit)
        top_layout.addWidget(swap_button)
        top_layout.addWidget(self.sides[1].edit)
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("Leaderboard:"))
        top_layout.addWidget(self.leaderboard_box)
        top_layout.addStretch()

        self.plot = pg.PlotWidget()
        self.plot.setBackground(self._color("background-color", "#202025"))
        self.plot.setLabel("bottom", "Rating")
        self.plot.setLabel("left", "Probability density")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.addLegend()

        layout = QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.plot, stretch=1)
        layout.addWidget(self.summary)
        self.redraw()

    def _color(self, attribute: str, fallback: str) -> str:
        return THEME.find_stylesheet_attribute(THEME_SECTION, attribute, fallback=fallback)

    def set_player(self, index: int, login: str, ratings: list[LeaderboardRating]) -> None:
        side = self.sides[index]
        side.request_id += 1
        side.edit.setText(login)
        self._set_side(side, login, ratings)

    def request_player(self, index: int, login: str) -> None:
        self.sides[index].edit.setText(login)
        self.on_login_entered(self.sides[index], login)

    def on_login_entered(self, side: Side, login: str) -> None:
        if login == side.login:
            return
        side.request_id += 1
        side.login = login
        side.ratings = None
        if login:
            handler = partial(self._on_ratings_received, side, side.request_id, login)
            self.replies.append(self.ratings_api.get_ratings_by_login(login, handler))
        self.refresh()

    def _on_ratings_received(
        self,
        side: Side,
        request_id: int,
        login: str,
        ratings: list[LeaderboardRating],
    ) -> None:
        if request_id == side.request_id:
            self._set_side(side, login, ratings)

    def _set_side(self, side: Side, login: str, ratings: list[LeaderboardRating]) -> None:
        side.login = login
        side.ratings = {
            rating.leaderboard.technical_name: rating
            for rating in ratings
            if rating.leaderboard is not None
        }
        self.refresh()

    def abort_requests(self) -> None:
        for side in self.sides:
            side.edit.abort_requests()
        for reply in self.replies:
            try:
                reply.abort()
            except RuntimeError:
                pass
        self.replies.clear()

    def swap(self) -> None:
        first, second = self.sides
        first.login, second.login = second.login, first.login
        first.ratings, second.ratings = second.ratings, first.ratings
        for side in self.sides:
            side.request_id += 1
            side.edit.setText(side.login)
            if side.login and side.ratings is None:
                login, side.login = side.login, ""
                self.on_login_entered(side, login)
        self.redraw()

    def _leaderboards(self) -> list[Leaderboard]:
        leaderboards: dict[str, Leaderboard] = {}
        for side in self.sides:
            for name, rating in (side.ratings or {}).items():
                assert rating.leaderboard is not None
                leaderboards.setdefault(name, rating.leaderboard)
        return sorted(leaderboards.values())

    def refresh(self) -> None:
        selected = self.leaderboard_box.currentData()
        self.leaderboard_box.blockSignals(True)
        self.leaderboard_box.clear()
        for leaderboard in self._leaderboards():
            self.leaderboard_box.addItem(leaderboard.pretty_name, leaderboard.technical_name)
        if (index := self.leaderboard_box.findData(selected)) != -1:
            self.leaderboard_box.setCurrentIndex(index)
        self.leaderboard_box.blockSignals(False)
        self.redraw()

    def _add_curve(self, rating: Rating, x: np.ndarray, name: str, color: str) -> None:
        y = np.exp(-0.5 * ((x - rating.mean) / rating.deviation) ** 2)
        y /= rating.deviation * math.sqrt(2 * math.pi)
        fill = pg.mkColor(color)
        fill.setAlpha(80)
        self.plot.plot(x, y, pen=pg.mkPen(color, width=2), fillLevel=0, brush=fill, name=name)
        self.plot.addLine(x=rating.mean, pen=pg.mkPen(color, style=Qt.PenStyle.DashLine))

    def _pending_message(self) -> str | None:
        for side in self.sides:
            if not side.login:
                return "Enter two players to compare"
            if side.ratings is None:
                return f"Loading ratings of {side.login}…"
            if not side.ratings:
                return f"No ratings found for {side.login}"
        if self.leaderboard_box.currentIndex() < 0:
            return "No ratings to compare"
        return None

    def redraw(self) -> None:
        self.plot.clear()
        if (message := self._pending_message()) is not None:
            self.summary.setText(message)
            return

        leaderboard = self.leaderboard_box.currentData()
        ratings = [side.rating(leaderboard) for side in self.sides]
        first, second = (rating or DEFAULT_RATING for rating in ratings)

        lo = min(r.mean - 4 * r.deviation for r in (first, second))
        hi = max(r.mean + 4 * r.deviation for r in (first, second))
        x = np.linspace(lo, hi, 500)
        for side, rating in zip(self.sides, (first, second)):
            self._add_curve(rating, x, side.login, side.color)
        self.plot.setXRange(lo, hi, padding=0)

        first_chance = win_probability(first, second)
        rows = zip(self.sides, (first, second), ratings, (first_chance, 1 - first_chance))
        lines = [
            f"<b>{side.login}</b>: {r.mean:.0f} ± {r.deviation:.0f} "
            f"(likely {r.mean - r.deviation:.0f}–{r.mean + r.deviation:.0f}, "
            f"displayed {r.displayed():.0f}{'' if actual else ', unrated'}), "
            f"win chance <b>{chance:.1%}</b>"
            for side, r, actual, chance in rows
        ]
        lines.append(f"Chance of an even match: <b>{match_quality(first, second):.1%}</b>")
        self.summary.setText("<br>".join(lines))
