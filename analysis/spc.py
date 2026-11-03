"""管制圖偵測器（E1）。

所有偵測器都回傳同一種結構 `Detection`，bench 才能直接比較。
- baseline：模擬現有 spc_summary（樣本標準差 3σ + 連續 8 點同側）
- imr：I-MR 圖，σ 用移動全距估計（不會被異常本身撐大），加 Nelson 規則 1/2/3/5
- auto：計數資料改用 c 圖（Poisson 界限），其餘走 imr

- shewhart_*：shewhart 函式庫（選用相依），包成同一個 Detection；計數資料用 Laney u′

函式庫只透過 `shewhart_chart()` 使用，版本變動時只改這裡。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

D2 = 1.128  # n=2 移動全距的 d2 常數


@dataclass
class Detection:
    anomalous: bool
    first_alarm: int | None          # 第一個觸發點的 index
    rules: dict[str, list[int]] = field(default_factory=dict)  # 規則 -> 觸發點
    center: float = 0.0
    ucl: float = 0.0
    lcl: float = 0.0
    method: str = ""

    def to_dict(self) -> dict:
        return {"anomalous": self.anomalous, "first_alarm": self.first_alarm, "rules": self.rules,
                "center": self.center, "ucl": self.ucl, "lcl": self.lcl, "method": self.method}


def _finish(rules: dict[str, list[int]], center, ucl, lcl, method) -> Detection:
    rules = {k: v for k, v in rules.items() if v}
    hits = [i for v in rules.values() for i in v]
    return Detection(bool(hits), min(hits) if hits else None, rules,
                     float(center), float(ucl), float(lcl), method)


def _run_same_side(x, center, n) -> list[int]:
    side = np.sign(x - center)
    out, run = [], 0
    for i in range(len(x)):
        run = run + 1 if i and side[i] == side[i - 1] and side[i] != 0 else 1
        if run >= n:
            out.append(i)
    return out


def _trend(x, n=6) -> list[int]:
    d = np.sign(np.diff(x))
    out, run = [], 0
    for i in range(len(d)):
        run = run + 1 if i and d[i] == d[i - 1] and d[i] != 0 else 1
        if run >= n - 1:
            out.append(i + 1)
    return out


def _k_of_m(x, center, sigma, k, m, zone) -> list[int]:
    out = []
    for i in range(m - 1, len(x)):
        w = x[i - m + 1:i + 1]
        if np.sum(w > center + zone * sigma) >= k or np.sum(w < center - zone * sigma) >= k:
            out.append(i)
    return out


def baseline(x, phase1: int | None = None) -> Detection:
    x = np.asarray(x, float)
    ref = x[:phase1] if phase1 else x
    c, s = ref.mean(), ref.std(ddof=1)
    rules = {
        "beyond_3s": np.flatnonzero(np.abs(x - c) > 3 * s).tolist(),
        "8_same_side": _run_same_side(x, c, 8),
    }
    return _finish(rules, c, c + 3 * s, c - 3 * s, "baseline")


def imr(x, phase1: int | None = None) -> Detection:
    x = np.asarray(x, float)
    ref = x[:phase1] if phase1 else x
    c = np.median(ref)  # 中位數：離群點與後段平移不太會拉動中心線
    mr = np.abs(np.diff(ref))
    s = np.median(mr) / 0.954 if len(mr) else 0.0  # 移動全距中位數的 σ 估計，比平均更穩健
    if s == 0:
        s = mr.mean() / D2 if len(mr) else 1e-9
    rules = {
        "nelson1_beyond_3s": np.flatnonzero(np.abs(x - c) > 3 * s).tolist(),
        "nelson2_9_same_side": _run_same_side(x, c, 9),
        "nelson3_6_trend": _trend(x, 6),
        "nelson5_2of3_beyond_2s": _k_of_m(x, c, s, 2, 3, 2.0),
    }
    return _finish(rules, c, c + 3 * s, c - 3 * s, "imr")


def c_chart(x, phase1: int | None = None, laney: bool = True) -> Detection:
    """計數資料的 c 圖；laney=True 時用 Laney c′ 修正過度離散（負二項資料）。

    下界通常是 0，所以只看上界與連續偏高。
    """
    x = np.asarray(x, float)
    ref = x[:phase1] if phase1 else x
    cbar = max(float(ref.mean()), 1e-9)
    sigma = np.sqrt(cbar)
    if laney and len(ref) > 2:
        z = (ref - cbar) / sigma
        mr = np.abs(np.diff(z))
        sigma_z = float(np.median(mr) / 0.954) or float(mr.mean() / D2)
        sigma *= max(1.0, sigma_z)  # 只放寬、不收緊
    ucl = cbar + 3 * sigma
    lcl = max(0.0, cbar - 3 * sigma)
    rules = {
        "c_beyond_ucl": np.flatnonzero(x > ucl).tolist(),
        "c_9_above": [i for i in _run_same_side(x, cbar, 9) if x[i] > cbar],
    }
    return _finish(rules, cbar, ucl, lcl, "laney_c" if laney else "c_chart")


def auto(x, data_kind: str = "variable", phase1: int | None = None) -> Detection:
    return c_chart(x, phase1) if data_kind == "count" else imr(x, phase1)


# 每條規則要幾個點才成立；用來把「整段違規點」換成「第一次能發出警報的點」
_RULE_NEED = {"nelson_2": 9, "nelson_3": 6, "nelson_4": 14, "nelson_5": 3, "nelson_6": 5,
              "nelson_7": 15, "nelson_8": 8, "we_2": 3, "we_3": 5, "we_4": 8}


def shewhart_chart(x, data_kind: str = "variable", rules: str = "nelson",
                   keep: set[str] | None = None) -> Detection:
    """用 shewhart 函式庫：一般資料走 I-MR（只看 I 圖），計數資料走 Laney u′。

    keep：只保留這些規則的訊號（shewhart 只接受整組規則，逐條比較時在這裡過濾）。
    """
    import shewhart as sw  # 選用相依

    x = np.asarray(x, float)
    if data_kind == "count":
        # 屬性圖只支援 nelson（四條屬性圖規則）或 none；WE 的分區規則只適用計量值
        r = sw.laney_u(x, size=np.ones(len(x)), rules="none" if rules == "none" else "nelson")
        chart, c, u, l = "attr", r.stats["u_center"], r.stats["u_ucl"], r.stats["u_lcl"]
    else:
        r = sw.imr(x, rules=rules)
        chart, c, u, l = "i", r.stats["i_center"], r.stats["i_ucl"], r.stats["i_lcl"]
    fired: dict[str, list[int]] = {}
    for sig in r.signals:
        if sig.chart != chart or (keep is not None and sig.rule not in keep):
            continue
        pts = sorted(sig.points)
        need = _RULE_NEED.get(sig.rule, 1)
        fired.setdefault(sig.rule, []).append(pts[min(need, len(pts)) - 1])
    return _finish(fired, c, u, l, f"shewhart_{rules}")


DETECTORS = {
    "baseline": lambda x, kind: baseline(x),
    "imr": lambda x, kind: imr(x),
    "auto": lambda x, kind: auto(x, kind),
    "shewhart_nelson": lambda x, kind: shewhart_chart(x, kind, "nelson"),
    "shewhart_we": lambda x, kind: shewhart_chart(x, kind, "western_electric"),
    # 逐條量完後的精簡組合：只留誤報低的規則 1、2
    "shewhart_n12": lambda x, kind: shewhart_chart(x, kind, "nelson", keep={"nelson_1", "nelson_2"}),
}
