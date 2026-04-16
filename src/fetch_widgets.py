#!/usr/bin/env python3
"""Haal weer + markten op en schrijf naar /tmp/dagkrant-widgets.json"""
import json
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch(url, timeout=10):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

# ── Weer via Buienradar ───────────────────────────────────────────────────────
weer_temp = "?"; weer_icon = "🌤️"; weer_feel = "?"; weer_wind = "?"; weer_desc = ""; weer_humidity = "?"
try:
    data = fetch("https://data.buienradar.nl/2.0/feed/json", timeout=8)
    j = json.loads(data)
    stations = j["actual"]["stationmeasurements"]
    st = next((s for s in stations if "hilversum" in s.get("stationname","").lower()), stations[0])
    temp = st.get("temperature", st.get("feeltemperature", "?"))
    weer_temp = str(round(float(temp))) if temp != "?" else "?"
    feel = st.get("feeltemperature", temp)
    weer_feel = str(round(float(feel))) if feel else "?"
    wind_ms = st.get("windspeed", 0)
    weer_wind = str(round(float(wind_ms) * 3.6)) if wind_ms else "?"  # m/s → km/h
    weer_humidity = str(round(float(st.get("humidity", 0)))) if st.get("humidity") else "?"
    desc = st.get("weatherdescription", "").lower()
    weer_desc = st.get("weatherdescription", "")
    if "sun" in desc or "clear" in desc or "zonnig" in desc: weer_icon = "☀️"
    elif "partly" in desc or "half" in desc or "half": weer_icon = "⛅"
    elif "cloud" in desc or "bewolkt" in desc: weer_icon = "☁️"
    elif "rain" in desc or "shower" in desc or "regen" in desc: weer_icon = "🌧️"
    elif "storm" in desc or "thunder" in desc: weer_icon = "⛈️"
    elif "snow" in desc or "sneeuw" in desc: weer_icon = "❄️"
    elif "fog" in desc or "mist" in desc: weer_icon = "🌫️"
    else: weer_icon = "🌤️"
except Exception:
    pass

# ── Markten via Yahoo Finance ─────────────────────────────────────────────────
aex="?"; aex_pct="?"; sp500="?"; sp500_pct="?"; brent="?"; brent_pct="?"; eurusd="?"
aex_trend=[]; sp500_trend=[]; brent_trend=[]

def _fetch_symbol(sym, key, wil_trend, dec):
    range_param = "1mo" if wil_trend else "1d"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range={range_param}"
    raw = fetch(url, timeout=10)
    if not raw:
        return key, None, None, None, None
    try:
        j2 = json.loads(raw)
        result = j2["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice", meta.get("chartPreviousClose", 0))
        prev  = meta.get("chartPreviousClose", meta.get("previousClose", price))
        pct   = ((price - prev) / prev * 100) if prev else 0
        sign  = "+" if pct >= 0 else ""
        pct_str = f"{sign}{pct:.1f}%"
        trend = None
        if wil_trend:
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            trend = [round(c, dec) for c in closes if c is not None][-15:]
        return key, price, pct_str, trend, dec
    except Exception:
        return key, None, None, None, dec

try:
    trend_syms = {
        "^AEX":    ("aex",   True,  0),
        "^GSPC":   ("sp500", True,  0),
        "BZ=F":    ("brent", True,  2),
        "EURUSD=X":("eurusd",False, 4),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_symbol, sym, key, wt, dec): sym
                   for sym, (key, wt, dec) in trend_syms.items()}
        for fut in as_completed(futures, timeout=15):
            key, price, pct_str, trend, dec = fut.result()
            if price is None:
                continue
            if key == "aex":
                aex = str(round(price, dec)); aex_pct = pct_str
                if trend: aex_trend = trend
            elif key == "sp500":
                sp500 = str(round(price, dec)); sp500_pct = pct_str
                if trend: sp500_trend = trend
            elif key == "brent":
                brent = f"{price:.{dec}f}"; brent_pct = pct_str
                if trend: brent_trend = trend
            elif key == "eurusd":
                eurusd = f"{price:.4f}"
except Exception:
    pass

# ── Output ────────────────────────────────────────────────────────────────────
out = {
    "weer_temp":      weer_temp,
    "weer_icon":      weer_icon,
    "weer_feel":      weer_feel,
    "weer_wind":      weer_wind,
    "weer_humidity":  weer_humidity,
    "weer_desc":      weer_desc,
    "aex":            aex,   "aex_pct":    aex_pct,   "aex_trend":   aex_trend,
    "sp500":          sp500, "sp500_pct":  sp500_pct, "sp500_trend": sp500_trend,
    "brent":          brent, "brent_pct":  brent_pct, "brent_trend": brent_trend,
    "eurusd":         eurusd,
    "verkeer":        "A27/A28 — zie ANWB",
}

import pathlib
pathlib.Path("/tmp/dagkrant-widgets.json").write_text(json.dumps(out, ensure_ascii=False))
print(f"[widgets] weer={weer_temp}°C {weer_icon} (voelt {weer_feel}°C, wind {weer_wind}km/h) | "
      f"AEX={aex}{aex_pct} | S&P={sp500} | Brent={brent} | EUR/USD={eurusd} | "
      f"trends: AEX={len(aex_trend)}pt S&P={len(sp500_trend)}pt Brent={len(brent_trend)}pt")
