import importlib
import sys

from PyQt6.QtCore import QThread

HEAVY_MODULES = (
    "numpy",
    "pyqtgraph",
    "scipy_ndimage.ndimage._filters" if getattr(sys, "frozen", False) else "scipy.ndimage",
)


class _HeavyModulesPreloader(QThread):
    def run(self) -> None:
        for name in HEAVY_MODULES:
            importlib.import_module(name)


HeavyModulesPreloader = _HeavyModulesPreloader()
HeavyModulesPreloader.finished.connect(HeavyModulesPreloader.deleteLater)
