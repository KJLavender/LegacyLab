"""AppPlugin 介面：換一個舊系統，只要新增一個實作這個介面的模組。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.trace import Trace


class WriteBlocked(PermissionError):
    """會改資料的動作，沒有明確允許就擋下。"""


class AppPlugin(ABC):
    name: str = "base"
    # 會改資料的動作清單；預設全部擋下
    write_actions: frozenset[str] = frozenset()

    def __init__(self, config: dict | None = None, trace: Trace | None = None,
                 allow_write: set[str] | frozenset[str] = frozenset()):
        self.config = config or {}
        self.trace = trace or Trace(None)
        unknown = set(allow_write) - set(self.write_actions)
        if unknown:
            raise ValueError(f"unknown write actions: {sorted(unknown)}")
        self.allow_write = frozenset(allow_write)

    def guard_write(self, action: str) -> None:
        if action in self.write_actions and action not in self.allow_write:
            raise WriteBlocked(f"write action {action!r} is blocked (pass allow_write={{{action!r}}} to enable)")

    @abstractmethod
    def launch(self) -> int:
        """啟動並登入，回傳主視窗 hwnd。"""

    @abstractmethod
    def query(self, **filters) -> list[dict[str, str]]:
        """查詢並回傳清單（每列一個 dict）。"""

    @abstractmethod
    def open_item(self, item_id: str) -> int:
        """開啟明細，回傳明細視窗 hwnd。"""

    @abstractmethod
    def close_item(self) -> None: ...

    @abstractmethod
    def export(self, item_id: str, out_dir: Path) -> Path:
        """匯出資料，回傳檔案路徑。"""

    @abstractmethod
    def analyze(self, path: Path) -> dict[str, Any]:
        """分析匯出的檔案，回傳結構化結果。"""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
