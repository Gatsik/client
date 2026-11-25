from typing import TYPE_CHECKING
from typing import Any
from typing import Self

from PyQt6.QtCore import pyqtSignal

from src.model.chat.channel import ChannelID
from src.model.modelitem import ModelItem
from src.model.player import Player
from src.model.transaction import ModelTransaction
from src.model.transaction import transactional

if TYPE_CHECKING:
    from src.model.chat.channelchatter import ChannelChatter


class Chatter(ModelItem):
    newPlayer = pyqtSignal(object, object, object)
    added_channel = pyqtSignal(object)
    removed_channel = pyqtSignal(object)

    def __init__(self, name: str, hostname: str, away: bool = False) -> None:
        ModelItem.__init__(self)
        self.name = name
        self.hostname = hostname
        self.away = away
        self._data_fields.extend(("name", "hostname", "away"))
        self._player = None
        self.channels: dict[tuple[ChannelID, str], ChannelChatter] = {}

    @property
    def id_key(self) -> str:
        return self.name

    def copy(self) -> Self:
        return self.__class__(**self.field_dict)

    @transactional
    def update(self, *, _transaction: ModelTransaction = ModelTransaction(), **kwargs: Any) -> None:
        olduser = self.copy()
        super().update(**kwargs)
        self.emit_update(olduser, _transaction=_transaction)

    @property
    def player(self) -> Player | None:
        return self._player

    @transactional
    def set_player(
        self,
        val: Player | None,
        *,
        _transaction: ModelTransaction = ModelTransaction(),
    ) -> None:
        oldplayer = self._player
        self._player = val
        _transaction.emit(self.newPlayer, self, val, oldplayer)

    @player.setter
    def player(self, val: Player | None) -> None:
        # CAVEAT: this will emit signals immediately!
        self.set_player(val)

    @transactional
    def add_channel(
        self,
        cc: ChannelChatter,
        *,
        _transaction: ModelTransaction = ModelTransaction(),
    ) -> None:
        self.channels[cc.id_key] = cc
        _transaction.emit(self.added_channel, cc)

    @transactional
    def remove_channel(
        self,
        cc: ChannelChatter,
        *,
        _transaction: ModelTransaction = ModelTransaction(),
    ) -> None:
        del self.channels[cc.id_key]
        _transaction.emit(self.removed_channel, cc)

    def is_base_channel_mod(self) -> bool:
        return any(
            cc.is_mod()
            for cc in self.channels.values()
            if cc.channel.is_base
        )
