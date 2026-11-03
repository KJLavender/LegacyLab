"""定位方式依序退回（參考 UFO² 的混合 GUI/API 與 Terminator 的選擇器）。

順序：api → hwnd → msaa → image → ocr。前一層拿不到才往下一層，
每次用到哪一層都記到 stats 與 trace，bench 才看得出哪一層最常退回。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

LAYERS = ("api", "hwnd", "msaa", "image", "ocr")


class LocateFailed(LookupError):
    pass


@dataclass
class Strategy:
    layer: str
    fn: Callable[..., Any]   # 回傳 None 或丟例外代表這一層失敗

    def __post_init__(self):
        if self.layer not in LAYERS:
            raise ValueError(f"unknown layer {self.layer!r}")


class Locator:
    stats: Counter = Counter()   # 全域統計：(目標, 層) -> 次數

    def __init__(self, target: str, *strategies: Strategy, trace=None):
        self.target = target
        self.strategies = sorted(strategies, key=lambda s: LAYERS.index(s.layer))
        self.trace = trace

    def resolve(self, *args, **kwargs) -> Any:
        errors = []
        for s in self.strategies:
            try:
                v = s.fn(*args, **kwargs)
            except Exception as e:
                errors.append(f"{s.layer}: {type(e).__name__}: {e}")
                continue
            if v is not None:
                Locator.stats[(self.target, s.layer)] += 1
                if self.trace:
                    self.trace.note(**{f"layer:{self.target}": s.layer})
                return v
            errors.append(f"{s.layer}: no result")
        Locator.stats[(self.target, "failed")] += 1
        raise LocateFailed(f"{self.target}: all layers failed -> {errors}")

    @classmethod
    def report(cls) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for (target, layer), n in cls.stats.items():
            out.setdefault(target, {})[layer] = n
        return out
