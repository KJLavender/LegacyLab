# LegacyLab

**English** | [繁體中文](README.zh-TW.md)

A self-contained lab for automating legacy Windows desktop systems (VB6-era GUIs with owner-drawn grids, modal busy dialogs, and no API). It contains a **simulated legacy system** with a known answer key, a **generic automation framework**, and a **benchmark** that scores every new idea against the old approach.

Nothing here touches a real company system or real data, so it can be developed and published openly.

## Components

| Path | What it is |
| --- | --- |
| `sim/datagen/` | Generates equipment, charts and measurements with injected anomalies (shift, drift, outliers, skewed counts) plus `answer_key.json`. Fixed seeds. |
| `sim/legacyapp/` | Fake legacy app in C# WinForms, built with the `csc.exe` that ships with Windows. Version MsgBox, LOGIN window, busy-wait dialog, owner-drawn grid (GDI text, no API), fixed 697×505 chart window, `Tools > Export Data`, a data-modifying `Exclude` menu. |
| `sim/portal/`, `sim/launcher/` | Fake portal + SSO (Starlette, 127.0.0.1 only) that issues one-time tokens, and a `legacyapp://` protocol handler that validates the URL and starts LegacyApp (like a VBS launcher). `register.py` registers the protocol under HKCU; the benchmark calls the handler directly and does not need it. |
| `sim/chaos.ini` | Chaos mode: random delays, popups (single- and multi-button), token expiry, focus stealing, DPI scaling, comma decimals. Levels `off` / `light` / `heavy`. |
| `core/win32.py` | ctypes-only Win32 layer: find windows, read/write controls, native menus, background clicks via `PostMessage`, `PrintWindow` capture, dialog policy. |
| `core/ocr/` | Swappable OCR engines: fixed-font **template matching**, **RapidOCR**, and `FallbackOcr` (template first, RapidOCR only when unsure). |
| `core/launcher.py` | Config-driven launch through the portal: log in, pick a function, read the protocol URL, hand it to the handler. |
| `core/locator.py` | Layered fallback: `api → hwnd → msaa → image → ocr`, with stats on which layer was used. |
| `core/trace.py` | Failure trace: per-step timing, and on failure a screenshot, window tree and traceback. |
| `plugins/` | `AppPlugin` interface and the `legacyapp` domain module. Write actions are blocked unless explicitly allowed. |
| `analysis/` | SPC (baseline 3σ, I-MR + Nelson rules, Laney c′ for counts, and the `shewhart` library behind the same interface) and change-point detection (CUSUM, PELT, ADWIN). |
| `bench/` | `analysis_bench` (E1/E2, `--per-rule`), `ocr_bench` (E3), `ocr_calibrate` (self-labels template OCR from exact chart titles read via Win32), `e2e_bench` (YAML tasks × chaos levels, `--portal`, `--dialog-rule`). Results go to `bench/results/*.json` with git commit and seed. |
| `tools/inspect_window.py` | Read-only dump of a window's control tree and MSAA text, to see what can be read without OCR. |

## Quick start

```bat
setup.bat
.venv\Scripts\python -m bench.analysis_bench --seed 42
.venv\Scripts\python -m bench.ocr_bench --engines template,rapidocr,template+rapidocr
.venv\Scripts\python -m bench.ocr_calibrate
.venv\Scripts\python -m bench.e2e_bench --levels off,light,heavy --repeats 3
.venv\Scripts\python -m bench.e2e_bench --portal
.venv\Scripts\python -m pytest
```

The fake login is `demo` / `demo123` (`sim/legacyapp/users.ini.example`). Copy it to `users.ini` to change it; never put real passwords there.

## Safety rules

- Read-only by default. Data-modifying actions (`write_actions`) raise `WriteBlocked` before any GUI interaction unless passed in `allow_write`.
- Single-button dialogs are dismissed automatically. Multi-button dialogs are answered only by `dialog_rules` (text fragment → standard button name such as `Yes` / `No`, matched by control ID so it works in any Windows language); anything else fails the run. The default is `{"Reconnect now?": "Yes"}`; pass `dialog_rules={}` or `--no-default-rules` for the strictest mode. Rules may not answer data-modifying confirmations.
- Company plugins, URLs and screenshots are excluded by `.gitignore`.
