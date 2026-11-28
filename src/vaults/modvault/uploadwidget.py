import json
import logging
import os
import tempfile
from typing import TYPE_CHECKING
from typing import Any

from PyQt6 import QtCore
from PyQt6 import QtWidgets
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkReply

from src import util
from src.api.ApiAccessors import ApiAccessor
from src.api.ApiBase import ApiAccessManagerInstance
from src.api.ApiBase import api_error_text
from src.config import Settings
from src.qt.utils import critical_msgbox
from src.vaults.modvault import utils
from src.vaults.zip_thread import ZipThread

if TYPE_CHECKING:
    from src.vaults.modvault.modvault import ModVault


logger = logging.getLogger(__name__)

FormClass, BaseClass = util.THEME.loadUiType("vaults/modvault/upload.ui")


class ModUploader(QtCore.QObject):
    not_started = QtCore.pyqtSignal()
    internal_error = QtCore.pyqtSignal(QNetworkReply)
    error = QtCore.pyqtSignal(QNetworkReply)
    complete = QtCore.pyqtSignal()
    zip_end = QtCore.pyqtSignal()
    file_sent = QtCore.pyqtSignal()

    def __init__(self, moddir: str, progress_bar: QtWidgets.QProgressBar) -> None:
        super().__init__()
        self.moddir = moddir
        self.tempdir = tempfile.TemporaryDirectory()
        self.qfile = QtCore.QFile(self)
        self.request_id = ""
        self.upload_url = QtCore.QUrl()

        self.api = ApiAccessor()
        self.reply = None

        self.bar = progress_bar

        archive_path = os.path.join(self.tempdir.name, "mod")
        self.zip_thread = ZipThread(archive_path, *os.path.split(self.moddir))
        self.zip_thread.zip_error.connect(self.not_started.emit)
        self.zip_thread.zip_ready.connect(self.upload)
        self.zip_thread.zip_ready.connect(self.zip_end.emit)

    def abort(self) -> None:
        if self.reply is not None and self.reply.isRunning():
            self.reply.abort()

    def clean(self) -> None:
        self.qfile.close()
        self.reply = None

    def run(self) -> None:
        self.api.get("/mods/upload/start", self.on_start_success, self.on_start_failure)

    def on_start_success(self, upload_info: dict[str, str]) -> None:
        self.request_id = upload_info["requestId"]
        self.upload_url = QtCore.QUrl(upload_info["uploadUrl"])
        self.zip_thread.start()

    def upload(self, zipped: str) -> None:
        self.qfile = QtCore.QFile(zipped, self)
        if not self.qfile.open(self.qfile.OpenModeFlag.ReadOnly):
            logger.error("Could not open file '%s'", self.qfile.fileName())
            self.not_started.emit()
            return
        self.reply = ApiAccessManagerInstance.put(
            self.upload_url,
            self.qfile,
            self.on_upload_success,
            self.on_upload_failure,
            authorize=False,
        )
        self.reply.uploadProgress.connect(self.on_upload_progress)

    def on_start_failure(self, reply: QNetworkReply) -> None:
        self.clean()
        self.internal_error.emit(reply)

    def on_upload_success(self, reply: QNetworkReply) -> None:
        response = json.dumps({"requestId": self.request_id})
        self.api.post(
            "/mods/upload/complete",
            QtCore.QByteArray(response.encode()),
            self.on_complete_success,
            self.on_complete_failure,
        )

    def on_upload_progress(self, sent: int, total: int) -> None:
        if total != 0:
            self.bar.setValue(int(100 * sent / total))
            if sent == total:
                self.file_sent.emit()

    def on_upload_failure(self, reply: QNetworkReply) -> None:
        self.clean()
        self.internal_error.emit(reply)

    def on_complete_success(self, message: dict[str, Any]) -> None:
        self.clean()
        self.complete.emit()

    def on_complete_failure(self, reply: QNetworkReply) -> None:
        self.clean()
        self.error.emit(reply)


class UploadModWidget(FormClass, BaseClass):
    def __init__(self, parent: ModVault, modDir: str, modinfo: utils.ModInfo) -> None:
        BaseClass.__init__(self, parent)

        self.setupUi(self)

        self.client = parent.client
        self.modinfo = modinfo
        self.modDir = modDir

        self.setWindowTitle("Uploading Mod")

        self.Name.setText(modinfo.name)
        self.Version.setText(str(modinfo.version))
        self.isUIOnly.setText(str(modinfo.ui_only))
        self.UID.setText(modinfo.uid)
        self.Description.setPlainText(modinfo.description)
        if modinfo.icon != "":
            self.IconURI.setText(utils.iconPathToFull(self.modDir, modinfo.icon))
            self.updateThumbnail()
        else:
            self.Thumbnail.setPixmap(util.THEME.pixmap("games/unknown_map.png").scaled(100, 100))
        self.UploadButton.pressed.connect(self.upload)
        self.UploadButton.setEnabled(False)
        self.checkRules.toggled.connect(self.UploadButton.setEnabled)
        self.buttonRules.clicked.connect(
            lambda: QDesktopServices.openUrl(QtCore.QUrl(Settings.get("vault/rules_url"))),
        )

        self.uploader = ModUploader(self.modDir, self.progressBar)
        self.uploader.internal_error.connect(self.uploader_error)
        self.uploader.error.connect(self.completion_error)
        self.uploader.complete.connect(self.complete)
        self.uploader.not_started.connect(self.not_started)
        self.uploader.zip_end.connect(self.enter_uploading_state)
        self.uploader.file_sent.connect(self.enter_awaiting_verdict_state)

        self.buttonAbort.clicked.connect(self.uploader.abort)
        self.enter_start_state()

    @QtCore.pyqtSlot()
    def upload(self):
        n = self.Name.text()
        if any([(i in n) for i in '"<*>|?/\\:']):
            QtWidgets.QMessageBox.information(
                self.client,
                "Invalid Name",
                "The mod name contains invalid characters: /\\<>|?:\"",
            )
            return

        iconpath = utils.iconPathToFull(self.modDir, self.modinfo.icon)
        infolder = False
        if (
            iconpath != ""
            and (
                os.path.commonprefix([
                    os.path.normcase(self.modDir),
                    os.path.normcase(iconpath),
                ])
                == os.path.normcase(self.modDir)
            )
        ):  # the icon is in the game folder
            # localpath = utils.fullPathToIcon(iconpath)
            infolder = True
        if iconpath != "" and not infolder:
            QtWidgets.QMessageBox.information(
                self.client,
                "Invalid Icon File",
                (
                    "The file {} is not located inside the modfolder. Copy the"
                    " icon file to your modfolder and change the mod_info.lua "
                    "accordingly".format(iconpath)
                ),
            )
            return
        self.start_upload()

    def start_upload(self) -> None:
        self.enter_zipping_state()
        self.uploader.run()

    def enter_start_state(self) -> None:
        self.progressBar.setValue(0)
        self.progressFrame.hide()
        self.UploadButton.show()
        self.checkRules.setChecked(False)

    def enter_zipping_state(self) -> None:
        self.UploadButton.hide()
        self.buttonAbort.setEnabled(False)
        self.progressFrame.show()
        self.labelStatusBarInfo.setText("Zipping files...")
        self.progressBar.setRange(0, 0)

    def enter_uploading_state(self) -> None:
        self.UploadButton.hide()
        self.progressFrame.show()
        self.buttonAbort.setEnabled(True)
        self.labelStatusBarInfo.setText("Uploading files...")
        self.progressBar.setRange(0, 100)

    def enter_awaiting_verdict_state(self) -> None:
        self.UploadButton.hide()
        self.buttonAbort.setEnabled(True)
        self.progressFrame.show()
        self.labelStatusBarInfo.setText("Waiting for server's verdict...")
        self.progressBar.setRange(0, 0)

    def enter_finish_state(self) -> None:
        self.progressBar.setValue(0)
        self.progressFrame.hide()
        self.UploadButton.show()
        self.UploadButton.setEnabled(False)

    def not_started(self) -> None:
        self.enter_start_state()
        critical_msgbox(
            self.client,
            "Mod uploading error",
            "Something went wrong zipping the mod files.",
        )

    def uploader_error(self, reply: QNetworkReply) -> None:
        self.enter_start_state()
        if reply.error() is reply.NetworkError.OperationCanceledError:
            return
        critical_msgbox(
            self.client,
            "Mod upload error",
            "Something went wrong uploading the mod files.",
            api_error_text(reply),
        )

    def completion_error(self, reply: QNetworkReply) -> None:
        self.enter_start_state()
        if reply.error() is reply.NetworkError.OperationCanceledError:
            return
        critical_msgbox(
            self.client,
            "Mod upload error",
            "Something went wrong uploading the mod files.",
            api_error_text(reply),
        )

    def complete(self) -> None:
        self.enter_finish_state()
        QtWidgets.QMessageBox.information(self.client, "Success", "Upload finished!")
        self.accept()

    @QtCore.pyqtSlot()
    def updateThumbnail(self):
        iconfilename = utils.iconPathToFull(self.modDir, self.modinfo.icon)
        if iconfilename == "":
            return False
        if os.path.splitext(iconfilename)[1].lower() == ".dds":
            old = iconfilename
            iconfilename = os.path.join(
                self.modDir,
                os.path.splitext(os.path.basename(iconfilename))[0] + ".png",
            )
            succes = utils.generateThumbnail(old, iconfilename)
            if not succes:
                QtWidgets.QMessageBox.information(
                    self.client,
                    "Invalid Icon File",
                    (
                        "Because FAF can't read DDS files, it tried to convert"
                        " it to a png. This failed. Try something else"
                    ),
                )
                return False
        try:
            self.Thumbnail.setPixmap(util.THEME.pixmap(iconfilename, themed=False).scaled(100, 100))
        except Exception as e:
            QtWidgets.QMessageBox.information(
                self.client,
                "Invalid Icon File",
                "This was not a valid icon file. Please pick a png or jpeg\n"
                f"Error: {e}",
            )
            return False
        self.modinfo.thumbnail = utils.fullPathToIcon(self.modDir, iconfilename)
        self.IconURI.setText(iconfilename)
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        self.uploader.abort()
        super().closeEvent(event)
