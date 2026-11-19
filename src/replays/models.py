from collections.abc import Callable

from pydantic import BaseModel
from pydantic import Field
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from src import util
from src.api.models.Player import Player
from src.model.rating import Rating
from src.qt.models.qtlistmodel import QtListModel
from src.qt.models.qtlistmodel import QtListModelItem
from src.user_notes.notes import UserNotes


# FIXME - this is what the widget uses so far, we should define this
# schema precisely in the future
class MetadataModel(BaseModel):
    uid: int
    complete: bool = Field(False)
    featured_mod: str | None
    launched_at: float
    mapname: str
    num_players: int
    teams: dict[str, list[str]]
    title: str
    game_time: float = Field(0.0)


class ScoreboardModelItem(QtListModelItem):
    def __init__(
        self,
        replay_data: dict,
        mod: str | None,
        user_notes: UserNotes | None = None,
    ) -> None:
        super().__init__()
        self.replay_data = replay_data
        self.mod = mod or ""
        self._user_notes = user_notes
        self.player = Player(**replay_data["player"])
        if len(self.replay_data["ratingChanges"]) > 0:
            self.rating_stats = self.replay_data["ratingChanges"][0]
        else:
            self.rating_stats = None

    @classmethod
    def builder(
        cls,
        mod: str | None,
        user_notes: UserNotes | None = None,
    ) -> Callable[[dict], ScoreboardModelItem]:
        def build(data: dict) -> ScoreboardModelItem:
            return cls(data, mod, user_notes)
        return build

    def player_id(self) -> int:
        return int(self.player.xd)

    def note(self) -> str | None:
        if self._user_notes is None:
            return None
        return self._user_notes.get(self.player_id())

    def score(self) -> int:
        return self.replay_data["score"]

    def login(self) -> str:
        return self.player.login

    def rating_before(self) -> int:
        # gamePlayerStats' fields 'before*' and 'after*' can be removed
        # at any time and 'ratingChanges' can be absent if game result is
        # undefined
        if self.rating_stats is not None:
            rating = Rating(
                self.rating_stats["meanBefore"],
                self.rating_stats["deviationBefore"],
            )
            return round(rating.displayed())
        elif self.replay_data.get("beforeMean") and self.replay_data.get("beforeDeviation"):
            rating = Rating(
                self.replay_data["beforeMean"],
                self.replay_data["beforeDeviation"],
            )
            return round(rating.displayed())
        return 0

    def rating_after(self) -> int:
        if self.rating_stats is not None:
            rating = Rating(
                self.rating_stats["meanAfter"],
                self.rating_stats["deviationAfter"],
            )
            return round(rating.displayed())
        elif self.replay_data.get("afterMean") and self.replay_data.get("afterDeviation"):
            rating = Rating(
                self.replay_data["afterMean"],
                self.replay_data["afterDeviation"],
            )
            return round(rating.displayed())
        return 0

    def rating(self) -> int | None:
        if self.rating_stats is None and "beforeMean" not in self.replay_data:
            return None
        return self.rating_before()

    def rating_change(self) -> int:
        if self.rating_stats is None:
            return 0
        return self.rating_after() - self.rating_before()

    def faction_name(self) -> str:
        if "faction" in self.replay_data:
            if self.replay_data["faction"] == 1:
                faction = "UEF"
            elif self.replay_data["faction"] == 2:
                faction = "Aeon"
            elif self.replay_data["faction"] == 3:
                faction = "Cybran"
            elif self.replay_data["faction"] == 4:
                faction = "Seraphim"
            elif self.replay_data["faction"] == 5:
                if self.mod == "nomads":
                    faction = "Nomads"
                else:
                    faction = "Random"
            elif self.replay_data["faction"] == 6:
                if self.mod == "nomads":
                    faction = "Random"
                else:
                    faction = "broken"
            else:
                faction = "broken"
        else:
            faction = "Missing"
        return faction

    def icon(self) -> QIcon:
        return util.THEME.icon(f"replays/{self.faction_name()}.png")

    def tooltip(self) -> str | None:
        return self.note()


class ScoreboardModel(QtListModel[dict, ScoreboardModelItem]):
    def __init__(
            self,
            spoiled: bool,
            alignment: Qt.AlignmentFlag,
            item_builder: Callable[[dict], ScoreboardModelItem],
    ) -> None:
        super().__init__(item_builder)
        self.spoiled = spoiled
        self.alignment = alignment

    def get_alignment(self) -> Qt.AlignmentFlag:
        return self.alignment

    def add_player(self, player: dict) -> None:
        self._add_item(player, player["player"]["id"])
