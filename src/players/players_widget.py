from PyQt6.QtCore import QByteArray
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QPoint
from PyQt6.QtCore import QSize
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMenu
from PyQt6.QtWidgets import QStyledItemDelegate
from PyQt6.QtWidgets import QStyleOptionViewItem
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from src.chat.chat_controller import ChatController
from src.config import Settings
from src.contextmenu.playercontextmenu import PlayerContextMenu
from src.fa.game_runner import GameRunner
from src.model.chat.chatterset import Chatterset
from src.players.players_model import GAME_COLUMNS
from src.players.players_model import HEADER_TOOLTIPS
from src.players.players_model import HEADERS
from src.players.players_model import Column
from src.players.players_model import PlayersFilterModel
from src.players.players_model import RelationFilter
from src.players.players_model import StatusFilter
from src.qt.itemviews.tableitemdelegte import TableItemDelegate
from src.qt.itemviews.tableview import TableView

HEADER_STATE_KEY = "players/header_state"

STRETCH_COLUMNS = (Column.NAME, Column.MAP, Column.GAME)
ICON_PADDING = 8


class RowHoverDelegate(TableItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = self._customize_style_option(option, index)
        QStyledItemDelegate.paint(self, painter, opt, index)


class PlayersWidget(QWidget):
    private_chat_opened = pyqtSignal()

    def __init__(
        self,
        model: PlayersFilterModel,
        context_menu: PlayerContextMenu,
        game_runner: GameRunner,
        chat_controller: ChatController,
        chatters: Chatterset,
    ) -> None:
        super().__init__()
        self._model = model
        self._context_menu = context_menu
        self._game_runner = game_runner
        self._chat_controller = chat_controller
        self._chatters = chatters

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search player or clan...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(model.set_text)

        self._relation = self._combo(RelationFilter, model.set_relation)
        self._status = self._combo(StatusFilter, model.set_status)
        self._count = QLabel()

        filters = QHBoxLayout()
        filters.addWidget(self._search, 1)
        filters.addWidget(self._relation)
        filters.addWidget(self._status)
        filters.addStretch(1)
        filters.addWidget(self._count)

        self._table = self._make_table()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filters)
        layout.addWidget(self._table)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_header_state)
        self._restore_header_state()
        header = self._table.horizontalHeader()
        header.sectionMoved.connect(self._save_timer.start)
        header.sortIndicatorChanged.connect(self._save_timer.start)

        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.timeout.connect(self._update_count)
        changes = (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged)
        for signal in changes:
            signal.connect(self._count_timer.start)
        self._update_count()

    @staticmethod
    def _combo(options, setter) -> QComboBox:
        combo = QComboBox()
        for option in options:
            combo.addItem(option.value, option)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        view = combo.view()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setMinimumWidth(view.sizeHintForColumn(0) + 2 * view.frameWidth() + 16)
        combo.currentIndexChanged.connect(lambda _: setter(combo.currentData()))
        return combo

    def _make_table(self) -> TableView:
        table = TableView()
        table.setModel(self._model)
        table.setItemDelegate(RowHoverDelegate(table))
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setIconSize(QSize(40, 20))
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.setVerticalScrollMode(table.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(table.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setDefaultSectionSize(24)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_player_menu)
        table.doubleClicked.connect(self._at_double_clicked)

        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        header.setResizeContentsPrecision(100)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        table.sortByColumn(Column.NAME, Qt.SortOrder.AscendingOrder)
        return table

    def _update_count(self) -> None:
        total = self._model.source().player_count()
        shown = self._model.rowCount()
        text = f"{total} players online"
        if shown != total:
            text += f", {shown} shown"
        self._count.setText(text)

    def _show_player_menu(self, pos: QPoint) -> None:
        player = self._model.player_at(self._table.indexAt(pos))
        if player is None:
            return
        menu = self._context_menu.get_context_menu(player.login, player.id)
        menu.popup(self._table.viewport().mapToGlobal(pos))

    def _show_header_menu(self, pos: QPoint) -> None:
        header = self._table.horizontalHeader()
        menu = QMenu(self)
        for column in Column:
            action = QAction(HEADERS[column] or HEADER_TOOLTIPS[column], menu)
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(column))
            action.toggled.connect(lambda checked, c=column: self._set_column_visible(c, checked))
            menu.addAction(action)
        menu.popup(header.mapToGlobal(pos))

    def _set_column_visible(self, column: Column, visible: bool) -> None:
        self._table.horizontalHeader().setSectionHidden(column, not visible)
        self._save_header_state()

    def _at_double_clicked(self, index: QModelIndex) -> None:
        player = self._model.player_at(index)
        if player is None:
            return
        game = player.currentGame
        if index.column() in GAME_COLUMNS:
            if game is not None and not game.closed():
                self._game_runner.run_game_with_url(game, player.id)
        elif player.login in self._chatters:
            self._chat_controller.join_private_channel(player.login)
            self.private_chat_opened.emit()

    def _save_header_state(self) -> None:
        Settings.set(HEADER_STATE_KEY, self._table.horizontalHeader().saveState())

    def _restore_header_state(self) -> None:
        header = self._table.horizontalHeader()
        state = Settings.get(HEADER_STATE_KEY, type=QByteArray)
        if state:
            header.restoreState(state)
        header.setStretchLastSection(False)
        Mode = QHeaderView.ResizeMode
        for column in Column:
            mode = Mode.Stretch if column in STRETCH_COLUMNS else Mode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        icon_size = self._table.iconSize()
        fixed_widths = {
            Column.COUNTRY: icon_size.height() + ICON_PADDING,
            Column.AVATAR: icon_size.width() + ICON_PADDING,
        }
        header.setMinimumSectionSize(min(fixed_widths.values()))
        for column, width in fixed_widths.items():
            header.setSectionResizeMode(column, Mode.Fixed)
            header.resizeSection(column, width)
