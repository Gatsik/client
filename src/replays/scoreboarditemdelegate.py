from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QRect
from PyQt6.QtCore import QSize
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtGui import QPen
from PyQt6.QtWidgets import QStyledItemDelegate
from PyQt6.QtWidgets import QStyleOptionViewItem

from src.qt.itemviews.styleditemdelegate import StyledItemDelegate
from src.qt.utils import qpainter
from src.replays.models import ScoreboardModel
from src.replays.models import ScoreboardModelItem
from src.user_notes.dialogs import note_icon


class ScoreboardItemDelegate(StyledItemDelegate):
    NOTE_ICON_SIZE = 16
    NOTE_ICON_SPACING = 3

    def __init__(self) -> None:
        StyledItemDelegate.__init__(self)
        self._row_height = 22

    def row_height(self) -> int:
        return self._row_height

    def sizeHint(self, option, index) -> QSize:
        size = QStyledItemDelegate.sizeHint(self, option, index)
        return QSize(size.width(), self._row_height)

    def _draw_score(
            self,
            painter: QPainter,
            rect: QRect,
            player_data: ScoreboardModelItem,
            alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> QRect:
        score = f"{player_data.score()}"
        score_rect = QRect(rect)
        score_rect.setWidth(20)
        if alignment == Qt.AlignmentFlag.AlignRight:
            score_rect.moveLeft(rect.width() - score_rect.width())
        painter.drawText(score_rect, Qt.AlignmentFlag.AlignCenter, score)
        return score_rect

    def _draw_icon(
            self,
            painter: QPainter,
            rect: QRect,
            player_data: ScoreboardModelItem,
            alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> QRect:
        icon = player_data.icon()
        icon_rect = QRect(rect)
        icon_rect.setWidth(40)
        icon_rect.setHeight(20)
        if alignment == Qt.AlignmentFlag.AlignRight:
            icon_rect.moveLeft(rect.width() - icon_rect.width())
        icon.paint(painter, icon_rect)
        return icon_rect

    def _draw_nick_and_rating(
            self,
            painter: QPainter,
            rect: QRect,
            player_data: ScoreboardModelItem,
            alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> QRect:
        rating = player_data.rating()
        rating_str = f"{rating}" if rating is not None else "???"
        text = f"{player_data.login()} ({rating_str})"
        has_note = player_data.note() is not None
        icon_size = min(self.NOTE_ICON_SIZE, rect.height())
        text_width = rect.width()
        if has_note:
            text_width -= icon_size + self.NOTE_ICON_SPACING
        elided = self._get_elided_text(painter, text, width=text_width)
        painter.drawText(rect, alignment, elided)
        if has_note:
            self._draw_note_icon(painter, rect, elided, icon_size, alignment)
        return rect

    def _draw_note_icon(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        icon_size: int,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        advance = painter.fontMetrics().horizontalAdvance(text) + self.NOTE_ICON_SPACING
        if alignment == Qt.AlignmentFlag.AlignRight:
            left = rect.right() - advance - icon_size + 1
        else:
            left = rect.left() + advance
        # text is top-aligned
        text_height = painter.fontMetrics().height()
        top = rect.top() + max(0, (text_height - icon_size) // 2)
        icon_rect = QRect(left, top, icon_size, icon_size)
        note_icon().paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

    def _draw_rating_change(
            self,
            painter: QPainter,
            rect: QRect,
            player_data: ScoreboardModelItem,
            alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> QRect:
        change = player_data.rating_change()
        rating_change_rect = QRect(rect)
        rating_change_rect.setWidth(30)
        if alignment == Qt.AlignmentFlag.AlignRight:
            rating_change_rect.moveLeft(rect.width() - rating_change_rect.width())
        color = painter.pen().color()
        if change > 0:
            color = Qt.GlobalColor.green
        elif change < 0:
            color = Qt.GlobalColor.red
        with qpainter(painter):
            painter.setPen(QPen(color))
            painter.drawText(rating_change_rect, Qt.AlignmentFlag.AlignCenter, f"{change:+}")
        return rating_change_rect

    def _shrink_rect_along(
            self,
            rect: QRect,
            adjustment: int,
            alignment: Qt.AlignmentFlag,
    ) -> QRect:
        """
        Returns a new rect shrinked from left or right side
        by given adjustment
        """
        direction = 1 if alignment == Qt.AlignmentFlag.AlignLeft else -1
        index = 0 if alignment == Qt.AlignmentFlag.AlignLeft else 2
        adjustments = [0, 0, 0, 0]
        adjustments[index] = adjustment * direction
        return rect.adjusted(*adjustments)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        player_data: ScoreboardModelItem = index.data()
        team_model: ScoreboardModel = index.model()
        team_alignment = team_model.get_alignment()
        rect = QRect(option.rect)

        with qpainter(painter):
            self._draw_clear_option(painter, option)

            if team_model.spoiled:
                score_rect = self._draw_score(painter, rect, player_data, team_alignment)
                rect = self._shrink_rect_along(rect, score_rect.width(), team_alignment)

                diff_rect = self._draw_rating_change(painter, rect, player_data, team_alignment)
                rect = self._shrink_rect_along(rect, diff_rect.width(), team_alignment)

            icon_rect = self._draw_icon(painter, rect, player_data, team_alignment)
            rect = self._shrink_rect_along(rect, icon_rect.width() + 3, team_alignment)

            self._draw_nick_and_rating(painter, rect, player_data, team_alignment)
