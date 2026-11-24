from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QMouseEvent

from src.qt.itemviews.tableview import TableView
from src.stats.models.leagueleaderboardtablemodel import Column

if TYPE_CHECKING:
    from src.client._clientwindow import ClientWindow


class LeagueTableView(TableView):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.client: ClientWindow | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.RightButton:
            TableView.mousePressEvent(self, event)
            return

        row = self.indexAt(event.pos()).row()
        if row != -1 and self.client is not None:
            model = self.model()
            name = model.data(model.index(row, Column.NAME))
            uid = int(model.data(model.index(row, Column.ID)))
            self.selectRow(row)
            menu = self.client.player_ctx_menu.get_context_menu(name, uid)
            menu.popup(QCursor.pos())
        self.update_hover_row(event)
        self.verticalHeader().update_hover_section(event)
