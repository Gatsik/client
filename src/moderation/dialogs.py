from collections.abc import Iterable

from PyQt6.QtCore import QPoint
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtCore import Qt
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QAbstractItemView
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QDialog
from PyQt6.QtWidgets import QDialogButtonBox
from PyQt6.QtWidgets import QFormLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtWidgets import QMenu
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QTableWidget
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from src import util
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import ReplyGroup
from src.api.ApiBase import api_error_text
from src.api.models.ModerationReport import ModerationReport
from src.api.moderation_report_api import ModerationReportApiConnector
from src.api.player_api import PlayerApiConnector
from src.playercard.playerloginedit import PlayerLoginEdit


class ReportDialog(QDialog):
    submitted = pyqtSignal()

    def __init__(
        self,
        reporter_id: int,
        parent: QWidget | None = None,
        logins: Iterable[str] = (),
        game_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Report players")
        self.resize(520, 520)
        self.reporter_id = reporter_id
        self.player_api = PlayerApiConnector()
        self.report_api = ModerationReportApiConnector()
        self.replies = ReplyGroup(self)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Reports are reviewed by the moderation team. Please describe what happened "
            "as precisely as possible and include the game ID and time if it happened in a game.",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        layout.addLayout(form)

        self.login_edit = PlayerLoginEdit(self)
        self.login_edit.login_chosen.connect(self.add_player)
        add_button = QPushButton("Add")
        add_button.clicked.connect(lambda: self.add_player(self.login_edit.text()))
        login_row = QHBoxLayout()
        login_row.addWidget(self.login_edit)
        login_row.addWidget(add_button)
        form.addRow("Reported players:", login_row)

        self.players_list = QListWidget(self)
        self.players_list.setMaximumHeight(90)
        self.players_list.setToolTip("Double-click a player to remove them")
        self.players_list.itemDoubleClicked.connect(
            lambda item: self.players_list.takeItem(self.players_list.row(item)),
        )
        form.addRow("", self.players_list)
        for login in logins:
            self.add_player(login)

        self.game_edit = QLineEdit(self)
        self.game_edit.setPlaceholderText("Optional")
        self.game_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,12}"), self.game_edit),
        )
        if game_id is not None:
            self.game_edit.setText(str(game_id))
        form.addRow("Game ID:", self.game_edit)

        self.timecode_edit = QLineEdit(self)
        self.timecode_edit.setPlaceholderText("Optional, e.g. 00:12:34")
        form.addRow("Time in game:", self.timecode_edit)

        self.description_edit = QPlainTextEdit(self)
        self.description_edit.setPlaceholderText("What happened?")
        form.addRow("Description:", self.description_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Submit report")
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        enter = event is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if not (enter and self.login_edit.hasFocus()):
            super().keyPressEvent(event)

    def logins(self) -> list[str]:
        return [self.players_list.item(row).text() for row in range(self.players_list.count())]

    def add_player(self, login: str) -> None:
        login = login.strip()
        if login and login.casefold() not in map(str.casefold, self.logins()):
            self.players_list.addItem(login)
        self.login_edit.clear()

    def set_busy(self, busy: bool) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDisabled(busy)

    def submit(self) -> None:
        self.add_player(self.login_edit.text())
        logins = self.logins()
        if not logins:
            QMessageBox.warning(self, "Report", "Add at least one player to report.")
            return
        if not self.description_edit.toPlainText().strip():
            QMessageBox.warning(self, "Report", "Please describe what happened.")
            return
        self.set_busy(True)
        self.replies.add(self.player_api.get_ids(logins, self.on_ids, self.on_error))

    def on_ids(self, ids: dict[str, int]) -> None:
        logins = self.logins()
        if missing := [login for login in logins if login.casefold() not in ids]:
            self.set_busy(False)
            QMessageBox.warning(self, "Report", f"Unknown players: {', '.join(missing)}")
            return
        game_text = self.game_edit.text()
        reply = self.report_api.submit_report(
            self.reporter_id,
            [ids[login.casefold()] for login in logins],
            self.description_edit.toPlainText().strip(),
            int(game_text) if game_text else None,
            self.timecode_edit.text().strip(),
            self.on_submitted,
            self.on_error,
        )
        self.replies.add(reply)

    def on_submitted(self, _: ParsedDataApiResponse) -> None:
        self.submitted.emit()
        QMessageBox.information(self, "Report", "Your report has been submitted.")
        self.accept()

    def on_error(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        self.set_busy(False)
        QMessageBox.warning(self, "Failed to submit report", api_error_text(reply))


class ModerationReportsDialog(QDialog):
    COLUMNS = (
        ("Created", 80),
        ("Status", 80),
        ("Reported players", 110),
        ("Game", 110),
        ("Time in game", 85),
        ("Description", None),
        ("Moderator notice", None),
    )

    def __init__(self, reporter_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Moderation reports")
        self.resize(1000, 500)
        self.reporter_id = reporter_id
        self.report_api = ModerationReportApiConnector()
        self.replies = ReplyGroup(self)

        layout = QVBoxLayout(self)
        self.status_label = QLabel(self)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels([name for name, _ in self.COLUMNS])
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header = self.table.horizontalHeader()
        for col, (_, width) in enumerate(self.COLUMNS):
            if width is None:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                self.table.setColumnWidth(col, width)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        new_button = QPushButton("New report")
        new_button.clicked.connect(self.new_report)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(new_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.refresh()

    def show_context_menu(self, pos: QPoint) -> None:
        item = self.table.itemAt(pos)
        clipboard = QApplication.clipboard()
        if item is None or clipboard is None:
            return
        menu = QMenu(self.table)
        menu.addAction("Copy", lambda: clipboard.setText(item.text()))
        menu.exec(self.table.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def new_report(self) -> None:
        dialog = ReportDialog(self.reporter_id, self)
        dialog.submitted.connect(self.refresh)
        dialog.show()

    def refresh(self) -> None:
        self.status_label.setText("Loading reports...")
        reply = self.report_api.request_reports(self.reporter_id, self.show_reports, self.on_error)
        self.replies.add(reply)

    def on_error(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.OperationCanceledError:
            self.status_label.setText(f"Failed to load reports: {api_error_text(reply)}")

    def show_reports(self, reports: list[ModerationReport]) -> None:
        self.status_label.setText(
            f"You have submitted {len(reports)} report(s)." if reports
            else "You have not submitted any reports.",
        )
        self.table.setRowCount(len(reports))
        for row, report in enumerate(reports):
            values = (
                util.utctolocal(report.create_time),
                report.report_status.value.capitalize(),
                ", ".join(player.login for player in report.reported_users or []),
                f"#{report.game.xd} {report.game.name}" if report.game else "",
                report.game_incident_timecode or "",
                report.report_description,
                report.moderator_notice or "",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(row, col, item)
