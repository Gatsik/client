import os
import shutil

from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QWidget

from src import util
from src.api.ApiAccessors import DataApiAccessor
from src.api.ApiAccessors import ParsedDataApiResponse
from src.api.ApiBase import api_error_text
from src.api.models.Map import Map
from src.api.models.MapVersion import MapVersion
from src.fa import maps
from src.fa.maps_.preview import create_largest_preview
from src.fa.maps_.previewdialog import MapPreviewDialog
from src.model.player import Player
from src.qt.utils import critical_msgbox
from src.vaults.detailswidget import DetailsWidget


class MapDetailsWidget(DetailsWidget[Map]):
    def __init__(
            self,
            item_data: Map,
            player: Player,
            parent: QWidget | None = None,
    ) -> None:
        super().__init__(item_data, util.MAP_PREVIEW_LARGE_DIR, player, parent)
        self.item_data = item_data
        assert item_data.version is not None
        self.item_version = item_data.version
        self.ui.thumbnailLabel.clicked.connect(self.preview_map_large)

        self.games_api = DataApiAccessor("/data/game")

    def init_ui(self) -> None:
        super().init_ui()
        self.ui.versionLayout.addRow(self.ui.hideButton)
        self.ui.hideButton.setVisible(
            self.item_data.author is not None
            and int(self.item_data.author.xd) == self.player.id,
        )
        self.ui.hideButton.clicked.connect(self.hide_map_version)

    def _ask_if_played_map(self) -> None:
        self.games_api.get_parsed(
            {
                "include": "playerStats",
                "filter": (
                    f"playerStats.player.id=={self.player.id};"
                    f"mapVersion.id=={self.item_version.xd}"
                ),
                "page[size]": 1,
            },
            self.allow_review,
        )

    def ask_review(self) -> None:
        if self.item_data.author is not None and self.item_data.author.login == self.player.login:
            self.ui.addReviewButton.setEnabled(False)
            self.ui.detailedReviews.addCommentButton.setEnabled(False)
        else:
            self._ask_if_played_map()

    def allow_review(self, response: ParsedDataApiResponse) -> None:
        map_played = len(response["data"]) > 0
        self.ui.addReviewButton.setEnabled(map_played)
        self.ui.detailedReviews.addCommentButton.setEnabled(map_played)

    def preview_map_large(self) -> None:
        if not self.is_installed():
            return
        folder = maps.folderForMap(self.item_version.folder_name)
        assert folder is not None
        pixmap = create_largest_preview(self.screen(), folder)
        dialog = MapPreviewDialog(pixmap, self)
        dialog.exec()

    def is_installed(self) -> bool:
        return maps.isMapAvailable(self.item_version.folder_name)

    def set_author(self) -> None:
        if self.item_data.author:
            author_label = QLabel(f"{self.item_data.author.login}")
            self.ui.authorLayout.addRow(QLabel("Author:"), author_label)
        else:
            self.ui.authorLayout.addWidget(QLabel("Unknown Author"))

    def set_type(self) -> None:
        self.ui.typeLabel.setText(f"Type: {self.item_data.map_type}")

    def set_additional_info(self) -> None:
        self.ui.additionalInfoLabel.setText(f"{self.item_data.games_played} games played")

    def version_info(self) -> list[tuple[str, str]]:
        return [
            ("Version:", str(self.item_version.version)),
            ("Dimensions:", str(self.item_version.size)),
            ("Max Players:", str(self.item_version.max_players)),
            ("Games Played:", str(self.item_version.games_played)),
            ("Ranked:", "Yes" if self.item_version.ranked else "No"),
            ("Hidden:", "Yes" if self.item_version.hidden else "No"),
        ]

    def technical_info(self) -> list[tuple[str, str]]:
        return [
            *super().technical_info(),
            ("Folder Name", self.item_version.folder_name),
            ("Width", str(self.item_version.size.width_km)),
            ("Height", str(self.item_version.size.height_km)),
            ("Max Players", str(self.item_version.max_players)),
            ("Version", str(self.item_version.version)),
            ("Version Games Played", str(self.item_version.games_played)),
            ("Map Games Played", str(self.item_data.games_played)),
            ("Ranked", "Yes" if self.item_version.ranked else "No"),
            ("Hidden", "Yes" if self.item_version.hidden else "No"),
            ("Download URL", self.item_version.download_url),
            ("Small Thumbnail", self.item_version.thumbnail_url_small),
            ("Large Thumbnail", self.item_version.thumbnail_url_large),
        ]

    def download_item(self) -> None:
        ret, msg = maps._doDownloadMap(
            self.item_version.folder_name,
            self.item_version.download_url,
            silent=False,
        )
        if not ret and msg is not None:
            msg()

    def remove_item(self) -> None:
        full_path = os.path.join(maps.getUserMapsFolder(), self.item_version.folder_name)
        shutil.rmtree(full_path)

    def view_folder(self) -> None:
        util.showDirInFileBrowser(maps.folderForMap(self.item_version.folder_name))

    def hide_map_version(self) -> None:
        if QMessageBox.question(
            None,
            "Hide map version from vault",
            (
                f"Are you sure you wish to hide {self.item_version.folder_name!r} from vault?"
                "<br/><b>You won't be able to unhide it with the client</b>"
            ),
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        ) is QMessageBox.StandardButton.No:
            return

        self.ui.hideButton.setEnabled(False)
        payload = self.item_version.to_jsonapi_payload(
            set(MapVersion.model_fields) - {"xd", "hidden"},
            {""},
            id=self.item_version.xd,
            hidden=True,
        )
        # it doesn't matter this is 'games' api
        self.games_api.patch(
            f"/data/mapVersion/{self.item_version.xd}",
            payload,
            self.on_hide_success,
            self.on_hide_failure,
        )

    def on_hide_success(self, reply: QNetworkReply) -> None:
        self.ui.hideButton.hide()
        self.item_version.hidden = True
        self.item_hidden_changed.emit()

    def on_hide_failure(self, reply: QNetworkReply) -> None:
        self.ui.hideButton.setEnabled(True)
        critical_msgbox(
            None,
            "Error",
            "Could not hide map version",
            api_error_text(reply),
        )
