# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2.150", "google-auth>=2.35"]
# ///
"""Create Gmail filters from an approved label plan so future mail is labelled, archived and marked read the same way."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from googleapiclient.discovery import build

from gmail_scan import load_credentials

MAX_FROM = 900  # Gmail rejects very long criteria; keep each filter's sender list short.


def chunks(senders: list[str]) -> list[str]:
    out, cur = [], []
    for s in senders:
        if cur and len(" OR ".join(cur + [s])) > MAX_FROM:
            out.append(" OR ".join(cur))
            cur = []
        cur.append(s)
    return out + ([" OR ".join(cur)] if cur else [])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--skip", nargs="*", default=[], help="labels to leave without a filter")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    svc = build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
    labels = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute()["labels"]}
    existing = {json.dumps(f.get("criteria"), sort_keys=True)
                for f in svc.users().settings().filters().list(userId="me").execute().get("filter", [])}
    for lab, g in plan.items():
        if lab in args.skip:
            continue
        remove = (["INBOX"] if g["archive"] else []) + (["UNREAD"] if g["read"] else [])
        parts = chunks(g["senders"])
        print(f"{lab}: {len(parts)} filters for {len(g['senders'])} senders, archive={g['archive']} read={g['read']}")
        for crit in parts:
            body = {"criteria": {"from": crit}, "action": {"addLabelIds": [labels[lab]], "removeLabelIds": remove}}
            if args.dry_run or json.dumps(body["criteria"], sort_keys=True) in existing:
                continue
            svc.users().settings().filters().create(userId="me", body=body).execute()


if __name__ == "__main__":
    main()
