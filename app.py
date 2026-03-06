from flask import Flask, render_template, request, jsonify
import yfinance as yf
import json
import os
import threading
import time
import requests
from datetime import datetime, timedelta

def now_tr():
    return datetime.utcnow() + timedelta(hours=3)

app = Flask(__name__)
SENT_ALERTS = set()
DATA_FILE = "watchlist.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {"pairs": [], "telegram": {"bot_token": "", "chat_id": ""}, "alerts": []}
    if os.environ.get("BOT_TOKEN"):
        data["telegram"]["bot_token"] = os.environ.get("BOT_TOKEN")
    if os.environ.get("CHAT_ID"):
        data["telegram"]["chat_id"] = os.environ.get("CHAT_ID")
    if os.environ.get("PAIRS"):
        env_pairs = os.environ.get("PAIRS").split(",")
        existing = [p["symbol"] for p in data["pairs"]]
        for sym in env_pairs:
            sym = sym.strip().upper()
            if sym and sym not in existing:
                data["pairs"].append({"symbol": sym, "last_price": None, "last_scan": None, "fvgs": []})
    return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

OANDA_SYMBOLS = {
    "EURUSD=X": "EUR_USD", "USDJPY=X": "USD_JPY", "GBPUSD=X": "GBP_USD",
    "USDCHF=X": "USD_CHF", "AUDUSD=X": "AUD_USD", "USDCAD=X": "USD_CAD",
    "NZDUSD=X": "NZD_USD", "EURJPY=X": "EUR_JPY", "GBPJPY=X": "GBP_JPY",
    "EURGBP=X": "EUR_GBP", "GC=F": "XAU_USD", "SI=F": "XAG_USD",
    "CL=F": "WTICO_USD", "BZ=F": "BCO_USD",
    "^DJI": "US30_USD", "^NDX": "NAS100_USD", "^FTSE": "UK100_GBP",
    "^N225": "JP225_USD", "^GDAXI": "DE30_EUR", "^GSPC": "SPX500_USD"
}

CRYPTO_SYMBOLS = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT"
}

def detect_fvg(symbol):
    try:
        if symbol in CRYPTO_SYMBOLS:
            return detect_fvg_binance(symbol)
        else:
            return detect_fvg_oanda(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, []

def detect_fvg_oanda(symbol):
    try:
        api_key = os.environ.get("OANDA_API_KEY", "")
        oanda_symbol = OANDA_SYMBOLS.get(symbol, symbol)
        
        url = f"https://api-fxpractice.oanda.com/v3/instruments/{oanda_symbol}/candles"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {
            "granularity": "D",
            "count": 90,
            "price": "M",
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York"
        }
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        
        if "candles" not in data:
            print(f"OANDA hata {symbol}: {data}")
            return None, []
        
        candles = [c for c in data["candles"] if c["complete"]]
        if len(candles) < 3:
            return None, []
        
        fvgs = []
        for i in range(2, len(candles)):
            h0 = float(candles[i-2]["mid"]["h"])
            l0 = float(candles[i-2]["mid"]["l"])
            h2 = float(candles[i]["mid"]["h"])
            l2 = float(candles[i]["mid"]["l"])
            from datetime import timezone
            candle_time = datetime.fromisoformat(candles[i-1]["time"][:19])
            date = (candle_time + timedelta(hours=3)).strftime("%Y-%m-%d")
            
            if h0 < l2:
                fvg_bottom, fvg_top = h0, l2
                touched = any(float(candles[j]["mid"]["l"]) <= fvg_top and float(candles[j]["mid"]["h"]) >= fvg_bottom for j in range(i+1, len(candles)))
                fvgs.append({"type": "bullish", "top": fvg_top, "bottom": fvg_bottom, "date": date, "filled": touched})
            elif l0 > h2:
                fvg_bottom, fvg_top = h2, l0
                touched = any(float(candles[j]["mid"]["l"]) <= fvg_top and float(candles[j]["mid"]["h"]) >= fvg_bottom for j in range(i+1, len(candles)))
                fvgs.append({"type": "bearish", "top": fvg_top, "bottom": fvg_bottom, "date": date, "filled": touched})
        
        current_price = float(candles[-1]["mid"]["c"])
        recent_fvgs = [f for f in fvgs if not f["filled"]][-15:]
        for fvg in recent_fvgs:
            fvg["price_inside"] = fvg["bottom"] <= current_price <= fvg["top"]
        return current_price, recent_fvgs
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, []

def detect_fvg_binance(symbol):
    try:
        binance_symbol = CRYPTO_SYMBOLS.get(symbol)
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": binance_symbol,
            "interval": "1d",
            "limit": 92
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if not data or isinstance(data, dict):
            print(f"Binance hata {symbol}: {data}")
            return None, []

        data = data[:-1]  # Kapanmamış son mumu çıkar

        if len(data) < 3:
            return None, []

        fvgs = []
        for i in range(2, len(data)):
            h0 = float(data[i-2][2])
            l0 = float(data[i-2][3])
            h2 = float(data[i][2])
            l2 = float(data[i][3])
            date = datetime.utcfromtimestamp(data[i-1][0]/1000).strftime("%Y-%m-%d")

            if h0 < l2:
                fvg_bottom, fvg_top = h0, l2
                touched = any(float(data[j][3]) <= fvg_top and float(data[j][2]) >= fvg_bottom for j in range(i+1, len(data)))
                fvgs.append({"type": "bullish", "top": fvg_top, "bottom": fvg_bottom, "date": date, "filled": touched})
            elif l0 > h2:
                fvg_bottom, fvg_top = h2, l0
                touched = any(float(data[j][3]) <= fvg_top and float(data[j][2]) >= fvg_bottom for j in range(i+1, len(data)))
                fvgs.append({"type": "bearish", "top": fvg_top, "bottom": fvg_bottom, "date": date, "filled": touched})

        current_price = float(data[-1][4])
        recent_fvgs = [f for f in fvgs if not f["filled"]][-15:]
        for fvg in recent_fvgs:
            fvg["price_inside"] = fvg["bottom"] <= current_price <= fvg["top"]
        return current_price, recent_fvgs

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, []

def send_telegram(bot_token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
        print(f"Telegram response: {r.status_code} - {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram hatası: {e}")
        return False

def scan_loop():
    while True:
        try:
            data = load_data()
            bot_token = data["telegram"].get("bot_token", "")
            chat_id = data["telegram"].get("chat_id", "")
            for pair in data["pairs"]:
                symbol = pair["symbol"]
                current_price, fvgs = detect_fvg(symbol)
                if current_price is None:
                    continue
                pair["last_price"] = current_price
                pair["last_scan"] = now_tr().strftime("%H:%M:%S")
                pair["fvgs"] = fvgs
                triggered = [f for f in fvgs if f.get("price_inside")]
                if triggered:
                    triggered = [max(triggered, key=lambda x: x["date"])]
                for fvg in triggered:
                    alert_key = f"{symbol}_{fvg['date']}_{fvg['type']}"
                    if alert_key not in SENT_ALERTS:
                        direction = "📈 BULLISH" if fvg["type"] == "bullish" else "📉 BEARISH"
                        msg = (f"⚡ <b>FVG ALARM!</b>\n\n"
                               f"📊 <b>Parite:</b> {symbol}\n"
                               f"🎯 <b>Tip:</b> {direction} FVG\n"
                               f"💰 <b>Güncel Fiyat:</b> {current_price:.5f}\n"
                               f"📐 <b>FVG Aralığı:</b> {fvg['bottom']:.5f} - {fvg['top']:.5f}\n"
                               f"📅 <b>FVG Tarihi:</b> {fvg['date']}\n"
                               f"⏰ <b>Alarm Zamanı:</b> {now_tr().strftime('%d.%m.%Y %H:%M')}")
                        if bot_token and chat_id:
                            if send_telegram(bot_token, chat_id, msg):
                                SENT_ALERTS.add(alert_key)
                                data["alerts"].insert(0, {"symbol": symbol, "type": fvg["type"], "price": current_price, "fvg_range": f"{fvg['bottom']:.5f} - {fvg['top']:.5f}", "time": now_tr().strftime("%d.%m.%Y %H:%M")})
                                data["alerts"] = data["alerts"][:50]
            save_data(data)
        except Exception as e:
            print(f"Tarama hatası: {e}")
        time.sleep(60)

threading.Thread(target=scan_loop, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def get_data():
    return jsonify(load_data())

@app.route("/api/pairs", methods=["POST"])
def add_pair():
    body = request.json
    symbol = body.get("symbol", "").upper().strip()
    data = load_data()
    if not any(p["symbol"] == symbol for p in data["pairs"]):
        data["pairs"].append({"symbol": symbol, "last_price": None, "last_scan": None, "fvgs": []})
        save_data(data)
    return jsonify({"ok": True})

@app.route("/api/pairs/<symbol>", methods=["DELETE"])
def remove_pair(symbol):
    data = load_data()
    data["pairs"] = [p for p in data["pairs"] if p["symbol"] != symbol.upper()]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/telegram", methods=["POST"])
def save_telegram():
    body = request.json
    data = load_data()
    data["telegram"] = {"bot_token": body.get("bot_token", ""), "chat_id": body.get("chat_id", "")}
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/test_telegram", methods=["POST"])
def test_telegram():
    body = request.json
    ok = send_telegram(body["bot_token"], body["chat_id"], "✅ <b>FVG Alert sistemi bağlantısı başarılı!</b>\nBildirimler aktif.")
    return jsonify({"ok": ok})

@app.route("/api/scan_now", methods=["POST"])
def scan_now():
    data = load_data()
    results = []
    for pair in data["pairs"]:
        price, fvgs = detect_fvg(pair["symbol"])
        pair["last_price"] = price
        pair["last_scan"] = now_tr().strftime("%H:%M:%S")
        pair["fvgs"] = fvgs
        results.append({"symbol": pair["symbol"], "price": price, "fvg_count": len(fvgs)})
    save_data(data)
    return jsonify({"ok": True, "results": results})

port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)