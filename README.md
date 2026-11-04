# LegacyLab

**English** | [繁體中文](README.zh-TW.md)

LegacyLab is a practice ground for automating old Windows desktop programs, the kind built in VB6 that have no API, draw their tables by hand, and freeze behind "please wait" dialogs. You can't call such a program from code, so a script has to find its windows, read its text and click its buttons. That is fragile, and it is hard to tell whether a new trick really helps.

So this project gives you three things in one place: a fake legacy program whose correct answers are known, an automation framework, and a benchmark that scores every new idea against the old way. Nothing here touches a real company system or real data, so it is safe to publish.

## What is inside

| Path | What it is |
| --- | --- |
| `sim/datagen/` | Generates equipment, charts and measurements with hidden problems (a shift, a drift, outliers, skewed counts), plus `answer_key.json` with the right answers. Seeds are fixed, so results repeat. |
| `sim/legacyapp/` | The fake legacy program, written in C# WinForms and built with the `csc.exe` that comes with Windows. It has a version popup, a login window, a "busy" dialog, two tabs, dropdowns that load slowly and depend on each other, a hand-drawn grid (text painted with GDI, so no control to read), a standard ListView (`By Lot`), a fixed-size chart window, `Tools > Export Data`, an `Exclude` menu that changes data, and a session that expires mid-task and forces a new login. |
| `sim/portal/`, `sim/launcher/` | A fake web portal with single sign-on (SSO) on 127.0.0.1 only. It hands out one-time tokens. A `legacyapp://` handler checks the URL and starts the program, like a VBS launcher would. `register.py` registers that protocol for the current user. The benchmark calls the handler directly, so registering is not needed. |
| `sim/chaos.ini` | Chaos mode, to make runs messier: random delays, popups, expiring tokens, session timeout, slow lists, stolen focus, DPI scaling, commas as decimal marks. Levels are `off`, `light` and `heavy`. |
| `core/win32.py` | Win32 layer using only `ctypes`. Finds windows, reads and writes controls, uses native menus, clicks in the background with `PostMessage`, switches tabs, reads a ListView in another process (32-bit and 64-bit), and captures a control with `PrintWindow` after it has finished painting. |
| `core/ocr/` | Interchangeable OCR engines (OCR turns a picture of text into text): template matching for a fixed font, RapidOCR, and a mix that tries the template first and asks RapidOCR only when unsure. A cache remembers cells already confirmed through exact Win32 text. |
| `core/launcher.py` | Starts the program through the portal from a config: log in, pick a function, read the protocol URL, give it to the handler. |
| `core/locator.py` | Finds things in layers, from most to least reliable: `api`, `hwnd`, `msaa`, `image`, `ocr`. It records which layer was used. |
| `core/trace.py` | Failure trace: time per step, and on failure a screenshot, the window tree and the traceback. |
| `plugins/` | The `AppPlugin` interface and the `legacyapp` plugin. Actions that write data are blocked unless you allow them. |
| `analysis/` | Statistical process control (SPC: control charts that flag when a measurement leaves its normal range), change-point detection (finding where a series started to shift), and `pipeline.py`, where SPC raises the alarm and PELT finds the lot where the change began. |
| `bench/` | The benchmarks, see below. Results go to `bench/results/*.json` with the git commit and seed. |
| `tools/patrol.py` | Patrol: exports and analyzes every chart, then writes an HTML report with anomalies first. `--score` grades it against the answer key. |
| `tools/demo.py` | A slow, narrated run of the whole flow, with a screenshot per step. |
| `tools/inspect_window.py` | Read-only dump of a window's controls and MSAA text, to see what can be read without OCR. |

The benchmarks in `bench/`:

- `analysis_bench`: control-chart and change-point methods (`--per-rule` scores each rule alone).
- `ocr_bench`: OCR engines on the real screen of the fake program.
- `ocr_calibrate`: trains the template OCR from chart titles read exactly through Win32, so no hand labeling is needed.
- `e2e_bench`: whole tasks (YAML files in `bench/tasks/`) at each chaos level, with options `--portal`, `--dialog-rule` and `--cache`.

## Run it

You need Windows with a desktop session (the GUI tests and benchmarks drive real windows) and Python 3.11 or newer. `setup.bat` creates `.venv`, installs the dependencies, generates the data with seed 42, and builds the fake program. It needs no admin rights.

```bat
setup.bat
.venv\Scripts\python -m bench.analysis_bench --seed 42
.venv\Scripts\python -m bench.ocr_bench --engines template,rapidocr,template+rapidocr
.venv\Scripts\python -m bench.ocr_calibrate
.venv\Scripts\python -m bench.e2e_bench --levels off,light,heavy --repeats 3
.venv\Scripts\python -m bench.e2e_bench --portal
.venv\Scripts\python tools/patrol.py --score
.venv\Scripts\python -m pytest
```

Run `tools\demo.py` the same way to watch a narrated run.

The fake login is `demo` / `demo123` (see `sim/legacyapp/users.ini.example`). Copy that file to `users.ini` to change it. Never put real passwords there.

## Sample results

These are from my first runs on 2026-11-03 and 2026-11-04, and they are written up in [docs/findings.md](docs/findings.md) (in Traditional Chinese). The numbers can differ on another machine. Rerun them with the commands above.

OCR on the real screen of the fake program (the first 21 rows to train, 51 rows to test):

| Engine | Exact `equip_id` strings | Time per cell |
| --- | --- | --- |
| template | 57% | 1.2 ms |
| RapidOCR (limited to allowed characters) | 86% | 7.3 ms |
| template, then RapidOCR when unsure | 86% | 4.0 ms |

The mixed engine is as accurate as RapidOCR alone and 45% faster, because the template handles 64% of the cells.

Other findings:

- On the control-chart test, counts data had a false-alarm rate of 0.44-0.50 with plain 3-sigma limits. Laney's c' correction, which allows for extra spread in counts, brought it down to 0.30-0.38.
- The patrol exported and analyzed 72 charts in 125 seconds with no failures. It caught 94% of the planted problems, with a 33% false-alarm rate.
- A task that pages through the grid and reads IDs with plain OCR failed every time (0 of 3 runs at each level), because a few IDs were misread (`Å`, `O` versus `0`). With the cells OCR was unsure about checked against the chart title, it passed 3 of 3 at the `off` chaos level.
- Under `heavy` chaos, the "Reconnect now?" dialog stops a run, because multi-button dialogs are never answered unless a rule allows them. The default rule answers it, and the tasks then pass.

## Safety rules

- Read-only by default. An action that changes data (`write_actions`) raises `WriteBlocked` before any GUI interaction unless it is listed in `allow_write`.
- Single-button dialogs are closed automatically. A dialog with several buttons is answered only by `dialog_rules`. A rule maps a text fragment to a standard button name such as `Yes` or `No`, matched by control ID so it works in any Windows language. Any other dialog fails the run. The default is `{"Reconnect now?": "Yes"}`. Pass `dialog_rules={}`, or `--no-default-rules` in the benchmark, for the strictest mode. Rules may not answer confirmations that change data.
- Company plugins, URLs and screenshots are excluded by `.gitignore`.
