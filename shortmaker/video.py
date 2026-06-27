"""Étape 6 — assemblage final avec ffmpeg, sans aucun montage manuel.

Pour chaque scène : une image fixe -> léger zoom (effet Ken Burns) sur la durée
de la voix off de la scène. On concatène les clips, on colle l'audio, on incruste
les sous-titres calés au mot, et on ajoute la bannière du site sur la scène finale.
"""
from __future__ import annotations

import os
import subprocess

from .config import FONT_FILE, FPS, HEIGHT, WIDTH


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Échec ffmpeg :\n" + " ".join(cmd) + "\n\n" + proc.stderr[-2000:]
        )


def _scene_clip(image: str, duration: float, dst: str, motion: bool) -> None:
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
) -> str:
    workdir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_work")
    os.makedirs(workdir, exist_ok=True)

    # 1) un clip vidéo (muet) par scène
    clips = []
    for i, (img, dur) in enumerate(zip(scene_images, durations)):
        clip = os.path.join(workdir, f"scene_{i:02d}.mp4")
        _scene_clip(img, dur, clip, motion)
        clips.append(clip)

    # 2) vidéo concaténée + 3) audio concaténé
    video_silent = os.path.join(workdir, "video_silent.mp4")
    audio = os.path.join(workdir, "audio.m4a")
    _concat_video(clips, video_silent, workdir)
    _concat_audio(mp3s, audio)

    # 4) incrustation sous-titres + bannière site sur la scène finale, puis muxage audio
    banner = _drawtext_escape(f"→ {site_url}")
    drawtext = (
        f"drawtext=fontfile='{FONT_FILE}':text='{banner}':"
        f"fontcolor=white:fontsize=52:box=1:boxcolor=black@0.6:boxborderw=24:"
        f"x=(w-text_w)/2:y=h*0.16:enable='between(t,{cta_start:.2f},{cta_end:.2f})'"
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
