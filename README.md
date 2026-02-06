# 台積電價格監控 (TSMC Price Monitor)

每 3~5 分鐘檢查台積電股價，當價格進入動態區間（±2%）時，透過 LINE 推播通知。

## 功能

* 動態計算提醒區間（依當前股價 ±2%）
* 使用 LINE Messaging API 推播通知（長期穩定）
* 從外部檔案讀取 token（安全管理）
* 包含交易時間判斷與重試機制

## 安裝與使用

1. 建立 `config/` 資料夾，將 LINE Channel Access Token 放入：

   
   config/channelaccesstoken.txt
   
2. 安裝依賴：

   
   pip install -r requirements.txt
   
3. 執行程式：

   
   python src/tsmc_price_notify.py
   

> ⚠️ **安全提醒**
>
> * `channelaccesstoken.txt` **絕對不要 commit 到 GitHub**
> * 建議將 `config/` 加入 `.gitignore`
> * 也可以改用環境變數管理 token，避免明文存放

## 部署建議

* [Render.com](https://render.com/)（免費方案）
* [Railway.app](https://railway.app/)
* [Heroku](https://www.heroku.com/)（付費 Eco 方案）

## 開發建議

* Python 版本建議使用 3.11
* workflow 或排程建議每 3~5 分鐘觸發程式，保持穩定推播
