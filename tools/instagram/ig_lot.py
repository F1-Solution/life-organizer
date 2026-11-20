# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.48"]
# ///
"""Open an approved lot of Instagram DM threads (max 15, random 30-90 s pauses) and save their post and link URLs; never types or sends."""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PROFILE = Path(os.environ["USERPROFILE"]) / ".config" / "instagram-reader" / "profile"
MAX_LOT = 15
# Scrolls the inbox list until a row whose first line starts with the name appears, then clicks it.
JS_OPEN = """async (name) => {
  for (let i = 0; i < 60; i++) {
    const row = [...document.querySelectorAll('div[role="button"], a[href*="/direct/t/"]')]
      .find(e => e.innerText.trim().split('\\n')[0].trim().startsWith(name) && e.innerText.includes('·'));
    if (row) { row.click(); return true; }
    const boxes = [...document.querySelectorAll('div')].filter(d => d.scrollHeight > d.clientHeight + 50
        && d.innerText.includes('·') && getComputedStyle(d).overflowY !== 'visible');
    const box = boxes.sort((a, b) => a.innerText.length - b.innerText.length)[0];
    if (!box) return false;
    const before = box.scrollTop; box.scrollTop += box.clientHeight;
    if (box.scrollTop === before) return false;
    await new Promise(r => setTimeout(r, 2000));
  }
  return false;
}"""
# Returns the open conversation's text and every link inside it (the inbox list holds no post links).
JS_READ = """() => {
  const main = document.querySelector('div[role="main"]') || document.body;
  const links = [...main.querySelectorAll('a[href]')].map(a => ({href: a.href, text: a.innerText.trim()}));
  return {url: location.href, text: main.innerText.slice(-6000), links};
}"""


def clean(href: str) -> str | None:
    parts = urlsplit(href)
    if parts.netloc == "l.instagram.com":
        return parse_qs(parts.query).get("u", [None])[0]
    if "instagram.com" in parts.netloc:
        return href.split("?")[0] if any(k in parts.path for k in ("/p/", "/reel/", "/tv/")) else None
    return href if parts.scheme.startswith("http") else None


def read_thread(page, name: str) -> dict:
    try:
        page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeout:
        return {"name": name, "error": "inbox non caricata"}
    page.wait_for_timeout(7000)
    if not page.evaluate(JS_OPEN, name):
        return {"name": name, "error": "thread non trovato"}
    page.wait_for_timeout(7000)
    data = page.evaluate(JS_READ)
    urls = list(dict.fromkeys(u for u in (clean(l["href"]) for l in data["links"]) if u))
    return {"name": name, "thread_url": data["url"], "urls": urls, "text": data["text"],
            "letto_il": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--names", type=Path, required=True, help="JSON list of approved thread names (prefixes)")
    p.add_argument("--out", type=Path, required=True, help="JSONL, one record per thread (appended)")
    args = p.parse_args()
    names = json.loads(args.names.read_text(encoding="utf-8"))
    if len(names) > MAX_LOT:
        raise SystemExit(f"Lot has {len(names)} threads; the limit is {MAX_LOT}.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, name in enumerate(names):
            rec = read_thread(page, name)
            with args.out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{name}: {rec.get('error') or str(len(rec['urls'])) + ' link'}", flush=True)
            if i < len(names) - 1:
                page.wait_for_timeout(random.uniform(30, 90) * 1000)
        ctx.close()


if __name__ == "__main__":
    main()
