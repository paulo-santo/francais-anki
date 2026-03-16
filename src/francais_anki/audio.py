from __future__ import annotations

import asyncio
import random
import shutil
import tempfile
from pathlib import Path

import edge_tts
from pydub import AudioSegment

from .config import PAUSE_MS
from .models import InputNote, PreparedNote, VoiceOptions
from .utils import get_logger, slugify, stable_guid, stable_hash


class AudioGenerationError(RuntimeError):
    pass


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioGenerationError(
            "ffmpeg nao encontrado no PATH. Instale-o antes de gerar os audios."
        )


def choose_voices(note: InputNote, options: VoiceOptions) -> tuple[str, str]:
    seed = stable_hash(note.frase_fr, length=8)
    generator = random.Random(seed)
    male_voice = generator.choice(options.male_voices)
    female_voice = generator.choice(options.female_voices)
    if generator.choice([True, False]):
        return male_voice, female_voice
    return female_voice, male_voice


async def synthesize_mp3(text: str, voice: str, rate: str, output_path: Path) -> None:
    communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicator.save(str(output_path))


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

    voice_a, voice_b = choose_voices(note, voice_options)
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

        asyncio.run(synthesize_mp3(note.audio_text, voice_a, voice_options.normal_rate, segment_a))
        asyncio.run(synthesize_mp3(note.audio_text, voice_b, voice_options.slow_rate, segment_b))

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
