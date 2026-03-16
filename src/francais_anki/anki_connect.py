from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .anki_model import MODEL_CSS
from .config import ANKI_CONNECT_URL, ANKI_CONNECT_VERSION, DEFAULT_MODEL_NAME
from .models import DeckInput, PreparedNote
from .utils import escaped_anki_query, get_logger


class AnkiConnectError(RuntimeError):
    pass


@dataclass(slots=True)
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class AnkiConnectClient:
    def __init__(self, endpoint: str = ANKI_CONNECT_URL, timeout: int = 15) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def invoke(self, action: str, params: dict[str, Any] | None = None) -> Any:
        response = requests.post(
            self.endpoint,
            json={
                "action": action,
                "version": ANKI_CONNECT_VERSION,
                "params": params or {},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise AnkiConnectError(str(payload["error"]))
        return payload.get("result")

    def is_available(self) -> bool:
        try:
            result = self.invoke("version")
        except (requests.RequestException, AnkiConnectError):
            return False
        return bool(result)

    def ensure_deck(self, deck_name: str) -> None:
        self.invoke("createDeck", {"deck": deck_name})

    def ensure_model(self) -> None:
        existing = set(self.invoke("modelNames"))
        if DEFAULT_MODEL_NAME in existing:
            return
        self.invoke(
            "createModel",
            {
                "modelName": DEFAULT_MODEL_NAME,
                "inOrderFields": [
                    "FraseFR",
                    "Audio",
                    "TraducaoPT",
                    "IPA",
                    "Observacao",
                ],
                "css": MODEL_CSS,
                "cardTemplates": [
                    {
                        "Name": "Leitura e Pronuncia",
                        "Front": """{{#FraseFR}}
<div class="frase">{{FraseFR}}</div>
{{/FraseFR}}""",
                        "Back": """{{FrontSide}}

<hr id=answer>

{{#Audio}}
<div class="audio">{{Audio}}</div>
{{/Audio}}

{{#TraducaoPT}}
<details>
  <summary>Mostrar traducao</summary>
  <div class="traducao">{{TraducaoPT}}</div>
</details>
{{/TraducaoPT}}

{{#IPA}}
<div class="ipa">{{IPA}}</div>
{{/IPA}}

{{#Observacao}}
<div class="obs">{{Observacao}}</div>
{{/Observacao}}""",
                    },
                    {
                        "Name": "Audicao",
                        "Front": """{{#Audio}}
<div class="audio">{{Audio}}</div>
{{/Audio}}""",
                        "Back": """{{FrontSide}}

<hr id=answer>

{{#FraseFR}}
<div class="frase">{{FraseFR}}</div>
{{/FraseFR}}

{{#TraducaoPT}}
<details>
  <summary>Mostrar traducao</summary>
  <div class="traducao">{{TraducaoPT}}</div>
</details>
{{/TraducaoPT}}

{{#IPA}}
<div class="ipa">{{IPA}}</div>
{{/IPA}}

{{#Observacao}}
<div class="obs">{{Observacao}}</div>
{{/Observacao}}""",
                    },
                ],
            },
        )

    def store_media_file(self, media_path: Path) -> None:
        encoded = base64.b64encode(media_path.read_bytes()).decode("ascii")
        self.invoke(
            "storeMediaFile",
            {"filename": media_path.name, "data": encoded},
        )

    def find_existing_notes(self, deck_name: str, frase_fr: str) -> list[int]:
        query = (
            f'deck:"{escaped_anki_query(deck_name)}" '
            f'note:"{escaped_anki_query(DEFAULT_MODEL_NAME)}" '
            f'FraseFR:"{escaped_anki_query(frase_fr)}"'
        )
        result = self.invoke("findNotes", {"query": query})
        return [int(item) for item in result]

    def add_note(self, deck_name: str, prepared: PreparedNote) -> None:
        self.invoke(
            "addNote",
            {
                "note": {
                    "deckName": deck_name,
                    "modelName": DEFAULT_MODEL_NAME,
                    "fields": {
                        "FraseFR": prepared.input_note.frase_fr,
                        "Audio": prepared.audio_field,
                        "TraducaoPT": prepared.input_note.traducao_pt,
                        "IPA": prepared.input_note.ipa,
                        "Observacao": prepared.input_note.observacao,
                    },
                    "tags": prepared.tags,
                    "options": {"allowDuplicate": False},
                }
            },
        )

    def update_note(self, note_id: int, prepared: PreparedNote) -> None:
        self.invoke(
            "updateNoteFields",
            {
                "note": {
                    "id": note_id,
                    "fields": {
                        "FraseFR": prepared.input_note.frase_fr,
                        "Audio": prepared.audio_field,
                        "TraducaoPT": prepared.input_note.traducao_pt,
                        "IPA": prepared.input_note.ipa,
                        "Observacao": prepared.input_note.observacao,
                    },
                }
            },
        )
        self.invoke("addTags", {"notes": [note_id], "tags": " ".join(prepared.tags)})

    def sync_collection(self) -> None:
        self.invoke("sync")


def sync_notes(
    client: AnkiConnectClient,
    deck_input: DeckInput,
    prepared_notes: list[PreparedNote],
    media_dir: Path,
) -> SyncStats:
    logger = get_logger()
    stats = SyncStats()
    client.ensure_model()
    client.ensure_deck(deck_input.full_deck_name)

    for prepared in prepared_notes:
        media_path = media_dir / prepared.audio_filename
        client.store_media_file(media_path)
        existing_ids = client.find_existing_notes(
            deck_name=deck_input.full_deck_name,
            frase_fr=prepared.input_note.frase_fr,
        )
        if existing_ids:
            for note_id in existing_ids:
                client.update_note(note_id, prepared)
            stats.updated += len(existing_ids)
            logger.info(
                "Atualizada(s) %s nota(s) existentes para '%s'",
                len(existing_ids),
                prepared.input_note.frase_fr,
            )
            continue

        try:
            client.add_note(deck_input.full_deck_name, prepared)
            stats.created += 1
            logger.info("Nota criada via AnkiConnect para '%s'", prepared.input_note.frase_fr)
        except AnkiConnectError as exc:
            stats.skipped += 1
            logger.warning(
                "Falha ao criar nota via AnkiConnect para '%s': %s",
                prepared.input_note.frase_fr,
                exc,
            )

    try:
        client.sync_collection()
    except AnkiConnectError as exc:
        logger.warning("Nao foi possivel sincronizar a colecao via AnkiConnect: %s", exc)

    return stats
