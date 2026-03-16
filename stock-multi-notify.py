import os
import re
import sys
from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding='utf-8')

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import pandas as pd
from FinMind.data import DataLoader
import requests
import yfinance as yf
import time

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================== 環境變數 ========================
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not all([GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_ID, FINMIND_TOKEN]):
    raise RuntimeError("缺少必要的環境變數")

# ======================== 參數設定 ========================
STOCK_LIST = ["2330", "6770", "3481", "2337", "2344", "2409", "2367", "3374", "3324", "00642U", "0050", "2231"]
SHEET_NAME = "Sheet1"
CONFIG_SHEET_NAME = "Config"  # Google Sheets 股票清單分頁名稱

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
    """從 Config 分頁讀取股票清單，含格式驗證。失敗時回傳 None 使用預設清單。"""
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
        invalid = []

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
                invalid.append(stock_id)
                write_log(f"⚠️ 代號格式錯誤，跳過：{stock_id}")
                continue

            if stock_id in stock_name_map:
                write_log(f"⚠️ 代號重複，跳過：{stock_id}")
                continue

            stock_list.append(stock_id)
            stock_name_map[stock_id] = stock_name

        if invalid:
            send_discord_push(
                f"⚠️ **Config 分頁有 {len(invalid)} 筆代號格式錯誤，已跳過**\n"
                f"錯誤代號：{', '.join(invalid)}\n"
                f"格式說明：4～6 碼數字，可接一個英文字母（例：2330、00642U）"
            )

        if not stock_list:
            send_discord_push("⚠️ **Config 分頁所有代號均無效，改用程式內建預設清單**")
            return None, None

        write_log(f"從 Config 分頁載入 {len(stock_list)} 支股票：{stock_list}")
        return stock_list, stock_name_map
    except Exception as e:
        write_log(f"讀取 Config 分頁失敗：{e}，使用預設清單")
        return None, None


def try_yfinance(stock_id: str, suffix: str):
    """用指定後綴向 yfinance 取得價格，含 rate limit retry。"""
    tw_symbol = f"{stock_id}.{suffix}"
    for attempt in range(3):
        try:
            ticker = yf.Ticker(tw_symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                latest = hist.iloc[-1]
                price = float(latest["Close"])
                time_str = latest.name.strftime("%Y-%m-%d %H:%M:%S")
                write_log(f"{stock_id} yfinance 取得最新分鐘價（.{suffix}）：{price:.2f} @ {time_str}")
                return {"price": price, "time": time_str, "source": "today_yfinance", "is_latest": True, "finmind_success": False}

            hist_daily = ticker.history(period="5d")
            if not hist_daily.empty:
                latest = hist_daily.iloc[-1]
                price = float(latest["Close"])
                date_str = latest.name.strftime("%Y-%m-%d")
                write_log(f"{stock_id} yfinance 取得最近日收盤價（.{suffix}）：{price:.2f} ({date_str})")
                return {"price": price, "time": date_str, "source": "previous_yfinance", "is_latest": False, "finmind_success": False}

            return None  # 無資料，換後綴試試
        except Exception as e:
            if "Too Many Requests" in str(e) or "Rate limited" in str(e):
                if attempt < 2:
                    write_log(f"{stock_id} yfinance rate limit（.{suffix}），等 3 秒後重試（第 {attempt + 1} 次）")
                    time.sleep(3)
                else:
                    write_log(f"{stock_id} yfinance 備援失敗（.{suffix}）：{e}")
                    return None
            else:
                write_log(f"{stock_id} yfinance 異常（.{suffix}）：{e}")
                return None
    return None


def send_discord_push(message: str):
    if not DISCORD_WEBHOOK_URL:
        write_log("未設定 DISCORD_WEBHOOK_URL，無法推播 Discord。")
        return
    data = {"content": message}
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        if resp.status_code != 204:
            write_log(f"Discord 推播失敗，狀態碼：{resp.status_code}，回應：{resp.text}")
        else:
            write_log("Discord 推播成功")
    except Exception as e:
        write_log(f"Discord 推播失敗：{e}")


def write_log(msg):
    now_str = datetime.now().strftime('%Y年%m月%d日 %H時%M分%S秒')
    with open("error.log", "a", encoding="utf-8") as f:
        f.write(f"{now_str} {msg}\n")
    print(f"{now_str} {msg}")


# ======================== 交易日判斷 ========================
def is_trading_day(dl: DataLoader, check_date: str, is_after_close: bool) -> bool:
    """
    判斷指定日期是否為台股交易日
    - 盤後：優先檢查當天是否有日K資料
    - 盤中：檢查昨天是否有交易資料（用來推估今天是否可能開盤）
    """
    symbol_for_check = "2330"  # 使用台積電作為代表股票

    try:
        if is_after_close:
            # 盤後：檢查今天是否有日K資料
            df = dl.taiwan_stock_daily(symbol_for_check, start_date=check_date, end_date=check_date)
            if not df.empty:
                write_log(f"盤後檢查：{check_date} 有日K資料，視為交易日")
                return True
            else:
                write_log(f"盤後檢查：{check_date} 無日K資料，視為非交易日")
                return False
        else:
            # 盤中：查最近 7 天內是否有交易資料（避免週一查到週日誤判休市）
            start = (datetime.strptime(check_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
            yesterday = (datetime.strptime(check_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            df = dl.taiwan_stock_daily(symbol_for_check, start_date=start, end_date=yesterday)
            if not df.empty:
                write_log(f"盤中檢查：最近 7 天內有交易資料，今天很可能為交易日")
                return True
            else:
                write_log(f"盤中檢查：最近 7 天內無交易資料，今天很可能休市")
                return False
    except Exception as e:
        write_log(f"交易日檢查 FinMind 失敗：{e}，改用 yfinance 確認")
        try:
            ticker = yf.Ticker("2330.TW")
            hist = ticker.history(period="2d")
            if not hist.empty:
                write_log("yfinance 確認有資料，視為交易日")
                return True
        except Exception as e2:
            write_log(f"yfinance 也失敗：{e2}")
        write_log("無法確認交易日，預設為交易日（避免漏跑）")
        return True


# ======================== 價格取得函式 ========================
def get_latest_available_price(dl, stock_id: str):
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).strftime("%Y-%m-%d")
    try:
        df = dl.get_data(dataset="TaiwanStockPrice", data_id=stock_id, start_date=today)
        if df is not None and not df.empty and 'close' in df.columns:
            latest = df.iloc[-1]
            time_str = latest["date"]
            if "Time" in df.columns and pd.notna(latest.get("Time", None)):
                time_str = f"{latest['date']} {latest['Time']}"
            price = float(latest["close"])
            write_log(f"{stock_id} 取得當天最新分鐘價（FinMind）：{price:.2f} @ {time_str}")
            return {
                "price": price,
                "time": time_str,
                "source": "today_tick_finmind",
                "is_latest": True,
                "finmind_success": True
            }
    except Exception as e:
        write_log(f"{stock_id} FinMind 當天分鐘價失敗：{e}")

    try:
        df_day = dl.taiwan_stock_daily(stock_id, start_date=today, end_date=today)
        if not df_day.empty:
            price = float(df_day.iloc[0]["close"])
            write_log(f"{stock_id} 取得當天日收盤價（FinMind）：{price:.2f}")
            return {
                "price": price,
                "time": f"{today} 收盤",
                "source": "today_daily_finmind",
                "is_latest": True,
                "finmind_success": True
            }
    except Exception as e:
        write_log(f"{stock_id} FinMind 當天日收盤價失敗：{e}")

    write_log(f"{stock_id} FinMind 今天完全無資料 → 改用 yfinance 備援（自動偵測 .TW / .TWO）")
    for suffix in ["TW", "TWO"]:
        result = try_yfinance(stock_id, suffix)
        if result:
            return result

    write_log(f"{stock_id} FinMind 與 yfinance 都無法取得任何價格")
    return None


def get_today_close(dl, stock_id: str, date_str: str) -> Optional[float]:
    try:
        df = dl.taiwan_stock_daily(stock_id, start_date=date_str, end_date=date_str)
        if not df.empty:
            return float(df.iloc[0]["close"])
        return None
    except Exception as e:
        write_log(f"{stock_id} 取得 {date_str} 收盤價失敗：{e}")
        return None


def get_prev_close(dl, stock_id: str, before_date: str) -> Optional[float]:
    """取得 before_date 之前最近一個交易日的收盤價（最多往回找 7 天，解決週一查到週日的問題）"""
    try:
        start = (datetime.strptime(before_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        yesterday = (datetime.strptime(before_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(stock_id, start_date=start, end_date=yesterday)
        if not df.empty:
            return float(df.iloc[-1]["close"])
        return None
    except Exception as e:
        write_log(f"{stock_id} 取得前一交易日收盤價失敗：{e}")
        return None


def get_stock_data(dl, stock_id: str) -> Optional[Dict]:
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    is_after_close = now.hour > 13 or (now.hour == 13 and now.minute >= 30)

    instant = get_latest_available_price(dl, stock_id)
    if not instant:
        return None

    yesterday_close = get_prev_close(dl, stock_id, today)
    if yesterday_close is None:
        yesterday_close = instant["price"]

    result = {
        "stock_id": stock_id,
        "latest_price": instant["price"],
        "latest_time": instant["time"],
        "yesterday_close": yesterday_close,
        "date": today,
        "is_after_close": is_after_close,
        "source": instant["source"],
        "is_latest": instant["is_latest"],
        "finmind_success": instant.get("finmind_success", False)
    }

    if is_after_close:
        close_price = get_today_close(dl, stock_id, today)
        if close_price:
            result["close_price"] = close_price
        else:
            result["close_price"] = instant["price"]
        result["close_time"] = instant["time"]

    return result


def calculate_ma(prices, window):
    if len(prices) < window:
        return None
    return pd.Series(prices).rolling(window).mean().iloc[-1]


# ======================== Google Sheets ========================
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


# ======================== 盤中建議 ========================
def get_intraday_advice(latest, ma5, ma20, pct):
    if not (ma5 and ma20):
        return "均線資料不夠，先等等看比較好"

    diff_ma5 = (latest - ma5) / ma5 * 100 if ma5 else 0

    if latest > ma5 and latest > ma20:
        if diff_ma5 <= 2.8 and 3.0 <= pct <= 6.0:
            return "剛突破均線 + 今天力道很強，建議可以全部買進（但設好停損點）"
        elif diff_ma5 > 7.5 or (diff_ma5 > 6.0 and pct > 4.5):
            return "現在明顯過熱 + 漲幅很大，建議全部賣出鎖利，或至少先賣 70%~100%"
        elif pct > 5.0:
            return "今天漲很多，建議先賣 50%~80% 鎖住部分利潤，剩下的看明天"
        elif diff_ma5 > 4.5:
            return "股價已經漲不少，現在偏貴，建議先觀望，或最多用 10%~20% 的資金試試看"
        elif 1.5 <= pct < 3.5:
            return "今天有往上力道，建議先用 25%~45% 的資金分批買進"
        elif abs(pct) < 1.2:
            if pct > 0:
                return "小漲站上均線，建議先用 10%~25% 的資金試試看"
            else:
                return "站上均線但今天沒力道，建議先觀望，不要急著買"
        else:
            return "漲太快了，建議先不要追，最多用 15%~30% 的資金小量進場"

    elif latest < ma5 and latest < ma20:
        if pct < -5.0:
            return "今天跌很多 + 跌破均線，建議全部賣出止損，或至少先賣 70%~100%"
        elif pct < -2.5:
            return "跌破均線 + 跌幅明顯，建議先賣 40%~70% 降低風險"
        else:
            return "股價在均線下面，建議暫時不要買，等反彈再看"

    elif abs(pct) > 7.0:
        if pct > 7.0:
            return "今天漲超兇，建議先賣 60%~90% 鎖住大部分利潤"
        else:
            return "今天跌超兇，建議先賣 60%~90% 避險"

    else:
        return "現在情況不明，先觀望比較安全，等明天再說"


def get_after_close_summary(latest, ma5, ma20, change):
    if ma5 and latest > ma5 and ma20 and latest > ma20:
        return "建議明天可以買進，今天收盤價比平均價高"
    elif ma5 and latest < ma5 and ma20 and latest < ma20:
        return "建議明天不要買，今天收盤價比平均價低"
    elif abs(change) < 1:
        return "今天沒什麼變化，明天再觀察"
    else:
        return "今天價格有變動，明天再看情況決定要不要買"


# ======================== 主程式 ========================
def main():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    now_str = now.strftime("%Y年%m月%d日 %H時%M分%S秒")
    today_date = now.strftime("%Y-%m-%d")
    hour = now.hour
    minute = now.minute

    write_log(f"🕐 台灣時間：{now_str}")

    # 台灣時間 09:30 前為盤前，略過本次執行（09:00 整點剛開盤尚無盤中資料）
    if hour < 9 or (hour == 9 and minute < 30):
        write_log("盤前時段（09:30 前），略過本次執行")
        return

    service = get_sheets_service()
    if not service:
        write_log("無法連線 Google Sheets，結束執行")
        return

    dl = DataLoader()
    try:
        dl.login_by_token(FINMIND_TOKEN)
    except Exception as e:
        write_log(f"FinMind 登入失敗：{e}")
        return

    # ==================== 交易日檢查 ====================
    is_after_close = hour > 13 or (hour == 13 and minute >= 30)

    if not is_trading_day(dl, today_date, is_after_close):
        write_log(f"今天 {today_date} 判斷為非交易日，結束本次執行")
        return

    write_log("通過交易日檢查，開始處理股票資料...")

    # ──────────────── 從 Config 分頁讀取股票清單 ────────────────
    sheets_stock_list, sheets_stock_name_map = load_stock_list_from_sheets(service)
    active_stock_list = sheets_stock_list if sheets_stock_list else STOCK_LIST
    active_stock_name_map = sheets_stock_name_map if sheets_stock_name_map else STOCK_NAME_MAP

    # ──────────────── 使用 Google Sheets 記錄當天推播批次計數 ────────────────
    count_range = f"{SHEET_NAME}!J1:K1"  # J1: 日期, K1: 計數

    current_count = 1
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=count_range
        ).execute()
        values = result.get('values', [])
        if values and len(values) > 0 and len(values[0]) >= 2:
            sheet_date = str(values[0][0]).strip() if values[0][0] else ""
            sheet_count_str = str(values[0][1]).strip() if len(values[0]) > 1 else ""
            if sheet_date == today_date and sheet_count_str.isdigit():
                current_count = int(sheet_count_str) + 1
            else:
                write_log(f"Sheets 日期不符或無效：{sheet_date}，本次從 1 開始")
    except Exception as e:
        write_log(f"讀取 Sheets 計數失敗：{e}，本次視為第 1 次")

    # ──────────────── 推播批次標題 ────────────────
    title_text = "盤中更新"
    if hour >= 14:
        title_text = "盤後更新"
    elif hour == 13 and 31 <= minute < 59:
        title_text = "昨日收盤更新"

    batch_title = [
        "════════════════════════════════════════════════════════════",
        f"📢 今日第 {current_count} 次 {title_text}　{now_str}",
        "════════════════════════════════════════════════════════════",
        ""
    ]
    send_discord_push("\n".join(batch_title))
    time.sleep(1.0)  # 縮短為 1 秒，避免卡太久

    # ==================== 原有推播時間判斷 ====================
    is_yesterday_push = (hour == 13 and 31 <= minute < 59)
    is_today_push = (hour >= 14)

    success = True  # 用來判斷是否完整執行所有股票
    holiday_skipped = 0  # 記錄因今日無即時資料（國定假日）而跳過的股票數

    for stock_id in active_stock_list:
        stock_name = active_stock_name_map.get(stock_id, stock_id)
        stock = get_stock_data(dl, stock_id)
        if not stock:
            write_log(f"{stock_id} 無法取得資料，跳過")
            success = False
            send_discord_push(
                f"⚠️ **{stock_id} {stock_name}** 無法取得資料，本次已跳過\n"
                f"可能原因：代號錯誤 / 已下市 / 暫時性 API 問題"
            )
            continue

        # 取得近 90 天收盤價計算均線（90天≈63交易日，足以計算MA60）
        try:
            df = dl.taiwan_stock_daily(
                stock_id,
                start_date=(now - timedelta(days=90)).strftime("%Y-%m-%d"),
                end_date=now.strftime("%Y-%m-%d")
            )
            closes = df["close"].tolist() if not df.empty else []
        except Exception as e:
            write_log(f"{stock_id} 取得均線歷史資料失敗：{e}，均線以無資料顯示")
            closes = []

        ma5 = calculate_ma(closes, 5)
        ma20 = calculate_ma(closes, 20)
        ma60 = calculate_ma(closes, 60)

        ma5_str = f"{ma5:.2f}" if ma5 is not None else "無資料"
        ma20_str = f"{ma20:.2f}" if ma20 is not None else "無資料"
        ma60_str = f"{ma60:.2f}" if ma60 is not None else "無資料"

        latest = stock["latest_price"]
        yesterday_close = stock["yesterday_close"]
        change = latest - yesterday_close
        pct = change / yesterday_close * 100 if yesterday_close != 0 else 0

        # 來源註記
        if stock.get("finmind_success", False):
            if stock["source"] == "today_tick_finmind":
                source_note = f"（{stock['latest_time']}）"
            elif stock["source"] == "today_daily_finmind":
                source_note = f"（{stock['latest_time']} 當天收盤）"
            else:
                source_note = f"（{stock['latest_time']}）"
        else:
            if stock["source"] == "today_yfinance":
                source_note = f"（{stock['latest_time']}）（yfinance 備援）"
            else:
                source_note = f"（{stock['latest_time']} 收盤）（yfinance 備援）"

        footnote = "※ 資料來源：FinMind（yfinance 為備援來源）"

        # 共用明顯分隔標頭（方式1）
        header = [
            "═══════════════════════════════════════════════",
            f"🆕 新推播 {now_str} 🆕",
            "═══════════════════════════════════════════════",
        ]

        if is_yesterday_push:
            msg = header + [
                f"---",
                f"【{stock_id} {stock_name} 昨日收盤價 {now.strftime('%Y年%m月%d日')}】",
                f"時間：{now_str}",
                "━━━━━━━━━━━━━━",
                f"昨收：{yesterday_close:.2f} 元",
                f"5日均線：{ma5_str}",
                f"20日均線：{ma20_str}",
                f"60日均線：{ma60_str}",
                f"建議：{get_intraday_advice(yesterday_close, ma5, ma20, 0)}",
                "※ 資料來源：FinMind"
            ]
            send_discord_push("\n".join(msg))
            write_log(f"{stock_id} 推播昨日收盤價完成")
            time.sleep(1.0)
            continue

        if is_today_push and stock["is_after_close"]:
            close_price_for_sheet = get_today_close(dl, stock_id, stock["date"])
            if close_price_for_sheet is None:
                write_log(f"{stock_id} 盤後寫入：FinMind 當天日K尚未有資料，跳過寫入")
                close_price = stock["latest_price"]
                close_note = f"{stock['latest_time']} （當前最新價）"
            else:
                close_price = close_price_for_sheet
                close_note = f"{stock['latest_time']} （日K正式收盤）"

            msg = header + [
                f"---",
                f"【{stock_id} {stock_name} 價格監控 {now.strftime('%Y年%m月%d日')}】",
                f"時間：{now_str}",
                "━━━━━━━━━━━━━━",
                f"最新價：{latest:.2f} 元{source_note}",
                f"昨收：{yesterday_close:.2f} 元",
                f"漲跌：{change:+.2f}（{pct:+.2f}%）",
                f"5日均線：{ma5_str}",
                f"20日均線：{ma20_str}",
                f"60日均線：{ma60_str}",
                f"今日收盤：{close_price:.2f} 元{close_note}",
                f"行情摘要：{get_after_close_summary(latest, ma5, ma20, change)}",
                footnote
            ]

            if close_price_for_sheet is not None:
                save_to_sheets(
                    service, stock_id, stock_name, stock["date"],
                    close_price_for_sheet, ma5, ma20, ma60, now_str
                )

            send_discord_push("\n".join(msg))
            write_log(f"{stock_id} 推播盤後資訊完成")
            time.sleep(1.0)
            continue

        # 盤中推播 — 若今日無即時資料（國定假日），略過避免推出舊收盤
        if not stock["is_latest"]:
            write_log(f"{stock_id} 今日無即時資料（可能為國定假日），略過盤中推播")
            holiday_skipped += 1
            success = False
            continue

        msg = header + [
            f"---",
            f"【{stock_id} {stock_name} 盤中監控 {now.strftime('%Y年%m月%d日')}】",
            f"時間：{now_str}",
            "━━━━━━━━━━━━━━",
            f"最新價：{latest:.2f} 元{source_note}",
            f"昨收：{yesterday_close:.2f} 元",
            f"漲跌：{change:+.2f}（{pct:+.2f}%）",
            f"5日均線：{ma5_str}",
            f"20日均線：{ma20_str}",
            f"60日均線：{ma60_str}",
            f"建議：{get_intraday_advice(latest, ma5, ma20, pct)}",
            footnote
        ]

        send_discord_push("\n".join(msg))
        write_log(f"{stock_id} 盤中推播完成")
        time.sleep(1.0)  # 個股間隔，避免太密集

    # ──────────────── 國定假日：所有股票盤中均無即時資料 ────────────────
    if not is_yesterday_push and not is_today_push and holiday_skipped == len(active_stock_list):
        send_discord_push(
            "📢 今日所有股票均無即時交易資料（可能為國定假日），本次略過盤中推播"
        )

    # ──────────────── 只有完整執行才更新計數到 Sheets ────────────────
    if success:
        try:
            update_values = [[today_date, current_count]]
            service.spreadsheets().values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=count_range,
                valueInputOption="USER_ENTERED",
                body={"values": update_values}
            ).execute()
            write_log(f"本次推播完成，更新 Sheets 計數：{today_date} 第 {current_count} 次")
        except Exception as e:
            write_log(f"更新 Sheets 計數失敗：{e}")
    else:
        write_log(f"本次推播未完整執行 {len(active_stock_list)} 支股票，不更新計數")

    apply_sheet_formatting(service)


if __name__ == "__main__":
    main()