import logging
import time
from collections.abc import Sequence
from enum import IntEnum
from operator import itemgetter

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtGui import QPixmap
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QDialogButtonBox
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtWidgets import QInputDialog
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QStyleFactory
from PyQt6.QtWidgets import QWidget

from src import util
from src.chat.channel_view import ChatLineCssTemplate
from src.chat.chatter_model import ChatterLayoutElements
from src.chat.language_channel_config import LanguageChannelConfig
from src.client_import.importer import DataImporter
from src.client_import.page import ClientImportPage
from src.config import Settings
from src.connectivity.IceAdapterProcess import IceAdapterProcess
from src.fa.path import validate_game_path
from src.fa.path import validate_path
from src.notifications.ns_settings import NsSettings
from src.updater import ClientUpdateTools
from src.updater.base import UpdateChannel
from src.vaults.modvault.utils import setModFolder

FormClass, BaseClass = util.THEME.loadUiType("client/optionsdialog.ui")


class OptionsDialog(FormClass, BaseClass):
    class Tabs(IntEnum):
        GENERAL = 0
        CHAT = 1
        FORGED_ALLIANCE = 2
        NOTIFICATIONS = 3
        ICE_ADAPTER = 4
        CACHE = 5
        IMPORT = 6

    def __init__(
        self,
        parent: QWidget | None,
        update_tools: ClientUpdateTools,
        data_importers: Sequence[DataImporter] = (),
    ) -> None:
        BaseClass.__init__(self, parent)
        self.setModal(True)
        self.setupUi(self)

        self.splitter.setSizes(Settings.get_list("options/splitter", type=int, default=[]))
        self.splitter.splitterMoved.connect(self.save_splitter_sizes)

        self._update_tools = update_tools
        self._loaded = False
        self._restart_needed = False

        # TODO: make it work
        self.checkUseCustomTheme.setVisible(False)

        self.checkOwnReplayProcess.setToolTip(
            "Allows to run replays alongside running game process.\n"
            "All necessary game files will be downloaded into a separate\n"
            "dedicated directory, which will require additional disk space.",
        )
        self.checkLiveReplayWorkaround.setToolTip(
            "Use pipe to stream live replay data. Avoids Premature EOF errors,\n"
            "but the replay will end abruptly with no ability to select armies/see\n"
            "statistics/etc.",
        )

        self.import_page = ClientImportPage(
            source_combo=self.comboImportSource,
            path_edit=self.editImportPath,
            browse_button=self.buttonBrowseImportPath,
            status_label=self.labelImportStatus,
            import_buttons={"user_notes": self.buttonImportUserNotes},
            importers=data_importers,
            parent_widget=self,
        )

        self.tabSelection.currentRowChanged.connect(self.change_tab)

        self.buttonBox.accepted.connect(self.on_accepted)
        self.applyButton = self.buttonBox.button(QDialogButtonBox.StandardButton.Apply)
        self.applyButton.clicked.connect(self.apply_options)
        self.applyButton.setEnabled(False)

        self.resetButton = self.buttonBox.button(QDialogButtonBox.StandardButton.Reset)
        self.resetButton.clicked.connect(self.reset)

        self.cancelButton = self.buttonBox.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancelButton.clicked.connect(self.cancel)

        self._chat_formatter = util.THEME.readfile("chat/chatline.qhtml")
        self.lconfig = LanguageChannelConfig(Settings, util.THEME)
        self.languageChannelsView.setModel(self.lconfig.model())

        self.lconfig.model().dataChanged.connect(self.enable_apply_button)
        NsSettings.model.dataChanged.connect(self.enable_apply_button)

        self.connect_general_options_controls()
        self.connect_chat_options_controls()
        self.connect_game_options_controls()
        self.connect_data_options_controls()
        self.connect_requiring_restart()
        self.connect_enabling_apply_button()

        self._test_chat_lines = 0

    def change_tab(self, index: int) -> None:
        self.tabOption.setCurrentIndex(index)

    def showEvent(self, event: QShowEvent) -> None:
        if not self._loaded:
            self.populate_lists()
            self.configure_chat_area()
            self.load_options()
            self._loaded = True
            self._restart_needed = False
            self.applyButton.setEnabled(False)
        super().showEvent(event)

    def enable_apply_button(self) -> None:
        self.applyButton.setEnabled(True)

    def on_accepted(self) -> None:
        if self.applyButton.isEnabled():
            if not self.apply_options():
                return
        if self._restart_needed:
            QMessageBox.information(self, "Restart Needed", "FAF will quit now.")
            QApplication.quit()
        self.accept()

    def require_restart(self) -> None:
        self._restart_needed = True

    def reset(self) -> None:
        result = QMessageBox.question(
            self,
            "Clear Settings",
            "Are you sure you wish to clear all settings, "
            "login info, etc. used by this program?",
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            util.settings.clear()
            util.settings.sync()
            QMessageBox.information(self, "Restart Needed", "FAF will quit now.")
            QApplication.quit()

    def cancel(self) -> None:
        self.load_options()
        self.applyButton.setEnabled(False)
        self.reject()

    def apply_options(self) -> bool:
        if not self.validate_data_paths():
            return False
        self.save_options()
        Settings.apply()
        self.applyButton.setEnabled(False)
        return True

    def connect_general_options_controls(self) -> None:
        self.buttonLinkToSteam.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(Settings.get("STEAMLINK_URL"))))  # noqa: E501
        self.buttonCheckUpdates.clicked.connect(lambda: self._update_tools.checker.check(always_notify=True))  # noqa: E501
        self.buttonBrowseThemeFile.clicked.connect(lambda: self.browse_dir(self.lineCustomThemeFile))  # noqa: E501
        self.buttonBrowseLogPath.clicked.connect(lambda: self.browse_dir(self.lineFileLogPath))  # noqa:: E501

    def connect_chat_options_controls(self) -> None:
        self.buttonAddAutojoinChannel.clicked.connect(self.add_autojoin_channel)
        self.buttonRemoveAutojoinChannel.clicked.connect(self.remove_autojoin_channel)
        self.buttonChatClear.clicked.connect(self.clear_chat)

        self.spinChatFontSize.valueChanged.connect(self.send_test_chat_text)
        self.comboChatFontFamily.currentFontChanged.connect(self.send_test_chat_text)
        self.spinChatNickWidth.valueChanged.connect(self.send_test_chat_text)
        self.spinChatTimeWidth.valueChanged.connect(self.send_test_chat_text)
        self.spinChatPadding.valueChanged.connect(self.send_test_chat_text)
        self.lineChatLongNick.editingFinished.connect(self.send_test_chat_text)
        self.lineChatShortNick.editingFinished.connect(self.send_test_chat_text)

        self.lineChatSend.returnPressed.connect(self.send_custom_test_chat_text)

    def connect_game_options_controls(self) -> None:
        self.buttonBrowseFA.clicked.connect(lambda: self.browse_dir(self.editFAPath))
        self.buttonBrowseVault.clicked.connect(lambda: self.browse_dir(self.editVaultPath))

    def connect_data_options_controls(self) -> None:
        self.buttonBrowseDataPath.clicked.connect(lambda: self.browse_dir(self.editDataPath))
        self.buttonViewDataPath.clicked.connect(lambda: util.showDirInFileBrowser(self.editDataPath.text()))  # noqa: E501
        self.buttonClearGameFiles.clicked.connect(self.clear_game_files)

        self.buttonViewGameCache.clicked.connect(lambda: util.showDirInFileBrowser(util.GAME_CACHE_DIR))  # noqa: E501
        self.buttonClearGameCache.clicked.connect(lambda: util.clearDirectory(util.GAME_CACHE_DIR))
        self.buttonViewCache.clicked.connect(lambda: util.showDirInFileBrowser(util.CACHE_DIR))
        self.buttonClearCache.clicked.connect(self.clear_cache)
        self.buttonViewIceAdapters.clicked.connect(lambda: util.showDirInFileBrowser(util.ICE_ADAPTER_DIR))  # noqa: E501
        self.buttonClearIceAdapters.clicked.connect(lambda: util.clearDirectory(util.ICE_ADAPTER_DIR))  # noqa: E501
        self.buttonViewMapGenerators.clicked.connect(lambda: util.showDirInFileBrowser(util.MAPGEN_DIR))  # noqa: E501
        self.buttonClearMapGenerators.clicked.connect(lambda: util.clearDirectory(util.MAPGEN_DIR))

    def connect_requiring_restart(self) -> None:
        self.lineFileLogPath.textChanged.connect(self.require_restart)
        self.lineCustomThemeFile.textChanged.connect(self.require_restart)

        self.editFAPath.textChanged.connect(self.require_restart)
        self.editVaultPath.textChanged.connect(self.require_restart)

        self.editDataPath.textChanged.connect(self.require_restart)

    def connect_enabling_apply_button(self) -> None:
        self.checkAutoLogin.toggled.connect(self.enable_apply_button)
        self.comboStyle.currentIndexChanged.connect(self.enable_apply_button)
        self.comboColorScheme.currentIndexChanged.connect(self.enable_apply_button)
        self.checkUseCustomTheme.toggled.connect(self.enable_apply_button)
        self.lineCustomThemeFile.textChanged.connect(self.enable_apply_button)
        self.checkFileLog.toggled.connect(self.enable_apply_button)
        self.comboLogLevel.currentIndexChanged.connect(self.enable_apply_button)
        self.lineFileLogPath.textChanged.connect(self.enable_apply_button)
        self.checkFileLogBackup.toggled.connect(self.enable_apply_button)
        self.spinFileLogSize.valueChanged.connect(self.enable_apply_button)
        self.spinLogBackupCount.valueChanged.connect(self.enable_apply_button)
        self.checkProgramUpdates.toggled.connect(self.enable_apply_button)
        self.comboUpdateChannel.currentIndexChanged.connect(self.enable_apply_button)
        self.checkOldReleases.toggled.connect(self.enable_apply_button)

        self.checkColoredNames.toggled.connect(self.enable_apply_button)
        self.checkFriendsOnTop.toggled.connect(self.enable_apply_button)
        self.hideChattersList.itemSelectionChanged.connect(self.enable_apply_button)
        self.checkJoinsParts.toggled.connect(self.enable_apply_button)
        self.checkFriendGames.toggled.connect(self.enable_apply_button)
        self.checkFriendReplays.toggled.connect(self.enable_apply_button)
        self.checkSoundEffects.toggled.connect(self.enable_apply_button)
        self.checkIgnoreFoes.toggled.connect(self.enable_apply_button)
        self.checkNewbiesChannel.toggled.connect(self.enable_apply_button)
        self.autojoinChannelsBox.toggled.connect(self.enable_apply_button)
        self.spinChatFontSize.valueChanged.connect(self.enable_apply_button)
        self.comboChatFontFamily.currentFontChanged.connect(self.enable_apply_button)
        self.spinChatNickWidth.valueChanged.connect(self.enable_apply_button)
        self.spinChatTimeWidth.valueChanged.connect(self.enable_apply_button)
        self.spinChatPadding.valueChanged.connect(self.enable_apply_button)

        self.editFAPath.textChanged.connect(self.enable_apply_button)
        self.checkForceAffinity.toggled.connect(self.enable_apply_button)
        self.checkSaveGameLogs.toggled.connect(self.enable_apply_button)
        self.spinGameLogsCount.valueChanged.connect(self.enable_apply_button)
        self.editDataPath.textChanged.connect(self.enable_apply_button)
        self.checkOwnReplayProcess.toggled.connect(self.enable_apply_button)
        self.checkLiveReplayWorkaround.toggled.connect(self.enable_apply_button)
        self.editVaultPath.textChanged.connect(self.enable_apply_button)
        self.checkAutoDownloadMods.toggled.connect(self.enable_apply_button)
        self.checkAutoDownloadMaps.toggled.connect(self.enable_apply_button)
        self.checkAutoGenerateMaps.toggled.connect(self.enable_apply_button)
        self.checkAutoDeleteGeneratedMaps.toggled.connect(self.enable_apply_button)

        self.notificationsBox.toggled.connect(self.enable_apply_button)
        self.nsIngameComboBox.currentIndexChanged.connect(self.enable_apply_button)
        self.nsPopLifetime.valueChanged.connect(self.enable_apply_button)
        self.nsPositionComboBox.currentIndexChanged.connect(self.enable_apply_button)

        self.comboAdapterSelection.currentIndexChanged.connect(self.enable_apply_button)
        self.javaInfoWindowBox.toggled.connect(self.enable_apply_button)
        self.spinJavaWindowLaunchDelay.valueChanged.connect(self.enable_apply_button)
        self.javaVersionBox.toggled.connect(self.enable_apply_button)
        self.lineJavaVersion.textChanged.connect(self.enable_apply_button)
        self.goVersionBox.toggled.connect(self.enable_apply_button)
        self.lineGoVersion.textChanged.connect(self.enable_apply_button)
        self.checkConsentLogSharing.toggled.connect(self.enable_apply_button)
        self.comboForceRelay.currentIndexChanged.connect(self.enable_apply_button)

        self.gameCacheBox.toggled.connect(self.enable_apply_button)
        self.spinGameCacheAge.valueChanged.connect(self.enable_apply_button)
        self.ICEAdapterCacheBox.toggled.connect(self.enable_apply_button)
        self.spinIceAdapterAge.valueChanged.connect(self.enable_apply_button)
        self.mapGeneratorsBox.toggled.connect(self.enable_apply_button)
        self.spinMapGenAge.valueChanged.connect(self.enable_apply_button)

    def populate_lists(self) -> None:
        self.comboStyle.addItems(QStyleFactory.keys())
        self.comboColorScheme.addItems(map(str, util.THEME.listThemes()))
        self.comboUpdateChannel.addItems(item.name for item in UpdateChannel)

        levels = logging.getLevelNamesMapping()
        for name, level in sorted(levels.items(), key=itemgetter(1), reverse=True):
            self.comboLogLevel.addItem(name, level)

        self.hideChattersList.addItems(elem.name.title() for elem in ChatterLayoutElements)

    def load_options(self) -> None:
        self.load_general_options()
        self.load_chat_options()
        self.load_game_options()
        self.load_notifications_options()
        self.load_ice_adapter_options()
        self.load_data_options()

    def load_general_options(self) -> None:
        self.checkAutoLogin.setChecked(Settings.get("user/remember", True, type=bool))

        self.comboColorScheme.setCurrentText(str(util.THEME.theme))
        with Settings.group("theme") as group:
            self.comboStyle.setCurrentText(group.value("style", "windowsvista"))
            self.checkUseCustomTheme.setChecked(group.value("custom", False, type=bool))
            self.lineCustomThemeFile.setText(group.value("custom_path", ""))

        with Settings.group("client/logs") as group:
            self.checkFileLog.setChecked(group.value("enable", True, type=bool))
            self.lineFileLogPath.setText(group.value("path", util.LOG_DIR))
            self.comboLogLevel.setCurrentIndex(
                self.comboLogLevel.findData(group.value("level", logging.INFO, type=int)),
            )
            self.checkFileLogBackup.setChecked(group.value("backup", True, type=bool))
            self.spinFileLogSize.setValue(
                group.value("max_size", 512 * 1024, type=int) // 1024,
            )
            self.spinLogBackupCount.setValue(group.value("backup_count", 1, type=int))

        with Settings.group("updater") as group:
            self.checkProgramUpdates.setChecked(group.value("autocheck", True, type=bool))
            self.comboUpdateChannel.setCurrentText(
                group.value("branch", UpdateChannel.Prerelease.name),
            )
            self.checkOldReleases.setChecked(group.value("downgrade", False, type=bool))

    def load_chat_options(self) -> None:
        self.lconfig.load_data()

        with Settings.group("chat") as group:
            self.checkColoredNames.setChecked(group.value("coloredNicknames", False, type=bool))
            self.checkFriendsOnTop.setChecked(group.value("friendsontop", True, type=bool))
            self.checkJoinsParts.setChecked(group.value("joinsparts", False, type=bool))
            self.checkFriendGames.setChecked(group.value("opengames", True, type=bool))
            self.checkFriendReplays.setChecked(group.value("livereplays", True, type=bool))
            self.checkSoundEffects.setChecked(group.value("soundeffects", True, type=bool))
            self.checkIgnoreFoes.setChecked(group.value("ignoreFoes", True, type=bool))
            self.checkNewbiesChannel.setChecked(group.value("newbiesChannel", True, type=bool))
            self.autojoinChannelsBox.setChecked(group.value("auto_join", True, type=bool))
            self.listAutojoinChannels.clear()
            self.listAutojoinChannels.addItems(
                [
                    ch.removeprefix("#")
                    for ch in group.value("auto_join_channels", [], type=str)
                    if ch
                ],
            )

            hide_chatter_items = group.value("hide_chatter_items", "")
            for index, elem in enumerate(ChatterLayoutElements):
                list_item = self.hideChattersList.item(index)
                list_item.setSelected(elem.value in hide_chatter_items)

        with Settings.group("chat/font") as group:
            self.spinChatFontSize.setValue(group.value("size", 9, type=int))
            self.comboChatFontFamily.setCurrentText(group.value("family", "Segoe UI"))
            self.spinChatNickWidth.setValue(group.value("nick_width", 101, type=int))
            self.spinChatTimeWidth.setValue(group.value("time_width", 32, type=int))
            self.spinChatPadding.setValue(group.value("padding", 10, type=int))

    def configure_chat_area(self) -> None:
        self._reset_chat_area()
        template = ChatLineCssTemplate(util.THEME, self.parent().player_colors)
        doc = self.browserChatArea.document()
        doc.setDefaultStyleSheet(template.css)

    def load_game_options(self) -> None:
        self.editFAPath.setText(Settings.get("ForgedAlliance/app/path", ""))
        self.editVaultPath.setText(util.VAULTS_BASE_DIR)

        with Settings.group("game") as group:
            self.checkForceAffinity.setChecked(group.value("force_affinity", True, type=bool))
            self.checkSaveGameLogs.setChecked(group.value("logs", True, type=bool))
            self.spinGameLogsCount.setValue(group.value("logs_max_count", 30, type=int))
            self.checkOwnReplayProcess.setChecked(group.value("replay_process", True, type=bool))
            self.checkLiveReplayWorkaround.setChecked(
                group.value("pipe_live_replay", True, type=bool),
            )

        self.checkAutoDownloadMods.setChecked(Settings.get("mods/autodownload", False, type=bool))
        self.checkAutoDownloadMaps.setChecked(Settings.get("maps/autodownload", False, type=bool))
        self.checkAutoGenerateMaps.setChecked(
            Settings.get("mapGenerator/autostart", False, type=bool),
        )
        self.checkAutoDeleteGeneratedMaps.setChecked(
            Settings.get("maps/autodelete_generated", True, type=bool),
        )

    def load_notifications_options(self) -> None:
        self.tableView.setModel(NsSettings.model)
        for row in range(0, NsSettings.model.rowCount(None)):
            self.tableView.setIndexWidget(
                NsSettings.model.createIndex(row, 4),
                NsSettings.model.getHook(row).settings(),
            )
        self.notificationsBox.setChecked(NsSettings.enabled)
        self.nsIngameComboBox.setCurrentIndex(NsSettings.ingame_notifications.value)
        self.nsPopLifetime.setValue(NsSettings.popup_lifetime)
        self.nsPositionComboBox.setCurrentIndex(NsSettings.popup_position.value)

    def load_ice_adapter_options(self) -> None:
        with Settings.group("iceadapter") as group:
            self.comboAdapterSelection.setCurrentIndex(group.value("kind", "java") != "java")
            self.javaInfoWindowBox.setChecked(group.value("info_window", True, type=bool))
            self.spinJavaWindowLaunchDelay.setValue(group.value("delay_ui_seconds", 10, type=int))
            self.javaVersionBox.setChecked(group.value("force_java_version", False, type=bool))
            self.lineJavaVersion.setText(group.value("java_version", ""))
            self.goVersionBox.setChecked(group.value("force_go_version", False, type=bool))
            self.lineGoVersion.setText(group.value("go_version", ""))
            self.checkConsentLogSharing.setChecked(
                group.value("consent_log_sharing", False, type=bool),
            )
            force_relay = IceAdapterProcess.ForceRelay(group.value("force_relay", "auto"))
            self.comboForceRelay.setCurrentIndex(
                list(IceAdapterProcess.ForceRelay).index(force_relay),
            )

    def load_data_options(self) -> None:
        self.editDataPath.setText(Settings.get("client/data_path"))

        with Settings.group("cache") as group:
            self.gameCacheBox.setChecked(group.value("enabled", True, type=bool))
            self.spinGameCacheAge.setValue(group.value("store_duration", 30, type=int))

        with Settings.group("iceadapter") as group:
            self.ICEAdapterCacheBox.setChecked(group.value("cache", True, type=bool))
            self.spinIceAdapterAge.setValue(group.value("store_duration", 30, type=int))

        with Settings.group("mapGenerator") as group:
            self.mapGeneratorsBox.setChecked(group.value("cache", True, type=bool))
            self.spinMapGenAge.setValue(group.value("store_duration", 30, type=int))

    def save_options(self) -> None:
        self.save_general_options()
        self.save_chat_options()
        self.save_game_options()
        self.save_notifications_options()
        self.save_ice_adapter_options()
        self.save_data_options()

    def save_general_options(self) -> None:
        Settings.set("user/remember", self.checkAutoLogin.isChecked())

        with Settings.group("theme") as group:
            group.setValue("style", self.comboStyle.currentText())
            group.setValue("theme/name", self.comboColorScheme.currentText())
            group.setValue("custom", self.checkUseCustomTheme.isChecked())
            group.setValue("custom_path", self.lineCustomThemeFile.text())

        with Settings.group("client/logs") as group:
            group.setValue("enable", self.checkFileLog.isChecked())
            if text := self.lineFileLogPath.text().strip():
                group.setValue("path", text)
            group.setValue("level", self.comboLogLevel.currentData())
            group.setValue("backup", self.checkFileLogBackup.isChecked())
            group.setValue("max_size", self.spinFileLogSize.value() * 1024)
            group.setValue("backup_count", self.spinLogBackupCount.value())

        with Settings.group("updater") as group:
            group.setValue("autocheck", self.checkProgramUpdates.isChecked())
            group.setValue("branch", self.comboUpdateChannel.currentText())
            group.setValue("downgrade", self.checkOldReleases.isChecked())

    def save_chat_options(self) -> None:
        with Settings.group("chat") as group:
            group.setValue("coloredNicknames", self.checkColoredNames.isChecked())
            group.setValue("friendsontop", self.checkFriendsOnTop.isChecked())
            group.setValue("joinsparts", self.checkJoinsParts.isChecked())
            group.setValue("opengames", self.checkFriendGames.isChecked())
            group.setValue("livereplays", self.checkFriendReplays.isChecked())
            group.setValue("soundeffects", self.checkSoundEffects.isChecked())
            group.setValue("ignoreFoes", self.checkIgnoreFoes.isChecked())
            group.setValue("newbiesChannel", self.checkNewbiesChannel.isChecked())
            group.setValue("auto_join", self.autojoinChannelsBox.isChecked())
            group.setValue(
                "auto_join_channels",
                [
                    f"#{self.listAutojoinChannels.item(row).text()}"
                    for row in range(self.listAutojoinChannels.count())
                ],
            )
            group.setValue(
                "hide_chatter_items",
                " ".join(
                    elem.value for i, elem in enumerate(ChatterLayoutElements)
                    if self.hideChattersList.item(i).isSelected()
                ),
            )

        with Settings.group("chat/font") as group:
            group.setValue("size", self.spinChatFontSize.value())
            group.setValue("family", self.comboChatFontFamily.currentFont().family())
            group.setValue("nick_width", self.spinChatNickWidth.value())
            group.setValue("time_width", self.spinChatTimeWidth.value())
            group.setValue("padding", self.spinChatPadding.value())

        self.lconfig.save_channels()

    def save_game_options(self) -> None:
        with Settings.group("game") as group:
            group.setValue("force_affinity", self.checkForceAffinity.isChecked())
            group.setValue("logs", self.checkSaveGameLogs.isChecked())
            group.setValue("logs_max_count", self.spinGameLogsCount.value())
            group.setValue("replay_process", self.checkOwnReplayProcess.isChecked())
            group.setValue("pipe_live_replay", self.checkLiveReplayWorkaround.isChecked())

        with Settings.group("maps") as group:
            group.setValue("autodownload", self.checkAutoDownloadMaps.isChecked())
            group.setValue("autodelete_generated", self.checkAutoDeleteGeneratedMaps.isChecked())

        if text := self.editFAPath.text().strip():
            Settings.set("ForgedAlliance/app/path", text)
        if text := self.editVaultPath.text().strip():
            Settings.set("vault/custom_path", text)
        Settings.set("mods/autodownload", self.checkAutoDownloadMods.isChecked())
        Settings.set("mapGenerator/autostart", self.checkAutoGenerateMaps.isChecked())

        if (vault_path := self.editVaultPath.text().strip()) and vault_path != util.VAULTS_BASE_DIR:
            util.change_vaults_base_dir(vault_path)
            setModFolder()

    def save_notifications_options(self) -> None:
        with Settings.group("notifications") as group:
            group.setValue("enabled", self.notificationsBox.isChecked())
            group.setValue("ingame", self.nsIngameComboBox.currentIndex())
            group.setValue("popup_lifetime", self.nsPopLifetime.value())
            group.setValue("popup_position", self.nsPositionComboBox.currentIndex())

    def save_ice_adapter_options(self) -> None:
        with Settings.group("iceadapter") as group:
            group.setValue("kind", ["java", "go"][self.comboAdapterSelection.currentIndex()])
            group.setValue("info_window", self.javaInfoWindowBox.isChecked())
            group.setValue("delay_ui_seconds", self.spinJavaWindowLaunchDelay.value())
            group.setValue("force_java_version", self.javaVersionBox.isChecked())
            group.setValue("java_version", self.lineJavaVersion.text())
            group.setValue("force_go_version", self.goVersionBox.isChecked())
            group.setValue("go_version", self.lineGoVersion.text())
            group.setValue("consent_log_sharing", self.checkConsentLogSharing.isChecked())
            group.setValue(
                "force_relay",
                list(IceAdapterProcess.ForceRelay)[self.comboForceRelay.currentIndex()].value,
            )

    def save_data_options(self) -> None:
        Settings.set("client/data_path", self.editDataPath.text())

        with Settings.group("cache") as group:
            group.setValue("enabled", self.gameCacheBox.isChecked())
            group.setValue("store_duration", self.spinGameCacheAge.value())

        with Settings.group("iceadapter") as group:
            group.setValue("cache", self.ICEAdapterCacheBox.isChecked())
            group.setValue("store_duration", self.spinIceAdapterAge.value())

        with Settings.group("mapGenerator") as group:
            group.setValue("cache", self.mapGeneratorsBox.isChecked())
            group.setValue("store_duration", self.spinMapGenAge.value())

    def validate_data_paths(self) -> bool:
        suggestion = (
            "{path_type} Path is invalid. Make sure:\n"
            "1. It exists\n"
            "2. It doesn't contain any non-ASCII characters\n"
            "3. It doesn't end with slash ('/') or ('\\')\n\n"
            "{path}"
        )
        if self.editFAPath.text() and not validate_game_path(self.editFAPath.text()):
            QMessageBox.critical(
                self,
                "Invalid Path",
                suggestion.format(path_type="Game", path=self.editFAPath.text()),
            )
            self.tabSelection.setCurrentRow(self.Tabs.FORGED_ALLIANCE)
            return False
        if self.editDataPath.text() and not validate_path(self.editDataPath.text()):
            QMessageBox.critical(
                self,
                "Invalid Path",
                suggestion.format(path_type="Data", path=self.editDataPath.text()),
            )
            self.tabSelection.setCurrentRow(self.Tabs.FORGED_ALLIANCE)
            return False
        if self.editVaultPath.text() and not validate_path(self.editVaultPath.text()):
            QMessageBox.critical(
                self,
                "Invalid Path",
                suggestion.format(path_type="Vault", path=self.editVaultPath.text()),
            )
            self.tabSelection.setCurrentRow(self.Tabs.FORGED_ALLIANCE)
            return False
        return True

    def clear_game_files(self) -> None:
        util.clearDirectory(util.BIN_DIR)
        util.clearDirectory(util.GAMEDATA_DIR)

    def clear_cache(self) -> None:
        if util.clearDirectory(util.CACHE_DIR):
            self._restart_needed = True

    def browse_dir(self, line_edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Directory",
            line_edit.text() or "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if directory:
            line_edit.setText(directory)

    def save_splitter_sizes(self) -> None:
        Settings.set("options/splitter", self.splitter.sizes())

    def add_autojoin_channel(self) -> None:
        channel, ok = QInputDialog.getText(self, "Add Channel", "Enter channel name:")
        if ok and (normalized_name := channel.removeprefix("#").strip()):
            self.listAutojoinChannels.addItem(normalized_name)
            self.enable_apply_button()

    def remove_autojoin_channel(self) -> None:
        current = self.listAutojoinChannels.currentItem()
        if current is None:
            return
        self.listAutojoinChannels.takeItem(self.listAutojoinChannels.row(current))
        self.enable_apply_button()

    def send_custom_test_chat_text(self) -> None:
        if self._test_chat_lines > 8:
            return
        self._send_test_chat_text(
            self.parent().me.login or "Tester", self.lineChatSend.text(), "me player",
        )
        self.lineChatSend.clear()
        self._test_chat_lines += 1

    def _reset_chat_area(self) -> None:
        self.browserChatArea.clear()
        doc = self.browserChatArea.document()
        avatar_src = util.THEME.themepath("chat/avatar/avatar_blank.png")
        doc.addResource(
            doc.ResourceType.ImageResource,
            QUrl("avatar_blank"),
            QPixmap(avatar_src).scaled(40, 20),
        )

    def send_test_chat_text(self) -> None:
        self._reset_chat_area()
        self._send_test_chat_text(
            self.lineChatLongNick.text(),
            "The quick brown fox jumps over the lazy dog",
        )
        self._send_test_chat_text(self.lineChatShortNick.text(), "Etaoin shrdlu")

    def _send_test_chat_text(self, sender: str, text: str, tags: str = "player") -> None:
        font = self.comboChatFontFamily.currentFont()
        font.setPointSize(self.spinChatFontSize.value())
        self.browserChatArea.setFont(font)

        metrics = QFontMetrics(font)
        elided_sender = metrics.elidedText(
            sender,
            Qt.TextElideMode.ElideRight,
            self.spinChatNickWidth.value() - metrics.horizontalAdvance(":"),
        )
        avatar = '<img src="avatar_blank" title="Blank avatar"/>'
        formatted = self._chat_formatter.format(
            time=time.strftime("%H:%M", time.localtime()),
            time_width=self.spinChatTimeWidth.value(),
            sender_width=self.spinChatNickWidth.value(),
            sender=sender,
            elided_sender=elided_sender + ":",
            text=text,
            avatar=avatar,
            tags=tags,
            padding=self.spinChatPadding.value(),
        )
        self.browserChatArea.append(formatted)

    def clear_chat(self) -> None:
        self._test_chat_lines = 0
        self._reset_chat_area()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            self.focusWidget() is self.lineChatSend
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            return
        super().keyPressEvent(event)
