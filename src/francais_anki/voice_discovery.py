from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

import edge_tts


# Fallback voices used when dynamic discovery fails or yields no results.
FALLBACK_FR_FR_VOICES = [
    "fr-FR-HenriNeural",
    "fr-FR-RemyMultilingualNeural",
    "fr-FR-DeniseNeural",
    "fr-FR-VivienneMultilingualNeural",
]
FALLBACK_FR_EXTENDED_VOICES = ["fr-BE-GerardNeural", "fr-CH-ArianeNeural"]
FALLBACK_FR_CA_VOICES = ["fr-CA-AntoineNeural", "fr-CA-JeanNeural", "fr-CA-SylvieNeural"]


@dataclass(slots=True)
class VoiceWeights:
    fr_fr: float = 0.8
    fr_extended: float = 0.2
    fr_ca: float = 0.0

    def normalized(self) -> "VoiceWeights":
        total = self.fr_fr + self.fr_extended + self.fr_ca
        if total <= 0:
            return VoiceWeights(fr_fr=1.0, fr_extended=0.0, fr_ca=0.0)
        return VoiceWeights(
            fr_fr=self.fr_fr / total,
            fr_extended=self.fr_extended / total,
            fr_ca=self.fr_ca / total,
        )


@dataclass(slots=True)
class VoiceCatalog:
    fr_fr_voices: list[str]
    fr_extended_voices: list[str]
    fr_ca_voices: list[str]


def classify_voice(voice: dict[str, Any]) -> str | None:
    locale = voice.get("Locale", "")
    if locale == "fr-FR":
        return "fr_fr"
    elif locale in ("fr-BE", "fr-CH"):
        return "fr_extended"
    elif locale == "fr-CA":
        return "fr_ca"
    return None


async def discover_voices_async() -> VoiceCatalog:
    voices = await edge_tts.list_voices()
    fr_fr: list[str] = []
    fr_extended: list[str] = []
    fr_ca: list[str] = []

    for voice in voices:
        category = classify_voice(voice)
        if category == "fr_fr":
            fr_fr.append(voice["ShortName"])
        elif category == "fr_extended":
            fr_extended.append(voice["ShortName"])
        elif category == "fr_ca":
            fr_ca.append(voice["ShortName"])

    # Ensure we always return non-empty categories for downstream usage.
    return VoiceCatalog(
        fr_fr_voices=fr_fr or FALLBACK_FR_FR_VOICES,
        fr_extended_voices=fr_extended or FALLBACK_FR_EXTENDED_VOICES,
        fr_ca_voices=fr_ca or FALLBACK_FR_CA_VOICES,
    )


def discover_voices() -> VoiceCatalog:
    try:
        return asyncio.run(asyncio.wait_for(discover_voices_async(), timeout=15.0))
    except Exception:
        return VoiceCatalog(
            fr_fr_voices=FALLBACK_FR_FR_VOICES,
            fr_extended_voices=FALLBACK_FR_EXTENDED_VOICES,
            fr_ca_voices=FALLBACK_FR_CA_VOICES,
        )


def infer_gender(voice_name: str) -> str:
    # Simple heuristic: if the name suggests a gender
    name_lower = voice_name.lower()
    if any(word in name_lower for word in ["henri", "remy", "antoine", "jean", "gerard"]):
        return "male"
    elif any(word in name_lower for word in ["denise", "vivienne", "ariane", "sylvie"]):
        return "female"
    return "female"


def voices_for_note(phrase: str, catalog: VoiceCatalog, weights: VoiceWeights) -> list[str]:
    """Select voices for a note based on phrase, using weights for distribution."""
    seed = hash(phrase) % (2**32)
    generator = random.Random(seed)
    normalized_weights = weights.normalized()

    # Select group based on weights
    group = _select_group(generator, normalized_weights)

    # Get voices from the selected group
    voices = _voices_for_group(catalog, group)

    # If the group is empty, fallback to fr_fr
    if not voices:
        voices = catalog.fr_fr_voices

    return voices


def _select_group(generator: random.Random, weights: VoiceWeights) -> str:
    """Select a voice group based on normalized weights."""
    rand = generator.random()
    if rand < weights.fr_fr:
        return "fr_fr"
    elif rand < weights.fr_fr + weights.fr_extended:
        return "fr_extended"
    else:
        return "fr_ca"


def _voices_for_group(catalog: VoiceCatalog, group: str) -> list[str]:
    """Get voices for a specific group."""
    if group == "fr_fr":
        return catalog.fr_fr_voices
    elif group == "fr_extended":
        return catalog.fr_extended_voices
    elif group == "fr_ca":
        return catalog.fr_ca_voices
    return []
