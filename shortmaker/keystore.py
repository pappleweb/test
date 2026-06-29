"""Stockage local des clés API par fournisseur, avec activation.

`keys.json` (à la racine du dépôt, **gitignoré**) :
    { provider: { "keys": [ {"label","value"} ], "active": int } }

La clé *active* de chaque fournisseur est injectée dans l'environnement des jobs
(priorité sur les variables d'environnement). Prototype : stockage **en clair** sur
disque local — pour un SaaS, remplacer par un secrets manager chiffré par tenant.
"""
from __future__ import annotations

import json
import os
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_FILE = os.path.join(_ROOT, "keys.json")

# Fournisseur -> variable d'environnement consommée par le pipeline.
ENV_VAR = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "fal": "FAL_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
PROVIDERS = list(ENV_VAR)

_LOCK = threading.Lock()


def _read() -> dict:
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data: dict) -> None:
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load() -> dict:
    """État complet, avec une entrée par fournisseur connu."""
    data = _read()
    for p in PROVIDERS:
        entry = data.setdefault(p, {"keys": [], "active": 0})
        entry.setdefault("keys", [])
        entry.setdefault("active", 0)
    return data


def add_key(provider: str, label: str, value: str) -> None:
    if provider not in ENV_VAR or not value.strip():
        return
    with _LOCK:
        data = load()
        keys = data[provider]["keys"]
        keys.append({"label": label.strip() or f"clé {len(keys) + 1}", "value": value.strip()})
        if len(keys) == 1:
            data[provider]["active"] = 0
        _write(data)


def delete_key(provider: str, index: int) -> None:
    with _LOCK:
        data = load()
        keys = data[provider]["keys"]
        if 0 <= index < len(keys):
            keys.pop(index)
            if data[provider]["active"] >= len(keys):
                data[provider]["active"] = max(0, len(keys) - 1)
            _write(data)


def set_active(provider: str, index: int) -> None:
    with _LOCK:
        data = load()
        if 0 <= index < len(data[provider]["keys"]):
            data[provider]["active"] = index
            _write(data)


def active_value(provider: str) -> str | None:
    entry = load().get(provider, {})
    keys, i = entry.get("keys", []), entry.get("active", 0)
    return keys[i]["value"] if 0 <= i < len(keys) else None


def active_env() -> dict:
    """`{VAR: valeur_active}` pour les fournisseurs ayant une clé active."""
    return {var: v for p, var in ENV_VAR.items() if (v := active_value(p))}


def masked_view() -> dict:
    """Vue pour l'API : valeurs masquées (jamais renvoyer les clés en clair)."""
    out = {}
    for p, entry in load().items():
        if p not in ENV_VAR:
            continue
        out[p] = {
            "active": entry["active"],
            "keys": [
                {"label": k["label"],
                 "hint": ("…" + k["value"][-4:]) if len(k["value"]) >= 4 else "…"}
                for k in entry["keys"]
            ],
        }
    return out
