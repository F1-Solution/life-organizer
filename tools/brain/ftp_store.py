"""Upload originals to the home FTP server over explicit TLS, under /second-brain/<fonte>/<anno>/ (no deletes)."""
from __future__ import annotations

import ftplib
import os
from pathlib import Path

HOST = "ftpwin.alessioekatya.it"
BASE = "/second-brain"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value and os.name == "nt":
        import winreg  # User variables set after the shell started are only in the registry.

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, name)[0]
    if not value:
        raise SystemExit(f"Missing environment variable {name}.")
    return value


class FtpStore:
    def __init__(self) -> None:
        self.ftp = ftplib.FTP_TLS(HOST, timeout=120)
        self.ftp.auth()
        self.ftp.login(_env("FTP_AK_USERNAME"), _env("FTP_AK_PASSWORD"))
        self.ftp.prot_p()

    def _ensure_dir(self, path: str) -> None:
        current = ""
        for part in path.strip("/").split("/"):
            current += "/" + part
            try:
                self.ftp.mkd(current)
            except ftplib.error_perm:
                pass  # Already exists.

    def size(self, remote: str) -> int | None:
        try:
            self.ftp.voidcmd("TYPE I")
            return self.ftp.size(remote)
        except ftplib.error_perm:
            return None

    def upload(self, local: Path, fonte: str, anno: str, name: str | None = None) -> str:
        folder = f"{BASE}/{fonte}/{anno}"
        remote = f"{folder}/{name or local.name}"
        if self.size(remote) == local.stat().st_size:
            return remote
        self._ensure_dir(folder)
        with local.open("rb") as fh:
            self.ftp.storbinary(f"STOR {remote}", fh, blocksize=1024 * 1024)
        if self.size(remote) != local.stat().st_size:
            raise RuntimeError(f"Size mismatch after upload: {remote}")
        return remote

    def close(self) -> None:
        try:
            self.ftp.quit()
        except ftplib.all_errors:
            self.ftp.close()
