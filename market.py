import requests
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")

STOCKS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN"
}

def get_stock_price(symbol):
    try:
        yahoo_symbol = STOCKS.get(symbol, symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return round(price, 2)
    except Exception as e:
        print(f"Price fetch error [{symbol}]: {e}")
        return None

def get_all_closing_prices():
    prices = {}
    for symbol in STOCKS:
        price = get_stock_price(symbol)
        if price:
            prices[symbol] = price
    return prices

def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close

def is_prediction_window_open():
    return not is_market_open()

def get_next_trading_date():
    from datetime import timedelta
    now = datetime.now(IST)
    next_day = now + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.date()

def calculate_points(predicted, actual):
    if actual == 0:
        return 0
    diff_percent = abs(predicted - actual) / actual * 100
    if diff_percent > 5:
        return 0
    points = round(100 - (diff_percent * 20), 2)
    return max(0, points)