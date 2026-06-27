"""Étape 5 — sous-titres ASS calés au mot près (style YouTube Short, gros texte centré).

On reçoit, scène par scène, les timings mot-à-mot (relatifs à la scène) et l'instant
de départ absolu de la scène. On regroupe les mots en petits paquets lisibles.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import HEIGHT, WIDTH, FONT_NAME
from .tts import WordTiming

_MAX_WORDS_PER_CUE = 3
_MAX_CHARS_PER_CUE = 22

_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT_NAME},96,&H00FFFFFF,&H00000000,&H64000000,1,0,1,6,2,2,80,80,520,1
Style: CTA,{FONT_NAME},78,&H0000F0FF,&H00000000,&H96000000,1,0,1,6,2,2,80,80,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""


@dataclass
class SceneCues:
    start_abs: float            # début absolu de la scène dans la vidéo (s)
    words: list[WordTiming]     # timings relatifs à la scène
    is_cta: bool = False


def build_ass(scenes: list[SceneCues], out_path: str) -> str:
    lines = [_HEADER]
    for sc in scenes:
        for cue_text, start, end in _group(sc.words):
            style = "CTA" if sc.is_cta else "Caption"
            lines.append(
                f"Dialogue: 0,{_ts(sc.start_abs + start)},{_ts(sc.start_abs + end)},"
                f"{style},,0,0,,{_escape(cue_text)}"
            )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _group(words: list[WordTiming]):
    """Regroupe les mots en cues courtes (≤3 mots / ≤22 caractères)."""
    cue: list[WordTiming] = []
    for w in words:
        candidate = cue + [w]
        text = " ".join(x.text for x in candidate)
        if cue and (len(candidate) > _MAX_WORDS_PER_CUE or len(text) > _MAX_CHARS_PER_CUE):
            yield _emit(cue)
            cue = [w]
        else:
            cue = candidate
    if cue:
        yield _emit(cue)


def _emit(cue: list[WordTiming]):
    text = " ".join(w.text for w in cue)
    return text, cue[0].start, cue[-1].end


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()
