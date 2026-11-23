# /// script
# requires-python = ">=3.10"
# ///
"""List the Outlook daily series that can be deleted: created by the user, without attendees, with at least one link in subject or body, and every link has an analysed Scheda."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "brain"))
from collect_links import URL_RE, normalize  # noqa: E402


def analysed_urls(catalog: Path, vault: Path) -> set[str]:
    """Normalized catalog URLs whose Scheda says stato: analizzata."""
    states = {}
    for f in (vault / "Risorse").glob("*.md"):
        fm = f.read_text(encoding="utf-8").split("---")[1]
        sid, stato = re.search(r'^id: "?(\w+)"?$', fm, re.M), re.search(r"^stato: (\S+)", fm, re.M)
        if sid and stato:
            states[sid.group(1)] = stato.group(1)
    out = set()
    for line in catalog.open(encoding="utf-8"):
        item = json.loads(line)
        if item.get("url") and states.get(item["id"]) == "analizzata":
            out.add(item["url"])
    return out


def eligible(ev: dict, done: set[str]) -> tuple[bool, str]:
    if ev["entry_id"] in done:
        return False, "già cancellata"
    if not ev.get("mine") or ev.get("recipients", 99) > 1:
        return False, "non tua o con partecipanti"
    return True, ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--export", type=Path, required=True, help="JSON from outlook_daily.ps1")
    p.add_argument("--catalog", type=Path, default=ROOT / "data" / "brain" / "catalog.jsonl")
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--log", type=Path, default=ROOT / "data" / "outlook" / "eventi-cancellati.jsonl")
    p.add_argument("--out", type=Path, required=True, help="plan JSON for outlook_cleanup.ps1")
    a = p.parse_args()
    ok_urls = analysed_urls(a.catalog, a.vault)
    done = {json.loads(line)["entry_id"] for line in a.log.open(encoding="utf-8")} if a.log.exists() else set()
    plan, skipped = [], {}
    for ev in json.loads(a.export.read_text(encoding="utf-8-sig")):
        good, why = eligible(ev, done)
        urls = [normalize(u) for u in URL_RE.findall(f"{ev['subject']}\n{ev.get('body') or ''}")]
        if good and not urls:
            good, why = False, "nessun link"
        elif good and not all(u in ok_urls for u in urls):
            good, why = False, "link senza Scheda analizzata"
        if good:
            plan.append({"entry_id": ev["entry_id"], "subject": ev["subject"], "urls": urls, "stato": "analizzata"})
        else:
            skipped[why] = skipped.get(why, 0) + 1
    a.out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(plan)} series to delete -> {a.out}; skipped: {skipped}")
    for e in plan:
        print(f"  {e['subject'][:90]}")


if __name__ == "__main__":
    main()
