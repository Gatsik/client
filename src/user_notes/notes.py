import logging
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from PyQt6.QtCore import QObject
from PyQt6.QtCore import QSettings
from PyQt6.QtCore import pyqtSignal

logger = logging.getLogger(__name__)


class _GroupedSettings(Protocol):
    def group(self, name: str) -> AbstractContextManager[QSettings]: ...


class UserNotes[KT: (int, str)](QObject):
    PLAYERS_GROUP = "user.notes"
    IRC_GROUP = "user.irc_notes"

    # key of the added, changed or removed note
    updated = pyqtSignal(object)

    def __init__(
        self,
        settings: _GroupedSettings,
        group: str,
        parse_key: Callable[[str], KT],
    ) -> None:
        super().__init__()
        self._settings = settings
        self._group = group
        self._parse_key = parse_key
        self._notes: dict[KT, str] = {}
        self._load()

    @classmethod
    def for_players(cls, settings: _GroupedSettings) -> UserNotes[int]:
        return cls(settings, cls.PLAYERS_GROUP, int)

    @classmethod
    def for_irc_users(cls, settings: _GroupedSettings) -> UserNotes[str]:
        return cls(settings, cls.IRC_GROUP, _parse_nickname)

    @staticmethod
    def normalize(text: str | None) -> str:
        if not text:
            return ""
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def _as_text(value: object) -> str:
        # QSettings returns a list for unquoted comma-separated values
        if isinstance(value, list | tuple):
            return ", ".join(str(v) for v in value)
        if value is None:
            return ""
        return str(value)

    def _load(self) -> None:
        self._notes.clear()
        with self._settings.group(self._group) as group:
            for raw_key in group.childKeys():
                try:
                    key = self._parse_key(raw_key)
                except ValueError:
                    logger.warning(
                        "Ignoring user note with invalid key in %s: %r", self._group, raw_key,
                    )
                    continue
                text = self.normalize(self._as_text(group.value(raw_key)))
                if text:
                    self._notes[key] = text

    def _write(self, key: KT, text: str | None) -> None:
        with self._settings.group(self._group) as group:
            if text:
                group.setValue(str(key), text)
            else:
                group.remove(str(key))

    def get(self, key: KT) -> str | None:
        return self._notes.get(key)

    def has(self, key: KT) -> bool:
        return key in self._notes

    def set(self, key: KT, text: str | None) -> None:
        # empty text removes the note
        text = self.normalize(text)
        if not text:
            self.remove(key)
            return
        if self._notes.get(key) == text:
            return
        self._notes[key] = text
        self._write(key, text)
        self.updated.emit(key)

    def remove(self, key: KT) -> None:
        if key not in self._notes:
            return
        del self._notes[key]
        self._write(key, None)
        self.updated.emit(key)

    def update_many(self, notes: Mapping[KT, str]) -> None:
        for key, text in notes.items():
            self.set(key, text)

    def all(self) -> dict[KT, str]:
        return dict(self._notes)

    def __len__(self) -> int:
        return len(self._notes)

    def __iter__(self) -> Iterator[KT]:
        return iter(dict(self._notes))

    def __contains__(self, key: object) -> bool:
        return key in self._notes


def _parse_nickname(raw_key: str) -> str:
    if not raw_key or "/" in raw_key:
        raise ValueError(raw_key)
    return raw_key
