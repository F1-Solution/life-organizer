# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.48"]
# ///
"""Open Instagram in a dedicated persistent Edge profile so the owner can log in by hand; closes when the window is closed."""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(os.environ["USERPROFILE"]) / ".config" / "instagram-reader" / "profile"


def main() -> None:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.instagram.com/direct/inbox/")
        page.wait_for_event("close", timeout=0)
        ctx.close()


if __name__ == "__main__":
    main()
