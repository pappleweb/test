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

# Police utilisée pour les sous-titres et l'appel à l'action (présente sur la plupart des Linux).
FONT_NAME = "DejaVu Sans"
FONT_FILE = os.getenv(
    "FONT_FILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)


@dataclass
class Settings:
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    pexels_api_key: str | None = os.getenv("PEXELS_API_KEY")
    pixabay_api_key: str | None = os.getenv("PIXABAY_API_KEY")
    tts_voice: str = os.getenv("TTS_VOICE", "fr-FR-DeniseNeural")
    site_url: str = os.getenv("SITE_URL", "https://mon-site.fr")
    # Durée cible de la narration (un Short fait <= 60 s).
    target_seconds: int = int(os.getenv("TARGET_SECONDS", "45"))


SETTINGS = Settings()
