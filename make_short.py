#!/usr/bin/env python3
"""Génère un YouTube Short à partir d'une URL d'article ou d'un texte.

Exemples :
    python make_short.py "https://mon-site.fr/mon-article"
    python make_short.py article.txt --site https://mon-site.fr
    echo "Mon texte..." | python make_short.py - --voice fr-FR-HenriNeural

Sortie (dossier --out, par défaut ./out/<slug>/) :
    short.mp4        -> la vidéo verticale prête à publier
    youtube.txt      -> titre + description + hashtags à copier-coller
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from shortmaker import captions as cap
from shortmaker import images, script, tts, video
from shortmaker.config import SETTINGS
from shortmaker.extract import load_source


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s[:50] or "short")


def main() -> int:
    p = argparse.ArgumentParser(description="Article/texte -> YouTube Short (voix off + images calées).")
    p.add_argument("source", help="URL d'article, chemin de fichier, '-' pour stdin, ou texte brut.")
    p.add_argument("--out", default=None, help="Dossier de sortie (défaut: ./out/<slug>/).")
    p.add_argument("--site", default=SETTINGS.site_url, help="URL de ton site (appel à l'action).")
    p.add_argument("--voice", default=SETTINGS.tts_voice, help="Voix Edge-TTS (ex: fr-FR-HenriNeural).")
    p.add_argument("--tts", choices=["auto", "eleven", "edge", "espeak"], default="auto",
                   help="Moteur voix : auto (eleven si clé, sinon edge), eleven, edge, espeak.")
    p.add_argument("--no-llm", action="store_true", help="Forcer le résumé gratuit (sans Claude).")
    p.add_argument("--no-motion", action="store_true", help="Désactiver le léger zoom des images.")
    args = p.parse_args()

    source = sys.stdin.read() if args.source == "-" else args.source

    # 1) Texte de l'article
    print("• Extraction de l'article…")
    article = load_source(source)
    site = article.url or args.site

    # 2) Scénario (Claude Haiku ou repli gratuit)
    print("• Écriture du scénario…")
    sc = script.build_script(article.title, article.text, site, use_llm=not args.no_llm)
    print(f"  {len(sc.scenes)} scènes.")

    # Dossiers
    out_dir = args.out or os.path.join("out", _slug(sc.youtube_title or article.title))
    assets = os.path.join(out_dir, "assets")
    os.makedirs(assets, exist_ok=True)

    # 3) Voix off scène par scène (durée + timing mot-à-mot)
    engine = args.tts
    if engine == "auto":
        engine = "eleven" if SETTINGS.elevenlabs_api_key else "edge"
    print(f"• Voix off ({engine})…")
    mp3s, durations, scene_cues = [], [], []
    t_cursor = 0.0
    cta_start = cta_end = 0.0
    for i, scene in enumerate(sc.scenes):
        mp3 = os.path.join(assets, f"voice_{i:02d}.mp3")
        clip = tts.synthesize(scene.narration, args.voice, mp3, engine=engine)
        mp3s.append(mp3)
        durations.append(clip.duration)
        scene_cues.append(cap.SceneCues(start_abs=t_cursor, words=clip.words, is_cta=scene.is_cta))
        if scene.is_cta:
            cta_start, cta_end = t_cursor, t_cursor + clip.duration
        t_cursor += clip.duration
    print(f"  Durée totale ≈ {t_cursor:.1f}s.")

    # 4) Un visuel par scène : image fixe (défaut) ou court clip vidéo (VISUAL_MODE=video)
    scene_images = []
    if SETTINGS.visual_mode == "video":
        from shortmaker import videos
        print("• Clips vidéo (Pexels, gratuit)…")
        for i, scene in enumerate(sc.scenes):
            clip = os.path.join(assets, f"clip_{i:02d}.mp4")
            if videos.fetch_clip(scene.image_query, clip, seed=i):
                scene_images.append(clip)
                print(f"  scène {i}: clip « {scene.image_query} »")
            else:
                # Pas de clip trouvé -> repli image fixe pour cette scène.
                img = os.path.join(assets, f"img_{i:02d}.jpg")
                images.fetch_image(scene.image_query, img, seed=i)
                scene_images.append(img)
                print(f"  scène {i}: (pas de clip) image « {scene.image_query} »")
    else:
        print("• Images (banque gratuite)…")
        for i, scene in enumerate(sc.scenes):
            img = os.path.join(assets, f"img_{i:02d}.jpg")
            images.fetch_image(scene.image_query, img, seed=i)
            scene_images.append(img)
            print(f"  scène {i}: « {scene.image_query} »")

    # 5) Sous-titres calés au mot
    ass_path = os.path.join(assets, "captions.ass")
    cap.build_ass(scene_cues, ass_path)

    # 6) Montage final
    print("• Assemblage vidéo (ffmpeg)…")
    out_mp4 = os.path.join(out_dir, "short.mp4")
    video.assemble(
        scene_images=scene_images,
        durations=durations,
        mp3s=mp3s,
        ass_path=ass_path,
        site_url=site,
        cta_start=cta_start,
        cta_end=cta_end,
        out_path=out_mp4,
        motion=not args.no_motion,
    )

    # 7) Métadonnées YouTube prêtes à coller
    yt = os.path.join(out_dir, "youtube.txt")
    desc = sc.youtube_description.strip()
    if site and site not in desc:
        desc += f"\n\n👉 Article complet : {site}"
    with open(yt, "w", encoding="utf-8") as f:
        f.write(f"TITRE :\n{sc.youtube_title}\n\nDESCRIPTION :\n{desc}\n\n"
                f"HASHTAGS :\n{' '.join(sc.hashtags)}\n")

    print(f"\n✅ Terminé !\n   Vidéo : {out_mp4}\n   Texte YouTube : {yt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
