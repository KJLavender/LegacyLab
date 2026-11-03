"""變化點偵測（E2）：回答「從哪一點、哪一個 lot 開始變」。

- cusum：雙邊表格式 CUSUM，線上偵測，回報警報點與估計的起點
- pelt：ruptures 的 PELT，離線找變化點（選用）
- adwin：river 的 ADWIN，線上偵測（選用）

全部回傳 `ChangeResult`；`lot_at()` 把 index 對回 Batch Lot。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ChangeResult:
    detected: bool
    alarm_idx: int | None        # 第一次發出警報的點（算偵測延遲用）
    change_idx: int | None       # 估計的實際變化起點
    method: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _robust_ref(x, phase1):
    ref = x[:phase1] if phase1 else x[: max(10, len(x) // 3)]
    mu = float(np.median(ref))
    mr = np.abs(np.diff(ref))
    sigma = float(np.median(mr) / 0.954) if len(mr) else 1.0
    return mu, sigma or 1.0


def cusum(x, k: float = 0.5, h: float = 5.0, phase1: int | None = None) -> ChangeResult:
    """k、h 以 σ 為單位；h=5 對應約 1σ 平移的平均偵測延遲 ~10 點。"""
    x = np.asarray(x, float)
    mu, sigma = _robust_ref(x, phase1)
    z = (x - mu) / sigma
    hi = lo = 0.0
    last_zero_hi = last_zero_lo = 0
    for i, v in enumerate(z):
        hi = max(0.0, hi + v - k)
        lo = max(0.0, lo - v - k)
        if hi == 0:
            last_zero_hi = i + 1
        if lo == 0:
            last_zero_lo = i + 1
        if hi > h:
            return ChangeResult(True, i, last_zero_hi, "cusum")
        if lo > h:
            return ChangeResult(True, i, last_zero_lo, "cusum")
    return ChangeResult(False, None, None, "cusum")


def pelt(x, penalty: float | None = None) -> ChangeResult:
    import ruptures as rpt  # 選用相依

    x = np.asarray(x, float)
    _, sigma = _robust_ref(x, None)
    pen = penalty if penalty is not None else 3 * np.log(len(x)) * sigma ** 2
    bkps = rpt.Pelt(model="l2", min_size=5).fit(x.reshape(-1, 1)).predict(pen=pen)
    cps = [b for b in bkps if b < len(x)]
    if not cps:
        return ChangeResult(False, None, None, "pelt")
    # 離線方法看完整段才知道，所以警報點記為最後一點
    return ChangeResult(True, len(x) - 1, cps[0], "pelt")


def adwin(x, delta: float = 0.002) -> ChangeResult:
    from river import drift  # 選用相依

    # 預設 clock=32（每 32 點才檢查一次），對 60 點的序列太稀疏；先標準化再逐點檢查
    x = np.asarray(x, float)
    mu, sigma = _robust_ref(x, None)
    det = drift.ADWIN(delta=delta, clock=1, grace_period=10)
    for i, v in enumerate((x - mu) / sigma):
        det.update(float(v))
        if det.drift_detected:
            return ChangeResult(True, i, max(0, i - int(det.width)), "adwin")
    return ChangeResult(False, None, None, "adwin")


def lot_at(lots: list[str], idx: int | None) -> str | None:
    return lots[idx] if idx is not None and 0 <= idx < len(lots) else None


DETECTORS = {"cusum": cusum, "pelt": pelt, "adwin": adwin}
