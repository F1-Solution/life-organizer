"""Move originals held locally by extract.py --no-ftp onto the FTP and record their paths in each meta.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ftp_store import FtpStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    for meta_file in sorted((ROOT / "vault" / "_estratti").glob("*/meta.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        locals_ = [Path(p) for p in meta.get("locale", []) if Path(p).exists()]
        if not locals_:
            continue
        store = FtpStore()  # One connection per item keeps long runs clear of the server's idle timeout.
        try:
            for f in locals_:
                fonte, anno = f.parent.parent.name, f.parent.name
                remote = store.upload(f, fonte, anno)
                meta.setdefault("ftp", [])
                if remote not in meta["ftp"]:
                    meta["ftp"].append(remote)
                f.unlink()
        finally:
            store.close()
        meta.pop("locale", None)
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{meta['id']}: {len(locals_)} file", flush=True)


if __name__ == "__main__":
    main()
