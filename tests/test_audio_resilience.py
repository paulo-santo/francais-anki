from __future__ import annotations

import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from francais_anki import audio, builder
from francais_anki.models import (
    DeckInput,
    InputNote,
    PreparedNote,
    RetryPassStatus,
    TtsOptions,
    VoiceOptions,
)


def make_note(text: str = "bonjour") -> InputNote:
    return InputNote(
        frase_fr=text,
        traducao_pt="ola",
        ipa="",
        observacao="",
        audio_text=text,
    )


def make_deck_input() -> DeckInput:
    return DeckInput(
        deck_name="Deck",
        subdeck_theme="Tema",
        level_tag="A1",
        theme_tag="numeros",
        notes=[make_note("un"), make_note("deux")],
        voice_options=VoiceOptions(
            male_voices=["fr-FR-HenriNeural"],
            female_voices=["fr-FR-DeniseNeural"],
        ),
    )


def make_prepared(note: InputNote) -> PreparedNote:
    return PreparedNote(
        input_note=note,
        guid=f"guid-{note.frase_fr}",
        audio_filename=f"{note.frase_fr}.mp3",
        audio_field=f"[sound:{note.frase_fr}.mp3]",
        tags=[],
    )


class AudioResilienceTests(unittest.TestCase):
    def test_input_note_normalizes_digit_only_audio_text_to_french_words(self) -> None:
        note = InputNote.from_dict(
            {
                "frase_fr": "84",
                "traducao_pt": "84",
                "audio_text": "84",
            }
        )

        self.assertEqual(note.audio_text, "quatre-vingt-quatre")

    def test_build_audio_filename_depends_on_normalized_audio_text(self) -> None:
        numeric_note = InputNote.from_dict(
            {
                "frase_fr": "84",
                "traducao_pt": "84",
                "audio_text": "84",
            }
        )
        literal_note = InputNote.from_dict(
            {
                "frase_fr": "84",
                "traducao_pt": "84",
                "audio_text": "eighty-four",
            }
        )

        self.assertNotEqual(
            audio.build_audio_filename(numeric_note),
            audio.build_audio_filename(literal_note),
        )

    def test_synthesize_with_retries_retries_transient_timeout(self) -> None:
        note = make_note()
        calls: list[int] = []

        async def fake_synthesize_mp3(*args, **kwargs) -> None:
            calls.append(1)
            if len(calls) == 1:
                raise asyncio.TimeoutError("slow socket")

        with (
            patch("francais_anki.audio.synthesize_mp3", fake_synthesize_mp3),
            patch("francais_anki.audio.time.sleep"),
        ):
            audio.synthesize_with_retries(
                note=note,
                voice="fr-FR-HenriNeural",
                rate="+0%",
                output_path=Path("ignored.mp3"),
                tts_options=TtsOptions(retries=2),
            )

        self.assertEqual(len(calls), 2)

    def test_resolve_voice_selection_prefers_monolingual_voices_for_digit_notes(self) -> None:
        note = InputNote.from_dict(
            {
                "frase_fr": "57",
                "traducao_pt": "57",
                "audio_text": "57",
            }
        )
        voice_options = VoiceOptions(
            male_voices=["fr-FR-RemyMultilingualNeural", "fr-FR-HenriNeural"],
            female_voices=["fr-FR-VivienneMultilingualNeural", "fr-FR-DeniseNeural"],
        )

        selection = audio.resolve_voice_selection(note, voice_options)

        self.assertEqual(selection.male_voices, ["fr-FR-HenriNeural"])
        self.assertEqual(selection.female_voices, ["fr-FR-DeniseNeural"])
        self.assertNotIn("fr-FR-RemyMultilingualNeural", selection.all_voices)
        self.assertNotIn("fr-FR-VivienneMultilingualNeural", selection.all_voices)

    def test_synthesize_with_fallback_uses_next_voice_after_failures(self) -> None:
        note = make_note()
        selection = audio.VoiceSelection(
            all_voices=["fr-FR-HenriNeural", "fr-FR-DeniseNeural"],
            male_voices=["fr-FR-HenriNeural"],
            female_voices=["fr-FR-DeniseNeural"],
        )
        attempted: list[str] = []

        def fake_synthesize_with_retries(*, voice: str, **kwargs) -> None:
            attempted.append(voice)
            if voice == "fr-FR-HenriNeural":
                raise audio.AudioGenerationError("timeout", attempted_voices=[voice])

        with patch("francais_anki.audio.synthesize_with_retries", fake_synthesize_with_retries):
            selected = audio.synthesize_with_fallback(
                note=note,
                selection=selection,
                preferred_voice="fr-FR-HenriNeural",
                rate="+0%",
                output_path=Path("ignored.mp3"),
                tts_options=TtsOptions(),
            )

        self.assertEqual(selected, "fr-FR-DeniseNeural")
        self.assertEqual(attempted, ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"])

    def test_generate_audio_bundle_reuses_existing_audio(self) -> None:
        note = make_note()
        voice_options = VoiceOptions(
            male_voices=["fr-FR-HenriNeural"],
            female_voices=["fr-FR-DeniseNeural"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir)
            existing_path = media_dir / audio.build_audio_filename(note)
            existing_path.write_bytes(b"existing mp3")

            with (
                patch("francais_anki.audio.ensure_ffmpeg_available"),
                patch("francais_anki.audio.synthesize_with_fallback") as synth_mock,
            ):
                prepared = audio.generate_audio_bundle(
                    note=note,
                    voice_options=voice_options,
                    tts_options=TtsOptions(),
                    media_dir=media_dir,
                )

        synth_mock.assert_not_called()
        self.assertEqual(prepared.audio_filename, existing_path.name)

    def test_prepare_notes_retries_failed_notes_in_second_pass(self) -> None:
        deck_input = make_deck_input()
        attempts: dict[str, int] = {}

        def fake_generate_audio_bundle(*, note: InputNote, **kwargs) -> PreparedNote:
            attempts[note.frase_fr] = attempts.get(note.frase_fr, 0) + 1
            if note.frase_fr == "deux" and attempts[note.frase_fr] == 1:
                raise audio.AudioGenerationError("timeout", attempted_voices=["voice-a"])
            return make_prepared(note)

        with patch("francais_anki.builder.generate_audio_bundle", fake_generate_audio_bundle):
            result = builder.prepare_notes(
                deck_input=deck_input,
                media_dir=Path("ignored"),
                tts_options=TtsOptions(final_retry_pass=True),
            )

        self.assertEqual(result.first_pass_successes, 1)
        self.assertEqual(result.recovered_on_retry, 1)
        self.assertEqual(result.total_notes, 2)
        self.assertEqual(result.retry_pass_status, RetryPassStatus.ENABLED_AND_EXECUTED)
        self.assertEqual(len(result.failed_notes), 0)
        self.assertEqual(len(result.prepared_notes), 2)
        self.assertEqual(attempts["deux"], 2)

    def test_prepare_notes_keeps_failure_when_retry_pass_disabled(self) -> None:
        deck_input = make_deck_input()

        def fake_generate_audio_bundle(*, note: InputNote, **kwargs) -> PreparedNote:
            if note.frase_fr == "deux":
                raise audio.AudioGenerationError("timeout", attempted_voices=["voice-a"])
            return make_prepared(note)

        with patch("francais_anki.builder.generate_audio_bundle", fake_generate_audio_bundle):
            result = builder.prepare_notes(
                deck_input=deck_input,
                media_dir=Path("ignored"),
                tts_options=TtsOptions(final_retry_pass=False),
            )

        self.assertEqual(result.first_pass_successes, 1)
        self.assertEqual(result.recovered_on_retry, 0)
        self.assertEqual(result.total_notes, 2)
        self.assertEqual(result.retry_pass_status, RetryPassStatus.DISABLED)
        self.assertEqual(len(result.failed_notes), 1)
        self.assertEqual(result.failed_notes[0].note.frase_fr, "deux")

    def test_prepare_notes_logs_progress_and_final_summary(self) -> None:
        deck_input = make_deck_input()
        logger = logging.getLogger("francais_anki")

        def fake_generate_audio_bundle(*, note: InputNote, **kwargs) -> PreparedNote:
            if note.frase_fr == "deux":
                raise audio.AudioGenerationError("timeout", attempted_voices=["voice-a"])
            return make_prepared(note)

        with (
            patch("francais_anki.builder.generate_audio_bundle", fake_generate_audio_bundle),
            self.assertLogs(logger, level="INFO") as captured,
        ):
            builder.prepare_notes(
                deck_input=deck_input,
                media_dir=Path("ignored"),
                tts_options=TtsOptions(final_retry_pass=False),
            )

        log_output = "\n".join(captured.output)
        self.assertIn("primeira passada [1/2] Preparando nota 'un'", log_output)
        self.assertIn("primeira passada [2/2] Preparando nota 'deux'", log_output)
        self.assertIn("Resumo da geracao de audio: 1/2 nota(s) gerada(s) com audio", log_output)
        self.assertIn("Status do reprocessamento: reprocessamento desabilitado.", log_output)
        self.assertIn("Notas nao geradas: deux", log_output)

    def test_cli_parser_accepts_resilience_flags(self) -> None:
        parser = __import__("francais_anki.cli", fromlist=["build_parser"]).build_parser()

        args = parser.parse_args(
            [
                "--input",
                "data/input.minimal.json",
                "--tts-connect-timeout",
                "20",
                "--tts-receive-timeout",
                "90",
                "--tts-retries",
                "4",
                "--no-tts-final-retry-pass",
            ]
        )

        self.assertEqual(args.tts_connect_timeout, 20)
        self.assertEqual(args.tts_receive_timeout, 90)
        self.assertEqual(args.tts_retries, 4)
        self.assertFalse(args.tts_final_retry_pass)

    def test_cli_parser_accepts_input_dir(self) -> None:
        parser = __import__("francais_anki.cli", fromlist=["build_parser"]).build_parser()

        args = parser.parse_args(
            [
                "--input-dir",
                "data/todo",
            ]
        )

        self.assertEqual(args.input_dir, Path("data/todo"))
        self.assertIsNone(args.input)

    def test_discover_input_files_supports_single_file_and_recursive_directory(self) -> None:
        cli = __import__("francais_anki.cli", fromlist=["discover_input_files"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            single_file = root / "one.json"
            nested_dir = root / "nested" / "deeper"
            nested_dir.mkdir(parents=True)
            nested_file = nested_dir / "two.json"
            ignored_file = root / "ignore.txt"

            single_file.write_text("{}", encoding="utf-8")
            nested_file.write_text("{}", encoding="utf-8")
            ignored_file.write_text("x", encoding="utf-8")

            self.assertEqual(cli.discover_input_files(single_file), [single_file.resolve()])
            self.assertEqual(
                cli.discover_input_files(root),
                sorted([single_file.resolve(), nested_file.resolve()]),
            )


if __name__ == "__main__":
    unittest.main()
