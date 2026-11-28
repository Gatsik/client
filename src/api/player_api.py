import logging
from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtNetwork import QNetworkReply

from src.api.ApiAccessors import DataApiAccessor
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import QueryOptions
from src.api.models.Player import Clan
from src.api.models.Player import ClanMembership
from src.api.models.Player import Player

logger = logging.getLogger(__name__)


class PlayerApiConnector(DataApiAccessor):
    alias_info = pyqtSignal(dict)
    player_ready = pyqtSignal(Player)

    def __init__(self) -> None:
        super().__init__('/data/player')

    def requestDataForAliasViewer(self, nameToFind: str) -> None:
        query: QueryOptions = {
            'include': 'names',
            'filter': '(login=="{name}",names.name=="{name}")'.format(
                name=nameToFind,
            ),
            'fields[player]': 'login,names',
            'fields[nameRecord]': 'name,changeTime,player',
        }
        self.get_parsed(query, self.alias_info.emit)

    def get_logins(
        self,
        player_ids: list[str],
        handler: Callable[[dict[str, str]], None],
    ) -> None:
        query: QueryOptions = {
            "filter": "id=in=({})".format(",".join(player_ids)),
            "fields[player]": "login",
            "page[size]": len(player_ids),
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler({entry["id"]: entry["login"] for entry in message["data"]})

        self.get_parsed(query, handle)

    def get_ids(
        self,
        logins: list[str],
        handler: Callable[[dict[str, int]], None],
        error_handler: Callable[[QNetworkReply], None],
    ) -> QNetworkReply:
        quoted = ",".join('"{}"'.format(login.replace('"', "")) for login in logins)
        query: QueryOptions = {
            "filter": f"login=in=({quoted})",
            "fields[player]": "login",
            "page[size]": len(logins),
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler({entry["login"].casefold(): int(entry["id"]) for entry in message["data"]})

        return self.get_parsed(query, handle, error_handler)

    def search_logins(
        self,
        prefix: str,
        handler: Callable[[list[str]], None],
        limit: int = 20,
    ) -> QNetworkReply:
        query: QueryOptions = {
            "filter": f'login=="{prefix}*"',
            "fields[player]": "login",
            "page[size]": limit,
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler([entry["login"] for entry in message["data"]])

        return self.get_parsed(query, handle)

    def request_player(self, player_id: str) -> None:
        query: QueryOptions = {
            "include": "avatarAssignments.avatar,names,clanMembership.clan.memberships.player",
            "filter": f"id=={player_id}",
        }
        self.get_parsed(query, self.handle_player)

    def handle_player(self, message: ParsedDataApiResponse) -> None:
        player_dict, = message["data"]
        assert isinstance(player_dict, dict)
        player = Player(**player_dict)
        if "clan" in player_dict["clanMembership"]:
            clan = Clan(**player_dict["clanMembership"]["clan"])
            clan_membership = ClanMembership(**player_dict["clanMembership"])
            clan_membership.custom_clan = clan
            player.custom_clan_membership = clan_membership
        self.player_ready.emit(player)
