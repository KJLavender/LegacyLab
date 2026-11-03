"""固定字型的模板比對 OCR。

舊系統的自繪表格通常是同一個字型、同一個大小、整數像素位置，每個字元每次畫出來都一樣，
所以把字元的點陣存成樣板、逐一比對，就能做到接近 100% 而且不需要模型。

- train()：給「儲存格圖片 + 正確文字」，自動切字並學樣板（只學切得剛好的）
- read_line()：切字後比對；字元黏在一起時用動態規劃拆成多個樣板
- 認不出的字元輸出 "?"，不亂猜
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.ocr.base import ink_mask


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    cols = mask.any(axis=0)
    segs, start = [], None
    for x, on in enumerate(cols):
        if on and start is None:
            start = x
        elif not on and start is not None:
            segs.append((start, x))
            start = None
    if start is not None:
        segs.append((start, len(cols)))
    return segs


def _rows(mask: np.ndarray) -> tuple[int, int]:
    rows = np.flatnonzero(mask.any(axis=1))
    return (int(rows[0]), int(rows[-1]) + 1) if len(rows) else (0, mask.shape[0])


class TemplateOcr:
    name = "template"

    def __init__(self, frac: float = 0.5, space_px: int = 4, max_cost: float = 0.2):
        self.frac = frac
        self.space_px = space_px
        self.max_cost = max_cost
        self.height: int | None = None              # 樣板高度（= 儲存格高度）
        self.glyphs: dict[str, list[np.ndarray]] = {}
        self._exact: dict[bytes, str] = {}
        self._ambig: dict[bytes, set[str]] = {}       # 點陣完全相同的字（例如 I 和 l）
        self.last_uncertain = False                    # 上一次 read_line 有歧義字或認不出的字

    @property
    def confusable(self) -> set[str]:
        """在任何一種畫法（一般列／反白列）下點陣相同過的字。輸出這些字就算沒把握，
        因為同一個字在另一種畫法下可能還沒學到歧義。"""
        return {c for group in self._ambig.values() for c in group}

    # ---------- 學習 ----------

    def _mask(self, img) -> np.ndarray:
        m = ink_mask(img, self.frac)
        if self.height is None:
            self.height = m.shape[0]
        elif m.shape[0] != self.height:
            raise ValueError(f"cell height {m.shape[0]} != template height {self.height}")
        return m

    def _add(self, ch: str, g: np.ndarray) -> None:
        """ch 可以是多個字（相黏的連字樣板，例如 "ri"）。"""
        key = self._key(g)
        if key in self._exact:
            if self._exact[key] != ch and len(ch) == 1 == len(self._exact[key]):
                self._ambig.setdefault(key, {self._exact[key]}).add(ch)
            return
        self._exact[key] = ch
        self.glyphs.setdefault(ch, []).append(g)

    @staticmethod
    def _key(g: np.ndarray) -> bytes:
        return g.shape[1].to_bytes(2, "little") + np.packbits(g).tobytes()

    def train(self, samples, max_passes: int = 4) -> dict:
        """samples: iterable of (PIL image, text)。

        第一輪只學「區段數 = 字數」的樣本；之後幾輪用已知樣板把黏在一起的區段拆開，
        從剩下唯一不認得的區段學新字元，直到學不到新東西為止。
        """
        pending = []
        for img, text in samples:
            mask = self._mask(img)
            chars = text.replace(" ", "")
            segs = [mask[:, s:e] for s, e in _segments(mask)]
            if len(segs) == len(chars):
                for g, ch in zip(segs, chars):
                    self._add(ch, g)
            else:
                pending.append((segs, chars))
        for _ in range(max_passes):
            before = len(self._exact)
            pending = [p for p in pending if not self._align(*p)]
            if len(self._exact) == before:
                break
        return {"skipped": len(pending), "chars": len(self.glyphs), "variants": len(self._exact)}

    def _align(self, segs: list[np.ndarray], chars: str) -> bool:
        """把區段對到文字；能對齊就學下來並回傳 True。

        認得的區段長度固定；只剩一個不認得的區段時，它的長度由總字數反推（可能是連字）；
        有多個不認得的區段時，只有「各 1 字剛好對上總字數」才學。
        """
        texts = [self._match(g) for g in segs]
        known = [t if "?" not in t else None for t in texts]
        unknown = [i for i, t in enumerate(known) if t is None]
        if not unknown:
            return "".join(known) == chars
        rem = len(chars) - sum(len(t) for t in known if t)
        if len(unknown) == 1:
            lens = [len(t) if t else rem for t in known]     # 唯一的未知區段：長度由總字數反推
        elif rem == len(unknown):
            lens = [len(t) if t else 1 for t in known]
        else:
            return False   # 不知道哪一段是相黏的，不猜（用寬度猜會學到錯的連字）
        if rem < 1 or sum(lens) != len(chars):
            return False
        pos, conflicts = 0, []
        for g, t, n in zip(segs, known, lens):
            if t is not None and chars[pos:pos + n] != t:
                if n != 1:
                    return False
                conflicts.append((g, chars[pos]))   # 點陣相同、字不同 → 歧義（例如 I / l）
            pos += n
        if len(conflicts) > 1:
            return False
        for g, ch in conflicts:
            self._add(ch, g)
        pos = 0
        for g, t, n in zip(segs, known, lens):
            if t is None:
                self._add(chars[pos:pos + n], g)
            pos += n
        return True

    # ---------- 辨識 ----------

    def read_line(self, img) -> str:
        if not self.glyphs:
            raise RuntimeError("TemplateOcr has no templates; call train() or load() first")
        if img.height != self.height:
            self.last_uncertain = True
            return "?"   # 字型大小不同（例如 DPI 縮放），模板不適用，交給下一個引擎
        mask = self._mask(img)
        out, amb, prev_end = [], {}, None
        for s, e in _segments(mask):
            if prev_end is not None and s - prev_end >= self.space_px:
                out.append(" ")
            g = mask[:, s:e]
            if self._key(g) in self._ambig:
                amb[len(out)] = self._ambig[self._key(g)]
            out.append(self._match(g))
            prev_end = e
        for i, cands in amb.items():
            out[i] = self._pick_case(out, i, cands)
        # 用了歧義字（點陣相同的 I/l、A/Å…）或有認不出的字，就算沒把握
        self.last_uncertain = bool(amb) or "?" in out or any(c in self.confusable for c in out)
        return "".join(out)

    @staticmethod
    def _pick_case(out: list[str], i: int, cands: set[str]) -> str:
        """點陣相同的字依同一個詞其他字母的大小寫決定（"variabIe" → "variable"）。"""
        word = "".join(c for j, c in enumerate(out) if j != i)
        lower = sum(c.islower() for c in word)
        upper = sum(c.isupper() for c in word)
        pref = [c for c in cands if (c.islower() if lower > upper else c.isupper())]
        return sorted(pref or cands)[0]

    def _match(self, seg: np.ndarray) -> str:
        hit = self._exact.get(self._key(seg))
        if hit is not None:
            return hit
        w = seg.shape[1]
        # best[i] = (累計成本, 文字)：前 i 欄的最佳拆法
        best: list[tuple[float, str] | None] = [None] * (w + 1)
        best[0] = (0.0, "")
        for i in range(w):
            if best[i] is None:
                continue
            for ch, variants in self.glyphs.items():
                for g in variants:
                    gw = g.shape[1]
                    if i + gw > w:
                        continue
                    part = seg[:, i:i + gw]
                    cost = np.count_nonzero(part ^ g) / max(1, np.count_nonzero(g))
                    if cost > self.max_cost:
                        continue
                    cand = (best[i][0] + cost, best[i][1] + ch)
                    j = i + gw
                    # 相鄰字元可能共用一欄（字距 0 或負），允許下一個字從 j-1 開始
                    for k in (j, j - 1):
                        if i < k <= w and (best[k] is None or cand[0] < best[k][0]):
                            best[k] = cand
        return best[w][1] if best[w] is not None else "?"

    # ---------- 存檔 ----------

    def save(self, path: Path | str) -> None:
        def enc(g):
            return {"w": int(g.shape[1]), "bits": np.packbits(g).tobytes().hex()}

        by_key = {self._key(g): g for gs in self.glyphs.values() for g in gs}
        doc = {"height": self.height, "frac": self.frac,
               "glyphs": {ch: [enc(g) for g in gs] for ch, gs in self.glyphs.items()},
               # 點陣相同的字：第二個字不會進 glyphs，要另外存，不然讀回來就忘了
               "ambiguous": [{"chars": sorted(chars), **enc(by_key[k])}
                             for k, chars in self._ambig.items() if k in by_key]}
        Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str, **kw) -> "TemplateOcr":
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        self = cls(frac=doc["frac"], **kw)
        self.height = doc["height"]

        def dec(g):
            n = self.height * g["w"]
            bits = np.unpackbits(np.frombuffer(bytes.fromhex(g["bits"]), np.uint8))[:n]
            return bits.reshape(self.height, g["w"]).astype(bool)

        for ch, gs in doc["glyphs"].items():
            for g in gs:
                self._add(ch, dec(g))
        for a in doc.get("ambiguous", []):
            for ch in a["chars"]:
                self._add(ch, dec(a))
        return self
