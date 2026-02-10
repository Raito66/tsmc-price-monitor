# stock-multi-notify（多股自動推播通知）

本專案自動監控多檔台股（如台積電、力積電、群創等），盤中與盤後將即時價格、均線、行情建議自動推播至 Discord，並同步儲存至 Google Sheets。資料來源為 FinMind。

## 功能特色

* 盤中推播即時成交價、均線、操作建議。
* 盤後自動推播最新價、正式收盤價、行情摘要、均線分析與建議。
* 支援多支股票並可快速調整監控清單（於 `STOCK_LIST` 設定）。
* 所有推播均全自動產生，無需人工干預。
* 資料紀錄於 Google Sheets 並自動補齊400筆歷史。
* 自動處理 Google Sheets API 配額限制。

## 價格取得與計算邏輯（重要）

### 盤中（交易時間內）

* **優先來源**：FinMind `TaiwanStockPrice` 的「當天即時成交價」。
* **當天無資料時**：

  * 自動回退至「最近一個有交易日」的收盤價（**不固定使用昨日**）。
* **推播顯示會標註來源**，例如：

  * `1780.00（當天收盤價）`
  * `1765.00（2025-02-07 最近交易日）`

此設計可避免開盤初期或資料延遲時，長時間顯示過舊的「昨日收盤價」。

### 盤後（收盤後）

盤後推播同時顯示兩種價格，資訊更完整：

* **最新價**：

  * 當天最後一筆成交價
  * 若當天無成交，則使用最近一個交易日的收盤價

* **今日收盤**：

  * 來自日 K 資料的「正式收盤價」
  * 若日 K 無資料，同樣回退至最近交易日價格

* **漲跌幅計算基準**：以前一交易日的收盤價為準

### 特殊時段規則（13:31～13:59）

* 此時段仍維持「昨日收盤價 + 操作建議」的特殊推播模式
* 目的為避免收盤資料尚未穩定時，產生誤導訊息
* 可依實際需求於程式中調整或關閉

## 快速開始

### 1. 安裝依賴套件

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數 `.env`

建立 `.env` 檔案，格式如下：

```
GOOGLE_SHEETS_CREDENTIALS=（你的 Google Sheets Service Account JSON）
GOOGLE_SHEET_ID=（Google Sheets 文件ID）
FINMIND_TOKEN=（你的 FinMind API Token）
DISCORD_WEBHOOK_URL=（你的 Discord Webhook URL）
```

### 3. 設定 Discord Webhook

1. 在 Discord 頻道 > 編輯頻道 > 整合 > Webhooks > 新增 Webhook。
2. 複製 Webhook URL，填入 `.env` 的 `DISCORD_WEBHOOK_URL` 欄位。

### 4. 設定 Google Sheets 權限

* 必須將 Google Service Account 的 email 加入你要操作的 Google Sheets 共用（給編輯權限），否則無法寫入。

### 5. 執行主程式

```bash
python stock-multi-notify.py
```

執行後會根據監控清單自動推播訊息至 Discord 並同步寫入 Google Sheets。

### 6. 補齊歷史資料

需要重建或補齊歷史行情與均線可用：

```bash
python stock-history-fill.py
```

* 會自動檢查與補齊資料，每檔最多保留400筆，缺漏自動補齊。
* 如遇 Google Sheets API 配額（429 quota exceeded），程式會自動 sleep 並重試，**流程不中斷且不遺漏資料**。

## 進階設定與範例

* 股票清單及名稱對應於 `stock-multi-notify.py` 內的 `STOCK_LIST` 與 `STOCK_NAME_MAP`，可依需求新增或調整。
* Google Sheets 欄位設計：

  * A: 股票代碼
  * B: 名稱
  * C: 日期
  * D: 收盤價
  * E: 5日均線
  * F: 20日均線
  * G: 60日均線
  * H: 最後更新時間
* 預設抓取最近一年(365天)資料。

## 通知與排程建議

* 盤中建議每3分鐘檢查一次；補齊歷史資料建議於非交易時段或手動執行。
* 推播內容包含：即時行情、均線資訊及操作建議。

## 常見問題

* **Service Account 權限不足** 會導致 Google Sheets 寫入失敗，一定要設定共用。
* **需求新股票** 請在 `STOCK_LIST` 中加入股票代碼，同步更新 `STOCK_NAME_MAP`。
* **API 配額限制** 程式會自動等待與重試。
* **資料安全** 若Google Sheets已有400筆會自動跳過，流程可安全重複執行。

## 注意事項

* 僅供資訊參考，不構成投資建議。
* 如有推播異常請檢查 Discord、Google Sheets 權限及 API Token 是否正確。
* 詳細參數及流程請見程式註解。

---

> 本專案可依公司/個人需求調整推播平台（如 Discord、LINE），相關更動請參照程式內註解。
