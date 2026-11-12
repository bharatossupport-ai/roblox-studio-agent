"""Settings stored in %APPDATA%\\StudioAgent (keys in the OS keyring when available)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import keyring  # Windows Credential Manager
except Exception:  # pragma: no cover
    keyring = None

SERVICE = "StudioAgent"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    d = base / "StudioAgent"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "provider": "free",
    "models": {},       # provider id -> model
    "base_urls": {},    # provider id -> base url override (custom)
    "custom_prompt": "",
    "max_steps": 40,
}


def load() -> dict:
    p = config_dir() / "config.json"
    cfg = dict(DEFAULTS)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text("utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> None:
    (config_dir() / "config.json").write_text(json.dumps(cfg, indent=2), "utf-8")


def get_key(provider_id: str) -> str:
    if keyring:
        try:
            return keyring.get_password(SERVICE, provider_id) or ""
        except Exception:
            pass
    return load().get("_keys", {}).get(provider_id, "")


def set_key(provider_id: str, key: str) -> None:
    if keyring:
        try:
            if key:
                keyring.set_password(SERVICE, provider_id, key)
            else:
                try:
                    keyring.delete_password(SERVICE, provider_id)
                except Exception:
                    pass
            return
        except Exception:
            pass
    cfg = load()
    cfg.setdefault("_keys", {})[provider_id] = key
    save(cfg)
