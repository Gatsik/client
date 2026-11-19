import json
import os
import sys
from collections.abc import Callable
from typing import Any
from typing import NamedTuple


class ClientImportError(Exception):
    pass


class ClientSource(NamedTuple):
    id: str
    name: str
    file_filter: str
    candidate_paths: Callable[[], list[str]]

    def default_path(self) -> str | None:
        candidates = self.candidate_paths()
        for path in candidates:
            if os.path.isfile(path):
                return path
        return candidates[0] if candidates else None


def read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise ClientImportError(f"File not found: {path}") from e
    except OSError as e:
        raise ClientImportError(f"Could not read {path}: {e.strerror or e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ClientImportError(f"{path} is not a valid JSON file: {e}") from e


def _appdata() -> str:
    return os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def _xdg_config() -> str:
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def downlords_candidate_paths() -> list[str]:
    if sys.platform == "win32":
        return [os.path.join(_appdata(), "Forged Alliance Forever", "client.prefs")]
    return [os.path.join(os.path.expanduser("~"), ".faforever", "client.prefs")]


def rust_client_candidate_paths() -> list[str]:
    if sys.platform == "win32":
        base = _appdata()
        return [
            os.path.join(base, "FAForever", "FAForever Client", "config", "settings.json"),
            os.path.join(base, "FAForever", "FAForever Client", "settings.json"),
        ]
    if sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        return [
            os.path.join(base, "com.FAForever.FAForever-Client", "settings.json"),
        ]
    base = _xdg_config()
    return [
        os.path.join(base, "faforeverclient", "settings.json"),
        os.path.join(base, "faforever-client", "settings.json"),
    ]


DOWNLORDS_CLIENT = ClientSource(
    id="downlords-faf-client",
    name="Downlord's FAF Client",
    file_filter="Downlord's FAF Client preferences (client.prefs);;All files (*)",
    candidate_paths=downlords_candidate_paths,
)

RUST_CLIENT = ClientSource(
    id="faforever-rust-client",
    name="FAForever Rust Client",
    file_filter=(
        "FAForever Rust Client settings (settings.json);;JSON files (*.json);;All files (*)"
    ),
    candidate_paths=rust_client_candidate_paths,
)

CLIENT_SOURCES = (DOWNLORDS_CLIENT, RUST_CLIENT)
