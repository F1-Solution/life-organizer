# /// script
# requires-python = ">=3.10"
# dependencies = ["google-api-python-client>=2", "google-auth>=2", "openpyxl>=3"]
# ///
"""Move the to-do tasks of an approved plan into the "Da fare" list without due date, and turn idea tasks into Idee.md in the vault; --dry-run only lists them."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from googleapiclient.discovery import build

from tasks_delete import delete, load_credentials

ROOT = Path(__file__).resolve().parents[2]
VAULT = Path(os.environ.get("BRAIN_VAULT", "C:/ObsidianVault"))  # The Obsidian vault lives outside this repo.
LIST_NAME = "Da fare"


def todo_list(svc) -> str:  # noqa: ANN001
    for tl in svc.tasklists().list(maxResults=100).execute().get("items", []):
        if tl["title"] == LIST_NAME:
            return tl["id"]
    return svc.tasklists().insert(body={"title": LIST_NAME}).execute()["id"]


def write_ideas(ideas: list[dict], path: Path) -> None:
    """Append the ideas to the note, grouped by section, as unchecked boxes."""
    text = path.read_text(encoding="utf-8") if path.exists() else "# Idee\n\nIdee di progetto e cose da vedere, spostate da Google Tasks.\n"
    for section in dict.fromkeys(i["sezione"] for i in ideas):
        lines = [f"- [ ] {i['title']}" + (f" — {i['notes'].strip()}" if i.get("notes") else "")
                 for i in ideas if i["sezione"] == section and f"- [ ] {i['title']}" not in text]
        if lines:
            text += f"\n## {section}\n\n" + "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, default=ROOT / "data" / "google" / "todo-piano.json")
    p.add_argument("--ideas", type=Path, default=VAULT / "Idee.md")
    p.add_argument("--log", type=Path, default=ROOT / "data" / "google" / "tasks-spostati.jsonl")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    plan = json.loads(a.plan.read_text(encoding="utf-8"))
    done = {json.loads(line)["id"] for line in a.log.open(encoding="utf-8")} if a.log.exists() else set()
    todo = [t for t in plan["todo"] if t["id"] not in done]
    ideas = [t for t in plan["idee"] if t["id"] not in done]
    print(f"{len(todo)} to-dos to move to '{LIST_NAME}', {len(ideas)} ideas to {a.ideas.name}")
    if a.dry_run:
        for t in todo + ideas:
            print(f"  {t.get('sezione', 'da fare')}: {t['title'][:80]}")
        return
    svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)
    dest = todo_list(svc)
    with a.log.open("a", encoding="utf-8") as log:
        for t in todo:
            moved = svc.tasks().move(tasklist=t["list"], task=t["id"], destinationTasklist=dest).execute()
            svc.tasks().patch(tasklist=dest, task=moved["id"], body={"due": None}).execute()
            log.write(json.dumps({"id": t["id"], "nuovo_id": moved["id"], "title": t["title"], "azione": "da-fare"}, ensure_ascii=False) + "\n")
        write_ideas(ideas, a.ideas)  # The note is written before the tasks go, so nothing is lost.
        for t in ideas:
            delete(svc, t["list"], t["id"])
            log.write(json.dumps({"id": t["id"], "title": t["title"], "azione": "idea", "sezione": t["sezione"]}, ensure_ascii=False) + "\n")
    print("done")


if __name__ == "__main__":
    main()
