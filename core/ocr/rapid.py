"""RapidOCR（PP-OCR 的 ONNX 版）引擎。選用相依：pip install -e .[ocr]"""
from __future__ import annotations

import numpy as np


class RapidOcr:
    name = "rapidocr"

    # 預設只允許 ASCII 可見字元和 Å；中文模型常幻想出「個」之類的字
    DEFAULT_ALLOWED = frozenset(chr(c) for c in range(0x20, 0x7F)) | {"Å"}

    def __init__(self, upscale: int = 3, allowed: frozenset[str] | None = DEFAULT_ALLOWED):
        from rapidocr_onnxruntime import RapidOCR

        self.engine = RapidOCR()
        self.upscale = upscale
        self.allowed = allowed

    def read_line(self, img) -> str:
        # 儲存格很小，放大後只跑辨識（不跑偵測），對單行文字比較準
        img = img.convert("RGB")
        if self.upscale > 1:
            from PIL import Image

            img = img.resize((img.width * self.upscale, img.height * self.upscale), Image.LANCZOS)
        result, _ = self.engine(np.asarray(img), use_det=False, use_cls=False, use_rec=True)
        if not result:
            return ""
        text = "".join(r[0] for r in result).strip()
        if self.allowed is not None:
            text = "".join(c for c in text if c in self.allowed)
        return text
