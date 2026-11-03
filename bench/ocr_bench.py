"""E3 OCR bench：在真的 LegacyApp 畫面上比較 OCR 引擎。

流程：查 ALL → 逐頁擷圖 → 用前 --train-rows 列訓練模板 OCR → 其餘列給各引擎辨識 → 和答案比對。
答案來自資料產生器（sim_data/charts.csv），plugin 本身看不到。

    python -m bench.ocr_bench --engines template,rapidocr --chaos off
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from bench.common import ROOT, print_table, save_result
from bench.metrics import char_accuracy, row_exact
from core.ocr.base import FallbackOcr, ink_mask
from core.ocr.template import TemplateOcr
from plugins.legacyapp import COLUMNS, LegacyAppPlugin

TEMPLATES = ROOT / "ocr_templates" / "legacyapp.json"


def truth_rows(data: Path) -> list[list[str]]:
    with (data / "charts.csv").open(encoding="utf-8-sig") as f:
        return [[r["chart_id"], r["equip_id"], r["param"], r["data_kind"], r["points"]] for r in csv.DictReader(f)]


def make_engine(name: str, tpl: TemplateOcr):
    """template / rapidocr / template+rapidocr（模板認不出才交給 RapidOCR）。"""
    parts = []
    for n in name.split("+"):
        if n == "template":
            parts.append(tpl)
        elif n == "rapidocr":
            from core.ocr.rapid import RapidOcr
            parts.append(RapidOcr())
        else:
            raise ValueError(f"unknown engine {n}")
    return parts[0] if len(parts) == 1 else FallbackOcr(*parts)


def collect(plugin: LegacyAppPlugin, total: int) -> list[tuple[int, list]]:
    """回傳每一列（全域 index, 儲存格圖片）。"""
    seen: dict[int, list] = {}
    for top, n, img in plugin.pages(total):
        for i in range(n):
            seen.setdefault(top + i, plugin.row_cells(img, i))
    return sorted(seen.items())


def run(engines: list[str], train_rows: int, chaos: str, seed: int) -> dict:
    data = ROOT / "sim_data"
    truth = truth_rows(data)
    with LegacyAppPlugin({"chaos": chaos, "seed": seed}) as p:
        p.launch()
        total = p.run_query(equip_type="ALL")
        rows = collect(p, total)
    if total != len(truth):
        raise RuntimeError(f"grid shows {total} rows but answer key has {len(truth)}")

    train, test = rows[:train_rows], rows[train_rows:]
    tpl = TemplateOcr()
    info = tpl.train((cell, truth[i][c]) for i, cells in train for c, cell in enumerate(cells))
    TEMPLATES.parent.mkdir(exist_ok=True)
    tpl.save(TEMPLATES)

    results = {"train_rows": len(train), "test_rows": len(test), "template_train": info, "engines": {}}
    for name in engines:
        eng = make_engine(name, tpl)
        t0 = time.perf_counter()
        preds = [[eng.read_line(cell) if ink_mask(cell).any() else "" for cell in cells] for _, cells in test]
        dt = time.perf_counter() - t0
        gold = [truth[i] for i, _ in test]
        ids_t = [g[1] for g in gold]
        ids_p = [p[1] for p in preds]
        errors = [{"truth": g, "pred": p} for g, p in zip(gold, preds) if g != p][:15]
        results["engines"][name] = {
            "char_accuracy": char_accuracy(["|".join(g) for g in gold], ["|".join(p) for p in preds]),
            "equip_id_char_accuracy": char_accuracy(ids_t, ids_p),
            "equip_id_exact": row_exact([[x] for x in ids_t], [[x] for x in ids_p]),
            "row_exact": row_exact(gold, preds),
            "ms_per_cell": 1000 * dt / max(1, len(test) * len(COLUMNS)),
            "sample_errors": errors,
            "equip_id_errors": [[t, p] for t, p in zip(ids_t, ids_p) if t != p],
        }
        if isinstance(eng, FallbackOcr):
            results["engines"][name]["engine_usage"] = eng.used
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="template")
    ap.add_argument("--train-rows", type=int, default=21, help="訓練用的列數（預設第一頁）")
    ap.add_argument("--chaos", default="off")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    res = run(a.engines.split(","), a.train_rows, a.chaos, a.seed)
    print(f"train rows {res['train_rows']}, test rows {res['test_rows']}, template: {res['template_train']}")
    print_table([{"engine": k, **v} for k, v in res["engines"].items()],
                ["engine", "char_accuracy", "equip_id_char_accuracy", "equip_id_exact", "row_exact", "ms_per_cell"])
    for k, v in res["engines"].items():
        for e in v["sample_errors"][:3]:
            print(f"  [{k}] truth={e['truth']} pred={e['pred']}")
        if v["equip_id_errors"]:
            print(f"  [{k}] equip_id errors: " + ", ".join(f"{t}->{p}" for t, p in v["equip_id_errors"]))
        if "engine_usage" in v:
            print(f"  [{k}] engine usage: {v['engine_usage']}")
    print("saved:", save_result("ocr", a.seed, res))


if __name__ == "__main__":
    main()
