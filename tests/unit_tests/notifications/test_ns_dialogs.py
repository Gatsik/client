import pytest
from PyQt6.QtCore import Qt

from src.notifications.hook_newgame import NewGameDialog
from src.notifications.hook_partyinvite import PartyInviteDialog
from src.notifications.hook_useronline import UserOnlineDialog
from src.notifications.ns_type import NsType


@pytest.mark.parametrize(
    ("dialog_class", "event_type"),
    [
        (NewGameDialog, NsType.NEW_GAME),
        (PartyInviteDialog, NsType.PARTY_INVITE),
        (UserOnlineDialog, NsType.USER_ONLINE),
    ],
)
def test_save_button_saves_settings_once(qtbot, mocker, dialog_class, event_type):
    save_settings = mocker.patch.object(dialog_class, "saveSettings")
    dialog = dialog_class(mocker.Mock(), event_type)
    qtbot.addWidget(dialog)
    qtbot.mouseClick(dialog.btnSave, Qt.MouseButton.LeftButton)
    save_settings.assert_called_once()
