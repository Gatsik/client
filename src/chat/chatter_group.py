from enum import Enum

from PyQt6.QtCore import QObject

from src.qt.models.qtlistmodel import QtListModelItem


class ChatterGroup(Enum):
    FRIENDS = "Friends"
    MODERATORS = "Moderators"
    CLAN = "Clan"
    PLAYERS = "Players"
    IRC = "IRC users"
    CHATTERBOXES = "Chatterboxes"
    FOES = "Foes"
    AWAY = "Away"


class ChatterGroupItem(QtListModelItem):
    def __init__(self, group: ChatterGroup) -> None:
        QObject.__init__(self)
        self.group = group
        self.count = 0

    def tooltip(self) -> None:
        return None
