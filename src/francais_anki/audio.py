from __future__ import annotations

import asyncio
import random
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import edge_tts
from pydub import AudioSegment

from .config import PAUSE_MS
from .models import InputNote, PreparedNote, VoiceOptions
from .utils import get_logger, slugify, stable_guid, stable_hash
from .voice_discovery import infer_gender, voices_for_note


class AudioGenerationError(RuntimeError):
    pass


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioGenerationError(
            "ffmpeg nao encontrado no PATH. Instale-o antes de gerar os audios."
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


def resolve_voice_selection(note: InputNote, options: VoiceOptions) -> VoiceSelection:
    if options.catalog:
        all_voices = voices_for_note(note.frase_fr, options.catalog, options.weights)
        male_voices = [voice for voice in all_voices if infer_gender(voice) == "male"] or all_voices
        female_voices = [voice for voice in all_voices if infer_gender(voice) == "female"] or all_voices
    else:
        male_voices = options.male_voices
        female_voices = options.female_voices
        all_voices = male_voices + female_voices

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


async def synthesize_mp3(text: str, voice: str, rate: str, output_path: Path) -> None:
    communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicator.save(str(output_path))


def synthesize_with_fallback(
    note: InputNote,
    selection: VoiceSelection,
    preferred_voice: str,
    rate: str,
    output_path: Path,
) -> str:
    logger = get_logger()
    attempted: list[str] = []

    for voice in selection.fallback_candidates(preferred_voice):
        attempted.append(voice)
        try:
            asyncio.run(synthesize_mp3(note.audio_text, voice, rate, output_path))
            if voice != preferred_voice:
                logger.warning(
                    "Falha ao sintetizar '%s' com %s; usando fallback %s",
                    note.frase_fr,
                    preferred_voice,
                    voice,
                )
            return voice
        except edge_tts.exceptions.NoAudioReceived:
            logger.warning(
                "Nenhum audio retornado para '%s' com voz %s; tentando fallback",
                note.frase_fr,
                voice,
            )

    raise AudioGenerationError(
        "Nenhuma voz retornou audio para "
        f"'{note.frase_fr}'. Tentativas: {', '.join(attempted)}"
    )


def build_audio_filename(note: InputNote) -> str:
    slug = slugify(note.frase_fr)
    suffix = stable_hash(note.frase_fr, length=10)
    return f"{slug}-{suffix}.mp3"


def generate_audio_bundle(
    note: InputNote,
    voice_options: VoiceOptions,
    media_dir: Path,
) -> PreparedNote:
    logger = get_logger()
    ensure_ffmpeg_available()
    media_dir.mkdir(parents=True, exist_ok=True)

    selection = resolve_voice_selection(note, voice_options)
    voice_a, voice_b = choose_voices(note, selection)
    final_filename = build_audio_filename(note)
    final_path = media_dir / final_filename

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
        )
        voice_b = synthesize_with_fallback(
            note,
            selection,
            voice_b,
            voice_options.slow_rate,
            segment_b,
        )

        clip_a = AudioSegment.from_file(segment_a, format="mp3")
        clip_b = AudioSegment.from_file(segment_b, format="mp3")
        pause = AudioSegment.silent(duration=PAUSE_MS)
        combined = clip_a + pause + clip_b
        combined.export(final_path, format="mp3")

    return PreparedNote(
        input_note=note,
        guid=stable_guid(note.frase_fr),
        audio_filename=final_filename,
        audio_field=f"[sound:{final_filename}]",
        tags=[],
    )
