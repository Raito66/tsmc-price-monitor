# 台積電價格監控 - 使用 Google Sheets 永久儲存
# 盤中：即時成交價
# 盤後：即時成交價 + 正式收盤價寫入 Sheets

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pandas as pd

from FinMind.data import DataLoader
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================== 環境變數 ========================

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")

if not all([CHANNEL_ACCESS_TOKEN, USER_ID, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_ID, FINMIND_TOKEN]):
    raise RuntimeError("缺少必要的環境變數")

# ======================== 參數設定 ========================

TSMC_STOCK_ID = "2330"
HISTORY_DAYS = 365
SHEET_NAME = "Sheet1"

# ==========================================================

def get_sheets_service():
    try:
        creds_json = GOOGLE_SHEETS_CREDENTIALS
        credentials_info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=credentials)
        print("✅ Google Sheets 連線成功")
        return service
    except Exception as e:
        print(f"⚠️ Google Sheets 連線失敗：{e}")
        return None


def send_line_push(message: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    }
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=payload, timeout=10)


# ======================== ★ 核心修正：即時價 ========================

def get_latest_instant_price(dl, stock_id: str):
    try:
        df = dl.get_data(
            dataset="TaiwanStockInstant",
            data_id=stock_id
        )

        if df.empty:
            print(f"{stock_id} 即時資料為空")
            return None

        latest = df.iloc[-1]

        price = float(latest["deal_price"])
        time_str = latest["datetime"]

        print(f"{stock_id} 即時成交：{price}（{time_str}）")

        return {
            "price": price,
            "time": time_str
        }

    except Exception as e:
        print(f"{stock_id} 取得即時價失敗：{e}")
        return None



def get_today_close(dl, date_str: str) -> Optional[float]:
    """盤後正式收盤價（存 Sheets 用）"""
    try:
        df = dl.taiwan_stock_daily(
            stock_id=TSMC_STOCK_ID,
            start_date=date_str,
            end_date=date_str
        )
        if not df.empty:
            return float(df.iloc[0]["close"])
        return None
    except Exception as e:
        print(f"取得收盤價失敗：{e}")
        return None


def get_yesterday_close(dl) -> Optional[float]:
    try:
        end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(TSMC_STOCK_ID, start, end)
        if not df.empty:
            return float(df.iloc[-1]["close"])
        return None
    except:
        return None


# ======================== 主邏輯 ========================

def get_tsmc_data(dl) -> Optional[Dict]:
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")

    instant = get_latest_instant_price(dl, TSMC_STOCK_ID)
    if not instant:
        return None

    yesterday_close = get_yesterday_close(dl) or instant["price"]

    is_after_close = now.hour > 13 or (now.hour == 13 and now.minute >= 30)

    result = {
        "latest_price": instant["price"],
        "latest_time": instant["time"],
        "yesterday_close": yesterday_close,
        "date": today,
        "is_after_close": is_after_close
    }

    if is_after_close:
        close_price = get_today_close(dl, today)
        if close_price:
            result["close_price"] = close_price

    return result


# ======================== Sheets / MA（你原本的邏輯，未動） ========================

def calculate_ma(history, days):
    if len(history) < days:
        return None
    return sum(h["price"] for h in history[-days:]) / days


# ======================== 主程式 ========================

def main():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today = now.strftime("%Y-%m-%d")

    print(f"🕐 台灣時間：{now_str}")

    service = get_sheets_service()
    dl = DataLoader()
    dl.login_by_token(FINMIND_TOKEN)

    stock = get_tsmc_data(dl)
    if not stock:
        send_line_push(f"【台積電監控】\n{now_str}\n⚠️ 無法取得股價")
        return

    latest = stock["latest_price"]
    yesterday = stock["yesterday_close"]
    change = latest - yesterday
    pct = change / yesterday * 100 if yesterday else 0

    title = "【台積電盤中快訊】" if not stock["is_after_close"] else "【台積電價格監控】"

    msg = [
        title,
        f"時間：{now_str}",
        "━━━━━━━━━━━━━━",
        f"最新成交：{stock['latest_time']}",
        f"現價：{latest:.2f} 元",
        f"昨收：{yesterday:.2f} 元",
        f"漲跌：{change:+.2f}（{pct:+.2f}%）"
    ]

    if stock["is_after_close"] and "close_price" in stock:
        msg.append(f"今日收盤：{stock['close_price']:.2f} 元")

    msg.append("※ 資料來源：FinMind（付費版）")
    send_line_push("\n".join(msg))

    print("推播完成")


if __name__ == "__main__":
    main()
