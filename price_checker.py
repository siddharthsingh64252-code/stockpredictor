import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

INDEX_MAP = {
    "NIFTY50":    "^NSEI",
    "NIFTY":      "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "SENSEX":     "^BSESN",
}


def get_stock_price(symbol: str):
    try:
        symbol     = symbol.upper().strip()
        yf_symbol  = INDEX_MAP.get(symbol, symbol + ".NS")
        url        = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
        resp       = requests.get(url, headers=HEADERS, timeout=10)
        data       = resp.json()
        price      = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return round(float(price), 2)
    except Exception as e:
        print(f"[price_checker] {symbol}: {e}")
        return None


def get_closing_price(symbol: str):
    return get_stock_price(symbol)