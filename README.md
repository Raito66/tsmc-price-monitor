# 台積電股價監控系統（Google Sheets 雲端版）

自動監控台積電（2330）股價，並將歷史資料永久儲存於 Google Sheets，透過 LINE 即時推播通知。

## 主要功能

- 即時取得台積電現價、昨收
- Google Sheets 雲端儲存歷史資料（自動保留一年）
- 多均線技術分析（5/20/60日）
- 年度高低點、均價、距離高低點百分比
- 智能推播建議（多空訊號、年度統計、短線趨勢）
- LINE 通知
- 支援 Render.com 定時任務與本地執行

---

## 執行環境與需求

- Python 3.8+
- Google Sheets API Service Account 憑證
- LINE Messaging API Channel Access Token & User ID

### 必要環境變數

| 變數名 | 說明 |
|--------|------|
| LINE_CHANNEL_ACCESS_TOKEN | LINE Bot Token |
| LINE_USER_ID | LINE User ID |
| GOOGLE_SHEETS_CREDENTIALS | Google Sheets Service Account JSON（整份內容） |
| GOOGLE_SHEET_ID | 目標 Google Sheet 的 ID |

---

## 執行方式

### 1. Google Sheets 準備
- 建立 Google Sheet，命名為 Sheet1（或自訂，程式可調整 SHEET_NAME）
- 取得 Google Service Account JSON，並將帳號加入該 Sheet 的共用權限

### 2. 設定環境變數
- 將上述四個變數設為系統環境變數，或於 Render.com 設定

### 3. 安裝相依套件
- 於專案根目錄下安裝 requirements.txt 內所有套件

### 4. 執行主程式
- 本地：python tsmc_price_notify.py
- Render.com：設置 Cron Job，指令同上

---

## Google Sheets 結構

- 每天僅新增一筆資料（自動判斷日期）
- 欄位：日期、價格、5日均線、20日均線、60日均線、時間戳
- 自動清理超過一年（365天）前的舊資料

---

## LINE 通知內容範例

【台積電價格監控】
時間：2026-02-08 10:30:00
━━━━━━━━━━━━━━
現價：1780.00 元
昨收：1765.00 元
漲跌：+15.00 元（+0.85%）
━━━━━━━━━━━━━━
📊 年度統計
最高：1900.00 元（2025-12-01）
最低：1550.00 元（2025-06-01）
均價：1700.00 元
距高點：-6.3%
距低點：+14.8%
━━━━━━━━━━━━━━
📈 技術分析
5日均線：1775.00 元 ✅
20日均線：1760.00 元 ✅
60日均線：1720.00 元 ✅
━━━━━━━━━━━━━━
📈 短中期多頭格局
✅ 建議：可持續持有
━━━━━━━━━━━━━━
📝 歷史：365/365 天 (Google Sheets ☁️)

---

## Render.com 部署建議

- 建立 Cron Job，排程建議：
  - 盤中：09:00-13:30，每 3 分鐘
  - 盤後：14:00-14:30，每 3 分鐘
- 指令：python tsmc_price_notify.py
- 設定所有必要環境變數

---

## 專案結構

TSMC-Notify/
├── tsmc_price_notify.py   # 主程式
├── requirements.txt       # 相依套件
├── README.md              # 說明文件
├── channelaccesstoken.txt # (可選) LINE Token 檔
├── tsmc-monitor-2a246d265897.json # (可選) Google 憑證檔

---

## 常見問題

- Google Sheets 權限錯誤：請確認 Service Account 已加入該 Sheet 共用
- LINE 未收到通知：請檢查 Token 與 User ID 是否正確
- 只新增一筆資料：設計上每天只新增一筆，避免重複，適合做長期均線與年度統計
- 多次執行不會重複寫入同一天資料

---

## 授權
MIT License

---

如有問題，請開 Issue 或聯絡作者。

**如果覺得有幫助，歡迎給 Star！**
