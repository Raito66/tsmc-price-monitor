# 台積電價格監控 - 使用 LINE Messaging API 推播通知（Cron 穩定版）
# 每次執行：抓一次股價 → 與昨收比較 → 分級提醒 → 結束

import requests
import os
from datetime import datetime, timedelta

# ======================== 環境變數 ========================

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

if not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN 未設定")
if not USER_ID:
    raise RuntimeError("LINE_USER_ID 未設定")

# ======================== 參數設定 ========================

TSMC_SYMBOL = "2330"
API_URL = (
    f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    f"?ex_ch=tse_{TSMC_SYMBOL}.tw&json=1&delay=0"
)

# 漲跌幅門檻設定（可依需求調整）
THRESHOLD_BIG_DROP = -3.0    # 大跌門檻
THRESHOLD_DROP = -2.0        # 下跌門檻
THRESHOLD_SMALL_DROP = -1.0  # 小跌門檻
THRESHOLD_SMALL_RISE = 1.0   # 小漲門檻
THRESHOLD_RISE = 2.0         # 上漲門檻
THRESHOLD_BIG_RISE = 3.0     # 大漲門檻

# ==========================================================

def send_line_push(message: str):
    """發送 LINE 推播訊息"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": message}],
    }

    r = requests.post(url, headers=headers, json=payload, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"LINE 推播失敗：{r.status_code} - {r.text}")

def get_tsmc_data(max_retries=3):
    """取得台積電股價資訊（現價 + 昨收）"""
    for _ in range(max_retries):
        try:
            r = requests.get(API_URL, timeout=10)
            data = r.json()
            if data.get("msgArray"):
                stock_data = data["msgArray"][0]
                
                # z: 最新成交價, y: 昨收價
                price_str = stock_data.get("z")
                yesterday_str = stock_data.get("y")
                
                if price_str and price_str != "-" and yesterday_str and yesterday_str != "-":
                    return {
                        "price": float(price_str),
                        "yesterday_close": float(yesterday_str)
                    }
        except Exception as e:
            print(f"⚠️ API 請求失敗：{e}")
    return None

def get_alert_message(change_percent: float) -> str:
    """根據漲跌幅返回分級提醒訊息"""
    if change_percent <= THRESHOLD_BIG_DROP:
        return f"🔥 大跌 {abs(change_percent):.2f}%！建議買入"
    elif change_percent <= THRESHOLD_DROP:
        return f"💡 下跌 {abs(change_percent):.2f}%，可考慮買入"
    elif change_percent <= THRESHOLD_SMALL_DROP:
        return f"📉 小跌 {abs(change_percent):.2f}%，持續觀察"
    elif change_percent >= THRESHOLD_BIG_RISE:
        return f"🚫 大漲 {change_percent:.2f}%！不建議追高"
    elif change_percent >= THRESHOLD_RISE:
        return f"⚠️ 上漲 {change_percent:.2f}%，建議觀望"
    elif change_percent >= THRESHOLD_SMALL_RISE:
        return f"📈 小漲 {change_percent:.2f}%"
    else:
        return f"📊 持平（{change_percent:+.2f}%）"

def main():
    # 取得台灣時間
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"🕐 台灣時間：{now}")
    print(f"🕐 UTC 時間：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 取得股價資料
    stock_data = get_tsmc_data()
    if stock_data is None:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ 無法取得股價資料")
        print("⚠️ 無法取得股價")
        return
    
    price = stock_data["price"]
    yesterday_close = stock_data["yesterday_close"]
    
    # 計算漲跌幅
    change_percent = ((price - yesterday_close) / yesterday_close) * 100
    change_amount = price - yesterday_close
    
    # 取得分級提醒
    alert = get_alert_message(change_percent)
    
    # 組合推播訊息
    msg = (
        f"【台積電價格監控】\n"
        f"時間：{now}\n"
        f"━━━━━━━━━━━━━━\n"
        f"現價：{price:.2f} 元\n"
        f"昨收：{yesterday_close:.2f} 元\n"
        f"漲跌：{change_amount:+.2f} 元（{change_percent:+.2f}%）\n"
        f"━━━━━━━━━━━━━━\n"
        f"{alert}"
    )
    
    send_line_push(msg)
    print("✅ 推播股價資訊完成")
    print(f"   現價：{price:.2f}，昨收：{yesterday_close:.2f}，漲跌：{change_percent:+.2f}%")

if __name__ == "__main__":
    main()