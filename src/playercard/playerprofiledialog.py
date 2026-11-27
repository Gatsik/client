from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QWidget

from src import util
from src.api.models.AvatarAssignment import AvatarAssignment
from src.api.models.LeaderboardRating import LeaderboardRating
from src.api.models.NameRecord import NameRecord
from src.api.models.Player import Player
from src.api.models.PlayerEvent import PlayerEvent
from src.api.player_api import PlayerApiConnector
from src.api.stats_api import LeaderboardRatingApiConnector
from src.api.stats_api import LeagueSeasonScoreApiConnector
from src.api.stats_api import PlayerEventApiAccessor
from src.config import Settings
from src.downloadManager import CachedImageDownloader
from src.model.player import Player as OnlinePlayer
from src.model.playerset import Playerset
from src.playercard.achievements import AchievementsHandler
from src.playercard.activity import ActivityHeatmap
from src.playercard.avatarhandler import AvatarHandler
from src.playercard.clantab import ClanMembershipTab
from src.playercard.comparison import RatingComparisonTab
from src.playercard.leagueformatter import league_formatter_factory
from src.playercard.ratingtabwidget import RatingTabWidgetController
from src.playercard.statistics import StatsCharts
from src.qt.utils import center_widget_on_screen

if TYPE_CHECKING:
    from src.contextmenu.playercontextmenu import PlayerContextMenu

FormClass, BaseClass = util.THEME.loadUiType("player_card/playercard.ui")


class PlayerProfileDialog(FormClass, BaseClass):
    def __init__(
        self,
        avatar_dler: CachedImageDownloader,
        player_id: str,
        ctx_menu: PlayerContextMenu,
        me: OnlinePlayer | None,
        players: Playerset,
        parent: QWidget | None = None,
    ) -> None:
        BaseClass.__init__(self, parent)
        self.setupUi(self)
        rating_history_pages = Settings.get("playercard/defaultRatingPages", default=10, type=int)
        self.defaultRatingPagesSpinBox.setValue(rating_history_pages)
        window_flags = (
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowFlags(window_flags)

        self.clan_tab = ClanMembershipTab(ctx_menu)
        self.mainTabWidget.addTab(self.clan_tab, "Clan")
        clan_tab_index = self.mainTabWidget.indexOf(self.clan_tab)
        self.viewClanButton.clicked.connect(
            lambda: self.mainTabWidget.setCurrentIndex(clan_tab_index),
        )
        self.me = me
        self.comparison_tab = RatingComparisonTab([player.login for player in players.values()])
        self.mainTabWidget.addTab(self.comparison_tab, "Compare")
        self.mainTabWidget.currentChanged.connect(self.on_tab_changed)
        self.tab_widget_ctrl = RatingTabWidgetController(
            player_id,
            self.ratingsTabWidget,
            self.loadNextRatingHistoryPageButton,
            self.loadMoreRatingHistoryButton,
            self.defaultRatingPagesSpinBox,
        )
        self.avatar_handler = AvatarHandler(self.avatarList, avatar_dler)

        self.player_id = player_id

        self.player_api = PlayerApiConnector()
        self.player_api.player_ready.connect(self.process_player)

        self.leagues_api = LeagueSeasonScoreApiConnector()

        self.ratings_api = LeaderboardRatingApiConnector()
        self.ratings_api.player_ratings_ready.connect(self.process_player_ratings)

        self.player_event_api = PlayerEventApiAccessor()
        self.player_event_api.events_ready.connect(self.process_player_events)

        self.stats_charts = StatsCharts()
        self.activity: ActivityHeatmap | None = None

        self.achievements_handler = AchievementsHandler(self.verticalLayout_2, self.player_id)
        self.leagues_img_dler = CachedImageDownloader(util.DIVISIONS_CACHE_DIR, QSize(160, 80))

        self.player: Player | None = None
        self.player_ratings: list[LeaderboardRating] = []
        self._ratings_received = False
        self.player_events: list[PlayerEvent] = []

        self._restore_geometry_from_settings()
        self._loaded_tabs: set[int] = set()

    def _restore_geometry_from_settings(self) -> None:
        with Settings.group("playercard") as settings:
            self.restoreGeometry(settings.value("geometry", self.saveGeometry()))
            center_widget_on_screen(self)

    def run(self) -> None:
        self.ratings_api.get_player_ratings(self.player_id)
        self.player_api.request_player(self.player_id)
        self.player_event_api.get_player_events(self.player_id)
        self.exec()

    def on_tab_changed(self, index: int) -> None:
        if index in self._loaded_tabs:
            return
        if self.mainTabWidget.currentWidget() == self.achievementsTab:
            self.achievements_handler.run()
        elif self.mainTabWidget.currentWidget() == self.statsTab:
            pie_chart = self.stats_charts.game_types_played(self.player_ratings)
            self.statsChartsLayout.addWidget(pie_chart)
            for chartview in self.stats_charts.player_events_charts(self.player_events):
                self.statsChartsLayout.addWidget(chartview)
            self.activity = ActivityHeatmap(self.player_id)
            self.statsChartsLayout.insertWidget(0, self.activity)
            self.activity.load_more()
        elif self.mainTabWidget.currentWidget() == self.clan_tab and self.player is not None:
            self.clan_tab.set_membership(self.player.custom_clan_membership)
        elif self.mainTabWidget.currentWidget() == self.comparison_tab:
            if self.me is not None and str(self.me.id) != self.player_id:
                self.comparison_tab.request_player(1, self.me.login)
        self._loaded_tabs.add(index)

    def process_player_ratings(self, ratings: dict[str, list[LeaderboardRating]]) -> None:
        for rating in ratings["values"]:
            widget = league_formatter_factory(
                self.player_id,
                rating,
                self.leagues_api,
                self.leagues_img_dler,
            )
            self.leaguesLayout.addWidget(widget)
        self.tab_widget_ctrl.setup(ratings["values"])
        self.player_ratings = ratings["values"]
        self._ratings_received = True
        self.update_comparison()

    def process_player(self, player: Player) -> None:
        self.setWindowTitle(player.login)
        self.nicknameLabel.setText(player.login)
        self.idLabel.setText(player.xd)
        self.registeredLabel.setText(util.utctolocal(player.create_time))
        self.lastLoginLabel.setText(util.utctolocal(player.update_time))
        self.userAgentLabel.setText(player.user_agent)
        self.add_avatars(player.avatar_assignments)
        self.add_names(player.names)
        self.viewClanButton.setEnabled(player.custom_clan_membership is not None)
        if player.custom_clan_membership is not None:
            assert player.custom_clan_membership.custom_clan is not None
            tag = player.custom_clan_membership.custom_clan.tag
            name = player.custom_clan_membership.custom_clan.name
            self.clanNameLabel.setText(f"[{tag}] ({name})")
            self.clanJoinedLabel.setText(util.utctolocal(player.custom_clan_membership.create_time))
        self.player = player
        self.update_comparison()

    def update_comparison(self) -> None:
        if self.player is None or not self._ratings_received:
            return
        if not self.comparison_tab.sides[0].login:
            self.comparison_tab.set_player(0, self.player.login, self.player_ratings)

    def add_names(self, names: list[NameRecord] | None) -> None:
        if names is None:
            return
        self.nameHistoryTableWidget.setRowCount(len(names))
        for row, name_record in enumerate(names):
            name = QTableWidgetItem(name_record.name)
            used_until = QTableWidgetItem(util.utctolocal(name_record.change_time))
            self.nameHistoryTableWidget.setItem(row, 0, name)
            self.nameHistoryTableWidget.setItem(row, 1, used_until)

    def add_avatars(self, avatar_assignments: list[AvatarAssignment] | None) -> None:
        self.avatar_handler.populate_avatars(avatar_assignments)

    def process_player_events(self, events: list[PlayerEvent]) -> None:
        self.player_events = events

    def closeEvent(self, event: QCloseEvent) -> None:
        with Settings.group("playercard") as settings:
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("defaultRatingPages", self.defaultRatingPagesSpinBox.value())
        self.tab_widget_ctrl.close()
        BaseClass.closeEvent(self, event)
