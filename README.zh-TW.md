# LegacyLab

[English](README.md) | **繁體中文**

舊 Windows 桌面系統（VB6 時代、自繪表格、Busy Wait 對話框、沒有 API）的自動化實驗場。包含有答案卷的**模擬舊系統**、**通用自動化框架**，以及拿每個新想法和舊作法比較的**評分工具**。

完全不碰公司系統和公司資料，可以公開開發、放上 GitHub。

## 組成

| 路徑 | 內容 |
| --- | --- |
| `sim/datagen/` | 產生機台、圖表、量測值，注入已知異常（平移、漂移、離群、偏態計數），同時輸出 `answer_key.json`。固定亂數種子。 |
| `sim/legacyapp/` | 假舊系統（C# WinForms），用 Windows 內建的 `csc.exe` 編譯。版本 MsgBox、LOGIN 視窗、Busy Wait、自繪表格（GDI 畫字、無 API）、固定 697×505 圖表視窗、`Tools > Export Data`、會改資料的 `Exclude` 選單。 |
| `sim/portal/`、`sim/launcher/` | 假入口網站 + SSO（Starlette，只綁 127.0.0.1），發一次性 token；`legacyapp://` 協定處理程式檢查 URL 後啟動 LegacyApp（仿 VBS 啟動程式）。`register.py` 可把協定註冊到 HKCU；bench 直接呼叫處理程式，不需要註冊。 |
| `sim/chaos.ini` | 混沌模式：隨機延遲、突發對話框（單按鈕／多按鈕）、token 過期、搶焦點、DPI 縮放、逗號小數點。分 `off` / `light` / `heavy` 三級。 |
| `core/win32.py` | 只用 ctypes 的 Win32 層：找視窗、讀寫控制項、原生選單、用 `PostMessage` 背景點擊、`PrintWindow` 擷圖、對話框處理規則。 |
| `core/ocr/` | 可切換的 OCR 引擎：固定字型**模板比對**、**RapidOCR**、`FallbackOcr`（先用模板，認不出才交給 RapidOCR）。 |
| `core/launcher.py` | 依設定透過入口網站啟動：登入、點功能、取得協定 URL、交給處理程式。 |
| `core/locator.py` | 定位方式依序退回：`api → hwnd → msaa → image → ocr`，並統計每次用到哪一層。 |
| `core/trace.py` | 失敗現場紀錄：每一步的耗時；失敗時存截圖、視窗樹和例外。 |
| `plugins/` | `AppPlugin` 介面與 `legacyapp` 領域模組。會改資料的動作預設擋下。 |
| `analysis/` | 管制圖（基準 3σ、I-MR + Nelson 規則、計數資料用 Laney c′，以及包在同一介面下的 `shewhart` 函式庫）與變化點偵測（CUSUM、PELT、ADWIN）。 |
| `bench/` | `analysis_bench`（E1/E2，`--per-rule` 逐條規則）、`ocr_bench`（E3）、`ocr_calibrate`（用 Win32 讀到的圖表標題自動標註、訓練模板 OCR）、`e2e_bench`（YAML 任務 × 混沌等級，`--portal`、`--dialog-rule`）。結果存到 `bench/results/*.json`，附 git commit 與種子。 |
| `tools/inspect_window.py` | 唯讀列出視窗的控制項樹與 MSAA 文字，確認哪些東西不用 OCR 就讀得到。 |

## 快速開始

```bat
setup.bat
.venv\Scripts\python -m bench.analysis_bench --seed 42
.venv\Scripts\python -m bench.ocr_bench --engines template,rapidocr,template+rapidocr
.venv\Scripts\python -m bench.ocr_calibrate
.venv\Scripts\python -m bench.e2e_bench --levels off,light,heavy --repeats 3
.venv\Scripts\python -m bench.e2e_bench --portal
.venv\Scripts\python -m pytest
```

假登入帳密是 `demo` / `demo123`（`sim/legacyapp/users.ini.example`）。要改的話複製成 `users.ini`；不要放真密碼。

## 安全規則

- 預設唯讀。會改資料的動作（`write_actions`）沒有放進 `allow_write` 時，在碰到 GUI 之前就丟 `WriteBlocked`。
- 單一按鈕的對話框自動按掉。多按鈕對話框只照 `dialog_rules`（內文片段 → 標準按鈕名稱，如 `Yes` / `No`；用控制項 ID 比對，任何 Windows 語系都適用）處理，其餘一律讓這次執行失敗。預設是 `{"Reconnect now?": "Yes"}`；要最嚴格的模式就設 `dialog_rules={}` 或加 `--no-default-rules`。規則不能用來回答會改資料的確認框。
- 公司 plugin、網址、截圖都列在 `.gitignore`。
