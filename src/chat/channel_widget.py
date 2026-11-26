import logging
import re
from typing import TYPE_CHECKING
from typing import Any
from typing import Self

from PyQt6.QtCore import QObject
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtCore import QRegularExpressionMatch
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtGui import QKeySequence
from PyQt6.QtGui import QShortcut
from PyQt6.QtGui import QSyntaxHighlighter
from PyQt6.QtGui import QTextBlock
from PyQt6.QtGui import QTextCharFormat
from PyQt6.QtGui import QTextCursor
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QFrame
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMenu
from PyQt6.QtWidgets import QPushButton

from src.chat.chat_area import ChatArea
from src.chat.chat_area import ChatAreaEntry
from src.client.chat_config import ChatConfig
from src.config import Settings
from src.model.chat.channel import Channel
from src.qt.utils import monkeypatch_method
from src.util.theme import ThemeSet

if TYPE_CHECKING:
    from src.chat.channel_view import ChatLineCssTemplate

logger = logging.getLogger(__name__)


class SearchHighlighter(QSyntaxHighlighter):
    def __init__(self, parent: QTextDocument, theme: ThemeSet) -> None:
        super().__init__(parent)
        self.highlight_format = QTextCharFormat()
        color_str = theme.find_stylesheet_attribute(
            "QTextBrowser::custom",
            "highlight-background-color",
        ) or "yellow"
        self.highlight_format.setBackground(QColor(color_str))
        self.expression = QRegularExpression("")
        self.search_results: list[tuple[QTextBlock, QRegularExpressionMatch]] = []

    def set_expression(self, exp: QRegularExpression, /) -> None:
        self.expression = exp
        self.search_results.clear()

    def highlightBlock(self, text: str | None) -> None:
        if self.expression.pattern() == "":
            return

        block = self.currentBlock()
        iterator = self.expression.globalMatch(text)
        while (iterator.hasNext()):
            m = iterator.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self.highlight_format)
            self.search_results.append((block, m))


class ChannelWidget(QObject):
    line_typed = pyqtSignal(str, object)
    chatter_list_resized = pyqtSignal(object)
    url_clicked = pyqtSignal(QUrl)
    css_reloaded = pyqtSignal()
    reply_requested = pyqtSignal(object)
    menu_requested = pyqtSignal(QMenu, object)

    def __init__(
        self,
        channel: Channel,
        chat_area_css: ChatLineCssTemplate,
        theme: ThemeSet,
        chat_config: ChatConfig,
    ) -> None:
        QObject.__init__(self)
        self.channel = channel
        self._chat_area_css = chat_area_css
        self._chat_area_css.changed.connect(self._reload_css)
        self._chat_config = chat_config
        self._reply_to: object | None = None
        self.set_theme(theme)

        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self.chat_edit)
        self._search_shortcut.activated.connect(self._toggle_search)
        self._cancel_reply_shortcut = QShortcut(QKeySequence("Escape"), self.chat_edit)
        self._cancel_reply_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._cancel_reply_shortcut.activated.connect(self.cancel_reply)

        self.search_button.clicked.connect(self._find_text)
        self.clear_search_button.clicked.connect(self._reset_search)

        self.search_edit.returnPressed.connect(self._find_text)
        self.current_search_index = -1
        self.search_term = ""
        self.highlighter = SearchHighlighter(self.chat_area.document(), theme)
        Settings.changed.connect(self._set_font)

    @classmethod
    def build(
        cls,
        channel: Channel,
        chat_area_css: ChatLineCssTemplate,
        theme: ThemeSet,
        chat_config: ChatConfig,
        **kwargs: Any,
    ) -> Self:
        return cls(channel, chat_area_css, theme, chat_config)

    @property
    def chat_area(self) -> ChatArea:
        return self.form.chatArea

    @property
    def chat_edit(self):
        return self.form.chatEdit

    @property
    def nick_frame(self):
        return self.form.nickFrame

    @property
    def nick_list(self):
        return self.form.nickList

    @property
    def nick_filter(self):
        return self.form.nickFilter

    @property
    def announce_line(self):
        return self.form.announceLine

    @property
    def search_edit(self) -> QLineEdit:
        return self.form.searchEdit

    @property
    def search_label(self) -> QLabel:
        return self.form.searchLabel

    @property
    def search_frame(self) -> QFrame:
        return self.form.searchFrame

    @property
    def search_button(self) -> QPushButton:
        return self.form.searchChannelButton

    @property
    def clear_search_button(self) -> QPushButton:
        return self.form.clearSearchButton

    @property
    def reply_frame(self) -> QFrame:
        return self.form.replyFrame

    @property
    def reply_label(self) -> QLabel:
        return self.form.replyLabel

    def set_theme(self, theme: ThemeSet) -> None:
        formc, basec = theme.loadUiType("chat/channel.ui")
        self.form = formc()
        self.base = basec()
        self.form.setupUi(self.base)
        self.form.searchFrame.hide()

        # Used by chat widget so it knows it corresponds to this widget
        self.base.cid = self.channel.id_key
        self.chat_edit.returnPressed.connect(self._at_line_typed)
        self.nick_list.resized.connect(self._chatter_list_resized)
        self.chat_edit.set_channel(self.channel)
        self.nick_filter.textChanged.connect(self._set_chatter_filter)
        self.chat_area.anchorClicked.connect(self._url_clicked)
        self.chat_area.reply_requested.connect(self.reply_requested.emit)
        self.chat_area.menu_requested.connect(self.menu_requested.emit)
        self.form.cancelReplyButton.clicked.connect(self.cancel_reply)
        self.reply_frame.hide()
        self._override_widget_methods()
        self._load_css()
        self._set_font()
        self._sticky_scroll = ChatAreaStickyScroll(
            self.chat_area.verticalScrollBar(),
        )

    def _set_font(self) -> None:
        cur_font = self.chat_area.font()
        with Settings.group("chat/font") as group:
            font = QFont(group.value("family", cur_font.family()))
            font.setPointSize(group.value("size", cur_font.pointSize(), type=int))
        self.chat_area.setFont(font)

    def font(self) -> QFont:
        return self.chat_area.currentFont()

    def _override_widget_methods(self):

        def on_key_release(obj, old_fn, keyevent):
            if keyevent.key() == 67:    # Ctrl-C
                self.chat_area.copy()
            else:
                old_fn(keyevent)

        def showEvent(obj, super_showEvent, event):
            if self.search_frame.isVisible():
                self.search_edit.setFocus()
            else:
                self.chat_edit.setFocus()
            return super_showEvent(event)

        # FIXME: remove these hacks
        monkeypatch_method(self.base, "keyReleaseEvent", on_key_release)
        monkeypatch_method(self.base, "showEvent", showEvent)

    def _chatter_list_resized(self, size):
        self.chatter_list_resized.emit(size)

    def _url_clicked(self, url):
        self.url_clicked.emit(url)

    # This might be fairly expensive, as we reapply all chat lines to the area.
    # Make sure it's not called really often!
    def _reload_css(self):
        logger.info("Reloading chat CSS...")
        self._load_css()
        self.css_reloaded.emit()    # Qt does not reapply css on its own

    def _load_css(self):
        self.chat_area.document().setDefaultStyleSheet(self._chat_area_css.css)

    def clear_chat(self):
        self.chat_area.clear_entries()

    def add_avatar_resource(self, url, pix):
        doc = self.chat_area.document()
        link = QUrl(url)
        if not doc.resource(QTextDocument.ResourceType.ImageResource, link):
            doc.addResource(QTextDocument.ResourceType.ImageResource, link, pix)

    def _set_chatter_filter(self, text):
        self.nick_list.model().setFilterFixedString(text)

    def _at_line_typed(self):
        text = self.chat_edit.text()
        self.chat_edit.clear()
        fragments = text.split("\n")
        for line in fragments:
            # Compound wacky Whitespace
            line = re.sub(r'\s', ' ', line).strip()
            if not line:
                continue
            reply_to, self._reply_to = self._reply_to, None
            self.line_typed.emit(line, reply_to)
        if self._reply_to is None:
            self.reply_frame.hide()

    def start_reply(self, payload: object, description: str) -> None:
        self._reply_to = payload
        metrics = QFontMetrics(self.reply_label.font())
        self.reply_label.setToolTip(description)
        self.reply_label.setText(
            metrics.elidedText(description, Qt.TextElideMode.ElideRight, self.chat_edit.width()),
        )
        self.reply_frame.show()
        self.chat_edit.setFocus()

    def cancel_reply(self) -> None:
        self._reply_to = None
        self.reply_frame.hide()

    def insert_text(self, text: str) -> None:
        self.chat_edit.insert(text)
        self.chat_edit.setFocus()

    def show_chatter_list(self, should_show):
        self.nick_frame.setVisible(should_show)

    def append_line(self, text: str, entry: ChatAreaEntry) -> None:
        self.chat_area.append_entry(text, entry)

    def remove_lines(self, number: int) -> None:
        self.chat_area.remove_entries(number)

    def flash_entry(self, index: int) -> None:
        self.chat_area.flash_entry(index)

    def set_chatter_delegate(self, delegate):
        self.nick_list.setItemDelegate(delegate)

    def set_chatter_model(self, model):
        self.nick_list.setModel(model)
        model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_chatter_event_filter(self, event_filter):
        self.nick_list.viewport().installEventFilter(event_filter)

    def set_nick_edit_label(self, text):
        self.nick_filter.setPlaceholderText(text)

    @property
    def hidden(self):
        return not self.base.isVisible()

    def set_topic(self, topic: str) -> None:
        self.announce_line.setText(topic)
        self.announce_line.show()

    def clear_topic(self) -> None:
        self.announce_line.clear()
        self.announce_line.hide()

    def _toggle_search(self) -> None:
        if self.search_edit.isVisible() and self.search_edit.hasFocus():
            self._reset_search()
            self.search_frame.hide()
            self.chat_edit.setFocus()
        else:
            self.search_frame.show()
            self.search_edit.setFocus()

    def _reset_search(self) -> None:
        self.search_term = ""
        self.highlighter.set_expression(QRegularExpression(""))

        cursor = self.chat_area.textCursor()
        cursor.clearSelection()
        self.chat_area.setTextCursor(cursor)

        self.search_label.clear()
        self.highlighter.rehighlight()

    def _find_text(self) -> None:
        search_term = self.search_edit.text().strip()

        if not search_term:
            self._reset_search()
            return

        if search_term == self.search_term:
            if not self.highlighter.search_results:
                return
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._navigate_to_search_result(self.current_search_index - 1)
            else:
                self._navigate_to_search_result(self.current_search_index + 1)
            return

        self.search_term = search_term
        pattern_opt = QRegularExpression.PatternOption.CaseInsensitiveOption
        self.highlighter.set_expression(QRegularExpression(search_term, pattern_opt))
        self.highlighter.rehighlight()

        if self.highlighter.search_results:
            self.current_search_index = 0
            self._navigate_to_search_result(0)
        else:
            self.current_search_index = -1
            self.search_label.setText("0 out of 0")

    def _navigate_to_search_result(self, index: int) -> None:
        self.current_search_index = index % len(self.highlighter.search_results)

        block, m = self.highlighter.search_results[self.current_search_index]

        cursor = self.chat_area.textCursor()
        cursor.setPosition(block.position() + m.capturedStart())
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            m.capturedLength(),
        )
        self.chat_area.setTextCursor(cursor)

        current = self.current_search_index + 1
        total = len(self.highlighter.search_results)
        self.search_label.setText(f"{current} out of {total}")


class ChatAreaStickyScroll:
    def __init__(self, scrollbar):
        self._scrollbar = scrollbar
        self._scrollbar.valueChanged.connect(self._track_maximum)
        self._scrollbar.rangeChanged.connect(self._stick_at_range_changed)
        self._is_set_to_maximum = True
        self._old_value = self._scrollbar.value()
        self._saved_scroll = 0

    def save_scroll(self):
        self._saved_scroll = self._scrollbar.value()

    def restore_scroll(self):
        if self._is_set_to_maximum:
            self._scrollbar.setValue(self._scrollbar.maximum())
        else:
            self._scrollbar.setValue(self._saved_scroll)

    def _track_maximum(self, val):
        self._is_set_to_maximum = val == self._scrollbar.maximum()
        self._old_value = val

    def _stick_at_range_changed(self, min_, max_):
        if self._is_set_to_maximum:
            self._scrollbar.setValue(max_)
        else:
            self._scrollbar.setValue(self._old_value)
