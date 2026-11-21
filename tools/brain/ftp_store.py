"""Upload originals to the home FTP server over explicit TLS, under /second-brain/<fonte>/<anno>/ (no deletes)."""
from __future__ import annotations

import ftplib
import io
import os
import urllib.error
import urllib.request
from pathlib import Path

HOST = "ftpwin.alessioekatya.it"
BASE = "/alessioekatya.it/second-brain"
# The folder sits under the web root: this IIS rule refuses every file over HTTP so originals stay FTP-only.
WEB_CONFIG = b"""<?xml version="1.0" encoding="UTF-8"?>
<configuration><system.webServer><security><requestFiltering>
<fileExtensions allowUnlisted="false" />
</requestFiltering></security><directoryBrowse enabled="false" /></system.webServer></configuration>
"""


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value and os.name == "nt":
        import winreg  # User variables set after the shell started are only in the registry.

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, name)[0]
    if not value:
        raise SystemExit(f"Missing environment variable {name}.")
    return value


PROBE = "probe-accesso-web.txt"
PROBE_URL = f"https://www.alessioekatya.it/second-brain/{PROBE}"


def _http_status(url: str) -> int:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30).status
    except urllib.error.HTTPError as exc:
        return exc.code


class _IisFtpTls(ftplib.FTP_TLS):
    """IIS resets TLS data connections instead of sending close_notify, so skip the unwrap that ftplib does."""

    def storbinary(self, cmd, fp, blocksize=1 << 20, callback=None, rest=None):  # noqa: ANN001, ANN201
        self.voidcmd("TYPE I")
        with self.transfercmd(cmd, rest) as conn:
            while buf := fp.read(blocksize):
                conn.sendall(buf)
        return self.voidresp()

    def retrlines(self, cmd, callback=None):  # noqa: ANN001, ANN201
        self.sendcmd("TYPE A")
        with self.transfercmd(cmd) as conn, conn.makefile("r", encoding=self.encoding) as fp:
            for line in fp:
                (callback or print)(line.rstrip("\r\n"))
        return self.voidresp()


class FtpStore:
    def __init__(self) -> None:
        self.ftp = _IisFtpTls(HOST, timeout=120)
        self.ftp.auth()
        self.ftp.login(_env("FTP_AK_USERNAME"), _env("FTP_AK_PASSWORD"))
        self.ftp.prot_p()
        self._protect()

    def _protect(self) -> None:

        self._ensure_dir(BASE)
        current = io.BytesIO()
        try:
            self.ftp.retrbinary(f"RETR {BASE}/web.config", current.write)
        except ftplib.error_perm:
            pass
        if current.getvalue() != WEB_CONFIG:
            self.ftp.storbinary(f"STOR {BASE}/web.config", io.BytesIO(WEB_CONFIG))
        if self.size(f"{BASE}/{PROBE}") is None:
            self.ftp.storbinary(f"STOR {BASE}/{PROBE}", io.BytesIO(b"probe"))
        # Fail closed: refuse to upload unless the web server demonstrably hides the folder.
        status = _http_status(PROBE_URL)
        if status not in (401, 403, 404):
            self.close()
            raise SystemExit(f"{PROBE_URL} answered {status}: the folder is reachable from the web, upload refused.")

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
        partial = self.size(remote) or 0
        offset = partial if partial < local.stat().st_size else 0  # Resume an interrupted upload with REST.
        with local.open("rb") as fh:
            fh.seek(offset)
            self.ftp.storbinary(f"STOR {remote}", fh, blocksize=1024 * 1024, rest=offset or None)
        if self.size(remote) != local.stat().st_size:
            raise RuntimeError(f"Size mismatch after upload: {remote}")
        return remote

    def close(self) -> None:
        try:
            self.ftp.quit()
        except ftplib.all_errors:
            self.ftp.close()
