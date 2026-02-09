# 多股價格監控 - Google Sheets 永久儲存
# 盤中：即時成交價
# 盤後：即時成交價 + 正式收盤價寫入 Sheets
# 支援多支股票同時監控與推播

import os
from dotenv import load_dotenv
load_dotenv()  # 只會補充本地 .env，優先用系統環境變數
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

STOCK_LIST = ["2330","6770","3481","2337","2344","2409","2367"]  # 可以放多支股票
HISTORY_DAYS = 365
SHEET_NAME = "Sheet1"

STOCK_NAME_MAP = {
    "2330": "台積電",
    "6770": "力積電",
    "3481": "群創",
    "2337": "旺宏",
    "2344": "華邦電",
    "2409": "友達",
    "2367": "燿華"
}

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
    try:
        requests.post(url, headers=headers, json={"to": USER_ID, "messages":[{"type":"text","text":message}]}, timeout=10)
    except Exception as e:
        print(f"LINE 推播失敗：{e}")

def write_log(msg):
    with open("error.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    # 也印出到 console 方便 debug
    print(msg)

# ======================== 核心函式 ========================

def get_latest_instant_price(dl, stock_id: str):
    """取得單支股票盤中即時成交價"""
    df = None
    try:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        df = dl.get_data(dataset="TaiwanStockPrice", data_id=stock_id, start_date=today)
        if df is None or df.empty or 'deal_price' not in df.columns:
            msg = f"{stock_id} 即時資料為空或缺少 deal_price 欄位, df={df}"
            write_log(msg)
            return None
        latest = df.iloc[-1]
        return {"price": float(latest["deal_price"]), "time": latest["datetime"]}
    except Exception as e:
        error_msg = f"{stock_id} 取得即時價失敗：{e}"
        write_log(error_msg)
        write_log(f"{stock_id} df repr: {repr(df)}")
        try:
            write_log(f"{stock_id} df columns: {df.columns if df is not None else 'None'}")
            write_log(f"{stock_id} df head: {df.head() if df is not None and not df.empty else 'Empty'}")
        except Exception as log_e:
            write_log(f"{stock_id} log df error: {log_e}")
        return None

def get_today_close(dl, stock_id: str, date_str: str) -> Optional[float]:
    """盤後正式收盤價（存 Sheets 用）"""
    try:
        df = dl.taiwan_stock_daily(stock_id, start_date=date_str, end_date=date_str)
        if not df.empty:
            return float(df.iloc[0]["close"])
        return None
    except Exception as e:
        error_msg = f"{stock_id} 取得收盤價失敗：{e}"
        write_log(error_msg)
        return None

def get_yesterday_close(dl, stock_id: str) -> Optional[float]:
    """前一交易日收盤價"""
    try:
        end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(stock_id, start, end)
        if not df.empty:
            return float(df.iloc[-1]["close"])
        return None
    except Exception as e:
        error_msg = f"{stock_id} 取得昨收失敗：{e}"
        write_log(error_msg)
        return None

def get_stock_data(dl, stock_id: str) -> Optional[Dict]:
    """取得單支股票資料，盤中即時價 + 盤後收盤價"""
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")

    instant = get_latest_instant_price(dl, stock_id)
    if not instant:
        return None

    yesterday_close = get_yesterday_close(dl, stock_id) or instant["price"]

    is_after_close = now.hour > 13 or (now.hour == 13 and now.minute >= 30)

    result = {
        "stock_id": stock_id,
        "latest_price": instant["price"],
        "latest_time": instant["time"],
        "yesterday_close": yesterday_close,
        "date": today,
        "is_after_close": is_after_close
    }

    if is_after_close:
        close_price = get_today_close(dl, stock_id, today)
        if close_price:
            result["close_price"] = close_price

    return result

def calculate_ma(prices, window):
    return pd.Series(prices).rolling(window).mean().iloc[-1] if len(prices) >= window else None

# ======================== Google Sheets ========================

def load_history_from_sheets(service) -> List[Dict]:
    if not service:
        return []
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:F"
        ).execute()
        values = result.get("values", [])
        history = []
        for row in values:
            if len(row) >= 2:
                history.append({
                    "date": row[0],
                    "price": float(row[1]),
                    "timestamp": row[5] if len(row) > 5 else row[0]
                })
        return history
    except Exception as e:
        error_msg = f"讀取 Sheets 失敗：{e}"
        write_log(error_msg)
        return []

def save_to_sheets(service, stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp):
    if not service:
        return False
    try:
        values = [[stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp]]
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        write_log(f"{stock_id} 寫入 Sheets 成功：{date} - {price:.2f}")
        return True
    except Exception as e:
        error_msg = f"{stock_id} 寫入 Sheets 失敗：{e}"
        write_log(error_msg)
        return False

# ======================== 主程式 ========================

def main():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    write_log(f"🕐 台灣時間：{now_str}")

    service = get_sheets_service()
    dl = DataLoader()
    dl.login_by_token(FINMIND_TOKEN)

    for stock_id in STOCK_LIST:
        stock_name = STOCK_NAME_MAP.get(stock_id, stock_id)
        stock = get_stock_data(dl, stock_id)
        if not stock:
            write_log(f"{stock_id} 無法取得資料")
            continue

        # 取得歷史收盤價
        df = dl.taiwan_stock_daily(stock_id, start_date=(now - timedelta(days=61)).strftime("%Y-%m-%d"), end_date=now.strftime("%Y-%m-%d"))
        closes = df["close"].tolist() if not df.empty else []

        ma5 = calculate_ma(closes, 5)
        ma20 = calculate_ma(closes, 20)
        ma60 = calculate_ma(closes, 60)

        latest = stock["latest_price"]
        yesterday = stock["yesterday_close"]
        change = latest - yesterday
        pct = change / yesterday * 100 if yesterday else 0

        msg = [
            f"【{stock_id} {stock_name} 價格監控】",
            f"時間：{now_str}",
            "━━━━━━━━━━━━━━",
            f"現價：{latest:.2f} 元",
            f"昨收：{yesterday:.2f} 元",
            f"漲跌：{change:+.2f}（{pct:+.2f}%）",
            f"5日均線：{ma5:.2f}" if ma5 is not None else "5日均線：無資料",
            f"20日均線：{ma20:.2f}" if ma20 is not None else "20日均線：無資料",
            f"60日均線：{ma60:.2f}" if ma60 is not None else "60日均線：無資料"
        ]

        if stock["is_after_close"] and "close_price" in stock:
            msg.append(f"今日收盤：{stock['close_price']:.2f} 元")
            save_to_sheets(service, stock_id, stock_name, stock["date"], stock["close_price"], ma5, ma20, ma60, now_str)

        msg.append("※ 資料來源：FinMind（付費版）")
        send_line_push("\n".join(msg))
        write_log(f"{stock_id} LINE 推播內容：\n" + "\n".join(msg))
        write_log(f"{stock_id} 推播完成")

if __name__ == "__main__":
    main()
