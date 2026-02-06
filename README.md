# 台積電股價監控系統 🚀

自動監控台積電（2330）股價，並透過 LINE 推送通知。

## ✨ 功能特點

- 📊 即時獲取台積電股價
- 📱 LINE 即時推送通知
- 🎯 動態區間計算（±2%）
- ⏰ 零股交易時間自動監控
- 🌏 部署在 Render.com（新加坡節點，低延遲）

---

## 🕐 監控時間

| 時段 | 時間 | 頻率 |
|------|------|------|
| **盤中零股** | 09:00 - 13:30 | 每 3 分鐘 |
| **盤後零股** | 14:00 - 14:30 | 每 3 分鐘 |

*僅在週一至週五的交易日運行*

---

## 📋 系統架構

```
┌─────────────────────────────────────────────┐
│          Render.com Cron Jobs               │
│  ┌──────────────────────────────────────┐   │
│  │  盤中監控 (09:00-13:30)              │   │
│  │  Cron: */3 1-5 * * 1-5               │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │  盤後監控 (14:00-14:30)              │   │
│  │  Cron: */3 6 * * 1-5                 │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│     台灣證券交易所 API                       │
│     mis.twse.com.tw                         │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│          LINE Messaging API                 │
│          推送通知到您的手機                  │
└─────────────────────────────────────────────┘
```

---

## 🚀 部署指南

### 前置需求

1. **LINE Messaging API**
   - 前往 [LINE Developers Console](https://developers.line.biz/console/)
   - 建立 Messaging API Channel
   - 取得 `Channel Access Token`
   - 取得您的 `User ID`

2. **Render.com 帳號**
   - 註冊：https://render.com
   - 使用 GitHub 帳號登入

---

### 部署步驟

#### 1. Fork 或 Clone 本專案

```bash
git clone https://github.com/Raito66/tsmc-price-monitor.git
cd tsmc-price-monitor
```

#### 2. 在 Render.com 建立 Cron Job（盤中監控）

1. 登入 Render.com
2. 點擊 **"New +"** → **"Cron Job"**
3. 填寫設定：
   - **Name**: `tsmc-monitor-trading-hours`
   - **Region**: `Singapore`
   - **Repository**: 選擇您的儲存庫
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Command**: `python src/tsmc_price_notify.py`
   - **Schedule**: `*/3 1-5 * * 1-5`

4. 新增環境變數：
   - `LINE_CHANNEL_ACCESS_TOKEN`: 您的 LINE Token
   - `LINE_USER_ID`: 您的 LINE User ID

5. **Instance Type**: 選擇 `Starter`（512MB, 0.5 CPU）

6. 點擊 **"Create Cron Job"**

#### 3. 建立第二個 Cron Job（盤後監控）

重複步驟 2，但修改：
- **Name**: `tsmc-monitor-after-hours`
- **Schedule**: `*/3 6 * * 1-5`

其他設定保持一致。

---

## 📱 通知格式

### 一般通知
```
【台積電價格監控】
時間：2026-02-06 10:30:00
現價：1050.00 元
動態區間：1029.00 ~ 1071.00 元
```

### 帶建議的通知
```
【台積電價格監控】
時間：2026-02-06 10:30:00
現價：1030.00 元
動態區間：1029.00 ~ 1071.00 元
（接近下緣，偏買入）
```

---

## ⚙️ 設定說明

### 環境變數

| 變數名 | 說明 | 必需 |
|--------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API 的 Token | ✅ 是 |
| `LINE_USER_ID` | LINE 使用者 ID | ✅ 是 |

### 參數調整

編輯 `src/tsmc_price_notify.py`：

```python
PERCENT_RANGE = 2.0     # 動態區間百分比（±2%）
MIN_RANGE = 60          # 最小區間寬度（元）
```

---

## 📊 費用說明

### Render.com 費用（Starter 方案）

- **單次執行**：約 15 秒
- **每次費用**：$0.00004
- **每天執行**：約 110 次
- **每天費用**：約 $0.004
- **每月費用**：約 **$0.10 美元**

*非常便宜，每月不到 1 美元！*

---

## 🔧 本地測試

### 安裝相依套件

```bash
pip install -r requirements.txt
```

### 設定環境變數

```bash
export LINE_CHANNEL_ACCESS_TOKEN="your_token_here"
export LINE_USER_ID="your_user_id_here"
```

### 執行

```bash
python src/tsmc_price_notify.py
```

---

## 📁 專案結構

```
tsmc-price-monitor/
├── src/
│   └── tsmc_price_notify.py    # 主程式
├── requirements.txt             # Python 相依套件
├── README.md                    # 說明文件
└── .gitignore                   # Git 忽略檔案
```

---

## 🛠️ 故障排除

### 沒有收到通知？

1. **檢查 Render Logs**
   - 進入 Cron Job 詳情頁
   - 點擊 "Logs" 查看執行日誌

2. **檢查環境變數**
   - 確認 `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_USER_ID` 已設定
   - 注意不要有多餘的空格

3. **檢查 LINE Bot**
   - 確認已將 Bot 加為好友
   - 檢查 Channel 是否啟用

### 收到錯誤通知？

- **「無法取得最新成交價」**：
  - 可能是非交易時間
  - 或台灣證交所 API 暫時無回應

### 時間不準確？

- Render 使用 UTC 時間
- 程式會自動轉換為台灣時間（UTC+8）
- 檢查 Cron 表達式是否正確

---

## 📈 未來計畫

- [ ] 支援多支股票監控
- [ ] 支援自訂提醒條件
- [ ] 新增技術指標分析
- [ ] 支援 Telegram 推送
- [ ] Web Dashboard

---

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

---

## 📄 授權條款

MIT License

---

## 💡 常見問題

### Q: 為什麼選擇 Render.com？
A: 
- ✅ 穩定可靠，幾乎無延遲
- ✅ 費用極低（約 $0.10/月）
- ✅ 新加坡節點，存取台灣速度快

### Q: 可以改回 GitHub Actions 嗎？
A: 可以，但 GitHub Actions 有延遲（5-30分鐘），且執行時間不穩定。

### Q: 如何修改監控頻率？
A: 修改 Render 的 Schedule 參數：
- 每 5 分鐘：`*/5 1-5 * * 1-5`
- 每 10 分鐘：`*/10 1-5 * * 1-5`

### Q: 可以監控其他股票嗎？
A: 可以，修改 `TSMC_SYMBOL = "2330"` 為其他股票代號即可。

---

## 📞 聯絡方式

如有問題，請提交 Issue 或聯絡作者。

---

**⭐ 如果這個專案對您有幫助，請給個 Star！**