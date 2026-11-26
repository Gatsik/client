"""
Settings for notifications: if a new game is hosted.
"""
from PyQt6 import QtCore

from src import config
from src import util
from src.config import Settings
from src.notifications.ns_hook import NsHook
from src.notifications.ns_type import NsType


class NsHookNewGame(NsHook):
    def __init__(self):
        NsHook.__init__(self, NsType.NEW_GAME)
        self.button.setEnabled(True)
        self.dialog = NewGameDialog(self, self.eventType)
        self.button.clicked.connect(self.dialog.show)


FormClass, BaseClass = util.THEME.loadUiType("notification_system/new_game.ui")


class NewGameDialog(FormClass, BaseClass):
    def __init__(self, parent, eventType):
        BaseClass.__init__(self)
        self.setModal(True)
        self.parent = parent
        self.eventType = eventType
        self._settings_key = f'notifications/{eventType}'
        self.setupUi(self)
        self.btnSave.clicked.connect(self.on_save_clicked)
        self.setStyleSheet(util.THEME.stylesheet)

        # remove help button
        self.setWindowFlags(
            self.windowFlags() & (~QtCore.Qt.WindowType.WindowContextHelpButtonHint),
        )

        self.loadSettings()

    def loadSettings(self):
        self.mode = Settings.get(self._settings_key + '/mode', 'friends')

        if self.mode == 'friends':
            self.checkBoxFriends.setCheckState(QtCore.Qt.CheckState.Checked)
        else:
            self.checkBoxFriends.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.parent.mode = self.mode

    def saveSettings(self):
        config.Settings.set(self._settings_key + '/mode', self.mode)
        self.parent.mode = self.mode

    @QtCore.pyqtSlot()
    def on_save_clicked(self):
        if self.checkBoxFriends.checkState() == QtCore.Qt.CheckState.Checked:
            self.mode = 'friends'
        else:
            self.mode = 'all'
        self.saveSettings()
        self.hide()
