# ⚡ FVG Alert — Kurulum Rehberi

## Nedir?
Yahoo Finance verisini kullanarak belirlediğiniz paritelerde günlük grafikte **FVG (Fair Value Gap)** oluştuğunda veya fiyat FVG bölgesine girdiğinde **Telegram** üzerinden bildirim gönderen sistem.

---

## ⚙️ Kurulum

### 1. Python bağımlılıklarını yükleyin
```bash
pip install -r requirements.txt
```

### 2. Uygulamayı başlatın
```bash
python app.py
```

### 3. Tarayıcınızda açın
```
http://localhost:5000
```

---

## 🤖 Telegram Bot Kurulumu

1. Telegram'da **@BotFather**'a gidin
2. `/newbot` yazın → bot adı ve kullanıcı adı girin
3. Size verilen **Bot Token**'ı kopyalayın

4. **@userinfobot**'a mesaj atın → **Chat ID**'nizi öğrenin

5. Paneldeki "Telegram Botu" bölümüne yapıştırıp **Kaydet**'e tıklayın
6. **Test Gönder** ile doğrulayın

---

## 📊 Desteklenen Semboller (Yahoo Finance)

| Tip | Örnek Semboller |
|-----|----------------|
| Forex | `EURUSD=X`, `GBPUSD=X`, `USDJPY=X` |
| Kripto | `BTC-USD`, `ETH-USD` |
| ABD Hisse | `AAPL`, `TSLA`, `SPY` |
| TR Hisse | `THYAO.IS`, `BIST100.IS` |
| Altın | `GC=F` |
| Ham Petrol | `CL=F` |

---

## 🎯 FVG Algoritması

```
Bullish FVG: mum[i-2].high < mum[i].low
             → Aradaki boşluk destek bölgesi

Bearish FVG: mum[i-2].low > mum[i].high
             → Aradaki boşluk direnç bölgesi

Alarm: Güncel fiyat FVG bölgesinin içine girdiğinde
```

---

## ⏱ Tarama Sıklığı
- Otomatik: **Her 5 dakikada bir**
- Manuel: Panel üzerinden "Şimdi Tara" butonu

---

## 📁 Dosya Yapısı
```
fvg-alert/
├── app.py              # Ana uygulama
├── requirements.txt    # Bağımlılıklar
├── watchlist.json      # Pariteler + ayarlar (otomatik oluşur)
└── templates/
    └── index.html      # Web arayüzü
```
