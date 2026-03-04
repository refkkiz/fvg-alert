from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import json
import os
import threading
import time
import requests
from datetime import datetime, timedelta

app = Flask(__name__)
DATA_FILE = "watchlist.json"

# ─── Veri Yönetimi ───────────────────────────────────────────────────────────

import os

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
    
    # Pariteler env'den geliyorsa ekle
    if os.environ.get("PAIRS"):
        env_pairs = os.environ.get("PAIRS").split(",")
        existing = [p["symbol"] for p in data["pairs"]]
        for sym in env_pairs:
            sym = sym.strip().upper()
            if sym and sym not in existing:
                data["pairs"].append({"symbol": sym, "last_price": None, "last_scan": None, "fvgs": []})
    
    return data

# ─── FVG Tespit Algoritması ───────────────────────────────────────────────────

def detect_fvg(symbol):
    """
    FVG (Fair Value Gap) tespiti:
    Bullish FVG: Mum[i-2].high < Mum[i].low  → aradaki boşluk = FVG
    Bearish FVG: Mum[i-2].low  > Mum[i].high → aradaki boşluk = FVG
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="60d", interval="1d")
        if df.empty or len(df) < 3:
            return None, []

        fvgs = []
        for i in range(2, len(df)):
            c0 = df.iloc[i-2]  # 3 mum öncesi
            c2 = df.iloc[i]    # güncel mum

            # Bullish FVG
            if c0["High"] < c2["Low"]:
                fvgs.append({
                    "type": "bullish",
                    "top": float(c2["Low"]),
                    "bottom": float(c0["High"]),
                    "date": str(df.index[i-1].date()),
                    "filled": False
                })

            # Bearish FVG
            elif c0["Low"] > c2["High"]:
                fvgs.append({
                    "type": "bearish",
                    "top": float(c0["Low"]),
                    "bottom": float(c2["High"]),
                    "date": str(df.index[i-1].date()),
                    "filled": False
                })

        current_price = float(df["Close"].iloc[-1])

        # Son 10 FVG'yi kontrol et, dolu olanları işaretle
        recent_fvgs = fvgs[-15:]
        for fvg in recent_fvgs:
            if fvg["bottom"] <= current_price <= fvg["top"]:
                fvg["price_inside"] = True
            else:
                fvg["price_inside"] = False

        return current_price, recent_fvgs

    except Exception as e:
        import traceback
        print(f"FVG tespit hatası {symbol}: {e}")
        traceback.print_exc()
        return None, []

# ─── Telegram Bildirimi ───────────────────────────────────────────────────────

def send_telegram(bot_token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        r = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response: {r.status_code} - {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram hatası: {e}")
        return False

# ─── Arka Plan Tarama ─────────────────────────────────────────────────────────

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
                pair["last_scan"] = datetime.now().strftime("%H:%M:%S")
                pair["fvgs"] = fvgs

                # FVG içinde fiyat var mı? Sadece en yeni FVG'yi al
                triggered = [f for f in fvgs if f.get("price_inside")]
                if triggered:
                    triggered = [max(triggered, key=lambda x: x["date"])]

                for fvg in triggered:
                    alert_key = f"{symbol}_{fvg['date']}_{fvg['type']}"
                    sent_alerts = data.get("sent_alerts", [])

                    if alert_key not in sent_alerts:
                        direction = "📈 BULLISH" if fvg["type"] == "bullish" else "📉 BEARISH"
                        msg = (
                            f"⚡ <b>FVG ALARM!</b>\n\n"
                            f"📊 <b>Parite:</b> {symbol}\n"
                            f"🎯 <b>Tip:</b> {direction} FVG\n"
                            f"💰 <b>Güncel Fiyat:</b> {current_price:.5f}\n"
                            f"📐 <b>FVG Aralığı:</b> {fvg['bottom']:.5f} - {fvg['top']:.5f}\n"
                            f"📅 <b>FVG Tarihi:</b> {fvg['date']}\n"
                            f"⏰ <b>Alarm Zamanı:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                        )
                        if bot_token and chat_id:
                            if send_telegram(bot_token, chat_id, msg):
                                sent_alerts.append(alert_key)
                                data["sent_alerts"] = sent_alerts
                                # Alarm geçmişine ekle
                                data["alerts"].insert(0, {
                                    "symbol": symbol,
                                    "type": fvg["type"],
                                    "price": current_price,
                                    "fvg_range": f"{fvg['bottom']:.5f} - {fvg['top']:.5f}",
                                    "time": datetime.now().strftime("%d.%m.%Y %H:%M")
                                })
                                data["alerts"] = data["alerts"][:50]

            save_data(data)
        except Exception as e:
            print(f"Tarama hatası: {e}")

        time.sleep(300)  # 5 dakikada bir tara

# ─── API Endpoint'leri ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def get_data():
    data = load_data()
    return jsonify(data)

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
    data["telegram"] = {
        "bot_token": body.get("bot_token", ""),
        "chat_id": body.get("chat_id", "")
    }
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/test_telegram", methods=["POST"])
def test_telegram():
    body = request.json
    ok = send_telegram(body["bot_token"], body["chat_id"],
                       "✅ <b>FVG Alert sistemi bağlantısı başarılı!</b>\nBildirimler aktif.")
    return jsonify({"ok": ok})

@app.route("/api/scan_now", methods=["POST"])
def scan_now():
    """Manuel anlık tarama"""
    data = load_data()
    results = []
    for pair in data["pairs"]:
        price, fvgs = detect_fvg(pair["symbol"])
        pair["last_price"] = price
        pair["last_scan"] = datetime.now().strftime("%H:%M:%S")
        pair["fvgs"] = fvgs
        results.append({"symbol": pair["symbol"], "price": price, "fvg_count": len(fvgs)})
    save_data(data)
    return jsonify({"ok": True, "results": results})

if __name__ == "__main__":
    # Arka plan tarama thread'ini başlat
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    print("🚀 FVG Alert sistemi başlatıldı → http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)
