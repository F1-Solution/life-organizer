"""Shared config and pure helpers for the read-only Telegram tools."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TG_READER_HOME", Path.home() / ".config" / "telegram-reader"))
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "telegram"
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session: Path


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    env_file = config_dir / ".env"
    if not env_file.is_file():
        raise SystemExit(f"Missing {env_file}: create it with TG_API_ID=... and TG_API_HASH=... (from my.telegram.org).")
    values = parse_env(env_file.read_text(encoding="utf-8"))
    try:
        api_id = int(values["TG_API_ID"])
        api_hash = values["TG_API_HASH"]
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"{env_file} must define a numeric TG_API_ID and TG_API_HASH.") from exc
    return Config(api_id=api_id, api_hash=api_hash, session=config_dir / "reader.session")


def slugify(name: str, entity_id: int) -> str:
    slug = re.sub(r"[^\w-]+", "-", name.strip().lower(), flags=re.UNICODE).strip("-")
    return f"{slug or 'chat'}-{entity_id}"


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(m.rstrip(".,;:!?") for m in URL_RE.findall(text or "")))


def pick_by_name(names: dict[int, str], query: str) -> int:
    """Return the id whose name matches query: exact (case-insensitive) first, then substring."""
    q = query.strip().lower()
    exact = [i for i, n in names.items() if n.lower() == q]
    if len(exact) == 1:
        return exact[0]
    partial = exact or [i for i, n in names.items() if q in n.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No chat matches {query!r}. Use --list-chats to see names and ids.")
    options = "\n".join(f"  {i}  {names[i]}" for i in partial[:20])
    raise SystemExit(f"{query!r} matches several chats; pass the id instead:\n{options}")
