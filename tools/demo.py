"""完整流程 demo：在螢幕上放慢速度跑一次，每一步截圖，結果寫到 demo_out/。

入口網站登入 → 一次性 token 啟動 → 查詢 → OCR 讀表格 → 開圖 → 匯出 → 分析（對照答案卷）→ 寫入保護

    .venv\\Scripts\\python tools/demo.py --pause 1.5
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import win32  # noqa: E402
from core.ocr.base import FallbackOcr  # noqa: E402
from core.ocr.template import TemplateOcr  # noqa: E402
from plugins.base import WriteBlocked  # noqa: E402
from plugins.legacyapp import LegacyAppPlugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo_out"


class Demo:
    def __init__(self, pause: float):
        self.pause = pause
        self.steps: list[dict] = []
        OUT.mkdir(exist_ok=True)

    def step(self, title: str, detail: str = "", hwnd: int | None = None, **data):
        shot = None
        if hwnd and win32.is_alive(hwnd):
            shot = f"{len(self.steps) + 1:02d}.png"
            win32.capture(hwnd).save(OUT / shot)
        self.steps.append({"title": title, "detail": detail, "screenshot": shot, **data})
        print(f"[{len(self.steps)}] {title}  {detail}", flush=True)
        time.sleep(self.pause)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", type=float, default=1.5, help="每一步之間停幾秒，方便看")
    ap.add_argument("--equip-type", default="CVD")
    a = ap.parse_args()
    demo = Demo(a.pause)

    key = json.loads((ROOT / "sim_data/answer_key.json").read_text(encoding="utf-8"))
    truth = {c["chart_id"]: c for c in key["charts"]}

    tpl_path = ROOT / "ocr_templates/legacyapp.json"
    engines = [TemplateOcr.load(tpl_path)] if tpl_path.exists() else []
    try:
        from core.ocr.rapid import RapidOcr
        engines.append(RapidOcr())
    except ImportError:
        pass
    ocr = FallbackOcr(*engines)

    server = subprocess.Popen([sys.executable, "-m", "sim.portal.app", "--port", "8765"], cwd=ROOT)
    time.sleep(2)
    portal = {"portal_url": "http://127.0.0.1:8765", "func": "CHART", "scheme": "legacyapp",
              "handler": [sys.executable, str(ROOT / "sim/launcher/handler.py")]}
    t0 = time.perf_counter()
    try:
        with LegacyAppPlugin({"chaos": "off", "portal": portal}, ocr=ocr) as p:
            p.launch()
            demo.step("入口網站登入並啟動", f"一次性 token 驗證通過，LOGIN 視窗出現 {p.logins} 次；"
                      f"自動按掉的對話框：{len(p.dismissed)} 個（版本說明）", p.main)

            rows = p.query(equip_type=a.equip_type)
            demo.step(f"查詢 EquipType={a.equip_type}", f"狀態列讀到 {len(rows)} 筆；自繪表格用 OCR 讀出",
                      p.main, rows=rows, ocr_usage=dict(ocr.used), uncertain=len(p.uncertain))

            # demo 用答案卷挑一張「有平移」的圖來展示（plugin 本身看不到答案卷）
            pick = next((r["chart_id"] for r in rows if truth.get(r["chart_id"], {}).get("anomaly") == "shift"),
                        rows[0]["chart_id"])
            p.open_item(pick)
            demo.step(f"雙擊開圖 {pick}", f"標題（hwnd 精確讀取）：{p.chart_title()}", p.chart)

            path = p.export(pick, OUT)
            n = len(path.read_text(encoding="utf-8-sig").splitlines()) - 1
            demo.step("匯出 With Batch Lot", f"{path.name}，{n} 點；存檔對話框自動填檔名，完成訊息自動按掉", p.chart)

            res = p.analyze(path)
            t = truth[pick]
            where = (f"PELT 估計從第 {res['change']['change_idx']} 點（lot {res['change_lot']}）開始變"
                     if res["change"] else f"離群點 lot：{res['outlier_lots']}")
            demo.step("分析", f"SPC 判定 {'異常' if res['anomalous'] else '正常'}（{res['spc']['method']}，"
                      f"觸發規則 {list(res['spc']['rules'])}）；{where}；答案卷：{t['anomaly']}，第 {t['change_point']} 點",
                      analysis=res, truth=t)

            excluded = ROOT / "sim_data/excluded.csv"
            before = excluded.stat().st_size if excluded.exists() else 0
            try:
                p.exclude_last_point(pick)
                blocked = "沒有被擋下！"
            except WriteBlocked as e:
                blocked = f"已擋下：{e}"
            after = excluded.stat().st_size if excluded.exists() else 0
            demo.step("嘗試 Edit > Exclude（會改資料）", f"{blocked}；資料檔{'沒變' if before == after else '被改了'}", p.chart)
    finally:
        server.terminate()
    total = time.perf_counter() - t0 - a.pause * len(demo.steps)
    (OUT / "steps.json").write_text(json.dumps({"steps": demo.steps, "seconds_without_pauses": round(total, 1)},
                                               ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"done in {total:.1f}s (excluding pauses) -> {OUT}")


if __name__ == "__main__":
    main()
