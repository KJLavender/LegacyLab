"""單張圖的分析流程：SPC 負責發警報，變化點方法負責回答「從哪個 lot 開始變」。

bench 的結果（docs/findings.md）：PELT 找變化點起點最準（誤差 2–3 點）、誤報最少，
但它是離線方法；CUSUM 發警報快，起點估計卻常偏早。所以：
- 有沒有異常：spc.auto（I-MR + Nelson；計數資料用 Laney c′）
- 從哪裡開始：PELT（沒裝 ruptures 時退回 CUSUM）
- 只有離群點、沒有持續變化時：列出離群點所在的 lot
"""
from __future__ import annotations

from typing import Any

from analysis import changepoint, spc


def analyze_series(values: list[float], lots: list[str], data_kind: str = "variable") -> dict[str, Any]:
    det = spc.auto(values, data_kind)
    out: dict[str, Any] = {"n": len(values), "data_kind": data_kind, "spc": det.to_dict(),
                           "anomalous": det.anomalous, "first_alarm_lot": changepoint.lot_at(lots, det.first_alarm),
                           "change": None, "change_lot": None, "outlier_lots": []}
    if not det.anomalous:
        return out
    try:
        cp = changepoint.pelt(values)
    except ImportError:
        cp = changepoint.cusum(values)
    if cp.detected:
        out["change"] = cp.to_dict()
        out["change_lot"] = changepoint.lot_at(lots, cp.change_idx)
    beyond = next((v for k, v in det.rules.items() if "beyond" in k or k == "nelson_1"), [])
    out["outlier_lots"] = sorted({lots[i] for i in beyond if 0 <= i < len(lots)})
    out["summary"] = (f"從第 {cp.change_idx} 點（lot {out['change_lot']}）開始偏移" if cp.detected
                      else f"離群點：{', '.join(out['outlier_lots']) or '—'}")
    return out
