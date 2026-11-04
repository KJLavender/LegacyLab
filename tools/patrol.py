"""E5 定時巡檢：查全部 → 校正 ID → 每張圖開圖、匯出、分析 → HTML 報告（異常排最前面）。

    .venv\\Scripts\\python tools/patrol.py                 # 報告寫到 reports/
    .venv\\Scripts\\python tools/patrol.py --score         # 另外用答案卷替巡檢打分數（只有模擬環境有）
    .venv\\Scripts\\python tools/patrol.py --equip-type CVD --chaos light

要排程的話，用 Windows 工作排程器（schtasks，不需要系統管理員權限）呼叫這行即可。
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ocr.base import FallbackOcr  # noqa: E402
from core.ocr.template import TemplateOcr  # noqa: E402
from core.trace import Trace  # noqa: E402
from plugins.legacyapp import LegacyAppPlugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build_ocr() -> FallbackOcr:
    engines = []
    tpl = ROOT / "ocr_templates/legacyapp.json"
    if tpl.exists():
        engines.append(TemplateOcr.load(tpl))
    try:
        from core.ocr.rapid import RapidOcr
        engines.append(RapidOcr())
    except ImportError:
        pass
    if not engines:
        raise SystemExit("no OCR engine: run bench.ocr_calibrate or install .[ocr]")
    return FallbackOcr(*engines)


def patrol(equip_type: str, chaos: str, out: Path) -> dict:
    exports = out / "exports"
    trace = Trace(ROOT / "bench/traces", "patrol")
    cfg = {"chaos": chaos, "verified_cache": str(ROOT / "ocr_templates/verified_cells.json")}
    results, errors = [], []
    t0 = time.perf_counter()
    with LegacyAppPlugin(cfg, trace=trace, ocr=build_ocr()) as p:
        p.launch()
        rows = p.query(equip_type=equip_type)
        verified = p.verify_rows()
        for r in rows:
            try:
                path = p.export(r["chart_id"], exports)
                text = path.read_text(encoding="utf-8-sig").splitlines()
                sep = ";" if text[0].count(";") > text[0].count(",") else ","
                pts = list(csv.DictReader(text, delimiter=sep))
                res = p.analyze(path, r["kind"])
                results.append({**r, **res, "values": [float(x["Value"].replace(",", ".")) for x in pts],
                                "lots": [x["BatchLot"] for x in pts]})
            except Exception as e:   # 一張圖失敗不影響其他張；現場紀錄在 trace
                errors.append({"chart_id": r["chart_id"], "error": f"{type(e).__name__}: {e}"})
                p.close_item()
        p.close_item()
    if errors:
        trace.save()
    return {"started": datetime.now().isoformat(timespec="seconds"), "equip_type": equip_type, "chaos": chaos,
            "seconds": round(time.perf_counter() - t0, 1), "verified_rows": verified, "cache_hits": p.cache.hits,
            "results": results, "errors": errors}


def score(doc: dict) -> dict:
    key = json.loads((ROOT / "sim_data/answer_key.json").read_text(encoding="utf-8"))
    truth = {c["chart_id"]: c for c in key["charts"]}
    pos = [r for r in doc["results"] if truth[r["chart_id"]]["anomalous"]]
    neg = [r for r in doc["results"] if not truth[r["chart_id"]]["anomalous"]]
    errs = [abs(r["change"]["change_idx"] - truth[r["chart_id"]]["change_point"]) for r in pos
            if r["anomalous"] and r["change"] and truth[r["chart_id"]]["change_point"] is not None]
    for r in doc["results"]:
        r["truth"] = truth[r["chart_id"]]["anomaly"]
        r["truth_cp"] = truth[r["chart_id"]]["change_point"]
    return {"detection_rate": sum(r["anomalous"] for r in pos) / max(1, len(pos)),
            "false_alarm_rate": sum(r["anomalous"] for r in neg) / max(1, len(neg)),
            "lot_within_1": sum(e <= 4 for e in errs) / max(1, len(errs)),
            "n_pos": len(pos), "n_neg": len(neg)}


def sparkline(r: dict, w: int = 260, h: int = 54) -> str:
    v = r["values"]
    lo, hi = min(v + [r["spc"]["lcl"]]), max(v + [r["spc"]["ucl"]])
    span = (hi - lo) or 1
    X = lambda i: 2 + i * (w - 4) / max(1, len(v) - 1)
    Y = lambda y: h - 3 - (y - lo) / span * (h - 6)
    parts = [f'<line x1="0" x2="{w}" y1="{Y(r["spc"]["ucl"]):.1f}" y2="{Y(r["spc"]["ucl"]):.1f}" class="lim"/>',
             f'<line x1="0" x2="{w}" y1="{Y(r["spc"]["lcl"]):.1f}" y2="{Y(r["spc"]["lcl"]):.1f}" class="lim"/>',
             f'<polyline points="{" ".join(f"{X(i):.1f},{Y(y):.1f}" for i, y in enumerate(v))}" class="ln"/>']
    if r.get("change"):
        x = X(r["change"]["change_idx"])
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" class="cp"/>')
    if r.get("truth_cp") is not None:
        x = X(r["truth_cp"])
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" class="tcp"/>')
    return f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">{"".join(parts)}</svg>'


def render(doc: dict, sc: dict | None) -> str:
    res = sorted(doc["results"], key=lambda r: (not r["anomalous"], r["chart_id"]))
    n_bad = sum(r["anomalous"] for r in res)
    rows = []
    for r in res:
        where = r.get("summary", "") if r["anomalous"] else ""
        truth = (f'<td>{r["truth"]}{"" if r["truth_cp"] is None else " @" + str(r["truth_cp"])}</td>'
                 if sc else "")
        rows.append(f'<tr class="{"bad" if r["anomalous"] else ""}"><td>{r["chart_id"]}</td>'
                    f'<td>{html.escape(r["equip_id"])}</td><td>{r["param"]}</td><td>{r["kind"]}</td>'
                    f'<td>{"異常" if r["anomalous"] else "正常"}</td><td>{html.escape(where)}</td>'
                    f'<td>{", ".join(r["spc"]["rules"])}</td>{truth}<td>{sparkline(r)}</td></tr>')
    score_html = ""
    if sc:
        score_html = (f'<p class="score">對照答案卷：偵測率 {sc["detection_rate"]:.0%}（{sc["n_pos"]} 張異常）、'
                      f'誤報率 {sc["false_alarm_rate"]:.0%}（{sc["n_neg"]} 張正常）、'
                      f'起點落在 1 個 lot 內 {sc["lot_within_1"]:.0%}。圖中灰色虛線是答案卷的真實起點。</p>')
    errs = "".join(f"<li>{e['chart_id']}: {html.escape(e['error'])}</li>" for e in doc["errors"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>巡檢報告 {doc['started']}</title><style>
body{{font-family:system-ui,"Microsoft JhengHei",sans-serif;margin:16px;color:#222}}
table{{border-collapse:collapse;font-size:13px}} th,td{{border:1px solid #ddd;padding:3px 7px;text-align:left;vertical-align:middle}}
th{{background:#f3f3f3}} tr.bad td{{background:#fff3f0}} .score{{background:#eef6ff;padding:8px;border-radius:6px}}
.lim{{stroke:#c33;stroke-dasharray:3 2;stroke-width:1}} .ln{{fill:none;stroke:#1f6feb;stroke-width:1.3}}
.cp{{stroke:#e07b00;stroke-width:2}} .tcp{{stroke:#888;stroke-dasharray:2 2;stroke-width:1.5}}
</style></head><body>
<h2>巡檢報告</h2>
<p>{doc['started']}｜EquipType={doc['equip_type']}｜混沌模式 {doc['chaos']}｜{len(res)} 張圖，<b>{n_bad} 張異常</b>｜
耗時 {doc['seconds']} 秒（開圖確認 {doc['verified_rows']} 列 ID，快取命中 {doc['cache_hits']} 格）</p>
{score_html}
{"<p>失敗：</p><ul>" + errs + "</ul>" if errs else ""}
<table><tr><th>Chart</th><th>Equipment</th><th>Param</th><th>Kind</th><th>判定</th><th>從哪裡開始</th>
<th>觸發規則</th>{"<th>答案卷</th>" if sc else ""}<th>趨勢（橘線：估計起點）</th></tr>{"".join(rows)}</table>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equip-type", default="ALL")
    ap.add_argument("--chaos", default="off")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    a = ap.parse_args()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = a.out / stamp
    out.mkdir(parents=True, exist_ok=True)
    doc = patrol(a.equip_type, a.chaos, out)
    sc = score(doc) if a.score else None
    (out / "report.html").write_text(render(doc, sc), encoding="utf-8")
    slim = {**doc, "results": [{k: v for k, v in r.items() if k not in ("values", "lots")} for r in doc["results"]],
            "score": sc}
    (out / "report.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{len(doc['results'])} charts, {sum(r['anomalous'] for r in doc['results'])} anomalous, "
          f"{len(doc['errors'])} errors, {doc['seconds']}s -> {out / 'report.html'}")
    if sc:
        print("score:", {k: round(v, 3) if isinstance(v, float) else v for k, v in sc.items()})


if __name__ == "__main__":
    main()
