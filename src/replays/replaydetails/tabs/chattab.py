from collections.abc import Generator
from collections.abc import Sequence
from typing import Any
from typing import cast

from PyQt6.QtCore import QAbstractTableModel
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QButtonGroup
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMenu
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QTableView
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from src.config import Settings
from src.replays.replaydetails.helpers import seconds_to_human
from src.replays.replaydetails.replayreader import ReplayParser


class ChatTableModel(QAbstractTableModel):
    def __init__(self, chat_lines: Sequence[tuple[int, str, str, str, int]]) -> None:
        super().__init__()
        self.chat_lines = chat_lines
        self._horizontal_header = ("Time", "From", "To", "Message")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.chat_lines)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._horizontal_header)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._horizontal_header[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = 0) -> str | None:
        row = index.row()
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return str(seconds_to_human(self.chat_lines[row][column] // 10))
            return cast(str, self.chat_lines[row][column])


class ChatTabUI:
    def setupUi(self, widget: QWidget) -> None:
        layout = QVBoxLayout(widget)

        search_layout = QHBoxLayout()

        self.searchInput = QLineEdit()
        self.searchInput.setPlaceholderText("Search text...")

        self.clearButton = QPushButton("Clear")

        search_layout.addWidget(self.searchInput)
        search_layout.addWidget(self.clearButton)

        search_layout.addStretch()

        search_layout.addWidget(QLabel("Show messages to: "))

        self.toAllCheckBox = QCheckBox("all")
        self.toAlliesCheckBox = QCheckBox("allies")
        self.toNotifyCheckBox = QCheckBox("notify")
        self.toEnemiesCheckBox = QCheckBox("enemies")
        self.toPrivateCheckBox = QCheckBox("private")

        for btn in (
            self.toAllCheckBox,
            self.toAlliesCheckBox,
            self.toNotifyCheckBox,
            self.toEnemiesCheckBox,
            self.toPrivateCheckBox,
        ):
            search_layout.addWidget(btn)
        search_layout.addStretch()

        self.alternateColorsCheckBox = QCheckBox("Alternate row colors")
        search_layout.addWidget(self.alternateColorsCheckBox)
        layout.addLayout(search_layout)

        self.chatTable = QTableView()
        self.chatTable.setVerticalScrollMode(self.chatTable.ScrollMode.ScrollPerPixel)
        self.chatTable.setEditTriggers(self.chatTable.EditTrigger.NoEditTriggers)
        self.chatTable.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.chatTable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.chatTable.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.chatTable)


class ChatTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.ui = ChatTabUI()
        self.ui.setupUi(self)
        self.ui.searchInput.textChanged.connect(self.search)
        self.ui.searchInput.returnPressed.connect(self.search_next)
        self.ui.clearButton.clicked.connect(self.ui.searchInput.clear)
        self.ui.chatTable.doubleClicked.connect(self.on_chat_item_double_clicked)
        self.ui.chatTable.pressed.connect(self.on_chat_item_clicked)

        self.alternate_row_colors = Settings.get(
            "replaycard.chat/alternate_row_colors",
            default=True,
            type=bool,
        )
        self.ui.alternateColorsCheckBox.setChecked(self.alternate_row_colors)
        self.ui.chatTable.setAlternatingRowColors(self.alternate_row_colors)
        self.ui.alternateColorsCheckBox.checkStateChanged.connect(self.on_row_colors_alternation)

        self.message_filters = QButtonGroup()
        self.message_filters.setExclusive(False)
        for index, chbx in enumerate(
            (
                self.ui.toAllCheckBox,
                self.ui.toAlliesCheckBox,
                self.ui.toNotifyCheckBox,
                self.ui.toEnemiesCheckBox,
                self.ui.toPrivateCheckBox,
            ),
        ):
            self.message_filters.addButton(chbx, index)

        self.visible_recipients = Settings.get_list(
            "replaycard.chat/visible_recipients",
            default=[True] * 5,
            type=bool,
        )
        for index, btn in enumerate(self.message_filters.buttons()):
            try:
                btn.setChecked(self.visible_recipients[index])
            except IndexError:
                btn.setChecked(True)
                self.visible_recipients.append(True)

        self.message_filters.buttonToggled.connect(self.on_message_filter_changed)
        self._buttons_by_text = {btn.text(): btn for btn in self.message_filters.buttons()}

        self._search_index = 0
        self._matching_indexes: list[QModelIndex] = []

        self.chat_lines: list[tuple[int, str, str, str, int]] = []

    def initialize(self, parser: ReplayParser) -> None:
        self.chat_lines = parser.chatLine
        self.ui.searchInput.clear()
        model = ChatTableModel(self.chat_lines)
        self.ui.chatTable.setModel(model)

        for row, line in enumerate(self.chat_lines):
            hide = not self.visible_recipients[self._filter_id(line[2])]
            self.ui.chatTable.setRowHidden(row, hide)

    def _filter_id(self, recipient: str) -> int:
        if recipient in ("all", "allies", "notify", "enemies"):
            return self.message_filters.id(self._buttons_by_text[recipient])
        return self.message_filters.id(self.ui.toPrivateCheckBox)

    def _reset_search(self) -> None:
        self.ui.chatTable.setCurrentIndex(QModelIndex())
        self._matching_indexes.clear()
        self._search_index = 0

    def search(self, text: str) -> None:
        self._reset_search()

        if not text:
            return

        model = cast(ChatTableModel, self.ui.chatTable.model())
        self._matching_indexes = [
            index
            for column in range(model.columnCount())
            for index in model.match(
                model.index(0, column),
                Qt.ItemDataRole.DisplayRole,
                text,
                -1,
                Qt.MatchFlag.MatchContains,
            )
            if not self.ui.chatTable.isRowHidden(index.row())
        ]
        if self._matching_indexes:
            self.ui.chatTable.setCurrentIndex(self._matching_indexes[0])

    def search_next(self) -> None:
        if not self._matching_indexes:
            if text := self.ui.searchInput.text():
                self.search(text)
            return
        modifiers = QApplication.keyboardModifiers()
        self._search_index += -1 if modifiers == Qt.KeyboardModifier.ShiftModifier else 1
        index = self._matching_indexes[self._search_index % len(self._matching_indexes)]
        self.ui.chatTable.setCurrentIndex(index)

    def on_message_filter_changed(self, button: QCheckBox) -> None:
        button_id = self.message_filters.id(button)
        self.visible_recipients[button_id] = button.isChecked()
        for row in range(len(self.chat_lines)):
            if self._filter_id(self.chat_lines[row][2]) == button_id:
                self.ui.chatTable.setRowHidden(row, not button.isChecked())
        self._reset_search()

    def on_row_colors_alternation(self, state: Qt.CheckState) -> None:
        alternate = state == Qt.CheckState.Checked
        self.ui.chatTable.setAlternatingRowColors(alternate)
        self.alternate_row_colors = alternate

    def save_settings(self) -> None:
        Settings.set("replaycard.chat/visible_recipients", self.visible_recipients)
        Settings.set("replaycard.chat/alternate_row_colors", self.alternate_row_colors)

    def on_chat_item_double_clicked(self, index: QModelIndex) -> None:
        if QApplication.mouseButtons() != Qt.MouseButton.LeftButton:
            return
        text_dialog = QDialog(self)
        timing, sender_login, to, *_ = self.chat_lines[index.row()]
        title = f"[{seconds_to_human(timing // 10)}] {sender_login} to {to}"
        text_dialog.setWindowTitle(title)
        layout = QVBoxLayout(text_dialog)
        text_edit = QTextEdit(index.data(Qt.ItemDataRole.DisplayRole))
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        text_dialog.exec()
        text_dialog.deleteLater()

    def copy_text_in_selection(self) -> None:
        def _selected_text() -> Generator[str]:
            selection = self.ui.chatTable.selectedIndexes()
            if not selection:
                return
            for i, model_index in enumerate(selection[:-1]):
                text = model_index.data(Qt.ItemDataRole.DisplayRole)
                if selection[i + 1].row() > model_index.row():
                    yield f"{text}\n"
                else:
                    yield f"{text};"
            yield selection[-1].data(Qt.ItemDataRole.DisplayRole)

        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText("".join(_selected_text()))

    def on_chat_item_clicked(self, _: QModelIndex) -> None:
        if QApplication.mouseButtons() != Qt.MouseButton.RightButton:
            return
        menu = QMenu(self.ui.chatTable)
        action = QAction("Copy text", menu)
        action.triggered.connect(self.copy_text_in_selection)
        menu.addAction(action)
        menu.popup(QCursor.pos())
