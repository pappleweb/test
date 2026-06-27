"""Étape 5 — sous-titres ASS façon Short : grand texte centré, mot prononcé surligné.

On reçoit, scène par scène, les timings mot-à-mot et l'instant de départ absolu de la
scène. On affiche une petite fenêtre de mots ; le mot en cours de lecture est mis en
valeur (couleur + léger zoom), ce qui donne le rendu dynamique typique des Shorts.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import HEIGHT, WIDTH, CAPTION_FONT
from .tts import WordTiming

_MAX_WORDS_PER_CUE = 3
_MAX_CHARS_PER_CUE = 18

# Couleurs ASS au format &HBBGGRR
_WHITE = "&H00FFFFFF"
_ACCENT = "&H0022DDFF"   # jaune chaud pour le mot actif
_OUTLINE = "&H00101010"

_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{CAPTION_FONT},108,{_WHITE},{_WHITE},{_OUTLINE},&H64000000,1,0,0,0,100,100,0,0,1,7,3,2,90,90,760,1
Style: CTA,{CAPTION_FONT},92,{_ACCENT},{_ACCENT},{_OUTLINE},&H64000000,1,0,0,0,100,100,0,0,1,7,3,2,90,90,300,1

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
        style = "CTA" if sc.is_cta else "Caption"
        for group in _group(sc.words):
            lines.extend(_highlighted_lines(group, sc.start_abs, style))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _group(words: list[WordTiming]):
    """Regroupe les mots en fenêtres courtes (≤3 mots / ≤18 caractères)."""
    cue: list[WordTiming] = []
    for w in words:
        candidate = cue + [w]
        text = " ".join(x.text for x in candidate)
        if cue and (len(candidate) > _MAX_WORDS_PER_CUE or len(text) > _MAX_CHARS_PER_CUE):
            yield cue
            cue = [w]
        else:
            cue = candidate
    if cue:
        yield cue


def _highlighted_lines(group: list[WordTiming], base: float, style: str) -> list[str]:
    """Une ligne Dialogue par mot actif : la fenêtre reste affichée, le mot lu s'illumine."""
    out = []
    for i, active in enumerate(group):
        start = base + active.start
        # On garde la fenêtre jusqu'au mot suivant pour un surlignage continu (sans clignotement).
        end = base + (group[i + 1].start if i + 1 < len(group) else active.end)
        if end <= start:
            end = start + 0.15
        out.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},{style},,0,0,,{_render(group, i)}"
        )
    return out


def _render(group: list[WordTiming], active_idx: int) -> str:
    parts = []
    for i, w in enumerate(group):
        word = _escape(w.text)
        if i == active_idx:
            # mot actif : couleur accent + léger zoom
            parts.append(f"{{\\c{_ACCENT}\\fscx116\\fscy116}}{word}{{\\r}}")
        else:
            parts.append(word)
    return " ".join(parts)


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()
