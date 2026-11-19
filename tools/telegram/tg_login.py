# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["telethon>=1.45,<2"]
# ///
"""One-time interactive login: run it yourself in a terminal (asks phone, code and 2FA password)."""
import asyncio

from telethon import TelegramClient

from tg_common import load_config


async def main() -> None:
    cfg = load_config()
    cfg.session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(cfg.session), cfg.api_id, cfg.api_hash)
    async with client:
        me = await client.get_me()
        print(f"Login OK: {me.first_name} (id {me.id}). Session saved in {cfg.session}")


if __name__ == "__main__":
    asyncio.run(main())
