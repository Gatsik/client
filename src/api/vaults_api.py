import logging
from collections.abc import Callable
from collections.abc import Sequence
from copy import copy
from typing import Any
from typing import cast

from PyQt6.QtCore import QByteArray
from PyQt6.QtCore import QEventLoop
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtNetwork import QNetworkReply

from src.api.ApiAccessors import DataApiAccessor
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import QueryOptions
from src.api.models.Map import Map
from src.api.models.MapVersion import MapVersion
from src.api.models.MapVersionReview import MapVersionReview
from src.api.models.MatchmakerQueueMapPool import MatchmakerQueueMapPool
from src.api.models.Mod import Mod
from src.api.models.ModVersion import ModVersion
from src.api.models.ModVersionReview import ModVersionReview
from src.model.player import Player
from src.util import decapitalize

logger = logging.getLogger(__name__)


class VaultsApiConnector(DataApiAccessor):
    def __init__(self, route: str) -> None:
        super().__init__(route)
        self._includes: tuple[str, ...] = ("latestVersion", "reviewsSummary")
        self._filters: tuple[str, ...] = ("latestVersion.hidden=='false'",)

    def _extend_query_options(self, query_options: QueryOptions) -> QueryOptions:
        self._add_default_includes(query_options)
        self._apply_default_filters(query_options)
        return query_options

    def _copy_query_options(self, query_options: QueryOptions | None) -> QueryOptions:
        query_options = query_options or {}
        return copy(query_options)

    def request_data(self, query_options: QueryOptions | None = None) -> None:
        query = self._copy_query_options(query_options)
        self._extend_query_options(query)
        self.requestData(query)

    def _add_default_includes(self, query_options: QueryOptions) -> QueryOptions:
        if not self._includes:
            return query_options
        return self._extend_includes(query_options, self._includes)

    def _extend_includes(
            self,
            query_options: QueryOptions,
            to_include: Sequence[str],
    ) -> QueryOptions:
        cur_includes = str(query_options.get("include", ""))
        to_include_str = ",".join((cur_includes, *to_include)).removeprefix(",")
        query_options["include"] = to_include_str
        return query_options

    def _apply_default_filters(self, query_options: QueryOptions) -> QueryOptions:
        if not self._filters:
            return query_options
        cur_filters = str(query_options.get("filter", ""))
        query_options["filter"] = ";".join((cur_filters, *self._filters)).removeprefix(";")
        return query_options


class ModApiConnector(VaultsApiConnector):
    def __init__(self) -> None:
        super().__init__("/data/mod")

    def _extend_query_options(self, query_options: QueryOptions) -> QueryOptions:
        super()._extend_query_options(query_options)
        self._extend_includes(query_options, ["uploader"])
        return query_options

    def convert_parsed(self, parsed: ParsedDataApiResponse) -> dict[str, Any]:
        assert isinstance(parsed["data"], list)
        return {
            "values": [Mod(**entry) for entry in parsed["data"]],
            "meta": parsed["meta"],
        }


class MapApiConnector(VaultsApiConnector):
    def __init__(self) -> None:
        super().__init__("/data/map")

    def _extend_query_options(self, query_options: QueryOptions) -> QueryOptions:
        super()._extend_query_options(query_options)
        return self._extend_includes(query_options, ["author"])

    def _convert_mapversion(self, map_info: dict[str, Any], version_info: dict[str, Any]) -> Map:
        map_model = Map(**map_info)
        map_model.version = MapVersion(**version_info)
        return map_model

    def convert_parsed(self, parsed: ParsedDataApiResponse) -> dict[str, Any]:
        assert isinstance(parsed["data"], list)
        return {
            "values": [
                self._convert_mapversion(info, info["latestVersion"])
                for info in parsed["data"]
            ],
            "meta": parsed["meta"],
        }


class MapPoolApiConnector(VaultsApiConnector):
    def __init__(self) -> None:
        super().__init__("/data/matchmakerQueueMapPool")
        self._includes = (
            "mapPool.mapPoolAssignments",
            "mapPool.mapVersions",
            "mapPool.mapVersions.map",
            "matchmakerQueue",
        )
        self._filters: tuple[str, ...] = ()

    def request_pool_for_queue(self, name: str) -> None:
        self._filters = (f"matchmakerQueue.technicalName=={name!r}",)
        self.request_data()

    def convert_parsed(
        self,
        parsed: ParsedDataApiResponse,
    ) -> dict[str, list[MatchmakerQueueMapPool]]:
        assert isinstance(parsed["data"], list)
        return {
            "values": [MatchmakerQueueMapPool(**pool_data) for pool_data in parsed["data"]],
        }


class ReviewsApiConnector(VaultsApiConnector):
    def __init__(self) -> None:
        super().__init__("")
        self._includes: tuple[str, ...] = tuple()
        self._filters: tuple[str, ...] = tuple()

    def request_data(self, query_options: QueryOptions | None = None) -> None:
        query = self._copy_query_options(query_options)
        self._extend_query_options(query)
        self.get_parsed(query, self.data_ready.emit)

    def request_reviews(self, item: Map | Mod) -> None:
        self.route = f"/data/{item.__class__.__name__.lower()}/{item.xd}"
        query_options = {
            "include": ",".join(("versions", "versions.reviews", "versions.reviews.player")),
        }
        self.request_data(cast(QueryOptions, query_options))

    def request_filtered_reviews(
            self,
            item: Map | Mod,
            query_options: QueryOptions | None = None,
    ) -> None:
        self.route = f"/data/{item.__class__.__name__.lower()}"
        self.request_data(query_options)

    def request_review_by_player(
            self,
            item: Map | Mod,
            player: Player,
    ) -> None:
        assert item.version is not None
        json_api_name = decapitalize(item.version.__class__.__name__)
        self.route = f"/data/{json_api_name}Review"
        query = {
            "filter": (
                f"{json_api_name}.id=={item.version.xd}"
                f";player.id=={player.id}"
            ),
            "include": f"player,{json_api_name}",
        }
        self.request_data(cast(QueryOptions, query))

    def submit_review(
        self,
        version: MapVersion | ModVersion,
        payload: QByteArray,
        handler: Callable[[ParsedDataApiResponse], None],
        error_handler: Callable[[QNetworkReply], None],
    ) -> None:
        json_api_name = decapitalize(version.__class__.__name__)
        endpoint = f"/data/{json_api_name}/{version.xd}/reviews"
        self.post_and_parse(endpoint, payload, handler, error_handler)

    def delete_review(
            self,
            review: MapVersionReview | ModVersionReview,
            handler: Callable[[QNetworkReply], None],
            error_handler: Callable[[QNetworkReply], None],
    ) -> None:
        json_api_name = decapitalize(review.__class__.__name__)
        endpoint = f"/data/{json_api_name}/{review.xd}"
        self.delete(endpoint, handler, error_handler)

    def patch_review(
            self,
            review: MapVersionReview | ModVersionReview,
            payload: QByteArray,
            handler: Callable[[QNetworkReply], None],
            error_handler: Callable[[QNetworkReply], None],
    ) -> None:
        json_api_name = decapitalize(review.__class__.__name__)
        endpoint = f"/data/{json_api_name}/{review.xd}"
        self.patch(endpoint, payload, handler, error_handler, review)


class LatestModVersions(DataApiAccessor):
    ready = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("/data/modVersion")
        self.latest: dict[str, dict[str, Any]] = {}
        self.wait_loop = QEventLoop()
        self.ready.connect(self.wait_loop.quit)

    def store_latest_versions(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        for version in message["data"]:
            latest = (version.get("mod") or {}).get("latestVersion") or {}
            if "uid" in version and "uid" in latest:
                self.latest[version["uid"]] = latest
        self.ready.emit()

    def request_and_get_latest_versions(self, uids: list[str]) -> dict[str, dict[str, Any]]:
        self.latest = {}
        if not uids:
            return self.latest
        quoted = ",".join(f"'{uid}'" for uid in uids)
        query: QueryOptions = {
            "filter": f"uid=in=({quoted})",
            "include": "mod.latestVersion",
            "page[size]": len(uids),
        }
        self.get_parsed(query, self.store_latest_versions, lambda _: self.ready.emit())
        self.wait_loop.exec()
        return self.latest


class LatestMapVersion(DataApiAccessor):
    ready = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("/data/mapVersion")
        self.current: dict[str, Any] = {}
        self.latest: dict[str, Any] = {}
        self.wait_loop = QEventLoop()
        self.ready.connect(self.wait_loop.quit)

    def store_versions(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        if message["data"]:
            self.current = message["data"][0]
            self.latest = (self.current.get("map") or {}).get("latestVersion") or {}
        self.ready.emit()

    def request_and_get_versions(self, folder_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.current, self.latest = {}, {}
        query: QueryOptions = {
            "filter": f"folderName=='{folder_name}'",
            "include": "map.latestVersion",
            "page[size]": 1,
        }
        self.get_parsed(query, self.store_versions, lambda _: self.ready.emit())
        self.wait_loop.exec()
        return self.current, self.latest
