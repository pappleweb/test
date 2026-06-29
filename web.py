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

from shortmaker import keystore

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_BASE = os.path.join(APP_ROOT, "out", "web")
os.makedirs(OUT_BASE, exist_ok=True)

app = Flask(__name__)
JOBS: dict[str, dict] = {}  # job_id -> {status, log, out_dir, error}


def _looks_url(s: str) -> bool:
    return bool(re.match(r"https?://", s.strip()))


def _elevenlabs_key() -> str | None:
    return keystore.active_value("elevenlabs") or os.getenv("ELEVENLABS_API_KEY")


def _run_job(job_id: str, source: str, site: str, voice: str,
             tts: str, visual: str, images: str, transition: bool) -> None:
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
    if transition:
        cmd += ["--transition"]

    env = os.environ.copy()
    env.update(keystore.active_env())   # clés actives gérées dans /settings (prioritaires)
    env["ELEVENLABS_VOICE_ID"] = voice
    env["VISUAL_MODE"] = visual          # image | video
    env["IMAGE_PROVIDER"] = images       # stock | openrouter | flux
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

    voice = (data.get("voice") or "alice").strip()
    tts = "edge" if voice == "edge" else "auto"
    if voice == "edge":
        voice = ""
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "queued", "log": [], "out_dir": None, "error": None}
    threading.Thread(
        target=_run_job,
        args=(job_id, source, data.get("site") or "", voice, tts,
              data.get("visual") or "video", data.get("images") or "stock",
              data.get("transition") == "on"),
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


# --------------------------------------------------------------- Voix ElevenLabs

@app.get("/api/voices")
def api_voices():
    """Liste les voix du compte ElevenLabs (clé active) pour peupler le menu."""
    key = _elevenlabs_key()
    if not key:
        return jsonify(voices=[])
    try:
        import requests

        r = requests.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": key}, timeout=20)
        r.raise_for_status()
        voices = [{"id": v["voice_id"], "name": v["name"],
                   "category": v.get("category", "")} for v in r.json().get("voices", [])]
        return jsonify(voices=voices)
    except Exception as e:
        return jsonify(voices=[], error=str(e))


# --------------------------------------------------------------- Clés API (/settings)

@app.get("/api/keys")
def api_keys():
    return jsonify(providers=keystore.masked_view())


@app.post("/api/keys/add")
def api_keys_add():
    d = request.form
    keystore.add_key(d.get("provider", ""), d.get("label", ""), d.get("value", ""))
    return jsonify(providers=keystore.masked_view())


@app.post("/api/keys/activate")
def api_keys_activate():
    d = request.form
    keystore.set_active(d.get("provider", ""), int(d.get("index", -1)))
    return jsonify(providers=keystore.masked_view())


@app.post("/api/keys/delete")
def api_keys_delete():
    d = request.form
    keystore.delete_key(d.get("provider", ""), int(d.get("index", -1)))
    return jsonify(providers=keystore.masked_view())


@app.get("/")
def index():
    return app.response_class(PAGE, mimetype="text/html")


@app.get("/settings")
def settings():
    return app.response_class(SETTINGS_PAGE, mimetype="text/html")


_STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 0 auto;
         padding: 24px; background:#0f1115; color:#e7e9ee; }
  h1 { font-size: 1.5rem; } a { color:#7ab0ff; }
  p.sub { color:#9aa0ad; margin-top:-8px; }
  label { display:block; margin:14px 0 6px; font-weight:600; }
  textarea, input, select { width:100%; padding:10px; border-radius:8px;
         border:1px solid #2a2f3a; background:#171a21; color:#e7e9ee; font-size:14px; }
  textarea { min-height:140px; resize:vertical; }
  .row { display:flex; gap:12px; } .row > div { flex:1; }
  button { margin-top:18px; padding:12px 20px; border:0; border-radius:8px;
         background:#3b82f6; color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
  button.small { margin:0; padding:6px 10px; font-size:13px; }
  button.ghost { background:#2a2f3a; }
  button:disabled { background:#3a4252; cursor:not-allowed; }
  #log { white-space:pre-wrap; background:#0b0d11; border:1px solid #2a2f3a;
         border-radius:8px; padding:12px; margin-top:16px; font-family:ui-monospace,monospace;
         font-size:12.5px; color:#b7c0d0; max-height:240px; overflow:auto; display:none; }
  #result { margin-top:20px; display:none; }
  video { width:100%; max-width:340px; border-radius:12px; display:block; }
  pre#yt { white-space:pre-wrap; background:#0b0d11; border:1px solid #2a2f3a;
         border-radius:8px; padding:12px; font-size:13px; }
  a.dl { display:inline-block; margin-top:8px; }
  .err { color:#ff8585; }
  .prov { border:1px solid #2a2f3a; border-radius:10px; padding:14px; margin:14px 0; }
  .prov h3 { margin:0 0 8px; }
  .keyline { display:flex; align-items:center; gap:10px; padding:6px 0; }
  .keyline .muted { color:#9aa0ad; font-size:13px; }
  .badge { background:#1f6f3a; color:#fff; border-radius:6px; padding:2px 8px; font-size:12px; }
  nav { float:right; font-size:14px; }
"""


PAGE = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shortmaker — Article → Short</title>
<style>__STYLE__</style></head>
<body>
  <nav><a href="/settings">⚙ Clés API</a></nav>
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
      <label for="voice">Voix (ElevenLabs)</label>
      <select id="voice"><option value="edge">Edge (gratuit)</option></select>
    </div>
  </div>

  <label for="voiceCustom">…ou un ID de voix ElevenLabs précis (prioritaire si rempli)</label>
  <input id="voiceCustom" placeholder="ex. Xb7hH8MSUJpSbSDYk0k2">

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
        <option value="stock">Banque gratuite (+ images de l'article)</option>
        <option value="openrouter">IA Gemini (si clé OpenRouter)</option>
        <option value="flux">IA FLUX (si clé fal)</option>
      </select>
    </div>
  </div>

  <label style="display:flex;align-items:center;gap:8px;font-weight:500;margin-top:16px;">
    <input type="checkbox" id="transition" style="width:auto;">
    Transitions (fondus enchaînés entre scènes)
  </label>

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

// Peuple le menu des voix depuis le compte ElevenLabs (clé active).
(async () => {
  try {
    const { voices } = await (await fetch('/api/voices')).json();
    const sel = $('voice');
    for (const v of (voices||[])) {
      const o = document.createElement('option');
      o.value = v.id; o.textContent = v.name + (v.category ? ' ('+v.category+')' : '');
      sel.insertBefore(o, sel.firstChild);
    }
    if (voices && voices.length) sel.selectedIndex = 0;
  } catch (e) {}
})();

$('go').onclick = async () => {
  const source = $('source').value.trim();
  if (!source) { alert("Colle une URL ou le texte d'un article."); return; }
  $('go').disabled = true; $('result').style.display='none';
  const log = $('log'); log.style.display='block'; log.textContent='• Lancement…';
  const fd = new FormData();
  for (const k of ['source','site','visual','images']) fd.append(k, $(k).value);
  fd.append('voice', $('voiceCustom').value.trim() || $('voice').value);
  fd.append('transition', $('transition').checked ? 'on' : 'off');
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
</body></html>""".replace("__STYLE__", _STYLE)


SETTINGS_PAGE = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>shortmaker — Clés API</title>
<style>__STYLE__</style></head>
<body>
  <nav><a href="/">← Générateur</a></nav>
  <h1>⚙ Clés API</h1>
  <p class="sub">Ajoute plusieurs clés par fournisseur et active celle à utiliser. Stockées
     en local (<code>keys.json</code>), prioritaires sur les variables d'environnement.</p>
  <div id="providers"></div>

<script>
const $ = id => document.getElementById(id);
const LABELS = {elevenlabs:'ElevenLabs (voix)', pexels:'Pexels (images + vidéos)',
  pixabay:'Pixabay (images secours)', openrouter:'OpenRouter (images Gemini)',
  fal:'fal.ai (images FLUX)', anthropic:'Anthropic (scénario)'};

function post(url, obj) {
  const fd = new FormData();
  for (const k in obj) fd.append(k, obj[k]);
  return fetch(url, {method:'POST', body:fd}).then(r => r.json());
}

function render(data) {
  const root = $('providers'); root.innerHTML = '';
  for (const p in LABELS) {
    const info = data[p] || {keys:[], active:0};
    const div = document.createElement('div'); div.className = 'prov';
    let html = '<h3>'+LABELS[p]+'</h3>';
    if (!info.keys.length) html += '<p class="muted">Aucune clé.</p>';
    info.keys.forEach((k, i) => {
      const active = (i === info.active);
      html += '<div class="keyline">'
        + (active ? '<span class="badge">active</span>' : '<button class="small ghost" data-act="activate" data-p="'+p+'" data-i="'+i+'">activer</button>')
        + '<span>'+k.label+'</span><span class="muted">'+k.hint+'</span>'
        + '<button class="small ghost" data-act="delete" data-p="'+p+'" data-i="'+i+'" style="margin-left:auto;">suppr</button>'
        + '</div>';
    });
    html += '<div class="keyline"><input placeholder="libellé (ex. compte perso)" data-f="label" data-p="'+p+'">'
      + '<input placeholder="valeur de la clé" data-f="value" data-p="'+p+'">'
      + '<button class="small" data-act="add" data-p="'+p+'">ajouter</button></div>';
    div.innerHTML = html; root.appendChild(div);
  }
  root.querySelectorAll('button[data-act]').forEach(b => b.onclick = onAction);
}

async function onAction(e) {
  const b = e.currentTarget, p = b.dataset.p, act = b.dataset.act;
  let data;
  if (act === 'add') {
    const label = document.querySelector('input[data-f="label"][data-p="'+p+'"]').value;
    const value = document.querySelector('input[data-f="value"][data-p="'+p+'"]').value;
    if (!value.trim()) return;
    data = await post('/api/keys/add', {provider:p, label, value});
  } else {
    data = await post('/api/keys/'+act, {provider:p, index:b.dataset.i});
  }
  render(data.providers);
}

(async () => render((await (await fetch('/api/keys')).json()).providers))();
</script>
</body></html>""".replace("__STYLE__", _STYLE)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
