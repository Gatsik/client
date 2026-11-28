from collections.abc import Callable
from collections.abc import Iterable

from PyQt6.QtNetwork import QNetworkReply

from src.api.ApiAccessors import DataApiAccessor
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import QueryOptions
from src.api.ApiBase import _do_nothing
from src.api.models.ModerationReport import ModerationReport


class ModerationReportApiConnector(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/moderationReport")

    def request_reports(
        self,
        reporter_id: int,
        handler: Callable[[list[ModerationReport]], None],
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
    ) -> QNetworkReply:
        query: QueryOptions = {
            "include": "reportedUsers,lastModerator,game",
            "filter": f"reporter.id=={reporter_id}",
            "sort": "-createTime",
            "page[size]": 100,
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler([ModerationReport(**entry) for entry in message["data"]])

        return self.get_parsed(query, handle, error_handler)

    def submit_report(
        self,
        reporter_id: int,
        reported_ids: Iterable[int],
        description: str,
        game_id: int | None,
        timecode: str,
        handler: Callable[[ParsedDataApiResponse], None],
        error_handler: Callable[[QNetworkReply], None],
    ) -> QNetworkReply:
        payload = ModerationReport.to_jsonapi_payload(
            {"createTime", "updateTime", "reportStatus"},
            {"reporter", "reportedUsers", "game"},
            reportDescription=description,
            gameIncidentTimecode=timecode or None,
            reporter={"id": reporter_id},
            reportedUsers=[{"id": pid} for pid in reported_ids],
            game=None if game_id is None else {"id": game_id},
        )
        return self.post_and_parse(self.route, payload, handler, error_handler)
