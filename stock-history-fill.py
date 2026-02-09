import os
from dotenv import load_dotenv
load_dotenv()
import json
from datetime import datetime, timedelta, timezone
import pandas as pd
import time
from FinMind.data import DataLoader
from google.oauth2 import service_account
from googleapiclient.discovery import build

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")

if not all([CHANNEL_ACCESS_TOKEN, USER_ID, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_ID, FINMIND_TOKEN]):
    raise RuntimeError("缺少必要的環境變數")

STOCK_LIST = ["2330","6770","3481","2337","2344","2409","2367"]
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

def write_log(msg):
    with open("error.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    print(msg)

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

def load_history_from_sheets(service):
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
                try:
                    price = float(row[1]) if row[1] not in ('', None) else None
                except Exception:
                    price = None
                if price is not None:
                    history.append({
                        "date": row[0],
                        "price": price,
                        "timestamp": row[5] if len(row) > 5 else row[0]
                    })
        return history
    except Exception as e:
        write_log(f"讀取 Sheets 失敗：{e}")
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
        write_log(f"{stock_id} 寫入 Sheets 失敗：{e}")
        return False

def calculate_ma(prices, window):
    return pd.Series(prices).rolling(window).mean().iloc[-1] if len(prices) >= window else None

def trim_history_to_limit(service, stock_id, limit=400):
    if not service:
        return
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:H"
        ).execute()
        values = result.get("values", [])
        stock_rows = [row for row in values if len(row) > 0 and row[0] == stock_id]
        if len(stock_rows) > limit:
            to_delete = len(stock_rows) - limit
            dates_to_delete = [row[2] for row in stock_rows[:to_delete]]
            for date in dates_to_delete:
                try:
                    service.spreadsheets().values().clear(
                        spreadsheetId=GOOGLE_SHEET_ID,
                        range=f"{SHEET_NAME}!A2:H",
                        body={}
                    ).execute()
                    remaining_rows = [row for row in values if not (len(row) > 0 and row[0] == stock_id and row[2] == date)]
                    if remaining_rows:
                        service.spreadsheets().values().update(
                            spreadsheetId=GOOGLE_SHEET_ID,
                            range=f"{SHEET_NAME}!A2",
                            valueInputOption="USER_ENTERED",
                            body={"values": remaining_rows}
                        ).execute()
                except Exception as e:
                    write_log(f"{stock_id} 刪除舊資料失敗：{e}")
    except Exception as e:
        write_log(f"{stock_id} trim_history_to_limit 失敗：{e}")

def fill_missing_history(service, dl, batch_days=10, sleep_sec=60):
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    for stock_id in STOCK_LIST:
        stock_name = STOCK_NAME_MAP.get(stock_id, stock_id)
        history = load_history_from_sheets(service)
        existing_dates = set([row["date"] for row in history if row.get("stock_id", stock_id) == stock_id])
        start_date = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(stock_id, start_date=start_date, end_date=end_date)
        if df.empty:
            write_log(f"{stock_id} 歷史收盤價資料為空，無法補齊")
            continue
        closes = df["close"].tolist()
        dates = df["date"].tolist()
        total = len(dates)
        for batch_start in range(0, total, batch_days):
            batch_end = min(batch_start + batch_days, total)
            for i in range(batch_start, batch_end):
                date = dates[i]
                if date not in existing_dates:
                    ma5 = calculate_ma(closes[:i+1], 5)
                    ma20 = calculate_ma(closes[:i+1], 20)
                    ma60 = calculate_ma(closes[:i+1], 60)
                    price = closes[i]
                    timestamp = f"{date} 00:00:00"
                    save_to_sheets(service, stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp)
                    write_log(f"{stock_id} 補齊歷史收盤價：{date} - {price}")
            write_log(f"{stock_id} batch {batch_start}-{batch_end} 補齊完成，sleep {sleep_sec} 秒")
            time.sleep(sleep_sec)
        trim_history_to_limit(service, stock_id, limit=400)

def main():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    write_log(f"🕐 台灣時間：{now_str}")
    service = get_sheets_service()
    dl = DataLoader()
    dl.login_by_token(FINMIND_TOKEN)
    fill_missing_history(service, dl)

if __name__ == "__main__":
    main()
