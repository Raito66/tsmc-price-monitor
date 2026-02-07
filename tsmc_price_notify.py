# 台積電價格監控 - 使用 Google Sheets 永久儲存
# 策略：多均線分析 + Google Sheets 雲端儲存

import requests
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
import urllib3

# 關閉 SSL 警告訊息（因為證交所憑證問題）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

TSMC_SYMBOL = "2330"
API_URL = (
    f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    f"?ex_ch=tse_{TSMC_SYMBOL}.tw&json=1&delay=0"
)

# 歷史資料設定
HISTORY_DAYS = 60  # 保留 60 天資料
SHEET_NAME = "Sheet1"  # 工作表名稱

# ==========================================================

def get_sheets_service():
    """建立 Google Sheets 服務"""
    try:
        # 改進的 JSON 解析，處理換行符號
        creds_json = GOOGLE_SHEETS_CREDENTIALS
        
        # 嘗試直接解析
        try:
            credentials_info = json.loads(creds_json)
        except json.JSONDecodeError:
            # 如果失敗，嘗試處理轉義字符
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

def get_tsmc_data(max_retries=3) -> Optional[Dict]:
    """取得台積電股價資訊（現價 + 昨收）"""
    for attempt in range(max_retries):
        try:
            # 優先嘗試正常 SSL 驗證
            try:
                r = requests.get(API_URL, timeout=10, verify=True)
            except requests.exceptions.SSLError:
                # SSL 驗證失敗，使用無驗證模式
                if attempt == 0:
                    print("⚠️ SSL 驗證失敗，使用無驗證模式連線證交所")
                r = requests.get(API_URL, timeout=10, verify=False)
            
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
            print(f"⚠️ API 請求失敗（第 {attempt + 1}/{max_retries} 次）：{e}")
    return None

# ==================== Google Sheets 操作 ====================

def load_history_from_sheets(service) -> List[Dict]:
    """從 Google Sheets 載入歷史資料"""
    if not service:
        return []
    
    try:
        # 讀取所有資料（跳過標題列）
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{SHEET_NAME}!A2:F'
        ).execute()
        
        values = result.get('values', [])
        
        history = []
        for row in values:
            if len(row) >= 2:  # 至少要有日期和價格
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
        # 準備資料
        values = [[
            date,
            price,
            f"{ma5:.2f}" if ma5 else "",
            f"{ma20:.2f}" if ma20 else "",
            f"{ma60:.2f}" if ma60 else "",
            timestamp
        ]]
        
        # 寫入新的一列
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

def cleanup_old_data(service, keep_days: int = 60):
    """清理超過指定天數的舊資料"""
    if not service:
        return
    
    try:
        # 讀取所有資料
        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{SHEET_NAME}!A2:F'
        ).execute()
        
        values = result.get('values', [])
        
        if len(values) <= keep_days:
            return  # 資料還不夠多，不需要清理
        
        # 只保留最近的資料
        rows_to_delete = len(values) - keep_days
        
        # 刪除舊資料（從第2列開始刪除）
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

def get_smart_suggestion(price: float, history: List[Dict], ma5: Optional[float], 
                         ma20: Optional[float], ma60: Optional[float]) -> List[str]:
    """智能買賣建議"""
    suggestions = []
    
    if len(history) < 3:
        suggestions.append("📊 資料累積中，暫無建議")
        return suggestions
    
    trend_desc, trend_icon = analyze_trend(history, days=3)
    
    # 強烈買入：多頭排列 + 止跌反彈
    if (ma5 and ma20 and ma60 and 
        price > ma5 > ma20 > ma60 and 
        trend_desc == "止跌反彈"):
        suggestions.append("🔥 多頭排列且止跌反彈")
        suggestions.append("💡 強烈建議：可積極買入")
        return suggestions
    
    # 買入：突破20日線
    if ma20 and price > ma20 and len(history) >= 2:
        prev_price = history[-2]['price']
        if prev_price <= ma20:
            suggestions.append("💡 突破20日均線（月線）")
            suggestions.append("✅ 建議：可考慮分批買入")
            return suggestions
    
    # 買入：止跌反彈且站穩5日線
    if trend_desc == "止跌反彈" and ma5 and price > ma5:
        suggestions.append(f"{trend_icon} {trend_desc}且站穩5日線")
        suggestions.append("💡 建議：可考慮分批買入")
        return suggestions
    
    # 觀望：連續下跌
    if trend_desc == "連續下跌":
        suggestions.append(f"{trend_icon} {trend_desc}")
        if ma20 and price < ma20:
            suggestions.append("⚠️ 建議：趨勢偏弱，繼續觀望")
            suggestions.append("👀 等待：止跌並突破月線再考慮")
        else:
            suggestions.append("👀 建議：等待止跌訊號")
        return suggestions
    
    # 觀望：空頭排列
    if ma5 and ma20 and ma60 and price < ma5 < ma20 < ma60:
        suggestions.append("📉 空頭排列（價格 < 短期 < 中期 < 長期）")
        suggestions.append("⚠️ 建議：趨勢偏弱，不宜進場")
        return suggestions
    
    # 賣出：跌破20日線
    if ma20 and price < ma20 and len(history) >= 2:
        prev_price = history[-2]['price']
        if prev_price >= ma20:
            suggestions.append("⚠️ 跌破20日均線（月線）")
            suggestions.append("🚫 建議：考慮減碼或停損")
            return suggestions
    
    # 賣出：上漲回落
    if trend_desc == "上漲回落" and ma5 and price < ma5:
        suggestions.append(f"{trend_icon} {trend_desc}且跌破5日線")
        suggestions.append("⚠️ 建議：可考慮減碼")
        return suggestions
    
    # 持有：多頭排列
    if ma5 and ma20 and price > ma5 > ma20:
        suggestions.append("📈 短中期多頭格局")
        suggestions.append("✅ 建議：可持續持有")
        return suggestions
    
    # 持有：連續上漲
    if trend_desc == "連續上漲":
        suggestions.append(f"{trend_icon} {trend_desc}")
        if ma5 and price > ma5 * 1.05:
            suggestions.append("⚠️ 提醒：漲幅較大，注意回檔風險")
        else:
            suggestions.append("✅ 建議：可持續持有")
        return suggestions
    
    # 預設：震盪整理
    suggestions.append(f"{trend_icon} {trend_desc}")
    suggestions.append("📊 建議：區間震盪，等待方向明朗")
    
    return suggestions

# ==================== 主程式 ====================

def main():
    # 取得台灣時間（使用新的 timezone-aware 方式）
    taipei_tz = timezone(timedelta(hours=8))
    now_dt = datetime.now(timezone.utc).astimezone(taipei_tz)
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today = now_dt.strftime("%Y-%m-%d")
    
    print(f"🕐 台灣時間：{now}")
    
    # 連線 Google Sheets
    service = get_sheets_service()
    if not service:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ Google Sheets 連線失敗")
        print("⚠️ Google Sheets 連線失敗")
        return
    
    # 取得股價資料
    stock_data = get_tsmc_data()
    if stock_data is None:
        send_line_push(f"【台積電監控】\n{now}\n⚠️ 無法取得股價資料")
        print("⚠️ 無法取得股價")
        return
    
    price = stock_data["price"]
    yesterday_close = stock_data["yesterday_close"]
    change_percent = ((price - yesterday_close) / yesterday_close) * 100
    change_amount = price - yesterday_close
    
    # 載入歷史資料
    history = load_history_from_sheets(service)
    
    # 檢查是否為新的一天
    if not history or history[-1].get('date') != today:
        # 計算均線（用於儲存）
        history.append({'date': today, 'price': price, 'timestamp': now})
        ma5 = calculate_ma(history, 5)
        ma20 = calculate_ma(history, 20)
        ma60 = calculate_ma(history, 60)
        
        # 儲存到 Sheets
        save_to_sheets(service, today, price, ma5, ma20, ma60, now)
        
        # 清理舊資料
        cleanup_old_data(service, HISTORY_DAYS)
    else:
        # 使用現有資料計算均線
        ma5 = calculate_ma(history, 5)
        ma20 = calculate_ma(history, 20)
        ma60 = calculate_ma(history, 60)
    
    # 智能建議
    suggestions = get_smart_suggestion(price, history, ma5, ma20, ma60)
    
    # ==================== 組合訊息 ====================
    
    msg_parts = []
    
    msg_parts.append("【台積電價格監控】")
    msg_parts.append(f"時間：{now}")
    msg_parts.append("━━━━━━━━━━━━━━")
    
    msg_parts.append(f"現價：{price:.2f} 元")
    msg_parts.append(f"昨收：{yesterday_close:.2f} 元")
    msg_parts.append(f"漲跌：{change_amount:+.2f} 元（{change_percent:+.2f}%）")
    
    if ma5 or ma20 or ma60:
        msg_parts.append("━━━━━━━━━━━━━━")
        msg_parts.append("📊 技術分析")
        
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
    if ma5:
        print(f"   MA5：{ma5:.2f}")
    if ma20:
        print(f"   MA20：{ma20:.2f}")
    if ma60:
        print(f"   MA60：{ma60:.2f}")

if __name__ == "__main__":
    main()