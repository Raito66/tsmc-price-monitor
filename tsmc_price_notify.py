# 台積電價格監控 - 使用 Google Sheets 永久儲存
# 資料來源：改用 yfinance (更穩定，不受證交所 API 限制)
# 策略：多均線分析 + Google Sheets 雲端儲存 + 進階年度分析

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import yfinance as yf
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================== 環境變數 ========================

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

if not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN 未設定")
if not USER_ID:
    raise RuntimeError("LINE_USER_ID 未設定")
if not GOOGLE_SHEETS_CREDENTIALS:
    raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS 未設定")
if not GOOGLE_SHEET_ID:
    raise RuntimeError("GOOGLE_SHEET_ID 未設定")

# ======================== 參數設定 ========================

TSMC_TICKER = "2330.TW"
HISTORY_DAYS = 365          # 保留一年資料
SHEET_NAME = "Sheet1"       # Google Sheets 工作表名稱

# ==========================================================

def get_sheets_service():
    """建立 Google Sheets 服務"""
    try:
        creds_json = GOOGLE_SHEETS_CREDENTIALS

        try:
            credentials_info = json.loads(creds_json)
        except json.JSONDecodeError:
            print("⚠️ JSON 解析失敗，嘗試處理轉義字符...")
            creds_json = creds_json.encode().decode('unicode_escape')
            credentials_info = json.loads(creds_json)

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=credentials)
        print("✅ Google Sheets 連線成功")
        return service
    except Exception as e:
        print(f"⚠️ Google Sheets 連線失敗：{e}")
        return None


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

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ LINE 推播失敗：{r.status_code} - {r.text}")
    except Exception as e:
        print(f"⚠️ LINE 推播錯誤：{e}")


def get_tsmc_data() -> Optional[Dict]:
    """
    使用 yfinance 取得台積電最新價格與昨收價
    回傳格式與原版相容
    """
    try:
        ticker = yf.Ticker(TSMC_TICKER)

        # 取得最新即時報價資訊
        info = ticker.info

        # 嘗試取得各種可能存在的即時價格欄位
        current_price = None
        for key in ['regularMarketPrice', 'currentPrice', 'lastPrice', 'previousClose']:
            if key in info and info[key] is not None:
                current_price = float(info[key])
                break

        # 昨收價
        previous_close = info.get('regularMarketPreviousClose') or info.get('previousClose')

        if current_price is None or previous_close is None:
            print("⚠️ yfinance 未取得完整價格資訊")
            return None

        # 取得今日日期 (台灣時間)
        taipei_tz = timezone(timedelta(hours=8))
        today_dt = datetime.now(timezone.utc).astimezone(taipei_tz)
        today_str = today_dt.strftime("%Y-%m-%d")

        return {
            "price": current_price,
            "yesterday_close": float(previous_close),
            "date": today_str
        }

    except Exception as e:
        print(f"⚠️ yfinance 取得資料失敗：{e}")
        return None


# ==================== Google Sheets 操作 ====================

def load_history_from_sheets(service) -> List[Dict]:
    """從 Google Sheets 載入歷史資料"""
    if not service:
        return []

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{SHEET_NAME}!A2:F'
        ).execute()

        values = result.get('values', [])

        history = []
        for row in values:
            if len(row) >= 2:
                history.append({
                    'date': row[0],
                    'price': float(row[1]),
                    'timestamp': row[5] if len(row) > 5 else row[0]
                })

        print(f"✅ 從 Google Sheets 載入 {len(history)} 筆資料")
        return history

    except Exception as e:
        print(f"⚠️ 讀取 Sheets 失敗：{e}")
        return []


def save_to_sheets(service, date: str, price: float, ma5: Optional[float],
                   ma20: Optional[float], ma60: Optional[float], timestamp: str) -> bool:
    """儲存資料到 Google Sheets"""
    if not service:
        return False

    try:
        values = [[
            date,
            price,
            f"{ma5:.2f}" if ma5 else "",
            f"{ma20:.2f}" if ma20 else "",
            f"{ma60:.2f}" if ma60 else "",
            timestamp
        ]]

        body = {'values': values}
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{SHEET_NAME}!A2',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()

        print(f"✅ 已寫入 Google Sheets：{date} - {price:.2f}")
        return True

    except Exception as e:
        print(f"⚠️ 寫入 Sheets 失敗：{e}")
        return False


def cleanup_old_data(service, keep_days: int = 365):
    """清理超過指定天數的舊資料"""
    if not service:
        return

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{SHEET_NAME}!A2:F'
        ).execute()

        values = result.get('values', [])

        if len(values) <= keep_days:
            return

        rows_to_delete = len(values) - keep_days

        request = {
            'requests': [{
                'deleteDimension': {
                    'range': {
                        'sheetId': 0,
                        'dimension': 'ROWS',
                        'startIndex': 1,
                        'endIndex': 1 + rows_to_delete
                    }
                }
            }]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_SHEET_ID,
            body=request
        ).execute()

        print(f"✅ 已清理 {rows_to_delete} 筆舊資料")

    except Exception as e:
        print(f"⚠️ 清理舊資料失敗：{e}")


# ==================== 技術分析 ====================

def calculate_ma(history: List[Dict], days: int) -> Optional[float]:
    """計算 N 日均線"""
    if len(history) < days:
        return None
    recent_prices = [h['price'] for h in history[-days:]]
    return sum(recent_prices) / len(recent_prices)


def analyze_trend(history: List[Dict], days: int = 3) -> tuple:
    """分析近 N 日趨勢"""
    if len(history) < days:
        return "資料不足", "📊"

    prices = [h['price'] for h in history[-days:]]

    if days == 3:
        if prices[0] > prices[1] > prices[2]:
            return "連續下跌", "📉"
        elif prices[0] < prices[1] < prices[2]:
            return "連續上漲", "📈"
        elif prices[0] > prices[1] and prices[1] < prices[2]:
            return "止跌反彈", "💡"
        elif prices[0] < prices[1] and prices[1] > prices[2]:
            return "上漲回落", "⚠️"
        else:
            return "震盪整理", "📊"

    return "整理中", "📊"


# ==================== 進階分析功能 ====================

def get_yearly_stats(history: List[Dict]) -> Dict:
    """計算年度統計資料"""
    if len(history) < 30:
        return {}

    prices = [h['price'] for h in history]

    stats = {
        'max_price': max(prices),
        'min_price': min(prices),
        'avg_price': sum(prices) / len(prices),
        'current_price': prices[-1]
    }

    for h in history:
        if h['price'] == stats['max_price']:
            stats['max_date'] = h['date']
        if h['price'] == stats['min_price']:
            stats['min_date'] = h['date']

    stats['from_high_pct'] = ((stats['current_price'] - stats['max_price']) / stats['max_price']) * 100
    stats['from_low_pct'] = ((stats['current_price'] - stats['min_price']) / stats['min_price']) * 100

    return stats


def get_long_term_trend(history: List[Dict]) -> str:
    """判斷長期趨勢（30/60/90天）"""
    if len(history) < 90:
        return ""

    ma30 = calculate_ma(history, 30)
    ma60 = calculate_ma(history, 60)
    ma90 = calculate_ma(history, 90)

    if not all([ma30, ma60, ma90]):
        return ""

    current = history[-1]['price']

    if current > ma30 > ma60 > ma90:
        return "📈 長期多頭（30>60>90）"
    elif current < ma30 < ma60 < ma90:
        return "📉 長期空頭（30<60>90）"
    elif current > ma30 and ma30 > ma60:
        return "💡 轉多訊號（突破中期均線）"
    elif current < ma30 and ma30 < ma60:
        return "⚠️ 轉弱訊號（跌破中期均線）"
    else:
        return "📊 區間整理"


def get_smart_suggestion(price: float, history: List[Dict], ma5: Optional[float],
                        ma20: Optional[float], ma60: Optional[float]) -> List[str]:
    """智能買賣建議（加強版）"""
    suggestions = []

    if len(history) < 3:
        suggestions.append("📊 資料累積中，暫無建議")
        return suggestions

    trend_desc, trend_icon = analyze_trend(history, days=3)

    yearly_stats = get_yearly_stats(history)
    if yearly_stats:
        if yearly_stats['from_low_pct'] < 5:
            suggestions.append("🎯 接近年度低點，關注買點")
            suggestions.append(f"   年度低點：{yearly_stats['min_price']:.2f}（{yearly_stats.get('min_date', 'N/A')}）")

        if yearly_stats['from_high_pct'] > -5:
            suggestions.append("⚠️ 接近年度高點，注意風險")
            suggestions.append(f"   年度高點：{yearly_stats['max_price']:.2f}（{yearly_stats.get('max_date', 'N/A')}）")

    long_term = get_long_term_trend(history)
    if long_term:
        suggestions.append(long_term)

    # 以下為原有邏輯（保持不變）
    if (ma5 and ma20 and ma60 and
        price > ma5 > ma20 > ma60 and
        trend_desc == "止跌反彈"):
        suggestions.append("🔥 多頭排列且止跌反彈")
        suggestions.append("💡 強烈建議：可積極買入")
        return suggestions

    if ma20 and price > ma20 and len(history) >= 2:
        prev_price = history[-2]['price']
        if prev_price <= ma20:
            suggestions.append("💡 突破20日均線（月線）")
            suggestions.append("✅ 建議：可考慮分批買入")
            return suggestions

    if trend_desc == "止跌反彈" and ma5 and price > ma5:
        suggestions.append(f"{trend_icon} {trend_desc}且站穩5日線")
        suggestions.append("💡 建議：可考慮分批買入")
        return suggestions

    if trend_desc == "連續下跌":
        suggestions.append(f"{trend_icon} {trend_desc}")
        if ma20 and price < ma20:
            suggestions.append("⚠️ 建議：趨勢偏弱，繼續觀望")
            suggestions.append("👀 等待：止跌並突破月線再考慮")
        else:
            suggestions.append("👀 建議：等待止跌訊號")
        return suggestions

    if ma5 and ma20 and ma60 and price < ma5 < ma20 < ma60:
        suggestions.append("📉 空頭排列（價格 < 短期 < 中期 < 長期）")
        suggestions.append("⚠️ 建議：趨勢偏弱，不宜進場")
        return suggestions

    if ma20 and price < ma20 and len(history) >= 2:
        prev_price = history[-2]['price']
        if prev_price >= ma20:
            suggestions.append("⚠️ 跌破20日均線（月線）")
            suggestions.append("🚫 建議：考慮減碼或停損")
            return suggestions

    if trend_desc == "上漲回落" and ma5 and price < ma5:
        suggestions.append(f"{trend_icon} {trend_desc}且跌破5日線")
        suggestions.append("⚠️ 建議：可考慮減碼")
        return suggestions

    if ma5 and ma20 and price > ma5 > ma20:
        suggestions.append("📈 短中期多頭格局")
        suggestions.append("✅ 建議：可持續持有")
        return suggestions

    if trend_desc == "連續上漲":
        suggestions.append(f"{trend_icon} {trend_desc}")
        if ma5 and price > ma5 * 1.05:
            suggestions.append("⚠️ 提醒：漲幅較大，注意回檔風險")
        else:
            suggestions.append("✅ 建議：可持續持有")
        return suggestions

    suggestions.append(f"{trend_icon} {trend_desc}")
    suggestions.append("📊 建議：區間震盪，等待方向明朗")

    return suggestions


# ==================== 主程式 ====================

def main():
    taipei_tz = timezone(timedelta(hours=8))
    now_dt = datetime.now(timezone.utc).astimezone(taipei_tz)
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today = now_dt.strftime("%Y-%m-%d")

    print(f"🕐 台灣時間：{now}")

    service = get_sheets_service()
    if not service:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ Google Sheets 連線失敗")
        print("⚠️ Google Sheets 連線失敗")
        return

    stock_data = get_tsmc_data()
    if stock_data is None:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ 無法取得最新股價資料（可能市場未開盤）")
        print("⚠️ 無法取得股價資料")
        return

    price = stock_data["price"]
    yesterday_close = stock_data["yesterday_close"]
    change_percent = ((price - yesterday_close) / yesterday_close) * 100
    change_amount = price - yesterday_close

    history = load_history_from_sheets(service)

    # 只在有新價格 且 是新的一天 時才新增資料
    last_date = history[-1].get('date') if history else None

    if last_date != today:
        history.append({'date': today, 'price': price, 'timestamp': now})
        ma5 = calculate_ma(history, 5)
        ma20 = calculate_ma(history, 20)
        ma60 = calculate_ma(history, 60)

        save_to_sheets(service, today, price, ma5, ma20, ma60, now)
        cleanup_old_data(service, HISTORY_DAYS)
    else:
        # 同一天，使用歷史最後一筆價格計算均線
        ma5 = calculate_ma(history, 5)
        ma20 = calculate_ma(history, 20)
        ma60 = calculate_ma(history, 60)

    suggestions = get_smart_suggestion(price, history, ma5, ma20, ma60)
    yearly_stats = get_yearly_stats(history)

    # ==================== 組合訊息 ====================

    msg_parts = []
    msg_parts.append("【台積電價格監控】")
    msg_parts.append(f"時間：{now}")
    msg_parts.append("━━━━━━━━━━━━━━")

    msg_parts.append(f"現價：{price:.2f} 元")
    msg_parts.append(f"昨收：{yesterday_close:.2f} 元")
    msg_parts.append(f"漲跌：{change_amount:+.2f} 元（{change_percent:+.2f}%）")

    if yearly_stats and len(history) >= 30:
        msg_parts.append("━━━━━━━━━━━━━━")
        msg_parts.append("📊 年度統計")
        msg_parts.append(f"最高：{yearly_stats['max_price']:.2f} 元（{yearly_stats.get('max_date', 'N/A')}）")
        msg_parts.append(f"最低：{yearly_stats['min_price']:.2f} 元（{yearly_stats.get('min_date', 'N/A')}）")
        msg_parts.append(f"均價：{yearly_stats['avg_price']:.2f} 元")

        if yearly_stats['from_high_pct'] < 0:
            msg_parts.append(f"距高點：{yearly_stats['from_high_pct']:.1f}%")
        if yearly_stats['from_low_pct'] > 0:
            msg_parts.append(f"距低點：+{yearly_stats['from_low_pct']:.1f}%")

    if ma5 or ma20 or ma60:
        msg_parts.append("━━━━━━━━━━━━━━")
        msg_parts.append("📈 技術分析")

        if ma5:
            icon = "✅" if price > ma5 else "⚠️"
            msg_parts.append(f"5日均線：{ma5:.2f} 元 {icon}")
        if ma20:
            icon = "✅" if price > ma20 else "⚠️"
            msg_parts.append(f"20日均線：{ma20:.2f} 元 {icon}")
        if ma60:
            icon = "✅" if price > ma60 else "⚠️"
            msg_parts.append(f"60日均線：{ma60:.2f} 元 {icon}")

    msg_parts.append("━━━━━━━━━━━━━━")
    msg_parts.extend(suggestions)

    msg_parts.append("━━━━━━━━━━━━━━")
    msg_parts.append(f"📝 歷史：{len(history)}/{HISTORY_DAYS} 天 (Google Sheets ☁️)")

    msg = "\n".join(msg_parts)
    send_line_push(msg)

    print("✅ 推播完成")
    print(f"   現價：{price:.2f}，昨收：{yesterday_close:.2f}，漲跌：{change_percent:+.2f}%")
    if ma5: print(f"   MA5：{ma5:.2f}")
    if ma20: print(f"   MA20：{ma20:.2f}")
    if ma60: print(f"   MA60：{ma60:.2f}")
    if yearly_stats:
        print(f"   年度高點：{yearly_stats.get('max_price', 0):.2f}，低點：{yearly_stats.get('min_price', 0):.2f}")


if __name__ == "__main__":
    main()