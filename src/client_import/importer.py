from typing import Protocol

from PyQt6.QtWidgets import QWidget

from src.client_import.sources import ClientSource


class DataImporter(Protocol):
    """Imports one kind of data from other clients' settings"""

    # key of the importer's button in the import page
    id: str
    title: str

    def supports(self, source: ClientSource) -> bool: ...

    def import_from(self, source: ClientSource, path: str, parent: QWidget | None) -> None: ...
