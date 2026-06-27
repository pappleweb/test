"""Étape 3 — voix off gratuite via Edge-TTS, avec le timing mot-à-mot.

On synthétise CHAQUE scène séparément : la durée de la scène = la durée de son audio.
Pas d'alignement approximatif à faire -> les images sont calées pile sur les paroles.
"""
from __future__ import annotations

import asyncio
import os
import ssl
import subprocess
from dataclasses import dataclass


def _trust_extra_ca() -> None:
    """Si un CA bundle d'entreprise/proxy est fourni, faire en sorte qu'Edge-TTS l'accepte.

    Edge-TTS impose un contexte SSL basé sur certifi ; on l'élargit pour tolérer les
    proxys qui interceptent le TLS (sinon : CERTIFICATE_VERIFY_FAILED).
    """
    ca = (
        os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or ("/root/.ccr/ca-bundle.crt" if os.path.exists("/root/.ccr/ca-bundle.crt") else None)
    )
    if not ca or not os.path.exists(ca):
        return
    try:
        import edge_tts.communicate as _c

        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cafile=ca)
        _c._SSL_CTX = ctx
    except Exception:
        pass


@dataclass
class WordTiming:
    text: str
    start: float  # secondes, relatif au début de la scène
    end: float


@dataclass
class VoiceClip:
    mp3_path: str
    duration: float           # secondes
    words: list[WordTiming]


async def _synth_one(text: str, voice: str, mp3_path: str) -> list[WordTiming]:
    import edge_tts

    _trust_extra_ca()
    # boundary="WordBoundary" -> timing mot-à-mot (le défaut est SentenceBoundary).
    communicate = edge_tts.Communicate(
        text, voice, boundary="WordBoundary", proxy=os.getenv("EDGE_TTS_PROXY") or None
    )
    words: list[WordTiming] = []
    with open(mp3_path, "wb") as out:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                out.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7            # 100 ns -> s
                end = (chunk["offset"] + chunk["duration"]) / 1e7
                words.append(WordTiming(text=chunk["text"], start=start, end=end))
    return words


def synthesize(text: str, voice: str, mp3_path: str) -> VoiceClip:
    words = asyncio.run(_synth_one(text, voice, mp3_path))
    duration = _probe_duration(mp3_path)
    # Garde-fou : caler la fin du dernier mot sur la durée réelle de l'audio.
    if words and words[-1].end > duration:
        words[-1].end = duration
    return VoiceClip(mp3_path=mp3_path, duration=duration, words=words)


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())
