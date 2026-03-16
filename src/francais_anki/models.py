from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_BASE_DECK
from .voice_discovery import VoiceCatalog, VoiceWeights

DEFAULT_MALE_VOICES = ["fr-FR-HenriNeural", "fr-FR-RemyMultilingualNeural"]
DEFAULT_FEMALE_VOICES = ["fr-FR-DeniseNeural", "fr-FR-VivienneMultilingualNeural"]
DEFAULT_NORMAL_RATE = "+0%"
DEFAULT_SLOW_RATE = "-12%"


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
class InputNote:
    frase_fr: str
    traducao_pt: str
    ipa: str
    observacao: str
    audio_text: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InputNote":
        return cls(
            frase_fr=str(payload["frase_fr"]).strip(),
            traducao_pt=str(payload.get("traducao_pt", "")).strip(),
            ipa=str(payload.get("ipa", "")).strip(),
            observacao=str(payload.get("observacao", "")).strip(),
            audio_text=str(payload.get("audio_text") or payload["frase_fr"]).strip(),
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
