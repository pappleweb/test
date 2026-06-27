"""Configuration centrale et réglages par défaut."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# --- Format vidéo : YouTube Short = vertical 9:16, 1080x1920 ---
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Police des sous-titres : nom reconnu par libass (fontconfig).
# Liberation Sans = très proche d'Arial/Helvetica, rendu net et "neutre" idéal pour les Shorts.
CAPTION_FONT = os.getenv("CAPTION_FONT", "Liberation Sans")
# Fichier de police pour la bannière incrustée (drawtext a besoin du chemin).
FONT_FILE = os.getenv(
    "FONT_FILE", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
)


@dataclass
class Settings:
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    pexels_api_key: str | None = os.getenv("PEXELS_API_KEY")
    pixabay_api_key: str | None = os.getenv("PIXABAY_API_KEY")
    # Images : "stock" (banque gratuite Pexels/Pixabay, défaut) ou "flux" (IA générative).
    image_provider: str = os.getenv("IMAGE_PROVIDER", "stock")
    # FLUX via fal.ai. schnell = le moins cher (~0,003 $/image) ; dev/pro = endpoints à changer ici.
    fal_api_key: str | None = os.getenv("FAL_KEY")
    flux_endpoint: str = os.getenv("FLUX_ENDPOINT", "https://fal.run/fal-ai/flux/schnell")
    # Style commun ajouté à chaque prompt -> images cohérentes entre les scènes.
    image_style: str = os.getenv(
        "IMAGE_STYLE",
        "vertical 9:16 photograph, natural warm lighting, vivid appetizing colors, "
        "sharp focus, high detail, professional, no text, no watermark",
    )
    tts_voice: str = os.getenv("TTS_VOICE", "fr-FR-DeniseNeural")
    # ElevenLabs (offre gratuite ~10k caractères/mois). Voix féminine FR par défaut : "Charlotte".
    elevenlabs_api_key: str | None = os.getenv("ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "XB0fDUnXU5powFXDhCwa")
    elevenlabs_model: str = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    site_url: str = os.getenv("SITE_URL", "https://mon-site.fr")
    # Durée cible de la narration (un Short fait <= 60 s).
    target_seconds: int = int(os.getenv("TARGET_SECONDS", "45"))


SETTINGS = Settings()
