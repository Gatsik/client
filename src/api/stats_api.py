import logging
from collections.abc import Callable
from collections.abc import Iterator
from copy import copy
from operator import methodcaller
from typing import cast

from PyQt6.QtCore import QDateTime
from PyQt6.QtCore import Qt
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtNetwork import QNetworkReply

from src.api.ApiAccessors import ApiAccessor
from src.api.ApiAccessors import DataApiAccessor
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import QueryOptions
from src.api.models.Achievement import Achievement
from src.api.models.Leaderboard import Leaderboard
from src.api.models.LeaderboardRating import LeaderboardRating
from src.api.models.LeagueSeason import LeagueSeason
from src.api.models.LeagueSeasonScore import LeagueSeasonScore
from src.api.models.LeagueSubdivision import LeagueSubdivision
from src.api.models.PlayerAchievement import PlayerAchievement
from src.api.models.PlayerEvent import PlayerEvent

logger = logging.getLogger(__name__)


class LeaderboardRatingApiConnector(DataApiAccessor):
    player_ratings_ready = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__('/data/leaderboardRating')

    def get_player_ratings(self, pid: str) -> None:
        query: QueryOptions = {
            "include": "leaderboard",
            "filter": f"player.id=={pid}",
        }
        self.get_parsed(query, self.handle_player_ratings)

    def handle_player_ratings(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        ratings = sorted(
            [LeaderboardRating(**entry) for entry in message["data"]],
            key=lambda rating: rating.leaderboard.order() if rating.leaderboard is not None else 0,
        )
        self.player_ratings_ready.emit({"values": ratings})


class LeaderboardApiConnector(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/leaderboard")

    def convert_parsed(
        self,
        parsed: ParsedDataApiResponse,
    ) -> dict[str, list[Leaderboard]]:
        assert isinstance(parsed["data"], list)
        return {
            "values": sorted(
                [Leaderboard(**entry) for entry in parsed["data"]],
                key=methodcaller("order"),
            ),
        }


class LeaderboardRatingJournalApiConnector(ApiAccessor):
    ratings_ready = pyqtSignal(dict)
    api_error = pyqtSignal(str)

    max_ready = pyqtSignal(dict)

    def __init__(self, pid: str, leaderboard: str) -> None:
        super().__init__("/data/leaderboardRatingJournal")
        self.query: QueryOptions = {
            "include": "gamePlayerStats",
            "filter": (
                f"gamePlayerStats.player.id=={pid!r};"
                f"leaderboard.technicalName=={leaderboard!r};"
                "gamePlayerStats.scoreTime=isnull='false'"
            ),
            "sort": "-gamePlayerStats.scoreTime",
        }
        self.replies: list[QNetworkReply] = []

    def get_history_page(self, page: int) -> None:
        self.query.update({
            "page[size]": 10000,
            "page[number]": page,
            "page[totals]": "",
        })
        self.replies.append(self.get(self.query, self.ratings_ready.emit, self.on_error))

    def get_max_rating(self) -> None:
        query = copy(self.query)
        query.update({
            "sort": "-meanAfter",
            "page[number]": 1,
            "page[size]": 100,
        })
        self.replies.append(self.get(query, self.max_ready.emit, self.on_error))

    def on_error(self, reply: QNetworkReply) -> None:
        self.api_error.emit(reply.errorString())

    def abort(self) -> None:
        for reply in self.replies:
            try:
                reply.abort()
            except RuntimeError:
                pass
        self.replies.clear()


class LeagueSeasonScoreApiConnector(DataApiAccessor):
    score_ready = pyqtSignal(LeagueSeasonScore)
    scores_ready = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__("/data/leagueSeasonScore")
        self.include = (
            "leagueSeasonDivisionSubdivision",
            "leagueSeasonDivisionSubdivision.leagueSeasonDivision",
            "leagueSeason",
            "leagueSeason.leaderboard",
        )

    def filters(self, player_id: str) -> tuple[str, str, str]:
        utc_str = QDateTime.currentDateTime().toUTC().toString(Qt.DateFormat.ISODate)
        return (
            f"loginId=={player_id!r}",
            f"leagueSeason.startDate=le={utc_str}",
            f"leagueSeason.endDate=ge={utc_str}",
        )

    def handle_score(self, message: ParsedDataApiResponse) -> None:
        score_data = message["data"]
        assert isinstance(score_data, list)
        if score_data:
            self.score_ready.emit(LeagueSeasonScore(**score_data[0]))

    def get_player_score_in_leaderboard(self, player_id: str, leaderboard: str) -> None:
        filters = (
            *self.filters(player_id),
            f"leagueSeason.leaderboard.technicalName=={leaderboard!r}",
        )
        query: QueryOptions = {"include": ",".join(self.include), "filter": ";".join(filters)}
        self.get_parsed(query, self.handle_score)

    def handle_season_scores(self, message: ParsedDataApiResponse) -> None:
        scores = message["data"]
        assert isinstance(scores, list)
        if scores:
            self.scores_ready.emit([LeagueSeasonScore(**score_data) for score_data in scores])

    def get_player_scores(self, player_id: str) -> None:
        query_params = {
            "include": ",".join(self.include),
            "filter": ";".join(self.filters(player_id)),
        }
        self.get_parsed(cast(QueryOptions, query_params), self.handle_season_scores)


class LeagueSeasonApiConnector(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/leagueSeason")

    def get_current_seasons(self, handler: Callable[[list[LeagueSeason]], None]) -> None:
        now = QDateTime.currentDateTime().toUTC().toString(Qt.DateFormat.ISODate)
        query: QueryOptions = {
            "include": "leaderboard",
            "filter": f"startDate=le={now};endDate=ge={now}",
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler([LeagueSeason(**entry) for entry in message["data"]])

        self.get_parsed(query, handle)


class LeagueSubdivisionApiConnector(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/leagueSeasonDivisionSubdivision")

    def get_season_subdivisions(
        self,
        season_id: str,
        handler: Callable[[list[LeagueSubdivision]], None],
    ) -> None:
        query: QueryOptions = {
            "include": "leagueSeasonDivision",
            "filter": f"leagueSeasonDivision.leagueSeason.id=={season_id}",
            "page[size]": 1000,
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            subdivisions = [LeagueSubdivision(**entry) for entry in message["data"]]
            handler(
                sorted(
                    subdivisions,
                    key=lambda sub: (sub.division.index if sub.division else 0, sub.index),
                    reverse=True,
                ),
            )

        self.get_parsed(query, handle)


class LeagueScoreboardApiConnector(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/leagueSeasonScore")

    def get_scores(
        self,
        season_id: str,
        subdivision_id: str | None,
        page: int,
        page_size: int,
        handler: Callable[[ParsedDataApiResponse], None],
        error_handler: Callable[[QNetworkReply], None],
    ) -> QNetworkReply:
        if subdivision_id is None:
            scope = "score=isnull=false"
            sort = ",".join((
                "-leagueSeasonDivisionSubdivision.leagueSeasonDivision.divisionIndex",
                "-leagueSeasonDivisionSubdivision.subdivisionIndex",
                "-score",
                "-gameCount",
            ))
        else:
            scope = f"leagueSeasonDivisionSubdivision.id=={subdivision_id}"
            sort = "-score,-gameCount"
        query: QueryOptions = {
            "filter": f"leagueSeason.id=={season_id};{scope}",
            "sort": sort,
            "page[size]": page_size,
            "page[number]": page,
            "page[totals]": "yes",
        }
        return self.get_parsed(query, handler, error_handler)

    def get_player_score(
        self,
        season_id: str,
        player_id: str,
        handler: Callable[[LeagueSeasonScore | None], None],
    ) -> None:
        query: QueryOptions = {
            "include": "leagueSeasonDivisionSubdivision",
            "filter": f"leagueSeason.id=={season_id};loginId=={player_id}",
        }

        def handle(message: ParsedDataApiResponse) -> None:
            assert isinstance(message["data"], list)
            handler(LeagueSeasonScore(**message["data"][0]) if message["data"] else None)

        self.get_parsed(query, handle)

    def get_rank(
        self,
        season_id: str,
        subdivision_id: str,
        score: LeagueSeasonScore,
        higher_subdivision_ids: list[str],
        handler: Callable[[int], None],
    ) -> None:
        same_subdivision = (
            f"(leagueSeasonDivisionSubdivision.id=={subdivision_id};"
            f"(score=gt={score.score},(score=={score.score};gameCount=gt={score.game_count})))"
        )
        if higher_subdivision_ids:
            higher = "{}.id=in=({})".format(
                "leagueSeasonDivisionSubdivision", ",".join(higher_subdivision_ids),
            )
            above = f"({higher},{same_subdivision})"
        else:
            above = same_subdivision
        query: QueryOptions = {
            "filter": f"leagueSeason.id=={season_id};score=isnull=false;{above}",
            "page[size]": 1,
            "page[totals]": "yes",
        }

        def handle(message: ParsedDataApiResponse) -> None:
            handler(message.get("meta", {}).get("page", {}).get("totalRecords", 0))

        self.get_parsed(query, handle)


class PlayerEventApiAccessor(DataApiAccessor):
    events_ready = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__("/data/playerEvent")

    def get_player_events(self, player_id: str) -> None:
        query: QueryOptions = {
            "include": "event",
            "filter": f"player.id=={player_id}",
        }
        self.get_parsed(query, self.handle_player_events)

    def handle_player_events(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        self.events_ready.emit([PlayerEvent(**entry) for entry in message["data"]])


class PlayerAchievementApiAccessor(DataApiAccessor):
    achievments_ready = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__("/data/playerAchievement")

    def get_achievements(self, player_id: str | int) -> None:
        query: QueryOptions = {
            "include": "achievement",
            "filter": f"player.id=={player_id}",
            "sort": "achievement.order",
        }
        self.get_parsed(query, self.handle_achievements)

    def handle_achievements(self, message: ParsedDataApiResponse) -> None:
        assert isinstance(message["data"], list)
        self.achievments_ready.emit(PlayerAchievement(**entry) for entry in message["data"])


class AchievementsApiAccessor(DataApiAccessor):
    def __init__(self) -> None:
        super().__init__("/data/achievement")

    def convert_parsed(
        self,
        parsed: ParsedDataApiResponse,
    ) -> dict[str, Iterator[Achievement]]:
        assert isinstance(parsed["data"], list)
        return {"values": (Achievement(**entry) for entry in parsed["data"])}
