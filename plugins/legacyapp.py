"""假舊系統 LegacyApp 的領域模組。

只用使用者看得到的東西操作：視窗、選單、按鈕、擷圖。不直接讀 sim_data（那是答案卷）。
"""
from __future__ import annotations

import csv
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from analysis import changepoint, spc
from core import win32
from core.locator import Locator, Strategy
from core.ocr.base import ink_mask
from core.text import levenshtein
from plugins.base import AppPlugin

ROOT = Path(__file__).resolve().parents[1]
MAIN_TITLE = "LegacyApp - View By Equipment"
COLUMNS = ["chart_id", "equip_id", "param", "kind", "points"]
# 表格版面（100% DPI）；和 sim/legacyapp/src/MainForm.cs 的 ResultGrid 一致
GRID = {"header": 20, "row": 18, "border": 2, "widths": [80, 130, 100, 90, 70]}
GRID_WIDTH_100 = 544
# 已知只有固定幾種值的欄位：OCR 結果貼齊最接近的合法值
COLUMN_VOCAB = {"kind": ("variable", "count")}
# 圖表視窗標題「C0011 / CVD001 / THK」對應的欄位：開圖後可以用 hwnd 精確讀到
TITLE_COLUMNS = ("chart_id", "equip_id", "param")


def _read_users(path: Path) -> tuple[str, str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(";"):
            u, p = line.split("=", 1)
            return u.strip(), p.strip()
    raise ValueError(f"no user in {path}")


class LegacyAppPlugin(AppPlugin):
    name = "legacyapp"
    write_actions = frozenset({"exclude"})

    def __init__(self, config=None, trace=None, allow_write=frozenset(), ocr=None):
        super().__init__(config, trace, allow_write)
        c = self.config
        self.exe = Path(c.get("exe", ROOT / "sim/legacyapp/bin/LegacyApp.exe"))
        self.data = Path(c.get("data", ROOT / "sim_data"))
        self.timeout = float(c.get("timeout", 20))
        # 多按鈕對話框的處理規則（內文片段 → 按鈕）。必須由使用者明確設定；預設沒有。
        self.dialog_rules: dict[str, str] = dict(c.get("dialog_rules", {}))
        if any("modify" in k.lower() for k in self.dialog_rules):
            raise ValueError("dialog_rules must not answer data-modifying confirmations")
        users = Path(c.get("users", ROOT / "sim/legacyapp/users.ini"))
        if not users.exists():
            users = ROOT / "sim/legacyapp/users.ini.example"
        self.user, self.password = (c["user"], c["password"]) if "user" in c else _read_users(users)
        self.ocr = ocr                        # OcrEngine；要多引擎退回時傳 FallbackOcr
        self.proc: subprocess.Popen | None = None
        self.main = 0
        self.chart = 0
        self.rows: list[dict[str, str]] = []
        self._top = 0
        self.dismissed: list[str] = []
        self.logins = 0
        self.uncertain: set[int] = set()       # OCR 沒把握的列 index
        self.row_images: dict[int, list] = {}  # 列 index → 儲存格圖片（用標題校正後可當訓練標註）

    # ---------- 共用 ----------

    @property
    def pid(self) -> int:
        return self.proc.pid if self.proc else 0

    def _pump(self, cond, timeout: float | None = None, desc: str = "condition", expect: tuple[str, ...] = ()):
        """等待條件成立；等的同時處理突發對話框（expect 是預期中、要自己處理的對話框標題）。"""
        def check():
            self.dismissed += win32.handle_dialogs(self.pid, self.dialog_rules, expect)
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f"LegacyApp exited with code {self.proc.returncode}")
            return cond()
        return win32.wait_until(check, timeout or self.timeout, 0.1, desc)

    # ---------- 啟動與登入 ----------

    def launch(self) -> int:
        with self.trace.step("launch"):
            if not self.exe.exists():
                raise FileNotFoundError(f"{self.exe} not found; run sim\\legacyapp\\build.bat")
            env = dict(os.environ)
            if "chaos" in self.config:
                env["LEGACYLAB_CHAOS"] = self.config["chaos"]
            for k, v in self.config.get("chaos_overrides", {}).items():
                env[f"LEGACYLAB_CHAOS_{k.upper()}"] = str(v)
            if self.config.get("seed") is not None:
                env["LEGACYLAB_CHAOS_SEED"] = str(self.config["seed"])
            env["LEGACYLAB_DATA"] = str(self.data)
            env["LEGACYLAB_EXE"] = str(self.exe)
            portal = self.config.get("portal")
            if portal:
                # 走入口網站：登入 → 點功能 → 一次性 token → 協定處理程式啟動
                from core.launcher import launch
                res = launch({"user": self.user, "password": self.password, **portal}, env=env)
                if res.pid is None:
                    raise RuntimeError("portal launch via os.startfile gives no PID; configure a handler")
                self.proc = win32.PidProcess(res.pid)
                self.trace.note(launch="portal")
            else:
                self.proc = subprocess.Popen([str(self.exe), "--data", str(self.data)], env=env)
                self.trace.note(launch="direct")
            logins = 0

            def ready():
                nonlocal logins
                main = win32.find_window(title=MAIN_TITLE, pid=self.pid)
                if main:
                    return main.hwnd
                login = win32.find_window(title="LOGIN", pid=self.pid)
                if login and not win32.dialogs(self.pid):
                    if logins >= 2:
                        raise PermissionError("login failed twice; check users.ini")
                    self._login(login.hwnd)
                    logins += 1
                    time.sleep(0.5)
                return None

            self.main = self._pump(ready, desc="main window")
            self.trace.window = self.main
            self.logins = logins   # 入口網站模式下 >0 表示 token 被拒、退回 LOGIN
            self.trace.note(logins=logins)
            return self.main

    def _login(self, hwnd: int) -> None:
        with self.trace.step("login"):
            edits = sorted((w for w in win32.children(hwnd) if "EDIT" in w.cls.upper()), key=lambda w: w.rect[1])
            win32.set_text(edits[0].hwnd, self.user)
            win32.set_text(edits[1].hwnd, self.password)
            ok = win32.find_child(hwnd, text="OK")
            win32.click_button(ok.hwnd)

    # ---------- 查詢 ----------

    def _controls(self) -> dict[str, win32.Win]:
        kids = win32.children(self.main)
        edits = sorted((w for w in kids if "EDIT" in w.cls.upper()), key=lambda w: w.rect[0])
        return {
            "equip": edits[0], "days": edits[1], "points": edits[2],
            "type": next(w for w in kids if "COMBOBOX" in w.cls.upper()),
            "query": next(w for w in kids if w.text == "Query"),
            "status": next(w for w in kids if "statusbar" in w.cls.lower()),
            "grid": max((w for w in kids if ".Window." in w.cls), key=lambda w: w.size[0] * w.size[1]),
        }

    def query(self, equip_id: str = "", equip_type: str = "ALL", days: int = 30, points: int = 60,
              **_) -> list[dict[str, str]]:
        total = self.run_query(equip_id, equip_type, days, points)
        self.rows = self._read_grid(total)
        return self.rows

    def run_query(self, equip_id: str = "", equip_type: str = "ALL", days: int = 30, points: int = 60) -> int:
        """按下查詢並等結果，回傳筆數（從狀態列讀，不用 OCR）。"""
        with self.trace.step("query", equip_id=equip_id, equip_type=equip_type):
            c = self._controls()
            win32.set_text(c["equip"].hwnd, equip_id)
            win32.set_text(c["days"].hwnd, str(days))
            win32.set_text(c["points"].hwnd, str(points))
            if not win32.combo_select(c["type"].hwnd, equip_type):
                raise ValueError(f"EquipType {equip_type!r} not in list")
            win32.click_button(c["query"].hwnd)
            status = self._pump(lambda: (t := win32.get_text(c["status"].hwnd)).endswith("found") and t,
                                desc="query result")
            total = int(status.split()[0])
            self.trace.note(total=total)
            return total

    def _geometry(self, grid_hwnd: int) -> dict:
        """依表格實際寬度換算 DPI 縮放後的版面。"""
        l, t, r, b = win32.get_rect(grid_hwnd)
        k = (r - l) / GRID_WIDTH_100
        g = {"header": round(GRID["header"] * k), "row": round(GRID["row"] * k), "border": GRID["border"],
             "widths": [round(w * k) for w in GRID["widths"]], "height": b - t, "scale": k}
        return g

    def _visible_rows(self, grid_hwnd: int) -> int:
        g = self._geometry(grid_hwnd)
        return max(1, (g["height"] - g["header"] - g["border"]) // g["row"])

    def pages(self, total: int):
        """逐頁擷取表格，產生 (第一列的全域 index, 可見列數, 圖片)。"""
        grid = self._controls()["grid"].hwnd
        vis = self._visible_rows(grid)
        self.geom = self._geometry(grid)
        self._top = 0
        while True:
            img = win32.capture(self.main, crop_child=grid)
            if win32.is_blank(img):
                raise RuntimeError("grid capture is blank (screen locked or RDP minimized?)")
            yield self._top, min(vis, total - self._top), img
            if self._top + vis >= total:
                return
            win32.post_key(grid, "pagedown")
            self._top = min(self._top + vis, max(0, total - vis))
            time.sleep(0.3)

    def _read_grid(self, total: int) -> list[dict[str, str]]:
        with self.trace.step("read_grid", total=total):
            rows: list[dict[str, str] | None] = [None] * total
            self.uncertain, self.row_images = set(), {}
            for top, n, img in self.pages(total):
                for i in range(n):
                    if rows[top + i] is None:
                        rows[top + i], unsure = self._read_row(img, i, with_confidence=True)
                        self.row_images[top + i] = self.row_cells(img, i)
                        if unsure:
                            self.uncertain.add(top + i)
            self.trace.note(uncertain_rows=len(self.uncertain))
            return rows  # type: ignore[return-value]

    def row_cells(self, img, i: int) -> list:
        """第 i 個可見列的各儲存格圖片（bench 訓練模板 OCR 也用這個）。"""
        g = getattr(self, "geom", None) or {**GRID}
        y = g["border"] + g["header"] + i * g["row"]
        cells, x = [], g["border"]
        for w in g["widths"]:
            cells.append(img.crop((x + 1, y, x + w - 1, y + g["row"] - 1)))
            x += w
        return cells

    def _read_row(self, img, i: int, with_confidence: bool = False):
        """with_confidence=True 時回傳 (列, 是否沒把握)；只看標題能校正的欄位。"""
        out, unsure = {}, False
        for col, cell in zip(COLUMNS, self.row_cells(img, i)):
            text = self._ocr(cell) if ink_mask(cell).any() else ""
            if col in TITLE_COLUMNS and text:
                unsure |= "?" in text or getattr(self.ocr, "last_uncertain", False)
            if col in COLUMN_VOCAB and text:
                text = min(COLUMN_VOCAB[col], key=lambda w: levenshtein(w, text))
            out[col] = text
        return (out, unsure) if with_confidence else out

    def _ocr(self, cell) -> str:
        if self.ocr is None:
            raise RuntimeError("no OCR engine configured")
        return self.ocr.read_line(cell)

    # ---------- 明細 ----------

    def open_item(self, item_id: str) -> int:
        with self.trace.step("open_item", item=item_id):
            idx = next((i for i, r in enumerate(self.rows) if r["chart_id"] == item_id), None)
            if idx is None:
                raise LookupError(f"{item_id} not in last query result")
            self._open_row(idx, expect=item_id)
            title = self.chart_title()
            if item_id not in title:
                raise LookupError(f"opened chart {title!r}, expected {item_id}")
            self._apply_title(idx, title)
            return self.chart

    def _open_row(self, idx: int, expect: str | None = None) -> None:
        """翻到第 idx 列並雙擊。expect 有值時，點之前先用 OCR 確認那一列是目標，避免點錯。"""
        grid = self._controls()["grid"].hwnd
        vis = self._visible_rows(grid)
        target_top = min((idx // vis) * vis, max(0, len(self.rows) - vis))
        while self._top != target_top:
            down = self._top < target_top
            win32.post_key(grid, "pagedown" if down else "pageup")
            self._top = min(self._top + vis, max(0, len(self.rows) - vis)) if down else max(0, self._top - vis)
            time.sleep(0.2)
        i = idx - self._top
        self.geom = g = self._geometry(grid)
        if expect is not None:
            img = win32.capture(self.main, crop_child=grid)
            seen = self._read_row(img, i)["chart_id"]
            if seen != expect:
                raise LookupError(f"row {i} shows {seen!r}, expected {expect!r}")
        y = g["border"] + g["header"] + i * g["row"] + g["row"] // 2
        win32.post_click(grid, g["border"] + 20, y, double=True)
        self.chart = self._pump(lambda: (w := win32.find_window(title="Chart", pid=self.pid)) and w.hwnd,
                                desc="chart window")

    def _apply_title(self, idx: int, title: str) -> dict[str, str]:
        """用標題（hwnd 讀到的精確文字）校正那一列的 OCR 結果。"""
        parts = [p.strip() for p in title.split(" / ")]
        if len(parts) != len(TITLE_COLUMNS):
            return {}
        self.rows[idx].update(zip(TITLE_COLUMNS, parts))
        return dict(zip(TITLE_COLUMNS, parts))

    def verify_rows(self, all_rows: bool = False, learn: bool = True) -> int:
        """把 OCR 沒把握的列（all_rows=True 時是全部）逐一打開，用標題的精確文字校正。

        learn=True 時這些文字也拿來訓練模板 OCR：不需要人工標註或答案卷，
        訓練資料完全來自系統自己的畫面（真系統上也適用）。
        """
        targets = sorted(range(len(self.rows)) if all_rows else self.uncertain)
        with self.trace.step("verify_rows", n=len(targets), all_rows=all_rows):
            samples = []
            for idx in targets:
                self.close_item()
                self._open_row(idx)
                exact = self._apply_title(idx, self.chart_title())
                cells = self.row_images.get(idx)
                if cells:
                    samples += [(cells[COLUMNS.index(c)], exact[c]) for c in TITLE_COLUMNS if c in exact]
            self.close_item()
            fixed = len(targets)
            self.uncertain -= set(targets)
            tpl = next((e for e in getattr(self.ocr, "engines", [self.ocr]) if hasattr(e, "train")), None)
            if learn and tpl is not None and samples:
                self.trace.note(learned=tpl.train(samples))
                if self.config.get("templates_out"):
                    tpl.save(self.config["templates_out"])
            return fixed

    def chart_title(self) -> str:
        def by_hwnd():
            box = win32.find_child(self.chart, cls="WindowsForms10.EDIT")
            return box.text if box and box.text else None

        def by_ocr():
            img = win32.capture(self.chart)
            box = win32.find_child(self.chart, cls="WindowsForms10.EDIT")
            l, t, *_ = win32.get_rect(self.chart)
            bl, bt, br, bb = box.rect
            return self._ocr(img.crop((bl - l + 2, bt - t + 2, br - l - 2, bb - t - 2))) or None

        return Locator("chart_title", Strategy("hwnd", by_hwnd), Strategy("ocr", by_ocr),
                       trace=self.trace).resolve()

    def close_item(self) -> None:
        if self.chart and win32.is_alive(self.chart):
            win32.close_window(self.chart)
            self._pump(lambda: not win32.is_alive(self.chart), desc="chart closed")
        self.chart = 0

    # ---------- 匯出 ----------

    def export(self, item_id: str, out_dir: Path) -> Path:
        with self.trace.step("export", item=item_id):
            if not (self.chart and win32.is_alive(self.chart) and item_id in self.chart_title()):
                self.close_item()
                self.open_item(item_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = (out_dir / f"{item_id}.csv").resolve()
            path.unlink(missing_ok=True)   # 避免「是否覆寫」的多按鈕對話框
            win32.menu_command(self.chart, ["Tools", "Export Data", "With Batch Lot"])
            dlg = self._pump(lambda: next((d.hwnd for d in win32.dialogs(self.pid)
                                           if win32.is_file_dialog(d.hwnd)), None), desc="save dialog")
            name_box = win32.user32.GetDlgItem(dlg, 1148)   # 檔名欄（cmb13）
            edit = win32.find_child(name_box, cls="Edit") if name_box else None
            edit = edit or win32.find_child(dlg, cls="Edit")
            win32.set_text(edit.hwnd, str(path))
            win32.click_button(win32.user32.GetDlgItem(dlg, 1))  # IDOK = 存檔
            self._pump(lambda: path.exists() and not any(win32.is_file_dialog(d.hwnd)
                                                         for d in win32.dialogs(self.pid)), desc="export file")
            # 等「Export completed.」被自動按掉，再確認檔案寫完
            self._pump(lambda: not win32.dialogs(self.pid), desc="export done")
            return path

    # ---------- 會改資料的動作 ----------

    def exclude_last_point(self, item_id: str) -> None:
        """會改資料：沒有 allow_write={"exclude"} 時，在碰到 GUI 之前就擋下。"""
        self.guard_write("exclude")
        with self.trace.step("exclude", item=item_id):
            if not (self.chart and win32.is_alive(self.chart) and item_id in self.chart_title()):
                self.close_item()
                self.open_item(item_id)
            win32.menu_command(self.chart, ["Edit", "Exclude Point..."])
            # 使用者已明確允許，所以這個確認框按「是」
            dlg = self._pump(lambda: next((d.hwnd for d in win32.dialogs(self.pid)
                                           if d.text == "Exclude Point"), None), desc="exclude confirm",
                             expect=("Exclude Point",))
            yes = win32.find_child(dlg, cls="Button", pred=lambda w: win32.button_label(w.text) in ("Yes", "是"))
            win32.click_button(yes.hwnd)
            self._pump(lambda: not win32.dialogs(self.pid), desc="exclude done")

    # ---------- 分析 ----------

    def analyze(self, path: Path, data_kind: str | None = None) -> dict[str, Any]:
        text = Path(path).read_text(encoding="utf-8-sig")
        dialect = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        rows = list(csv.DictReader(text.splitlines(), delimiter=dialect))
        values = [float(r["Value"].replace(",", ".")) for r in rows]
        lots = [r.get("BatchLot", "") for r in rows]
        if data_kind is None:
            item = Path(path).stem
            data_kind = next((r["kind"] for r in self.rows if r["chart_id"] == item), "variable")
        det = spc.auto(values, data_kind)
        cp = changepoint.cusum(values)
        return {"spc": det.to_dict(), "changepoint": cp.to_dict(),
                "change_lot": changepoint.lot_at(lots, cp.change_idx),
                "first_alarm_lot": changepoint.lot_at(lots, det.first_alarm), "n": len(values)}

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if self.main and win32.is_alive(self.main):
                win32.close_window(self.main)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
