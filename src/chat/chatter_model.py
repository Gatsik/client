from bisect import bisect_left
from collections.abc import Callable
from collections.abc import Hashable
from collections.abc import Iterable
from enum import Enum
from enum import IntEnum
from typing import TYPE_CHECKING
from typing import Any
from typing import NamedTuple
from typing import Self

from PyQt6 import QtCore
from PyQt6 import QtGui
from PyQt6 import QtWidgets
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QObject
from PyQt6.QtCore import QPoint
from PyQt6.QtCore import QRect
from PyQt6.QtCore import QSize
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QIcon

from src import util
from src.chat.chatter_group import ChatterGroup
from src.chat.chatter_group import ChatterGroupItem
from src.chat.chatter_menu import ChatterMenu
from src.chat.chatter_model_item import ChatterModelItem
from src.chat.chatterlistview import ChatterListView
from src.chat.gameinfo import SensitiveMapInfoChecker
from src.client.playercolors import PlayerColors
from src.client.user import User
from src.client.user import UserRelationModel
from src.downloadManager import CachedImageDownloader
from src.fa import maps
from src.model.chat.channel import Channel
from src.model.chat.channelchatter import ChannelChatter
from src.model.game import GameState
from src.model.rating import RatingType
from src.qt.itemviews.styleditemdelegate import StyledItemDelegate
from src.qt.models.qtlistmodel import QtListModel
from src.user_notes.dialogs import note_icon
from src.user_notes.notes import UserNotes
from src.util.theme import ThemeSet

if TYPE_CHECKING:
    from src.client.chat_config import ChatConfig


class ChatterModel(QtListModel[ChannelChatter, ChatterModelItem]):
    """
    Keeps rows sorted, so that the filter model on top doesn't have to:
    sorting there makes every filter change re-sort all the matching rows
    """

    # above this many chatters added at once, the model is reset instead
    MAX_SINGLE_INSERTS = 100

    def __init__(
        self,
        channel: Channel,
        item_builder: Callable[[ChannelChatter], ChatterModelItem],
        sorter: ChatterSorter,
    ) -> None:
        super().__init__(item_builder)
        self._channel = channel
        self._sorter = sorter
        self._sorter.changed.connect(self._resort)
        self._keys: dict[ChatterListItem, ChatterSortKey] = {}
        self._groups: dict[ChatterGroupKey, ChatterGroupItem] = {}

        self._pending: dict[Hashable, ChannelChatter] = {}
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._add_pending)

        self._channel.added_chatter.connect(self.add_chatter)
        self._channel.removed_chatter.connect(self.remove_chatter)

        self._add_items(self._channel.chatters.values())

    @classmethod
    def build(cls, channel: Channel, sorter: ChatterSorter, **kwargs: Any) -> Self:
        builder = ChatterModelItem.builder(**kwargs)
        return cls(channel, builder, sorter)

    def add_chatter(self, chatter: ChannelChatter) -> None:
        self._pending[chatter.id_key] = chatter
        self._pending_timer.start()

    def _add_pending(self) -> None:
        pending, self._pending = self._pending, {}
        self._add_items(pending.values())

    def remove_chatter(self, chatter: ChannelChatter) -> None:
        if self._pending.pop(chatter.id_key, None) is None:
            self._remove_item(chatter.id_key)

    def clear_chatters(self) -> None:
        self._pending.clear()
        self._clear_items()

    def invalidate_items(self) -> None:
        start = self.index(0)
        end = self.index(len(self._itemlist) - 1)
        self.dataChanged.emit(start, end)

    def _row(self, item: ChatterListItem) -> int:
        return bisect_left(self._itemlist, self._keys[item], key=self._keys.__getitem__)

    def group_of(self, item: ChatterModelItem) -> ChatterGroup | None:
        gkey = self._keys[item].group_key
        return None if gkey is None else gkey.group

    def _join_group(self, key: ChatterSortKey) -> ChatterGroupItem | None:
        if (gkey := key.group_key) is None:
            return None
        if (header := self._groups.get(gkey)) is None:
            header = self._groups[gkey] = ChatterGroupItem(gkey.group)
            self._keys[header] = gkey.header_sort_key()
        header.count += 1
        return header

    def _leave_group(self, key: ChatterSortKey) -> None:
        if (gkey := key.group_key) is None:
            return
        header = self._groups[gkey]
        header.count -= 1
        if header.count > 0:
            self._header_changed(header)
            return
        self._take_row(self._row(header))
        del self._groups[gkey]
        del self._keys[header]

    def _header_changed(self, header: ChatterGroupItem) -> None:
        index = self.index(self._row(header), 0)
        self.dataChanged.emit(index, index)

    def _add_items(self, chatters: Iterable[ChannelChatter]) -> None:
        new: list[ChatterListItem] = []
        headers: set[ChatterGroupItem] = set()
        for cc in chatters:
            assert cc.id_key not in self._items
            item = self._item_builder(cc)
            item.updated.connect(self._at_item_updated)
            self._items[cc.id_key] = item
            key = self._keys[item] = self._sorter.key(item)
            new.append(item)
            if (header := self._join_group(key)) is not None:
                headers.add(header)
                if header.count == 1:
                    new.append(header)
        if not new:
            return
        if not self._itemlist or len(new) > self.MAX_SINGLE_INSERTS:
            self.beginResetModel()
            self._itemlist = sorted(self._itemlist + new, key=self._keys.__getitem__)
            self.endResetModel()
        else:
            for item in new:
                self._insert_row(item)
            for header in headers:
                self._header_changed(header)

    def _insert_row(self, item: ChatterListItem) -> None:
        row = self._row(item)
        self.beginInsertRows(QModelIndex(), row, row)
        self._itemlist.insert(row, item)
        self.endInsertRows()

    def _take_row(self, row: int) -> None:
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._itemlist[row]
        self.endRemoveRows()

    def _remove_item(self, id_: Hashable) -> None:
        item = self._items.pop(id_)
        item.updated.disconnect(self._at_item_updated)
        self._take_row(self._row(item))
        self._leave_group(self._keys.pop(item))

    def _clear_items(self) -> None:
        if self._itemlist:
            super()._clear_items()
        self._keys.clear()
        self._groups.clear()

    def _at_item_updated(self, item: ChatterModelItem) -> None:
        if item not in self._keys:
            return
        row = self._row(item)
        old_key = self._keys[item]
        key = self._keys[item] = self._sorter.key(item)
        items = self._itemlist
        regrouped = old_key.group_key != key.group_key
        if (
            regrouped
            or (row > 0 and key < self._keys[items[row - 1]])
            or (row + 1 < len(items) and self._keys[items[row + 1]] < key)
        ):
            # remove and insert rather than move, which the filter model
            # handles as a layout change and re-filters every row
            self._take_row(row)
            if regrouped:
                self._leave_group(old_key)
                if (header := self._join_group(key)) is not None:
                    if header.count == 1:
                        self._insert_row(header)
                    else:
                        self._header_changed(header)
            self._insert_row(item)
        else:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def _resort(self) -> None:
        self.beginResetModel()
        self._keys.clear()
        self._groups.clear()
        self._itemlist = list(self._items.values())
        for item in self._items.values():
            key = self._keys[item] = self._sorter.key(item)
            if (header := self._join_group(key)) is not None and header.count == 1:
                self._itemlist.append(header)
        self._itemlist.sort(key=self._keys.__getitem__)
        self.endResetModel()


class ChatterRank(IntEnum):
    ME = -2
    FRIEND_ON_TOP = -1
    ELEVATED = 0
    FRIEND = 1
    CLANNIE = 2
    USER = 3
    NONPLAYER = 4
    CHATTERBOX = 5
    FOE = 6


RANK_GROUPS = {
    ChatterRank.FRIEND_ON_TOP: ChatterGroup.FRIENDS,
    ChatterRank.ELEVATED: ChatterGroup.MODERATORS,
    ChatterRank.FRIEND: ChatterGroup.FRIENDS,
    ChatterRank.CLANNIE: ChatterGroup.CLAN,
    ChatterRank.USER: ChatterGroup.PLAYERS,
    ChatterRank.NONPLAYER: ChatterGroup.IRC,
    ChatterRank.CHATTERBOX: ChatterGroup.CHATTERBOXES,
    ChatterRank.FOE: ChatterGroup.FOES,
}


class ChatterGroupKey(NamedTuple):
    away: bool
    rank: ChatterRank

    @property
    def group(self) -> ChatterGroup:
        return ChatterGroup.AWAY if self.away else RANK_GROUPS[self.rank]

    def header_sort_key(self) -> ChatterSortKey:
        return ChatterSortKey(self.away, self.rank, "", "")


class ChatterSortKey(NamedTuple):
    away: bool
    rank: ChatterRank
    lower_name: str
    name: str

    @property
    def group_key(self) -> ChatterGroupKey | None:
        if self.rank == ChatterRank.ME:
            return None
        if self.away:
            return ChatterGroupKey(away=True, rank=min(ChatterRank))
        return ChatterGroupKey(away=False, rank=self.rank)


type ChatterListItem = ChatterModelItem | ChatterGroupItem


class ChatterSorter(QObject):
    changed = pyqtSignal()

    def __init__(
        self,
        me: User,
        user_relations: UserRelationModel,
        chat_config: ChatConfig,
    ) -> None:
        super().__init__()
        self._me = me
        self._user_relations = user_relations
        self._chat_config = chat_config
        self._chat_config.updated.connect(self._check_sort_changed)
        self._me.clan_changed.connect(self.changed)

    @classmethod
    def build(
        cls,
        me: User,
        user_relations: UserRelationModel,
        chat_config: ChatConfig,
        **kwargs: Any,
    ) -> Self:
        return cls(me, user_relations, chat_config)

    def key(self, item: ChatterModelItem) -> ChatterSortKey:
        chatter = item.chatter
        name = chatter.name
        rank = self._get_user_rank(item)
        return ChatterSortKey(
            away=chatter.away and rank != ChatterRank.ME,
            rank=rank,
            lower_name=name.lower(),
            name=name,
        )

    def _get_user_rank(self, item):
        name = item.chatter.name
        if name == self._me.login:
            return ChatterRank.ME
        pid = item.player.id if item.player is not None else None
        is_friend = self._user_relations.is_friend(pid, name)
        if self._chat_config.friendsontop and is_friend:
            return ChatterRank.FRIEND_ON_TOP
        if item.cc.is_mod():
            return ChatterRank.ELEVATED
        if is_friend:
            return ChatterRank.FRIEND
        if self._me.is_clannie(pid):
            return ChatterRank.CLANNIE
        if self._user_relations.is_foe(pid, name):
            return ChatterRank.FOE
        if self._user_relations.is_chatterbox(pid, name):
            return ChatterRank.CHATTERBOX
        if item.player is not None:
            return ChatterRank.USER
        return ChatterRank.NONPLAYER

    def _check_sort_changed(self, option):
        if option == "friendsontop":
            self.changed.emit()


class ChatterFilterModel(QSortFilterProxyModel):
    def __init__(self, model: ChatterModel, chat_config: ChatConfig) -> None:
        QSortFilterProxyModel.__init__(self)
        self.setSourceModel(model)
        self._chat_config = chat_config
        self._chat_config.updated.connect(self._at_chat_config_updated)

    @classmethod
    def build(cls, model: ChatterModel, chat_config: ChatConfig, **kwargs: Any) -> Self:
        return cls(model, chat_config)

    def _at_chat_config_updated(self, setting: str) -> None:
        if setting == "collapsed_chatter_groups":
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row: int, parent: QtCore.QModelIndex) -> bool:
        source = self.sourceModel()
        index = source.index(row, 0, parent)
        if not index.isValid():
            return False
        data = source.data(index, Qt.ItemDataRole.DisplayRole)
        regex = self.filterRegularExpression()
        if isinstance(data, ChatterGroupItem):
            return not regex.pattern()
        if regex.pattern():
            return regex.match(ChatterFormat.chatter_name(data.chatter)).hasMatch()
        return source.group_of(data) not in self._chat_config.collapsed_chatter_groups

    def invalidate_items(self):
        self.sourceModel().invalidate_items()


# TODO - place in some separate file?
class ChatterFormat:
    @classmethod
    def name(cls, chatter: str, clan: str | None) -> str:
        if clan is not None:
            return f"[{clan}]{chatter}"
        else:
            return chatter

    @classmethod
    def chatter_name(cls, chatter):
        clan = None if chatter.player is None else chatter.player.clan
        return cls.name(chatter.name, clan)


class ChatterItemFormatter:
    def __init__(
        self,
        avatars: CachedImageDownloader,
        player_colors: PlayerColors,
        info_hider: SensitiveMapInfoChecker,
        user_notes: UserNotes[int] | None = None,
        irc_user_notes: UserNotes[str] | None = None,
    ) -> None:
        self._avatars = avatars
        self._player_colors = player_colors
        self._info_hider = info_hider
        self._user_notes = user_notes
        self._irc_user_notes = irc_user_notes

    @classmethod
    def build(
        cls,
        avatar_dler: CachedImageDownloader,
        player_colors: PlayerColors,
        user_notes: UserNotes[int] | None = None,
        irc_user_notes: UserNotes[str] | None = None,
        **kwargs: Any,
    ) -> Self:
        info_hider = SensitiveMapInfoChecker.build(**kwargs)
        return cls(avatar_dler, player_colors, info_hider, user_notes, irc_user_notes)

    def note(self, data: ChatterModelItem) -> str | None:
        if data.player is not None:
            if self._user_notes is None:
                return None
            return self._user_notes.get(data.player.id)
        if self._irc_user_notes is None:
            return None
        return self._irc_user_notes.get(data.chatter.name)

    def map_icon(self, data):
        game = data.game
        if game is None or game.closed():
            should_hide_info = False
        else:
            should_hide_info = self._info_hider.has_sensitive_data(game)
        if should_hide_info:
            return None

        name = data.map_name()
        return None if name is None else maps.preview(name)

    def chatter_name(self, data):
        return ChatterFormat.chatter_name(data.chatter)

    def chatter_color(self, data):
        pid = -1 if data.player is None else data.player.id
        colors = self._player_colors
        cc = data.cc
        if cc.is_mod():
            return colors.get_mod_color(pid, data.chatter.name)
        else:
            return colors.get_user_color(pid, data.chatter.name)

    def chatter_status(self, data):
        game = data.game
        if game is None or game.closed():
            return "none"
        if game.state == GameState.OPEN:
            if game.host == data.chatter.name:
                return "host"
            return "lobby"
        if game.state == GameState.PLAYING:
            if game.has_live_replay:
                return "playing"
            return "playing5"
        return "unknown"

    def chatter_rank(self, data: ChatterModelItem) -> str:
        if data.player is None:
            return "civilian"
        league = None  # FIXME: remove/handle this deprecated field
        if league is None or "league" not in league:
            return "newplayer"
        return league["league"]

    def chatter_avatar_icon(self, data: ChatterModelItem) -> QIcon | None:
        avatar_url = data.avatar_url()
        if avatar_url is None:
            return None
        if (pixmap := self._avatars.get_image(avatar_url)) is not None:
            return QIcon(pixmap)

    def chatter_country(self, data):
        if data.player is None:
            return None
        country = data.player.country
        if country is None or country == '':
            return '__'
        return country

    def rank_tooltip(self, data):
        if data.player is None:
            return "IRC User"
        player = data.player
        # chr(0xB1) = +-
        formatting = (
            ("{} Rating: {} ({} Games) [{}\xb1{}]\n") * len(player.ratings)
        )
        tooltip_info_list = []
        for rating_type in player.ratings.keys():
            if rating_type == RatingType.LADDER.value:
                rating_name = "Ladder"
            else:
                rating_name = (
                    rating_type.replace("_", " ").capitalize()
                )
            tooltip_info_list.extend([
                rating_name,
                player.rating_estimate(rating_type),
                player.game_count(rating_type),
                player.rating_mean(rating_type),
                player.rating_deviation(rating_type),
            ])

        tooltip_str = formatting.format(*tooltip_info_list)
        league = None
        if league is not None and "division" in league:
            tooltip_str = "Division : {}\n{}".format(
                league["division"],
                tooltip_str,
            )
        return tooltip_str.strip()

    def status_tooltip(self, data):
        # Status tooltip handling
        game = data.game
        if game is None or game.closed():
            return "Idle"

        if self._info_hider.has_sensitive_data(game):
            game_map = "<i>[delayed reveal]</i>"
            game_title = "<i>[delayed reveal]</i>"
        else:
            game_map = game.mapdisplayname
            game_title = game.title

        private_str = " (private)" if game.password_protected else ""
        if game.state == GameState.PLAYING and not game.has_live_replay:
            delay_str = " - LIVE DELAY (5 Min)"
        else:
            delay_str = ""

        head_str = ""
        if game.state == GameState.OPEN:
            if game.host == data.player.login:
                head_str = "Hosting{private} game</b>"
            else:
                head_str = "In{private} Lobby</b> (host {host})"
        elif game.state == GameState.PLAYING:
            head_str = "Playing</b>{delay}"
        header = head_str.format(
            private=private_str, delay=delay_str,
            host=game.host,
        )

        formatting = (
            "<b>{}<br/>"
            "title: {}<br/>"
            "mod: {}<br/>"
            "map: {}<br/>"
            "players: {} / {}<br/>"
            "id: {}"
        )

        game_str = formatting.format(
            header, game_title, game.featured_mod, game_map,
            game.num_players - len(game.observers), game.max_players, game.uid,
        )
        return game_str

    def avatar_tooltip(self, data):
        try:
            return data.player.avatar["tooltip"]
        except (TypeError, AttributeError, KeyError):
            return None

    def map_tooltip(self, data):
        if data.game is None:
            return None
        if self._info_hider.has_sensitive_data(data.game):
            return "<i>[delayed reveal]</i>"
        return data.game.mapdisplayname

    def country_tooltip(self, data):
        return self.chatter_country(data)

    def nick_tooltip(self, data):
        country = self.country_tooltip(data)
        if not data.chatter.away:
            return country
        return "Away" if country is None else f"{country} (away)"


class ChatterItemDelegate(StyledItemDelegate):
    def __init__(
        self,
        layout: ChatterLayout,
        formatter: ChatterItemFormatter,
        chat_config: ChatConfig,
    ) -> None:
        StyledItemDelegate.__init__(self)
        self.layout = layout
        self._formatter = formatter
        self._chat_config = chat_config

    @classmethod
    def build(cls, layout: ChatterLayout, chat_config: ChatConfig, **kwargs: Any) -> Self:
        formatter = ChatterItemFormatter.build(**kwargs)
        return cls(layout, formatter, chat_config)

    def update_width(self, size):
        current_size = self.layout.size
        if size.width() != current_size.width():
            current_size.setWidth(size.width())
            self.layout.size = current_size

    def paint(self, painter, option, index):
        painter.save()

        data = index.data()

        self._draw_clear_option(painter, option)
        if isinstance(data, ChatterGroupItem):
            self._draw_group_header(painter, option, data)
            painter.restore()
            return
        self._handle_highlight(painter, option)

        painter.translate(option.rect.left(), option.rect.top())

        Elems = ChatterLayoutElements
        draw = {
            Elems.NICK: self._draw_nick,
            Elems.STATUS: self._draw_status,
            Elems.MAP: self._draw_map,
            Elems.RANK: self._draw_rank,
            Elems.AVATAR: self._draw_avatar,
            Elems.COUNTRY: self._draw_country,
            Elems.NOTE: self._draw_note,
        }
        for item in self.layout.visible_items():
            draw[item](painter, data)

        painter.restore()

    def _draw_group_header(
            self,
            painter: QtGui.QPainter,
            option: QtWidgets.QStyleOptionViewItem,
            header: ChatterGroupItem,
    ) -> None:
        collapsed = header.group in self._chat_config.collapsed_chatter_groups
        arrow = "\u25b8" if collapsed else "\u25be"
        text = f"{arrow} {header.group.value} ({header.count})"
        font = QtGui.QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(option.palette.color(QtGui.QPalette.ColorRole.Text))
        rect = option.rect.adjusted(4, 0, -4, 0)
        text = self._get_elided_text(painter, text, width=rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _handle_highlight(
            self,
            painter: QtGui.QPainter,
            option: QtWidgets.QStyleOptionViewItem,
    ) -> None:
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight)

    def _draw_nick(self, painter: QtGui.QPainter, data: ChatterModelItem) -> None:
        text = self._formatter.chatter_name(data)
        color = QColor(self._formatter.chatter_color(data))
        if data.chatter.away:
            color.setAlphaF(0.4)
        clip = QRect(self.layout.sizes[ChatterLayoutElements.NICK])
        text = self._get_elided_text(painter, text, width=clip.width())

        painter.save()
        pen = painter.pen()
        pen.setColor(color)
        painter.setPen(pen)

        painter.drawText(clip, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        painter.restore()

    def _draw_status(self, painter, data):
        status = self._formatter.chatter_status(data)
        icon = util.THEME.icon(f"chat/status/{status}.png")
        self._draw_icon(painter, icon, ChatterLayoutElements.STATUS)

    # TODO - handle optionality of maps
    def _draw_map(self, painter, data):
        icon = self._formatter.map_icon(data)
        if not icon:
            return
        self._draw_icon(painter, icon, ChatterLayoutElements.MAP)

    def _draw_rank(self, painter, data):
        rank = self._formatter.chatter_rank(data)
        icon = util.THEME.icon(f"chat/rank/{rank}.png")
        self._draw_icon(painter, icon, ChatterLayoutElements.RANK)

    def _draw_avatar(self, painter, data):
        icon = self._formatter.chatter_avatar_icon(data)
        if not icon:
            return
        self._draw_icon(painter, icon, ChatterLayoutElements.AVATAR)

    def _draw_country(self, painter, data):
        country = self._formatter.chatter_country(data)
        if country is None:
            return
        icon = util.THEME.icon(f"chat/countries/{country.lower()}.png")
        self._draw_icon(painter, icon, ChatterLayoutElements.COUNTRY)

    def _draw_note(self, painter: QtGui.QPainter, data: ChatterModelItem) -> None:
        if self._formatter.note(data) is None:
            return
        self._draw_icon(painter, note_icon(), ChatterLayoutElements.NOTE)

    def _draw_icon(self, painter, icon, element):
        rect = self.layout.sizes[element]
        icon.paint(painter, rect, QtCore.Qt.AlignmentFlag.AlignCenter)

    def sizeHint(self, option, index):
        return self.layout.size

    def get_tooltip(self, data, elem):
        if elem is None:
            return None
        return self._tooltip(data, elem)

    def _tooltip(self, data, item):
        if item == ChatterLayoutElements.RANK:
            return self._formatter.rank_tooltip(data)
        elif item == ChatterLayoutElements.STATUS:
            return self._formatter.status_tooltip(data)
        elif item == ChatterLayoutElements.AVATAR:
            return self._formatter.avatar_tooltip(data)
        elif item == ChatterLayoutElements.MAP:
            return self._formatter.map_tooltip(data)
        elif item == ChatterLayoutElements.COUNTRY:
            return self._formatter.country_tooltip(data)
        elif item == ChatterLayoutElements.NICK:
            return self._formatter.nick_tooltip(data)
        elif item == ChatterLayoutElements.NOTE:
            return self._formatter.note(data)


class ChatterLayoutElements(Enum):
    RANK = "rankBox"
    STATUS = "statusBox"
    AVATAR = "avatarBox"
    MAP = "mapBox"
    COUNTRY = "countryBox"
    NICK = "nickBox"
    NOTE = "noteBox"


class ChatterLayout(QObject):
    """Provides layout info for delegate using Qt widget layouts."""
    LAYOUT_FILE = "chat/chatter.ui"

    def __init__(self, theme: ThemeSet, chat_config: ChatConfig) -> None:
        QObject.__init__(self)
        self._theme = theme
        self._chat_config = chat_config
        self.sizes: dict[ChatterLayoutElements, QRect] = {}
        self.load_layout()
        self._chat_config.updated.connect(self._at_chat_config_updated)
        self._set_visibility()

    @classmethod
    def build(cls, theme: ThemeSet, chat_config: ChatConfig, **kwargs: Any) -> Self:
        return cls(theme, chat_config)

    def load_layout(self) -> None:
        formc, basec = self._theme.loadUiType(self.LAYOUT_FILE)
        self._form = formc()
        self._base = basec()
        self._form.setupUi(self._base)
        self._size = self._base.size()

    def _at_chat_config_updated(self, setting: str) -> None:
        if setting == "hide_chatter_items":
            self._set_visibility()

    def _set_visibility(self) -> None:
        for item in ChatterLayoutElements:
            self._set_visible(item)
        self._update_layout()

    def _set_visible(self, item: ChatterLayoutElements) -> None:
        getattr(self._form, item.value).setVisible(self.is_visible(item))

    def is_visible(self, item: ChatterLayoutElements) -> bool:
        return item not in self._chat_config.hide_chatter_items

    def visible_items(self) -> list[ChatterLayoutElements]:
        return [i for i in ChatterLayoutElements if self.is_visible(i)]

    @property
    def size(self) -> QSize:
        return self._base.size()

    @size.setter
    def size(self, size: QSize) -> None:
        self._size = size
        self._update_layout()

    def element_at_point(self, point: QPoint) -> ChatterLayoutElements | None:
        for elem in ChatterLayoutElements:
            if self.sizes[elem].contains(point) and self.is_visible(elem):
                return elem
        return None

    def _update_layout(self):
        self._base.resize(self._size)
        self._force_layout_recalculation()
        for elem in ChatterLayoutElements:
            self.sizes[elem] = self._get_widget_position(elem.value)

    def _force_layout_recalculation(self):
        layout = self._base.layout()
        layout.update()
        layout.activate()

    def _get_widget_position(self, name: str) -> QRect:
        widget = getattr(self._form, name)
        size = widget.rect()
        top_left = widget.mapTo(self._base, size.topLeft())
        size.moveTopLeft(top_left)
        return size


class ChatterEventFilter(QObject):
    double_clicked = pyqtSignal(object, object)

    def __init__(
        self,
        chatter_layout: ChatterLayout,
        tooltip_handler: ChatterItemDelegate,
        menu_handler: ChatterMenu,
        chat_config: ChatConfig,
    ) -> None:
        QObject.__init__(self)
        self._chatter_layout = chatter_layout
        self._tooltip_handler = tooltip_handler
        self._menu_handler = menu_handler
        self._chat_config = chat_config

    @classmethod
    def build(
        cls,
        chatter_layout: ChatterLayout,
        tooltip_handler: ChatterItemDelegate,
        menu_handler: ChatterMenu,
        chat_config: ChatConfig,
        **kwargs: Any,
    ) -> Self:
        return cls(chatter_layout, tooltip_handler, menu_handler, chat_config)

    def eventFilter(self, obj, event):
        if self._handle_group_click(obj, event):
            return True
        if event.type() == QtCore.QEvent.Type.ToolTip:
            return self._handle_tooltip(obj, event)
        elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                return self._handle_context_menu(obj, event)
        elif event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                return self._handle_double_click(obj, event)
        return super().eventFilter(obj, event)

    def _handle_group_click(self, widget: QtWidgets.QWidget, event: QtCore.QEvent) -> bool:
        Type = QtCore.QEvent.Type
        clicks = (Type.MouseButtonPress, Type.MouseButtonRelease, Type.MouseButtonDblClick)
        if event.type() not in clicks or event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        data, _ = self._get_data_and_elem(widget, event)
        if not isinstance(data, ChatterGroupItem):
            return False
        # toggled on release, since every click has exactly one, also within a double click
        if event.type() == Type.MouseButtonRelease:
            self._chat_config.toggle_chatter_group(data.group)
        return True

    def _get_data_and_elem(
            self,
            widget: QtWidgets.QWidget,
            event: QtGui.QMouseEvent,
    ) -> tuple[Any, ChatterLayoutElements | None]:
        view: ChatterListView = widget.parent()
        idx = view.indexAt(event.pos())
        if not idx.isValid():
            return None, None
        item_rect = view.visualRect(idx)
        point = event.pos() - item_rect.topLeft()
        elem = self._chatter_layout.element_at_point(point)
        return idx.data(), elem

    def _handle_tooltip(self, widget: QtWidgets.QWidget, event: QtGui.QMouseEvent) -> bool:
        data, elem = self._get_data_and_elem(widget, event)
        if data is None or isinstance(data, ChatterGroupItem):
            return False
        tooltip_text = self._tooltip_handler.get_tooltip(data, elem)
        if tooltip_text is None:
            return False

        QtWidgets.QToolTip.showText(event.globalPos(), tooltip_text, widget)
        return True

    def _handle_context_menu(self, widget: QtWidgets.QWidget, event: QtGui.QMouseEvent) -> bool:
        data, elem = self._get_data_and_elem(widget, event)
        if data is None or isinstance(data, ChatterGroupItem):
            return False

        player_id = data.player.id if data.player is not None else -1
        menu = self._menu_handler.get_context_menu(data.chatter.name, player_id)
        menu.popup(QtGui.QCursor.pos())
        return True

    def _handle_double_click(self, widget, event):
        data, elem = self._get_data_and_elem(widget, event)
        if data is None:
            return False
        self.double_clicked.emit(data, elem)
        return True
