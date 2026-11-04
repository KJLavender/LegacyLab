# 實驗結果紀錄

## 第一輪（2026-11-03）

數字都可以用 `bench/` 重跑；原始結果在 `bench/results/*.json`（不進 git）。

### E1 管制圖（analysis_bench，種子 42 / 7 / 123）

| 方法 | 偵測率 | 誤報率 | 計數資料誤報率 |
| --- | --- | --- | --- |
| baseline（樣本σ 3σ + 8 點同側） | 0.94–0.98 | 0.29 | 0.44–0.50 |
| imr（MR σ + Nelson 1/2/3/5） | 0.92–0.96 | 0.46–0.53 | 0.50–0.70 |
| auto（imr + 計數用 Laney c′） | 0.90–0.94 | 0.33–0.42 | 0.30–0.38 |

- 計數資料改用 Laney c′ 後，誤報率從 0.44–0.50 降到 0.30–0.38；一般的 c 圖（Poisson 界限）在負二項資料上反而更差（0.70），所以一定要做過度離散修正。
- Nelson 規則全開時誤報率偏高（4 條規則 × 60 點的多重檢定），下一輪逐條量。
- 函式庫（shewhart 等）還沒接，要先確認它的 API，再包進同一個 `Detection` 介面。

### E2 變化點（不含離群值圖）

| 方法 | 偵測率 | 誤報率 | 變化點位置誤差（中位數） |
| --- | --- | --- | --- |
| CUSUM（k=0.5, h=5） | 0.97–1.00 | 0.46–0.65 | 3 點 |
| PELT（ruptures） | 0.95–0.97 | 0.04–0.24 | 2–3 點 |
| ADWIN（river，clock=1） | 0.30–0.43 | 0.00 | 12–18 點 |

- PELT 誤報最少、位置最準，但它是離線方法，適合「事後找從哪個 lot 開始變」。
- CUSUM 偵測快但誤報多；σ 只用前 1/3 估，計數資料的移動全距又常是 0/1，σ 被低估。
- ADWIN 在 60 點、1.5σ 平移下太保守。預設 `clock=32` 時完全偵測不到。

### E3 OCR（ocr_bench，LegacyApp 實際畫面，前 21 列訓練、51 列測試）

| 引擎 | 全部字元 | equip_id 字元 | equip_id 整串正確 | ms/格 |
| --- | --- | --- | --- | --- |
| template | 0.70 | 0.89 | 0.57 | 1.2 |
| rapidocr（加允許字元過濾） | 0.97 | 0.98 | 0.86 | 7.3 |
| template + rapidocr | 0.97 | 0.98 | 0.86 | 4.0 |

- 模板的錯誤幾乎都是「訓練資料沒看過的字」，而且會輸出 `?`，不會有把握地錯；`O/0` 模板全對，RapidOCR 會錯。
- 串接後準確率和 RapidOCR 一樣，但快 45%（64% 的格子由模板處理）。
- 兩個引擎都把 `Å` 認成 `A`：模板是因為小圈被 0.5 門檻濾掉。改用寬鬆遮罩後出現「有把握但錯」（`8`→`0`），所以退回。
- RapidOCR 不過濾時會幻想出「60個」。

### 端到端（e2e_bench，每格 3 次）

| 任務 | off | light | heavy |
| --- | --- | --- | --- |
| query_export_analyze | 3/3 | 3/3 | 2/3 |
| write_guard | 3/3 | 3/3 | 3/3 |
| paging_lookup | 0/3 | 0/3 | 0/3 |

- `paging_lookup` 翻頁、定位、開圖都成功，失敗原因全是 OCR：72 列中 7 列 ID 錯（`Å`、`O/0`）。
- heavy 的失敗是多按鈕對話框 `Reconnect now?`，照設計不自動處理；可用 `--dialog-rule "Reconnect now?=否"` 明確允許。
- 搶焦點完全沒有影響，因為所有輸入都用 PostMessage 送。
- token 過期還測不到：入口網站與 SSO 還沒做，目前每次都走 LOGIN 視窗。

### 發現的 WinForms 和 VB6 差異（風險表第一列）

- WinForms 的 DoubleClick 會檢查實際游標位置，背景送 `WM_LBUTTONDBLCLK` 不會觸發；VB6 的 DblClick 會。假系統已改成在 MouseDown 用 `Clicks == 2` 判斷，對齊 VB6。
- 控制項類別名是 `WindowsForms10.*`，不是 VB6 的 `Thunder*`；插件用「EDIT／COMBOBOX 子字串＋位置」找控制項，換到真系統時要改。

## 第二輪（2026-11-03）

### E1 接上 shewhart，逐條量 Nelson 規則（種子 42 / 7 / 123 / 2024 / 99）

| 方法 | 偵測率 | 誤報率 |
| --- | --- | --- |
| baseline | 0.89–0.98 | 0.25–0.45 |
| shewhart，Nelson 8 條全開 | 0.94–1.00 | 0.45–0.55 |
| shewhart，只用 Nelson 1+2 | 0.90–0.95 | 0.21–0.40 |

- 逐條看（種子 42）：`nelson_1` 偵測率 0.77、誤報率 0.17；`nelson_2` 誤報率 0.08；`nelson_4`、`nelson_6`、`nelson_7` 幾乎只貢獻誤報。
- 結論：計量資料上沒有方法明顯贏過基準版；換函式庫的真正好處在計數資料（Laney 修正）與規則可以逐條控管。
- shewhart 只接受整組規則（`nelson` / `western_electric` / `none`），屬性圖只支援 `nelson`；逐條比較由 `analysis/spc.py` 自己過濾訊號。

### 入口網站 + 一次性 token（e2e_bench --portal）

- off：不用登入，`query_export_analyze` 平均 3.05 秒（直接啟動 3.55 秒）。
- light / heavy：混沌模式讓 token 失效時退回 LOGIN 視窗，都能完成（login_fallbacks 各 1 次）。
- 同一個 token 重放：第一次進主畫面，第二次跳 LOGIN（一次性驗證有效）。

### OCR：用 hwnd 讀到的圖表標題校正與自我標註

| 任務 | off | light | heavy |
| --- | --- | --- | --- |
| paging_lookup（不校正） | 0/3 | 0/3 | 0/3 |
| paging_lookup_verified（校正沒把握的列） | 3/3（18 秒） | 1/3 | 0/3 |
| 同上 + `--dialog-rule "Reconnect now?=否"` | — | 3/3（36 秒） | 3/3（47 秒） |

- `bench.ocr_calibrate`：全部 72 列開圖、讀標題、訓練模板，約 40 秒；不需要答案卷或人工標註，真系統上也能這樣做。
- 校準後模板學到 `A` / `Å` 點陣相同；只要輸出這類字就標成沒把握，再開圖確認（每次約 27 列）。
- 踩到的坑：反白列的點陣和一般列不同，歧義只記在其中一種畫法上會漏掉，所以改成字元層級；歧義原本沒存進模板檔，讀回來就忘了（已修正並加測試）。
- 加上明確的對話框規則後，heavy 混沌下除了不校正的翻頁任務，所有任務 3/3。

### 其他

- 失敗時，多按鈕對話框本身也會截圖，並記下文字與按鈕。

### 預設對話框規則

- 預設 `{"Reconnect now?": "Yes"}`，按鈕用標準 ID 比對（中文 Windows 的「是(&Y)」也對得到）。
- heavy 混沌、不帶任何 `--dialog-rule`：`query_export_analyze`、`write_guard`、`paging_lookup_verified` 都是 3/3；`paging_lookup`（不校正）仍是 0/3，原因是 OCR。

## 第三輪（2026-11-04）

### 變化點起點：PELT vs CUSUM（種子 42 / 7 / 123 / 2024 / 99，起點誤差在 4 點＝1 個 lot 內的比例）

| 異常類型 | PELT | CUSUM |
| --- | --- | --- |
| 平移 | 0.85 | 0.74 |
| 計數平移 | 0.95 | 0.57 |
| 漂移 | 0.17 | 0.48 |

- 分析流程改成 SPC 發警報、PELT 找起點（`analysis/pipeline.py`）。
- 漸進漂移是兩者的弱點：斜率每點 0.12σ，前 8 點累積不到 1σ，被雜訊蓋住。試過連續分段直線模型（`clinear`），沒有改善，所以不加。

### 已確認儲存格快取（e2e_bench --cache）

- `paging_lookup_verified`：第一次 20.4 秒（要開圖確認），之後 4.2–4.7 秒，結果一樣全對。
- key 用原始像素的雜湊（`A` 和 `Å` 的二值化遮罩相同，不能用遮罩）。

### E5 巡檢（tools/patrol.py --score，off）

- 72 張圖、125 秒、0 失敗；偵測率 94%、誤報率 33%、起點落在 1 個 lot 內 48%（被漂移拉低）。

### 假系統變複雜後（三級混沌各 3 次）

| 任務 | off | light | heavy |
| --- | --- | --- | --- |
| equip_filter（等清單載入完才選機台） | 3/3 | 3/3 | 3/3 |
| equip_filter_naive（不等，對照組） | 0/3 | 0/3 | 3/3* |
| lot_lookup（hwnd 跨行程讀 ListView） | 3/3（2.0 秒） | 3/3 | 3/3 |
| lot_lookup_ocr（同上但強制 OCR） | 3/3（3.1 秒） | 3/3 | 3/3 |
| long_session（連續匯出 6 張） | 3/3 | 3/3 | 3/3（中途重新登入 1 次） |
| paging_lookup_verified | 3/3 | 3/3 | 3/3（中途重新登入 6 次） |

\* heavy 下天真模式「成功」是巧合：它卡到 session 過期，重新登入後被重試，那時清單剛好載入完。

- 跨行程讀 ListView：64 位元 Python 讀 32 位元 LegacyApp，`LVITEM` 的指標寬度不同，要依目標行程切換結構。
- 頁籤：只送 `TCM_SETCURSEL` 不會觸發 WinForms 的切頁事件，要讀頁籤位置再背景點擊。
- 下拉選單：`CB_SELECTSTRING` 是前綴比對，改用 `CB_FINDSTRINGEXACT`。
- 天真模式在 off 下也 0/3：清單載入期間 Query 是灰的，按了沒反應，一直等到逾時。

### 擷圖踩到的坑（OCR 讀 ListView 從 50% 修到 100%）

1. `PrintWindow(PW_RENDERFULLCONTENT)` 拿的是 DWM 最後合成的畫面，可能畫到一半。實測 ListView 有字的列數會在 18–25 之間跳動。
2. 先 `RedrawWindow(RDW_UPDATENOW)`：沒用，因為那塊沒被標成無效。
3. 加 `RDW_INVALIDATE`：更糟。跨行程的 RedrawWindow 不等對方畫完，反而擷到重畫中的畫面。
4. 等前後兩張相同再擷：成功率 50%，畫一半的狀態可以穩定維持很久。
5. 最後：直接對子控制項 `PrintWindow(child, 0)`，讓控制項同步把自己畫進我們的 DC；畫出來是空白（不支援 `WM_PRINT` 的舊控制項）才退回 DWM 擷圖。light / heavy 各 12 次全部成功。
- 另外加了自我檢查：ListView 每格都該有值，有空格就重擷重認，並把截圖存進現場紀錄。
- 答案卷的 Mean/Max 要照 .NET Framework 的格式化規則（先取 15 位有效數字再四捨五入），不然 30 列會有 1 列對不上。
