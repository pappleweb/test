"""Étape 4 — une image verticale par scène, depuis une banque GRATUITE.

Ordre d'essai : Pexels -> Pixabay -> dégradé généré localement (toujours dispo).
Les requêtes sont en anglais (meilleurs résultats sur ces banques).
"""
from __future__ import annotations

import hashlib
import os

import requests

from .config import HEIGHT, WIDTH, SETTINGS

_TIMEOUT = 20


def fetch_image(query: str, dst_path: str, seed: int = 0) -> str:
    """Télécharge une image portrait pour `query` vers `dst_path`. Renvoie le chemin."""
    if SETTINGS.pexels_api_key:
        url = _pexels(query, seed)
        if url and _download(url, dst_path):
            return dst_path
    if SETTINGS.pixabay_api_key:
        url = _pixabay(query, seed)
        if url and _download(url, dst_path):
            return dst_path
    # Dernier recours : on fabrique un fond dégradé lisible, hors-ligne.
    _gradient(query, dst_path)
    return dst_path


# ---------------------------------------------------------------- Pexels

def _pexels(query: str, seed: int) -> str | None:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": SETTINGS.pexels_api_key},
            params={"query": query, "orientation": "portrait", "per_page": 10, "size": "large"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            return None
        photo = photos[seed % len(photos)]
        return photo["src"].get("portrait") or photo["src"].get("large")
    except Exception as e:
        print(f"[images] Pexels: {e}")
        return None


# ---------------------------------------------------------------- Pixabay

def _pixabay(query: str, seed: int) -> str | None:
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": SETTINGS.pixabay_api_key,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "per_page": 10,
                "safesearch": "true",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        if not hits:
            return None
        return hits[seed % len(hits)].get("largeImageURL")
    except Exception as e:
        print(f"[images] Pixabay: {e}")
        return None


# ---------------------------------------------------------------- Helpers

def _download(url: str, dst_path: str) -> bool:
    try:
        r = requests.get(url, timeout=_TIMEOUT, stream=True)
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return os.path.getsize(dst_path) > 1024
    except Exception as e:
        print(f"[images] téléchargement: {e}")
        return False


def _gradient(query: str, dst_path: str) -> None:
    """Fond dégradé déterministe (couleur dérivée du texte) avec le mot-clé écrit dessus."""
    from PIL import Image, ImageDraw

    h = hashlib.md5(query.encode()).digest()
    top = (h[0], h[1], h[2])
    bottom = (h[3] // 2, h[4] // 2, h[5] // 2)

    img = Image.new("RGB", (WIDTH, HEIGHT))
    px = img.load()
    for y in range(HEIGHT):
        t = y / HEIGHT
        px_row = (
            int(top[0] * (1 - t) + bottom[0] * t),
            int(top[1] * (1 - t) + bottom[1] * t),
            int(top[2] * (1 - t) + bottom[2] * t),
        )
        for x in range(WIDTH):
            px[x, y] = px_row
    ImageDraw.Draw(img)  # (texte volontairement omis : les sous-titres suffisent)
    img.save(dst_path, "JPEG", quality=88)
