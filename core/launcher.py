"""透過入口網站啟動舊系統：登入 → 點功能 → 拿到協定 URL → 交給協定處理程式。

入口網址、功能代碼、協定、處理程式都來自設定，換一個系統只改設定：

    {"portal_url": "http://127.0.0.1:8765", "func": "CHART", "scheme": "legacyapp",
     "user": "demo", "password": "...", "handler": ["python", "sim/launcher/handler.py"]}

handler 省略時用 os.startfile（需要協定已註冊在 HKCU，和使用者在瀏覽器點連結一樣）。
"""
from __future__ import annotations

import http.cookiejar
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class LaunchResult:
    url: str
    pid: int | None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # 讓 302 變成 HTTPError，才能讀到自訂協定的 Location


def get_launch_url(cfg: dict) -> str:
    base = cfg["portal_url"].rstrip("/")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode({"user": cfg["user"], "password": cfg["password"]}).encode()
    try:
        opener.open(f"{base}/login", data=body, timeout=10)
    except urllib.error.HTTPError as e:
        raise PermissionError(f"portal login failed: HTTP {e.code}") from e
    no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)
    try:
        no_redirect.open(f"{base}/launch?func={urllib.parse.quote(cfg['func'])}", timeout=10)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        if e.code in (301, 302, 303, 307) and loc.startswith(cfg.get("scheme", "legacyapp") + ":"):
            return loc
        raise RuntimeError(f"portal launch failed: HTTP {e.code} {loc!r}") from e
    raise RuntimeError("portal did not redirect to the app protocol")


def launch(cfg: dict, env: dict | None = None) -> LaunchResult:
    url = get_launch_url(cfg)
    handler = cfg.get("handler")
    if not handler:
        os.startfile(url)  # type: ignore[attr-defined]  # Windows only
        return LaunchResult(url, None)
    out = subprocess.run([*handler, url], capture_output=True, text=True, env=env, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"protocol handler rejected launch: {out.stderr.strip()}")
    return LaunchResult(url, int(out.stdout.strip().splitlines()[-1]))
