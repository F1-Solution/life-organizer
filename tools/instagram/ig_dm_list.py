# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.48"]
# ///
"""Read-only: scroll the Instagram Direct inbox and save every thread (name, preview, age, unread) without opening any."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(os.environ["USERPROFILE"]) / ".config" / "instagram-reader" / "profile"
# Picks the scrollable list holding the threads, and returns one entry per thread link/row.
JS_ROWS = """() => {
  const boxes = [...document.querySelectorAll('div')].filter(d => d.scrollHeight > d.clientHeight + 50
      && /Unread|new message|sent/.test(d.innerText) && getComputedStyle(d).overflowY !== 'visible');
  const box = boxes.sort((a, b) => a.innerText.length - b.innerText.length)[0];
  if (!box) return {rows: [], end: true};
  const rows = [...box.querySelectorAll('div[role="button"], a[href*="/direct/t/"]')]
      .map(e => e.innerText.trim()).filter(t => t.includes('·'));
  const before = box.scrollTop; box.scrollTop += box.clientHeight;
  return {rows, end: box.scrollTop === before};
}"""


def parse(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip() and l.strip() != "·"]
    return {"name": lines[0], "preview": lines[1] if len(lines) > 1 else "",
            "age": next((l for l in lines[2:] if l not in ("Unread", "Active")), ""),
            "unread": "Unread" in lines}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-scrolls", type=int, default=80)
    args = p.parse_args()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.instagram.com/direct/inbox/")
        page.wait_for_timeout(8000)
        seen: dict[str, dict] = {}
        for _ in range(args.max_scrolls):
            res = page.evaluate(JS_ROWS)
            for t in res["rows"]:
                row = parse(t)
                seen.setdefault(row["name"], row)
            if res["end"]:
                break
            page.wait_for_timeout(2500)
        ctx.close()
    args.out.write_text(json.dumps(list(seen.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(seen)} threads, {sum(r['unread'] for r in seen.values())} unread")


if __name__ == "__main__":
    main()
