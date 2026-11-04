# LegacyLab

[English](README.md) | **繁體中文**

LegacyLab 是用來練習自動化舊 Windows 桌面程式的實驗場。這類程式多半是 VB6 時代做的:沒有 API、表格是自己畫的、還會卡在「請稍候」的對話框後面。你沒辦法用程式碼直接呼叫它們,腳本只能自己找視窗、讀文字、按按鈕。這種做法很脆弱,而且很難判斷一個新招數到底有沒有幫助。

所以這個專案把三樣東西放在一起:一個有標準答案的模擬舊系統、一套自動化框架,以及一個把每個新想法拿來和舊做法比分數的評測工具。這裡完全不碰公司系統和公司資料,所以可以放心公開。

## 內容

| 路徑 | 內容 |
| --- | --- |
| `sim/datagen/` | 產生機台、圖表和量測值,並藏進問題(平移、漂移、離群值、偏斜的計數),另外輸出記錄正確答案的 `answer_key.json`。種子固定,所以結果可以重現。 |
| `sim/legacyapp/` | 模擬的舊系統,用 C# WinForms 寫成,以 Windows 內建的 `csc.exe` 編譯。有版本提示視窗、登入視窗、忙碌等待對話框、兩個頁籤、載入很慢又互相連動的下拉選單、自繪表格(文字用 GDI 畫上去,沒有控制項可讀)、標準 ListView(`By Lot`)、固定大小的圖表視窗、`Tools > Export Data`、會改資料的 `Exclude` 選單,以及做到一半就過期、逼你重新登入的 session。 |
| `sim/portal/`、`sim/launcher/` | 假的入口網站加單一登入(SSO),只開在 127.0.0.1。它會發一次性 token。`legacyapp://` 處理程式會檢查網址並啟動程式,就像 VBS 啟動器一樣。`register.py` 會替目前使用者註冊這個協定。評測是直接呼叫處理程式,所以不必註冊。 |
| `sim/chaos.ini` | 混沌模式,讓執行更混亂:隨機延遲、彈出視窗、token 過期、session 逾時、清單載入變慢、搶走焦點、DPI 縮放、小數點用逗號。等級有 `off`、`light`、`heavy`。 |
| `core/win32.py` | 只用 `ctypes` 寫的 Win32 層。能找視窗、讀寫控制項、操作原生選單、用 `PostMessage` 在背景點擊、切換頁籤、跨行程讀 ListView(32 位元與 64 位元都行),並在控制項畫完之後用 `PrintWindow` 擷圖。 |
| `core/ocr/` | 可替換的 OCR 引擎(OCR 是把文字圖片變回文字):固定字型的模板比對、RapidOCR,以及先用模板、沒把握才問 RapidOCR 的組合。快取會記住已經用精確 Win32 文字確認過的儲存格。 |
| `core/launcher.py` | 依設定檔經由入口網站啟動程式:登入、選功能、讀出協定網址、交給處理程式。 |
| `core/locator.py` | 分層找東西,從最可靠到最不可靠:`api`、`hwnd`、`msaa`、`image`、`ocr`。並記錄用了哪一層。 |
| `core/trace.py` | 失敗紀錄:每一步的耗時,失敗時附上截圖、視窗樹和 traceback。 |
| `plugins/` | `AppPlugin` 介面和 `legacyapp` 外掛。會寫入資料的動作,除非明確允許,否則一律擋下。 |
| `analysis/` | 統計製程管制(SPC,用管制圖判斷量測值是否跑出正常範圍)、變化點偵測(找出數列從哪裡開始改變),以及 `pipeline.py`:SPC 負責發警報,PELT 負責找出變化從哪個 lot 開始。 |
| `bench/` | 各種評測,見下方。結果存到 `bench/results/*.json`,附上 git commit 和種子。 |
| `tools/patrol.py` | 巡檢:匯出並分析每一張圖表,輸出異常排在最前面的 HTML 報告。加 `--score` 會拿答案卷評分。 |
| `tools/demo.py` | 慢速、有解說的完整流程示範,每一步都截圖。 |
| `tools/inspect_window.py` | 唯讀地列出視窗的控制項和 MSAA 文字,看看不用 OCR 能讀到什麼。 |

`bench/` 裡的評測:

- `analysis_bench`:管制圖與變化點方法(`--per-rule` 會把每條規則單獨評分)。
- `ocr_bench`:在模擬系統的真實畫面上比較 OCR 引擎。
- `ocr_calibrate`:用 Win32 精確讀到的圖表標題來訓練模板 OCR,不需要人工標註。
- `e2e_bench`:在每個混沌等級下跑完整任務(`bench/tasks/` 裡的 YAML 檔),可加 `--portal`、`--dialog-rule`、`--cache`。

## 執行方式

需要 Windows 並且有桌面 session(GUI 測試和評測會操作真的視窗),以及 Python 3.11 以上。`setup.bat` 會建立 `.venv`、安裝相依套件、用種子 42 產生資料,並編譯模擬程式,不需要管理員權限。

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

想看有解說的完整流程,用同樣方式執行 `tools\demo.py`。

假的登入帳密是 `demo` / `demo123`(見 `sim/legacyapp/users.ini.example`)。要改就把那個檔案複製成 `users.ini`。不要在裡面放真的密碼。

## 結果範例

以下是我 2026-11-03 和 2026-11-04 第一批執行的結果,完整紀錄在 [docs/findings.md](docs/findings.md)。換一台機器數字可能不同,請用上面的指令重跑。

在模擬系統的真實畫面上比較 OCR(前 21 列用來訓練,51 列用來測試):

| 引擎 | `equip_id` 整串正確 | 每格耗時 |
| --- | --- | --- |
| 模板 | 57% | 1.2 ms |
| RapidOCR(限制只能輸出允許的字元) | 86% | 7.3 ms |
| 先模板,沒把握再用 RapidOCR | 86% | 4.0 ms |

組合引擎的準確率和單用 RapidOCR 一樣,但快 45%,因為有 64% 的格子由模板處理。

其他發現:

- 管制圖測試中,計數資料用一般 3σ 界限時誤報率是 0.44-0.50。改用 Laney c′ 修正(把計數資料額外的離散度算進去)後降到 0.30-0.38。
- 巡檢在 125 秒內匯出並分析了 72 張圖,沒有失敗。它抓到 94% 的植入問題,誤報率 33%。
- 翻頁讀 ID、只靠 OCR 的任務每次都失敗(每個混沌等級都是 3 次裡 0 次),因為有幾個 ID 讀錯(`Å`、`O` 與 `0`)。把 OCR 沒把握的格子拿圖表標題比對確認後,在 `off` 混沌等級下 3 次全過。
- 在 `heavy` 混沌下,「Reconnect now?」對話框會讓執行中斷,因為有多個按鈕的對話框除非有規則允許,否則不會自動回答。預設規則會回答它,之後任務就通過了。

## 安全規則

- 預設唯讀。會改資料的動作(`write_actions`)在動到任何 GUI 之前就會丟出 `WriteBlocked`,除非列在 `allow_write` 裡。
- 只有一個按鈕的對話框會自動關掉。有多個按鈕的對話框只由 `dialog_rules` 回答。規則是把一段文字對應到標準按鈕名稱,例如 `Yes` 或 `No`,用控制項 ID 比對,所以任何語言的 Windows 都適用。其他對話框一律讓該次執行失敗。預設規則是 `{"Reconnect now?": "Yes"}`。要最嚴格的模式,傳入 `dialog_rules={}`,評測則加 `--no-default-rules`。規則不能用來回答會改資料的確認視窗。
- 公司專用的外掛、網址和截圖都被 `.gitignore` 排除。
