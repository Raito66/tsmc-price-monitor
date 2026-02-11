# stock-multi-notify（多股自動推播通知）

## 專案簡介
stock-multi-notify 是一套多股台股自動監控與推播系統，可於盤中與盤後自動取得股價、
均線與行情建議，並透過 Discord Webhook 推播，同步將歷史資料儲存至 Google Sheets。

資料來源以 FinMind API 為主，並在異常時自動切換至 Yahoo Finance API 作為備援，
確保價格取得與推播流程穩定不中斷。

---

## 功能特色
- 盤中推播即時成交價、均線與操作建議
- 盤後推播最新價、正式收盤價與行情摘要
- 支援多檔股票同時監控（STOCK_LIST 可快速調整）
- 全自動推播，無需人工干預
- Google Sheets 雲端紀錄歷史資料
- 自動補齊最多 400 筆歷史行情
- 自動處理 Google Sheets API 配額限制（429）
- FinMind / Yahoo Finance API 自動容錯切換
- 支援 Render.com Cron Job 雲端部署

---

## 價格取得與計算邏輯

### 盤中（交易時間內）
- 優先使用 FinMind TaiwanStockPrice 的當天即時成交價
- 若當天無資料，回退至「最近一個有交易日」的收盤價（非固定昨日）
- 推播會標註價格來源日期，避免誤判

### 盤後（收盤後）
- 同時顯示：
  - 最新價（當天最後成交價，或最近交易日收盤）
  - 今日正式收盤價（日 K 資料）
- 漲跌幅以前一交易日收盤價為計算基準

### 特殊時段（13:31～13:59）
- 維持昨日收盤價 + 操作建議模式
- 避免收盤資料尚未穩定時產生誤導訊息
- 可於程式中自行調整或關閉

---

## 執行環境
- Python 3.8+
- Google Sheets API Service Account
- Discord Webhook
- FinMind API Token
- Yahoo Finance（備援，免 Token）

---

## 環境變數設定（.env）
GOOGLE_SHEETS_CREDENTIALS=你的 Google Sheets Service Account JSON  
GOOGLE_SHEET_ID=你的 Google Sheets 文件 ID  
FINMIND_TOKEN=你的 FinMind API Token  
DISCORD_WEBHOOK_URL=你的 Discord Webhook URL  

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
- Command：
```bash
python stock-multi-notify.py
```

（歷史補齊腳本請手動或另建 Cron Job 執行）

### 3. 設定排程（建議）
*/5 0-7 * * 1-5

（台灣時間，Render 請設定時區為 Asia/Taipei）

### 4. 設定環境變數
於 Render Dashboard → Environment：
- GOOGLE_SHEETS_CREDENTIALS
- GOOGLE_SHEET_ID
- FINMIND_TOKEN
- DISCORD_WEBHOOK_URL

⚠️ **Google Sheets 憑證請直接貼 JSON 內容，不要換行錯誤**

---

## Google Sheets 欄位設計
A: 股票代碼  
B: 股票名稱  
C: 日期  
D: 收盤價  
E: 5 日均線  
F: 20 日均線  
G: 60 日均線  
H: 最後更新時間  

---

## 常見問題
- Service Account Email 必須加入 Google Sheets 共用（編輯權限）
- 新增股票請同步更新 STOCK_LIST 與 STOCK_NAME_MAP
- API 配額限制會自動等待並重試
- 若 Sheets 已有 400 筆資料會自動跳過，可安全重複執行

---

## 注意事項
- 本專案僅供資訊參考，不構成投資建議
- 請妥善保管 API Token 與 Discord Webhook URL
- 詳細參數與流程請參考程式內註解

---

## 授權
MIT License

2026//2/10
主要改動重點

「全部買進」條件：乖離 ≤ 2.8% 且當日漲幅 3.0% ~ 6.0%（剛突破且力道強但不過熱）
「全部賣出」條件：乖離 > 7.5% 或（乖離 > 6% 且漲幅 > 4.5%）
大部分建議都給出明確比例：10%~20%、20%~40%、25%~45%、50%~80% 等
極端波動（>7%）會建議賣出大部分
跌勢有止損建議（全部賣出或賣 40%~70%）
