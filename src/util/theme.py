import hashlib
import importlib
import logging
import os
import re
from collections.abc import Callable
from collections.abc import Iterable
from functools import cached_property
from typing import Any
from typing import Concatenate

from PyQt6 import QtCore
from PyQt6 import QtGui
from PyQt6 import QtWidgets
from PyQt6 import uic
from semantic_version import Version

from src.config import SettingsCls

logger = logging.getLogger(__name__)


def _noneIfNoFile[**P, R](
    fun: Callable[Concatenate[Theme, P], R],
) -> Callable[Concatenate[Theme, P], R | None]:
    def _fun(self: Theme, *args: P.args, **kwargs: P.kwargs) -> R | None:
        filename, = args
        assert isinstance(filename, str)
        if not os.path.isfile(self._themepath(filename)):
            return None
        return fun(self, *args, **kwargs)
    return _fun


def _warn_resource_null[**P, R](
    fn: Callable[Concatenate[ThemeSet, P], R],
) -> Callable[Concatenate[ThemeSet, P], R]:
    def _nullcheck(self: ThemeSet, *args: P.args, **kwargs: P.kwargs) -> R:
        filename, = args
        assert isinstance(filename, str)
        ret = fn(self, *args, **kwargs)
        if ret is None:
            logger.warning("Failed to load resource '%s' in theme. %s", filename, fn.__name__)
        return ret
    return _nullcheck


class Theme:
    """
    Represents a single FAF client theme.
    """

    def __init__(
        self,
        themedir: str | None,
        name: str | None,
        *,
        builtin: bool = False,
        compiled_package: str | None = None,
    ) -> None:
        self._themedir = themedir
        self.name = name
        self._pixmapcache: dict[str, QtGui.QPixmap | None] = {}
        self._builtin = builtin
        self._compiled_package = compiled_package

    @cached_property
    def stylesheet(self) -> str | None:
        if (
            self.name is None  # unthemed
            and QtWidgets.QApplication.style().name() == "windowsvista"
        ):
            return self.readstylesheet("client/client_light.css")
        else:
            return self.readstylesheet("client/client.css")

    def is_builtin(self) -> bool:
        return self._builtin

    def __str__(self):
        return str(self.name)

    def _themepath(self, filename: str) -> str:
        if self._themedir is None:
            return filename
        else:
            return os.path.join(self._themedir, filename)

    @property
    def themedir(self):
        return str(self._themedir)

    def version(self):
        if self._themedir is None:
            return None
        try:
            version_file = self._themepath("version")
            with open(version_file) as f:
                return Version(f.read().strip())
        except (OSError, ValueError):
            return None

    def pixmap(self, filename: str) -> QtGui.QPixmap | None:
        """
        This function loads a pixmap from a themed directory, or anywhere.
        It also stores them in a cache dictionary (may or may not be necessary
        depending on how Qt works under the hood)
        """
        try:
            return self._pixmapcache[filename]
        except KeyError:
            if os.path.isfile(self._themepath(filename)):
                pix = QtGui.QPixmap(self._themepath(filename))
            else:
                pix = None

        self._pixmapcache[filename] = pix
        return pix

    @_noneIfNoFile
    def loadUi(self, filename):
        # Loads and compiles a Qt Ui file via uic.
        return uic.loadUi(self._themepath(filename))

    @_noneIfNoFile
    def loadUiType(self, filename):
        # Loads and compiles a Qt Ui file via uic, and returns the Type and
        # Basetype as a tuple
        if (ui_type := self._load_compiled_ui_type(filename)) is not None:
            return ui_type
        return uic.loadUiType(self._themepath(filename))

    def _load_compiled_ui_type(self, filename: str) -> tuple[type, type] | None:
        if self._compiled_package is None:
            return None
        module_path = filename.removesuffix(".ui").replace("/", ".")
        try:
            module = importlib.import_module(f"{self._compiled_package}.{module_path}")
        except ImportError:
            return None
        with open(self._themepath(filename), "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != module.UI_HASH:
                logger.warning("Compiled %s is outdated, falling back to uic", filename)
                return None
        return module.FormClass, module.BaseClass

    @_noneIfNoFile
    def readlines(self, filename):
        # Reads and returns the contents of a file in the theme dir.
        with open(self._themepath(filename)) as f:
            logger.debug("Read themed file: " + filename)
            return f.readlines()

    @_noneIfNoFile
    def readstylesheet(self, filename: str) -> str | None:
        with open(self._themepath(filename)) as f:
            logger.info("Read themed stylesheet: %s", filename)
            sheet = f.read()
            if self._themedir is not None:
                return sheet.replace("%THEMEPATH%", self._themedir.replace("\\", "/"))
            else:
                return sheet

    @_noneIfNoFile
    def themeurl(self, filename):
        """
        This creates an url to use for a local stylesheet. It's a bit of a
        hack because Qt has a bug identifying proper localfile QUrls
        """
        return QtCore.QUrl(
            "file://" + self._themepath(filename).replace("\\", "/"),
        )

    @_noneIfNoFile
    def themepath(self, filename: str) -> str:
        return self._themepath(filename).replace("\\", "/")

    @_noneIfNoFile
    def readfile(self, filename):
        # Reads and returns the contents of a file in the theme folder.
        with open(self._themepath(filename)) as f:
            logger.debug("Read themed file: " + filename)
            return f.read()

    @_noneIfNoFile
    def sound(self, filename):
        # Returns a sound file string, from the themed folder.
        return self._themepath(filename)

    def find_stylesheet_attribute(self, section: str, attribute: str) -> str | None:
        if self.stylesheet is None:
            return
        field = r"\s{0,8}[\w-]+\s{0,2}:\s{0,2}[#\d\w\s-]+;\n"
        target_field = fr"\s{{0,8}}{attribute}\s{{0,2}}:\s{{0,2}}([#\d\w\s-]+);\n"
        escaped_section = section.replace("[", "\\[").replace("]", "\\]")
        pattern = fr"{escaped_section}[\s\n]{{0,10}}{{\n({field}){{0,100}}{target_field}"
        mobject = re.search(pattern, self.stylesheet, flags=re.S)
        if mobject is not None:
            return mobject[2]

    def find_stylesheet_style(self, section: str) -> str | None:
        if self.stylesheet is None:
            return
        field = r"\s{0,8}[\w-]+\s{0,2}:\s{0,2}[#\d\w\s-]+;\n"
        escaped_section = section.replace("[", "\\[").replace("]", "\\]")
        pattern = fr"{escaped_section}[\s\n]{{0,10}}{{\n(({field}){{0,100}})\s{{0,10}}}}"
        mobject = re.search(pattern, self.stylesheet, flags=re.S)
        if mobject is not None:
            return mobject[1]


class ThemeSet(QtCore.QObject):
    """
    Represent a collection of themes to choose from, with a default theme and
    an unthemed directory.
    """
    stylesheets_reloaded = QtCore.pyqtSignal()

    def __init__(
        self,
        themeset: Iterable[Theme],
        default_theme: Theme,
        settings: SettingsCls,
        client_version: str,
        unthemed: Theme | None = None,
    ) -> None:
        QtCore.QObject.__init__(self)
        self._default_theme = default_theme
        self._themeset = themeset
        self._theme = default_theme
        self._unthemed = Theme(None, '', builtin=True) if unthemed is None else unthemed
        self._settings = settings
        self._client_version = client_version

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def stylesheet(self) -> str:
        return self._theme.stylesheet or ""

    def _getThemeByName(self, name):
        if name is None:
            return self._unthemed
        matching_themes = [
            theme for theme in self._themeset if theme.name == name
        ]
        if not matching_themes:
            return None
        return matching_themes[0]

    def loadTheme(self) -> None:
        name = self._settings.get("theme/theme/name", "Default") or None
        logger.debug("Loaded Theme: " + str(name))
        self.setTheme(name, False)

    def listThemes(self):
        return [None] + [theme.name for theme in self._themeset]

    def setTheme(self, name, restart=True):
        theme = self._getThemeByName(name)
        if theme is None:
            return

        set_theme = self._do_setTheme(theme)

        self._settings.set("theme/theme/name", self._theme.name)
        self._settings.sync()

        if set_theme and restart:
            QtWidgets.QMessageBox.information(
                None, "Restart Needed", "FAF will quit now.",
            )
            QtWidgets.QApplication.quit()

    def _checkThemeVersion(self, theme):
        # Returns a (potentially overridden) theme version.
        version = theme.version()
        if version is None:
            # Malformed theme, we should not override it!
            return None

        override_config = "theme_version_override/" + str(theme)
        override_version_str = self._settings.get(override_config, None)

        if override_version_str is None:
            return version

        try:
            override_version = Version(override_version_str)
        except ValueError:
            # Did someone manually mess with the override config?
            logger.warning(
                "Malformed theme version override setting: {}"
                .format(override_version_str),
            )
            self._settings.remove(override_config)
            return version

        if version >= override_version:
            logger.info(
                "New version %s of theme %s, removing override %s",
                str(version), theme, override_version_str,
            )
            self._settings.remove(override_config)
            return version
        else:
            return override_version

    def _checkThemeOutdated(self, theme_version):
        faf_version = Version(self._client_version)
        return faf_version > theme_version

    def _do_setTheme(self, new_theme: Theme) -> bool:
        old_theme = self._theme

        def theme_changed() -> bool:
            return old_theme != self._theme

        if new_theme == self._theme:
            return theme_changed()

        if new_theme.is_builtin():
            # No need for checks
            self._theme = new_theme
            return theme_changed()

        theme_version = self._checkThemeVersion(new_theme)
        if theme_version is None:
            QtWidgets.QMessageBox.information(
                QtWidgets.QApplication.activeWindow(),
                "Invalid Theme",
                (
                    "Failed to read the version of the following theme:"
                    "<br/><b>{}</b><br/><i>Contact the maker of the theme for"
                    " a fix!</i>".format(str(new_theme))
                ),
            )
            logger.error(
                "Error reading theme version: %s in directory %s",
                new_theme, new_theme.themedir,
            )
            return theme_changed()

        outdated = self._checkThemeOutdated(theme_version)

        if not outdated:
            logger.info("Using theme: %s in directory %s", new_theme, new_theme.themedir)
            self._theme = new_theme
        else:
            box = QtWidgets.QMessageBox(QtWidgets.QApplication.activeWindow())
            box.setWindowTitle("Incompatible Theme")
            box.setText(
                "The selected theme reports compatibility with a lower "
                "version of the FA client:<br/><b>{}</b><br/><i>Contact "
                "the maker of the theme for an update!</i><br/><b>Do you "
                "want to try to apply the theme anyway?</b>"
                .format(str(new_theme)),
            )
            b_yes = box.addButton(
                "Apply this once",
                QtWidgets.QMessageBox.ButtonRole.YesRole,
            )
            b_always = box.addButton(
                "Always apply for this FA version",
                QtWidgets.QMessageBox.ButtonRole.YesRole,
            )
            b_default = box.addButton(
                "Use default theme",
                QtWidgets.QMessageBox.ButtonRole.NoRole,
            )
            b_no = box.addButton("Abort", QtWidgets.QMessageBox.ButtonRole.NoRole)
            box.exec()
            result = box.clickedButton()

            if result == b_always:
                QtWidgets.QMessageBox.information(
                    QtWidgets.QApplication.activeWindow(),
                    "Notice",
                    (
                        "If the applied theme causes crashes, clear the "
                        "'[theme_version_override]'<br/> section of your FA "
                        "client config file."
                    ),
                )
                logger.info(
                    "Overriding version of theme '%s' with '%s'",
                    new_theme, self._client_version,
                )
                override_config = "theme_version_override/" + str(new_theme)
                self._settings.set(override_config, self._client_version)

            if result == b_always or result == b_yes:
                logger.info("Using theme: %s in directory %s", new_theme, new_theme.themedir)
                self._theme = new_theme
            elif result == b_default:
                self._theme = self._default_theme
            elif result == b_no:
                pass
            else:
                pass
        return theme_changed()

    def _theme_callchain(self, fn_name: str, filename: str, themed: bool) -> Any:
        """
        Calls fn_name chaining through theme / default theme / unthemed.
        """
        if themed:
            item = getattr(self._theme, fn_name)(filename)
            if item is None:
                item = getattr(self._default_theme, fn_name)(filename)
        else:
            item = getattr(self._unthemed, fn_name)(filename)
        return item

    def _pixmap(self, filename: str, *, themed: bool = True) -> QtGui.QPixmap | None:
        return self._theme_callchain("pixmap", filename, themed)

    @_warn_resource_null
    def loadUi(self, filename: str, *, themed: bool = True):
        return self._theme_callchain("loadUi", filename, themed)

    @_warn_resource_null
    def loadUiType(self, filename: str, *, themed: bool = True):
        return self._theme_callchain("loadUiType", filename, themed)

    @_warn_resource_null
    def readlines(self, filename: str, *, themed: bool = True):
        return self._theme_callchain("readlines", filename, themed)

    @_warn_resource_null
    def themeurl(self, filename: str, *, themed: bool = True):
        return self._theme_callchain("themeurl", filename, themed)

    @_warn_resource_null
    def themepath(self, filename: str, *, themed: bool = True) -> str:
        return self._theme_callchain("themepath", filename, themed)

    @_warn_resource_null
    def readfile(self, filename: str, *, themed: bool = True):
        return self._theme_callchain("readfile", filename, themed)

    @_warn_resource_null
    def sound(self, filename: str, *, themed: bool = True) -> QtCore.QUrl:
        filepath = self._theme_callchain("sound", filename, themed)
        return QtCore.QUrl.fromLocalFile(filepath)

    def pixmap(self, filename: str, *, themed: bool = True) -> QtGui.QPixmap:
        # If we receive None, return the default pixmap
        ret = self._pixmap(filename, themed=themed)
        if ret is None:
            return QtGui.QPixmap()
        return ret

    def reloadStyleSheets(self) -> None:
        if hasattr(self._theme, "stylesheet"):
            del self._theme.stylesheet
        if hasattr(self._default_theme, "stylesheet"):
            del self._default_theme.stylesheet
        self.stylesheets_reloaded.emit()

    def icon(
        self,
        filename: str,
        themed: bool = True,
        pix: bool = False,
    ) -> QtGui.QIcon | QtGui.QPixmap:
        """
        Convenience method returning an icon from a cached,
        optionally themed pixmap as returned by the pixmap(...) function
        """
        if pix:
            return self.pixmap(filename, themed=themed)
        else:
            icon = QtGui.QIcon()
            icon.addPixmap(self.pixmap(filename, themed=themed), QtGui.QIcon.Mode.Normal)
            splitExt = os.path.splitext(filename)
            if len(splitExt) == 2:
                disabled = self.pixmap(splitExt[0] + "_disabled" + splitExt[1], themed=themed)
                icon.addPixmap(disabled, QtGui.QIcon.Mode.Disabled, QtGui.QIcon.State.On)

                active = self.pixmap(splitExt[0] + "_active" + splitExt[1], themed=themed)
                icon.addPixmap(active, QtGui.QIcon.Mode.Active, QtGui.QIcon.State.On)

                selected = self.pixmap(splitExt[0] + "_selected" + splitExt[1], themed=themed)
                icon.addPixmap(selected, QtGui.QIcon.Mode.Selected, QtGui.QIcon.State.On)
            return icon

    def find_stylesheet_attribute(self, section: str, attribute: str, fallback: str = "") -> str:
        if (found := self._theme.find_stylesheet_attribute(section, attribute)) is None:
            return self._default_theme.find_stylesheet_attribute(section, attribute) or fallback
        else:
            return found or fallback

    def find_stylesheet_style(self, section: str, fallback: str = "") -> str:
        if (style := self._theme.find_stylesheet_style(section)) is None:
            return self._default_theme.find_stylesheet_style(section) or fallback
        else:
            return style or fallback

    def find_stylesheet_style_as_dict(self, section: str) -> dict[str, str]:
        sheetlines = self.find_stylesheet_style(section).splitlines()
        return {
            name.strip().replace("-", "_"): value.strip()[:-1]
            for name, value in (line.split(":") for line in sheetlines)
        }
