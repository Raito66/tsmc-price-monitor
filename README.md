# stock-multi-notify（多股自動推播通知）

## 專案簡介

stock-multi-notify 是一套多股台股自動監控與推播系統，可於盤中與盤後自動取得股價、
均線與行情建議，並透過 Discord Webhook 推播，同步將歷史資料儲存至 Google Sheets。

資料來源以 FinMind API 為主，並在異常時自動切換至 Yahoo Finance（yfinance）作為備援，
確保價格取得與推播流程穩定不中斷。

---

## 為什麼不直接看盤或用 App？

**股票 App 是你去找資訊，這套系統是資訊自己來找你。**

你手機上一定有股票 App。但你每天真的會固定去開它嗎？
忙的時候忘了看，想起來的時候已經錯過了。
這套系統解決的就是這一點：**它不需要你記得去查，它會在固定時間主動推給你。**

| | 股票 App／看盤網站 | 本系統 |
|---|---|---|
| 查看方式 | 手動開 App，逐支查詢 | 定時自動推播到 Discord |
| 股票數量 | 一支一支看 | 12 支同時監控，一次推完 |
| 技術指標 | 自己看圖判斷均線位置 | MA5／MA20／MA60 自動計算，直接給數字 |
| 操作建議 | 沒有，靠自己解讀 | 根據均線位置與漲跌幅自動給出建議 |
| 通知時機 | 要自己記得去看 | 每 5 分鐘主動推播，不怕忘 |
| 使用情境 | 需要切換到 App | Discord 通知彈出來掃一眼就好 |
| 客製化 | App 給什麼看什麼 | 自己的股票清單，隨時在 Google Sheets 增刪 |
| 歷史紀錄 | 要自己截圖或記 | 自動存入 Google Sheets，可回頭查 |

### 實際使用情境

- **上班中** — 不方便一直盯盤，Discord 通知彈出來，5 秒掃一眼就判斷要不要行動
- **同時追多支** — 12 支股票每次一起推完，不需要逐一切換 App 查詢
- **不想自己算指標** — MA5／MA20／MA60 和操作建議都算好了，看結論就夠
- **不想錯過時機** — 定時推播，有動靜自然看到，不需要特別記得去查
- **FinMind 升級付費後** — 盤中即時資料自動生效，推播準確度直接提升，不需改任何設定

---

## 功能特色

- 盤中推播即時成交價、MA5／MA20／MA60 均線與操作建議
- 盤後推播最新價、正式收盤價與行情摘要
- 12 支股票同時監控，批次標題顯示今日第 N 次推播
- **股票清單由 Google Sheets Config 分頁動態管理**，新增／移除無需修改程式碼
- Config 分頁含格式驗證，代號錯誤或格式不符時 Discord 發出警告
- C 欄填 N 可暫停個別股票監控，不影響其他股票，推播期間也安全修改
- FinMind 失敗自動切換 yfinance 備援；yfinance 遭限流自動 retry（最多 3 次）
- 上市股使用 `.TW`、上櫃股（精材、雙鴻）自動偵測使用 `.TWO` 後綴，無需手動設定
- 交易日判斷：查最近 7 天資料，正確處理週一與多日連假情境
- 前一交易日收盤往回最多找 7 天，修正週一漲跌幅顯示 0% 的問題
- 國定假日偵測：盤中無即時資料時自動跳過，不推出舊收盤假裝即時行情
- 盤前時段（09:00 前）自動略過，不觸發假日誤判
- Google Sheets 雲端紀錄歷史收盤、均線，並追蹤當天推播次數
- FinMind 免費版即可運作；升級付費後盤中自動切回即時資料，無需改程式
- 支援 Render.com Cron Job 雲端部署

---

## 監控股票清單

| 代號 | 名稱 | 市場 |
|------|------|------|
| 2330 | 台積電 | 上市 |
| 6770 | 力積電 | 上市 |
| 3481 | 群創 | 上市 |
| 2337 | 旺宏 | 上市 |
| 2344 | 華邦電 | 上市 |
| 2409 | 友達 | 上市 |
| 2367 | 燿華 | 上市 |
| 3374 | 精材 | 上櫃 |
| 3324 | 雙鴻 | 上櫃 |
| 00642U | 期元大S&P石油 | 上市 ETF |
| 0050 | 元大台灣50 | 上市 ETF |
| 2231 | 為升 | 上市 |

> 新增或移除股票請直接編輯 Google Sheets 的 **Config 分頁**，程式下次執行即生效，無需修改程式碼。

---

## 股票清單管理（Config 分頁）

| 欄位 | 內容 | 說明 |
|------|------|------|
| A | 股票代號 | 4～6 碼數字，可接一個英文字母（如 00642U） |
| B | 股票名稱 | 顯示用名稱 |
| C | 啟用（Y/N） | N 表示暫停監控，不影響其他股票 |

- 代號格式錯誤時，Discord 會發出警告並跳過該筆
- C 欄改為 N 可暫停個別股票，不需刪除整列
- 推播執行期間修改 Config 不影響當次執行，下次執行才生效

---

## 價格取得與計算邏輯

### 盤中（09:00～13:30）
- 優先使用 FinMind TaiwanStockPrice 當天即時成交價（付費方案）
- FinMind 失敗 → 自動切換 yfinance，約 15～20 分鐘延遲
- yfinance 遭限流時每 3 秒 retry，最多 3 次
- 推播標注價格來源（FinMind 即時 或 yfinance 備援）

### 特殊時段（13:31～13:59）
- 顯示前一交易日收盤價 + 均線與操作建議
- 避免收盤結算期間資料尚未穩定時產生誤導

### 盤後（14:00 後）
- 最新價（當天最後成交價）＋今日正式收盤價（日 K 資料）同時顯示
- 漲跌幅以前一**交易日**收盤價為基準（最多往回找 7 天，正確處理週一）

### 國定假日／非交易日
- 盤後：FinMind 查無當天日 K → 自動判斷非交易日，程式靜默結束
- 盤中：今日無即時資料（`is_latest=False`）→ 跳過推播，Discord 推送一則說明通知
- 盤前（09:00 前）：直接略過，不進行任何 API 呼叫或推播

---

## 執行環境

- Python 3.8+
- Google Sheets API Service Account
- Discord Webhook
- FinMind API Token（免費方案可用；升級付費後盤中即時資料自動生效，不需改程式）
- Yahoo Finance（備援，免 Token）

---

## 環境變數設定（.env）

```
GOOGLE_SHEETS_CREDENTIALS=你的 Google Sheets Service Account JSON
GOOGLE_SHEET_ID=你的 Google Sheets 文件 ID
FINMIND_TOKEN=你的 FinMind API Token
DISCORD_WEBHOOK_URL=你的 Discord Webhook URL
```

---

## 快速開始（本地執行）

### 安裝套件

```bash
pip install -r requirements.txt
```

### 執行推播程式

```bash
python stock-multi-notify.py
```

### 補齊歷史資料

```bash
python stock-history-fill.py
```

---

## Render.com 部署方式（建議）

本專案適合使用 **Render Cron Job** 方式部署，不需常駐服務，穩定且節省資源。

### 1. 建立專案

- 將本專案推送至 GitHub Repository
- 登入 https://render.com
- New → **Cron Job**
- 連結你的 GitHub 專案

### 2. 設定執行指令

```bash
python stock-multi-notify.py
```

### 3. 排程設定

| 服務 | Cron | 說明 |
|------|------|------|
| 推播（notify） | `*/5 0-7 * * 1-5` | UTC，對應台灣 08:00～15:55，週一至週五 |
| 補齊歷史（fill） | `0 7 * * 1-5` | UTC，對應台灣 15:00，週一至週五 |

> 推播程式已內建盤前判斷，09:00 前自動略過，`*/5 0-7` 排程下也不會誤推。

### 4. 設定環境變數

於 Render Dashboard → Environment：
- GOOGLE_SHEETS_CREDENTIALS
- GOOGLE_SHEET_ID
- FINMIND_TOKEN
- DISCORD_WEBHOOK_URL

⚠️ **Google Sheets 憑證請直接貼 JSON 內容，勿換行**

---

## Google Sheets 欄位設計

### Sheet1（A～H）：歷史收盤紀錄

| 欄位 | 內容 |
|------|------|
| A | 股票代碼 |
| B | 股票名稱 |
| C | 日期 |
| D | 收盤價 |
| E | 5 日均線 |
| F | 20 日均線 |
| G | 60 日均線 |
| H | 最後更新時間 |

### Sheet1（J1～K1）：當天推播計數

| 欄位 | 內容 |
|------|------|
| J1 | 日期（YYYY-MM-DD） |
| K1 | 當天推播次數 |

### Config 分頁（A～C）：股票清單

| 欄位 | 內容 |
|------|------|
| A | 股票代號 |
| B | 股票名稱 |
| C | 啟用（Y/N） |

---

## 常見問題

- Service Account Email 必須加入 Google Sheets 共用（編輯權限）
- 新增／移除股票請在 Google Sheets **Config 分頁**操作，不需改程式
- 上櫃股（如精材 3374、雙鴻 3324）系統已自動偵測使用 `.TWO` 後綴，不需手動設定
- FinMind 免費方案盤中資料以 yfinance 備援為主（約 15～20 分鐘延遲）；付費升級後自動切回即時，不需修改程式
- `stock-history-fill.py` 同樣讀取 Config 分頁，股票清單與推播程式自動同步

---

## 注意事項

- 本專案僅供資訊參考，不構成投資建議
- 請妥善保管 API Token 與 Discord Webhook URL

---

## 授權

MIT License
