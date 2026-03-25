from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any

from .config import DEFAULT_BASE_DECK
from .voice_discovery import VoiceCatalog, VoiceWeights

DEFAULT_MALE_VOICES = ["fr-FR-HenriNeural", "fr-FR-RemyMultilingualNeural"]
DEFAULT_FEMALE_VOICES = ["fr-FR-DeniseNeural", "fr-FR-VivienneMultilingualNeural"]
DEFAULT_NORMAL_RATE = "+0%"
DEFAULT_SLOW_RATE = "-12%"
FRENCH_UNITS = {
    0: "zero",
    1: "un",
    2: "deux",
    3: "trois",
    4: "quatre",
    5: "cinq",
    6: "six",
    7: "sept",
    8: "huit",
    9: "neuf",
    10: "dix",
    11: "onze",
    12: "douze",
    13: "treize",
    14: "quatorze",
    15: "quinze",
    16: "seize",
}
TENS_WORDS = {
    20: "vingt",
    30: "trente",
    40: "quarante",
    50: "cinquante",
    60: "soixante",
}


@dataclass(slots=True)
class VoiceOptions:
    # When a catalog is provided, voices are selected dynamically per phrase
    # based on configured weights.
    catalog: VoiceCatalog | None = None
    weights: VoiceWeights = field(default_factory=VoiceWeights)
    # Used when no catalog is available.
    male_voices: list[str] = field(default_factory=list)
    female_voices: list[str] = field(default_factory=list)
    normal_rate: str = DEFAULT_NORMAL_RATE
    slow_rate: str = DEFAULT_SLOW_RATE

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, catalog: VoiceCatalog | None = None) -> "VoiceOptions":
        payload = payload or {}
        weights = VoiceWeights(
            fr_fr=payload.get("fr_fr_weight", 0.8),
            fr_extended=payload.get("fr_extended_weight", 0.2),
            fr_ca=payload.get("fr_ca_weight", 0.0),
        )

        if catalog:
            return cls(
                catalog=catalog,
                weights=weights,
                normal_rate=str(payload.get("normal_rate", DEFAULT_NORMAL_RATE)),
                slow_rate=str(payload.get("slow_rate", DEFAULT_SLOW_RATE)),
            )

        male_voices = list(payload.get("male_voices") or DEFAULT_MALE_VOICES)
        female_voices = list(payload.get("female_voices") or DEFAULT_FEMALE_VOICES)
        return cls(
            weights=weights,
            male_voices=male_voices,
            female_voices=female_voices,
            normal_rate=str(payload.get("normal_rate", DEFAULT_NORMAL_RATE)),
            slow_rate=str(payload.get("slow_rate", DEFAULT_SLOW_RATE)),
        )


@dataclass(slots=True)
class TtsOptions:
    connect_timeout: int = 10
    receive_timeout: int = 60
    retries: int = 2
    final_retry_pass: bool = True


def french_number_to_words(value: int) -> str:
    if value < 0 or value > 9999:
        raise ValueError(f"Numero fora do intervalo suportado: {value}")
    if value < 17:
        return FRENCH_UNITS[value]
    if value < 20:
        return f"dix-{FRENCH_UNITS[value - 10]}"
    if value < 100:
        return _french_below_hundred(value)
    if value < 1000:
        return _french_below_thousand(value)

    thousands, remainder = divmod(value, 1000)
    if thousands == 1:
        prefix = "mille"
    else:
        prefix = f"{french_number_to_words(thousands)} mille"

    if remainder == 0:
        return prefix
    return f"{prefix} {french_number_to_words(remainder)}"


def normalize_french_audio_text(text: str) -> str:
    normalized = text.strip()
    if not re.fullmatch(r"\d+", normalized):
        return normalized

    try:
        return french_number_to_words(int(normalized))
    except ValueError:
        return normalized


def _french_below_hundred(value: int) -> str:
    if value < 17:
        return FRENCH_UNITS[value]
    if value < 20:
        return f"dix-{FRENCH_UNITS[value - 10]}"
    if value < 70:
        tens = (value // 10) * 10
        unit = value % 10
        tens_word = TENS_WORDS[tens]
        if unit == 0:
            return tens_word
        if unit == 1:
            return f"{tens_word} et un"
        return f"{tens_word}-{FRENCH_UNITS[unit]}"
    if value < 80:
        if value == 71:
            return "soixante et onze"
        return f"soixante-{_french_below_hundred(value - 60)}"
    if value == 80:
        return "quatre-vingts"
    return f"quatre-vingt-{_french_below_hundred(value - 80)}"


def _french_below_thousand(value: int) -> str:
    hundreds, remainder = divmod(value, 100)
    if hundreds == 1:
        prefix = "cent"
    else:
        prefix = f"{FRENCH_UNITS[hundreds]} cent"

    if remainder == 0:
        return f"{prefix}s" if hundreds > 1 else prefix
    return f"{prefix} {french_number_to_words(remainder)}"


@dataclass(slots=True)
class InputNote:
    frase_fr: str
    traducao_pt: str
    ipa: str
    observacao: str
    audio_text: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InputNote":
        raw_audio_text = str(payload.get("audio_text") or payload["frase_fr"]).strip()
        return cls(
            frase_fr=str(payload["frase_fr"]).strip(),
            traducao_pt=str(payload.get("traducao_pt", "")).strip(),
            ipa=str(payload.get("ipa", "")).strip(),
            observacao=str(payload.get("observacao", "")).strip(),
            audio_text=normalize_french_audio_text(raw_audio_text),
        )


@dataclass(slots=True)
class DeckInput:
    deck_name: str
    subdeck_theme: str
    level_tag: str
    theme_tag: str
    notes: list[InputNote]
    voice_options: VoiceOptions = field(default_factory=VoiceOptions)

    @property
    def full_deck_name(self) -> str:
        deck_name = self.deck_name.strip() or DEFAULT_BASE_DECK
        return f"{deck_name}::{self.subdeck_theme.strip()}"

    @property
    def note_tags(self) -> list[str]:
        return ["alliance-francaise", self.level_tag, self.theme_tag]

    @classmethod
    def from_dict(cls, payload: dict[str, Any], voice_catalog: VoiceCatalog | None = None) -> "DeckInput":
        notes = [InputNote.from_dict(item) for item in payload.get("notes", [])]
        return cls(
            deck_name=str(payload.get("deck_name") or DEFAULT_BASE_DECK).strip(),
            subdeck_theme=str(payload["subdeck_theme"]).strip(),
            level_tag=str(payload["level_tag"]).strip(),
            theme_tag=str(payload["theme_tag"]).strip(),
            notes=notes,
            voice_options=VoiceOptions.from_dict(payload.get("voice_options"), voice_catalog),
        )


@dataclass(slots=True)
class PreparedNote:
    input_note: InputNote
    guid: str
    audio_filename: str
    audio_field: str
    tags: list[str]


@dataclass(slots=True)
class NotePreparationFailure:
    note: InputNote
    attempted_voices: list[str]
    error_message: str


class RetryPassStatus(StrEnum):
    ENABLED_AND_EXECUTED = "reprocessamento habilitado e executado"
    ENABLED_NOT_NEEDED = "reprocessamento habilitado, mas nao foi necessario"
    DISABLED = "reprocessamento desabilitado"


@dataclass(slots=True)
class PrepareNotesResult:
    prepared_notes: list[PreparedNote]
    total_notes: int = 0
    first_pass_successes: int = 0
    recovered_on_retry: int = 0
    retry_pass_status: RetryPassStatus = RetryPassStatus.ENABLED_NOT_NEEDED
    failed_notes: list[NotePreparationFailure] = field(default_factory=list)
