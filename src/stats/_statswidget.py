import logging
import time

from PyQt6 import QtCore
from PyQt6.QtCore import QSize

from src import util
from src.api.models.Leaderboard import Leaderboard
from src.api.models.LeagueSeason import LeagueSeason
from src.api.stats_api import LeaderboardApiConnector
from src.api.stats_api import LeagueSeasonApiConnector
from src.downloadManager import CachedImageDownloader
from src.qt.utils import block_signals
from src.stats.leaderboard_widget import LeaderboardWidget
from src.stats.league_leaderboard_widget import LeagueLeaderboardWidget
from src.ui.busy_widget import BusyWidget

logger = logging.getLogger(__name__)

ANTIFLOOD = 0.1

FormClass, BaseClass = util.THEME.loadUiType("stats/stats.ui")


class StatsWidget(BaseClass, FormClass, BusyWidget):

    # signals
    laddermaplist = QtCore.pyqtSignal(dict)

    def __init__(self, client):
        super(BaseClass, self).__init__()

        self.setupUi(self)

        self.client = client

        self.selected_player = None
        self.selected_player_loaded = False
        self.currentChanged.connect(self.busy_entered)
        self.pagesDivisions = {}
        self.pagesDivisionsResults = {}
        self.pagesAllLeagues = {}

        self.floodtimer = time.time()

        self.currentLeague = 0
        self.currentDivision = 0

        self.leaderboardApi = LeaderboardApiConnector()
        self.leaderboardApi.data_ready.connect(self.process_leaderboards_info)
        self.leaderboardApi.requestData({"sort": "id"})

        self.leagueSeasons: list[LeagueSeason] = []
        self.leagueSeasonsApi = LeagueSeasonApiConnector()
        self.leagueImgDler = CachedImageDownloader(util.DIVISIONS_CACHE_DIR, QSize(160, 80))
        self.leagueLeaderboards.currentChanged.connect(self.leagueLeaderboardsTabChanged)

        # hiding some non-functional tabs
        self.removeTab(self.indexOf(self.ladderTab))
        self.removeTab(self.indexOf(self.laddermapTab))

        self.leaderboardsByName: dict[str, Leaderboard] = {}

        self.client.authorized.connect(self.onAuthorized)

    def onAuthorized(self):
        if not self.leaderboardsByName:
            self.refreshLeaderboards()
        if not self.leagueSeasons:
            self.leagueSeasonsApi.get_current_seasons(self.process_league_seasons)

    def process_league_seasons(self, seasons: list[LeagueSeason]) -> None:
        self.leagueSeasons = seasons
        self.create_league_tabs()

    def create_league_tabs(self) -> None:
        if not self.leagueSeasons or not self.leaderboardsByName:
            return
        if self.leagueLeaderboards.count() > 0:
            return

        seasons: list[tuple[Leaderboard | None, LeagueSeason]] = []
        for season in self.leagueSeasons:
            name = season.leaderboard.technical_name if season.leaderboard else ""
            seasons.append((self.leaderboardsByName.get(name), season))
        seasons.sort(key=lambda pair: (pair[0] is None, pair[0].order() if pair[0] else 0))

        with block_signals(self.leagueLeaderboards):
            for leaderboard, season in seasons:
                if leaderboard is not None:
                    name = leaderboard.pretty_name
                elif season.leaderboard is not None:
                    name = season.leaderboard.technical_name
                else:
                    name = season.name
                widget = LeagueLeaderboardWidget(self.client, season, self.leagueImgDler)
                index = self.leagueLeaderboards.addTab(
                    widget, f"{name} (Season {season.season_number})",
                )
                self.leagueLeaderboards.setTabToolTip(index, widget.season_period())
        if self.currentIndex() == self.indexOf(self.leaguesTab):
            self.leagueLeaderboardsTabChanged(self.leagueLeaderboards.currentIndex())

    @QtCore.pyqtSlot(int)
    def leagueLeaderboardsTabChanged(self, curr: int) -> None:
        if (widget := self.leagueLeaderboards.widget(curr)) is not None:
            widget.entered()

    def refreshLeaderboards(self):
        with block_signals(self.leaderboards):
            while self.leaderboards.widget(0) is not None:
                self.leaderboards.widget(0).deleteLater()
                self.leaderboards.removeTab(0)
            self.leaderboardApi.requestData(dict(sort="id"))

    @QtCore.pyqtSlot(int)
    def leaderboardsTabChanged(self, curr):
        if self.leaderboards.widget(curr) is not None:
            self.leaderboards.widget(curr).entered()

    def process_leaderboards_info(self, message: dict[str, list[Leaderboard]]) -> None:
        self.leaderboardsByName.clear()
        for index, leaderboard in enumerate(message["values"]):
            self.leaderboardsByName[leaderboard.technical_name] = leaderboard
            self.leaderboards.insertTab(
                index,
                LeaderboardWidget(self.client, self, leaderboard.technical_name),
                leaderboard.pretty_name,
            )
        self.leaderboards.setCurrentIndex(1)
        self.leaderboards.currentChanged.connect(self.leaderboardsTabChanged)

        self.create_league_tabs()

    @QtCore.pyqtSlot()
    def busy_entered(self):
        if self.currentIndex() == self.indexOf(self.leaderboardsTab):
            self.leaderboards.currentChanged.emit(
                self.leaderboards.currentIndex(),
            )
        elif self.currentIndex() == self.indexOf(self.leaguesTab):
            self.leagueLeaderboardsTabChanged(self.leagueLeaderboards.currentIndex())
