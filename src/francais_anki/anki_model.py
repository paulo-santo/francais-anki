from __future__ import annotations

import html

import genanki

from .config import DEFAULT_MODEL_NAME
from .utils import stable_numeric_id

MODEL_CSS = """
.card {
  font-family: Arial, sans-serif;
  font-size: 22px;
  text-align: center;
  color: #222;
  background-color: #ffffff;
  padding: 20px;
  line-height: 1.5;
}

.frase {
  font-size: 30px;
  font-weight: 600;
  line-height: 1.4;
  margin-bottom: 18px;
}

.audio {
  margin: 18px 0;
}

.traducao {
  margin-top: 10px;
  font-size: 22px;
  color: #1f4d7a;
}

.ipa {
  margin-top: 16px;
  font-size: 22px;
  color: #6a1b9a;
}

.obs {
  margin-top: 14px;
  font-size: 18px;
  color: #555;
  font-style: italic;
}

details {
  margin-top: 16px;
}

summary {
  cursor: pointer;
  font-size: 18px;
  color: #444;
}

hr {
  margin: 20px 0;
}
""".strip()


class StableGuidNote(genanki.Note):
    def __init__(self, *args, stable_guid: str, **kwargs) -> None:
        self._stable_guid = stable_guid
        super().__init__(*args, **kwargs)

    @property
    def guid(self) -> str:
        return self._stable_guid


def create_model() -> genanki.Model:
    return genanki.Model(
        model_id=stable_numeric_id(DEFAULT_MODEL_NAME),
        name=DEFAULT_MODEL_NAME,
        fields=[
            {"name": "FraseFR"},
            {"name": "Audio"},
            {"name": "TraducaoPT"},
            {"name": "IPA"},
            {"name": "Observacao"},
        ],
        templates=[
            {
                "name": "Leitura e Pronuncia",
                "qfmt": """{{#FraseFR}}
<div class="frase">{{FraseFR}}</div>
{{/FraseFR}}""",
                "afmt": """{{FrontSide}}

<hr id=answer>

{{#Audio}}
<div class="audio">{{Audio}}</div>
{{/Audio}}

{{#TraducaoPT}}
<details>
  <summary>Mostrar traducao</summary>
  <div class="traducao">{{TraducaoPT}}</div>
  {{#Observacao}}
  <div class="obs">{{Observacao}}</div>
  {{/Observacao}}
</details>
{{/TraducaoPT}}

{{#IPA}}
<div class="ipa">{{IPA}}</div>
{{/IPA}}""",
            },
            {
                "name": "Audicao",
                "qfmt": """{{#Audio}}
<div class="audio">{{Audio}}</div>
{{/Audio}}""",
                "afmt": """{{FrontSide}}

<hr id=answer>

{{#FraseFR}}
<div class="frase">{{FraseFR}}</div>
{{/FraseFR}}

{{#TraducaoPT}}
<details>
  <summary>Mostrar traducao</summary>
  <div class="traducao">{{TraducaoPT}}</div>
  {{#Observacao}}
  <div class="obs">{{Observacao}}</div>
  {{/Observacao}}
</details>
{{/TraducaoPT}}

{{#IPA}}
<div class="ipa">{{IPA}}</div>
{{/IPA}}""",
            },
        ],
        css=MODEL_CSS,
        sort_field_index=0,
    )


def escaped_fields(
    frase_fr: str,
    audio: str,
    traducao_pt: str,
    ipa: str,
    observacao: str,
) -> list[str]:
    return [
        html.escape(frase_fr),
        audio,
        html.escape(traducao_pt),
        html.escape(ipa),
        html.escape(observacao),
    ]
