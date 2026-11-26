from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QEvent
from PyQt6.QtCore import QMimeData
from PyQt6.QtCore import QPoint
from PyQt6.QtCore import QRect
from PyQt6.QtCore import QRectF
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import pyqtProperty
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtGui import QPainter
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtGui import QTextCursor
from PyQt6.QtGui import QTextFrame
from PyQt6.QtWidgets import QMenu
from PyQt6.QtWidgets import QTextBrowser
from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class ChatAreaEntry:
    payload: object | None
    plain_text: str
    replyable: bool = False


class ChatArea(QTextBrowser):
    reply_requested = pyqtSignal(object)
    menu_requested = pyqtSignal(QMenu, object)

    FLASH_DURATION = 1500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document().setUndoRedoEnabled(False)
        self.viewport().setMouseTracking(True)
        self._default_cursor = self.viewport().cursor()
        self._entries: deque[ChatAreaEntry] = deque()
        self._mouse_pos: QPoint | None = None
        self._hover_key: int | None = None
        self._hover_index: int | None = None
        self._flash_index: int | None = None
        self._menu_index: int | None = None
        self._pressed_button = False
        self._over_button = False
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._stop_flash)

        self._hover_color = QColor(255, 255, 255, 18)
        self._flash_color = QColor(255, 255, 0, 45)
        self._button_color = QColor(60, 60, 60)
        self._button_text_color = QColor(220, 220, 220)

    def _set_color(self, attr: str, color: QColor) -> None:
        setattr(self, attr, QColor(color))
        self.viewport().update()

    @pyqtProperty(QColor)
    def hoverColor(self) -> QColor:
        return self._hover_color

    @hoverColor.setter
    def hoverColor(self, color: QColor) -> None:
        self._set_color("_hover_color", color)

    @pyqtProperty(QColor)
    def flashColor(self) -> QColor:
        return self._flash_color

    @flashColor.setter
    def flashColor(self, color: QColor) -> None:
        self._set_color("_flash_color", color)

    @pyqtProperty(QColor)
    def replyButtonColor(self) -> QColor:
        return self._button_color

    @replyButtonColor.setter
    def replyButtonColor(self, color: QColor) -> None:
        self._set_color("_button_color", color)

    @pyqtProperty(QColor)
    def replyButtonTextColor(self) -> QColor:
        return self._button_text_color

    @replyButtonTextColor.setter
    def replyButtonTextColor(self, color: QColor) -> None:
        self._set_color("_button_text_color", color)

    def append_entry(self, html: str, entry: ChatAreaEntry) -> None:
        self.append(html)
        self._entries.append(entry)

    def remove_entries(self, number: int) -> None:
        doc = self.document()
        frames = doc.rootFrame().childFrames()
        if number <= 0 or not frames:
            return
        cursor = QTextCursor(doc)
        if number < len(frames):
            cursor.setPosition(frames[number].firstPosition() - 1, QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        for _ in range(min(number, len(self._entries))):
            self._entries.popleft()
        self._invalidate()
        if self._menu_index is not None:
            self._menu_index = self._menu_index - number if self._menu_index >= number else None
        if self._flash_index is not None:
            self._flash_index -= number
            if self._flash_index < 0:
                self._stop_flash()

    def clear_entries(self) -> None:
        self.document().setHtml("")
        self._entries.clear()
        self._invalidate()
        self._menu_index = None
        self._stop_flash()

    def entries(self) -> deque[ChatAreaEntry]:
        return self._entries

    def flash_entry(self, index: int) -> None:
        frames = self.document().rootFrame().childFrames()
        if not 0 <= index < len(frames):
            return
        rect = self.document().documentLayout().frameBoundingRect(frames[index])
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(int(rect.center().y() - self.viewport().height() / 2))
        self._flash_index = index
        self._flash_timer.start(self.FLASH_DURATION)
        self.viewport().update()

    def _stop_flash(self) -> None:
        self._flash_index = None
        self._flash_timer.stop()
        self.viewport().update()

    def _invalidate(self) -> None:
        self._hover_key = None
        self._hover_index = None

    def _frames(self) -> list[QTextFrame]:
        return self.document().rootFrame().childFrames()

    def _viewport_rect(self, frame: QTextFrame) -> QRectF:
        rect = self.document().documentLayout().frameBoundingRect(frame)
        rect.setLeft(0)
        rect.setWidth(self.viewport().width())
        return rect.translated(0, -self.verticalScrollBar().value())

    def _entry_at(self, pos: QPoint) -> tuple[int, QRectF] | None:
        table = self.cursorForPosition(pos).currentTable()
        if table is None:
            return None
        rect = self._viewport_rect(table)
        if not rect.top() <= pos.y() < rect.bottom():
            return None
        key = table.firstPosition()
        if key != self._hover_key:
            self._hover_key = key
            self._hover_index = next(
                (i for i, f in enumerate(self._frames()) if f.firstPosition() == key), None,
            )
        if self._hover_index is None or self._hover_index >= len(self._entries):
            return None
        return self._hover_index, rect

    def _hovered(self) -> tuple[ChatAreaEntry, QRectF] | None:
        if self._mouse_pos is None:
            return None
        if (found := self._entry_at(self._mouse_pos)) is None:
            return None
        index, rect = found
        entry = self._entries[index]
        if entry.payload is None:
            return None
        return entry, rect

    def _button_rect(self, row: QRectF) -> QRect:
        metrics = self.fontMetrics()
        height = metrics.height() + 4
        width = metrics.horizontalAdvance("Reply") + 14
        return QRect(int(row.right()) - width - 4, int(row.top()) + 1, width, height)

    def _index_rect(self, index: int | None) -> QRectF | None:
        if index is None or index >= len(frames := self._frames()):
            return None
        return self._viewport_rect(frames[index])

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._menu_index is not None:
            hovered = None
            hover_rect = self._index_rect(self._menu_index)
        else:
            hovered = self._hovered()
            hover_rect = None if hovered is None else hovered[1]
        flash_rect = self._index_rect(self._flash_index)

        if hover_rect is not None or flash_rect is not None:
            painter = QPainter(self.viewport())
            if hover_rect is not None:
                painter.fillRect(hover_rect, self._hover_color)
            if flash_rect is not None:
                painter.fillRect(flash_rect, self._flash_color)
            painter.end()

        super().paintEvent(event)

        if hovered is not None and hovered[0].replyable:
            self._paint_button(self._button_rect(hovered[1]))

    def _paint_button(self, rect: QRect) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(self._button_color)
        if self._over_button:
            background = background.lighter(140)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(self._button_text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Reply")
        painter.end()

    def _button_hit(self, pos: QPoint) -> ChatAreaEntry | None:
        hovered = self._hovered()
        if hovered is None or not hovered[0].replyable:
            return None
        entry, row = hovered
        return entry if self._button_rect(row).contains(pos) else None

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if self._mouse_pos is not None or self._flash_index is not None:
            self.viewport().update()

    def viewportEvent(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.Leave:
            self._mouse_pos = None
            self._set_over_button(False)
            self.viewport().update()
        return super().viewportEvent(event)

    def _set_over_button(self, over: bool) -> None:
        if over == self._over_button:
            return
        self._over_button = over
        if over:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(self._default_cursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        old_key = self._hover_key
        self._mouse_pos = pos
        super().mouseMoveEvent(event)
        over_button = self._button_hit(pos) is not None
        if over_button != self._over_button or self._hover_key != old_key:
            self._set_over_button(over_button)
            self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            entry = self._button_hit(event.position().toPoint())
            if entry is not None:
                self._pressed_button = True
                self.reply_requested.emit(entry.payload)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed_button:
            self._pressed_button = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        pos = event.pos()
        doc_pos = pos + QPoint(0, self.verticalScrollBar().value())
        menu = self.createStandardContextMenu(doc_pos)
        if menu is None:
            return
        if (found := self._entry_at(pos)) is not None:
            index = found[0]
            if (payload := self._entries[index].payload) is not None:
                self._menu_index = index
                self.menu_requested.emit(menu, payload)
        self.viewport().update()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
            self._menu_index = None
            cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
            self._mouse_pos = cursor_pos if self.viewport().rect().contains(cursor_pos) else None
            self.viewport().update()

    def createMimeDataFromSelection(self) -> QMimeData:
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        selected = [
            index for index, frame in enumerate(self._frames())
            if frame.firstPosition() <= end and frame.lastPosition() >= start
        ]
        if len(selected) < 2 or selected[-1] >= len(self._entries):
            return super().createMimeDataFromSelection()
        mime = QMimeData()
        mime.setText("\n".join(self._entries[index].plain_text for index in selected))
        return mime
