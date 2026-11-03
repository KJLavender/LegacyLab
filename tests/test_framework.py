import json

import numpy as np
import pytest
from PIL import Image

from core.locator import LocateFailed, Locator, Strategy
from core.ocr.base import FallbackOcr, ink_mask
from core.ocr.template import TemplateOcr
from core.trace import Trace
from plugins.base import WriteBlocked
from plugins.legacyapp import LegacyAppPlugin

# 3×5 的點陣字，模擬固定字型
FONT = {
    "A": ["010", "101", "111", "101", "101"],
    "B": ["110", "101", "110", "101", "110"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
}


def render(text, gap=1, selected=False, height=9):
    cols = []
    for i, ch in enumerate(text):
        g = np.array([[c == "1" for c in row] for row in FONT[ch]])
        cols.append(g)
        if i < len(text) - 1:
            cols.append(np.zeros((5, gap), bool))
    m = np.hstack(cols)
    canvas = np.zeros((height, m.shape[1] + 6), bool)
    canvas[2:7, 3:3 + m.shape[1]] = m
    fg, bg = ((255, 255, 255), (0, 120, 215)) if selected else ((0, 0, 0), (255, 255, 255))
    a = np.where(canvas[..., None], fg, bg).astype(np.uint8)
    return Image.fromarray(a)


def test_ink_mask_handles_selected_rows():
    assert ink_mask(render("AB")).sum() == ink_mask(render("AB", selected=True)).sum()


def test_template_ocr_learns_and_reads():
    ocr = TemplateOcr()
    ocr.train([(render("AB"), "AB"), (render("01"), "01")])
    assert ocr.read_line(render("BA10")) == "BA10"
    assert ocr.read_line(render("A0", selected=True)) == "A0"


def test_template_ocr_splits_touching_glyphs():
    ocr = TemplateOcr()
    ocr.train([(render("AB"), "AB"), (render("01"), "01")])
    assert ocr.read_line(render("A1", gap=0)) == "A1"


def test_template_ocr_unknown_is_question_mark_and_roundtrip(tmp_path):
    ocr = TemplateOcr()
    ocr.train([(render("A0"), "A0")])
    assert "?" in ocr.read_line(render("AB"))
    ocr.save(tmp_path / "t.json")
    again = TemplateOcr.load(tmp_path / "t.json")
    assert again.read_line(render("0A")) == "0A"


def test_template_ocr_remembers_ambiguous_glyphs_after_save(tmp_path):
    FONT["Å"] = FONT["A"]          # 小圈被濾掉時，Å 和 A 點陣相同
    try:
        ocr = TemplateOcr()
        ocr.train([(render("AB"), "AB"), (render("Å0"), "Å0")])
        ocr.save(tmp_path / "t.json")
        again = TemplateOcr.load(tmp_path / "t.json")
        assert again.confusable == {"A", "Å"}
        again.read_line(render("B0"))
        assert again.last_uncertain is False
        again.read_line(render("BA"))
        assert again.last_uncertain is True   # 輸出了可能是 Å 的 A，要交給上層確認
    finally:
        del FONT["Å"]


def test_fallback_ocr_uses_next_engine_only_when_unsure():
    class Fixed:
        def __init__(self, name, text):
            self.name, self.text = name, text

        def read_line(self, img):
            return self.text

    f = FallbackOcr(Fixed("a", "A?C"), Fixed("b", "ABC"))
    assert f.read_line(None) == "ABC" and f.used == {"b": 1}
    f = FallbackOcr(Fixed("a", "ABC"), Fixed("b", "XXX"))
    assert f.read_line(None) == "ABC" and f.used == {"a": 1}


def test_locator_falls_back_in_layer_order():
    Locator.stats.clear()
    calls = []

    def hwnd():
        calls.append("hwnd")
        return None

    def ocr():
        calls.append("ocr")
        return "value"

    def api():
        calls.append("api")
        raise OSError("down")

    loc = Locator("thing", Strategy("ocr", ocr), Strategy("hwnd", hwnd), Strategy("api", api))
    assert loc.resolve() == "value"
    assert calls == ["api", "hwnd", "ocr"]
    assert Locator.report() == {"thing": {"ocr": 1}}
    with pytest.raises(LocateFailed):
        Locator("never", Strategy("hwnd", lambda: None)).resolve()


def test_write_actions_blocked_by_default():
    p = LegacyAppPlugin({"user": "u", "password": "p"})
    with pytest.raises(WriteBlocked):
        p.exclude_last_point("C0011")
    with pytest.raises(ValueError):
        LegacyAppPlugin({"user": "u", "password": "p"}, allow_write={"delete_everything"})


def test_dialog_rules_cannot_answer_modify_confirmations():
    with pytest.raises(ValueError):
        LegacyAppPlugin({"user": "u", "password": "p",
                         "dialog_rules": {"This will modify the database": "Yes"}})


def test_trace_records_failed_step(tmp_path):
    t = Trace(tmp_path, "unit")
    with pytest.raises(RuntimeError):
        with t.step("outer"):
            with t.step("inner"):
                raise RuntimeError("boom")
    path = t.save()
    steps = json.loads(path.read_text(encoding="utf-8"))
    assert steps[0]["ok"] is False and steps[0]["children"][0]["error"] == "RuntimeError: boom"
    assert "traceback" in steps[0]["children"][0] and "traceback" not in steps[0]
