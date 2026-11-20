# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2.150", "google-auth>=2.35"]
# ///
"""Read-only Gmail scan: saves headers of messages matching a query to JSONL (resumable, never modifies mail)."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "List-Id", "Precedence"]
BATCH = 50


def load_credentials() -> Credentials:
    # Secrets stay in memory: gws keeps them encrypted on disk.
    gws = shutil.which("gws") or "gws"  # On Windows gws is a .cmd shim that CreateProcess cannot find by bare name.
    raw = subprocess.run([gws, "auth", "export", "--unmasked"], capture_output=True, text=True, check=True).stdout
    d = json.loads(raw)
    return Credentials(None, refresh_token=d["refresh_token"], client_id=d["client_id"],
                       client_secret=d["client_secret"], token_uri="https://oauth2.googleapis.com/token")


def list_ids(svc, query: str) -> list[str]:
    ids, token = [], None
    while True:
        resp = svc.users().messages().list(userId="me", q=query, maxResults=500, pageToken=token).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        print(f"\rlisted {len(ids)}", end="", file=sys.stderr)
        if not token:
            print(file=sys.stderr)
            return ids


def to_record(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {"id": msg["id"], "thread": msg["threadId"], "labels": msg.get("labelIds", []),
            "internal_date": msg.get("internalDate"), "size": msg.get("sizeEstimate"),
            "snippet": msg.get("snippet", "")[:160], **{h.lower(): headers.get(h) for h in HEADERS}}


def fetch(svc, ids: list[str], out: Path) -> None:
    done = {json.loads(l)["id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    todo = [i for i in ids if i not in done]
    print(f"{len(done)} already saved, {len(todo)} to fetch", file=sys.stderr)
    with out.open("a", encoding="utf-8") as fh:
        for start in range(0, len(todo), BATCH):
            chunk, results, retry = todo[start:start + BATCH], {}, []

            def cb(req_id, resp, exc):
                if exc is None:
                    results[req_id] = resp
                elif isinstance(exc, HttpError) and exc.status_code in (403, 429, 500, 503):
                    retry.append(req_id)
                else:
                    print(f"\nskip {req_id}: {exc}", file=sys.stderr)

            pending = chunk
            for attempt in range(6):
                batch = svc.new_batch_http_request(callback=cb)
                for mid in pending:
                    batch.add(svc.users().messages().get(userId="me", id=mid, format="metadata",
                                                         metadataHeaders=HEADERS), request_id=mid)
                batch.execute()
                if not retry:
                    break
                pending, retry = retry, []
                time.sleep(2 ** attempt)
            for mid in chunk:
                if mid in results:
                    fh.write(json.dumps(to_record(results[mid]), ensure_ascii=False) + "\n")
            fh.flush()
            print(f"\rfetched {min(start + BATCH, len(todo))}/{len(todo)}", end="", file=sys.stderr)
            time.sleep(0.5)
    print(file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--query", default="in:inbox is:unread")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    svc = build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fetch(svc, list_ids(svc, args.query), args.out)


if __name__ == "__main__":
    main()
