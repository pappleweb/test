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


# Voix ElevenLabs prêtes à l'emploi (noms simples -> identifiants).
# Voix féminines adaptées au français via le modèle eleven_multilingual_v2.
ELEVEN_VOICES = {
    "charlotte": "XB0fDUnXU5powFXDhCwa",
    "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "lily": "pFZP5JQG7iQjIQuC4Bku",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
}


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


def synthesize(text: str, voice: str, mp3_path: str,
               engine: str = "edge", allow_fallback: bool = True) -> VoiceClip:
    """Synthétise `text`.

    engine : "eleven" (ElevenLabs, voix premium + timing précis),
             "edge"   (Microsoft, gratuit, timing exact),
             "espeak" (hors-ligne, sans réseau).
    """
    if engine == "espeak":
        return _synthesize_espeak(text, mp3_path)

    if engine == "eleven":
        try:
            return _synthesize_eleven(text, mp3_path)
        except Exception as e:
            if not allow_fallback:
                raise
            print(f"[tts] ElevenLabs indisponible ({type(e).__name__}: {e}); repli espeak-ng.")
            return _synthesize_espeak(text, mp3_path)

    try:
        words = asyncio.run(_synth_one(text, voice, mp3_path))
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"[tts] Edge-TTS indisponible ({type(e).__name__}); repli hors-ligne espeak-ng.")
        return _synthesize_espeak(text, mp3_path)

    duration = _probe_duration(mp3_path)
    # Garde-fou : caler la fin du dernier mot sur la durée réelle de l'audio.
    if words and words[-1].end > duration:
        words[-1].end = duration
    return VoiceClip(mp3_path=mp3_path, duration=duration, words=words)


def _synthesize_eleven(text: str, out_path: str) -> VoiceClip:
    """Voix premium ElevenLabs avec calage au mot via l'endpoint *with-timestamps*.

    Nécessite ELEVENLABS_API_KEY (offre gratuite ~10k caractères/mois).
    Voix féminine FR par défaut ("Charlotte") ; modifiable via ELEVENLABS_VOICE_ID.
    """
    import base64

    import requests

    from .config import SETTINGS

    key = SETTINGS.elevenlabs_api_key
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY manquante")

    # On accepte un nom de voix simple ("charlotte", "alice"…) ou un ID brut.
    voice_id = ELEVEN_VOICES.get(SETTINGS.elevenlabs_voice_id.lower(),
                                 SETTINGS.elevenlabs_voice_id)
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/"
        f"{voice_id}/with-timestamps"
    )
    resp = requests.post(
        url,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": SETTINGS.elevenlabs_model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))

    words = _words_from_char_alignment(data.get("alignment") or {})
    duration = _probe_duration(out_path)
    if not words:
        words = _approx_word_timings(text, duration)
    return VoiceClip(mp3_path=out_path, duration=duration, words=words)


def _words_from_char_alignment(alignment: dict) -> list[WordTiming]:
    """Convertit l'alignement caractère par caractère d'ElevenLabs en timings de mots."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not (len(chars) == len(starts) == len(ends)) or not chars:
        return []

    words: list[WordTiming] = []
    cur, cur_start, cur_end = "", None, None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append(WordTiming(cur, cur_start, cur_end))
                cur, cur_start, cur_end = "", None, None
        else:
            if not cur:
                cur_start = st
            cur += ch
            cur_end = en
    if cur:
        words.append(WordTiming(cur, cur_start, cur_end))
    return words


def _synthesize_espeak(text: str, out_path: str) -> VoiceClip:
    """Voix off 100 % hors-ligne via espeak-ng (qualité 'preview', sans réseau).

    espeak ne fournit pas le timing des mots : on l'approxime proportionnellement
    à la longueur des mots sur la durée réelle de l'audio.
    """
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    try:
        subprocess.run(
            ["espeak-ng", "-v", "fr", "-s", "155", "-p", "40", "-w", wav, text],
            capture_output=True, check=True,
        )
        # Transcode en mp3 pour rester homogène avec le reste du pipeline.
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav, "-c:a", "libmp3lame", "-q:a", "4", out_path],
            capture_output=True, check=True,
        )
    finally:
        if os.path.exists(wav):
            os.remove(wav)

    duration = _probe_duration(out_path)
    words = _approx_word_timings(text, duration)
    return VoiceClip(mp3_path=out_path, duration=duration, words=words)


def _approx_word_timings(text: str, duration: float) -> list[WordTiming]:
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]  # +1 pour la pause inter-mots
    total = sum(weights)
    out: list[WordTiming] = []
    t = 0.0
    for tok, w in zip(tokens, weights):
        dt = duration * w / total
        out.append(WordTiming(text=tok, start=t, end=t + dt))
        t += dt
    return out


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())
