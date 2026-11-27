import html
import time
from collections import deque
from collections.abc import Callable
from collections.abc import Generator
from typing import TYPE_CHECKING
from typing import Any
from typing import Self

import jinja2
from PyQt6.QtCore import QDate
from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import QObject
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtGui import QTextDocumentFragment
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QMenu

from src.chat.channel_tab import TabInfo
from src.chat.channel_widget import ChannelWidget
from src.chat.chat_area import ChatAreaEntry
from src.chat.chat_controller import ChatController
from src.chat.chatter_menu import ChatterMenu
from src.chat.chatter_model import ChatterEventFilter
from src.chat.chatter_model import ChatterFilterModel
from src.chat.chatter_model import ChatterFormat
from src.chat.chatter_model import ChatterItemDelegate
from src.chat.chatter_model import ChatterLayout
from src.chat.chatter_model import ChatterLayoutElements
from src.chat.chatter_model import ChatterModel
from src.chat.chatter_model import ChatterSorter
from src.client.playercolors import PlayerColors
from src.client.user import User
from src.client.user import UserRelations
from src.config import Settings
from src.downloadManager import CachedImageDownloader
from src.downloadManager import DownloadRequest
from src.fa.game_runner import GameRunner
from src.model.chat.channel import Channel
from src.model.chat.channel import ChannelType
from src.model.chat.channelchatter import ChannelChatter
from src.model.chat.chatline import ChatLineMetadata
from src.model.chat.chatline import ChatLineType
from src.model.chat.chatter import Chatter
from src.util import irc_escape
from src.util.gameurl import GameUrl
from src.util.theme import ThemeSet

if TYPE_CHECKING:
    from src.chat.channel_tab import ChannelTab

REPLY_SCHEME = "faf-reply"
REPLYABLE_TYPES = (ChatLineType.MESSAGE, ChatLineType.ACTION)


class ChannelView:
    def __init__(
        self,
        channel: Channel,
        controller: ChatController,
        widget: ChannelWidget,
        channel_tab: ChannelTab,
        chatter_list_view: ChattersView,
        lines_view: ChatAreaView,
    ) -> None:
        self._channel = channel
        self._controller = controller
        self._chatter_list_view = chatter_list_view
        self._lines_view = lines_view
        self.widget = widget
        self._channel_tab = channel_tab

        self.widget.line_typed.connect(self._at_line_typed)
        self.widget.reply_requested.connect(self._start_reply)
        self.widget.menu_requested.connect(self._extend_line_menu)
        if self._channel.id_key.type == ChannelType.PRIVATE:
            self.widget.show_chatter_list(False)

        self._away_count = sum(cc.chatter.away for cc in self._channel.chatters.values())
        self._channel.added_chatter.connect(self._at_chatter_added)
        self._channel.removed_chatter.connect(self._at_chatter_removed)
        self._controller.chatter_away_changed.connect(self._at_chatter_away_changed)
        self._update_chatter_count()

    def _at_chatter_added(self, cc: ChannelChatter) -> None:
        self._away_count += cc.chatter.away
        self._update_chatter_count()

    def _at_chatter_removed(self, cc: ChannelChatter) -> None:
        self._away_count -= cc.chatter.away
        self._update_chatter_count()

    def _at_chatter_away_changed(self, chatter: Chatter) -> None:
        if any(cc.channel is self._channel for cc in chatter.channels.values()):
            self._away_count += 1 if chatter.away else -1
            self._update_chatter_count()

    def _update_chatter_count(self) -> None:
        online = len(self._channel.chatters) - self._away_count
        self.widget.set_nick_edit_label(f"{online} users (type to filter)")

    @classmethod
    def build(
        cls,
        channel: Channel,
        controller: ChatController,
        channel_tab: ChannelTab,
        **kwargs: Any,
    ) -> Self:
        chat_css_template = ChatLineCssTemplate.build(**kwargs)
        widget = ChannelWidget.build(channel, chat_css_template, **kwargs)
        lines_view = ChatAreaView.build(channel, widget, channel_tab, **kwargs)
        chatter_list_view = ChattersView.build(channel, widget, controller, **kwargs)
        return cls(
            channel, controller, widget, channel_tab, chatter_list_view,
            lines_view,
        )

    @classmethod
    def builder(
        cls,
        controller: ChatController,
        **kwargs: Any,
    ) -> Callable[[Channel, ChannelTab], Self]:
        def make(channel: Channel, channel_tab: ChannelTab) -> Self:
            return cls.build(channel, controller, channel_tab, **kwargs)
        return make

    def _at_line_typed(self, line: str, reply: ChatLineMetadata | None) -> None:
        if reply is None:
            self._controller.send_message(self._channel.id_key, line)
            return
        sender = reply.line.sender
        if sender and not line.startswith("/") and sender.lower() not in line.lower():
            line = f"@{sender} {line}"
        self._controller.send_message(self._channel.id_key, line, reply.line.msgid)

    def _start_reply(self, data: ChatLineMetadata) -> None:
        if data.line.msgid is None:
            return
        self.widget.start_reply(data, f"Replying to @{data.line.sender}: {data.line.text}")

    def _extend_line_menu(self, menu: QMenu, data: ChatLineMetadata) -> None:
        line = data.line
        first = menu.actions()[0] if menu.actions() else None
        actions: list[QAction] = []

        def add(text: str, slot: Callable[[], Any]) -> None:
            action = QAction(text, menu)
            action.triggered.connect(slot)
            actions.append(action)

        if line.msgid is not None and line.type in REPLYABLE_TYPES:
            add("Reply", lambda: self._start_reply(data))
        if line.sender:
            add("Mention", lambda: self.widget.insert_text(f"@{line.sender} "))
            is_me = data.meta.is_me and data.meta.is_me()
            if self._channel.id_key.type == ChannelType.PUBLIC and not is_me:
                add(
                    "Private message",
                    lambda: self._controller.join_private_channel(line.sender),
                )
        add("Copy message", lambda: QApplication.clipboard().setText(line.text))
        if line.sender:
            add("Copy name", lambda: QApplication.clipboard().setText(line.sender))

        menu.insertActions(first, actions)
        if first is not None:
            menu.insertSeparator(first)

    def on_shown(self):
        self._channel_tab.info = TabInfo.IDLE
        self._lines_view.refresh_day()


class ChatAreaView:
    def __init__(
        self,
        channel: Channel,
        widget: ChannelWidget,
        widget_tab: ChannelTab,
        game_runner: GameRunner,
        avatar_adder: ChatAvatarPixAdder,
        formatter: ChatLineFormatter,
    ) -> None:
        self._channel = channel
        self._widget = widget
        self._widget_tab = widget_tab
        self._game_runner = game_runner
        self._channel.lines.added.connect(self._add_line)
        self._channel.lines.removed.connect(self._remove_lines)
        self._channel.updated.connect(self._at_channel_updated)
        self._widget.url_clicked.connect(self._at_url_clicked)
        self._widget.css_reloaded.connect(self._at_css_reloaded)
        self._avatar_adder = avatar_adder
        self._formatter = formatter
        self._separators: deque[bool] = deque()
        self._today = QDate.currentDate()

        self._set_topic(self._channel.topic)

    @classmethod
    def build(
        cls,
        channel: Channel,
        widget: ChannelWidget,
        widget_tab: ChannelTab,
        game_runner: GameRunner,
        **kwargs: Any,
    ) -> Self:
        avatar_adder = ChatAvatarPixAdder.build(widget, **kwargs)
        formatter = ChatLineFormatter.build(**kwargs)
        return cls(
            channel, widget, widget_tab, game_runner, avatar_adder, formatter,
        )

    def _add_line(self):
        data = self._channel.lines[-1]
        if data.meta.player.avatar.url:
            self._avatar_adder.add_avatar(data.meta.player.avatar.url())
        if not self.refresh_day():
            self._append_line(data)
        self._set_tab_info(data)

    def _append_line(self, data: ChatLineMetadata) -> None:
        for text, entry in self._line_entries(data):
            self._widget.append_line(text, entry)

    def _line_entries(self, data: ChatLineMetadata) -> Generator[tuple[str, ChatAreaEntry]]:
        separator = self._formatter.date_separator(data.line.time)
        if separator is not None:
            html, label = separator
            yield html, ChatAreaEntry(None, f"-- {label} --")
        self._separators.append(separator is not None)

        parent = self._find_line(data.line.reply_to) if data.line.reply_to else None
        html = self._formatter.format(data, self._widget.font(), parent)
        payload = None if data.line.type == ChatLineType.RAW else data
        replyable = data.line.msgid is not None and data.line.type in REPLYABLE_TYPES
        entry = ChatAreaEntry(payload, self._formatter.plain_text(data), replyable)
        yield html, entry

    def _find_line(self, msgid: str) -> ChatLineMetadata | None:
        lines = reversed(self._channel.lines)
        return next((data for data in lines if data.line.msgid == msgid), None)

    def _jump_to_line(self, msgid: str) -> None:
        for index, entry in enumerate(self._widget.chat_area.entries()):
            if isinstance(entry.payload, ChatLineMetadata) and entry.payload.line.msgid == msgid:
                self._widget.flash_entry(index)
                return

    def _remove_lines(self, number):
        number = min(number, len(self._separators))
        blocks = number + sum(self._separators.popleft() for _ in range(number))
        self._widget.remove_lines(blocks)

    def _at_channel_updated(self, new, old):
        if new.topic != old.topic:
            self._set_topic(new.topic)

    def _set_topic(self, topic: str) -> None:
        if topic == "":
            self._widget.clear_topic()
        else:
            self._widget.set_topic(irc_escape(topic))

    def _at_url_clicked(self, url: QUrl) -> None:
        if url.scheme() == REPLY_SCHEME:
            self._jump_to_line(url.path())
            return
        if not GameUrl.is_game_url(url):
            QDesktopServices.openUrl(url)
            return
        try:
            gurl = GameUrl.from_url(url)
        except ValueError:
            return
        self._game_runner.run_game_from_url(gurl)

    def _set_tab_info(self, data):
        self._widget_tab.info = self._tab_info(data)

    def _tab_info(self, data):
        if not self._widget.hidden:
            return TabInfo.IDLE
        if self._line_is_important(data):
            return TabInfo.IMPORTANT
        return TabInfo.NEW_MESSAGES

    def _line_is_important(self, data):
        if data.line.type in [
            ChatLineType.INFO, ChatLineType.ANNOUNCEMENT, ChatLineType.RAW,
        ]:
            return False
        if self._channel.id_key.type == ChannelType.PRIVATE:
            return True
        if data.meta.mentions_me and data.meta.mentions_me():
            return True
        return False

    def _at_css_reloaded(self):
        self._rerender()

    def _rerender(self) -> None:
        self._formatter.reset()
        self._separators.clear()
        self._widget.set_lines(
            [item for line in self._channel.lines for item in self._line_entries(line)],
        )

    def refresh_day(self) -> bool:
        today = QDate.currentDate()
        if today == self._today:
            return False
        self._today = today
        self._rerender()
        return True


class ChatAvatarPixAdder:
    def __init__(self, widget: ChannelWidget, avatar_dler: CachedImageDownloader) -> None:
        self._avatar_dler = avatar_dler
        self._widget = widget
        self._requests = {}

    @classmethod
    def build(
        cls,
        widget: ChannelWidget,
        avatar_dler: CachedImageDownloader,
        **kwargs: Any,
    ) -> Self:
        return cls(widget, avatar_dler)

    def add_avatar(self, url: str) -> None:
        avatar_pix = self._avatar_dler.get_image(url)
        if avatar_pix is not None:
            self._add_avatar_resource(url, avatar_pix)
        elif url not in self._requests:
            req = DownloadRequest()
            req.done.connect(self._add_avatar_resource)
            self._requests[url] = req
            self._avatar_dler.download_image(url, req)

    def _add_avatar_resource(self, url, pix):
        if url in self._requests:
            del self._requests[url]
        self._widget.add_avatar_resource(url, pix)


class ChatLineCssTemplate(QObject):
    changed = pyqtSignal()

    def __init__(self, theme: ThemeSet, player_colors: PlayerColors) -> None:
        QObject.__init__(self)
        self._player_colors = player_colors
        self._theme = theme
        self._player_colors.changed.connect(self._reload_css)
        self._theme.stylesheets_reloaded.connect(self._load_template)
        self._load_template()

    @classmethod
    def build(cls, theme: ThemeSet, player_colors: PlayerColors, **kwargs: Any) -> Self:
        return cls(theme, player_colors)

    def _load_template(self):
        self._env = jinja2.Environment()
        template_str = self._theme.readfile("chat/channel.css")
        self._template = self._env.from_string(template_str)
        self._reload_css()

    def _reload_css(self):
        colors = self._player_colors.colors
        if self._player_colors.colored_nicknames:
            random_colors = self._player_colors.random_colors
        else:
            random_colors = None
        self.css = self._template.render(
            colors=colors,
            random_colors=random_colors,
        )
        self.changed.emit()


class ChatLineFormatter:
    def __init__(self, theme: ThemeSet, player_colors: PlayerColors) -> None:
        self._set_theme(theme)
        self._player_colors = player_colors
        self._last_timestamp = None
        self._last_day = QDate()

    @classmethod
    def build(cls, theme: ThemeSet, player_colors: PlayerColors, **kwargs: Any) -> Self:
        return cls(theme, player_colors)

    def _set_theme(self, theme: ThemeSet) -> None:
        self._chatline_template = theme.readfile("chat/chatline.qhtml")
        self._avatar_template = theme.readfile("chat/chatline_avatar.qhtml")
        self._reply_template = theme.readfile("chat/chatline_reply.qhtml")
        self._date_separator_template = theme.readfile("chat/date_separator.qhtml")

    def reset(self) -> None:
        self._last_timestamp = None
        self._last_day = QDate()

    def date_separator(self, stamp: float) -> tuple[str, str] | None:
        day = QDateTime.fromMSecsSinceEpoch(int(stamp * 1000)).date()
        if day == self._last_day:
            return None
        self._last_day = day
        self._last_timestamp = None
        label = self._day_label(day)
        return self._date_separator_template.format(date=label), label

    @staticmethod
    def _day_label(day: QDate) -> str:
        today = QDate.currentDate()
        if day == today:
            return "Today"
        if day == today.addDays(-1):
            return "Yesterday"
        if day.year() != today.year():
            return day.toString("dddd, MMM d, yyyy")
        return day.toString("dddd, MMM d")

    def _line_tags(self, data: ChatLineMetadata) -> Generator[str]:
        line = data.line
        meta = data.meta
        if line.type == ChatLineType.NOTICE:
            yield "notice"
        if line.type == ChatLineType.ACTION:
            yield "action"
        if line.type == ChatLineType.INFO:
            yield "info"
        if line.type == ChatLineType.ANNOUNCEMENT:
            yield "announcement"
            return      # Let announcements decorate themselves
        if line.type == ChatLineType.RAW:
            yield "raw"
            return      # Ditto
        if meta.chatter:
            yield "chatter"
            if meta.chatter.is_mod and meta.chatter.is_mod():
                yield "mod"
            name = meta.chatter.name()
            id_ = meta.player.id() if meta.player.id else None
            yield (
                "randomcolor-{}".format(
                    self._player_colors.get_random_color_index(id_, name),
                )
            )
        if meta.player:
            yield "player"
        if meta.is_friend and meta.is_friend():
            yield "friend"
        if meta.is_foe and meta.is_foe():
            yield "foe"
        if meta.is_me and meta.is_me():
            yield "me"
        if meta.is_clannie and meta.is_clannie():
            yield "clannie"
        if meta.mentions_me and meta.mentions_me():
            yield "mentions_me"
        if meta.player.avatar and meta.player.avatar():
            yield "avatar"

    def _wrap_me(self, text: str, me: str | None) -> str:
        if me:
            return text.replace(me, f"<span class=\"my_mention\">{me}</span>")
        else:
            return text

    def plain_text(self, data: ChatLineMetadata) -> str:
        line = data.line
        stamp = time.strftime('%H:%M', time.localtime(line.time))
        text = line.text
        if line.type in (ChatLineType.ANNOUNCEMENT, ChatLineType.RAW):
            text = QTextDocumentFragment.fromHtml(text).toPlainText()
        if not line.sender:
            return f"{stamp} {text}"
        if line.type in (ChatLineType.MESSAGE, ChatLineType.NOTICE):
            return f"{stamp} {line.sender}: {text}"
        if line.type == ChatLineType.ACTION:
            return f"{stamp} * {line.sender} {text}"
        return f"{stamp} {line.sender} {text}"

    def _reply(self, data: ChatLineMetadata, parent: ChatLineMetadata | None) -> str:
        msgid = data.line.reply_to
        if msgid is None:
            return ""
        if parent is None:
            context = "Replying to an earlier message"
        else:
            text = " ".join(parent.line.text.split())
            if len(text) > 100:
                text = text[:100] + "…"
            context = f"@{parent.line.sender}: {text}"
        return self._reply_template.format(
            url=f"{REPLY_SCHEME}:{html.escape(msgid, quote=True)}",
            text=html.escape(context),
        )

    def format(
        self,
        data: ChatLineMetadata,
        font: QFont,
        parent: ChatLineMetadata | None = None,
    ) -> str:
        tags = " ".join(self._line_tags(data))
        avatar = self._avatar(data)

        if self._check_timestamp(data.line.time):
            stamp = time.strftime('%H:%M', time.localtime(data.line.time))
        else:
            stamp = ""

        text = data.line.text
        mtype = data.line.type

        if mtype == ChatLineType.RAW:
            return text

        if parent is not None and text.startswith(prefix := f"@{parent.line.sender} "):
            text = text.removeprefix(prefix)

        if mtype is not ChatLineType.ANNOUNCEMENT:
            text = self._wrap_me(irc_escape(text), data.meta.my_mention())

        sender_name = self._sender_name(data)
        nick_width = Settings.get("chat/font/nick_width", 101, type=int)
        metrics = QFontMetrics(font)
        elided_sender = metrics.elidedText(
            sender_name,
            Qt.TextElideMode.ElideRight,
            nick_width - metrics.horizontalAdvance(":"),
        )
        if mtype in (ChatLineType.MESSAGE, ChatLineType.NOTICE):
            elided_sender += ":"

        return self._chatline_template.format(
            time=stamp,
            time_width=Settings.get("chat/font/time_width", 32, type=int),
            sender=sender_name,
            elided_sender=elided_sender,
            sender_width=nick_width,
            text=text,
            avatar=avatar,
            tags=tags,
            reply=self._reply(data, parent),
            padding=Settings.get("chat/font/padding", 10, type=int),
        )

    def _avatar(self, data):
        if data.line.type in [
            ChatLineType.INFO, ChatLineType.ANNOUNCEMENT, ChatLineType.RAW,
        ]:
            return ""
        if not data.meta.player.avatar.url:
            return ""
        ava_meta = data.meta.player.avatar
        avatar_url = ava_meta.url()
        avatar_tip = ava_meta.tip() if ava_meta.tip else ""
        return self._avatar_template.format(url=avatar_url, tip=avatar_tip)

    def _sender_name(self, data: ChatLineMetadata) -> str:
        if data.line.sender is None:
            return ""
        sender = ChatterFormat.name(data.line.sender, data.meta.player.clan())
        return html.escape(sender)

    def _check_timestamp(self, stamp):
        local = time.localtime(stamp)
        new_stamp = (
            self._last_timestamp is None
            or local.tm_hour != self._last_timestamp.tm_hour
            or local.tm_min != self._last_timestamp.tm_min
        )
        if new_stamp:
            self._last_timestamp = local
        return new_stamp


class ChattersViewParameters(QObject):
    updated = pyqtSignal()

    def __init__(self, me: User, player_colors: PlayerColors) -> None:
        QObject.__init__(self)
        self._me = me
        self._me.playerChanged.connect(self._updated)
        self._me.clan_changed.connect(self._updated)
        self._player_colors = player_colors
        self._player_colors.changed.connect(self._updated)

    def _updated(self):
        self.updated.emit()

    @classmethod
    def build(cls, me: User, player_colors: PlayerColors, **kwargs: Any) -> Self:
        return cls(me, player_colors)


class ChattersView:
    def __init__(
        self,
        widget: ChannelWidget,
        chatter_layout: ChatterLayout,
        delegate: ChatterItemDelegate,
        model: ChatterFilterModel,
        controller: ChatController,
        event_filter: ChatterEventFilter,
        double_click_handler: ChatterDoubleClickHandler,
        view_parameters: ChattersViewParameters,
    ) -> None:
        self.chatter_layout = chatter_layout
        self.delegate = delegate
        self.model = model
        self._controller = controller
        self.event_filter = event_filter
        self._double_click_handler = double_click_handler
        self._view_parameters = view_parameters
        self.widget = widget

        widget.set_chatter_delegate(self.delegate)
        widget.set_chatter_model(self.model)
        widget.set_chatter_event_filter(self.event_filter)
        widget.chatter_list_resized.connect(self._at_chatter_list_resized)
        view_parameters.updated.connect(self._at_view_parameters_updated)
        self.event_filter.double_clicked.connect(
            self._double_click_handler.handle,
        )

    def _at_chatter_list_resized(self, size):
        self.delegate.update_width(size)

    def _at_view_parameters_updated(self):
        self.model.invalidate_items()

    @classmethod
    def build(
        cls,
        channel: Channel,
        widget: ChannelWidget,
        controller: ChatController,
        user_relations: UserRelations,
        **kwargs: Any,
    ) -> Self:
        sorter = ChatterSorter.build(user_relations=user_relations.model, **kwargs)
        model = ChatterModel.build(
            channel, sorter=sorter, relation_trackers=user_relations.trackers, **kwargs,
        )
        filter_model = ChatterFilterModel.build(model, **kwargs)

        chatter_layout = ChatterLayout.build(**kwargs)
        chatter_menu = ChatterMenu.build(**kwargs)
        delegate = ChatterItemDelegate.build(chatter_layout, **kwargs)
        event_filter = ChatterEventFilter.build(
            chatter_layout, delegate, chatter_menu, **kwargs,
        )
        double_click_handler = ChatterDoubleClickHandler.build(controller, **kwargs)
        view_parameters = ChattersViewParameters.build(**kwargs)

        return cls(
            widget, chatter_layout, delegate, filter_model,
            controller, event_filter, double_click_handler, view_parameters,
        )


class ChatterDoubleClickHandler:
    def __init__(self, controller: ChatController, game_runner: GameRunner) -> None:
        self._controller = controller
        self._game_runner = game_runner

    @classmethod
    def build(cls, controller: ChatController, game_runner: GameRunner, **kwargs: Any) -> Self:
        return cls(controller, game_runner)

    def handle(self, data, elem):
        if elem == ChatterLayoutElements.STATUS:
            self._game_action(data)
        else:
            self._privmsg(data)

    def _privmsg(self, data):
        self._controller.join_private_channel(data.chatter.name)

    def _game_action(self, data):
        game = data.game
        player = data.player
        if game is None or player is None:
            return
        self._game_runner.run_game_with_url(game, player.id)
