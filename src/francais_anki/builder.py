from __future__ import annotations

from pathlib import Path

import genanki

from .anki_model import StableGuidNote, create_model, escaped_fields
from .audio import AudioGenerationError, generate_audio_bundle
from .models import (
    DeckInput,
    InputNote,
    NotePreparationFailure,
    PrepareNotesResult,
    PreparedNote,
    RetryPassStatus,
    TtsOptions,
)
from .utils import get_logger, slugify, stable_numeric_id


def _prepare_note_pass(
    deck_input: DeckInput,
    notes: list[InputNote],
    tts_options: TtsOptions,
    media_dir: Path,
    *,
    pass_name: str,
    total_notes: int,
) -> tuple[list[PreparedNote], list[NotePreparationFailure]]:
    logger = get_logger()
    prepared: list[PreparedNote] = []
    failures: list[NotePreparationFailure] = []

    for index, note in enumerate(notes, start=1):
        progress_label = f"{pass_name} [{index}/{total_notes}]"
        logger.info("%s Preparando nota '%s'", progress_label, note.frase_fr)
        try:
            item = generate_audio_bundle(
                note=note,
                voice_options=deck_input.voice_options,
                tts_options=tts_options,
                media_dir=media_dir,
            )
            item.tags = list(deck_input.note_tags)
            prepared.append(item)
            logger.info("%s Nota gerada com sucesso para '%s'", progress_label, note.frase_fr)
        except AudioGenerationError as exc:
            logger.warning(
                "%s Falha para '%s'. Vozes tentadas: %s. Erro: %s",
                progress_label,
                note.frase_fr,
                ", ".join(exc.attempted_voices) or "nenhuma",
                exc,
            )
            failures.append(
                NotePreparationFailure(
                    note=note,
                    attempted_voices=list(exc.attempted_voices),
                    error_message=str(exc),
                )
            )

    return prepared, failures


def prepare_notes(
    deck_input: DeckInput,
    media_dir: Path,
    tts_options: TtsOptions,
) -> PrepareNotesResult:
    logger = get_logger()
    total_notes = len(deck_input.notes)
    first_pass_prepared, first_pass_failures = _prepare_note_pass(
        deck_input=deck_input,
        notes=deck_input.notes,
        tts_options=tts_options,
        media_dir=media_dir,
        pass_name="primeira passada",
        total_notes=total_notes,
    )

    retry_prepared: list[PreparedNote] = []
    final_failures = first_pass_failures
    retry_pass_status = RetryPassStatus.ENABLED_NOT_NEEDED
    if not tts_options.final_retry_pass:
        retry_pass_status = RetryPassStatus.DISABLED

    if first_pass_failures and tts_options.final_retry_pass:
        retry_pass_status = RetryPassStatus.ENABLED_AND_EXECUTED
        logger.info(
            "Iniciando segunda passada para %s nota(s) com falha de audio",
            len(first_pass_failures),
        )
        retry_prepared, final_failures = _prepare_note_pass(
            deck_input=deck_input,
            notes=[failure.note for failure in first_pass_failures],
            tts_options=tts_options,
            media_dir=media_dir,
            pass_name="segunda passada",
            total_notes=len(first_pass_failures),
        )

    result = PrepareNotesResult(
        prepared_notes=[*first_pass_prepared, *retry_prepared],
        total_notes=total_notes,
        first_pass_successes=len(first_pass_prepared),
        recovered_on_retry=len(retry_prepared),
        retry_pass_status=retry_pass_status,
        failed_notes=final_failures,
    )

    logger.info(
        "Resumo da geracao de audio: %s/%s nota(s) gerada(s) com audio; "
        "%s sucesso(s) na primeira passada; %s recuperada(s) no reprocessamento; "
        "%s falha(s) final(is).",
        len(result.prepared_notes),
        result.total_notes,
        result.first_pass_successes,
        result.recovered_on_retry,
        len(result.failed_notes),
    )
    logger.info("Status do reprocessamento: %s.", result.retry_pass_status.value)

    if result.failed_notes:
        missing_notes = ", ".join(failure.note.frase_fr for failure in result.failed_notes)
        logger.error("Notas nao geradas: %s", missing_notes)
    else:
        logger.info("Todas as %s nota(s) foram geradas com audio.", result.total_notes)

    for failure in result.failed_notes:
        logger.error(
            "Nota ignorada por falha de audio: '%s'. Vozes tentadas: %s. Erro final: %s",
            failure.note.frase_fr,
            ", ".join(failure.attempted_voices) or "nenhuma",
            failure.error_message,
        )

    return result


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
