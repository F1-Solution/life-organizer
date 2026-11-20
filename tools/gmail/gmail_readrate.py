# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2.150", "google-auth>=2.35"]
# ///
"""Read-only: for each sender in a JSON list, count messages ever read vs total (capped), to spot never-read newsletters."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from googleapiclient.discovery import build

from gmail_scan import load_credentials

CAP = 500


def count(svc, q: str) -> int:
    resp = svc.users().messages().list(userId="me", q=q, maxResults=CAP, includeSpamTrash=False).execute()
    return len(resp.get("messages", []))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--senders", type=Path, required=True, help="JSON list of sender addresses")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--after", default="", help="Gmail date, e.g. 2025/07/31, to compare like-for-like periods")
    args = p.parse_args()
    svc = build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
    done = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for i, addr in enumerate(json.loads(args.senders.read_text(encoding="utf-8"))):
        if addr in done:
            continue
        for attempt in range(5):
            try:
                extra = f" after:{args.after}" if args.after else ""
                done[addr] = {"read": count(svc, f"from:{addr} is:read{extra}"), "total": count(svc, f"from:{addr}{extra}")}
                break
            except Exception as exc:  # Rate limits: back off and retry.
                print(f"retry {addr}: {exc}")
                time.sleep(2 ** attempt)
        if i % 25 == 0:
            args.out.write_text(json.dumps(done, indent=1), encoding="utf-8")
            print(f"{i} senders checked")
    args.out.write_text(json.dumps(done, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
