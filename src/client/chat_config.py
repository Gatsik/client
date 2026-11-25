from PyQt6 import QtCore

from src.chat.chatter_group import ChatterGroup
from src.chat.chatter_model import ChatterLayoutElements
from src.client.user import SignallingSet  # TODO - move to util


def signal_property(public):
    private = f"_{public}"

    def get(self):
        return getattr(self, private)

    def set_(self, v):
        old = getattr(self, private)
        if v != old:
            setattr(self, private, v)
            self.updated.emit(public)

    return property(get, set_)


class ChatConfig(QtCore.QObject):
    updated = QtCore.pyqtSignal(str)

    soundeffects = signal_property("soundeffects")
    joinsparts = signal_property("joinsparts")
    friendsontop = signal_property("friendsontop")
    newbies_channel = signal_property("newbies_channel")
    channel_blink_interval = signal_property("channel_blink_interval")
    channel_ping_timeout = signal_property("channel_ping_timeout")
    max_chat_lines = signal_property("max_chat_lines")
    ignore_foes = signal_property("ignore_foes")

    def __init__(self, settings: QtCore.QSettings) -> None:
        QtCore.QObject.__init__(self)
        self._settings = settings
        self._soundeffects = None
        self._joinsparts = None
        self._friendsontop = None
        self._newbies_channel = None
        self._channel_blink_interval = None
        self._channel_ping_timeout = None
        self._max_chat_lines = None
        self._ignore_foes = None

        self.hide_chatter_items = SignallingSet[ChatterLayoutElements]()
        self.hide_chatter_items.added.connect(self._emit_hidden_items)
        self.hide_chatter_items.removed.connect(self._emit_hidden_items)

        self.collapsed_chatter_groups = SignallingSet[ChatterGroup]()
        self.collapsed_chatter_groups.added.connect(self._at_collapsed_groups_changed)
        self.collapsed_chatter_groups.removed.connect(self._at_collapsed_groups_changed)

        self.chat_line_trim_count = 1
        self.announcement_channels = []
        self.channel_greeting = []
        self.channels_to_greet_in = []
        self.newbie_channel_game_threshold = 0
        self.load_settings()

    def _emit_hidden_items(self):
        self.updated.emit("hide_chatter_items")

    def _at_collapsed_groups_changed(self) -> None:
        groups = " ".join(group.name for group in self.collapsed_chatter_groups)
        self._settings.setValue("chat/collapsed_chatter_groups", groups)
        self.updated.emit("collapsed_chatter_groups")

    def toggle_chatter_group(self, group: ChatterGroup) -> None:
        if group in self.collapsed_chatter_groups:
            self.collapsed_chatter_groups.discard(group)
        else:
            self.collapsed_chatter_groups.add(group)

    def load_settings(self) -> None:
        s = self._settings
        self.soundeffects = s.value("chat/soundeffects", True, type=bool)
        self.joinsparts = s.value("chat/joinsparts", False, type=bool)
        self.friendsontop = s.value("chat/friendsontop", False, type=bool)
        self.newbies_channel = s.value("chat/newbiesChannel", True, type=bool)
        self.ignore_foes = s.value("chat/ignoreFoes", True, type=bool)

        items = s.value("chat/hide_chatter_items", "")
        items = items.split()
        hidden = set()
        for item in items:
            try:
                enum_val = ChatterLayoutElements(item)
                hidden.add(enum_val)
            except ValueError:
                pass
        self.hide_chatter_items.clear()
        self.hide_chatter_items |= hidden

        names = (s.value("chat/collapsed_chatter_groups", ChatterGroup.AWAY.name) or "").split()
        collapsed = {ChatterGroup[name] for name in names if name in ChatterGroup.__members__}
        if collapsed != set(self.collapsed_chatter_groups):
            self.collapsed_chatter_groups.clear()
            self.collapsed_chatter_groups |= collapsed

    def save_settings(self):
        s = self._settings
        s.setValue("chat/soundeffects", self.soundeffects)
        s.setValue("chat/joinsparts", self.joinsparts)
        s.setValue("chat/newbiesChannel", self.newbies_channel)
        s.setValue("chat/friendsontop", self.friendsontop)
        s.setValue("chat/ignoreFoes", self.ignore_foes)

        items = " ".join(item.value for item in self.hide_chatter_items)
        s.setValue("chat/hide_chatter_items", items)
