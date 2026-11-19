from collections.abc import Callable
from functools import cached_property
from typing import Any
from typing import Self
from urllib import parse

from PyQt6.QtCore import QObject

from src.client.user import UserRelationTrackers
from src.downloadManager import CachedImageDownloader
from src.downloadManager import DownloadRequest
from src.downloadManager import MapSmallPreviewDownloader
from src.fa import maps
from src.model.chat.channelchatter import ChannelChatter
from src.model.chat.chatter import Chatter
from src.model.game import Game
from src.model.player import Player
from src.qt.models.qtlistmodel import QtListModelItem


class ChatterModelItem(QtListModelItem):
    """
    UI representation of a chatter.
    """
    def __init__(
        self,
        cc: ChannelChatter,
        map_preview_dler: MapSmallPreviewDownloader,
        avatar_dler: CachedImageDownloader,
        relation_trackers: UserRelationTrackers,
    ) -> None:
        QObject.__init__(self)

        self._preview_dler = map_preview_dler
        self._avatar_dler = avatar_dler
        self._relation = relation_trackers

        self._player = None
        self._player_rel = None
        self._game = None
        self.cc = cc

        self.cc.updated.connect(self._updated)
        self.chatter.updated.connect(self._updated)
        self.chatter.newPlayer.connect(self._set_player)
        self._chatter_rel = self._relation.chatters[self.chatter.id_key]
        self._chatter_rel.updated.connect(self._updated)

        self.player = self.chatter.player

    @classmethod
    def builder(
        cls,
        map_preview_dler: MapSmallPreviewDownloader,
        avatar_dler: CachedImageDownloader,
        relation_trackers: UserRelationTrackers,
        **kwargs: Any,
    ) -> Callable[[ChannelChatter], Self]:
        def make(cc: ChannelChatter) -> Self:
            return cls(cc, map_preview_dler, avatar_dler, relation_trackers)
        return make

    def _updated(self):
        self.updated.emit(self)

    def _new_request(self) -> DownloadRequest:
        request = DownloadRequest()
        request.done.connect(self._updated)
        return request

    _map_request = cached_property(_new_request)
    _avatar_request = cached_property(_new_request)

    @property
    def chatter(self) -> Chatter:
        return self.cc.chatter

    def _set_player(
        self,
        chatter: Chatter,
        new_player: Player | None,
        old_player: Player | None,
    ) -> None:
        self.player = new_player
        self._updated()

    @property
    def player(self) -> Player | None:
        return self._player

    @player.setter
    def player(self, value: Player | None) -> None:
        if self._player is not None:
            self.game = None
            self._player.updated.disconnect(self._at_player_updated)
            self._player.newCurrentGame.disconnect(self._set_game)
            self._player_rel.updated.disconnect(self._updated)
            self._player_rel = None

        self._player = value

        if self._player is not None:
            self._player.updated.connect(self._at_player_updated)
            self._player.newCurrentGame.connect(self._set_game)
            self._player_rel = self._relation.players[self._player.id_key]
            self._player_rel.updated.connect(self._updated)
            self.game = self._player.currentGame
            self._download_avatar_if_needed()

    def _at_player_updated(self) -> None:
        self._download_avatar_if_needed()
        self._updated()

    def _set_game(self, player: Player | None, game: Game | None) -> None:
        self.game = game
        self._updated()

    @property
    def game(self) -> Game | None:
        return self._game

    @game.setter
    def game(self, value: Game | None) -> None:
        if self._game is not None:
            self._game.updated.disconnect(self._at_game_updated)
            self._game.liveReplayAvailable.disconnect(self._updated)

        self._game = value

        if self._game is not None:
            self._game.updated.connect(self._at_game_updated)
            self._game.liveReplayAvailable.connect(self._updated)
            self._download_map_preview_if_needed()

    def _at_game_updated(self, new: Game, old: Game) -> None:
        if new.mapname != old.mapname:
            self._download_map_preview_if_needed()
        self._updated()

    def _download_map_preview_if_needed(self) -> None:
        name = self.map_name()
        if name is None:
            return
        if not maps.preview(name):
            self._preview_dler.download_preview(name, self._map_request)

    def map_name(self) -> str | None:
        if self.game is None or self.game.closed():
            return None
        return self.game.mapname.lower()

    def _download_avatar_if_needed(self) -> None:
        if (url := self.avatar_url()) is not None:
            self._avatar_dler.download_if_needed(url, self._avatar_request)

    def avatar_url(self) -> str | None:
        if self.player is None or self.player.avatar is None:
            return None
        url = self.player.avatar["url"]
        return parse.unquote(url)

    def tooltip(self) -> None:
        # TODO: implement this and remove tricks with event filter
        ...
