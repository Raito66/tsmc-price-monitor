# 台積電價格監控 - 使用 LINE Messaging API 推播通知
# 策略：3日趨勢判斷 + 5日均價參考（右側交易）

import requests
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# ======================== 環境變數 ========================

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

if not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN 未設定")
if not USER_ID:
    raise RuntimeError("LINE_USER_ID 未設定")

# ======================== 參數設定 ========================

TSMC_SYMBOL = "2330"
API_URL = (
    f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    f"?ex_ch=tse_{TSMC_SYMBOL}.tw&json=1&delay=0"
)

# 歷史資料儲存路徑
HISTORY_FILE = Path("/tmp/tsmc_history.json")

# 需要保留的歷史天數
HISTORY_DAYS = 5

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

def get_tsmc_data(max_retries=3):
    """取得台積電股價資訊（現價 + 昨收）"""
    for _ in range(max_retries):
        try:
            r = requests.get(API_URL, timeout=10)
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
            print(f"⚠️ API 請求失敗：{e}")
    return None

def load_history():
    """載入歷史價格資料"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 載入歷史資料失敗：{e}")
    return []

def save_history(history):
    """儲存歷史價格資料（只保留最近 N 天）"""
    try:
        # 只保留最近的資料
        history = history[-HISTORY_DAYS:]
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 儲存歷史資料失敗：{e}")

def calculate_avg_price(history, days=5):
    """計算 N 日均價"""
    if len(history) < days:
        return None
    recent_prices = [h['price'] for h in history[-days:]]
    return sum(recent_prices) / len(recent_prices)

def analyze_trend(history):
    """分析近 3 日趨勢"""
    if len(history) < 3:
        return "資料不足", "📊"
    
    prices = [h['price'] for h in history[-3:]]
    
    # 判斷趨勢
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

def get_smart_alert(price, yesterday_close, history, avg_5day):
    """智能分級提醒（結合趨勢 + 均線）"""
    change_percent = ((price - yesterday_close) / yesterday_close) * 100
    
    # 趨勢分析
    trend_desc, trend_icon = analyze_trend(history)
    
    # 均線位置
    if avg_5day:
        ma_position = "上方" if price > avg_5day else "下方"
        ma_diff_percent = ((price - avg_5day) / avg_5day) * 100
    else:
        ma_position = "未知"
        ma_diff_percent = 0
    
    # 綜合判斷
    alert_parts = []
    
    # 1. 趨勢判斷
    if trend_desc == "止跌反彈" and avg_5day and price > avg_5day:
        alert_parts.append(f"{trend_icon} {trend_desc}且突破均線")
        alert_parts.append("💡 可能形成短期買點，可考慮分批買入")
    elif trend_desc == "止跌反彈":
        alert_parts.append(f"{trend_icon} {trend_desc}，但尚未突破均線")
        alert_parts.append("👀 持續觀察，等待突破確認")
    elif trend_desc == "連續下跌":
        alert_parts.append(f"{trend_icon} {trend_desc}")
        alert_parts.append("⚠️ 趨勢偏弱，建議觀望")
    elif trend_desc == "連續上漲":
        alert_parts.append(f"{trend_icon} {trend_desc}")
        if change_percent > 3:
            alert_parts.append("🚫 漲幅較大，不建議追高")
        else:
            alert_parts.append("📈 可持續持有")
    else:
        alert_parts.append(f"{trend_icon} {trend_desc}")
    
    # 2. 均線位置提示
    if avg_5day:
        alert_parts.append(f"📊 5日均價：{avg_5day:.2f} 元（價格在均線{ma_position}）")
    
    return "\n".join(alert_parts)

def main():
    # 取得台灣時間
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    today = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
    
    print(f"🕐 台灣時間：{now}")
    
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
    history = load_history()
    
    # 檢查是否為新的一天，避免重複記錄
    if not history or history[-1].get('date') != today:
        history.append({
            'date': today,
            'price': price,
            'timestamp': now
        })
        save_history(history)
        print(f"✅ 已記錄今日價格：{price:.2f}")
    
    # 計算 5 日均價
    avg_5day = calculate_avg_price(history, days=5)
    
    # 智能分析
    alert = get_smart_alert(price, yesterday_close, history, avg_5day)
    
    # 組合推播訊息
    msg = (
        f"【台積電價格監控】\n"
        f"時間：{now}\n"
        f"━━━━━━━━━━━━━━\n"
        f"現價：{price:.2f} 元\n"
        f"昨收：{yesterday_close:.2f} 元\n"
        f"漲跌：{change_amount:+.2f} 元（{change_percent:+.2f}%）\n"
        f"━━━━━━━━━━━━━━\n"
        f"{alert}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📝 歷史資料：{len(history)} 天"
    )
    
    send_line_push(msg)
    print("✅ 推播股價資訊完成")
    print(f"   現價：{price:.2f}，昨收：{yesterday_close:.2f}，漲跌：{change_percent:+.2f}%")
    if avg_5day:
        print(f"   5日均價：{avg_5day:.2f}")

if __name__ == "__main__":
    main()