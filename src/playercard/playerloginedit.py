from collections.abc import Iterable
from contextlib import suppress
from functools import partial

from PyQt6.QtCore import QStringListModel
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QCompleter
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QWidget

from src.api.player_api import PlayerApiConnector


def _abort(replies: list[QNetworkReply]) -> None:
    for reply in list(replies):
        try:
            reply.abort()
        except RuntimeError:
            pass
    replies.clear()


def _forget(replies: list[QNetworkReply], reply: QNetworkReply) -> None:
    with suppress(ValueError):
        replies.remove(reply)


class PlayerLoginEdit(QLineEdit):
    login_chosen = pyqtSignal(str)
    TYPING_DELAY_MS = 300
    MIN_SEARCH_LENGTH = 2

    def __init__(self, parent: QWidget | None = None, known_logins: Iterable[str] = ()) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Player login")
        self.player_api = PlayerApiConnector()
        self.replies: list[QNetworkReply] = []
        self.destroyed.connect(partial(_abort, self.replies))
        self._search_id = 0

        self.suggestions = QStringListModel(self)
        self.set_known_logins(known_logins)
        completer = QCompleter(self.suggestions, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.activated[str].connect(self.choose)
        self.setCompleter(completer)

        self.typing_timer = QTimer(self)
        self.typing_timer.setSingleShot(True)
        self.typing_timer.setInterval(self.TYPING_DELAY_MS)
        self.typing_timer.timeout.connect(self.search)
        self.textEdited.connect(self.on_text_edited)
        self.returnPressed.connect(self.on_return_pressed)

    def set_known_logins(self, logins: Iterable[str]) -> None:
        self._known = {login.casefold(): login for login in logins}
        self._update_suggestions()

    def _update_suggestions(self) -> None:
        self.suggestions.setStringList(sorted(self._known.values(), key=str.casefold))

    def on_text_edited(self) -> None:
        self._search_id += 1
        self.typing_timer.start()

    def search(self) -> None:
        prefix = self.text().strip().replace('"', "")
        if len(prefix) < self.MIN_SEARCH_LENGTH:
            return
        self._search_id += 1
        handler = partial(self._on_search_result, self._search_id)
        reply = self.player_api.search_logins(prefix, handler)
        reply.finished.connect(partial(_forget, self.replies, reply))
        self.replies.append(reply)

    def _on_search_result(self, search_id: int, logins: list[str]) -> None:
        if search_id != self._search_id:
            return
        new = {login.casefold(): login for login in logins if login.casefold() not in self._known}
        if not new:
            return
        self._known.update(new)
        self._update_suggestions()
        if self.hasFocus():
            self.completer().complete()

    def on_return_pressed(self) -> None:
        popup = self.completer().popup()
        if popup.isVisible() and popup.currentIndex().isValid():
            return
        self.choose(self.text())

    def choose(self, login: str) -> None:
        self.typing_timer.stop()
        self._search_id += 1
        self.completer().popup().hide()
        self.login_chosen.emit(login.strip())

    def abort_requests(self) -> None:
        self.typing_timer.stop()
        _abort(self.replies)
