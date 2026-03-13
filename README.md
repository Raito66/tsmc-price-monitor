# stock-multi-notify（多股自動推播通知）

## 專案簡介
stock-multi-notify 是一套多股台股自動監控與推播系統，可於盤中與盤後自動取得股價、
均線與行情建議，並透過 Discord Webhook 推播，同步將歷史資料儲存至 Google Sheets。

資料來源以 FinMind API 為主，並在異常時自動切換至 Yahoo Finance（yfinance）作為備援，
確保價格取得與推播流程穩定不中斷。

---

## 為什麼不直接看股票 App？

**股票 App 是你去找資訊，這套系統是資訊自己來找你。**

| | 股票 App / 網站 | 本系統 |
|---|---|---|
| 查看方式 | 手動開 App，逐支查詢 | 定時自動推播到 Discord |
| 股票數量 | 一支一支看 | 12 支同時監控，一次推完 |
| 技術指標 | 自己看圖判斷 | 均線自動計算，直接給建議 |
| 通知時機 | 要自己記得去看 | 固定間隔主動通知，不怕忘 |
| 客製化 | App 給什麼看什麼 | 自己的股票清單、自己的判斷邏輯 |

盤中在忙其他事時，不會特地去開 App，但 Discord 通知一跳出來就看到了。
均線和操作建議都已經算好，只需要看結論，不用自己分析。

---

## 功能特色
- 盤中推播即時成交價、均線與操作建議
- 盤後推播最新價、正式收盤價與行情摘要
- 支援 12 支股票同時監控（STOCK_LIST 可快速調整）
- 每次推播附帶批次標題（今日第 N 次 盤中／盤後更新）
- 全自動推播，無需人工干預
- Google Sheets 雲端紀錄歷史資料，並追蹤當天推播次數
- FinMind 失敗自動切換 yfinance 備援，yfinance 遭限流自動 retry（最多 3 次）
- 上市股使用 `.TW`，上櫃股（精材、雙鴻）自動使用 `.TWO` 後綴
- 交易日判斷：FinMind 失敗時改用 yfinance 確認，避免誤判非交易日而漏推
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

新增或移除股票請同步更新 `STOCK_LIST`、`STOCK_NAME_MAP`，
若為上櫃股還需加入 `TWO_STOCKS`。

---

## 價格取得與計算邏輯

### 盤中（交易時間內）
- 優先使用 FinMind TaiwanStockPrice 當天即時成交價
- FinMind 失敗 → 自動切換 yfinance，遭限流時每 3 秒 retry，最多 3 次
- 推播會標註價格來源（FinMind 或 yfinance 備援）

### 盤後（收盤後）
- 同時顯示：
  - 最新價（當天最後成交價）
  - 今日正式收盤價（日 K 資料）
- 漲跌幅以前一交易日收盤價為計算基準

### 特殊時段（13:31～13:59）
- 維持昨日收盤價 + 操作建議模式
- 避免收盤資料尚未穩定時產生誤導訊息

---

## 執行環境
- Python 3.8+
- Google Sheets API Service Account
- Discord Webhook
- FinMind API Token（免費方案可用，付費方案資料更即時）
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

> ⚠️ `stock-history-fill.py` 的股票清單目前為舊版 7 支，新增股票後請手動同步更新該檔案的 `STOCK_LIST`。

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

### 3. 設定排程（建議）
```
*/5 0-7 * * 1-5
```
（UTC 時間，對應台灣時間 08:00～15:00，週一至週五）

### 4. 設定環境變數
於 Render Dashboard → Environment：
- GOOGLE_SHEETS_CREDENTIALS
- GOOGLE_SHEET_ID
- FINMIND_TOKEN
- DISCORD_WEBHOOK_URL

⚠️ **Google Sheets 憑證請直接貼 JSON 內容，勿換行**

---

## Google Sheets 欄位設計

### A～H 欄：歷史收盤紀錄
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

### J1～K1：當天推播計數
| 欄位 | 內容 |
|------|------|
| J1 | 日期（YYYY-MM-DD） |
| K1 | 當天推播次數 |

---

## 常見問題
- Service Account Email 必須加入 Google Sheets 共用（編輯權限）
- 新增股票請同步更新 `STOCK_LIST`、`STOCK_NAME_MAP`；上櫃股另需加入 `TWO_STOCKS`
- FinMind 免費方案每天有 API 配額上限，盤中資料以 yfinance 備援為主
- `stock-history-fill.py` 需要 FinMind 付費方案才能穩定補齊歷史資料

---

## 注意事項
- 本專案僅供資訊參考，不構成投資建議
- 請妥善保管 API Token 與 Discord Webhook URL
- 詳細參數與流程請參考程式內註解

---

## 授權
MIT License
