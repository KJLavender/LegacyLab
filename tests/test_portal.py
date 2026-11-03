import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sim.launcher.handler import parse

ROOT = Path(__file__).resolve().parents[1]


def test_handler_validates_url():
    assert parse("legacyapp://launch?token=abcdefghijklmnop1234&func=CHART")["func"] == "CHART"
    for bad in ("http://launch?token=abcdefghijklmnop&func=CHART",
                "legacyapp://launch?token=abcdefghijklmnop&func=DELETE",
                "legacyapp://launch?token=short&func=CHART",
                "legacyapp://launch?token=abc%3Bdefghijklmnop&func=CHART"):
        with pytest.raises(ValueError):
            parse(bad)


@pytest.fixture()
def portal(tmp_path):
    pytest.importorskip("starlette")
    pytest.importorskip("uvicorn")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**__import__("os").environ, "LEGACYLAB_DATA": str(tmp_path), "LEGACYLAB_TOKEN_TTL": "60"}
    proc = subprocess.Popen([sys.executable, "-m", "sim.portal.app", "--port", str(port)], cwd=ROOT, env=env)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", tmp_path
    proc.terminate()


def test_portal_issues_one_time_token(portal):
    from core.launcher import get_launch_url

    url, data = portal
    cfg = {"portal_url": url, "func": "CHART", "user": "demo", "password": "demo123"}
    a, b = get_launch_url(cfg), get_launch_url(cfg)
    assert a.startswith("legacyapp://launch?token=") and a != b
    lines = (data / "tokens.txt").read_text().splitlines()
    assert len(lines) == 2 and all(int(l.split(",")[1]) > time.time() for l in lines)
    parse(a)   # 入口網站發的 URL 一定要能通過處理程式的檢查


def test_portal_rejects_bad_login(portal):
    from core.launcher import get_launch_url

    url, _ = portal
    with pytest.raises(PermissionError):
        get_launch_url({"portal_url": url, "func": "CHART", "user": "demo", "password": "wrong"})
