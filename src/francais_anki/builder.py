from __future__ import annotations

from pathlib import Path

import genanki

from .anki_model import StableGuidNote, create_model, escaped_fields
from .audio import generate_audio_bundle
from .models import DeckInput, PreparedNote
from .utils import get_logger, slugify, stable_numeric_id


def prepare_notes(deck_input: DeckInput, media_dir: Path) -> list[PreparedNote]:
    prepared: list[PreparedNote] = []
    for note in deck_input.notes:
        item = generate_audio_bundle(note, deck_input.voice_options, media_dir)
        item.tags = list(deck_input.note_tags)
        prepared.append(item)
    return prepared


def build_package(
    deck_input: DeckInput,
    prepared_notes: list[PreparedNote],
    apkg_dir: Path,
    media_dir: Path,
) -> Path:
    logger = get_logger()
    model = create_model()
    deck_id = stable_numeric_id(deck_input.full_deck_name)
    deck = genanki.Deck(deck_id=deck_id, name=deck_input.full_deck_name)

    for prepared in prepared_notes:
        fields = escaped_fields(
            frase_fr=prepared.input_note.frase_fr,
            audio=prepared.audio_field,
            traducao_pt=prepared.input_note.traducao_pt,
            ipa=prepared.input_note.ipa,
            observacao=prepared.input_note.observacao,
        )
        note = StableGuidNote(
            model=model,
            fields=fields,
            tags=prepared.tags,
            stable_guid=prepared.guid,
        )
        deck.add_note(note)

    apkg_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(deck_input.full_deck_name, max_length=60)}.apkg"
    package_path = apkg_dir / filename
    package = genanki.Package(deck)
    package.media_files = [str(media_dir / item.audio_filename) for item in prepared_notes]
    package.write_to_file(str(package_path))
    logger.info("Pacote .apkg gerado em %s", package_path)
    return package_path
