import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import QSize
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QCompleter
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QMessageBox

from src import util
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import QueryOptions
from src.api.models.LeagueSeason import LeagueSeason
from src.api.models.LeagueSeasonScore import LeagueSeasonScore
from src.api.models.LeagueSubdivision import LeagueSubdivision
from src.api.player_api import PlayerApiConnector
from src.api.stats_api import LeagueScoreboardApiConnector
from src.api.stats_api import LeagueSubdivisionApiConnector
from src.downloadManager import CachedImageDownloader
from src.downloadManager import DownloadRequest
from src.stats.itemviews.leaderboarditemdelegate import LeaderboardItemDelegate
from src.stats.models.leagueleaderboardtablemodel import Column
from src.stats.models.leagueleaderboardtablemodel import LeagueLeaderboardFilterModel
from src.stats.models.leagueleaderboardtablemodel import LeagueLeaderboardTableModel

if TYPE_CHECKING:
    from src.client._clientwindow import ClientWindow

logger = logging.getLogger(__name__)

FormClass, BaseClass = util.THEME.loadUiType("stats/league_leaderboard.ui")

LOGINS_CHUNK_SIZE = 200
ICON_SIZE = QSize(80, 40)
ALL_DIVISIONS = "All divisions"


class LeagueLeaderboardWidget(BaseClass, FormClass):
    def __init__(
        self,
        client: ClientWindow,
        season: LeagueSeason,
        img_dler: CachedImageDownloader,
    ) -> None:
        BaseClass.__init__(self)
        self.setupUi(self)

        self.client = client
        self.season = season

        self.subdivisions_api = LeagueSubdivisionApiConnector()
        self.scores_api = LeagueScoreboardApiConnector()
        self.player_api = PlayerApiConnector()

        self._downloader = img_dler
        self._icon_request = DownloadRequest()
        self._icon_request.done.connect(self.on_icon_downloaded)

        self.subdivisions: list[LeagueSubdivision] = []
        self.model: LeagueLeaderboardTableModel | None = None
        self.page = 1
        self.total_pages = 1
        self.page_size = self.quantityBox.value()
        self.loading = False
        self.subdivisions_requested = False

        self.pending_player_id: str | None = None
        self._scores_reply: QNetworkReply | None = None

        self.setup_ui()

    def setup_ui(self) -> None:
        self.seasonLabel.setText(self.season_period())

        self.tableView.client = self.client
        self.tableView.setItemDelegate(LeaderboardItemDelegate(self))
        header = self.tableView.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setFixedHeight(30)
        header.setHighlightSections(False)
        header.setSortIndicatorShown(True)

        self.subdivisionBox.currentIndexChanged.connect(self.on_subdivision_changed)
        self.searchPlayerLine.textEdited.connect(self.search_player_completion)
        self.searchPlayerLine.returnPressed.connect(self.find_player)
        self.searchPlayerButton.clicked.connect(self.find_player)
        self.quantityBox.editingFinished.connect(self.on_page_size_changed)
        self.refreshButton.clicked.connect(self.refresh)

        self.pageBox.valueChanged.connect(self.check_total_pages)
        self.pageBox.editingFinished.connect(lambda: self.get_page(self.pageBox.value()))
        self.goToPageButton.clicked.connect(lambda: self.get_page(self.pageBox.value()))
        self.firstButton.clicked.connect(lambda: self.get_page(1))
        self.previousButton.clicked.connect(lambda: self.get_page(self.page - 1))
        self.nextButton.clicked.connect(lambda: self.get_page(self.page + 1))
        self.lastButton.clicked.connect(lambda: self.get_page(self.total_pages))

    def entered(self) -> None:
        if not self.subdivisions_requested:
            self.refresh()

    def refresh(self) -> None:
        self.subdivisions_requested = True
        self.page_size = self.quantityBox.value()
        self.set_loading(True)
        self.subdivisions_api.get_season_subdivisions(self.season.xd, self.on_subdivisions_ready)

    def on_page_size_changed(self) -> None:
        if self.quantityBox.value() == self.page_size or not self.subdivisions:
            return
        self.page_size = self.quantityBox.value()
        self.total_pages = 1
        self.load_page(1)

    def check_total_pages(self) -> None:
        if self.pageBox.value() > self.total_pages:
            self.pageBox.setValue(self.total_pages)

    def set_loading(self, loading: bool) -> None:
        self.loading = loading
        self.labelLoading.setText("Loading..." if loading else "")

    def current_subdivision(self) -> LeagueSubdivision | None:
        index = self.subdivisionBox.currentIndex() - 1
        if 0 <= index < len(self.subdivisions):
            return self.subdivisions[index]
        return None

    def current_scope(self) -> str | None:
        subdivision = self.current_subdivision()
        return subdivision.xd if subdivision is not None else None

    def select_scope(self, subdivision_id: str | None) -> None:
        ids = [sub.xd for sub in self.subdivisions]
        index = ids.index(subdivision_id) + 1 if subdivision_id in ids else 0
        self.subdivisionBox.blockSignals(True)
        self.subdivisionBox.setCurrentIndex(index)
        self.subdivisionBox.blockSignals(False)
        self.show_header()

    @staticmethod
    def subdivision_name(subdivision: LeagueSubdivision) -> str:
        division = subdivision.division.name if subdivision.division else ""
        return f"{division} {subdivision.name}".strip()

    def divisions_info(self) -> dict[str, tuple[str, int]]:
        count = len(self.subdivisions)
        return {
            sub.xd: (self.subdivision_name(sub), count - position)
            for position, sub in enumerate(self.subdivisions)
        }

    def on_subdivisions_ready(self, subdivisions: list[LeagueSubdivision]) -> None:
        current_scope = self.current_scope()

        self.subdivisions = subdivisions
        self.subdivisionBox.blockSignals(True)
        self.subdivisionBox.clear()
        self.subdivisionBox.addItem(ALL_DIVISIONS)
        self.subdivisionBox.addItems(map(self.subdivision_name, subdivisions))
        self.subdivisionBox.blockSignals(False)

        if not subdivisions:
            self.set_loading(False)
            self.divisionLabel.setText("No divisions in this season")
            return

        self.select_scope(current_scope)
        self.total_pages = 1
        self.load_page(1)

    def on_subdivision_changed(self, _: int) -> None:
        self.show_header()
        self.total_pages = 1
        self.load_page(1)

    def season_period(self) -> str:
        start_utc = QDateTime.fromString(self.season.start_date, Qt.DateFormat.ISODate)
        end_utc = QDateTime.fromString(self.season.end_date, Qt.DateFormat.ISODate)
        start = start_utc.toString("yyyy-MM-dd")
        end = end_utc.toString("yyyy-MM-dd")
        days_left = QDateTime.currentDateTimeUtc().daysTo(end_utc)
        if days_left > 1:
            remaining = f"{days_left} days left"
        elif days_left == 1:
            remaining = "1 day left"
        else:
            remaining = "ends today"
        return f"Season {self.season.season_number}: {start} – {end} (UTC), {remaining}"

    def show_header(self) -> None:
        subdivision = self.current_subdivision()
        if subdivision is None:
            self.divisionLabel.setText(ALL_DIVISIONS)
            self.maxScoreLabel.clear()
            self.iconLabel.clear()
            return
        self.divisionLabel.setText(self.subdivision_name(subdivision))
        self.maxScoreLabel.setText(f"(max score: {subdivision.highest_score})")
        self.show_icon(subdivision)

    def show_icon(self, subdivision: LeagueSubdivision) -> None:
        url = subdivision.image_url
        pixmap = self._downloader.get_image(os.path.basename(url))
        if pixmap is None:
            self.iconLabel.clear()
            self._downloader.download_if_needed(url, self._icon_request)
        else:
            self.set_icon(pixmap)

    def set_icon(self, pixmap: QPixmap) -> None:
        self.iconLabel.setPixmap(
            pixmap.scaled(
                ICON_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
        )

    def on_icon_downloaded(self, url: str, pixmap: QPixmap) -> None:
        subdivision = self.current_subdivision()
        if subdivision is not None and os.path.basename(subdivision.image_url) in str(url):
            self.set_icon(pixmap)

    def get_page(self, number: int) -> None:
        if self.loading:
            QMessageBox.critical(
                self.client,
                "League leaderboards",
                "Please, wait for previous request to finish.",
            )
            return
        if 1 <= number <= self.total_pages and number != self.page:
            self.load_page(number)

    def load_page(self, number: int) -> None:
        if not self.subdivisions:
            return
        if self._scores_reply is not None:
            try:
                self._scores_reply.abort()
            except RuntimeError:
                pass
        self.set_loading(True)
        scope = self.current_scope()
        page_size = self.page_size

        def handle(message: ParsedDataApiResponse) -> None:
            self._scores_reply = None
            # selection might have been changed while loading
            if self.current_scope() == scope and self.page_size == page_size:
                self.on_scores_ready(message)

        self._scores_reply = self.scores_api.get_scores(
            self.season.xd, scope, number, page_size, handle, self.on_error,
        )

    def on_error(self, reply: QNetworkReply) -> None:
        self._scores_reply = None
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        self.set_loading(False)
        self.labelLoading.setText(f"Error: {reply.errorString()}")

    def on_scores_ready(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        page_meta = message.get("meta", {}).get("page", {})
        self.total_pages = max(page_meta.get("totalPages", 1), 1)
        self.page = max(page_meta.get("number", 1), 1)
        self.page_size = page_meta.get("limit", self.page_size)
        self.quantityBox.setValue(self.page_size)
        self.labelTotalPages.setText(str(self.total_pages))
        self.pageBox.blockSignals(True)
        self.pageBox.setValue(self.page)
        self.pageBox.blockSignals(False)

        offset = (self.page - 1) * self.page_size
        self.model = LeagueLeaderboardTableModel.from_api(
            message["data"], offset, self.divisions_info(),
        )
        self.model.set_placement_games(self.season.placement_games, self.season.placement_games_rp)
        proxy = LeagueLeaderboardFilterModel()
        proxy.setSourceModel(self.model)
        self.tableView.verticalHeader().setModel(proxy)
        self.tableView.setModel(proxy)
        self.tableView.setColumnHidden(Column.ID, True)
        self.tableView.setColumnHidden(
            Column.DIVISION,
            self.current_subdivision() is not None,
        )
        self.tableView.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tableView.scrollToTop()
        self.set_loading(False)

        self.request_logins(self.model)
        self.select_pending_player()

    def request_logins(self, model: LeagueLeaderboardTableModel) -> None:
        ids = model.player_ids

        def handle(logins: dict[str, str]) -> None:
            # page might have been switched in the meantime
            if self.model is model:
                model.set_logins(logins)
                self.update_completion()

        for start in range(0, len(ids), LOGINS_CHUNK_SIZE):
            self.player_api.get_logins(ids[start:start + LOGINS_CHUNK_SIZE], handle)

    def update_completion(self) -> None:
        if self.model is not None:
            self.searchPlayerLine.set_completion_list(self.model.logins)

    def select_pending_player(self) -> None:
        if self.pending_player_id is None or self.model is None:
            return
        row = self.model.row_of_player(self.pending_player_id)
        self.pending_player_id = None
        if row == -1:
            return
        proxy = self.tableView.model()
        proxy_index = proxy.mapFromSource(self.model.index(row, 0))
        self.tableView.selectRow(proxy_index.row())
        self.tableView.scrollTo(proxy_index)

    def search_player_completion(self) -> None:
        text = self.searchPlayerLine.text()
        if not text:
            return
        query = {"filter": f'login=="{text}*"', "page[size]": 10}
        self.player_api.get_parsed(query, self.create_player_completer)

    def create_player_completer(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        logins = sorted((player["login"] for player in message["data"]), key=str.lower)
        self.searchPlayerLine.set_completion_list(logins)
        completer = QCompleter(logins)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.searchPlayerLine.setCompleter(completer)
        completer.complete()

    def find_player(self) -> None:
        login = self.searchPlayerLine.text().strip()
        if not login:
            return

        if self.model is not None:
            for entry in self.model.entries:
                if entry.login is not None and entry.login.lower() == login.lower():
                    self.pending_player_id = entry.player_id
                    self.select_pending_player()
                    return

        self.labelLoading.setText("Searching...")
        query: QueryOptions = {"filter": f'login=="{login}"', "fields[player]": "login"}
        self.player_api.get_parsed(query, self.on_player_found)

    def on_player_found(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        if not message["data"]:
            self.labelLoading.setText("Player not found")
            return
        player_id = message["data"][0]["id"]
        self.scores_api.get_player_score(
            self.season.xd, player_id, lambda score: self.on_player_score(player_id, score),
        )

    def on_player_score(self, player_id: str, score: LeagueSeasonScore | None) -> None:
        if score is None or score.subdivision is None or score.score is None:
            self.labelLoading.setText("Player has no league rank in this season")
            return

        subdivision_id = score.subdivision.xd
        ids = [sub.xd for sub in self.subdivisions]
        if subdivision_id not in ids:
            self.labelLoading.setText("Player's division not found")
            return

        show_all = self.current_scope() is None
        higher_ids = ids[:ids.index(subdivision_id)] if show_all else []
        scope = None if show_all else subdivision_id

        def on_rank(players_above: int) -> None:
            self.pending_player_id = player_id
            page = players_above // self.page_size + 1
            if self.current_scope() == scope and page == self.page and self.model is not None:
                self.labelLoading.clear()
                self.select_pending_player()
                return
            self.select_scope(scope)
            self.load_page(page)

        self.scores_api.get_rank(self.season.xd, subdivision_id, score, higher_ids, on_rank)
