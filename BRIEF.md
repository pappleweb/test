# Brief technique — shortmaker (Article → YouTube Short)

> Document de passation destiné à une IA/équipe qui intégrera l'outil dans un SaaS.
> Décrit l'architecture, chaque module, les entrées/sorties, les clés, les
> dépendances réseau, les points d'extension et les adaptations nécessaires pour
> passer du **prototype** à une **plateforme multi-utilisateurs**.

---

## 1. Ce que fait l'outil

Entrée : une **URL d'article** ou du **texte brut**.
Sortie (dans `out/<slug>/`) :
- `short.mp4` — vidéo verticale **1080×1920**, prête pour YouTube Shorts / Reels / TikTok ;
- `youtube.txt` — titre + description + hashtags à copier-coller.

Caractéristiques : voix off française, visuels calés sur la narration (image fixe
animée OU clip vidéo), sous-titres incrustés **au mot**, appel à l'action (CTA) vers
le site, transitions optionnelles. Conçu pour coûter le moins cher possible (chaque
étape a un repli gratuit).

---

## 2. Pipeline (vue d'ensemble)

```
source (URL/texte)
   │  extract.py        -> texte propre + titre
   ▼
scénario               script.py     -> ShortScript { scenes[], youtube_*, hashtags }
   │                                    (Claude Haiku si clé, sinon résumé extractif gratuit)
   ▼
voix off par scène     tts.py        -> VoiceClip { mp3, durée, timings mot-à-mot }
   │                                    (ElevenLabs si clé -> Edge-TTS -> espeak hors-ligne)
   ▼
visuel par scène       images.py     -> 1 image (FLUX / Gemini / Pexels-Pixabay / dégradé)
                       videos.py     -> OU 1 clip vidéo (Pexels Videos) si VISUAL_MODE=video
   ▼
sous-titres            captions.py   -> fichier .ass calé au mot (depuis les timings)
   ▼
montage final          video.py      -> ffmpeg : clips + (fondus) + audio + sous-titres + CTA
   ▼
out/<slug>/short.mp4 + youtube.txt
```

Orchestration : `make_short.py` (CLI). Interface web : `web.py` (Flask) qui appelle
le CLI en sous-processus.

---

## 3. Modules (`shortmaker/`)

### config.py
`SETTINGS` (dataclass, lue depuis l'environnement / `.env`) centralise tous les
réglages. Champs clés :
- Format : `WIDTH=1080`, `HEIGHT=1920`, `FPS=30` (constantes module).
- `anthropic_api_key`, `anthropic_model` (défaut `claude-haiku-4-5-20251001`).
- `pexels_api_key`, `pixabay_api_key`.
- `visual_mode` : `"image"` (défaut) | `"video"`.
- `image_provider` : `"stock"` (défaut) | `"flux"` | `"openrouter"`.
- `fal_api_key`, `flux_endpoint` (défaut `https://fal.run/fal-ai/flux/schnell`).
- `openrouter_api_key`, `openrouter_image_model` (défaut `google/gemini-3.1-flash-image`).
- `image_style` : suffixe de prompt commun à toutes les scènes (cohérence visuelle).
- `tts_voice` (Edge, défaut `fr-FR-DeniseNeural`), `elevenlabs_api_key`,
  `elevenlabs_voice_id`, `elevenlabs_model` (défaut `eleven_multilingual_v2`).
- `site_url`, `target_seconds` (défaut 45 ; un Short doit faire ≤ 60 s).
- Polices : `CAPTION_FONT` (libass), `FONT_FILE` (chemin .ttf pour le bandeau ffmpeg).

### extract.py
`load_source(source) -> Article{title, text, url}`.
- URL -> `_download_html()` via **`requests`** (et non le downloader interne de
  trafilatura), puis `trafilatura.extract()`. **Raison** : trafilatura ne gère que
  les proxys SOCKS et fige le CA certifi ; `requests` honore `HTTPS_PROXY` /
  `REQUESTS_CA_BUNDLE`. À conserver derrière tout proxy d'entreprise.
- Fichier / texte brut -> `_from_text()` (1re ligne = titre par défaut).

### script.py
`build_script(title, text, site_url, use_llm) -> ShortScript`.
- `Scene { narration (FR), image_query (mots-clés EN), is_cta }`.
- `ShortScript { youtube_title, youtube_description, hashtags[], scenes[] }`.
- Avec `ANTHROPIC_API_KEY` : `_llm_script()` (Claude Haiku) produit narration +
  `image_query` + métadonnées en un JSON.
- Sans clé : `_extractive_script()` (gratuit) prend les phrases saillantes. Les
  `image_query` sont fabriqués par `_keywords(sentence, anchor)` :
  - `_topic(title)` extrait 1-2 mots-clés EN du titre = **ancrage du sujet** ;
  - chaque scène = ancrage + 1-2 mots traduits via `_FR_EN` (mini-dico FR→EN) ;
  - mots inconnus écartés (pas de pollution FR). But : requêtes EN, jamais hors-sujet.

### tts.py
`synthesize(text, voice, mp3_path, engine, allow_fallback) -> VoiceClip{mp3_path, duration, words[WordTiming{text,start,end}]}`.
- `engine="eleven"` : ElevenLabs endpoint **with-timestamps** -> timings au caractère
  convertis en mots (`_words_from_char_alignment`). Voix par nom via `ELEVEN_VOICES`
  (charlotte, alice, matilda, lily, sarah) ou ID brut.
- `engine="edge"` : Edge-TTS gratuit, `boundary="WordBoundary"` = timing mot exact.
- `engine="espeak"` : hors-ligne, timings approximés proportionnellement.
- Repli en cascade si une étape échoue. `_trust_extra_ca()` injecte le CA proxy
  dans Edge-TTS (sinon CERTIFICATE_VERIFY_FAILED).
- **Note offre gratuite ElevenLabs** : les voix de la *Voice Library* (ex. Charlotte)
  renvoient 402 ; seules les voix *premade* du compte (alice, sarah, lily, matilda…)
  marchent en free tier.

### images.py
`fetch_image(query, dst_path, seed) -> dst_path`. Ordre d'essai :
1. **FLUX** (`image_provider=flux` + `FAL_KEY`) : `_flux()` POST fal.run, renvoie URL.
2. **OpenRouter/Gemini** (`image_provider=openrouter` + `OPENROUTER_API_KEY`) :
   `_openrouter()` chat-completions, image en **data-URL base64** dans `message.images`.
3. **Pexels** puis **Pixabay** (photos portrait).
4. **Dégradé** local (Pillow) — toujours disponible, hors-ligne.
- `_build_prompt(query)` = `query` + `SETTINGS.image_style` (cohérence inter-scènes).
- Tout échec d'un fournisseur passe au suivant : une image sort toujours.

### videos.py (mode `VISUAL_MODE=video`)
`fetch_clip(query, dst_path, seed) -> dst_path | None`.
- `_pexels_video()` cherche un clip portrait mp4 via l'API Pexels Videos, choisit le
  fichier le plus proche de 1080×1920 (évite l'UHD 4K). Téléchargement depuis
  `videos.pexels.com` (hôte distinct de `api.pexels.com`).
- Renvoie `None` si rien -> l'appelant (make_short) retombe sur une image fixe.

### captions.py
`build_ass(scenes[SceneCues], out_path)` génère un `.ass` (libass).
- `SceneCues { start_abs, words[WordTiming], is_cta }`.
- Fenêtres de ≤3 mots / ≤18 caractères ; le mot prononcé est surligné (couleur accent
  + léger zoom) -> rendu « karaoké » typique des Shorts. Styles `Caption` et `CTA`.

### video.py
`assemble(scene_images, durations, mp3s, ass_path, site_url, cta_start, cta_end, out_path, motion=True, xfade=0.0) -> out_path`.
- `_scene_clip()` dispatch par extension : image (Ken Burns `zoompan`) ou vidéo
  (`_scene_clip_video` : boucle si trop court via `-stream_loop -1`, coupe via `-t`,
  scale+crop 1080×1920, audio retiré).
- **Transitions (optionnelles, `xfade>0`)** : `_xfade_chain()`. Astuce de synchro :
  chaque clip est rendu `durée + xfade`, et l'`offset` du fondu est posé sur la
  frontière de narration -> l'audio et les sous-titres restent calés ; la queue de
  `xfade` en trop est coupée par `-shortest` au muxage.
- **Bandeau CTA** : `_display_url(site_url)` n'affiche que le **domaine** (sans
  schéma/www/chemin) -> lisible, jamais débordant. drawtext blanc contouré dans une
  boîte sombre, affiché sur la fenêtre `[cta_start, cta_end]`.

---

## 4. CLI — make_short.py

```
python make_short.py <source> [--out DIR] [--site URL] [--voice EDGE_VOICE]
   [--tts auto|eleven|edge|espeak] [--no-llm] [--no-motion]
   [--transition] [--xfade SECONDS]
```
- `source` : URL, chemin de fichier, `-` (stdin), ou texte brut.
- `--tts auto` -> `eleven` si `ELEVENLABS_API_KEY`, sinon `edge`.
- Voix ElevenLabs : via env `ELEVENLABS_VOICE_ID` (nom ou ID).
- `--transition` (ou `--xfade 0.4`) active les fondus (coupes franches par défaut).
- Étapes loggées sur stdout (`•  …`) -> consommées telles quelles par l'UI web.

---

## 5. Interface web — web.py (Flask)

- `GET /` : page unique (form + JS, HTML inliné dans `PAGE`).
- `POST /api/generate` : crée un job, lance un **thread** qui exécute `make_short.py`
  en **sous-processus** (env = choix de l'utilisateur), renvoie `{job_id}`.
- `GET /api/status/<id>` : `{status: queued|running|done|error, log[], error}`.
- `GET /api/video/<id>` / `GET /api/youtube/<id>` : sert les fichiers produits.
- État des jobs en **mémoire** (`JOBS` dict) — OK proto, à remplacer pour le SaaS.
- Champs du form : source (URL/texte), site, voix, visuel (image/vidéo), source images
  (stock/openrouter), transitions (case à cocher).
- Production : `gunicorn -w 1 --threads 8 web:app` (cf. `Dockerfile`). 1 worker car
  l'état est en mémoire.

---

## 6. Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `ELEVENLABS_API_KEY` | voix premium | — (sinon Edge/espeak) |
| `ELEVENLABS_VOICE_ID` | nom (alice…) ou ID | `charlotte`* |
| `ELEVENLABS_MODEL` | modèle TTS | `eleven_multilingual_v2` |
| `PEXELS_API_KEY` | images + clips vidéo | — |
| `PIXABAY_API_KEY` | images (secours) | — |
| `VISUAL_MODE` | `image` / `video` | `image` |
| `IMAGE_PROVIDER` | `stock` / `flux` / `openrouter` | `stock` |
| `FAL_KEY` | FLUX (fal.ai) | — |
| `FLUX_ENDPOINT` | modèle FLUX | `…/fal-ai/flux/schnell` |
| `OPENROUTER_API_KEY` | images Gemini via OpenRouter | — |
| `OPENROUTER_IMAGE_MODEL` | modèle image | `google/gemini-3.1-flash-image` |
| `IMAGE_STYLE` | style commun des prompts | (cf. config.py) |
| `ANTHROPIC_API_KEY` | scénario Claude Haiku | — (sinon extractif) |
| `TTS_VOICE` | voix Edge | `fr-FR-DeniseNeural` |
| `SITE_URL` | CTA par défaut | — |
| `TARGET_SECONDS` | durée cible narration | `45` |
| `XFADE_SECONDS` | (avancé) durée fondu | `0` |
| `CAPTION_FONT`, `FONT_FILE` | polices sous-titres/bandeau | Liberation Sans |

\* `charlotte` (ID Voice Library) ne marche pas en free tier ElevenLabs ; mettre
`alice`/`sarah`/`lily`/`matilda` pour le gratuit.

---

## 7. Fournisseurs externes & réseau

Tout passe par `requests` (proxy/CA OK). Hôtes contactés :
- `api.elevenlabs.io` (voix), Edge-TTS (Microsoft, via edge-tts).
- `api.pexels.com` (recherche) + `videos.pexels.com` (téléchargement clips) + `pixabay.com`.
- `fal.run` / `fal.media` (FLUX, optionnel), `openrouter.ai` (Gemini images, optionnel).
- `api.anthropic.com` (scénario, optionnel).
- L'hôte de l'article (extraction).

**Chaque dépendance a un repli** ; aucune clé n'est obligatoire (sortie dégradée mais
fonctionnelle). En environnement à allowlist, autoriser les hôtes ci-dessus utilisés.

---

## 8. Points d'extension

- **Nouveau fournisseur d'images** : ajouter une fonction `_xxx()` dans `images.py` et
  un cas dans `fetch_image()` (gardé par sa clé), garder le repli.
- **Nouveau moteur TTS** : ajouter un `engine` dans `tts.py:synthesize()`.
- **Prompts par scène** : faire produire à `script.py` un vrai prompt descriptif par
  scène (le plus gros levier qualité pour images IA et recherche vidéo).
- **Transitions** : `xfade` paramétrable ; on peut ajouter d'autres `transition=` ffmpeg.
- **Format** : changer `WIDTH/HEIGHT/FPS` dans config pour d'autres ratios.

---

## 9. Limites du prototype (à traiter pour le SaaS)

- Jobs **en mémoire**, **1 worker**, génération **synchrone** côté worker.
- Pas d'auth, pas de quotas, pas de multitenancy.
- Sortie écrite sur le **disque local** (`out/`), éphémère en conteneur.
- Clés API globales (process), pas par utilisateur.
- Pas d'upload YouTube (récupération manuelle du `short.mp4`).

---

## 10. Adaptation SaaS (recommandations)

1. **File de jobs** : remplacer le thread + dict par **Redis + Celery/RQ** (ou un
   worker queue managé). `make_short.py` devient une task. Découpler API ↔ workers.
2. **Refactor en fonction** : extraire le cœur de `make_short.main()` en
   `generate_short(params) -> paths` réutilisable directement (sans sous-processus) ;
   passer les réglages en **paramètres** plutôt que via env global `SETTINGS`
   (aujourd'hui `SETTINGS` est lu à l'import — pour du multi-requête concurrent,
   injecter une config par job au lieu du singleton).
3. **Stockage** : écrire `short.mp4`/`youtube.txt` sur **S3** (ou équivalent), servir
   via URL signée. Nettoyage TTL.
4. **Clés** : par tenant, chiffrées (secrets manager) ; ne jamais les exposer côté client.
5. **Quotas/coûts** : compteur par utilisateur (TTS = caractères ElevenLabs, images IA
   = $/image). Choix de fournisseur par plan tarifaire.
6. **Scaling** : workers horizontaux (ffmpeg = CPU-bound) ; séparer file vs web.
7. **Sécurité** : valider/sanitiser l'URL d'entrée (SSRF — bloquer IP internes),
   limiter la taille du texte, timeouts, sandbox ffmpeg.
8. **Observabilité** : logs structurés par job, métriques de durée/coût, états en base.
9. **YouTube** (plus tard) : OAuth + YouTube Data API pour publier automatiquement.

---

## 11. Dépendances système & exécution

- **Système** : `ffmpeg`, `espeak-ng`, polices (`fonts-liberation`).
- **Python** : voir `requirements.txt` (edge-tts, trafilatura, requests, Pillow,
  python-dotenv, anthropic, Flask, gunicorn).
- **Conteneur** : `Dockerfile` fourni (image prête, gunicorn). `docker build -t shortmaker . && docker run -p 8080:8080 -e PEXELS_API_KEY=… -e ELEVENLABS_API_KEY=… shortmaker`.
- **Arborescence** :
  ```
  make_short.py     # CLI (orchestration)
  web.py            # interface web Flask
  Dockerfile        # image de prod (gunicorn)
  shortmaker/
    config.py extract.py script.py tts.py
    images.py videos.py captions.py video.py
  ```
```
