# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["yt-dlp[default]", "curl_cffi", "gallery-dl", "trafilatura>=1.12", "faster-whisper>=1.0", "rapidocr-onnxruntime>=1.3",
#                 "pypdf>=4", "pillow>=10", "playwright>=1.48", "requests>=2"]
# ///
"""Phase 3, step 1: download each catalog item, extract its text (article, README, transcript, OCR), upload originals to FTP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ftp_store import FtpStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "vault" / "_estratti"
IG_DIR = Path(os.environ["USERPROFILE"]) / ".config" / "instagram-reader"
COOKIES = IG_DIR / "cookies.txt"
STAGE = Path(os.environ["USERPROFILE"]) / "second-brain-originali"  # Holds originals while no private FTP folder exists.
VIDEO = {".mp4", ".webm", ".mkv", ".mov", ".m4a", ".mp3", ".opus", ".ogg", ".wav"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
LOGIN_WALL = {"linkedin.com", "threads.com", "threads.net", "x.com", "twitter.com", "facebook.com"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"}
_whisper = None
_ocr = None


def export_cookies() -> None:
    """Write the Instagram session cookies of the dedicated Edge profile as a Netscape cookies.txt for gallery-dl/yt-dlp."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(IG_DIR / "profile"), channel="msedge", headless=True)
        cookies = ctx.cookies()
        ctx.close()
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        dom = c["domain"]
        lines.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c["path"],
                                "TRUE" if c["secure"] else "FALSE", str(int(max(c.get("expires", 0), 0))), c["name"], c["value"]]))
    COOKIES.write_text("\n".join(lines) + "\n", encoding="utf-8")


def transcribe(path: Path) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    import numpy as np

    # Decoding with ffmpeg avoids the PyAV build that faster-whisper pins, which rejects its own arguments.
    run = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True)
    pcm = run.stdout
    if run.returncode or not pcm:  # Silent clips have no audio stream to decode.
        return ""
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    segments, _ = _whisper.transcribe(audio, vad_filter=True)
    return " ".join(s.text.strip() for s in segments)


def ocr(path: Path) -> str:
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr = RapidOCR()
    result, _ = _ocr(str(path))
    return "\n".join(r[1] for r in result or [])


def thumbnail(src: Path, dest: Path) -> None:
    from PIL import Image

    if src.suffix.lower() in VIDEO:
        frame = dest.with_suffix(".png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(src), "-frames:v", "1", str(frame)], check=False)
        if not frame.exists():
            return
        src = frame
    with Image.open(src) as im:
        im.thumbnail((320, 320))
        im.convert("RGB").save(dest, "JPEG", quality=70)
    if src.suffix == ".png" and src.parent == dest.parent:
        src.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def media_text(files: list[Path], meta: dict) -> list[str]:
    """Transcribe audio/video and OCR images; returns the text parts in order."""
    parts = []
    for f in files:
        ext = f.suffix.lower()
        if ext in VIDEO:
            text = transcribe(f)
            parts.append(f"## Trascrizione ({f.name})\n\n{text}")
        elif ext in IMAGE:
            text = ocr(f)
            if text.strip():
                parts.append(f"## OCR ({f.name})\n\n{text}")
    meta["media"] = [f.name for f in files]
    return parts


def handle_instagram(url: str, work: Path, meta: dict) -> list[str]:
    subprocess.run(["gallery-dl", "--cookies", str(COOKIES), "--write-metadata", "-D", str(work), url],
                   capture_output=True, text=True, timeout=600)
    info = sorted(work.glob("*.json"))
    if info:
        d = json.loads(info[0].read_text(encoding="utf-8"))
        meta.update(title=(d.get("description") or "")[:120], author=d.get("username") or d.get("fullname"),
                    published=str(d.get("post_date") or d.get("date") or "")[:10], caption=d.get("description"))
    files = sorted(f for f in work.iterdir() if f.suffix.lower() in VIDEO | IMAGE)
    if not files:
        raise RuntimeError("gallery-dl non ha scaricato nulla (post privato, rimosso o cookie scaduti)")
    return ([f"## Didascalia\n\n{meta['caption']}"] if meta.get("caption") else []) + media_text(files, meta)


def handle_youtube(url: str, work: Path, meta: dict) -> list[str]:
    base = ["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--write-info-json", "--write-auto-subs", "--write-subs", "--sub-langs", "it,en,en-orig",
            "--sub-format", "vtt", "-o", str(work / "%(id)s.%(ext)s")]
    probe = subprocess.run(["yt-dlp", "--js-runtimes", "node", "-j", "--no-playlist", url], capture_output=True, text=True)
    if probe.returncode:
        raise RuntimeError(probe.stderr.strip()[-400:])
    info = json.loads(probe.stdout)
    fmt = (["-f", "bestaudio[ext=m4a]/bestaudio"] if (info.get("duration") or 0) > 3600
           else ["-f", "bv*+ba/b", "-S", "res:720,ext:mp4:m4a", "--merge-output-format", "mp4"])  # res uses the short side, so Shorts work.
    run = subprocess.run(base + fmt + ["--ignore-errors", url], capture_output=True, text=True, timeout=3600)
    if not any(f.suffix.lower() in VIDEO for f in work.iterdir()):  # Subtitle failures alone must not sink the item.
        raise RuntimeError(run.stderr.strip()[-400:])
    meta.update(title=info.get("title"), author=info.get("channel"), published=(info.get("upload_date") or "")[:8],
                duration_s=info.get("duration"), description=info.get("description"))
    parts = [f"## Descrizione\n\n{info.get('description') or ''}"]
    subs = sorted(work.glob("*.vtt"))
    if subs:
        lines = [l for l in subs[0].read_text(encoding="utf-8").splitlines()
                 if l and "-->" not in l and not l.startswith(("WEBVTT", "Kind:", "Language:")) and not l.strip().isdigit()]
        parts.append("## Sottotitoli\n\n" + " ".join(dict.fromkeys(lines)))
        meta["media"] = [f.name for f in work.iterdir() if f.suffix.lower() in VIDEO]
    else:
        parts += media_text([f for f in work.iterdir() if f.suffix.lower() in VIDEO], meta)
    return parts


def handle_github(url: str, work: Path, meta: dict) -> list[str]:
    owner, repo = urlsplit(url).path.strip("/").split("/")[:2]
    info = json.loads(subprocess.run(["gh", "api", f"repos/{owner}/{repo}"], capture_output=True, text=True, check=True).stdout)
    readme = subprocess.run(["gh", "api", f"repos/{owner}/{repo}/readme", "-H", "Accept: application/vnd.github.raw"],
                            capture_output=True, text=True, encoding="utf-8").stdout
    meta.update(title=f"{owner}/{repo}", author=owner, description=info.get("description"), stars=info.get("stargazers_count"),
                topics=info.get("topics"), published=(info.get("created_at") or "")[:10], updated=(info.get("pushed_at") or "")[:10])
    (work / "README.md").write_text(readme, encoding="utf-8")
    return [f"## Descrizione\n\n{info.get('description') or ''}", f"## README\n\n{readme[:60000]}"]


def render(url: str, work: Path, meta: dict) -> list[str]:
    """Open the page in the dedicated Edge profile (logged-in sessions) and keep its visible text."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(IG_DIR / "profile"), channel="msedge", headless=True)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        text = page.evaluate("() => (document.querySelector('article') || document.querySelector('main') || document.body).innerText")
        meta.update(final_url=page.url, title=meta.get("title") or page.title())
        (work / "pagina.html").write_text(page.content(), encoding="utf-8")
        ctx.close()
    meta["resa_browser"] = True
    if len(text) < 300:
        meta["avviso"] = "testo breve anche nel browser: serve login o contenuto rimosso"
    else:
        meta.pop("avviso", None)
    return [f"## Testo (pagina resa nel browser)\n\n{text[:60000]}"]


def handle_web(url: str, work: Path, meta: dict) -> list[str]:
    try:
        parts = fetch_web(url, work, meta)
    except requests.RequestException:
        return render(url, work, meta)
    return render(meta.get("final_url") or url, work, meta) if meta.get("avviso") else parts


def fetch_web(url: str, work: Path, meta: dict) -> list[str]:
    import trafilatura

    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    meta["final_url"] = resp.url
    (work / "pagina.html").write_text(resp.text, encoding="utf-8")
    doc = trafilatura.bare_extraction(resp.text, url=resp.url, with_metadata=True)
    doc = doc.as_dict() if hasattr(doc, "as_dict") else (doc or {})
    text = trafilatura.extract(resp.text, url=resp.url, output_format="markdown") or ""
    meta.update(title=doc.get("title"), author=doc.get("author"), published=doc.get("date"), description=doc.get("description"))
    if len(text) < 300:
        meta["avviso"] = "testo breve: pagina dinamica o dietro login"
    return [f"## Testo\n\n{text}"]


def handle_file(path: Path, work: Path, meta: dict) -> list[str]:
    local = work / path.name
    shutil.copy2(path, local)
    meta.update(title=path.name)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return ["## Testo PDF\n\n" + "\n".join((p.extract_text() or "") for p in PdfReader(local).pages)]
    if path.suffix.lower() in {".md", ".txt"}:
        return ["## Testo\n\n" + local.read_text(encoding="utf-8", errors="replace")]
    return media_text([local], meta)


def resolve(url: str) -> str:
    try:
        return requests.head(url, headers=UA, allow_redirects=True, timeout=30).url
    except requests.RequestException:
        return url


def dispatch(item: dict, work: Path, meta: dict) -> list[str]:
    if not item["url"]:
        src = next(s for s in item["contesti"] if s.get("path"))
        meta["kind"] = "file"
        return handle_file(ROOT / src["path"], work, meta)
    url = item["url"]
    if urlsplit(url).netloc in {"t.co", "vm.tiktok.com", "share.google", "maps.app.goo.gl", "tr.ee", "bit.ly"}:
        url = meta["final_url"] = resolve(url)
    host = urlsplit(url).netloc.removeprefix("www.")
    if host == "instagram.com":
        meta["kind"] = "instagram"
        return handle_instagram(url, work, meta)
    if host in {"youtube.com", "youtu.be", "m.youtube.com"}:
        meta["kind"] = "video"
        return handle_youtube(url, work, meta)
    if host == "github.com" and len(urlsplit(url).path.strip("/").split("/")) >= 2:
        meta["kind"] = "repo"
        return handle_github(url, work, meta)
    meta["kind"] = "social" if host in LOGIN_WALL else "articolo"
    return handle_web(url, work, meta)


def upload_originals(work: Path, item: dict, meta: dict, store: FtpStore | None) -> None:
    fonte = item["fonti"][0].replace("-file", "").replace("-dm", "")
    anno = (item.get("prima_data") or str(date.today()))[:4]
    originals = [f for f in work.iterdir() if f.is_file() and f.suffix.lower() in VIDEO | IMAGE | {".pdf", ".html", ".docx", ".zip"}]
    meta["ftp"], meta["hash"] = [], {}
    for f in originals:
        meta["hash"][f.name] = sha256(f)
        if store:
            meta["ftp"].append(store.upload(f, fonte, anno, f"{item['id']}-{f.name}"))
        else:
            local = STAGE / fonte / anno / f"{item['id']}-{f.name}"
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, local)
            meta.setdefault("locale", []).append(str(local))


def process(item: dict, store: FtpStore | None) -> dict:
    dest = OUT / item["id"]
    dest.mkdir(parents=True, exist_ok=True)
    meta = {"id": item["id"], "url": item["url"], "fonti": item["fonti"], "prima_data": item["prima_data"],
            "contesti": [c.get("contesto", "") for c in item["contesti"]], "data_analisi": str(date.today())}
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = Path(tmp)
        try:
            parts = dispatch(item, work, meta)
            (dest / "testo.md").write_text("\n\n".join(parts), encoding="utf-8")
            media = [f for f in sorted(work.iterdir()) if f.suffix.lower() in VIDEO | IMAGE]
            if media:
                thumbnail(media[0], dest / "miniatura.jpg")
            upload_originals(work, item, meta, store)
            meta["stato"] = "estratta"
        except Exception as exc:  # One broken link must not stop the batch.
            meta.update(stato="errore", errore=f"{type(exc).__name__}: {exc}"[:500])
            (dest / "errore.txt").write_text(traceback.format_exc(), encoding="utf-8")
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", type=Path, default=ROOT / "data" / "brain" / "catalog.jsonl")
    p.add_argument("--ids", type=Path, required=True, help="JSON list of catalog ids to process")
    p.add_argument("--no-ftp", action="store_true")
    p.add_argument("--redo", action="store_true", help="process items already extracted")
    a = p.parse_args()
    wanted = json.loads(a.ids.read_text(encoding="utf-8"))
    items = {c["id"]: c for c in map(json.loads, a.catalog.open(encoding="utf-8")) if c["id"] in wanted}
    if any(c["url"] and "instagram.com" in c["url"] for c in items.values()):
        export_cookies()
    store = None if a.no_ftp else FtpStore()
    try:
        for i, cid in enumerate(wanted, 1):
            done = OUT / cid / "meta.json"
            if not a.redo and done.exists() and json.loads(done.read_text(encoding="utf-8")).get("stato") == "estratta":
                continue
            if store:
                store.close()
                store = FtpStore()  # Fresh connection per item: downloads and transcription outlast the FTP idle timeout.
            meta = process(items[cid], store)
            print(f"[{i}/{len(wanted)}] {cid} {meta.get('kind')} {meta['stato']} {meta.get('errore', '')[:120]}", flush=True)
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()
