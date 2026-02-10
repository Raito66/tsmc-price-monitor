import os
from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
from FinMind.data import DataLoader
import requests
import yfinance as yf

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
STOCK_LIST = ["2330", "6770", "3481", "2337", "2344", "2409", "2367"]
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

# ======================== 價格取得函式 ========================
def get_latest_available_price(dl, stock_id: str):
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).strftime("%Y-%m-%d")
    tw_symbol = f"{stock_id}.TW"

    # 1. 當天分鐘級資料（FinMind）
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

    # 2. 當天日收盤價（FinMind）
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

    # 今天完全沒有資料 → 改用 yfinance 備援
    write_log(f"{stock_id} FinMind 今天完全無資料 → 改用 yfinance 備援")
    try:
        ticker = yf.Ticker(tw_symbol)

        # 嘗試抓今天的分鐘資料
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            latest = hist.iloc[-1]
            price = float(latest["Close"])
            time_str = latest.name.strftime("%Y-%m-%d %H:%M:%S")
            write_log(f"{stock_id} yfinance 取得最新分鐘價：{price:.2f} @ {time_str}")
            return {
                "price": price,
                "time": time_str,  # ← 改成純時間
                "source": "today_yfinance",
                "is_latest": True,
                "finmind_success": False
            }

        # 如果分鐘沒抓到，抓最近 5 天日收盤
        hist_daily = ticker.history(period="5d")
        if not hist_daily.empty:
            latest = hist_daily.iloc[-1]
            price = float(latest["Close"])
            date_str = latest.name.strftime("%Y-%m-%d")
            write_log(f"{stock_id} yfinance 取得最近日收盤價：{price:.2f} ({date_str})")
            return {
                "price": price,
                "time": date_str,  # ← 改成純日期
                "source": "previous_yfinance",
                "is_latest": False,
                "finmind_success": False
            }
    except Exception as e:
        write_log(f"{stock_id} yfinance 備援也失敗：{e}")

    write_log(f"{stock_id} FinMind 與 yfinance 都無法取得任何價格")
    return None

def get_today_close(dl, stock_id: str, date_str: str) -> Optional[float]:
    """取得指定日期的日收盤價（僅用 FinMind，用於寫入 Sheets）"""
    try:
        df = dl.taiwan_stock_daily(stock_id, start_date=date_str, end_date=date_str)
        if not df.empty:
            return float(df.iloc[0]["close"])
        return None
    except Exception as e:
        write_log(f"{stock_id} 取得 {date_str} 收盤價失敗：{e}")
        return None

def get_stock_data(dl, stock_id: str) -> Optional[Dict]:
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    is_after_close = now.hour > 13 or (now.hour == 13 and now.minute >= 30)

    instant = get_latest_available_price(dl, stock_id)
    if not instant:
        return None

    # 取得昨天收盤價，用來計算漲跌
    yesterday_close = get_today_close(dl, stock_id, (now - timedelta(days=1)).strftime("%Y-%m-%d"))
    if yesterday_close is None:
        yesterday_close = instant["price"]  # 避免除以零

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

    # 如果已經盤後，嘗試取得今天正式收盤價
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

# ======================== 主程式 ========================
def main():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    now_str = now.strftime("%Y年%m月%d日 %H時%M分%S秒")
    hour = now.hour
    minute = now.minute
    write_log(f"🕐 台灣時間：{now_str}")

    service = get_sheets_service()
    dl = DataLoader()
    dl.login_by_token(FINMIND_TOKEN)

    # 判斷是否可能為交易日
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    df_yest = dl.taiwan_stock_daily("2330", start_date=yesterday, end_date=yesterday)
    if df_yest.empty:
        write_log("昨天無交易資料，今天很可能休市，結束本次執行")
        return

    # 判斷執行時段
    is_yesterday_push = (hour == 13 and 31 <= minute < 59)
    is_today_push = (hour >= 14)

    for stock_id in STOCK_LIST:
        stock_name = STOCK_NAME_MAP.get(stock_id, stock_id)
        stock = get_stock_data(dl, stock_id)
        if not stock:
            write_log(f"{stock_id} 無法取得資料")
            continue

        # 取近 61 天日K 算均線（使用 FinMind）
        df = dl.taiwan_stock_daily(
            stock_id,
            start_date=(now - timedelta(days=61)).strftime("%Y-%m-%d"),
            end_date=now.strftime("%Y-%m-%d")
        )
        closes = df["close"].tolist() if not df.empty else []

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

        # 來源註解（強化顯示） ← 這裡統一處理備援標記
        if stock.get("finmind_success", False):
            if stock["source"] == "today_tick_finmind":
                source_note = f"（{stock['latest_time']}）"
            elif stock["source"] == "today_daily_finmind":
                source_note = f"（{stock['latest_time']} 當天收盤）"
            else:
                source_note = f"（{stock['latest_time']}）"
        else:
            # yfinance 備援的情況
            if stock["source"] == "today_yfinance":
                source_note = f"（{stock['latest_time']}）（yfinance 備援）"
            else:
                source_note = f"（{stock['latest_time']} 收盤）（yfinance 備援）"

        # 盤中推播建議
        def get_intraday_advice(latest, ma5, ma20, ma60, pct):
            if ma5 and ma20 and latest > ma5 and latest > ma20:
                if abs(pct) < 1:
                    return "建議現在可以全部買進"
                elif 1 <= pct < 3:
                    return "建議分批買進 30% 資金，剩下的等價格下跌再買"
                elif pct >= 3:
                    return "建議不要現在買，等價格下跌再買"
                else:
                    return "建議現在可以買進"
            elif ma5 and ma20 and latest < ma5 and latest < ma20:
                return "建議不要買，暫時不要動作"
            elif abs(pct) > 5:
                return "今天價格變化太大，建議不要買也不要賣"
            elif ma5 and latest > ma5:
                return "可以小量分批買進 10%~20% 資金"
            else:
                return "建議暫時不要動作，等明天再看"

        # 盤後摘要
        def get_after_close_summary(latest, ma5, ma20, ma60, change):
            if ma5 and latest > ma5 and ma20 and latest > ma20:
                return "建議明天可以買進，今天收盤價比平均價高"
            elif ma5 and latest < ma5 and ma20 and latest < ma20:
                return "建議明天不要買，今天收盤價比平均價低"
            elif abs(change) < 1:
                return "今天沒什麼變化，明天再觀察"
            else:
                return "今天價格有變動，明天再看情況決定要不要買"

        # 只在 13:31~13:59 推播昨日收盤價
        if is_yesterday_push:
            msg = [
                f"---",
                f"【{stock_id} {stock_name} 昨日收盤價 {now.strftime('%Y年%m月%d日')}】",
                f"時間：{now_str}",
                "━━━━━━━━━━━━━━",
                f"昨收：{yesterday_close:.2f} 元",
                f"5日均線：{ma5_str}",
                f"20日均線：{ma20_str}",
                f"60日均線：{ma60_str}",
                f"建議：{get_intraday_advice(yesterday_close, ma5, ma20, ma60, 0)}",
                "※ 資料來源：FinMind"
            ]
            send_discord_push("\n".join(msg))
            write_log(f"{stock_id} 推播昨日收盤價完成")
            continue

        # 盤後推播
        if is_today_push and stock["is_after_close"]:
            close_price_for_sheet = get_today_close(dl, stock_id, stock["date"])
            if close_price_for_sheet is None:
                write_log(f"{stock_id} 盤後寫入：FinMind 當天日K尚未有資料，跳過寫入")
                close_price = stock["latest_price"]
                close_note = f"{stock['latest_time']} （當前最新價）"
            else:
                close_price = close_price_for_sheet
                close_note = f"{stock['latest_time']} （日K正式收盤）"

            msg = [
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
                f"行情摘要：{get_after_close_summary(latest, ma5, ma20, ma60, change)}",
                "※ 資料來源：FinMind（若顯示 yfinance 為備援）"
            ]

            if close_price_for_sheet is not None:
                save_to_sheets(
                    service, stock_id, stock_name, stock["date"],
                    close_price_for_sheet, ma5, ma20, ma60, now_str
                )

            send_discord_push("\n".join(msg))
            write_log(f"{stock_id} 推播盤後資訊完成")
            continue

        # 盤中推播（其他時間）
        msg = [
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
            f"建議：{get_intraday_advice(latest, ma5, ma20, ma60, pct)}",
            "※ 資料來源：FinMind（若顯示 yfinance 為備援）"
        ]

        send_discord_push("\n".join(msg))
        write_log(f"{stock_id} 盤中推播完成")

if __name__ == "__main__":
    main()