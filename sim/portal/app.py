"""假入口網站 + SSO（Starlette），只綁 127.0.0.1。

流程（仿公司入口網站）：
  GET  /                 未登入顯示登入表單，已登入顯示功能清單
  POST /login            帳密對 sim/legacyapp/users.ini（沒有時用 .example）
  GET  /launch?func=X    發一次性 token，寫進 sim_data/tokens.txt，302 轉到 legacyapp://launch?token=..&func=X

    python -m sim.portal.app --port 8765
"""
from __future__ import annotations

import argparse
import html
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[2]
FUNCS = {"CHART": "View By Equipment"}   # 功能代碼 → 名稱
SESSIONS: dict[str, str] = {}               # sid → user（只放記憶體，重啟就失效）


def _users() -> dict[str, str]:
    path = ROOT / "sim/legacyapp/users.ini"
    if not path.exists():
        path = ROOT / "sim/legacyapp/users.ini.example"
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(";"):
            u, p = line.split("=", 1)
            out[u.strip()] = p.strip()
    return out


def _data_dir() -> Path:
    return Path(os.environ.get("LEGACYLAB_DATA", ROOT / "sim_data"))


def _token_ttl() -> int:
    return int(os.environ.get("LEGACYLAB_TOKEN_TTL", "120"))


def issue_token(func: str) -> str:
    token = secrets.token_urlsafe(18)
    path = _data_dir() / "tokens.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="ascii") as f:
        f.write(f"{token},{int(time.time()) + _token_ttl()},{func}\n")
    return token


def _user(request: Request) -> str | None:
    return SESSIONS.get(request.cookies.get("sid", ""))


async def home(request: Request) -> Response:
    user = _user(request)
    if not user:
        return HTMLResponse("""<!doctype html><title>Portal Login</title>
<h1>Portal</h1><form method="post" action="/login">
<label>User <input name="user"></label> <label>Password <input name="password" type="password"></label>
<button>Login</button></form>""")
    links = "".join(f'<li><a href="/launch?func={k}">{html.escape(v)}</a></li>' for k, v in FUNCS.items())
    return HTMLResponse(f"<!doctype html><title>Portal</title><h1>Hello {html.escape(user)}</h1><ul>{links}</ul>")


async def login(request: Request) -> Response:
    form = parse_qs((await request.body()).decode("utf-8"))
    user, pw = form.get("user", [""])[0], form.get("password", [""])[0]
    if _users().get(user) != pw or not user:
        return HTMLResponse("invalid user or password", status_code=401)
    sid = secrets.token_urlsafe(18)
    SESSIONS[sid] = user
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("sid", sid, httponly=True, samesite="strict")
    return resp


async def launch(request: Request) -> Response:
    if not _user(request):
        return RedirectResponse("/", status_code=303)
    func = request.query_params.get("func", "")
    if func not in FUNCS:
        return HTMLResponse("unknown function", status_code=404)
    token = issue_token(func)
    return RedirectResponse(f"legacyapp://launch?token={token}&func={func}", status_code=302)


app = Starlette(routes=[Route("/", home), Route("/login", login, methods=["POST"]), Route("/launch", launch)])


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
