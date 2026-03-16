from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL_NAME = "FR - Frase / Audio / IPA"
DEFAULT_BASE_DECK = "Francais - Prononciation et comprehension orale"
DEFAULT_TAG = "alliance-francaise"
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
ANKI_CONNECT_VERSION = 5
PAUSE_MS = 2000


@dataclass(slots=True)
class AppPaths:
    project_root: Path
    data_dir: Path = field(init=False)
    output_dir: Path = field(init=False)
    media_dir: Path = field(init=False)
    apkg_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.project_root / "data"
        self.output_dir = self.project_root / "output"
        self.media_dir = self.output_dir / "media"
        self.apkg_dir = self.output_dir / "apkg"
        self.logs_dir = self.output_dir / "logs"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.apkg_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
