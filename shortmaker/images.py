"""Étape 4 — une image verticale par scène.

Ordre d'essai : [FLUX si IMAGE_PROVIDER=flux] -> Pexels -> Pixabay -> dégradé local.
Le repli est toujours assuré : si l'IA échoue (quota, refus, réseau), on retombe
sur la banque gratuite, puis sur un dégradé hors-ligne.
Les requêtes sont en anglais (meilleurs résultats sur les banques et les modèles).
"""
from __future__ import annotations

import hashlib
import os

import requests

from .config import HEIGHT, WIDTH, SETTINGS

_TIMEOUT = 20


def fetch_image(query: str, dst_path: str, seed: int = 0) -> str:
    """Télécharge une image portrait pour `query` vers `dst_path`. Renvoie le chemin."""
    if SETTINGS.image_provider == "flux" and SETTINGS.fal_api_key:
        url = _flux(query, seed)
        if url and _download(url, dst_path):
            return dst_path
        print("[images] FLUX indisponible -> repli banque gratuite.")
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


# ---------------------------------------------------------------- FLUX (fal.ai)

def _build_prompt(query: str) -> str:
    """Mot-clé de scène -> prompt descriptif + style commun (cohérence inter-scènes)."""
    return f"{query}. {SETTINGS.image_style}"


def _flux(query: str, seed: int) -> str | None:
    """Génère une image via FLUX (fal.ai) et renvoie son URL.

    Endpoint synchrone fal.run : un POST renvoie directement l'URL de l'image.
    Changer de modèle = changer FLUX_ENDPOINT (schnell par défaut, ou .../flux/dev).
    `requests` honore le proxy HTTPS + le CA de l'environnement.
    """
    try:
        r = requests.post(
            SETTINGS.flux_endpoint,
            headers={
                "Authorization": f"Key {SETTINGS.fal_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": _build_prompt(query),
                "image_size": "portrait_16_9",   # vertical 9:16
                "num_images": 1,
                "seed": seed,                      # reproductible par scène
                "enable_safety_checker": True,
            },
            timeout=120,
        )
        r.raise_for_status()
        images = r.json().get("images", [])
        if not images:
            return None
        return images[0].get("url")
    except Exception as e:
        print(f"[images] FLUX: {e}")
        return None


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
    """Arrière-plan graphique généré localement (sans réseau) : dégradé coloré vif,
    vignette et quelques halos lumineux. Couleur déterministe dérivée des mots-clés,
    donc chaque scène a un visuel distinct et net."""
    import colorsys

    from PIL import Image, ImageDraw, ImageFilter

    h = hashlib.md5(query.encode()).digest()
    hue = h[0] / 255.0                     # teinte vive propre à la scène
    hue2 = (hue + 0.08 + h[1] / 1024.0) % 1.0

    def rgb(hh, s, v):
        r, g, b = colorsys.hsv_to_rgb(hh, s, v)
        return int(r * 255), int(g * 255), int(b * 255)

    top = rgb(hue, 0.65, 0.95)             # haut clair et saturé
    bottom = rgb(hue2, 0.85, 0.32)         # bas plus sombre -> profondeur

    # Dégradé vertical (rapide, ligne par ligne sur une image fine puis redimensionnée).
    strip = Image.new("RGB", (1, HEIGHT))
    sp = strip.load()
    for y in range(HEIGHT):
        t = y / HEIGHT
        sp[0, y] = (
            int(top[0] * (1 - t) + bottom[0] * t),
            int(top[1] * (1 - t) + bottom[1] * t),
            int(top[2] * (1 - t) + bottom[2] * t),
        )
    img = strip.resize((WIDTH, HEIGHT))

    # Halos lumineux translucides (effet "bokeh") pour donner du relief.
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    od = ImageDraw.Draw(overlay)
    glow = rgb(hue, 0.45, 1.0)
    for i in range(3):
        cx = (h[2 + i] / 255.0) * WIDTH
        cy = (h[5 + i] / 255.0) * HEIGHT
        r = 180 + (h[8 + i] / 255.0) * 360
        od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=glow)
    overlay = overlay.filter(ImageFilter.GaussianBlur(160))
    img = Image.blend(img, overlay, 0.28)

    # Vignette (assombrit les bords) pour faire ressortir les sous-titres.
    vignette = Image.new("L", (WIDTH, HEIGHT), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-WIDTH * 0.3, -HEIGHT * 0.15, WIDTH * 1.3, HEIGHT * 1.15], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    img = Image.composite(img, dark, vignette)

    img.save(dst_path, "JPEG", quality=90)
