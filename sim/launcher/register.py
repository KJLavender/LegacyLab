"""在 HKCU 註冊／移除 legacyapp:// 協定（不需要系統管理員權限）。

只有想用瀏覽器真的點入口網站連結時才需要；bench 直接呼叫 handler.py，不用註冊。

    python sim/launcher/register.py install
    python sim/launcher/register.py uninstall
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

KEY = r"Software\Classes\legacyapp"
HANDLER = Path(__file__).resolve().parent / "handler.py"


def install() -> None:
    cmd = f'"{sys.executable}" "{HANDLER}" "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:LegacyApp Protocol")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\shell\open\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)
    print("registered:", cmd)


def uninstall() -> None:
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY + sub)
        except FileNotFoundError:
            pass
    print("unregistered")


if __name__ == "__main__":
    {"install": install, "uninstall": uninstall}[sys.argv[1]]()
