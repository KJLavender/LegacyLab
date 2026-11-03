"""Win32 操作（只用 ctypes）：找視窗、讀寫控制項、選單、背景點擊、擷圖、對話框處理。

滑鼠與鍵盤一律用 PostMessage 送到目標視窗，不移動游標、不需要前景焦點，
所以混沌模式的「搶焦點」不會打斷流程。
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.CloseHandle.argtypes = [wt.HANDLE]

# 座標一律用實體像素；DPI 縮放時和擷圖對得上
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except (AttributeError, OSError):
    pass

WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH = 0x000C, 0x000D, 0x000E
WM_COMMAND, WM_CLOSE = 0x0111, 0x0010
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
BM_CLICK = 0x00F5
CB_SELECTSTRING, CB_GETCURSEL = 0x014D, 0x0147
CBN_SELCHANGE = 1
SMTO_ABORTIFHUNG = 0x0002
GW_OWNER = 4
PW_RENDERFULLCONTENT = 2

VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "up": 0x26, "down": 0x28,
      "pageup": 0x21, "pagedown": 0x22, "home": 0x24, "end": 0x23}

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetWindow.restype = wt.HWND
user32.GetParent.restype = wt.HWND
user32.GetMenu.restype = wt.HMENU
user32.GetSubMenu.restype = wt.HMENU
user32.GetSubMenu.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetMenuItemCount.argtypes = [wt.HMENU]
user32.GetMenuItemID.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wt.UINT
user32.GetMenuStringW.argtypes = [wt.HMENU, wt.UINT, wt.LPWSTR, ctypes.c_int, wt.UINT]
user32.GetDlgItem.restype = wt.HWND
user32.GetDC.restype = wt.HDC
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
user32.GetDC.argtypes = [wt.HWND]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]


class Win32Error(RuntimeError):
    pass


class UnexpectedDialog(Win32Error):
    """出現多按鈕對話框：框架不替使用者做決定。"""

    def __init__(self, hwnd: int, title: str, text: str, buttons: list[str]):
        super().__init__(f"unexpected dialog '{title}': {text!r} buttons={buttons}")
        self.hwnd, self.title, self.text, self.buttons = hwnd, title, text, buttons


@dataclass
class Win:
    hwnd: int
    cls: str
    text: str
    rect: tuple[int, int, int, int]   # 螢幕座標 left, top, right, bottom
    ctrl_id: int

    @property
    def size(self) -> tuple[int, int]:
        return self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]


# ---------- 行程 ----------

class PidProcess:
    """只知道 PID 的行程（例如由協定處理程式啟動的），提供和 subprocess.Popen 相同的幾個方法。"""

    SYNCHRONIZE, TERMINATE, QUERY = 0x00100000, 0x0001, 0x1000
    STILL_ACTIVE = 259

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: int | None = None
        self._h = kernel32.OpenProcess(self.SYNCHRONIZE | self.TERMINATE | self.QUERY, False, pid)
        if not self._h:
            raise Win32Error(f"cannot open process {pid}")

    def poll(self) -> int | None:
        code = wt.DWORD()
        kernel32.GetExitCodeProcess(self._h, ctypes.byref(code))
        if code.value != self.STILL_ACTIVE:
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        import subprocess

        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if kernel32.WaitForSingleObject(self._h, ms) != 0:
            raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout)
        return self.poll()

    def kill(self) -> None:
        kernel32.TerminateProcess(self._h, 1)

    def __del__(self):
        if getattr(self, "_h", None):
            kernel32.CloseHandle(self._h)


# ---------- 查詢 ----------

def get_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_text(hwnd: int, timeout_ms: int = 1000) -> str:
    """跨行程讀控制項文字要用 WM_GETTEXT（GetWindowText 讀不到別人的 Edit）。"""
    res = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(hwnd, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(res)):
        return ""
    n = res.value + 1
    buf = ctypes.create_unicode_buffer(n)
    user32.SendMessageTimeoutW(hwnd, WM_GETTEXT, n, ctypes.addressof(buf), SMTO_ABORTIFHUNG, timeout_ms,
                               ctypes.byref(res))
    return buf.value


def get_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def get_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def describe(hwnd: int) -> Win:
    return Win(hwnd, get_class(hwnd), get_text(hwnd), get_rect(hwnd), user32.GetDlgCtrlID(hwnd))


def top_windows(pid: int | None = None, visible_only: bool = True) -> list[Win]:
    out: list[int] = []

    def cb(h, _):
        if (not visible_only or user32.IsWindowVisible(h)) and (pid is None or get_pid(h) == pid):
            out.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return [describe(h) for h in out]


def children(hwnd: int, visible_only: bool = True) -> list[Win]:
    """所有子孫視窗（EnumChildWindows 本來就會遞迴）。"""
    out: list[int] = []

    def cb(h, _):
        if not visible_only or user32.IsWindowVisible(h):
            out.append(h)
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return [describe(h) for h in out]


def find_window(title: str | None = None, title_re: str | None = None, cls: str | None = None,
                pid: int | None = None) -> Win | None:
    for w in top_windows(pid):
        if cls and w.cls != cls:
            continue
        if title is not None and w.text != title:
            continue
        if title_re and not re.search(title_re, w.text):
            continue
        return w
    return None


def find_child(parent: int, cls: str | None = None, text: str | None = None,
               ctrl_id: int | None = None, pred=None) -> Win | None:
    for w in children(parent):
        if cls and w.cls != cls and not w.cls.startswith(cls):
            continue
        if text is not None and w.text != text:
            continue
        if ctrl_id is not None and w.ctrl_id != ctrl_id:
            continue
        if pred and not pred(w):
            continue
        return w
    return None


def wait_until(fn, timeout: float = 10.0, interval: float = 0.1, desc: str = "condition"):
    end = time.monotonic() + timeout
    while True:
        v = fn()
        if v:
            return v
        if time.monotonic() > end:
            raise TimeoutError(f"timed out waiting for {desc} ({timeout}s)")
        time.sleep(interval)


def is_alive(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def is_enabled(hwnd: int) -> bool:
    return bool(user32.IsWindowEnabled(hwnd))


# ---------- 操作 ----------

def set_text(hwnd: int, text: str) -> None:
    buf = ctypes.create_unicode_buffer(text)
    user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.addressof(buf))


def click_button(hwnd: int) -> None:
    # PostMessage：按鈕若會開模態對話框，SendMessage 會卡住直到對話框關閉
    user32.PostMessageW(hwnd, BM_CLICK, 0, 0)


def combo_select(hwnd: int, text: str) -> bool:
    buf = ctypes.create_unicode_buffer(text)
    idx = user32.SendMessageW(hwnd, CB_SELECTSTRING, ctypes.c_size_t(-1).value, ctypes.addressof(buf))
    if idx < 0:
        return False
    parent = user32.GetParent(hwnd)
    wparam = (CBN_SELCHANGE << 16) | (user32.GetDlgCtrlID(hwnd) & 0xFFFF)
    user32.SendMessageW(parent, WM_COMMAND, wparam, hwnd)
    return True


def _lparam(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def post_click(hwnd: int, x: int, y: int, double: bool = False) -> None:
    """在控制項的 client 座標點擊，不移動游標。"""
    lp = _lparam(x, y)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    if double:
        user32.PostMessageW(hwnd, WM_LBUTTONDBLCLK, 1, lp)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def post_key(hwnd: int, key: str | int) -> None:
    vk = VK[key] if isinstance(key, str) else key
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 1)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0xC0000001)


def close_window(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _menu_items(hmenu) -> list[tuple[str, int]]:
    items = []
    for i in range(user32.GetMenuItemCount(hmenu)):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(hmenu, i, buf, 256, 0x400)  # MF_BYPOSITION
        items.append((buf.value.replace("&", "").split("\t")[0], i))
    return items


def menu_command(hwnd: int, path: list[str]) -> None:
    """依選單路徑（例如 ["Tools", "Export Data", "With Batch Lot"]）送 WM_COMMAND。"""
    hmenu = user32.GetMenu(hwnd)
    if not hmenu:
        raise Win32Error(f"window {hwnd:#x} has no menu")
    for depth, name in enumerate(path):
        items = _menu_items(hmenu)
        match = [i for label, i in items if label.lower() == name.lower()]
        if not match:
            raise Win32Error(f"menu item {name!r} not found; have {[l for l, _ in items]}")
        if depth == len(path) - 1:
            cmd = user32.GetMenuItemID(hmenu, match[0])
            user32.PostMessageW(hwnd, WM_COMMAND, cmd & 0xFFFF, 0)
            return
        hmenu = user32.GetSubMenu(hmenu, match[0])


# ---------- 對話框 ----------

def dialogs(pid: int) -> list[Win]:
    return [w for w in top_windows(pid) if w.cls == "#32770"]


def dialog_info(dlg: int) -> tuple[str, list[Win]]:
    kids = children(dlg)
    text = " ".join(w.text for w in kids if w.cls == "Static" and w.text)
    buttons = [w for w in kids if w.cls == "Button" and w.text]
    return text, buttons


FILE_DIALOG_CLASSES = {"DUIViewWndClassName", "ComboBoxEx32", "DirectUIHWND"}


def is_file_dialog(dlg: int) -> bool:
    return any(w.cls in FILE_DIALOG_CLASSES for w in children(dlg, visible_only=False))


def button_label(text: str) -> str:
    """「是(&Y)」「&Yes」→「是」「Yes」，比對按鈕用。"""
    return re.sub(r"\(&?\w\)$", "", text.replace("&", "")).strip()


# MessageBox 標準按鈕的控制項 ID：不受 Windows 語系影響（中文是「否(&N)」，英文是「No」）
STD_BUTTON_IDS = {"OK": 1, "Cancel": 2, "Abort": 3, "Retry": 4, "Ignore": 5, "Yes": 6, "No": 7}


def handle_dialogs(pid: int, rules: dict[str, str] | None = None, skip_titles: tuple[str, ...] = ()) -> list[str]:
    """只自動按「單一按鈕」的對話框；多按鈕的對話框只照 rules（內文片段 → 按鈕文字）處理，
    沒有規則就丟 UnexpectedDialog。開檔/存檔對話框不在這裡處理。回傳已關掉的對話框內容。"""
    closed = []
    for d in dialogs(pid):
        if d.text in skip_titles or is_file_dialog(d.hwnd):
            continue
        text, buttons = dialog_info(d.hwnd)
        if len(buttons) == 1:
            click_button(buttons[0].hwnd)
            closed.append(f"{d.text}: {text}")
        elif len(buttons) > 1:
            answer = next((btn for frag, btn in (rules or {}).items() if frag in text), None)
            target = next((b for b in buttons if answer and (b.ctrl_id == STD_BUTTON_IDS.get(answer)
                                                              or button_label(b.text) == answer)), None)
            if target is None:
                raise UnexpectedDialog(d.hwnd, d.text, text, [b.text for b in buttons])
            click_button(target.hwnd)
            closed.append(f"{d.text}: {text} -> {answer} (rule)")
    return closed


# ---------- 擷圖 ----------

def capture(hwnd: int, crop_child: int | None = None):
    """用 PrintWindow 擷取視窗（被遮住也能擷）。crop_child 指定時裁出該子控制項。"""
    from PIL import Image

    l, t, r, b = get_rect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        raise Win32Error("window has empty rect (minimized?)")
    hdc_screen = user32.GetDC(0)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    bmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi32.SelectObject(hdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT):
            raise Win32Error("PrintWindow failed")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(0, hdc_screen)
    if crop_child:
        cl, ct, cr, cb = get_rect(crop_child)
        img = img.crop((cl - l, ct - t, cr - l, cb - t))
    return img


def is_blank(img, tol: int = 4) -> bool:
    """全黑或單色：螢幕鎖定、RDP 縮小時 GDI 擷圖常見的結果。"""
    lo, hi = img.convert("L").getextrema()
    return hi - lo <= tol


def window_tree(hwnd: int) -> list[dict]:
    return [{"hwnd": hex(w.hwnd), "class": w.cls, "text": w.text, "rect": w.rect, "id": w.ctrl_id}
            for w in [describe(hwnd), *children(hwnd, visible_only=False)]]
