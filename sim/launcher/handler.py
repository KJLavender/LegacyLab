"""legacyapp:// 協定處理程式（仿舊系統常見的 VBS 啟動腳本）。

檢查 URL 格式與功能代碼後，帶著 URL 啟動 LegacyApp，並把子行程 PID 印到 stdout。
token 的真偽由 LegacyApp 自己驗證（和真系統一樣），這裡只擋明顯不合法的輸入。

    python sim/launcher/handler.py "legacyapp://launch?token=...&func=CHART"
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_FUNCS = {"CHART"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def parse(url: str) -> dict[str, str]:
    u = urlparse(url)
    if u.scheme != "legacyapp" or u.netloc != "launch":
        raise ValueError(f"not a legacyapp launch URL: {url!r}")
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if q.get("func") not in ALLOWED_FUNCS:
        raise ValueError(f"function not allowed: {q.get('func')!r}")
    if not TOKEN_RE.match(q.get("token", "")):
        raise ValueError("malformed token")
    return q


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: handler.py <legacyapp://launch?...>", file=sys.stderr)
        return 2
    try:
        parse(argv[1])
    except ValueError as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 1
    exe = Path(os.environ.get("LEGACYLAB_EXE", ROOT / "sim/legacyapp/bin/LegacyApp.exe"))
    args = [str(exe), argv[1]]
    if os.environ.get("LEGACYLAB_DATA"):
        args += ["--data", os.environ["LEGACYLAB_DATA"]]
    proc = subprocess.Popen(args, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    print(proc.pid, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
