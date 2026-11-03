"""失敗現場紀錄（參考 Playwright trace）。

每一步記下耗時、用到的定位層、備註；某一步失敗時，自動存下截圖、視窗樹和例外，
寫成 trace.json，混沌模式下失敗的原因才查得出來。
"""
from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Trace:
    def __init__(self, root: Path | str | None, name: str = "run", screenshot_every_step: bool = False):
        self.enabled = root is not None
        self.dir = Path(root) / f"{datetime.now():%Y%m%d-%H%M%S}-{name}" if root else None
        self.every = screenshot_every_step
        self.steps: list[dict] = []
        self._cur: dict | None = None
        self.window: int | None = None   # 失敗時要擷圖的視窗；plugin 啟動後設定

    def note(self, **kv) -> None:
        if self._cur is not None:
            self._cur.setdefault("notes", {}).update(kv)

    @contextmanager
    def step(self, name: str, **info):
        parent = self._cur
        rec = {"name": name, **info, "start": time.time()}
        self._cur = rec
        try:
            yield rec
            rec["ok"] = True
            if self.every:
                self._snapshot(rec, "ok")
        except BaseException as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
            if not getattr(e, "_traced", False):   # 只在最內層存現場
                rec["traceback"] = traceback.format_exc()
                self._snapshot(rec, "fail")
                try:
                    e._traced = True
                except AttributeError:
                    pass
            raise
        finally:
            rec["seconds"] = round(time.time() - rec.pop("start"), 3)
            self._cur = parent
            (parent.setdefault("children", []) if parent is not None else self.steps).append(rec)

    def _snapshot(self, rec: dict, tag: str) -> None:
        if not self.enabled or not self.window:
            return
        from core import win32

        self.dir.mkdir(parents=True, exist_ok=True)
        base = f"{len(self.steps):03d}-{rec['name'].replace(' ', '_')}-{tag}"
        try:
            if win32.is_alive(self.window):
                img = win32.capture(self.window)
                img.save(self.dir / f"{base}.png")
                rec["screenshot"] = f"{base}.png"
                rec["blank_capture"] = win32.is_blank(img)
                rec["window_tree"] = win32.window_tree(self.window)
            pid = win32.get_pid(self.window)
            rec["top_windows"] = [{"class": w.cls, "text": w.text} for w in win32.top_windows(pid)]
            # 對話框是獨立的頂層視窗，主視窗截圖裡看不到，要另外截
            for k, d in enumerate(win32.dialogs(pid)):
                name = f"{base}-dialog{k}.png"
                win32.capture(d.hwnd).save(self.dir / name)
                text, buttons = win32.dialog_info(d.hwnd)
                rec.setdefault("dialogs", []).append({"title": d.text, "text": text, "screenshot": name,
                                                      "buttons": [b.text for b in buttons]})
        except Exception as e:  # 擷取現場本身失敗不能蓋掉原本的錯誤
            rec["snapshot_error"] = repr(e)

    def save(self) -> Path | None:
        if not self.enabled:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "trace.json"
        path.write_text(json.dumps(self.steps, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return path
