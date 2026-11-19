from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import NamedTuple
from typing import NotRequired
from typing import TypedDict

from src.client_import.sources import DOWNLORDS_CLIENT
from src.client_import.sources import RUST_CLIENT
from src.client_import.sources import ClientImportError
from src.client_import.sources import read_json
from src.user_notes.notes import UserNotes

NotesImportError = ClientImportError


class DownlordsUserPrefs(TypedDict):
    notesByPlayerId: NotRequired[dict[str, str]]


class DownlordsPrefs(TypedDict):
    user: NotRequired[DownlordsUserPrefs]


class RustPlayerNote(TypedDict):
    playerId: int
    login: str
    note: str


class RustSocialPreferences(TypedDict):
    playerNotes: NotRequired[list[RustPlayerNote]]


class RustSettings(TypedDict):
    social: NotRequired[RustSocialPreferences]


class ImportedNote(NamedTuple):
    player_id: int
    text: str
    login: str | None = None


class NoteConflict(NamedTuple):
    player_id: int
    current: str
    incoming: str
    login: str | None = None


@dataclass
class ImportPlan:
    added: dict[int, ImportedNote] = field(default_factory=dict)
    unchanged: list[int] = field(default_factory=list)
    conflicts: list[NoteConflict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.conflicts


class ConflictResolution(Enum):
    KEEP_CURRENT = "Keep current"
    USE_IMPORTED = "Use imported"
    MERGE = "Merge both"


def merge_notes(current: str, incoming: str) -> str:
    if incoming in current:
        return current
    if current in incoming:
        return incoming
    return f"{current}\n{incoming}"


def resolve(conflict: NoteConflict, resolution: ConflictResolution) -> str:
    if resolution is ConflictResolution.USE_IMPORTED:
        return conflict.incoming
    if resolution is ConflictResolution.MERGE:
        return merge_notes(conflict.current, conflict.incoming)
    return conflict.current


def plan_import(current: Mapping[int, str], incoming: Mapping[int, ImportedNote]) -> ImportPlan:
    plan = ImportPlan()
    for player_id, note in sorted(incoming.items()):
        existing = current.get(player_id)
        if existing is None:
            plan.added[player_id] = note
        elif existing == note.text:
            plan.unchanged.append(player_id)
        else:
            plan.conflicts.append(NoteConflict(player_id, existing, note.text, note.login))
    return plan


def _add_note(
    result: dict[int, ImportedNote],
    raw_id: int | str,
    raw_text: str,
    login: str | None = None,
) -> None:
    try:
        player_id = int(raw_id)
    except (TypeError, ValueError):
        return
    if player_id <= 0 or not isinstance(raw_text, str):
        return
    text = UserNotes.normalize(raw_text)
    if not text:
        return
    result[player_id] = ImportedNote(
        player_id, text, login if isinstance(login, str) and login else None,
    )


def parse_downlords(path: str) -> dict[int, ImportedNote]:
    data: DownlordsPrefs = read_json(path)
    if not isinstance(data, dict):
        raise NotesImportError(
            "Unexpected file format: not a Downlord's FAF Client preferences file",
        )
    user = data.get("user")
    notes = user.get("notesByPlayerId") if isinstance(user, dict) else None
    result: dict[int, ImportedNote] = {}
    if notes is None:
        return result
    if not isinstance(notes, dict):
        raise NotesImportError("Unexpected format of 'user.notesByPlayerId'")
    for raw_id, raw_text in notes.items():
        _add_note(result, raw_id, raw_text)
    return result


def parse_rust_client(path: str) -> dict[int, ImportedNote]:
    data: RustSettings = read_json(path)
    if not isinstance(data, dict):
        raise NotesImportError("Unexpected file format: not a FAForever Rust Client settings file")
    social = data.get("social")
    notes = social.get("playerNotes") if isinstance(social, dict) else None
    result: dict[int, ImportedNote] = {}
    if notes is None:
        return result
    if not isinstance(notes, list):
        raise NotesImportError("Unexpected format of 'social.playerNotes'")
    for entry in notes:
        if isinstance(entry, dict):
            _add_note(
                result, entry.get("playerId", 0), entry.get("note", ""), entry.get("login"),
            )
    return result


NOTES_PARSERS: dict[str, Callable[[str], dict[int, ImportedNote]]] = {
    DOWNLORDS_CLIENT.id: parse_downlords,
    RUST_CLIENT.id: parse_rust_client,
}
