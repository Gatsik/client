from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from PyQt6.QtCore import QAbstractTableModel
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtCore import Qt

SORT_ROLE = Qt.ItemDataRole.UserRole


class Column(IntEnum):
    NAME = 0
    DIVISION = 1
    SCORE = 2
    GAMES = 3
    RETURNING = 4
    ID = 5


@dataclass
class LeagueEntry:
    player_id: str
    score: int
    games: int
    returning: bool
    division: str = ""
    division_rank: int = 0
    login: str | None = None


class LeagueLeaderboardTableModel(QAbstractTableModel):
    HEADERS = ("Name", "Division", "Score", "Games", "Returning player", "Player Id")

    def __init__(self, entries: list[LeagueEntry], offset: int = 0) -> None:
        super().__init__()
        self.entries = entries
        self.offset = offset
        self.header_tooltips: dict[int, str] = {}

    def set_placement_games(self, new_players: int, returning_players: int) -> None:
        self.header_tooltips[Column.RETURNING] = (
            "Player who had a league rank in a previous season.\n"
            f"Returning players are placed into a division after {returning_players} games,\n"
            f"new players after {new_players}."
        )

    @classmethod
    def from_api(
        cls,
        data: list[dict[str, Any]],
        offset: int,
        divisions: dict[str, tuple[str, int]],
    ) -> LeagueLeaderboardTableModel:
        return cls(
            [
                LeagueEntry(
                    str(item["loginId"]),
                    item["score"],
                    item["gameCount"],
                    bool(item.get("returningPlayer")),
                    *divisions[item["leagueSeasonDivisionSubdivision"]["id"]],
                ) for item in data
            ],
            offset,
        )

    @property
    def logins(self) -> list[str]:
        return [entry.login for entry in self.entries if entry.login is not None]

    @property
    def player_ids(self) -> list[str]:
        return [entry.player_id for entry in self.entries]

    def row_of_player(self, player_id: str) -> int:
        for row, entry in enumerate(self.entries):
            if entry.player_id == player_id:
                return row
        return -1

    def set_logins(self, logins: dict[str, str]) -> None:
        for row, entry in enumerate(self.entries):
            if entry.player_id in logins:
                entry.login = logins[entry.player_id]
                index = self.index(row, Column.NAME)
                self.dataChanged.emit(index, index)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        match role, orientation:
            case Qt.ItemDataRole.DisplayRole, Qt.Orientation.Horizontal:
                return self.HEADERS[section]
            case Qt.ItemDataRole.DisplayRole, Qt.Orientation.Vertical:
                return str(self.offset + section + 1)
            case Qt.ItemDataRole.TextAlignmentRole, _:
                return Qt.AlignmentFlag.AlignCenter
            case Qt.ItemDataRole.ToolTipRole, Qt.Orientation.Horizontal:
                return self.header_tooltips.get(section)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.display_value(entry, index.column())
        if role == SORT_ROLE:
            return self.sort_value(entry, index.column())
        return None

    @staticmethod
    def display_value(entry: LeagueEntry, column: int) -> str | None:
        match column:
            case Column.NAME:
                return entry.login if entry.login is not None else f"<id: {entry.player_id}>"
            case Column.DIVISION:
                return entry.division
            case Column.SCORE:
                return str(entry.score)
            case Column.GAMES:
                return str(entry.games)
            case Column.RETURNING:
                return "Yes" if entry.returning else "No"
            case Column.ID:
                return entry.player_id
        return None

    @staticmethod
    def sort_value(entry: LeagueEntry, column: int) -> Any:
        match column:
            case Column.NAME:
                return (entry.login or "").lower()
            case Column.DIVISION:
                return (entry.division_rank, entry.score)
            case Column.SCORE:
                return entry.score
            case Column.GAMES:
                return entry.games
            case Column.RETURNING:
                return int(entry.returning)
            case Column.ID:
                return int(entry.player_id)
        return None


class LeagueLeaderboardFilterModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(SORT_ROLE)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        assert model is not None
        return model.data(left, SORT_ROLE) < model.data(right, SORT_ROLE)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        return self.sourceModel().headerData(section, orientation, role)
