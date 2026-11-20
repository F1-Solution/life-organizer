# /// script
# requires-python = ">=3.10"
# ///
"""Phase 1: collect links and notes from every saved source into one de-duplicated catalog (read-only on sources)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.IGNORECASE)
TRAILING = ".,;:!?*»”’"
TRACKING = re.compile(r"^(utm_.*|igsh|igshid|si|is|fbclid|gclid|mibextid|ref_src|ref_url|rcm|trk|lipi|feature|s|t|.*token.*|r|triedRedirect)$")
SENSITIVE = re.compile(r"password|passw|pwd|\bpin\b|credenziali|utente\s*:|user(name)?\s*:|login\s*:", re.IGNORECASE)
PORN = re.compile(r"porn|xvideos|xnxx|xhamster|redtube|youporn|spankbang|eporner|onlyfans|brazzers|chaturbate|xxx", re.IGNORECASE)
WA_LINE = re.compile(r"^(\d{2}/\d{2}/\d{2}), (\d{2}:\d{2}) - ([^:]+): (.*)$")


@dataclass
class Item:
    key: str
    url: str | None
    sources: list[dict] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)


def normalize(url: str) -> str:
    url = url.rstrip(TRAILING)
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/") or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)]
    if host == "youtu.be":
        host, query, path = "youtube.com", [("v", path.strip("/"))], "/watch"
    if host in ("instagram.com", "threads.net", "threads.com", "linkedin.com", "tiktok.com", "github.com"):
        query = []  # Share links only add tracking to these hosts.
    return urlunsplit(("https", host, path, urlencode(query), ""))


class Catalog:
    def __init__(self) -> None:
        self.items: dict[str, Item] = {}

    def add(self, url: str | None, source: dict, note_key: str | None = None) -> None:
        key = normalize(url) if url else f"nota:{note_key}"
        item = self.items.setdefault(key, Item(key=key, url=key if url else None))
        item.sources.append(source)
        if url and PORN.search(url):
            item.flags.add("scarto-porno")
        if SENSITIVE.search(source.get("contesto", "")):
            item.flags.add("credenziali-omesse")
            source["contesto"] = "[omesso: possibili credenziali]"

    def add_text(self, text: str, source: dict) -> int:
        urls = URL_RE.findall(text)
        context = URL_RE.sub("", text).strip()[:300]
        for u in urls:
            self.add(u, {**source, "contesto": context})
        return len(urls)


def read_whatsapp(cat: Catalog, chat: Path) -> None:
    msgs, cur = [], None
    for line in chat.read_text(encoding="utf-8").splitlines():
        m = WA_LINE.match(line)
        if m:
            cur = {"data": datetime.strptime(m[1], "%d/%m/%y").date().isoformat(), "text": m[4]}
            msgs.append(cur)
        elif cur:
            cur["text"] += "\n" + line
    for msg in msgs:
        cat.add_text(msg["text"], {"fonte": "whatsapp", "data": msg["data"]})
    for f in sorted(chat.parent.iterdir()):
        if f != chat and f.is_file():
            cat.add(None, {"fonte": "whatsapp-file", "data": None, "contesto": f.name, "path": str(f.resolve().relative_to(ROOT))}, note_key=f"wa/{f.name}")


def read_telegram(cat: Catalog, jsonl: Path, docs_csv: Path) -> None:
    rows = []
    for line in jsonl.open(encoding="utf-8"):
        r = json.loads(line)
        src = {"fonte": "telegram", "data": r["date"][:10], "ref": r["id"]}
        text = r.get("text") or ""
        n = cat.add_text(text, src)
        for u in r.get("urls") or []:
            if u not in text:
                cat.add(u, {**src, "contesto": URL_RE.sub("", text).strip()[:300]})
        if r.get("media") == "document":
            rows.append([r["id"], r["date"][:10], r.get("file_name") or "", r.get("mime_type") or "",
                         round((r.get("size") or 0) / 1e6, 1), text.replace("\n", " ")[:150], ""])
        elif r.get("media") == "photo" and not n:
            cat.add(None, {**src, "contesto": text[:300] or "foto senza testo"}, note_key=f"tg/{r['id']}")
    with docs_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["id", "data", "nome_file", "tipo", "MB", "didascalia", "tenere (s/n)"])
        w.writerows(sorted(rows, key=lambda x: (x[3], x[2])))


def read_tasks(cat: Catalog, ndjson: Path, todo_csv: Path) -> None:
    todo = []
    for line in ndjson.open(encoding="utf-8"):
        for t in json.loads(line).get("items", []):
            if t.get("status") != "needsAction":
                continue
            text = f"{t.get('title', '')}\n{t.get('notes', '')}".strip()
            src = {"fonte": "google-tasks", "data": (t.get("updated") or "")[:10], "ref": t["id"]}
            if not cat.add_text(text, src):
                todo.append([t["id"], t.get("title", ""), (t.get("notes") or "").replace("\n", " ")[:200], ""])
    with todo_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["id", "titolo", "note", "tipo (da-fare / appunto / scarta)"])
        w.writerows(todo)


def read_outlook(cat: Catalog, daily_json: Path, exclude: set[str]) -> None:
    for ev in json.loads(daily_json.read_text(encoding="utf-8-sig")):
        if ev["subject"] in exclude:
            continue
        text = f"{ev['subject']}\n{ev.get('body') or ''}"
        src = {"fonte": "outlook", "data": ev["series_from"]}
        if not cat.add_text(text, src):
            cat.add(None, {**src, "contesto": ev["subject"]}, note_key=f"outlook/{ev['subject']}")


def read_instagram(cat: Catalog, jsonl: Path) -> None:
    for line in jsonl.open(encoding="utf-8"):
        r = json.loads(line)
        for u in r.get("urls", []):
            cat.add(u, {"fonte": "instagram-dm", "data": r["letto_il"][:10], "contesto": r["name"], "ref": r.get("thread_url")})


def write_catalog(cat: Catalog, out: Path) -> Counter:
    domains: Counter = Counter()
    with out.open("w", encoding="utf-8") as fh:
        for it in cat.items.values():
            domain = urlsplit(it.url).netloc if it.url else "(nota)"
            domains[domain] += 1
            dates = sorted(s["data"] for s in it.sources if s.get("data"))
            rec = {"id": hashlib.sha1(it.key.encode()).hexdigest()[:12], "url": it.url, "dominio": domain,
                   "fonti": sorted({s["fonte"] for s in it.sources}), "prima_data": dates[0] if dates else None,
                   "contesti": [s for s in it.sources][:5], "flag": sorted(it.flags), "stato": "nuova"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return domains


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--whatsapp", type=Path, required=True, help="exported chat .txt (media files beside it)")
    p.add_argument("--telegram", type=Path, required=True, help="messages.jsonl from tg_read.py")
    p.add_argument("--tasks", type=Path, required=True, help="tasks.ndjson from gws")
    p.add_argument("--outlook", type=Path, required=True, help="JSON from outlook_daily.ps1")
    p.add_argument("--instagram", type=Path, help="dm-links.jsonl from ig_lot.py")
    p.add_argument("--exclude-event", action="append", default=[], help="Outlook series to skip (e.g. work meetings)")
    p.add_argument("--out", type=Path, required=True, help="catalog JSONL")
    p.add_argument("--report-dir", type=Path, required=True)
    p.add_argument("--prefix", default=datetime.now().strftime("%Y-%m-%d"))
    a = p.parse_args()
    cat = Catalog()
    read_whatsapp(cat, a.whatsapp)
    read_telegram(cat, a.telegram, a.report_dir / f"{a.prefix}-telegram-documenti.csv")
    read_tasks(cat, a.tasks, a.report_dir / f"{a.prefix}-tasks-senza-link.csv")
    read_outlook(cat, a.outlook, set(a.exclude_event))
    if a.instagram:
        read_instagram(cat, a.instagram)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    domains = write_catalog(cat, a.out)
    flags = Counter(f for it in cat.items.values() for f in it.flags)
    multi = sum(1 for it in cat.items.values() if len({s["fonte"] for s in it.sources}) > 1)
    print(f"{len(cat.items)} items ({multi} in more than one source); flags {dict(flags)}")
    print("top domains:", domains.most_common(25))


if __name__ == "__main__":
    main()
