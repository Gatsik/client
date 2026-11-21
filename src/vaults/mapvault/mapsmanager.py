from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QStyle

from src import util
from src.fa import maps
from src.games.hostgamewidget import HostGameWidget

if TYPE_CHECKING:
    from src.client._clientwindow import ClientWindow


class MapsManagerDialog(HostGameWidget):
    def __init__(self, client: ClientWindow) -> None:
        super().__init__(client)
        self.setWindowTitle("Manage Custom Maps")
        self.setModal(True)
        self.ui.topSectionFrame.hide()
        self.ui.generateButton.hide()
        self.ui.selectRandomMapButton.hide()
        self.ui.modsGroup.hide()
        self.ui.saveAndCloseButton.hide()
        self.ui.hostButton.hide()

        dir_icon = QLabel()
        drive_pix = self.style().standardPixmap(QStyle.StandardPixmap.SP_DriveFDIcon)
        dir_icon.setPixmap(drive_pix)
        self.labelDirSize = QLabel("-")

        # remove leading stretch
        self.ui.mapInfoLayout.removeItem(self.ui.mapInfoLayout.itemAt(0))

        self.ui.mapInfoLayout.addWidget(dir_icon)
        self.ui.mapInfoLayout.addWidget(self.labelDirSize)

        buttons_layout = QHBoxLayout()

        self.buttonViewFiles = QPushButton("View Files")
        self.buttonDelete = QPushButton("Delete")
        self.buttonOk = QPushButton("OK")
        self.checkSkipConfirm = QCheckBox("Skip confirmation")

        buttons_layout.addWidget(self.buttonViewFiles)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.checkSkipConfirm)
        buttons_layout.addWidget(self.buttonDelete)
        buttons_layout.addWidget(self.buttonOk)

        self.ui.mainLayout.addLayout(buttons_layout)

        self.buttonViewFiles.clicked.connect(self.view_folder)
        self.buttonDelete.clicked.connect(self.delete_map)
        self.buttonOk.clicked.connect(self.accept)

    def run(self) -> None:
        self._reset()
        self.maps_metadata_parser_thread.start()
        self.show()

    def setup_maplist(self) -> None:
        self.ui.mapList.clear()

        for folder_name, map_info in maps.CachedMapsMetadata.get_installed_maps().items():
            if maps.isBase(folder_name):
                continue
            name = maps.getDisplayName(folder_name.lower())
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, map_info)
            self.ui.mapList.addItem(item)

        self.ui.mapList.sortItems()
        self.ui.mapList.setCurrentRow(0)
        self.filter_maps_by_name(self.ui.mapNameFilter.text())

    def map_changed(self, row: int) -> None:
        item = self.ui.mapList.item(row)
        if item is None:
            return
        map_info = item.data(Qt.ItemDataRole.UserRole)
        if (folder := maps.folderForMap(map_info["folder_name"])) is not None:
            size = f"{util.dir_size(folder) / 1024 / 1024:.2f} MiB"
            self.labelDirSize.setText(size)
        else:
            self.labelDirSize.setText("-")
        self.update_map_preview(item)

    def delete_map(self) -> None:
        mapitem = self.ui.mapList.currentItem()
        if mapitem is None:
            return

        map_info = mapitem.data(Qt.ItemDataRole.UserRole)
        if (folder := maps.folderForMap(map_info["folder_name"])) is None:
            return

        if util.clearDirectory(folder, confirm=not self.checkSkipConfirm.isChecked()):
            self.ui.mapList.takeItem(self.ui.mapList.row(mapitem))

    def view_folder(self) -> None:
        mapitem = self.ui.mapList.currentItem()
        if mapitem is None:
            return

        map_info = mapitem.data(Qt.ItemDataRole.UserRole)
        util.showDirInFileBrowser(maps.folderForMap(map_info["folder_name"]))
