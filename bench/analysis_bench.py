"""E1 / E2 分析 bench：不碰 GUI，直接用資料產生器的資料和答案卷打分數。

    python -m bench.analysis_bench --seed 42
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from analysis import changepoint, spc
from bench.common import print_table, save_result
from bench.metrics import detection_scores
from sim.datagen.generate import generate


def load(seed: int):
    import sqlite3

    tmp = Path(tempfile.mkdtemp(prefix="legacylab-"))
    key = generate(tmp, seed=seed)
    con = sqlite3.connect(tmp / "legacylab.db")
    series = {}
    for cid, val in con.execute("SELECT chart_id, value FROM points ORDER BY chart_id, idx"):
        series.setdefault(cid, []).append(val)
    con.close()
    return key["charts"], series


def run(seed: int) -> dict:
    truths, series = load(seed)
    results = {}

    for name, det in spc.DETECTORS.items():
        try:
            items = []
            for t in truths:
                d = det(series[t["chart_id"]], t["data_kind"])
                items.append({**_truth(t), "detected": d.anomalous, "alarm_idx": d.first_alarm,
                              "rules": d.rules})
            results[f"E1/{name}"] = _by_kind(items, truths)
            results[f"E1/{name}"]["per_rule"] = _per_rule(items)
        except ImportError as e:
            results[f"E1/{name}"] = {"skipped": f"missing dependency: {e.name}"}

    for name, fn in changepoint.DETECTORS.items():
        try:
            items = []
            for t in truths:
                if t["anomaly"] == "outlier":  # 變化點方法不負責單點離群
                    continue
                r = fn(series[t["chart_id"]])
                items.append({**_truth(t), "detected": r.detected, "alarm_idx": r.alarm_idx,
                              "cp_error": abs(r.change_idx - t["change_point"])
                              if r.detected and t["change_point"] is not None else None})
            sub = [t for t in truths if t["anomaly"] != "outlier"]
            res = _by_kind(items, sub)
            errs = sorted(i["cp_error"] for i in items if i.get("cp_error") is not None)
            res["all"]["median_cp_error"] = errs[len(errs) // 2] if errs else None
            results[f"E2/{name}"] = res
        except ImportError as e:
            results[f"E2/{name}"] = {"skipped": f"missing dependency: {e.name}"}
    return results


def _per_rule(items):
    """每條規則單獨使用時的偵測率與誤報率（找出誤報的來源）。"""
    rules = sorted({r for i in items for r in i["rules"]})
    pos = [i for i in items if i["anomalous"]]
    neg = [i for i in items if not i["anomalous"]]
    return {r: {"detection_rate": sum(r in i["rules"] for i in pos) / len(pos) if pos else None,
                "false_alarm_rate": sum(r in i["rules"] for i in neg) / len(neg) if neg else None}
            for r in rules}


def _truth(t):
    return {"anomalous": t["anomalous"], "change_point": t["change_point"], "kind": t["anomaly"],
            "data_kind": t["data_kind"]}


def _by_kind(items, truths):
    out = {"all": detection_scores(items)}
    # 偏態計數資料單獨列，才看得出 3σ 誤判
    count = [i for i in items if i["data_kind"] == "count"]
    if count:
        out["count"] = detection_scores(count)
    for kind in sorted({t["anomaly"] for t in truths} - {"normal"}):
        sel = [i for i in items if i["kind"] == kind]
        out[kind] = {"detection_rate": detection_scores(sel)["detection_rate"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--per-rule", action="store_true", help="另外列出每條規則單獨的偵測率/誤報率")
    a = ap.parse_args()
    results = run(a.seed)
    rows = []
    for name, r in results.items():
        if "skipped" in r:
            rows.append({"method": name, "note": r["skipped"]})
            continue
        rows.append({"method": name, **r["all"],
                     "count_FAR": r.get("count", {}).get("false_alarm_rate"),
                     **{f"DR_{k}": v["detection_rate"] for k, v in r.items()
                        if k not in ("all", "count", "per_rule")}})
    cols = ["method", "detection_rate", "false_alarm_rate", "median_delay", "median_cp_error",
            "count_FAR", "DR_shift", "DR_drift", "DR_outlier", "DR_count_shift", "note"]
    print_table(rows, cols)
    if a.per_rule:
        for name, r in results.items():
            if r.get("per_rule"):
                print()
                print(f"{name} per rule:")
                print_table([{"rule": k, **v} for k, v in r["per_rule"].items()],
                            ["rule", "detection_rate", "false_alarm_rate"])
    print("saved:", save_result("analysis", a.seed, {"results": results}))


if __name__ == "__main__":
    main()
