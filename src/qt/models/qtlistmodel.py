from abc import ABCMeta
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Hashable

from PyQt6.QtCore import QAbstractListModel
from PyQt6.QtCore import QModelIndex
from PyQt6.QtCore import QObject
from PyQt6.QtCore import Qt
from PyQt6.QtCore import pyqtSignal
from PyQt6.sip import wrappertype


class _QObjectMeta(ABCMeta, wrappertype):
    pass


class QtListModelItem(QObject, metaclass=_QObjectMeta):
    updated = pyqtSignal(object)

    @abstractmethod
    def tooltip(self) -> str | None:
        ...


# TODO: remove item_builder from here
class QtListModel[U, T: QtListModelItem](QAbstractListModel):
    def __init__(self, item_builder: Callable[[U], T]) -> None:
        super().__init__()
        self._items: dict[Hashable, T] = {}
        self._itemlist: list[T] = []  # For queries
        self._item_builder = item_builder

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._itemlist)

    def data(self, index: QModelIndex, role: int = 0) -> T | str | None:
        if not index.isValid() or index.row() >= len(self._itemlist):
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._itemlist[index.row()].tooltip()
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._itemlist[index.row()]

    # TODO - insertion and removal are O(n).
    def _add_item(self, data: U, id_: Hashable) -> None:
        assert id_ not in self._items
        next_index = len(self._itemlist)
        self.beginInsertRows(QModelIndex(), next_index, next_index)
        item = self._item_builder(data)
        item.updated.connect(self._at_item_updated)
        self._items[id_] = item
        self._itemlist.append(item)
        self.endInsertRows()

    def _remove_item(self, id_: Hashable) -> None:
        assert id_ in self._items
        item = self._items[id_]
        item_index = self._itemlist.index(item)
        self.beginRemoveRows(QModelIndex(), item_index, item_index)
        item.updated.disconnect(self._at_item_updated)
        del self._items[id_]
        self._itemlist.pop(item_index)
        self.endRemoveRows()

    def _clear_items(self) -> None:
        self.beginRemoveRows(QModelIndex(), 0, len(self._itemlist) - 1)
        for item in self._items.values():
            item.updated.disconnect(self._at_item_updated)
        self._items.clear()
        self._itemlist.clear()
        self.endRemoveRows()

    def _at_item_updated(self, item: T) -> None:
        item_index = self._itemlist.index(item)
        index = self.index(item_index, 0)
        self.dataChanged.emit(index, index)
