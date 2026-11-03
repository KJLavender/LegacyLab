"""評分指標，對應計畫「評分方式」表。"""
from __future__ import annotations

import statistics

from core.text import levenshtein  # noqa: F401  (bench 也直接用)


def char_accuracy(truths: list[str], preds: list[str]) -> float:
    """1 − 編輯距離 / 字元數（整份資料加總後再算）。"""
    total = sum(len(t) for t in truths)
    dist = sum(levenshtein(t, p) for t, p in zip(truths, preds))
    return max(0.0, 1 - dist / total) if total else 1.0


def row_exact(truth_rows: list[list[str]], pred_rows: list[list[str]]) -> float:
    if not truth_rows:
        return 1.0
    ok = sum(t == p for t, p in zip(truth_rows, pred_rows))
    return ok / len(truth_rows)


def detection_scores(items: list[dict]) -> dict:
    """items: {anomalous: bool(真實), detected: bool, change_point: int|None, alarm_idx: int|None}"""
    pos = [i for i in items if i["anomalous"]]
    neg = [i for i in items if not i["anomalous"]]
    tp = [i for i in pos if i["detected"]]
    fp = [i for i in neg if i["detected"]]
    delays = [i["alarm_idx"] - i["change_point"] for i in tp
              if i.get("change_point") is not None and i.get("alarm_idx") is not None
              and i["alarm_idx"] >= i["change_point"]]
    return {
        "detection_rate": len(tp) / len(pos) if pos else None,
        "false_alarm_rate": len(fp) / len(neg) if neg else None,
        "median_delay": statistics.median(delays) if delays else None,
        "n_pos": len(pos), "n_neg": len(neg),
    }
