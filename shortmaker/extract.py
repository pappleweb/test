"""Étape 1 — récupérer le texte de l'article depuis une URL, un fichier ou du texte brut."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin


@dataclass
class Article:
    title: str
    text: str
    url: str | None  # URL d'origine (sert à l'appel à l'action), None si texte brut
    images: list[str] = field(default_factory=list)  # URLs d'images trouvées dans le corps


def load_source(source: str) -> Article:
    """`source` peut être une URL http(s), un chemin de fichier, ou directement du texte."""
    if source.startswith(("http://", "https://")):
        return _from_url(source)
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            raw = f.read()
        return _from_text(raw, url=None)
    return _from_text(source, url=None)


def _from_url(url: str) -> Article:
    import trafilatura

    downloaded = _download_html(url)
    if not downloaded:
        raise RuntimeError(f"Impossible de télécharger l'article : {url}")

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        raise RuntimeError(f"Aucun texte exploitable extrait de : {url}")

    title = url
    try:
        meta = trafilatura.extract_metadata(downloaded)
        if meta and meta.title:
            title = meta.title
    except Exception:
        pass

    return Article(title=title.strip(), text=text.strip(), url=url,
                   images=_extract_images(downloaded, url))


# Fragments d'URL typiques d'éléments décoratifs (à écarter, pas du contenu d'article).
_IMG_BLOCKLIST = ("logo", "icon", "sprite", "avatar", "emoji", "favicon",
                  "placeholder", "pixel", "spacer", "1x1")


def _extract_images(html: str, base_url: str) -> list[str]:
    """URLs des images du CORPS de l'article (via trafilatura, qui scope au contenu).

    On récupère le markdown avec images, on en extrait les URLs, on les absolutise
    et on écarte les éléments décoratifs (logos, icônes…). Ordre = ordre de l'article.
    """
    import trafilatura

    try:
        md = trafilatura.extract(
            html, include_images=True, include_comments=False, output_format="markdown"
        ) or ""
    except Exception:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"!\[[^\]]*\]\(([^)\s]+)", md):
        u = urljoin(base_url, raw.strip())
        if not u.startswith(("http://", "https://")):
            continue
        low = u.lower()
        if any(b in low for b in _IMG_BLOCKLIST):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _download_html(url: str) -> str | None:
    """Télécharge le HTML via `requests`.

    Le downloader interne de trafilatura n'accepte que les proxys SOCKS et fige
    le CA `certifi` ; il échoue donc derrière un proxy HTTP d'entreprise à TLS
    intercepté. `requests` honore HTTPS_PROXY et REQUESTS_CA_BUNDLE -> on récupère
    le HTML ici, puis trafilatura fait l'extraction comme prévu.
    """
    import requests

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; shortmaker/1.0)"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _from_text(raw: str, url: str | None) -> Article:
    raw = raw.strip()
    if not raw:
        raise RuntimeError("Le texte fourni est vide.")
    # Première ligne non vide = titre par défaut.
    first_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "Mon article")
    title = first_line[:120]
    return Article(title=title, text=raw, url=url)
