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

    # Ancrage commun à toutes les scènes : le sujet de l'article (tiré du titre).
    # Évite qu'une scène au texte abstrait parte sur un visuel hors-sujet.
    anchor = _topic(title)

    scenes: list[Scene] = []
    used = 0
    # Accroche = titre reformulé.
    hook = title.rstrip(".!?") + " ?"
    scenes.append(Scene(narration=hook, image_query=_keywords(title, anchor)))
    used += len(hook.split())

    for sent in sentences:
        if used >= budget_words or len(scenes) >= 6:
            break
        sent = sent.strip()
        if len(sent.split()) < 4:
            continue
        scenes.append(Scene(narration=sent, image_query=_keywords(sent, anchor)))
        used += len(sent.split())

    scenes.append(Scene(
        narration="Tu veux la suite ? L'article complet est sur mon site, lien en description.",
        image_query=(f"{anchor} person phone" if anchor else "person reading phone website"),
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
    "vous", "nous", "tout", "tous", "vos", "votre", "leur", "leurs", "sans", "bien",
    "the", "a", "an", "of", "to", "in", "and", "is", "are", "your", "you",
}

# Mini-dictionnaire FR->EN du vocabulaire concret/visuel le plus courant.
# But : produire des requêtes EN (banques d'images/vidéos bien plus fournies).
# Mot inconnu -> on l'ignore plutôt que de polluer la requête avec du français.
_FR_EN = {
    "pizza": "pizza", "pizzas": "pizza", "pizzeria": "pizzeria",
    "anniversaire": "birthday", "fête": "party", "fete": "party", "fêtes": "party",
    "invités": "guests", "invité": "guests", "invites": "guests", "convives": "guests",
    "enfant": "children", "enfants": "children", "adulte": "adults", "adultes": "adults",
    "ami": "friends", "amis": "friends", "famille": "family", "couple": "couple",
    "personne": "person", "gens": "people", "groupe": "group", "monde": "people",
    "part": "slices", "parts": "slices", "tranche": "slices", "portion": "portions",
    "repas": "meal", "plat": "dish", "plats": "dishes", "cuisine": "cooking",
    "fromage": "cheese", "pâte": "dough", "pate": "dough", "four": "oven",
    "restaurant": "restaurant", "livraison": "delivery", "commande": "order",
    "commander": "ordering", "traiteur": "catering", "buffet": "buffet",
    "gâteau": "cake", "gateau": "cake", "boisson": "drinks", "apéritif": "appetizer",
    "table": "table", "maison": "home", "soirée": "evening party", "soiree": "evening party",
    "décoration": "decoration", "decoration": "decoration", "ballons": "balloons",
    "bougies": "candles", "ambiance": "atmosphere", "célébration": "celebration",
    "argent": "money", "budget": "budget", "prix": "price", "économie": "savings",
    "conseil": "tips", "conseils": "tips", "guide": "guide", "astuce": "tips",
    "succès": "success", "réussi": "success", "plaisir": "fun", "joie": "joy",
    "sourire": "smile", "réaction": "reaction", "réactions": "reaction",
    "manger": "eating", "déguster": "tasting", "partager": "sharing",
}


def _en_words(s: str) -> list[str]:
    """Mots-clés EN tirés de `s` : traduits via le dico, mots inconnus écartés."""
    out: list[str] = []
    for w in re.findall(r"[A-Za-zÀ-ÿ]{3,}", s.lower()):
        if w in _STOPWORDS:
            continue
        en = _FR_EN.get(w)
        if en and en not in out:
            out.append(en)
    return out


def _topic(title: str) -> str:
    """Ancrage : 1-2 mots-clés EN qui résument le sujet de l'article (depuis le titre)."""
    return " ".join(_en_words(title)[:2])


def _keywords(s: str, anchor: str = "") -> str:
    """Requête image/vidéo d'une scène : ancrage du sujet + 1-2 mots-clés EN propres à la scène."""
    anchor_words = anchor.split()
    scene = [w for w in _en_words(s) if w not in anchor_words][:2]
    parts = list(dict.fromkeys(anchor_words + scene))[:4]
    return " ".join(parts) if parts else "abstract background"


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    return re.split(r"(?<=[.!?])\s+", text)
