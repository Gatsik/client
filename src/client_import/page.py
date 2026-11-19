import logging
import os
from collections.abc import Mapping
from collections.abc import Sequence

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QAbstractButton
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QWidget

from src.client_import.importer import DataImporter
from src.client_import.sources import CLIENT_SOURCES
from src.client_import.sources import ClientSource

logger = logging.getLogger(__name__)


class ClientImportPage(QObject):
    """Import settings page. Imports apply immediately, regardless of Apply/OK"""

    def __init__(
        self,
        *,
        source_combo: QComboBox,
        path_edit: QLineEdit,
        browse_button: QAbstractButton,
        status_label: QLabel,
        import_buttons: Mapping[str, QAbstractButton],
        importers: Sequence[DataImporter],
        sources: Sequence[ClientSource] = CLIENT_SOURCES,
        parent_widget: QWidget | None = None,
    ) -> None:
        super().__init__(parent_widget)
        self.source_combo = source_combo
        self.path_edit = path_edit
        self.browse_button = browse_button
        self.status_label = status_label
        self._parent_widget = parent_widget

        importers_by_id = {importer.id: importer for importer in importers}
        for importer_id in importers_by_id.keys() - import_buttons.keys():
            logger.warning("No button in the import page for importer %r", importer_id)

        self._buttons: list[tuple[DataImporter, QAbstractButton]] = []
        for importer_id, button in import_buttons.items():
            importer = importers_by_id.get(importer_id)
            if importer is None:
                button.hide()
                continue
            button.clicked.connect(lambda _=False, i=importer: self.run_import(i))
            self._buttons.append((importer, button))

        self.source_combo.clear()
        for source in sources:
            self.source_combo.addItem(source.name, source)

        self.source_combo.currentIndexChanged.connect(self._at_source_changed)
        self.browse_button.clicked.connect(self.browse)
        self.path_edit.textChanged.connect(self._update_status)
        self._at_source_changed()

    def current_source(self) -> ClientSource | None:
        return self.source_combo.currentData()

    def current_path(self) -> str:
        return self.path_edit.text().strip()

    def _at_source_changed(self, *_) -> None:
        source = self.current_source()
        self.path_edit.setText((source.default_path() or "") if source else "")
        for importer, button in self._buttons:
            button.setEnabled(source is not None and importer.supports(source))
        self._update_status()

    def _update_status(self, *_) -> None:
        path = self.current_path()
        if not path:
            self.status_label.setText("Select the settings file.")
        elif os.path.isfile(path):
            self.status_label.setText("Settings file found.")
        else:
            self.status_label.setText(
                "File not found. Is the client installed? "
                "You can select the file manually.",
            )

    def browse(self) -> None:
        source = self.current_source()
        if source is None:
            return
        start = self.current_path()
        if start and not os.path.isfile(start):
            parent_dir = os.path.dirname(start)
            start = parent_dir if os.path.isdir(parent_dir) else ""
        path, _ = QFileDialog.getOpenFileName(
            self._parent_widget, f"Select {source.name} settings file", start, source.file_filter,
        )
        if path:
            self.path_edit.setText(path)

    def run_import(self, importer: DataImporter) -> None:
        source = self.current_source()
        if source is None:
            return
        path = self.current_path()
        if not os.path.isfile(path):
            QMessageBox.warning(
                self._parent_widget,
                f"Import {importer.title.lower()}",
                "Settings file not found. Please select the file first.",
            )
            return
        importer.import_from(source, path, self._parent_widget)
