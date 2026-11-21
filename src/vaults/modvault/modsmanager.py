import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtWidgets import QFormLayout
from PyQt6.QtWidgets import QGroupBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtWidgets import QVBoxLayout

from src import util
from src.api.models.ModType import ModType
from src.games.hostgamewidget import HostGameWidget
from src.vaults.modvault.utils import getInstalledMods

if TYPE_CHECKING:
    from src.client._clientwindow import ClientWindow


class ModsManagerDialog(HostGameWidget):
    def __init__(self, client: ClientWindow) -> None:
        super().__init__(client)
        self.setWindowTitle("Manage Custom Mods")
        self.setModal(True)
        self.ui.topSectionFrame.hide()
        self.ui.generateButton.hide()
        self.ui.selectRandomMapButton.hide()
        self.ui.mapsGroup.hide()
        self.ui.previewGroup.hide()
        self.ui.saveAndCloseButton.hide()
        self.ui.hostButton.hide()

        self.ui.deselectUiMods.hide()
        self.ui.deselectSimMods.hide()

        self.ui.modList.setSelectionMode(self.ui.modList.SelectionMode.SingleSelection)
        self.ui.modList.currentItemChanged.connect(self.mod_changed)

        self.modPreviewGroup = QGroupBox("Mod Preview")
        self.modPreviewGroup.setObjectName("previewGroup")

        preview_layout = QVBoxLayout(self.modPreviewGroup)
        preview_layout.setContentsMargins(10, 15, 10, 10)

        self.modPreviewLabel = QLabel()
        self.modPreviewLabel.setFixedSize(256, 256)
        self.modPreviewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.modPreviewLabel.setProperty("bordered", "true")
        self.modPreviewLabel.setText("No preview available")

        self.labelName = QLabel("-")
        self.labelName.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.labelName.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        mod_info_box = QGroupBox("Information")
        mod_info_layout = QFormLayout(mod_info_box)

        self.labelVersion = QLabel("-")
        self.labelType = QLabel("-")

        self.labelAuthor = QLabel("-")
        self.labelAuthor.setWordWrap(True)

        self.labelUID = QLabel("-")
        self.labelDirSize = QLabel("-")

        self.labelName.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.labelVersion.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.labelType.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.labelAuthor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.labelUID.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.labelDirSize.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.labelName.setCursor(Qt.CursorShape.IBeamCursor)
        self.labelVersion.setCursor(Qt.CursorShape.IBeamCursor)
        self.labelType.setCursor(Qt.CursorShape.IBeamCursor)
        self.labelAuthor.setCursor(Qt.CursorShape.IBeamCursor)
        self.labelUID.setCursor(Qt.CursorShape.IBeamCursor)
        self.labelDirSize.setCursor(Qt.CursorShape.IBeamCursor)

        mod_info_layout.addRow(QLabel("Author:"), self.labelAuthor)
        mod_info_layout.addRow(QLabel("Version:"), self.labelVersion)
        mod_info_layout.addRow(QLabel("Type:"), self.labelType)
        mod_info_layout.addRow(QLabel("UID:"), self.labelUID)
        mod_info_layout.addRow(QLabel("Directory size:"), self.labelDirSize)

        self.modDescription = QTextEdit("No description available")
        self.modDescription.setReadOnly(True)
        self.modDescription.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.modDescription.setMinimumHeight(120)
        self.modDescription.setFixedWidth(390)

        preview_layout.addWidget(self.modPreviewLabel, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.labelName)
        preview_layout.addWidget(mod_info_box)
        preview_layout.addWidget(self.modDescription)

        self.ui.middleSection.addWidget(self.modPreviewGroup)

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
        self.buttonDelete.clicked.connect(self.delete_mod)
        self.buttonOk.clicked.connect(self.accept)

    def run(self) -> None:
        self._reset()
        for mod in getInstalledMods():
            self.mods[mod.totalname] = mod
            self.ui.modList.addItem(mod.totalname)
        self.ui.modList.setCurrentRow(0)
        self.show()

    def mod_changed(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        if cur is None:
            return
        self.update_mod_preview(cur)

    def update_mod_preview(self, item: QListWidgetItem) -> None:
        mod = self.mods[item.text()]
        self.labelName.setText(mod.name)
        self.labelType.setText(ModType.UI.value if mod.ui_only else ModType.SIM.value)
        self.labelVersion.setText(str(mod.version))
        self.labelAuthor.setText(mod.author)
        self.labelUID.setText(mod.uid)
        self.labelDirSize.setText(f"{util.dir_size(mod.absfolder) / 1024 / 1024:.2f} MiB")
        self.modDescription.setText(mod.description)

        with os.scandir(mod.absfolder) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".png"):
                    self.modPreviewLabel.setPixmap(QPixmap(entry.path).scaled(256, 256))
                    break
            else:
                self.modPreviewLabel.setText("No preview available")

    def delete_mod(self) -> None:
        moditem = self.ui.modList.currentItem()
        if moditem is None:
            return
        if util.clearDirectory(
            self.mods[moditem.text()].absfolder,
            confirm=not self.checkSkipConfirm.isChecked(),
        ):
            self.ui.modList.takeItem(self.ui.modList.row(moditem))

    def view_folder(self) -> None:
        moditem = self.ui.modList.currentItem()
        if moditem is None:
            return

        util.showDirInFileBrowser(self.mods[moditem.text()].absfolder)
