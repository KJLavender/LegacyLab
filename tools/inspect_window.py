"""列出視窗的控制項樹，並檢查每個控制項透過 MSAA 能拿到什麼文字。

目的：在寫 OCR 之前，先確認真系統的表格、圖表標題有沒有用 MSAA 提供文字。
有的話，那部分就不需要 OCR。只讀取，不點擊、不輸入。

    python tools/inspect_window.py --title-re "<真系統視窗標題>"
    python tools/inspect_window.py --title-re "LegacyApp" --json out.json

MSAA 需要 comtypes（pip install comtypes）；沒有時只列 Win32 資訊。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import win32  # noqa: E402

OBJID_CLIENT = -4
CHILDID_SELF = 0


def msaa_reader():
    try:
        import comtypes.client
        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen.Accessibility import IAccessible
    except Exception as e:  # comtypes 沒裝或 oleacc 型別庫載入失敗
        print(f"(MSAA disabled: {e})", file=sys.stderr)
        return None

    oleacc = ctypes.oledll.oleacc

    def read(hwnd: int) -> dict:
        acc = ctypes.POINTER(IAccessible)()
        try:
            oleacc.AccessibleObjectFromWindow(hwnd, ctypes.c_long(OBJID_CLIENT).value & 0xFFFFFFFF,
                                              ctypes.byref(IAccessible._iid_), ctypes.byref(acc))
        except OSError as e:
            return {"error": str(e)}
        out = {}
        for prop in ("accName", "accValue", "accRole", "accChildCount"):
            try:
                v = getattr(acc, prop)
                v = v(CHILDID_SELF) if callable(v) else v
                if prop == "accRole":
                    buf = ctypes.create_unicode_buffer(64)
                    oleacc.GetRoleTextW(v, buf, 64)
                    v = buf.value
                out[prop[3:].lower()] = v
            except Exception:
                pass
        return out

    return read


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--title-re")
    g.add_argument("--hwnd", type=lambda s: int(s, 0))
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    hwnd = a.hwnd or (w.hwnd if (w := win32.find_window(title_re=a.title_re)) else None)
    if not hwnd:
        raise SystemExit("window not found")
    read = msaa_reader()
    rows = []
    for w in [win32.describe(hwnd), *win32.children(hwnd, visible_only=False)]:
        row = {"hwnd": hex(w.hwnd), "class": w.cls, "id": w.ctrl_id, "text": w.text,
               "size": w.size}
        if read:
            row["msaa"] = read(w.hwnd)
        rows.append(row)
        msaa = row.get("msaa", {})
        print(f"{row['hwnd']:>10} {w.cls[:40]:40} id={w.ctrl_id:<5} {w.size!s:12} "
              f"text={w.text[:30]!r} msaa_name={str(msaa.get('name'))[:30]!r} "
              f"value={str(msaa.get('value'))[:20]!r} role={msaa.get('role')} children={msaa.get('childcount')}")
    if a.json:
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    # 提示：沒有任何文字來源的大型控制項，就是需要 OCR 的地方
    blind = [r for r in rows if not r["text"] and not (r.get("msaa") or {}).get("name")
             and r["size"][0] * r["size"][1] > 20000]
    if blind:
        print("\nlarge controls with no text via Win32/MSAA (OCR needed):")
        for r in blind:
            print(f"  {r['hwnd']} {r['class']} {r['size']}")


if __name__ == "__main__":
    main()
