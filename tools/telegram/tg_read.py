# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["telethon>=1.45,<2"]
# ///
"""Read-only Telegram export: lists chats or appends new messages of one chat to JSONL (never marks them read)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.tl.types import (
    MessageEntityTextUrl,
    MessageEntityUrl,
    MessageMediaWebPage,
)

from tg_common import DATA_DIR, extract_urls, load_config, pick_by_name, slugify


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list-chats", action="store_true", help="list dialogs with their ids")
    p.add_argument("--chat", help="chat name, @username, numeric id, or 'me' for Saved Messages")
    p.add_argument("--since", help="only messages from this date (YYYY-MM-DD); ignores saved state")
    p.add_argument("--full", action="store_true", help="re-export the whole chat, replacing previous output")
    p.add_argument("--limit", type=int, default=None, help="max messages to fetch")
    p.add_argument("--media", action="store_true", help="download photos, videos, documents and voice notes")
    p.add_argument("--max-mb", type=float, default=50.0, help="skip media larger than this")
    p.add_argument("--out-dir", type=Path, default=DATA_DIR)
    return p.parse_args()


async def resolve_chat(client: TelegramClient, query: str):
    if query == "me" or query.startswith("@") or query.lstrip("-").isdigit():
        return await client.get_entity(int(query) if query.lstrip("-").isdigit() else query)
    dialogs = {d.id: d.name or "" async for d in client.iter_dialogs()}
    return await client.get_entity(pick_by_name(dialogs, query))


def message_urls(msg) -> list[str]:
    urls = []
    for entity, text in msg.get_entities_text():
        if isinstance(entity, MessageEntityTextUrl):
            urls.append(entity.url)
        elif isinstance(entity, MessageEntityUrl):
            urls.append(text)
    return list(dict.fromkeys(urls + extract_urls(msg.message)))


def web_preview(msg) -> dict | None:
    if not isinstance(msg.media, MessageMediaWebPage):
        return None
    page = msg.media.webpage
    fields = ("url", "site_name", "title", "description")
    return {f: getattr(page, f, None) for f in fields if getattr(page, f, None)} or None


async def to_record(msg, media_dir: Path, args: argparse.Namespace) -> dict:
    sender = await msg.get_sender()
    record = {
        "id": msg.id,
        "date": msg.date.isoformat(),
        "sender": utils.get_display_name(sender) if sender else None,
        "text": msg.message or "",
        "urls": message_urls(msg),
        "reply_to": msg.reply_to_msg_id,
        "forwarded_from": (msg.fwd_from.from_name if msg.fwd_from else None),
        "is_forward": msg.fwd_from is not None,
        "preview": web_preview(msg),
        "media": None,
        "media_file": None,
    }
    if msg.media and not isinstance(msg.media, MessageMediaWebPage):
        record["media"] = type(msg.media).__name__.removeprefix("MessageMedia").lower()
        size = getattr(msg.file, "size", None) or 0
        if args.media and size <= args.max_mb * 1024 * 1024:
            media_dir.mkdir(parents=True, exist_ok=True)
            path = await msg.download_media(file=str(media_dir / f"{msg.id}_"))
            record["media_file"] = str(Path(path).relative_to(media_dir.parent)) if path else None
    return record


async def export_chat(client: TelegramClient, args: argparse.Namespace) -> None:
    entity = await resolve_chat(client, args.chat)
    name = utils.get_display_name(entity) or str(entity.id)
    chat_dir = args.out_dir / slugify(name, entity.id)
    chat_dir.mkdir(parents=True, exist_ok=True)
    state_file, out_file = chat_dir / "state.json", chat_dir / "messages.jsonl"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    kwargs = {"reverse": True, "limit": args.limit}
    if args.since:
        kwargs["offset_date"] = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    elif not args.full and state.get("last_id"):
        kwargs["min_id"] = state["last_id"]
    mode = "w" if args.full or args.since else "a"

    count, last_id = 0, state.get("last_id", 0)
    with out_file.open(mode, encoding="utf-8") as fh:
        async for msg in client.iter_messages(entity, **kwargs):
            fh.write(json.dumps(await to_record(msg, chat_dir / "media", args), ensure_ascii=False) + "\n")
            count, last_id = count + 1, max(last_id, msg.id)

    state.update(chat=name, chat_id=entity.id, last_id=last_id, last_run=datetime.now(timezone.utc).isoformat())
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{count} new messages from {name!r} -> {out_file}")


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and choke on emoji in chat names.
    args = parse_args()
    if not args.list_chats and not args.chat:
        raise SystemExit("Pass --list-chats or --chat <name|@username|id|me>.")
    cfg = load_config()
    if not cfg.session.exists():
        raise SystemExit(f"No session at {cfg.session}: run tg_login.py yourself first.")
    client = TelegramClient(str(cfg.session), cfg.api_id, cfg.api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SystemExit("Session expired or revoked: run tg_login.py again.")
        if args.list_chats:
            async for d in client.iter_dialogs(limit=args.limit):
                print(f"{d.id}\t{d.name}")
        else:
            await export_chat(client, args)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
