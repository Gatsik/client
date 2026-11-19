import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QAbstractItemView
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QDialogButtonBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QInputDialog
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QTableWidget
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from src import util
from src.client_import.sources import ClientSource
from src.user_notes.importers import NOTES_PARSERS
from src.user_notes.importers import ConflictResolution
from src.user_notes.importers import ImportPlan
from src.user_notes.importers import NoteConflict
from src.user_notes.importers import NotesImportError
from src.user_notes.importers import plan_import
from src.user_notes.importers import resolve
from src.user_notes.notes import UserNotes

logger = logging.getLogger(__name__)

NameResolver = Callable[[int], str | None]

NOTE_ICON = "client/note.png"


def note_icon() -> QIcon:
    return util.THEME.icon(NOTE_ICON)


def edit_user_note[KT: (int, str)](
    parent: QWidget | None,
    notes: UserNotes[KT],
    key: KT,
    login: str,
) -> None:
    current = notes.get(key) or ""
    text, ok = QInputDialog.getMultiLineText(
        parent,
        "Edit note" if current else "Add note",
        f"Note for {login}:",
        current,
    )
    if ok:
        notes.set(key, text)


class NoteConflictsDialog(QDialog):
    PLAYER_COL, CURRENT_COL, IMPORTED_COL, ACTION_COL = range(4)

    def __init__(
        self,
        source_name: str,
        plan: ImportPlan,
        name_resolver: NameResolver,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import notes from {source_name}")
        self.resize(860, 480)
        self._plan = plan
        self._combos: list[QComboBox] = []

        layout = QVBoxLayout(self)
        summary = QLabel(self._summary_text(plan))
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self.table = QTableWidget(len(plan.conflicts), 4, self)
        self.table.setHorizontalHeaderLabels(["Player", "Current note", "Imported note", "Action"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.PLAYER_COL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.CURRENT_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.IMPORTED_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.ACTION_COL, QHeaderView.ResizeMode.ResizeToContents)

        for row, conflict in enumerate(plan.conflicts):
            self._fill_row(row, conflict, name_resolver)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table)

        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Apply to all:"))
        for resolution in ConflictResolution:
            button = QPushButton(resolution.value)
            button.clicked.connect(lambda _=False, r=resolution: self.set_all(r))
            bulk.addWidget(button)
        bulk.addStretch()
        layout.addLayout(bulk)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _summary_text(plan: ImportPlan) -> str:
        parts = [f"{len(plan.added)} new note(s) will be added."]
        if plan.unchanged:
            parts.append(f"{len(plan.unchanged)} identical note(s) will be skipped.")
        parts.append(
            f"{len(plan.conflicts)} player(s) already have a different note. "
            "Choose what to keep for each of them:",
        )
        return " ".join(parts)

    def _fill_row(self, row: int, conflict: NoteConflict, name_resolver: NameResolver) -> None:
        login = name_resolver(conflict.player_id) or conflict.login
        player = f"{login} ({conflict.player_id})" if login else str(conflict.player_id)
        self.table.setItem(row, self.PLAYER_COL, QTableWidgetItem(player))
        for col, text in (
            (self.CURRENT_COL, conflict.current),
            (self.IMPORTED_COL, conflict.incoming),
        ):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.table.setItem(row, col, item)

        combo = QComboBox()
        for resolution in ConflictResolution:
            combo.addItem(resolution.value, resolution)
        self.table.setCellWidget(row, self.ACTION_COL, combo)
        self._combos.append(combo)

    def set_all(self, resolution: ConflictResolution) -> None:
        for combo in self._combos:
            combo.setCurrentIndex(combo.findData(resolution))

    def resolutions(self) -> list[ConflictResolution]:
        return [combo.currentData() for combo in self._combos]

    def resolved_notes(self) -> dict[int, str]:
        return {
            conflict.player_id: resolve(conflict, resolution)
            for conflict, resolution in zip(self._plan.conflicts, self.resolutions())
        }


class UserNotesImporter:
    id = "user_notes"
    title = "User notes"

    def __init__(self, notes: UserNotes, name_resolver: NameResolver) -> None:
        self._notes = notes
        self._name_resolver = name_resolver
        self._parent: QWidget | None = None

    def supports(self, source: ClientSource) -> bool:
        return source.id in NOTES_PARSERS

    def import_from(self, source: ClientSource, path: str, parent: QWidget | None) -> None:
        self._parent = parent
        try:
            self.import_file(source, path)
        finally:
            self._parent = None

    def import_file(self, source: ClientSource, path: str) -> None:
        title = f"Import notes from {source.name}"
        try:
            incoming = NOTES_PARSERS[source.id](path)
        except NotesImportError as e:
            logger.warning("Failed to import notes from %s: %s", path, e)
            QMessageBox.warning(self._parent, title, str(e))
            return

        if not incoming:
            QMessageBox.information(self._parent, title, "No notes were found in this file.")
            return

        plan = plan_import(self._notes.all(), incoming)
        if plan.is_empty:
            QMessageBox.information(
                self._parent, title, "All notes from this file are already present.",
            )
            return

        resolved: dict[int, str] = {}
        if plan.conflicts:
            dialog = NoteConflictsDialog(source.name, plan, self._name_resolver, self._parent)
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                resolved = dialog.resolved_notes()
            finally:
                dialog.deleteLater()

        to_write = {pid: note.text for pid, note in plan.added.items()}
        updated = 0
        for pid, text in resolved.items():
            if text != self._notes.get(pid):
                to_write[pid] = text
                updated += 1
        self._notes.update_many(to_write)
        logger.info(
            "Imported notes from %s: %d added, %d updated", path, len(plan.added), updated,
        )

        QMessageBox.information(
            self._parent,
            title,
            f"Added {len(plan.added)} note(s), updated {updated} note(s).",
        )
