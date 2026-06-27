# shortmaker — Article → YouTube Short (automatique)

Donne une **URL d'article** (ou un texte), récupère un **Short vertical prêt à publier** :
voix off, images calées sur les paroles, sous-titres au mot, et un appel à l'action
qui invite à lire l'article complet sur ton site. **Zéro montage manuel.**

Pensé pour coûter **le moins cher possible** : tout est gratuit sauf, en option, la
génération du scénario par Claude Haiku (~1 centime par short).

```
URL / texte ─► extraction ─► scénario ─► voix off ─► images ─► sous-titres ─► short.mp4
              trafilatura    Claude/      Edge-TTS    Pexels/    ASS calé      ffmpeg
                             gratuit      (gratuit)   Pixabay    au mot
```

## Ce que ça produit

Dans `out/<titre>/` :

- **`short.mp4`** — vidéo verticale 1080×1920, prête pour YouTube Shorts.
- **`youtube.txt`** — titre, description et hashtags à copier-coller.

Caractéristiques :

- **Voix off française** (Edge-TTS, gratuit).
- **Images calées sur les paroles** : chaque scène dure exactement le temps de sa
  narration (timing fourni mot-à-mot par la synthèse vocale, pas d'alignement approximatif).
- **Sous-titres dynamiques** incrustés, façon Short (gros texte, 3 mots à la fois).
- **Appel à l'action final** : bannière avec l'URL de ton site + invitation à lire l'article.
- Léger zoom (effet Ken Burns) sur chaque image.

## Coût

| Élément        | Solution            | Coût |
|----------------|---------------------|------|
| Extraction     | trafilatura         | 0 €  |
| Voix off       | Edge-TTS (Microsoft)| 0 €  |
| Voix off (option premium) | ElevenLabs | gratuit ~10k car./mois |
| Images         | Pexels / Pixabay    | 0 €  |
| Images (option qualité) | FLUX schnell (fal.ai) | ~0,02 € / short |
| Images (option qualité) | Gemini image (OpenRouter) | ~0,5 € / short |
| Montage        | ffmpeg              | 0 €  |
| Scénario       | Claude Haiku (option)| ~0,01 € / short |

Sans clé Anthropic, le scénario bascule sur un **résumé extractif 100 % gratuit**.
Sans clé d'images, un **fond dégradé** est généré localement (les sous-titres restent lisibles).

### Mode vidéo (clips au lieu d'images)

Par défaut chaque scène est une photo animée (Ken Burns). Pour enchaîner de **courts
clips vidéo** (gratuits, Pexels Videos) avec la voix off par-dessus :

```bash
export VISUAL_MODE=video      # nécessite PEXELS_API_KEY
python make_short.py "https://mon-site.fr/article" --site https://mon-site.fr
```

- Un clip vertical par scène, **bouclé** s'il est trop court, **coupé** à la durée
  exacte de la voix off de la scène, recadré en 1080×1920.
- Repli automatique : si une scène n'a pas de clip, elle bascule en image fixe.
- L'audio des clips est ignoré (on garde la voix off + sous-titres + CTA).

### Images IA (option qualité)

Par défaut les images viennent des banques gratuites (`IMAGE_PROVIDER=stock`). Pour
des visuels générés sur mesure, deux providers IA sont dispos.

**FLUX** (Black Forest Labs, via fal.ai) — le moins cher :

```bash
export IMAGE_PROVIDER=flux
export FAL_KEY=...            # https://fal.ai/dashboard/keys
python make_short.py "https://mon-site.fr/article" --site https://mon-site.fr
```

- **FLUX.1 schnell** (défaut) : ~0,003 $/image → **~2 cts/short**.
- Modèle supérieur : `export FLUX_ENDPOINT=https://fal.run/fal-ai/flux/dev`.

**Gemini** (via OpenRouter) — cadrage 9:16 natif :

```bash
export IMAGE_PROVIDER=openrouter
export OPENROUTER_API_KEY=...   # https://openrouter.ai/keys
python make_short.py "https://mon-site.fr/article" --site https://mon-site.fr
```

- **gemini-3.1-flash-image** (défaut) : 9:16 vertical natif, ~0,07 $/image (~0,5 $/short).
- Moins cher mais carré : `export OPENROUTER_IMAGE_MODEL=google/gemini-2.5-flash-image`.

Communs aux deux :

- Style partagé entre les scènes (cohérence) réglable via `IMAGE_STYLE`.
- Repli automatique : si l'IA échoue (quota, refus, réseau), on retombe sur
  Pexels/Pixabay puis sur le dégradé local — un short sort toujours.

## Installation

Prérequis : **Python 3.10+** et **ffmpeg** (`sudo apt install ffmpeg` ou `brew install ffmpeg`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # puis remplis les clés que tu as (toutes optionnelles)
```

### Clés (gratuites) recommandées

- **Pexels** — https://www.pexels.com/api/ → `PEXELS_API_KEY`
- **Pixabay** (secours) — https://pixabay.com/api/docs/ → `PIXABAY_API_KEY`
- **Anthropic** (meilleur scénario) — https://console.anthropic.com/ → `ANTHROPIC_API_KEY`
- **ElevenLabs** (voix premium, optionnel) — https://elevenlabs.io/ → `ELEVENLABS_API_KEY`
  (offre gratuite ~10k caractères/mois ; voix féminine FR « Charlotte » par défaut).
  Si la clé est présente, elle est utilisée automatiquement (`--tts auto`).

## Utilisation

```bash
# Depuis l'URL d'un de tes articles
python make_short.py "https://mon-site.fr/mon-article" --site https://mon-site.fr

# Depuis un fichier texte
python make_short.py article.txt --site https://mon-site.fr

# Depuis du texte sur l'entrée standard
echo "Mon texte d'article..." | python make_short.py - --site https://mon-site.fr
```

Options utiles :

| Option        | Effet                                                        |
|---------------|--------------------------------------------------------------|
| `--site URL`  | URL affichée dans l'appel à l'action (défaut: `SITE_URL`).   |
| `--voice NOM` | Voix Edge-TTS (`fr-FR-DeniseNeural`, `fr-FR-HenriNeural`, …). |
| `--tts MOTEUR`| `auto` (défaut), `eleven` (ElevenLabs), `edge`, `espeak` (hors-ligne). |
| `--no-llm`    | Force le scénario gratuit (sans Claude).                     |
| `--no-motion` | Désactive le zoom des images.                                |
| `--out DOSSIER`| Dossier de sortie.                                          |

Lister les voix françaises disponibles :

```bash
edge-tts --list-voices | grep fr-
```

## Interface web

Pour générer un Short sans ligne de commande : colle une URL **ou le texte** de
ton article, choisis la voix et le type de visuel, récupère la vidéo + le texte
YouTube directement dans le navigateur.

```bash
python web.py            # puis ouvre http://localhost:5000
```

L'UI réutilise le moteur `make_short.py` (lancé en sous-processus) et affiche la
progression en direct. Réglages exposés : voix (ElevenLabs ou Edge gratuit),
visuel (clips vidéo ou images animées), source des images (banque gratuite ou IA).

## Comment c'est organisé

```
make_short.py            # orchestrateur en ligne de commande
web.py                   # interface web (Flask) : article -> vidéo dans le navigateur
shortmaker/
  config.py              # réglages (format 1080x1920, voix, modèle…)
  extract.py             # URL/fichier/texte -> texte propre de l'article
  script.py              # article -> scénario (Claude Haiku ou résumé gratuit)
  tts.py                 # scénario -> voix off + timing mot-à-mot (Edge-TTS)
  images.py              # mots-clés -> image verticale (Pexels/Pixabay/dégradé)
  captions.py            # timings -> sous-titres ASS calés au mot
  videos.py              # mots-clés -> court clip vidéo vertical (Pexels, mode video)
  video.py               # assemblage final ffmpeg (clips, fondus, audio, sous-titres, CTA)
```

## Notes

- Les requêtes d'images sont en anglais (meilleurs résultats sur les banques).
- Un Short doit faire **≤ 60 s** : ajuste la durée cible via `TARGET_SECONDS` dans `.env`.
- Derrière un proxy qui intercepte le TLS, Edge-TTS lit le CA via `SSL_CERT_FILE`
  (déjà géré automatiquement) ; un proxy explicite peut être donné par `EDGE_TTS_PROXY`.
- Le téléversement sur YouTube n'est pas automatisé : récupère `short.mp4` et
  `youtube.txt`, puis publie (l'API YouTube Data impose un projet Google Cloud ;
  ça peut être ajouté ensuite si tu veux).
