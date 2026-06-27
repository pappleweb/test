"""Étape 2 — transformer l'article en scénario de Short (accroche -> scènes -> appel à l'action).

Avec une clé Anthropic : Claude Haiku écrit un script punchy + requêtes d'images.
Sans clé : repli 100 % gratuit par résumé extractif (les phrases les plus saillantes).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import SETTINGS


@dataclass
class Scene:
    narration: str        # texte lu par la voix off (français)
    image_query: str      # mots-clés (anglais) pour chercher l'image
    is_cta: bool = False  # scène d'appel à l'action finale


@dataclass
class ShortScript:
    youtube_title: str
    youtube_description: str
    hashtags: list[str]
    scenes: list[Scene] = field(default_factory=list)


_SYSTEM = """Tu es un monteur de YouTube Shorts viraux et concis.
À partir d'un article, tu écris le script d'une voix off en FRANÇAIS d'environ {sec} secondes
(soit ~{words} mots au total), découpé en 4 à 6 scènes courtes.

Règles impératives :
- La 1re scène est une ACCROCHE choc (une phrase) qui donne envie de rester.
- Chaque scène = 1 à 2 phrases parlées, naturelles, rythmées (pas de jargon).
- Pour chaque scène, donne aussi "image_query" : 2 à 4 mots-clés EN ANGLAIS, concrets et
  visuels, qui décrivent une image d'illustration trouvable en banque d'images.
- Ne lis JAMAIS d'URL à voix haute.
- Termine par une scène d'appel à l'action qui invite à lire l'article complet sur le site.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, de la forme :
{{
  "youtube_title": "titre accrocheur < 90 caractères",
  "youtube_description": "2-3 phrases + invitation à lire l'article",
  "hashtags": ["#tag1", "#tag2", "#shorts"],
  "scenes": [
    {{"narration": "...", "image_query": "english keywords"}},
    {{"narration": "...", "image_query": "english keywords"}}
  ],
  "cta": {{"narration": "phrase d'appel à l'action", "image_query": "english keywords"}}
}}"""


def build_script(title: str, text: str, site_url: str, use_llm: bool = True) -> ShortScript:
    target = SETTINGS.target_seconds
    if use_llm and SETTINGS.anthropic_api_key:
        try:
            return _llm_script(title, text, site_url, target)
        except Exception as e:  # repli silencieux si l'API échoue
            print(f"[script] LLM indisponible ({e}); repli sur le résumé gratuit.")
    return _extractive_script(title, text, site_url, target)


# --------------------------------------------------------------------------- LLM

def _llm_script(title: str, text: str, site_url: str, target: int) -> ShortScript:
    from anthropic import Anthropic

    words = int(target * 2.5)  # ~2.5 mots/seconde en français
    client = Anthropic(api_key=SETTINGS.anthropic_api_key)
    # On borne l'article pour limiter le coût (le début suffit largement).
    article = text[:6000]

    msg = client.messages.create(
        model=SETTINGS.anthropic_model,
        max_tokens=1500,
        system=_SYSTEM.format(sec=target, words=words),
        messages=[{
            "role": "user",
            "content": (
                f"Titre de l'article : {title}\n"
                f"Site (pour l'appel à l'action) : {site_url}\n\n"
                f"Article :\n{article}"
            ),
        }],
    )
    raw = "".join(block.text for block in msg.content if block.type == "text")
    data = _parse_json(raw)

    scenes = [
        Scene(narration=s["narration"].strip(), image_query=s["image_query"].strip())
        for s in data["scenes"]
        if s.get("narration", "").strip()
    ]
    cta = data.get("cta") or {}
    scenes.append(Scene(
        narration=cta.get("narration", "Lis l'article complet sur mon site, lien en description !").strip(),
        image_query=cta.get("image_query", "person reading phone website").strip(),
        is_cta=True,
    ))

    return ShortScript(
        youtube_title=data.get("youtube_title", title)[:100],
        youtube_description=data.get("youtube_description", "").strip(),
        hashtags=[h if h.startswith("#") else f"#{h}" for h in data.get("hashtags", [])][:8],
        scenes=scenes,
    )


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    return json.loads(raw)


# -------------------------------------------------------------- Repli gratuit

def _extractive_script(title: str, text: str, site_url: str, target: int) -> ShortScript:
    """Sans IA : on prend les premières phrases informatives comme narration."""
    sentences = _split_sentences(text)
    budget_words = int(target * 2.5)

    scenes: list[Scene] = []
    used = 0
    # Accroche = titre reformulé.
    hook = title.rstrip(".!?") + " ?"
    scenes.append(Scene(narration=hook, image_query=_keywords(title)))
    used += len(hook.split())

    for sent in sentences:
        if used >= budget_words or len(scenes) >= 6:
            break
        sent = sent.strip()
        if len(sent.split()) < 4:
            continue
        scenes.append(Scene(narration=sent, image_query=_keywords(sent)))
        used += len(sent.split())

    scenes.append(Scene(
        narration="Tu veux la suite ? L'article complet est sur mon site, lien en description.",
        image_query="person reading phone website",
        is_cta=True,
    ))

    return ShortScript(
        youtube_title=title[:100],
        youtube_description=(
            f"{title}\n\n👉 Article complet : {site_url}"
        ),
        hashtags=["#shorts", "#article"],
        scenes=scenes,
    )


_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "à", "en", "dans",
    "pour", "sur", "par", "avec", "que", "qui", "quoi", "est", "sont", "ce",
    "cette", "ces", "son", "sa", "ses", "au", "aux", "plus", "mais", "ou", "où",
    "the", "a", "an", "of", "to", "in", "and", "is", "are",
}


def _keywords(s: str) -> str:
    words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", s.lower())
    words = [w for w in words if w not in _STOPWORDS]
    return " ".join(words[:3]) if words else "abstract background"


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    return re.split(r"(?<=[.!?])\s+", text)
