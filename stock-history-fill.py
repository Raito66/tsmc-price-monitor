import os
import re
import sys
from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding='utf-8')

import json
import time
from datetime import datetime, timedelta, timezone
import pandas as pd
from FinMind.data import DataLoader
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gc

# ======================== 環境變數 ========================
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")

if not all([GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_ID, FINMIND_TOKEN]):
    raise RuntimeError("缺少必要的環境變數")

# ======================== 參數設定 ========================
STOCK_LIST = ["2330", "6770", "3481", "2337", "2344", "2409", "2367", "3374", "3324", "00642U", "0050", "2231"]
STOCK_NAME_MAP = {
    "2330": "台積電",
    "6770": "力積電",
    "3481": "群創",
    "2337": "旺宏",
    "2344": "華邦電",
    "2409": "友達",
    "2367": "燿華",
    "3374": "精材",
    "3324": "雙鴻",
    "00642U": "期元大S&P石油",
    "0050": "元大台灣50",
    "2231": "為升"
}

SHEET_NAME = "Sheet1"
CONFIG_SHEET_NAME = "Config"

# 關鍵參數：Render 512MiB 安全設定
BATCH_DAYS = 90           # 90天≈63交易日，足以計算MA60
SLEEP_BETWEEN_STOCKS = 60   # 每支股票處理完休息 60 秒
SLEEP_BETWEEN_WRITES = 8    # 每寫 8 筆休息一次（防 Google API 限流）

# ======================== 工具函式 ========================
def write_log(msg):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open("error.log", "a", encoding="utf-8") as f:
        f.write(f"{now_str} {msg}\n")
    print(f"{now_str} {msg}")

def get_sheets_service():
    try:
        creds_json = GOOGLE_SHEETS_CREDENTIALS
        credentials_info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=credentials)
        write_log("✅ Google Sheets 連線成功")
        return service
    except Exception as e:
        write_log(f"⚠️ Google Sheets 連線失敗：{e}")
        return None

def get_sheet_id(service, sheet_name):
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=GOOGLE_SHEET_ID).execute()
        for sheet in spreadsheet["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
    except Exception as e:
        write_log(f"取得 sheet ID 失敗：{e}")
    return None


def reset_sheet_filter(service):
    sheet_id = get_sheet_id(service, SHEET_NAME)
    if sheet_id is None:
        write_log("⚠️ 無法取得 Sheet1 ID，跳過 filter 重設")
        return
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_SHEET_ID,
            body={"requests": [
                {"clearBasicFilter": {"sheetId": sheet_id}},
                {"setBasicFilter": {"filter": {"range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": 8
                }}}}
            ]}
        ).execute()
        write_log("✅ Sheet1 篩選器重設完成")
    except Exception as e:
        write_log(f"⚠️ 篩選器重設失敗：{e}")


def apply_sheet_formatting(service):
    """套用 Sheet1 欄位格式：文字靠左（A、B、C、H）、數字靠右（D、E、F、G）"""
    sheet_id = get_sheet_id(service, SHEET_NAME)
    if sheet_id is None:
        write_log("⚠️ 無法取得 Sheet1 ID，跳過格式套用")
        return
    try:
        requests = []
        # A欄（股票代號）→ 純文字格式，防止 0050 被吃成 50
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 10000,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "LEFT",
                "numberFormat": {"type": "TEXT"}
            }},
            "fields": "userEnteredFormat.horizontalAlignment,userEnteredFormat.numberFormat"
        }})
        for col in [1, 2, 7]:  # B=名稱, C=日期, H=timestamp → 靠左
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 10000,
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                "fields": "userEnteredFormat.horizontalAlignment"
            }})
        for col in [3, 4, 5, 6]:  # D=收盤價, E=MA5, F=MA20, G=MA60 → 靠右
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 10000,
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
                "fields": "userEnteredFormat.horizontalAlignment"
            }})
        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_SHEET_ID,
            body={"requests": requests}
        ).execute()
        write_log("✅ Sheet1 欄位格式套用完成")
    except Exception as e:
        write_log(f"⚠️ Sheet1 格式套用失敗：{e}")


def load_stock_list_from_sheets(service):
    """從 Config 分頁讀取股票清單（C欄=Y 才納入），失敗時回傳 None 使用預設清單。"""
    if not service:
        return None, None
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{CONFIG_SHEET_NAME}!A2:C"
        ).execute()
        rows = result.get("values", [])
        if not rows:
            write_log("Config 分頁無資料，使用預設清單")
            return None, None

        stock_list = []
        stock_name_map = {}

        for row in rows:
            if not row or not str(row[0]).strip():
                continue
            stock_id = str(row[0]).strip().upper()
            stock_name = str(row[1]).strip() if len(row) > 1 and row[1] else stock_id
            enabled = str(row[2]).strip().upper() if len(row) > 2 and row[2] else "Y"

            if enabled != "Y":
                write_log(f"{stock_id} 啟用欄為 {enabled}，跳過")
                continue
            if not re.match(r'^[0-9]{4,6}[A-Z]?$', stock_id):
                write_log(f"⚠️ 代號格式錯誤，跳過：{stock_id}")
                continue
            if stock_id in stock_name_map:
                continue

            stock_list.append(stock_id)
            stock_name_map[stock_id] = stock_name

        write_log(f"從 Config 分頁載入 {len(stock_list)} 支股票：{stock_list}")
        return stock_list, stock_name_map
    except Exception as e:
        write_log(f"讀取 Config 分頁失敗：{e}，使用預設清單")
        return None, None


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
            if len(row) >= 4 and (stock_id is None or row[0] == stock_id):
                try:
                    price = float(row[3]) if row[3] else None
                except:
                    price = None
                history.append({
                    "date": row[2],
                    "price": price,
                    "ma5": row[4] if len(row) > 4 else None,
                    "ma20": row[5] if len(row) > 5 else None,
                    "ma60": row[6] if len(row) > 6 else None,
                    "timestamp": row[7] if len(row) > 7 else row[2]
                })
        return history
    except Exception as e:
        write_log(f"讀取 Sheets 失敗：{e}")
        return []

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
                service.spreadsheets().values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=update_range,
                    valueInputOption="RAW",
                    body={"values": update_values}
                ).execute()
                write_log(f"{stock_id} 覆蓋 Sheets 成功：{date} - {price if price else 'None'}")
                return True
        # 沒找到就新增
        values = [[stock_id, stock_name, date, price, ma5, ma20, ma60, timestamp]]
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2",
            valueInputOption="RAW",
            body={"values": values}
        ).execute()
        write_log(f"{stock_id} 新增 Sheets 成功：{date} - {price if price else 'None'}")
        return True
    except Exception as e:
        write_log(f"{stock_id} 更新/新增 Sheets 失敗：{e}")
        return False

def calculate_ma(prices, window):
    if len(prices) < window:
        return None
    return pd.Series(prices).rolling(window).mean().iloc[-1]

def trim_history_to_limit(service, stock_id, limit=500):
    if not service:
        return
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:H"
        ).execute()
        values = result.get("values", [])
        stock_rows = [row for row in values if len(row) > 0 and row[0] == stock_id]
        if len(stock_rows) <= limit:
            return
        # 保留最新的 limit 筆
        keep_rows = stock_rows[-limit:]
        keep_dates = {row[2] for row in keep_rows}
        new_values = [row for row in values if len(row) == 0 or row[0] != stock_id or row[2] in keep_dates]
        service.spreadsheets().values().clear(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_NAME}!A2:H",
            body={}
        ).execute()
        if new_values:
            service.spreadsheets().values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f"{SHEET_NAME}!A2",
                valueInputOption="RAW",
                body={"values": new_values}
            ).execute()
        write_log(f"{stock_id} 清理完成，保留最新 {len(keep_rows)} 筆")
    except Exception as e:
        write_log(f"{stock_id} 清理歷史資料失敗：{e}")

# ======================== 主補齊函式 ========================
def fill_missing_history(service, dl, stock_list, stock_name_map):
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    end_date = now.strftime("%Y-%m-%d")

    for stock_id in stock_list:
        stock_name = stock_name_map.get(stock_id, stock_id)
        write_log(f"開始處理 {stock_id} ({stock_name})")

        # 讀取目前歷史（只用來比對）
        history = load_history_from_sheets(service, stock_id)
        history_map = {h["date"]: h for h in history}

        # 只下載最近 BATCH_DAYS 天
        start_date = (now - timedelta(days=BATCH_DAYS)).strftime("%Y-%m-%d")
        write_log(f"{stock_id} 下載範圍：{start_date} ~ {end_date}")

        try:
            df = dl.taiwan_stock_daily(stock_id, start_date=start_date, end_date=end_date)
        except Exception as e:
            write_log(f"{stock_id} FinMind 取得歷史資料失敗：{e}，跳過")
            continue

        if df.empty:
            write_log(f"{stock_id} 最近 {BATCH_DAYS} 天無資料，跳過")
            continue

        dates = df["date"].tolist()
        closes = df["close"].tolist()

        updated = 0
        for i, date in enumerate(dates):
            price = closes[i]

            ma5  = calculate_ma(closes[:i+1], 5)   if i+1 >= 5  else None
            ma20 = calculate_ma(closes[:i+1], 20)  if i+1 >= 20 else None
            ma60 = calculate_ma(closes[:i+1], 60)  if i+1 >= 60 else None

            timestamp = f"{date} 00:00:00"

            exist = history_map.get(date)
            need_update = True

            if exist:
                if all([
                    exist.get("price") not in (None, '', 'None'),
                    exist.get("ma5")  not in (None, '', '無資料'),
                    exist.get("ma20") not in (None, '', '無資料'),
                ]):
                    need_update = False

            if need_update:
                success = update_row_in_sheets(
                    service, stock_id, date, stock_name, price, ma5, ma20, ma60, timestamp
                )
                if success:
                    updated += 1

            # 每寫幾筆休息一下
            if (i + 1) % SLEEP_BETWEEN_WRITES == 0:
                time.sleep(5)

        write_log(f"{stock_id} 本次完成：更新/補齊 {updated} 筆（最近 {BATCH_DAYS} 天）")

        # 強制釋放記憶體
        del df, dates, closes
        gc.collect()

        # 每支股票處理完休息
        time.sleep(SLEEP_BETWEEN_STOCKS)

        # 可選：清理舊資料（建議先註解，等資料補齊再開啟）
        # trim_history_to_limit(service, stock_id, limit=500)

# ======================== 主程式 ========================
def main():
    write_log("=== 開始補齊歷史收盤價與均線 ===")
    service = get_sheets_service()
    if not service:
        write_log("無法連線 Google Sheets，結束執行")
        return

    dl = DataLoader()
    dl.login_by_token(FINMIND_TOKEN)

    sheets_stock_list, sheets_stock_name_map = load_stock_list_from_sheets(service)
    active_stock_list = sheets_stock_list if sheets_stock_list else STOCK_LIST
    active_stock_name_map = sheets_stock_name_map if sheets_stock_name_map else STOCK_NAME_MAP

    fill_missing_history(service, dl, active_stock_list, active_stock_name_map)
    apply_sheet_formatting(service)
    reset_sheet_filter(service)

    write_log("=== 補齊流程結束 ===")

if __name__ == "__main__":
    main()