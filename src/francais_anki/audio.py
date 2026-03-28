from __future__ import annotations

import asyncio
import random
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import edge_tts

from .config import PAUSE_MS
from .models import InputNote, PreparedNote, TtsOptions, VoiceOptions
from .utils import get_logger, slugify, stable_guid, stable_hash
from .voice_discovery import infer_gender, voices_for_note


class AudioGenerationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempted_voices: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.attempted_voices = attempted_voices or []


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioGenerationError(
            "ffmpeg nao encontrado no PATH. Instale-o antes de gerar os audios."
        )


def _concat_mp3_with_pause(
    part_a: Path, part_b: Path, output: Path, pause_ms: int
) -> None:
    """Concatenate two MP3 files with silence in between using ffmpeg."""
    pause_sec = pause_ms / 1000.0
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(part_a),
            "-i",
            str(part_b),
            "-filter_complex",
            f"aevalsrc=0:d={pause_sec}[sil];[0:a][sil][1:a]concat=n=3:v=0:a=1[out]",
            "-map",
            "[out]",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

@dataclass(slots=True)
class VoiceSelection:
    all_voices: list[str]
    male_voices: list[str]
    female_voices: list[str]

    def fallback_candidates(self, preferred_voice: str) -> list[str]:
        preferred_gender = infer_gender(preferred_voice)
        gender_pool = self.female_voices if preferred_gender == "female" else self.male_voices

        ordered: list[str] = []
        for voice in [preferred_voice, *gender_pool, *self.all_voices]:
            if voice and voice not in ordered:
                ordered.append(voice)
        return ordered


def prefer_monolingual_voices(note: InputNote, voices: list[str]) -> list[str]:
    if not note.frase_fr.strip().isdigit():
        return voices

    monolingual_voices = [
        voice for voice in voices if "multilingual" not in voice.lower()
    ]
    return monolingual_voices or voices


def resolve_voice_selection(note: InputNote, options: VoiceOptions) -> VoiceSelection:
    logger = get_logger()
    if options.catalog:
        all_voices = voices_for_note(note.frase_fr, options.catalog, options.weights)
    else:
        all_voices = options.male_voices + options.female_voices

    filtered_voices = prefer_monolingual_voices(note, all_voices)
    if filtered_voices != all_voices:
        logger.info(
            "Nota numerica '%s': priorizando vozes monolingues francesas",
            note.frase_fr,
        )
    all_voices = filtered_voices
    male_voices = [voice for voice in all_voices if infer_gender(voice) == "male"] or all_voices
    female_voices = [voice for voice in all_voices if infer_gender(voice) == "female"] or all_voices

    return VoiceSelection(
        all_voices=all_voices,
        male_voices=male_voices or all_voices,
        female_voices=female_voices or all_voices,
    )


def choose_voices(note: InputNote, selection: VoiceSelection) -> tuple[str, str]:
    seed = stable_hash(note.frase_fr, length=8)
    generator = random.Random(int(seed, 16))

    male_voice = generator.choice(selection.male_voices)
    female_voice = generator.choice(selection.female_voices)

    # Prefer two distinct voices when possible
    if male_voice == female_voice:
        candidates = [voice for voice in selection.all_voices if voice != male_voice]
        if candidates:
            female_voice = generator.choice(candidates)

    if generator.choice([True, False]):
        return male_voice, female_voice
    return female_voice, male_voice


async def synthesize_mp3(
    text: str,
    voice: str,
    rate: str,
    output_path: Path,
    tts_options: TtsOptions,
) -> None:
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        connect_timeout=tts_options.connect_timeout,
        receive_timeout=tts_options.receive_timeout,
    )
    total_timeout = tts_options.connect_timeout + tts_options.receive_timeout + 5
    await asyncio.wait_for(communicator.save(str(output_path)), timeout=total_timeout)


def is_retryable_tts_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            edge_tts.exceptions.NoAudioReceived,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ),
    )


def retry_backoff_seconds(attempt_number: int) -> float:
    return 0.75 * attempt_number


def synthesize_with_retries(
    note: InputNote,
    voice: str,
    rate: str,
    output_path: Path,
    tts_options: TtsOptions,
) -> None:
    logger = get_logger()
    total_attempts = max(1, tts_options.retries + 1)
    last_error: Exception | None = None

    for attempt_number in range(1, total_attempts + 1):
        try:
            logger.info(
                "Sintetizando '%s' com voz %s (tentativa %s/%s)",
                note.frase_fr,
                voice,
                attempt_number,
                total_attempts,
            )
            asyncio.run(
                synthesize_mp3(
                    note.audio_text,
                    voice,
                    rate,
                    output_path,
                    tts_options,
                )
            )
            return
        except Exception as exc:
            last_error = exc
            retryable = is_retryable_tts_error(exc)
            if attempt_number >= total_attempts or not retryable:
                break

            wait_seconds = retry_backoff_seconds(attempt_number)
            logger.warning(
                "Falha transitoria ao sintetizar '%s' com voz %s "
                "(tentativa %s/%s): %s. Novo retry em %.2fs",
                note.frase_fr,
                voice,
                attempt_number,
                total_attempts,
                exc,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    if last_error is None:
        raise AudioGenerationError(
            f"Falha desconhecida ao sintetizar '{note.frase_fr}' com voz {voice}",
            attempted_voices=[voice],
        )

    raise AudioGenerationError(
        f"Falha ao sintetizar '{note.frase_fr}' com voz {voice}: {last_error}",
        attempted_voices=[voice],
    ) from last_error


def synthesize_with_fallback(
    note: InputNote,
    selection: VoiceSelection,
    preferred_voice: str,
    rate: str,
    output_path: Path,
    tts_options: TtsOptions,
) -> str:
    logger = get_logger()
    attempted: list[str] = []

    for voice in selection.fallback_candidates(preferred_voice):
        attempted.append(voice)
        try:
            synthesize_with_retries(
                note=note,
                voice=voice,
                rate=rate,
                output_path=output_path,
                tts_options=tts_options,
            )
            if voice != preferred_voice:
                logger.warning(
                    "Falha ao sintetizar '%s' com %s; usando fallback %s",
                    note.frase_fr,
                    preferred_voice,
                    voice,
                )
            return voice
        except AudioGenerationError as exc:
            logger.warning(
                "Falha ao sintetizar '%s' com voz %s; tentando fallback. Motivo: %s",
                note.frase_fr,
                voice,
                exc,
            )

    raise AudioGenerationError(
        "Nenhuma voz retornou audio para "
        f"'{note.frase_fr}'. Tentativas: {', '.join(attempted)}",
        attempted_voices=attempted,
    )


def build_audio_filename(note: InputNote) -> str:
    slug = slugify(note.frase_fr)
    suffix = stable_hash(f"{note.frase_fr}|{note.audio_text}", length=10)
    return f"{slug}-{suffix}.mp3"


def generate_audio_bundle(
    note: InputNote,
    voice_options: VoiceOptions,
    tts_options: TtsOptions,
    media_dir: Path,
) -> PreparedNote:
    logger = get_logger()
    ensure_ffmpeg_available()
    media_dir.mkdir(parents=True, exist_ok=True)

    selection = resolve_voice_selection(note, voice_options)
    voice_a, voice_b = choose_voices(note, selection)
    final_filename = build_audio_filename(note)
    final_path = media_dir / final_filename

    if final_path.exists():
        logger.info(
            "Reaproveitando audio existente para '%s' em %s",
            note.frase_fr,
            final_path,
        )
        return PreparedNote(
            input_note=note,
            guid=stable_guid(note.frase_fr),
            audio_filename=final_filename,
            audio_field=f"[sound:{final_filename}]",
            tags=[],
        )

    logger.info(
        "Gerando audio para frase '%s' com vozes %s e %s",
        note.frase_fr,
        voice_a,
        voice_b,
    )

    with tempfile.TemporaryDirectory(prefix="francais-anki-audio-") as temp_dir:
        temp_path = Path(temp_dir)
        segment_a = temp_path / "part_a.mp3"
        segment_b = temp_path / "part_b.mp3"

        voice_a = synthesize_with_fallback(
            note,
            selection,
            voice_a,
            voice_options.normal_rate,
            segment_a,
            tts_options,
        )
        voice_b = synthesize_with_fallback(
            note,
            selection,
            voice_b,
            voice_options.slow_rate,
            segment_b,
            tts_options,
        )

        _concat_mp3_with_pause(segment_a, segment_b, final_path, PAUSE_MS)

    return PreparedNote(
        input_note=note,
        guid=stable_guid(note.frase_fr),
        audio_filename=final_filename,
        audio_field=f"[sound:{final_filename}]",
        tags=[],
    )
