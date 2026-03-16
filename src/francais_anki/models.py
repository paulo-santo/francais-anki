from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_BASE_DECK


@dataclass(slots=True)
class VoiceOptions:
    male_voices: list[str] = field(
        default_factory=lambda: [
            "fr-FR-HenriNeural",
            "fr-FR-RemyMultilingualNeural",
        ]
    )
    female_voices: list[str] = field(
        default_factory=lambda: [
            "fr-FR-DeniseNeural",
            "fr-FR-VivienneMultilingualNeural",
        ]
    )
    normal_rate: str = "+0%"
    slow_rate: str = "-12%"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "VoiceOptions":
        payload = payload or {}
        return cls(
            male_voices=list(payload.get("male_voices") or cls().male_voices),
            female_voices=list(payload.get("female_voices") or cls().female_voices),
            normal_rate=str(payload.get("normal_rate", cls().normal_rate)),
            slow_rate=str(payload.get("slow_rate", cls().slow_rate)),
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
    def from_dict(cls, payload: dict[str, Any]) -> "DeckInput":
        notes = [InputNote.from_dict(item) for item in payload.get("notes", [])]
        return cls(
            deck_name=str(payload.get("deck_name") or DEFAULT_BASE_DECK).strip(),
            subdeck_theme=str(payload["subdeck_theme"]).strip(),
            level_tag=str(payload["level_tag"]).strip(),
            theme_tag=str(payload["theme_tag"]).strip(),
            notes=notes,
            voice_options=VoiceOptions.from_dict(payload.get("voice_options")),
        )


@dataclass(slots=True)
class PreparedNote:
    input_note: InputNote
    guid: str
    audio_filename: str
    audio_field: str
    tags: list[str]
