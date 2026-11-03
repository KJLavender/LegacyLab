"""bench 共用：結果檔一律附 git commit 與種子。"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "results"


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip() or "uncommitted"
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return sha + ("-dirty" if dirty and sha != "uncommitted" else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def save_result(kind: str, seed: int, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{kind}-{stamp}.json"
    doc = {"kind": kind, "seed": seed, "commit": git_commit(),
           "created": datetime.now().isoformat(timespec="seconds"), **payload}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def print_table(rows: list[dict], cols: list[str]) -> None:
    def fmt(v):
        if v is None:
            return "-"
        return f"{v:.3f}" if isinstance(v, float) else str(v)
    widths = [max(len(c), *(len(fmt(r.get(c))) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  ".join(fmt(r.get(c)).ljust(w) for c, w in zip(cols, widths)))
