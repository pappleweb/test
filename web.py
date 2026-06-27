#!/usr/bin/env python3
"""Interface web de shortmaker : coller une URL ou le texte d'un article,
choisir la voix et le type de visuel, et récupérer la vidéo + le texte YouTube.

Le moteur reste `make_short.py` (lancé en sous-processus) : l'UI ne réécrit rien,
elle pilote le pipeline et affiche sa progression en direct.

    python web.py            # http://localhost:5000
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid

from flask import Flask, abort, jsonify, request, send_file

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_BASE = os.path.join(APP_ROOT, "out", "web")
os.makedirs(OUT_BASE, exist_ok=True)

# Voix ElevenLabs disponibles côté offre gratuite (cf. shortmaker/tts.py).
VOICES = ["alice", "sarah", "lily", "matilda"]

app = Flask(__name__)
JOBS: dict[str, dict] = {}  # job_id -> {status, log, out_dir, error}


def _looks_url(s: str) -> bool:
    return bool(re.match(r"https?://", s.strip()))


def _run_job(job_id: str, source: str, site: str, voice: str,
             tts: str, visual: str, images: str) -> None:
    job = JOBS[job_id]
    out_dir = os.path.join(OUT_BASE, job_id)
    os.makedirs(out_dir, exist_ok=True)
    job["out_dir"] = out_dir

    # Entrée : une URL est passée telle quelle ; du texte collé est écrit sur disque.
    if _looks_url(source):
        source_arg = source.strip()
    else:
        source_arg = os.path.join(out_dir, "article.txt")
        with open(source_arg, "w", encoding="utf-8") as f:
            f.write(source)

    cmd = [sys.executable, os.path.join(APP_ROOT, "make_short.py"),
           source_arg, "--out", out_dir, "--tts", tts]
    if site.strip():
        cmd += ["--site", site.strip()]

    env = os.environ.copy()
    env["ELEVENLABS_VOICE_ID"] = voice
    env["VISUAL_MODE"] = visual          # image | video
    env["IMAGE_PROVIDER"] = images       # stock | openrouter
    env["PYTHONUNBUFFERED"] = "1"

    job["status"] = "running"
    try:
        proc = subprocess.Popen(
            cmd, cwd=APP_ROOT, env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        for line in proc.stdout:
            job["log"].append(line.rstrip())
        proc.wait()
    except Exception as e:  # pragma: no cover
        job["status"] = "error"
        job["error"] = str(e)
        return

    if proc.returncode == 0 and os.path.exists(os.path.join(out_dir, "short.mp4")):
        job["status"] = "done"
    else:
        job["status"] = "error"
        job["error"] = "La génération a échoué (voir le journal)."


@app.post("/api/generate")
def api_generate():
    data = request.form
    source = (data.get("source") or "").strip()
    if not source:
        return jsonify(error="Colle une URL ou le texte d'un article."), 400

    voice = data.get("voice") or "alice"
    tts = "edge" if voice == "edge" else "auto"
    if voice == "edge":
        voice = ""
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "queued", "log": [], "out_dir": None, "error": None}
    threading.Thread(
        target=_run_job,
        args=(job_id, source, data.get("site") or "", voice, tts,
              data.get("visual") or "video", data.get("images") or "stock"),
        daemon=True,
    ).start()
    return jsonify(job_id=job_id)


@app.get("/api/status/<job_id>")
def api_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify(status=job["status"], log=job["log"], error=job["error"])


@app.get("/api/video/<job_id>")
def api_video(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        abort(404)
    return send_file(os.path.join(job["out_dir"], "short.mp4"), mimetype="video/mp4")


@app.get("/api/youtube/<job_id>")
def api_youtube(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        abort(404)
    path = os.path.join(job["out_dir"], "youtube.txt")
    if not os.path.exists(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        return app.response_class(f.read(), mimetype="text/plain")


@app.get("/")
def index():
    options = "".join(f'<option value="{v}">{v.capitalize()}</option>' for v in VOICES)
    return app.response_class(PAGE.replace("__VOICES__", options), mimetype="text/html")


PAGE = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shortmaker — Article → Short</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 0 auto;
         padding: 24px; background:#0f1115; color:#e7e9ee; }
  h1 { font-size: 1.5rem; }
  p.sub { color:#9aa0ad; margin-top:-8px; }
  label { display:block; margin:14px 0 6px; font-weight:600; }
  textarea, input, select { width:100%; padding:10px; border-radius:8px;
         border:1px solid #2a2f3a; background:#171a21; color:#e7e9ee; font-size:14px; }
  textarea { min-height:140px; resize:vertical; }
  .row { display:flex; gap:12px; } .row > div { flex:1; }
  button { margin-top:18px; padding:12px 20px; border:0; border-radius:8px;
         background:#3b82f6; color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
  button:disabled { background:#3a4252; cursor:not-allowed; }
  #log { white-space:pre-wrap; background:#0b0d11; border:1px solid #2a2f3a;
         border-radius:8px; padding:12px; margin-top:16px; font-family:ui-monospace,monospace;
         font-size:12.5px; color:#b7c0d0; max-height:240px; overflow:auto; display:none; }
  #result { margin-top:20px; display:none; }
  video { width:100%; max-width:340px; border-radius:12px; display:block; }
  pre#yt { white-space:pre-wrap; background:#0b0d11; border:1px solid #2a2f3a;
         border-radius:8px; padding:12px; font-size:13px; }
  a.dl { display:inline-block; margin-top:8px; color:#7ab0ff; }
  .err { color:#ff8585; }
</style></head>
<body>
  <h1>🎬 shortmaker</h1>
  <p class="sub">Colle une URL ou le texte d'un article → récupère un Short vertical prêt à publier.</p>

  <label for="source">Article (URL ou texte collé)</label>
  <textarea id="source" placeholder="https://mon-site.fr/mon-article  —  ou colle directement le texte…"></textarea>

  <div class="row">
    <div>
      <label for="site">URL de ton site (appel à l'action)</label>
      <input id="site" placeholder="https://mon-site.fr">
    </div>
    <div>
      <label for="voice">Voix</label>
      <select id="voice">__VOICES__<option value="edge">Edge (gratuit)</option></select>
    </div>
  </div>

  <div class="row">
    <div>
      <label for="visual">Visuel</label>
      <select id="visual">
        <option value="video">Clips vidéo (Pexels)</option>
        <option value="image">Images animées</option>
      </select>
    </div>
    <div>
      <label for="images">Source des images</label>
      <select id="images">
        <option value="stock">Banque gratuite</option>
        <option value="openrouter">IA Gemini (si clé OpenRouter)</option>
      </select>
    </div>
  </div>

  <button id="go">Générer le Short</button>

  <div id="log"></div>

  <div id="result">
    <h2>✅ Ton Short</h2>
    <video id="vid" controls></video>
    <a class="dl" id="dl" download="short.mp4">⬇ Télécharger short.mp4</a>
    <h3>Texte YouTube</h3>
    <pre id="yt"></pre>
  </div>

<script>
const $ = id => document.getElementById(id);
$('go').onclick = async () => {
  const source = $('source').value.trim();
  if (!source) { alert("Colle une URL ou le texte d'un article."); return; }
  $('go').disabled = true; $('result').style.display='none';
  const log = $('log'); log.style.display='block'; log.textContent='• Lancement…';
  const fd = new FormData();
  for (const k of ['source','site','voice','visual','images']) fd.append(k, $(k).value);
  let r = await fetch('/api/generate', {method:'POST', body:fd});
  if (!r.ok) { log.textContent = 'Erreur: ' + (await r.json()).error; $('go').disabled=false; return; }
  const { job_id } = await r.json();
  const poll = setInterval(async () => {
    const s = await (await fetch('/api/status/'+job_id)).json();
    if (s.log.length) log.textContent = s.log.join('\\n');
    log.scrollTop = log.scrollHeight;
    if (s.status === 'done') {
      clearInterval(poll); $('go').disabled=false;
      $('vid').src = '/api/video/'+job_id;
      $('dl').href = '/api/video/'+job_id;
      $('yt').textContent = await (await fetch('/api/youtube/'+job_id)).text();
      $('result').style.display='block';
    } else if (s.status === 'error') {
      clearInterval(poll); $('go').disabled=false;
      log.textContent += '\\n\\n❌ ' + (s.error||'échec');
      log.classList.add('err');
    }
  }, 1500);
};
</script>
</body></html>"""


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
