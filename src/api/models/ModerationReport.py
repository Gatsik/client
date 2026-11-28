from enum import Enum

from pydantic import Field

from src.api.models.AbstractEntity import AbstractEntity
from src.api.models.Game import Game
from src.api.models.Player import Player


class ModerationReportStatus(Enum):
    AWAITING = "AWAITING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    DISCARDED = "DISCARDED"


class ModerationReport(AbstractEntity):
    report_description:     str                    = Field(alias="reportDescription")
    report_status:          ModerationReportStatus = Field(alias="reportStatus")
    game_incident_timecode: str | None             = Field(None, alias="gameIncidentTimecode")
    moderator_notice:       str | None             = Field(None, alias="moderatorNotice")

    reporter:               Player | None          = Field(None)
    last_moderator:         Player | None          = Field(None, alias="lastModerator")
    game:                   Game | None            = Field(None)
    reported_users:         list[Player] | None    = Field(None, alias="reportedUsers")
