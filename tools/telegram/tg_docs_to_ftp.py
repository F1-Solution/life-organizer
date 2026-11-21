# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["telethon>=1.45,<2"]
# ///
"""Download the approved Saved Messages documents one at a time, upload each to the FTP and delete the local copy."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FileReferenceExpiredError

from tg_common import DATA_DIR, load_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
from ftp_store import FtpStore  # noqa: E402


CHUNK = 512 * 1024


async def download_resumable(client: TelegramClient, msg_id: int, local: Path, attempts: int = 20) -> None:
    """Append to a partial file from its current size, retrying dropped connections."""
    for attempt in range(attempts):
        try:
            msg = await client.get_messages("me", ids=msg_id)
            done = local.stat().st_size if local.exists() else 0
            if done >= msg.file.size:
                return
            done -= done % CHUNK  # Telegram only serves offsets aligned to the request size.
            with local.open("r+b" if local.exists() else "wb") as fh:
                fh.truncate(done)
                fh.seek(done)
                async for chunk in client.iter_download(msg.media, offset=done, request_size=CHUNK):
                    fh.write(chunk)
            return
        except FileReferenceExpiredError:
            print(f"{msg_id}: file reference expired, refetching", flush=True)  # The next attempt reloads the message.
        except (ConnectionError, OSError) as exc:
            print(f"{msg_id}: connection lost ({exc}), retry {attempt + 1}", flush=True)
            await asyncio.sleep(min(60 * (attempt + 1), 600))
            if not client.is_connected():
                await client.connect()
    raise RuntimeError(f"{msg_id}: download failed after {attempts} attempts")


async def run(args: argparse.Namespace) -> None:
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    done_file = DATA_DIR / "ftp-uploaded.json"
    done = json.loads(done_file.read_text(encoding="utf-8")) if done_file.exists() else {}
    cfg = load_config()
    client = TelegramClient(str(cfg.session), cfg.api_id, cfg.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Session expired or revoked: run tg_login.py again.")
    args.tmp.mkdir(parents=True, exist_ok=True)
    try:
        for doc in decisions["tenere"]:
            if str(doc["id"]) in done:
                continue
            msg = await client.get_messages("me", ids=doc["id"])
            if not msg or not msg.file:
                print(f"{doc['id']}: message or file missing", flush=True)
                continue
            local = args.tmp / (msg.file.name or f"{doc['id']}")
            await download_resumable(client, doc["id"], local)
            store = FtpStore()  # A fresh connection per file survives the server's idle timeout during long downloads.
            try:
                remote = store.upload(local, "telegram", str(msg.date.year))
            finally:
                store.close()
            local.unlink()
            done[str(doc["id"])] = remote
            done_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{doc['id']}: {remote} ({doc['MB']} MB)", flush=True)
    finally:
        await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions", type=Path, default=DATA_DIR / "documenti-decisioni.json")
    p.add_argument("--tmp", type=Path, required=True, help="scratch folder for one file at a time")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
