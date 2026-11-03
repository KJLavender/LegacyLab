"""模板 OCR 自我校準：查全部 → 每一列開圖讀標題（hwnd 精確文字）→ 用來訓練模板。

不用答案卷、不用人工標註；在真系統上也能用同樣方式產生訓練資料。

    .venv\Scripts\python -m bench.ocr_calibrate
"""
from __future__ import annotations

import argparse
import time

from bench.common import ROOT
from core.ocr.base import FallbackOcr
from core.ocr.template import TemplateOcr
from plugins.legacyapp import LegacyAppPlugin

OUT = ROOT / "ocr_templates" / "legacyapp.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equip-type", default="ALL")
    ap.add_argument("--fresh", action="store_true", help="從空白模板開始（預設接著既有模板學）")
    a = ap.parse_args()
    tpl = TemplateOcr() if a.fresh or not OUT.exists() else TemplateOcr.load(OUT)
    engines = [tpl]
    try:
        from core.ocr.rapid import RapidOcr
        engines.append(RapidOcr())
    except ImportError:
        pass
    ocr = FallbackOcr(*engines)
    if not tpl.glyphs and len(engines) == 1:
        raise SystemExit("empty templates and no RapidOCR: install .[ocr] or run bench.ocr_bench first")
    t0 = time.perf_counter()
    with LegacyAppPlugin({"chaos": "off", "templates_out": str(OUT)}, ocr=ocr) as p:
        p.launch()
        p.query(equip_type=a.equip_type)
        n = p.verify_rows(all_rows=True, learn=True)
    print(f"verified {n} rows in {time.perf_counter() - t0:.1f}s; templates: {len(tpl.glyphs)} chars, "
          f"{len(tpl._exact)} variants, ambiguous groups: {[sorted(v) for v in tpl._ambig.values()]}")
    print("saved:", OUT)


if __name__ == "__main__":
    main()
