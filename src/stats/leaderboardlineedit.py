from PyQt6 import QtCore
from PyQt6 import QtWidgets
from PyQt6.QtGui import QFocusEvent


# TODO: probably create a common ancestor of ChatLineEdit and this
class LeaderboardLineEdit(QtWidgets.QLineEdit):
    typingFinished = QtCore.pyqtSignal(str)
    TYPING_DELAY_MS = 300

    def __init__(self, parent):
        super().__init__(parent)
        self.completionStarted = False
        self.currenLocalChatter = None
        self.LocalNameList = []
        self.completionList = None

        self._typing_timer = QtCore.QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(self.TYPING_DELAY_MS)
        self._typing_timer.timeout.connect(lambda: self.typingFinished.emit(self.text()))
        self.textEdited.connect(lambda _: self._typing_timer.start())
        self.returnPressed.connect(self._typing_timer.stop)

    def focusOutEvent(self, event: QFocusEvent | None) -> None:
        self._typing_timer.stop()
        super().focusOutEvent(event)

    def set_completion_list(self, list_):
        self.completionList = list_

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            # Swallow a selection of keypresses that we want for our history
            # support.
            if event.key() == QtCore.Qt.Key.Key_Tab:
                self.try_completion()
                return True
            else:
                self.cancel_completion()
                return QtWidgets.QLineEdit.event(self, event)

        # All other events (non-keypress)
        return QtWidgets.QLineEdit.event(self, event)

    def try_completion(self):
        if not self.completionStarted:
            # no completion on empty line
            if self.text() == "":
                return
            # no completion if last character is a space
            if self.text().rfind(" ") == (len(self.text()) - 1):
                return

            self.completionStarted = True
            self.LocalNameList = []

            # make a copy of users because the list might change frequently
            # giving all kind of problems
            if self.completionList is not None:
                for name in self.completionList:
                    if name.lower().startswith(self.text().lower()):
                        self.LocalNameList.append(name)

            if len(self.LocalNameList) > 0:
                self.LocalNameList.sort(key=lambda login: login.lower())
                self.currenLoginIndex = 0
                self.setText(self.LocalNameList[self.currenLoginIndex])
            else:
                self.currenLoginIndex = None
        else:
            if self.currenLoginIndex is not None:
                self.currenLoginIndex += 1
                self.currenLoginIndex %= len(self.LocalNameList)
                self.setText(self.LocalNameList[self.currenLoginIndex])

    def cancel_completion(self):
        self.completionStarted = False
