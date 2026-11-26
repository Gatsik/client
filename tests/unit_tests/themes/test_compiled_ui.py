import shutil
import sys

import pytest

import compile_ui
from src.util import Theme

PACKAGE = "compiled_ui_test"
UI_FILE = "dialogs/information.ui"


@pytest.fixture
def themedir(tmp_path, monkeypatch):
    themedir = tmp_path / "theme"
    (themedir / "dialogs").mkdir(parents=True)
    shutil.copy(f"res/{UI_FILE}", themedir / UI_FILE)
    compile_ui.compile_dir(str(themedir), str(tmp_path / PACKAGE))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield themedir
    for name in [name for name in sys.modules if name.partition(".")[0] == PACKAGE]:
        del sys.modules[name]


def test_compiled_ui_is_used(themedir):
    theme = Theme(str(themedir), "", compiled_package=PACKAGE)
    form_class, base_class = theme.loadUiType(UI_FILE)
    compiled = sys.modules[f"{PACKAGE}.dialogs.information"]
    assert form_class is compiled.FormClass
    assert base_class is compiled.BaseClass


def test_outdated_compiled_ui_falls_back_to_uic(themedir):
    with open(themedir / UI_FILE, "a") as f:
        f.write("\n")
    theme = Theme(str(themedir), "", compiled_package=PACKAGE)
    form_class, base_class = theme.loadUiType(UI_FILE)
    compiled = sys.modules[f"{PACKAGE}.dialogs.information"]
    assert form_class is not compiled.FormClass
    assert form_class.__name__ == compiled.FormClass.__name__
    assert base_class is compiled.BaseClass


def test_missing_compiled_package_falls_back_to_uic(themedir):
    theme = Theme(str(themedir), "", compiled_package="no_such_package")
    form_class, _ = theme.loadUiType(UI_FILE)
    assert form_class.__module__ != f"{PACKAGE}.dialogs.information"
