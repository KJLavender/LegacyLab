"""OCR 引擎介面：grid 只認這個介面，引擎可以換（模板比對 / RapidOCR / Windows OCR）。"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class OcrEngine(Protocol):
    name: str

    def read_line(self, img) -> str:
        """辨識單行文字（一個表格儲存格）。img 是 PIL Image。"""
        ...


class FallbackOcr:
    """依序嘗試多個引擎；前一個結果含 "?"（認不出）或空白才換下一個。記錄每個引擎用了幾次。"""

    def __init__(self, *engines: OcrEngine):
        self.engines = engines
        self.name = "+".join(e.name for e in engines)
        self.used: dict[str, int] = {}
        self.last = ""   # 上一次由哪個引擎認出（"unresolved" 表示都認不出）

    def read_line(self, img) -> str:
        text = ""
        for eng in self.engines:
            text = eng.read_line(img)
            if text and "?" not in text:
                self.used[eng.name] = self.used.get(eng.name, 0) + 1
                self.last = eng.name
                return text
        self.used["unresolved"] = self.used.get("unresolved", 0) + 1
        self.last = "unresolved"
        return text

    @property
    def last_uncertain(self) -> bool:
        """第一個引擎沒把握（換了引擎、或第一個引擎遇到歧義字）。"""
        first = self.engines[0]
        return self.last != first.name or getattr(first, "last_uncertain", False)


def ink_mask(img, frac: float = 0.5, floor: int = 60) -> np.ndarray:
    """前景（字）= 和背景色差異超過「最大差異 × frac」的像素。

    背景色取最常見的顏色，所以反白列（白字藍底）也適用；
    用相對門檻去掉 ClearType 的彩色邊緣，相鄰字元才不會黏在一起。
    """
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    flat = a.reshape(-1, 3)
    colors, counts = np.unique(flat, axis=0, return_counts=True)
    bg = colors[counts.argmax()]
    d = np.abs(a - bg).sum(axis=2)
    return d > max(floor, frac * int(d.max()))
