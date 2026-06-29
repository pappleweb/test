"""Option vidéo — un court clip vertical par scène depuis Pexels Videos (gratuit).

Activé par VISUAL_MODE=video. Même clé que les photos (PEXELS_API_KEY). Si aucun
clip n'est trouvé pour une scène, l'appelant retombe sur une image fixe (mode par
défaut) : un short sort donc toujours.
"""
from __future__ import annotations

import os

import requests

from .config import SETTINGS

_TIMEOUT = 30


def fetch_clip(query: str, dst_path: str, seed: int = 0) -> str | None:
    """Télécharge un clip vertical pour `query` vers `dst_path`. Renvoie le chemin ou None."""
    if not SETTINGS.pexels_api_key:
        return None
    url = _pexels_video(query, seed)
    if url and _download(url, dst_path):
        return dst_path
    return None


def _pexels_video(query: str, seed: int) -> str | None:
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": SETTINGS.pexels_api_key},
            params={"query": query, "orientation": "portrait", "per_page": 10, "size": "medium"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
        if not videos:
            return None
        vid = videos[seed % len(videos)]
        # On ne garde que les fichiers mp4 portrait, et on vise ~1080x1920
        # (évite de télécharger de l'UHD 4K inutile : ffmpeg recadre ensuite).
        files = [
            f for f in vid.get("video_files", [])
            if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)
        ]
        if not files:
            return None
        best = min(files, key=lambda f: abs((f.get("height") or 0) - 1920))
        return best.get("link")
    except Exception as e:
        print(f"[videos] Pexels: {e}")
        return None


def _download(url: str, dst_path: str) -> bool:
    try:
        r = requests.get(url, timeout=_TIMEOUT, stream=True)
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        return os.path.getsize(dst_path) > 10240
    except Exception as e:
        print(f"[videos] téléchargement: {e}")
        return False
