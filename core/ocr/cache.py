"""已確認文字的快取：儲存格原始像素 → 用 hwnd 精確讀到的文字。

同一個 ID 每次畫出來的像素都一樣，所以開圖確認過一次，之後看到同樣的像素就直接用，
不必再開圖。key 用原始像素（不是二值化遮罩）：A 和 Å 的遮罩相同，像素不同。
差一個像素就不會命中，不會因為快取而讀錯。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class VerifiedCache:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.data: dict[str, str] = {}
        self.hits = self.misses = 0
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def key(img) -> str:
        img = img.convert("RGB")
        return hashlib.sha1(f"{img.width}x{img.height}".encode() + img.tobytes()).hexdigest()

    def get(self, img) -> str | None:
        v = self.data.get(self.key(img))
        if v is None:
            self.misses += 1
        else:
            self.hits += 1
        return v

    def put(self, img, text: str) -> None:
        self.data[self.key(img)] = text

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
