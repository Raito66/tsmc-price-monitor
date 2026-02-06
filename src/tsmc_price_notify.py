# 台積電價格監控 - 使用 LINE Messaging API 推播通知（Cron 穩定版）
# 每次執行：抓一次股價 → 計算動態區間 → 推播 → 結束

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

PERCENT_RANGE = 2.0     # ±2%
MIN_RANGE = 60          # 最小區間寬度（元）

TSMC_SYMBOL = "2330"
API_URL = (
    f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    f"?ex_ch=tse_{TSMC_SYMBOL}.tw&json=1&delay=0"
)

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

def get_tsmc_price(max_retries=3):
    """取得台積電最新成交價"""
    for _ in range(max_retries):
        try:
            r = requests.get(API_URL, timeout=10)
            data = r.json()
            if data.get("msgArray"):
                price_str = data["msgArray"][0].get("z")
                if price_str and price_str != "-":
                    return float(price_str)
        except Exception:
            pass
    return None

def main():
    # 取得台灣時間
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    price = get_tsmc_price()
    if price is None:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ 無法取得最新成交價")
        return

    # 動態區間計算
    offset = price * (PERCENT_RANGE / 100)
    low = price - offset
    high = price + offset

    if high - low < MIN_RANGE:
        low = price - MIN_RANGE / 2
        high = price + MIN_RANGE / 2

    position = ""
    if price <= low + (high - low) * 0.2:
        position = "（接近下緣，偏買入）"
    elif price >= high - (high - low) * 0.2:
        position = "（接近上緣，偏觀望）"

    msg = (
        f"【台積電價格監控】\n"
        f"時間：{now}\n"
        f"現價：{price:.2f} 元\n"
        f"動態區間：{low:.2f} ~ {high:.2f} 元\n"
        f"{position}"
    )

    send_line_push(msg)
    print("推播完成")

if __name__ == "__main__":
    main()
