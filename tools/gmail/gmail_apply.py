# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2.150", "google-auth>=2.35"]
# ///
"""Apply an approved label plan: adds labels, optionally archives and marks read. Never sends or deletes mail."""
from __future__ import annotations

import argparse
import json
from email.utils import parseaddr
from pathlib import Path

from googleapiclient.discovery import build

from gmail_scan import load_credentials

CHUNK = 1000  # batchModify limit


def label_ids(svc, names: list[str], dry: bool) -> dict[str, str]:
    existing = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute()["labels"]}
    for name in names:
        if name not in existing:
            print(f"create label {name}")
            if not dry:
                existing[name] = svc.users().labels().create(userId="me", body={"name": name}).execute()["id"]
    return existing


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True, help='{"Label": {"senders": [...], "archive": bool, "read": bool}}')
    p.add_argument("--messages", type=Path, required=True, help="JSONL from gmail_scan.py")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    sender_label = {s: lab for lab, g in plan.items() for s in g["senders"]}
    ids: dict[str, list[str]] = {lab: [] for lab in plan}
    for line in args.messages.open(encoding="utf-8"):
        r = json.loads(line)
        lab = sender_label.get(parseaddr(r.get("from") or "")[1].lower())
        if lab:
            ids[lab].append(r["id"])
    svc = build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
    labels = label_ids(svc, list(plan), args.dry_run)
    for lab, g in plan.items():
        remove = (["INBOX"] if g["archive"] else []) + (["UNREAD"] if g["read"] else [])
        print(f"{lab}: {len(ids[lab])} messages, archive={g['archive']} read={g['read']}")
        if args.dry_run:
            continue
        for i in range(0, len(ids[lab]), CHUNK):
            svc.users().messages().batchModify(userId="me", body={
                "ids": ids[lab][i:i + CHUNK], "addLabelIds": [labels[lab]], "removeLabelIds": remove}).execute()


if __name__ == "__main__":
    main()
