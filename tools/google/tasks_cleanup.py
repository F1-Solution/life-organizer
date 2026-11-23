# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2", "google-auth>=2", "openpyxl>=3"]
# ///
"""Delete the Google Tasks whose every link already has an analysed Scheda in the vault; --dry-run only lists them."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from googleapiclient.discovery import build

from tasks_delete import delete, load_credentials, task_lists

ROOT = Path(__file__).resolve().parents[2]


def scheda_states(vault: Path) -> dict[str, str]:
    """Map catalog id to the stato written in its Scheda."""
    out = {}
    for f in (vault / "Risorse").glob("*.md"):
        fm = f.read_text(encoding="utf-8").split("---")[1]
        sid, stato = re.search(r'^id: "?(\w+)"?$', fm, re.M), re.search(r"^stato: (\S+)", fm, re.M)
        if sid and stato:
            out[sid.group(1)] = stato.group(1)
    return out


def handled_tasks(catalog: Path, states: dict[str, str]) -> set[str]:
    """Task ids whose catalog items are all analysed."""
    items = defaultdict(list)
    for line in catalog.open(encoding="utf-8"):
        item = json.loads(line)
        for c in item["contesti"]:
            if isinstance(c, dict) and c.get("fonte") == "google-tasks" and c.get("ref"):
                items[c["ref"]].append(item["id"])
    return {ref for ref, ids in items.items() if all(states.get(i) == "analizzata" for i in ids)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", type=Path, default=ROOT / "data" / "brain" / "catalog.jsonl")
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--tasks", type=Path, default=ROOT / "data" / "google" / "tasks.ndjson")
    p.add_argument("--log", type=Path, default=ROOT / "data" / "google" / "tasks-cancellati.jsonl")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    lists = task_lists(a.tasks)
    done = {json.loads(line)["id"] for line in a.log.open(encoding="utf-8")} if a.log.exists() else set()
    todo = sorted(t for t in handled_tasks(a.catalog, scheda_states(a.vault)) - done if t in lists)
    print(f"{len(todo)} tasks handled in the second brain")
    if a.dry_run:
        for tid in todo:
            print(f"  {lists[tid][1][:80]}")
        return
    svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)
    with a.log.open("a", encoding="utf-8") as log:
        for i, tid in enumerate(todo, 1):
            list_id, title = lists[tid]
            delete(svc, list_id, tid)
            log.write(json.dumps({"id": tid, "list": list_id, "title": title, "motivo": "gestito"}, ensure_ascii=False) + "\n")
            print(f"\r{i}/{len(todo)}", end="", file=sys.stderr)
    print("\ndone")


if __name__ == "__main__":
    main()
