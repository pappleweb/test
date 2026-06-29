"""Étape 6 — assemblage final avec ffmpeg, sans aucun montage manuel.

Pour chaque scène : une image fixe -> léger zoom (effet Ken Burns) sur la durée
de la voix off de la scène. On concatène les clips, on colle l'audio, on incruste
les sous-titres calés au mot, et on ajoute la bannière du site sur la scène finale.
"""
from __future__ import annotations

import os
import re
import subprocess

from .config import FONT_FILE, FPS, HEIGHT, WIDTH


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Échec ffmpeg :\n" + " ".join(cmd) + "\n\n" + proc.stderr[-2000:]
        )


_VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def _scene_clip(visual: str, duration: float, dst: str, motion: bool) -> None:
    """Fabrique un clip de scène de durée `duration` à partir d'une image OU d'une vidéo
    (détection par extension). Une vidéo trop courte est bouclée, trop longue rognée."""
    if visual.lower().endswith(_VIDEO_EXT):
        _scene_clip_video(visual, duration, dst)
    else:
        _scene_clip_image(visual, duration, dst, motion)


def _scene_clip_video(src: str, duration: float, dst: str) -> None:
    # -stream_loop -1 : boucle la source si elle est plus courte que la scène.
    # -t : coupe à la durée exacte de la voix off. -an : on jette l'audio du stock.
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", src,
        "-t", f"{duration:.3f}", "-an", "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        dst,
    ])


def _scene_clip_image(image: str, duration: float, dst: str, motion: bool) -> None:
    frames = max(2, round(duration * FPS))
    base = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT}"
    )
    if motion:
        vf = (
            f"{base},zoompan=z='min(zoom+0.0010,1.18)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps={FPS}:s={WIDTH}x{HEIGHT},"
            f"setsar=1,format=yuv420p"
        )
    else:
        vf = f"{base},setsar=1,format=yuv420p"

    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", image,
        "-t", f"{duration:.3f}", "-r", str(FPS),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        dst,
    ])


def _xfade_chain(clips: list[str], durations: list[float], t: float, dst: str) -> None:
    """Enchaîne les clips avec un fondu (xfade) de `t` secondes entre chaque scène.

    Chaque clip a été rendu d'une durée `scène + t` : le décalage (offset) du fondu
    est placé sur la frontière de narration (somme des durées précédentes), si bien
    que chaque scène « arrive » à son instant exact -> audio et sous-titres synchro.
    La vidéo finale dure `somme(durées) + t` ; le `-shortest` du muxage recoupe la
    queue de `t` sur la longueur de l'audio.
    """
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", c]
    steps, prev, off = [], "[0:v]", 0.0
    for k in range(1, len(clips)):
        off += durations[k - 1]
        out = f"[v{k}]"
        steps.append(
            f"{prev}[{k}:v]xfade=transition=fade:duration={t:.3f}:offset={off:.3f}{out}"
        )
        prev = out
    cmd += [
        "-filter_complex", ";".join(steps), "-map", prev,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst,
    ]
    _run(cmd)


def _concat_video(clips: list[str], dst: str, workdir: str) -> None:
    listfile = os.path.join(workdir, "clips.txt")
    with open(listfile, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", dst])


def _concat_audio(mp3s: list[str], dst: str) -> None:
    cmd = ["ffmpeg", "-y"]
    for m in mp3s:
        cmd += ["-i", m]
    n = len(mp3s)
    streams = "".join(f"[{i}:a]" for i in range(n))
    cmd += [
        "-filter_complex", f"{streams}concat=n={n}:v=0:a=1[a]",
        "-map", "[a]", "-c:a", "aac", "-b:a", "192k", dst,
    ]
    _run(cmd)


def _display_url(url: str) -> str:
    """URL d'affichage courte pour le CTA : on garde le domaine seul (sans
    schéma, sans www, sans chemin) -> toujours lisible et contenu à l'écran."""
    s = re.sub(r"^https?://", "", url.strip())
    s = re.sub(r"^www\.", "", s)
    return s.split("/")[0] or url.strip()


def _drawtext_escape(text: str) -> str:
    for ch, esc in [("\\", r"\\"), (":", r"\:"), ("'", r"\'"), ("%", r"\%")]:
        text = text.replace(ch, esc)
    return text


def assemble(
    scene_images: list[str],
    durations: list[float],
    mp3s: list[str],
    ass_path: str,
    site_url: str,
    cta_start: float,
    cta_end: float,
    out_path: str,
    motion: bool = True,
    xfade: float = 0.0,
) -> str:
    workdir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_work")
    os.makedirs(workdir, exist_ok=True)

    # 1) un clip (muet) par scène. Pour le fondu enchaîné (optionnel), chaque clip est
    #    rendu `dur + xfade` : la queue sert à la transition sans rogner la narration.
    xfade = xfade if (xfade > 0 and len(scene_images) > 1) else 0.0
    clips = []
    for i, (img, dur) in enumerate(zip(scene_images, durations)):
        clip = os.path.join(workdir, f"scene_{i:02d}.mp4")
        _scene_clip(img, dur + xfade, clip, motion)
        clips.append(clip)

    # 2) vidéo (fondus enchaînés ou coupes franches) + 3) audio concaténé
    video_silent = os.path.join(workdir, "video_silent.mp4")
    audio = os.path.join(workdir, "audio.m4a")
    if xfade > 0:
        _xfade_chain(clips, durations, xfade, video_silent)
    else:
        _concat_video(clips, video_silent, workdir)
    _concat_audio(mp3s, audio)

    # 4) incrustation sous-titres + bandeau site sur la scène finale, puis muxage audio.
    #    On n'affiche que le DOMAINE (pas l'URL d'article complète) -> lisible, jamais
    #    débordant. Texte blanc + contour, dans un bandeau sombre semi-opaque, centré.
    banner = _drawtext_escape(f"→ {_display_url(site_url)}")
    drawtext = (
        f"drawtext=fontfile='{FONT_FILE}':text='{banner}':"
        f"fontcolor=white:fontsize=58:borderw=3:bordercolor=black:"
        f"box=1:boxcolor=black@0.6:boxborderw=32:"
        f"x=(w-text_w)/2:y=h*0.13:enable='between(t,{cta_start:.2f},{cta_end:.2f})'"
    )
    vf = f"subtitles='{ass_path}',{drawtext}"

    _run([
        "ffmpeg", "-y", "-i", video_silent, "-i", audio,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        out_path,
    ])
    return out_path
