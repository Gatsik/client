import json
import logging
import os
import tempfile
from typing import Any

from PyQt6.QtCore import QFile
from PyQt6.QtCore import QFileInfo
from PyQt6.QtCore import QObject
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QHttpMultiPart
from PyQt6.QtNetwork import QHttpPart
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtNetwork import QNetworkRequest
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QProgressBar
from PyQt6.QtWidgets import QWidget

from src import util
from src.api.ApiAccessors import ApiAccessor
from src.api.ApiBase import api_error_text
from src.api.models.MapVersion import MapSize
from src.config import Settings
from src.fa.maps import MapInfo
from src.fa.maps_.preview import create_large_preview
from src.qt.utils import critical_msgbox
from src.vaults.zip_thread import ZipThread

logger = logging.getLogger(__name__)

FormClass, BaseClass = util.THEME.loadUiType("vaults/mapvault/upload.ui")


class MapUploader(QObject):
    not_started = pyqtSignal()
    error = pyqtSignal(QNetworkReply)
    success = pyqtSignal()

    zip_end = pyqtSignal()
    file_sent = pyqtSignal()

    def __init__(self, mapdir: str, progress_bar: QProgressBar, *, is_ranked: bool = True) -> None:
        super().__init__()
        self.mapdir = mapdir
        self.tempdir = tempfile.TemporaryDirectory()
        self.qfile = QFile(self)

        self.api = ApiAccessor()
        self.reply = None

        self.bar = progress_bar
        self.is_ranked = is_ranked

        archive_path = os.path.join(self.tempdir.name, "map")
        self.zip_thread = ZipThread(archive_path, *os.path.split(self.mapdir))
        self.zip_thread.zip_error.connect(self.not_started.emit)
        self.zip_thread.zip_ready.connect(self.upload)
        self.zip_thread.zip_ready.connect(self.zip_end.emit)

    def set_ranked(self, ranked: bool, /) -> None:
        self.is_ranked = ranked

    def run(self) -> None:
        self.zip_thread.start()

    def upload(self, zipped: str) -> None:
        self.qfile = QFile(zipped, self)
        if not self.qfile.open(self.qfile.OpenModeFlag.ReadOnly):
            logger.error("Could not open file '%s'", self.qfile.fileName())
            self.not_started.emit()
            return

        multipart = self.make_multipart()
        self.reply = self.api.post(
            "/maps/upload",
            multipart,
            self.on_success,
            self.on_failure,
        )
        multipart.setParent(self.reply)
        self.reply.uploadProgress.connect(self.on_upload_progress)

    def make_multipart(self) -> QHttpMultiPart:
        multipart = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)

        file_part = QHttpPart()
        file_part_filename = QFileInfo(self.qfile).fileName()
        file_part.setHeader(
            QNetworkRequest.KnownHeaders.ContentDispositionHeader,
            f"form-data; name=\"file\"; filename=\"{file_part_filename}\"",
        )
        file_part.setBodyDevice(self.qfile)

        metadata_part = QHttpPart()
        metadata_part.setHeader(
            QNetworkRequest.KnownHeaders.ContentDispositionHeader,
            "form-data; name=\"metadata\"",
        )
        metadata = {"isRanked": self.is_ranked}
        metadata_part.setBody(json.dumps(metadata).encode())

        multipart.append(file_part)
        multipart.append(metadata_part)
        return multipart

    def on_success(self, message: dict[str, Any]) -> None:
        self.clean()
        self.success.emit()

    def on_failure(self, reply: QNetworkReply) -> None:
        self.clean()
        self.error.emit(reply)

    def on_upload_progress(self, sent: int, total: int) -> None:
        if total != 0:
            self.bar.setValue(int(100 * sent / total))
            if sent == total:
                self.file_sent.emit()

    def clean(self) -> None:
        self.qfile.close()
        self.reply = None

    def abort(self) -> None:
        if self.reply is not None and self.reply.isRunning():
            self.reply.abort()


class MapUploadDialog(FormClass, BaseClass):
    def __init__(self, mapdir: str, mapinfo: MapInfo, parent: QWidget | None = None) -> None:
        BaseClass.__init__(self, parent)
        self.setupUi(self)
        self.setWindowTitle("Uploading Map")

        self.mapdir = mapdir
        self.mapinfo = mapinfo

        self.lineName.setText(mapinfo["name"])
        self.lineVersion.setText(mapinfo["version"])
        size = MapSize(*map(int, mapinfo["map_size"].values()))
        self.lineWidth.setText(f"{size.width_px} ({size.width_km:g} km)")
        self.lineHeight.setText(f"{size.height_px} ({size.height_km:g} km)")
        self.linePlayers.setText(str(mapinfo["max_players"]))
        self.editDescription.setPlainText(mapinfo["description"])
        self.labelPreview.setPixmap(create_large_preview(mapdir).scaled(256, 256))

        self.checkRanked.setChecked(True)

        self.uploader = MapUploader(self.mapdir, self.progressBar, is_ranked=True)
        self.uploader.error.connect(self.on_upload_error)
        self.uploader.success.connect(self.on_upload_success)
        self.uploader.not_started.connect(self.not_started)
        self.uploader.zip_end.connect(self.enter_uploading_state)
        self.uploader.file_sent.connect(self.enter_awaiting_verdict_state)

        self.checkRanked.toggled.connect(self.uploader.set_ranked)
        self.checkRules.toggled.connect(self.buttonUpload.setEnabled)

        self.buttonRules.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(Settings.get("vault/rules_url"))),
        )
        self.buttonMetadata.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(Settings.get("vault/map_validation_url"))),
        )

        self.buttonUpload.clicked.connect(self.upload)
        self.buttonUpload.setEnabled(False)
        self.buttonAbort.clicked.connect(self.uploader.abort)

        self.enter_start_state()

    def enter_start_state(self) -> None:
        self.progressBar.setValue(0)
        self.progressFrame.hide()
        self.buttonUpload.show()
        self.checkRules.setChecked(False)

    def enter_zipping_state(self) -> None:
        self.buttonUpload.hide()
        self.buttonAbort.setEnabled(False)
        self.progressFrame.show()
        self.labelStatusBarInfo.setText("Zipping files...")
        self.progressBar.setRange(0, 0)

    def enter_uploading_state(self) -> None:
        self.buttonUpload.hide()
        self.buttonAbort.setEnabled(True)
        self.progressFrame.show()
        self.labelStatusBarInfo.setText("Uploading files...")
        self.progressBar.setRange(0, 100)

    def enter_awaiting_verdict_state(self) -> None:
        self.buttonUpload.hide()
        self.buttonAbort.setEnabled(True)
        self.progressFrame.show()
        self.labelStatusBarInfo.setText("Waiting for server's verdict...")
        self.progressBar.setRange(0, 0)

    def enter_finish_state(self) -> None:
        self.progressBar.setValue(0)
        self.progressFrame.hide()
        self.buttonUpload.show()
        self.buttonUpload.setEnabled(False)

    def upload(self) -> None:
        self.enter_zipping_state()
        self.uploader.run()

    def not_started(self) -> None:
        self.enter_start_state()
        critical_msgbox(
            self.parent(),
            "Map upload error",
            "Something went wrong zipping the map files.",
        )

    def on_upload_error(self, reply: QNetworkReply) -> None:
        self.enter_start_state()
        if reply.error() is reply.NetworkError.OperationCanceledError:
            return
        critical_msgbox(
            self.parent(),
            "Map upload error",
            "Something went wrong uploading the map files",
            api_error_text(reply),
        )

    def on_upload_success(self) -> None:
        self.enter_finish_state()
        QMessageBox.information(self.parent(), "Success", "Upload finished!")
        self.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.uploader.abort()
        super().closeEvent(event)
