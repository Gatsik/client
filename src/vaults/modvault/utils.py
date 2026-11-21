import logging
import os
import re
import shutil
import zipfile
from typing import Final

from PyQt6 import QtCore
from PyQt6 import QtGui
from PyQt6 import QtWidgets

from src import util
from src.api.vaults_api import LatestModVersions
from src.config import Settings
from src.util import PREFSFILENAME
from src.vaults import luaparser
from src.vaults.dialogs import downloadVaultAsset

logger = logging.getLogger(__name__)


modCache: dict[str, ModInfo] = {}


def getModFolder() -> str:
    return os.path.join(util.VAULTS_BASE_DIR, "mods")


def setModFolder():
    global MODFOLDER
    MODFOLDER = getModFolder()
    if installedMods:
        modCache.clear()
        getInstalledMods()


MODVAULT_DOWNLOAD_ROOT = "{}/faf/vault/".format(Settings.get('content/host'))

installedMods: list[ModInfo] = []  # This is a global list that should be kept intact.
# So it should be cleared using installedMods[:] = []

# mods selected by user, are not overwritten by temporary mods selected when
# joining game
selectedMods = Settings.get('play/mods', default=[])

setModFolder()


class ModInfo:
    def __init__(self, **kwargs):
        self.name = "Not filled in"
        self.uid = ""
        self.author = "Uknown author"
        self.version = 0
        self.folder = ""
        self.localfolder = ""
        self.description = ""
        self.ui_only = False
        self.__dict__.update(kwargs)

    def setFolder(self, localfolder: str) -> None:
        self.localfolder = localfolder
        self.absfolder = os.path.join(MODFOLDER, localfolder)
        self.mod_info = os.path.join(self.absfolder, "mod_info.lua")

    def update(self):
        self.setFolder(self.localfolder)
        if isinstance(self.version, int):
            self.totalname = f"{self.name} v{self.version}"
        elif isinstance(self.version, float):
            s = str(self.version).rstrip("0")
            self.totalname = f"{self.name} v{s}"
        else:
            raise TypeError("version is not an int or float")

    def __str__(self):
        return f'{self.totalname} in "{self.localfolder}"'


def getAllModFolders() -> list[str]:  # returns a list of names of installed mods
    try:
        return os.listdir(MODFOLDER)
    except FileNotFoundError:
        return []


def getInstalledMods() -> list[ModInfo]:
    installedMods[:] = []
    for f in getAllModFolders():
        m = None
        try:
            if os.path.isdir(os.path.join(MODFOLDER, f)):
                m = getModInfoFromFolder(f)
            else:
                m = getModInfoFromZip(f)
        except Exception:
            continue
        if m:
            installedMods.append(m)
    return installedMods


def modToFilename(mod):
    return mod.absfolder


def isModFolderValid(folder):
    return os.path.exists(os.path.join(folder, "mod_info.lua"))


def iconPathToFull(moddir: str, iconpath: str) -> str:
    """
    Converts a path supplied in the icon field of mod_info with an absolute
    path to that file. So "/mods/modname/data/icons/icon.dds" becomes
    "C:\\Users\\user\\Documents\\My Games\\Gas Powered Games\\Supreme Commander
    ...Forged Alliance\\Mods\\modname\\data\\icons\\icon.dds"
    """
    if not (iconpath.startswith("/mods") or iconpath.startswith("mods")):
        logger.info("Something went wrong parsing the path %s", iconpath)
        return ""

    # yay for dirty hacks
    return os.path.join(moddir, iconpath.removeprefix("/").split("/", 2)[2])


def fullPathToIcon(moddir: str, path: str) -> str:
    rel = os.path.relpath(os.path.abspath(path), start=os.path.abspath(moddir))
    return f"/mods/{rel.replace(os.sep, '/')}"


def getIcon(name):
    img = os.path.join(util.MOD_PREVIEW_DIR, name)
    if os.path.isfile(img):
        logger.log(5, "Using cached preview image for: %s", name)
        return img
    return None


def getModInfo(modinfofile):
    modinfo = modinfofile.parse(
        {
            "name": "name",
            "uid": "uid",
            "version": "version",
            "author": "author",
            "description": "description",
            "ui_only": "ui_only",
            "icon": "icon",
        },
        {
            "version": "1",
            "ui_only": "false",
            "description": "",
            "icon": "",
            "author": "",
        },
    )
    modinfo["ui_only"] = (modinfo["ui_only"] == 'true')
    if "uid" not in modinfo:
        logger.warning("Couldn't find uid for mod %s", modinfo["name"])
        return None
    # modinfo["uid"] = modinfo["uid"].lower()
    try:
        modinfo["version"] = int(modinfo["version"])
    except Exception:
        try:
            modinfo["version"] = float(modinfo["version"])
        except Exception:
            modinfo["version"] = 0
            logger.exception("Couldn't find version for mod %s", modinfo["name"])
    return modinfofile, modinfo


def parseModInfo(folder):
    if not isModFolderValid(folder):
        return None
    modinfofile = luaparser.luaParser(os.path.join(folder, "mod_info.lua"))
    return getModInfo(modinfofile)


def getModInfoFromZip(zfile: str) -> ModInfo | None:
    """get the mod info from a zip file"""
    if zfile in modCache:
        return modCache[zfile]

    r = None
    if zipfile.is_zipfile(os.path.join(MODFOLDER, zfile)):
        zip_ = zipfile.ZipFile(
            os.path.join(MODFOLDER, zfile), "r", zipfile.ZIP_DEFLATED,
        )
        if zip_.testzip() is None:
            for member in zip_.namelist():
                filename = os.path.basename(member)
                if not filename:
                    continue
                if filename == "mod_info.lua":
                    modinfofile = luaparser.luaParser("mod_info.lua")
                    modinfofile.iszip = True
                    modinfofile.zip = zip_
                    r = getModInfo(modinfofile)
    if r is None:
        logger.warning("mod_info.lua not found in zip file %s", zfile)
        return None
    f, info = r
    if f.error:
        logger.error("Error in parsing mod_info.lua in %s", zfile)
        return None
    m = ModInfo(**info)
    m.setFolder(zfile)
    m.update()
    modCache[zfile] = m
    return m


def getModInfoFromFolder(modfolder: str) -> ModInfo | None:  # modfolder must be local to MODFOLDER
    try:
        return modCache[modfolder]
    except KeyError:
        pass

    r = parseModInfo(os.path.join(MODFOLDER, modfolder))
    if r is None:
        logger.warning("mod_info.lua not found in %s folder", modfolder)
        return None
    f, info = r
    if f.error:
        logger.error("Error in parsing %s/mod_info.lua", modfolder)
        return None
    m = ModInfo(**info)
    m.setFolder(modfolder)
    m.update()
    modCache[modfolder] = m
    return m


ACTIVE_MODS_SECTION_PATTERN: Final = re.compile(r"active_mods\s*=\s*{.*?}", re.S)
MOD_STATE_PATTERN: Final = re.compile(r"\['(.*?)']\s*=\s*(true|false)")


# returns a list of ModInfo's containing information of the mods
def getActiveMods(uimods: bool | None = None, temporary: bool = True) -> list[ModInfo]:
    """uimods:
        None - return all active mods
        True - only return active UI Mods
        False - only return active non-UI Mods
       temporary:
        read from game.prefs and not from settings
    """
    active_mods = []
    try:
        if not os.path.exists(PREFSFILENAME):
            logger.info("No game.prefs file found")
            return []
        if temporary:
            with open(PREFSFILENAME) as f:
                data = f.read()
            if matched := ACTIVE_MODS_SECTION_PATTERN.search(data):
                uids = [uid for uid, b in MOD_STATE_PATTERN.findall(matched[0]) if b == "true"]
            else:
                logger.warning("No 'active_mods' section found in game.prefs file")
                return []
        else:
            uids = selectedMods[:]

        allmods: list[ModInfo] = []
        for m in installedMods:
            if (
                (uimods and m.ui_only)
                or (not uimods and not m.ui_only)
                or uimods is None
            ):
                allmods.append(m)
        active_mods = [m for m in allmods if m.uid in uids]
        # logger.debug(
        #     "All mods uids: {}\n\nActive mods uids: {}\n"
        #     .format(", ".join([mod.uid for mod in allmods]),
        #             ", ".join([mod.uid for mod in allmods]))
        # )
        return active_mods
    except Exception:
        return []


# uimods works the same as in getActiveMods
def setActiveMods(mods, keepuimods=True, temporary=True):
    """
    keepuimods:
        None: Replace all active mods with 'mods'
        True: Keep the UI mods already activated activated
        False: Keep only the non-UI mods that were activated activated
        So set it True if you want to set gameplay mods, and False if you want
        to set UI mods.
    temporary:
        Set this when mods are activated due to joining a game.
    """
    if keepuimods is not None:
        # returns the active UI mods if True, the active non-ui mods if False
        keepTheseMods = getActiveMods(keepuimods)
    else:
        keepTheseMods = []
    allmods = keepTheseMods + mods
    logger.debug("Setting active Mods: %s", [mod.uid for mod in allmods])
    active_mods = ",\n".join(f"    ['{mod.uid}'] = true" for mod in allmods)
    s = f"active_mods = {{\n{active_mods}\n}}"

    if not temporary:
        global selectedMods
        logger.debug("selectedMods was: %s", Settings.get("play/mods"))
        selectedMods = [str(mod.uid) for mod in allmods]
        logger.debug("Writing selectedMods: %s", selectedMods)
        Settings.set('play/mods', selectedMods)
        logger.debug("selectedMods written: %s", Settings.get("play/mods"))

    try:
        with open(PREFSFILENAME) as f:
            data = f.read()
    except Exception:
        logger.exception("Couldn't read the game.prefs file")
        return False

    if ACTIVE_MODS_SECTION_PATTERN.search(data):
        data = ACTIVE_MODS_SECTION_PATTERN.sub(s, data, 1)
    else:
        data += "\n" + s

    try:
        with open(PREFSFILENAME, 'w') as f:
            f.write(data)
    except Exception:
        logger.exception("Cound't write to the game.prefs file")
        return False

    return True


def generateThumbnail(sourcename, destname):
    """
    Given a dds file, generates a png file (or whatever the extension
    of dest is
    """
    logger.debug("Creating png thumnail for %s to %s", sourcename, destname)

    try:
        img = bytearray()
        buf = bytearray(16)
        with open(sourcename, "rb") as f:
            f.seek(128)  # skip header
            while f.readinto(buf):
                img += buf[:3] + buf[4:7] + buf[8:11] + buf[12:15]

        size = int((len(img) / 3) ** (1.0 / 2))
        image = QtGui.QImage(img, size, size, QtGui.QImage.Format_RGB888)
        imageFile = image.rgbSwapped().scaled(
            100, 100, transformMode=QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        imageFile.save(destname)
    except OSError:
        return False

    if os.path.isfile(destname):
        return True
    else:
        return False


def downloadMod(link: str, name: str, *, replace_existing: bool = False) -> bool:
    logger.debug("Getting mod from: %s", link)

    def handle_exist(path: str, modname: str) -> bool:
        modpath = os.path.join(path, modname)
        oldmod = getModInfoFromFolder(modpath)
        if replace_existing:
            if oldmod is not None:
                removeMod(oldmod)
            return True
        result = QtWidgets.QMessageBox.question(
            None,
            "Modfolder already exists",
            (
                "The mod is to be downloaded to the folder '{}'. This folder "
                "already exists and contains <b>{}</b>. Do you want to "
                "overwrite this mod?"
            ).format(modpath, oldmod.totalname),
            QtWidgets.QMessageBox.StandardButton.Yes,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if result == QtWidgets.QMessageBox.StandardButton.No:
            return False
        removeMod(oldmod)
        return True

    if downloadVaultAsset(link, MODFOLDER, handle_exist, name, "mod", silent=False):
        for modfolder, mod_info in reversed(modCache.items()):
            if mod_info.name == name:
                del modCache[modfolder]
                break
        getInstalledMods()  # update modCache and installedMods list
        return True
    return False


def removeMod(mod: ModInfo) -> bool:
    logger.debug("Removing mod %s", mod.name)
    real = None
    for m in installedMods:
        if m.uid == mod.uid:
            real = m
            break
    else:
        logger.warning("Can't remove '%s' mod. Mod not found.", mod.name)
        return False
    try:
        shutil.rmtree(real.absfolder)
    except FileNotFoundError as e:
        logger.warning("%s", e)
    modCache.pop(real.localfolder, None)
    installedMods.remove(real)
    return True
    # we don't update the installed mods, because the operating system takes
    # some time registering the deleted folder.


def remove_mod_by_uid(uid: str) -> bool:
    for mod in installedMods:
        if mod.uid == uid:
            return removeMod(mod)
    return False


def updateModsToLatest(mods: list[ModInfo]) -> list[ModInfo]:
    latest_versions = LatestModVersions().request_and_get_latest_versions([m.uid for m in mods])
    installed_uids = {m.uid for m in getInstalledMods()}

    replaced: dict[str, str] = {}  # old uid -> new uid
    for mod in mods:
        latest = latest_versions.get(mod.uid)
        if latest is None:
            logger.debug("Mod '%s' not found in the vault, skipping update", mod.totalname)
            continue
        if latest["uid"] == mod.uid or latest.get("version", 0) <= mod.version:
            logger.debug("Mod '%s' is up to date", mod.totalname)
            continue
        if latest["uid"] in installed_uids:
            logger.debug("Newer version of '%s' is already installed", mod.totalname)
            replaced[mod.uid] = latest["uid"]
            continue
        logger.debug("Updating mod '%s' to v%s", mod.totalname, latest.get("version"))
        if downloadMod(latest["downloadUrl"], mod.localfolder, replace_existing=True):
            # new version may have been extracted into another folder
            if any(m.uid == mod.uid for m in installedMods):
                removeMod(mod)
            replaced[mod.uid] = latest["uid"]

    if not replaced:
        return mods

    installed = {m.uid: m for m in getInstalledMods()}
    result = []
    for mod in mods:
        uid = replaced.get(mod.uid, mod.uid)
        if uid in installed:
            result.append(installed[uid])
        else:
            logger.warning("Mod '%s' is missing after update", mod.totalname)
    return result
