from enum import Enum
from enum import IntEnum
from typing import Any

from PyQt6.QtCore import QAbstractTableModel
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QIcon

from src import util
from src.chat.gameinfo import SensitiveMapInfoChecker
from src.client.playercolors import PlayerColors
from src.client.user import User
from src.client.user import UserRelations
from src.downloadManager import CachedImageDownloader
from src.downloadManager import DownloadRequest
from src.downloadManager import MapSmallPreviewDownloader
from src.fa import maps
from src.model.game import Game
from src.model.game import GameState
from src.model.player import Player
from src.model.playerset import Playerset
from src.model.rating import RatingType
from src.user_notes.notes import UserNotes

SORT_ROLE = Qt.ItemDataRole.UserRole
DELAYED_REVEAL = "[delayed reveal]"


class Column(IntEnum):
    COUNTRY = 0
    AVATAR = 1
    NAME = 2
    GLOBAL = 3
    LADDER = 4
    TMM_2V2 = 5
    TMM_3V3 = 6
    TMM_4V4 = 7
    GAMES = 8
    STATUS = 9
    MAP = 10
    GAME = 11


HEADERS = {
    Column.COUNTRY: "",
    Column.AVATAR: "",
    Column.NAME: "Player",
    Column.GLOBAL: "Global",
    Column.LADDER: "1v1",
    Column.TMM_2V2: "2v2",
    Column.TMM_3V3: "3v3",
    Column.TMM_4V4: "4v4",
    Column.GAMES: "Games",
    Column.STATUS: "Status",
    Column.GAME: "Game",
    Column.MAP: "Map",
}

HEADER_TOOLTIPS = {
    Column.COUNTRY: "Country",
    Column.AVATAR: "Avatar",
    Column.GLOBAL: "Global rating",
    Column.LADDER: "1v1 ladder rating",
    Column.TMM_2V2: "2v2 matchmaker rating",
    Column.TMM_3V3: "3v3 matchmaker rating",
    Column.TMM_4V4: "4v4 matchmaker rating",
    Column.GAMES: "Total number of rated games",
}

RATING_COLUMNS = {
    Column.GLOBAL: RatingType.GLOBAL,
    Column.LADDER: RatingType.LADDER,
    Column.TMM_2V2: RatingType.TMM_2v2,
    Column.TMM_3V3: RatingType.TMM_3v3,
    Column.TMM_4V4: RatingType.TMM_4v4,
}

NUMERIC_COLUMNS = frozenset((*RATING_COLUMNS, Column.GAMES))
GAME_COLUMNS = (Column.STATUS, Column.GAME, Column.MAP)


class PlayerStatus(Enum):
    IDLE = ("Idle", "none")
    HOSTING = ("Hosting", "host")
    LOBBY = ("In lobby", "lobby")
    PLAYING = ("Playing", "playing")
    PLAYING_DELAYED = ("Playing", "playing5")

    def __init__(self, label: str, icon_name: str) -> None:
        self.label = label
        self.icon_name = icon_name

    @property
    def in_lobby(self) -> bool:
        return self in (PlayerStatus.HOSTING, PlayerStatus.LOBBY)

    @property
    def playing(self) -> bool:
        return self in (PlayerStatus.PLAYING, PlayerStatus.PLAYING_DELAYED)


STATUS_ORDER = {status: i for i, status in enumerate(PlayerStatus)}


def player_status(player: Player) -> PlayerStatus:
    game = player.currentGame
    if game is None or game.closed():
        return PlayerStatus.IDLE
    if game.state == GameState.OPEN:
        return PlayerStatus.HOSTING if game.host == player.login else PlayerStatus.LOBBY
    if game.state == GameState.PLAYING:
        return PlayerStatus.PLAYING if game.has_live_replay else PlayerStatus.PLAYING_DELAYED
    return PlayerStatus.IDLE


def display_name(player: Player) -> str:
    return f"[{player.clan}]{player.login}" if player.clan else player.login


class PlayersTableModel(QAbstractTableModel):
    MAX_SINGLE_CHANGES = 100

    def __init__(
        self,
        playerset: Playerset,
        me: User,
        user_relations: UserRelations,
        player_colors: PlayerColors,
        avatar_dler: CachedImageDownloader,
        map_preview_dler: MapSmallPreviewDownloader,
        user_notes: UserNotes[int],
    ) -> None:
        super().__init__()
        self._me = me
        self._relations = user_relations.model
        self._player_colors = player_colors
        self._avatar_dler = avatar_dler
        self._preview_dler = map_preview_dler
        self._user_notes = user_notes
        self._info_hider = SensitiveMapInfoChecker(me)

        self._players: list[Player] = []
        self._rows: dict[int, int] = {}
        self._game_players: dict[int, set[int]] = {}

        self._pending_added: dict[int, Player] = {}
        self._pending_removed: dict[int, Player] = {}
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._apply_pending)

        self._avatar_request = DownloadRequest()
        self._avatar_request.done.connect(self._at_avatar_downloaded)
        self._map_requests: dict[str, DownloadRequest] = {}
        self._requested_avatars: set[str] = set()

        playerset.added.connect(self._at_player_added)
        playerset.removed.connect(self._at_player_removed)
        user_relations.trackers.players.updated.connect(self._at_relation_updated)
        player_colors.changed.connect(self._invalidate_all)
        me.playerChanged.connect(self._invalidate_all)
        me.clan_changed.connect(self._invalidate_all)

        self._insert_players(list(playerset.values()))

    def player_at(self, row: int) -> Player:
        return self._players[row]

    def player_count(self) -> int:
        return len(self._players)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._players)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(Column)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            return None
        column = Column(section)
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            return HEADER_TOOLTIPS.get(column)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._players):
            return None
        player = self._players[index.row()]
        column = Column(index.column())
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return self._display(player, column)
            case Qt.ItemDataRole.DecorationRole:
                return self._decoration(player, column)
            case Qt.ItemDataRole.ToolTipRole:
                return self._tooltip(player, column)
            case Qt.ItemDataRole.ForegroundRole if column == Column.NAME:
                return QColor(self._player_colors.get_user_color(player.id, player.login))
            case Qt.ItemDataRole.TextAlignmentRole if column in NUMERIC_COLUMNS:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            case _ if role == SORT_ROLE:
                return self._sort_key(player, column)
        return None

    def _display(self, player: Player, column: Column) -> str | None:
        if (rating_type := RATING_COLUMNS.get(column)) is not None:
            if not self._has_rating(player, rating_type):
                return None
            return str(player.rating_estimate(rating_type.value))
        match column:
            case Column.NAME:
                return display_name(player)
            case Column.GAMES:
                return str(player.number_of_games)
            case Column.STATUS:
                return player_status(player).label
            case Column.GAME:
                return self._game_title(player.currentGame)
            case Column.MAP:
                return self._map_name(player.currentGame)
        return None

    def _decoration(self, player: Player, column: Column) -> QIcon | None:
        match column:
            case Column.COUNTRY:
                country = (player.country or "__").lower()
                return util.THEME.icon(f"chat/countries/{country}.png")
            case Column.AVATAR:
                return self._avatar_icon(player)
            case Column.STATUS:
                return util.THEME.icon(f"chat/status/{player_status(player).icon_name}.png")
            case Column.MAP:
                return self._map_icon(player.currentGame)
        return None

    def _tooltip(self, player: Player, column: Column) -> str | None:
        if (rating_type := RATING_COLUMNS.get(column)) is not None:
            if not self._has_rating(player, rating_type):
                return "No games played"
            key = rating_type.value
            return (
                f"{player.rating_mean(key)} \xb1 {player.rating_deviation(key)}, "
                f"{player.game_count(key)} games"
            )
        match column:
            case Column.COUNTRY:
                return player.country or None
            case Column.AVATAR:
                return None if player.avatar is None else player.avatar.get("tooltip")
            case Column.NAME:
                return self._user_notes.get(player.id)
            case Column.STATUS | Column.GAME | Column.MAP:
                return self._game_tooltip(player)
        return None

    def _sort_key(self, player: Player, column: Column) -> Any:
        if (rating_type := RATING_COLUMNS.get(column)) is not None:
            if not self._has_rating(player, rating_type):
                return -1
            return player.rating_estimate(rating_type.value)
        match column:
            case Column.COUNTRY:
                return player.country or ""
            case Column.AVATAR:
                return "" if player.avatar is None else player.avatar.get("tooltip", "")
            case Column.NAME:
                return player.login.casefold()
            case Column.GAMES:
                return player.number_of_games
            case Column.STATUS:
                return STATUS_ORDER[player_status(player)]
            case Column.GAME:
                return (self._game_title(player.currentGame) or "").casefold()
            case Column.MAP:
                return (self._map_name(player.currentGame) or "").casefold()
        return None

    @staticmethod
    def _has_rating(player: Player, rating_type: RatingType) -> bool:
        return player.game_count(rating_type.value) > 0

    @staticmethod
    def _open_game(game: Game | None) -> Game | None:
        return None if game is None or game.closed() else game

    def _game_title(self, game: Game | None) -> str | None:
        if (game := self._open_game(game)) is None:
            return None
        if self._info_hider.has_sensitive_data(game):
            return DELAYED_REVEAL
        return game.title

    def _map_name(self, game: Game | None) -> str | None:
        if (game := self._open_game(game)) is None:
            return None
        if self._info_hider.has_sensitive_data(game):
            return DELAYED_REVEAL
        return game.mapdisplayname

    def _game_tooltip(self, player: Player) -> str | None:
        status = player_status(player)
        if (game := self._open_game(player.currentGame)) is None:
            return status.label
        lines = [status.label]
        if status == PlayerStatus.LOBBY:
            lines[0] += f" (host {game.host})"
        if status == PlayerStatus.PLAYING_DELAYED:
            lines[0] += " - live delay (5 min)"
        if game.password_protected:
            lines[0] += ", private"
        lines.extend((
            f"Title: {self._game_title(game)}",
            f"Mod: {game.featured_mod}",
            f"Map: {self._map_name(game)}",
            f"Players: {game.num_players - len(game.observers)} / {game.max_players}",
            f"Id: {game.uid}",
        ))
        return "\n".join(lines)

    def _avatar_icon(self, player: Player) -> QIcon | None:
        if player.avatar is None or not (url := player.avatar.get("url")):
            return None
        if (pixmap := self._avatar_dler.get_image(url)) is not None:
            return QIcon(pixmap)
        if url not in self._requested_avatars:
            self._requested_avatars.add(url)
            self._avatar_dler.download_if_needed(url, self._avatar_request)
        return None

    def _map_icon(self, game: Game | None) -> QIcon | None:
        if (game := self._open_game(game)) is None or self._info_hider.has_sensitive_data(game):
            return None
        name = game.mapname.lower()
        if (icon := maps.preview(name)) is not None:
            return icon
        if name not in self._map_requests:
            request = self._map_requests[name] = DownloadRequest()
            request.done.connect(self._at_map_downloaded)
            self._preview_dler.download_preview(name, request)
        return None

    def _at_avatar_downloaded(self) -> None:
        self._column_changed(Column.AVATAR)

    def _at_map_downloaded(self) -> None:
        self._column_changed(Column.MAP)

    def _column_changed(self, column: Column) -> None:
        if self._players:
            last = len(self._players) - 1
            self.dataChanged.emit(self.index(0, column), self.index(last, column))

    def _invalidate_all(self) -> None:
        if self._players:
            last = len(self._players) - 1
            self.dataChanged.emit(self.index(0, 0), self.index(last, len(Column) - 1))

    def _row_changed(self, pid: int, columns: tuple[Column, ...] = tuple(Column)) -> None:
        if (row := self._rows.get(pid)) is None:
            return
        self.dataChanged.emit(self.index(row, min(columns)), self.index(row, max(columns)))

    def _at_relation_updated(self, pid: int) -> None:
        self._row_changed(pid)

    def _at_player_added(self, player: Player) -> None:
        self._pending_added[player.id] = player
        self._pending_timer.start()

    def _at_player_removed(self, player: Player) -> None:
        if self._pending_added.get(player.id) is player:
            del self._pending_added[player.id]
            return
        self._pending_removed[player.id] = player
        self._pending_timer.start()

    def _apply_pending(self) -> None:
        removed, self._pending_removed = self._pending_removed, {}
        added, self._pending_added = self._pending_added, {}
        if removed:
            self._remove_players(list(removed.values()))
        if added:
            self._insert_players(list(added.values()))

    def _insert_players(self, players: list[Player]) -> None:
        if not players:
            return
        for player in players:
            self._connect_player(player)
        first = len(self._players)
        if len(players) > self.MAX_SINGLE_CHANGES:
            self.beginResetModel()
            self._players.extend(players)
            self._reindex(first)
            self.endResetModel()
        else:
            self.beginInsertRows(QModelIndex(), first, first + len(players) - 1)
            self._players.extend(players)
            self._reindex(first)
            self.endInsertRows()

    def _remove_players(self, players: list[Player]) -> None:
        present = [p for p in players if self._rows.get(p.id) is not None]
        for player in present:
            self._disconnect_player(player)
        if len(present) > self.MAX_SINGLE_CHANGES:
            gone = {p.id for p in present}
            self.beginResetModel()
            self._players = [p for p in self._players if p.id not in gone]
            self._rows.clear()
            self._reindex(0)
            self.endResetModel()
            return
        for player in present:
            row = self._rows.pop(player.id)
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._players[row]
            self._reindex(row)
            self.endRemoveRows()

    def _reindex(self, start: int) -> None:
        for row in range(start, len(self._players)):
            self._rows[self._players[row].id] = row

    def _connect_player(self, player: Player) -> None:
        player.updated.connect(self._at_player_updated)
        player.newCurrentGame.connect(self._at_player_game_changed)
        self._watch_game(player.id, player.currentGame)

    def _disconnect_player(self, player: Player) -> None:
        player.updated.disconnect(self._at_player_updated)
        player.newCurrentGame.disconnect(self._at_player_game_changed)
        self._unwatch_game(player.id, player.currentGame)

    def _at_player_updated(self, player: Player, old: Player) -> None:
        self._row_changed(player.id)

    def _at_player_game_changed(self, player: Player, new: Game | None, old: Game | None) -> None:
        self._unwatch_game(player.id, old)
        self._watch_game(player.id, new)
        self._row_changed(player.id, GAME_COLUMNS)

    def _watch_game(self, pid: int, game: Game | None) -> None:
        if game is None:
            return
        if (pids := self._game_players.get(game.uid)) is None:
            pids = self._game_players[game.uid] = set()
            game.updated.connect(self._at_game_updated)
            game.liveReplayAvailable.connect(self._at_game_changed)
        pids.add(pid)

    def _unwatch_game(self, pid: int, game: Game | None) -> None:
        if game is None or (pids := self._game_players.get(game.uid)) is None:
            return
        pids.discard(pid)
        if not pids:
            del self._game_players[game.uid]
            game.updated.disconnect(self._at_game_updated)
            game.liveReplayAvailable.disconnect(self._at_game_changed)

    def _at_game_updated(self, game: Game, old: Game) -> None:
        self._at_game_changed(game)

    def _at_game_changed(self, game: Game) -> None:
        for pid in self._game_players.get(game.uid, ()):
            self._row_changed(pid, GAME_COLUMNS)


class RelationFilter(Enum):
    ALL = "All players"
    FRIENDS = "Friends"
    CLAN = "Clan members"
    NO_FOES = "Without foes"


class StatusFilter(Enum):
    ALL = "Any status"
    IDLE = "Idle"
    LOBBY = "In lobby"
    PLAYING = "Playing"


class PlayersFilterModel(QSortFilterProxyModel):
    def __init__(self, source: PlayersTableModel, me: User, user_relations: UserRelations) -> None:
        super().__init__()
        self._me = me
        self._relations = user_relations.model
        self._text = ""
        self._relation = RelationFilter.ALL
        self._status = StatusFilter.ALL
        self.setSourceModel(source)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def source(self) -> PlayersTableModel:
        return self.sourceModel()

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self._text = text.strip().casefold()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_relation(self, relation: RelationFilter) -> None:
        self.beginFilterChange()
        self._relation = relation
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_status(self, status: StatusFilter) -> None:
        self.beginFilterChange()
        self._status = status
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Vertical:
            return section + 1 if role == Qt.ItemDataRole.DisplayRole else None
        return super().headerData(section, orientation, role)

    def player_at(self, index: QModelIndex) -> Player | None:
        if not index.isValid():
            return None
        return self.source().player_at(self.mapToSource(index).row())

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        player = self.source().player_at(row)
        if self._text and self._text not in display_name(player).casefold():
            return False
        if not self._accepts_relation(player):
            return False
        return self._accepts_status(player)

    def _accepts_relation(self, player: Player) -> bool:
        match self._relation:
            case RelationFilter.FRIENDS:
                return self._relations.is_friend(player.id, player.login)
            case RelationFilter.CLAN:
                return self._me.is_clannie(player.id)
            case RelationFilter.NO_FOES:
                return not self._relations.is_foe(player.id, player.login)
        return True

    def _accepts_status(self, player: Player) -> bool:
        status = player_status(player)
        match self._status:
            case StatusFilter.IDLE:
                return status == PlayerStatus.IDLE
            case StatusFilter.LOBBY:
                return status.in_lobby
            case StatusFilter.PLAYING:
                return status.playing
        return True
