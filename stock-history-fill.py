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

GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")

if not all([GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_ID, FINMIND_TOKEN]):
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

def load_history_from_sheets(service, stock_id=None):
    if not service:
        return []
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:H"
        ).execute()
        values = result.get("values", [])
        history = []
        for row in values:
            if len(row) >= 4:
                try:
                    price = float(row[3]) if row[3] not in ('', None) else None
                except Exception:
                    price = None
                ma5 = row[4] if len(row) > 4 else None
                ma20 = row[5] if len(row) > 5 else None
                ma60 = row[6] if len(row) > 6 else None
                history.append({
                    "stock_id": row[0],
                    "date": row[2],
                    "price": price,
                    "ma5": ma5,
                    "ma20": ma20,
                    "ma60": ma60,
                    "timestamp": row[7] if len(row) > 7 else row[2]
                })
        if stock_id:
            return [h for h in history if h["stock_id"] == stock_id]
        return history
    except Exception as e:
        write_log(f"讀取 Sheets 失敗：{e}")
        return []

def save_to_sheets(service, stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp):
    if not service:
        return False
    while True:
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
            err_str = str(e)
            if '429' in err_str or 'quota' in err_str.lower():
                write_log(f"append quota exceeded，sleep 60 秒後重試")
                time.sleep(60)
                continue
            else:
                write_log(f"{stock_id} 寫入 Sheets 失敗：{e}")
                return False

def update_row_in_sheets(service, stock_id, date, stock_name, price, ma5, ma20, ma60, timestamp):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:H"
        ).execute()
        values = result.get("values", [])
        for idx, row in enumerate(values):
            if len(row) > 2 and row[0] == stock_id and row[2] == date:
                update_range = f"{SHEET_NAME}!A{idx+2}:H{idx+2}"
                update_values = [[stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp]]
                while True:
                    try:
                        service.spreadsheets().values().update(
                            spreadsheetId=GOOGLE_SHEET_ID,
                            range=update_range,
                            valueInputOption="USER_ENTERED",
                            body={"values": update_values}
                        ).execute()
                        write_log(f"{stock_id} 覆蓋 Sheets 成功：{date} - {price}")
                        return True
                    except Exception as e:
                        err_str = str(e)
                        if '429' in err_str or 'quota' in err_str.lower():
                            write_log(f"update quota exceeded，sleep 60 秒後重試")
                            time.sleep(60)
                            continue
                        else:
                            write_log(f"{stock_id} 更新 Sheets 失敗：{e}")
                            return False
        # 沒找到就append
        return save_to_sheets(service, stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp)
    except Exception as e:
        write_log(f"{stock_id} 更新 Sheets 失敗：{e}")
        return False

def calculate_ma(prices, window):
    return pd.Series(prices).rolling(window).mean().iloc[-1] if len(prices) >= window else None

def safe_clear(service, spreadsheetId, range_):
    while True:
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheetId,
                range=range_,
                body={}
            ).execute()
            return True
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'quota' in err_str.lower():
                write_log(f"clear quota exceeded，sleep 60 秒後重試")
                time.sleep(60)
                continue
            else:
                write_log(f"clear 失敗：{e}")
                return False

def safe_update(service, spreadsheetId, range_, values):
    while True:
        try:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheetId,
                range=range_,
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
            return True
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'quota' in err_str.lower():
                write_log(f"update quota exceeded，sleep 60 秒後重試")
                time.sleep(60)
                continue
            else:
                write_log(f"update 失敗：{e}")
                return False

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
                    # 用 safe_clear 包裝
                    safe_clear(service, GOOGLE_SHEET_ID, f"{SHEET_NAME}!A2:H")
                    remaining_rows = [row for row in values if not (len(row) > 0 and row[0] == stock_id and row[2] == date)]
                    if remaining_rows:
                        # 用 safe_update 包裝
                        safe_update(service, GOOGLE_SHEET_ID, f"{SHEET_NAME}!A2", remaining_rows)
                except Exception as e:
                    write_log(f"{stock_id} 刪除舊資料失敗：{e}")
    except Exception as e:
        write_log(f"{stock_id} trim_history_to_limit 失敗：{e}")

def fill_missing_history(service, dl, batch_days=10, sleep_sec=60):
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    for stock_id in STOCK_LIST:
        stock_name = STOCK_NAME_MAP.get(stock_id, stock_id)
        history = load_history_from_sheets(service, stock_id)
        # 以日期為key，方便查找
        history_map = {h["date"]: h for h in history}
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
                price = closes[i]
                ma5 = calculate_ma(closes[:i+1], 5)
                ma20 = calculate_ma(closes[:i+1], 20)
                ma60 = calculate_ma(closes[:i+1], 60)
                timestamp = f"{date} 00:00:00"
                # 判斷該日期資料是否完整
                exist = history_map.get(date)
                if exist:
                    # 檢查均線欄位是否都齊全且非空
                    if all([
                        exist.get("price") not in (None, ''),
                        exist.get("ma5") not in (None, '', '無資料'),
                        exist.get("ma20") not in (None, '', '無資料'),
                        exist.get("ma60") not in (None, '', '無資料')
                    ]):
                        continue  # 完整就跳過
                # 不完整或不存在就覆蓋
                update_row_in_sheets(service, stock_id, date, stock_name, price, ma5, ma20, ma60, timestamp)
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
    # 每分鐘最多寫入 60 次
    fill_missing_history(service, dl, batch_days=60, sleep_sec=60)

if __name__ == "__main__":
    main()
