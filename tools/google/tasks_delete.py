# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2", "google-auth>=2", "openpyxl>=3"]
# ///
"""Delete the Google Tasks the owner marked "scarta" in the reviewed workbook (needs the tasks scope); --dry-run only lists them."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import openpyxl
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gmail"))
from gmail_scan import load_credentials  # noqa: E402


def marked(xlsx: Path) -> set[str]:
    rows = list(openpyxl.load_workbook(xlsx, read_only=True)["Tasks"].iter_rows(values_only=True))
    col = {k: i for i, k in enumerate(rows[0])}
    return {r[col["id"]] for r in rows[1:] if (r[col["correzione"]] or r[col["tipo"]]) == "scarta"}


def task_lists(ndjson: Path) -> dict[str, tuple[str, str]]:
    """Map task id to (list id, title) from the saved export."""
    out = {}
    for line in ndjson.open(encoding="utf-8"):
        for t in json.loads(line).get("items", []):
            out[t["id"]] = (t["selfLink"].split("/lists/")[1].split("/")[0], t.get("title", ""))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xlsx", type=Path, required=True)
    p.add_argument("--tasks", type=Path, required=True, help="tasks.ndjson export (also the backup)")
    p.add_argument("--log", type=Path, required=True, help="JSONL of deleted tasks")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    ids, lists = marked(a.xlsx), task_lists(a.tasks)
    missing = ids - lists.keys()
    if missing:
        raise SystemExit(f"{len(missing)} ids not in the export; refresh it first.")
    print(f"{len(ids)} tasks marked scarta")
    if a.dry_run:
        return
    svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)
    with a.log.open("a", encoding="utf-8") as log:
        for i, tid in enumerate(sorted(ids), 1):
            list_id, title = lists[tid]
            svc.tasks().delete(tasklist=list_id, task=tid).execute()
            log.write(json.dumps({"id": tid, "list": list_id, "title": title}, ensure_ascii=False) + "\n")
            print(f"\r{i}/{len(ids)}", end="", file=sys.stderr)
    print("\ndone")


if __name__ == "__main__":
    main()
