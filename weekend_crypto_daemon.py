#!/usr/bin/env python3
"""
Weekend Crypto Paper Trading Daemon
=====================================
Runs on Mac Mini every 15 min (via LaunchAgent).  On weekdays it exits
immediately.  On weekends it fetches crypto market data, generates
Larry Williams-style signals, and submits them to the Race to $1B engine.

Data sources (all free, no API key required):
  - CoinGecko      : prices, OHLC (14-day), market cap, volume
  - Alternative.me : Fear & Greed Index
  - Binance public : funding rates (optional enrichment)

State saved to: ~/.spartan_crypto_state.json
  → Sierra Intelligence reads this file to render the CRYPTO tab.
"""

import json
import logging
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────
STATE_FILE = Path.home() / ".spartan_crypto_state.json"
LOG_FILE   = Path.home() / "logs" / "weekend_crypto.log"
RACE_API   = "http://127.0.0.1:5027"

COINS: dict[str, str] = {           # symbol → CoinGecko id
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
    "BNB":  "binancecoin",
    "XRP":  "ripple",
    "AVAX": "avalanche-2",
    "ADA":  "cardano",
    "LINK": "chainlink",
    "DOT":  "polkadot",
    "DOGE": "dogecoin",
}

# ── Logging ───────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("weekend_crypto")


# ── Utilities ─────────────────────────────────────────────────

def is_weekend() -> bool:
    return datetime.now().weekday() >= 5   # 5=Sat, 6=Sun


def _http_get(url: str, timeout: int = 12, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SpartanBot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                wait = 30 * (attempt + 1)
                log.warning("Rate limited (429) — waiting %ds before retry %d/%d", wait, attempt + 2, retries)
                time.sleep(wait)
            else:
                log.warning("GET %s failed: %s", url, exc)
                return None
        except Exception as exc:
            log.warning("GET %s failed: %s", url, exc)
            return None
    return None


def _http_post(url: str, payload: dict, timeout: int = 8) -> dict | None:
    try:
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return None


# ── Data fetchers ─────────────────────────────────────────────

def fetch_prices() -> dict:
    """Return {SYM: {price, chg_24h, chg_7d, vol_24h, mkt_cap}} for all coins."""
    ids  = ",".join(COINS.values())
    url  = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd"
        f"&include_24hr_change=true&include_7d_change=true"
        f"&include_market_cap=true&include_24hr_vol=true"
    )
    raw = _http_get(url)
    if not raw:
        return {}
    id_to_sym = {v: k for k, v in COINS.items()}
    return {
        id_to_sym[cid]: {
            "price":    vals.get("usd", 0),
            "chg_24h":  vals.get("usd_24h_change", 0),
            "chg_7d":   vals.get("usd_7d_change", 0),
            "vol_24h":  vals.get("usd_24h_vol", 0),
            "mkt_cap":  vals.get("usd_market_cap", 0),
        }
        for cid, vals in raw.items() if cid in id_to_sym
    }


def fetch_ohlc(coin_id: str, days: int = 14) -> list:
    """Return list of [ts_ms, open, high, low, close] candles."""
    url  = (
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
        f"?vs_currency=usd&days={days}"
    )
    data = _http_get(url)
    return data if isinstance(data, list) else []


def fetch_fear_greed() -> dict:
    data = _http_get("https://api.alternative.me/fng/?limit=1")
    if data and isinstance(data.get("data"), list) and data["data"]:
        e = data["data"][0]
        return {"value": int(e.get("value", 50)), "label": e.get("value_classification", "Neutral")}
    return {"value": 50, "label": "Unknown"}


def fetch_funding_rates() -> dict:
    """Binance public funding rates for BTC/ETH (optional enrichment)."""
    url  = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    data = _http_get(url)
    result: dict = {}
    if data and isinstance(data, dict):
        fr = float(data.get("lastFundingRate", 0))
        result["BTC"] = {"funding_rate": fr, "annualised_pct": round(fr * 3 * 365 * 100, 2)}
    return result


# ── Indicators ────────────────────────────────────────────────

def williams_r(ohlc: list, period: int = 14) -> float | None:
    if len(ohlc) < period:
        return None
    recent = ohlc[-period:]
    hh = max(c[2] for c in recent)
    ll = min(c[3] for c in recent)
    cl = recent[-1][4]
    return None if hh == ll else -100.0 * (hh - cl) / (hh - ll)


# ── Signal generator ──────────────────────────────────────────

def lw_signal(wr: float | None, fear_greed: int, chg_7d: float,
              funding_rate: float | None = None) -> tuple[str, str]:
    """
    Larry Williams-style multi-factor signal.
    Bull/bear scores drive the final label; reasons explain the call.
    """
    bull, bear = 0, 0
    reasons: list[str] = []

    # Williams %R (oversold/overbought)
    if wr is not None:
        if wr < -80:
            bull += 2; reasons.append(f"%R {wr:.0f} oversold")
        elif wr < -60:
            bull += 1; reasons.append(f"%R {wr:.0f} near oversold")
        elif wr > -20:
            bear += 2; reasons.append(f"%R {wr:.0f} overbought")
        elif wr > -40:
            bear += 1; reasons.append(f"%R {wr:.0f} near overbought")

    # Fear & Greed (contrarian sentiment)
    if fear_greed <= 20:
        bull += 3; reasons.append(f"F&G {fear_greed} extreme fear")
    elif fear_greed <= 35:
        bull += 2; reasons.append(f"F&G {fear_greed} fear")
    elif fear_greed <= 45:
        bull += 1; reasons.append(f"F&G {fear_greed} mild fear")
    elif fear_greed >= 80:
        bear += 3; reasons.append(f"F&G {fear_greed} extreme greed")
    elif fear_greed >= 65:
        bear += 2; reasons.append(f"F&G {fear_greed} greed")
    elif fear_greed >= 55:
        bear += 1; reasons.append(f"F&G {fear_greed} mild greed")

    # 7-day trend
    if chg_7d < -15:
        bull += 2; reasons.append(f"7d {chg_7d:.1f}% oversold drop")
    elif chg_7d < -7:
        bull += 1; reasons.append(f"7d {chg_7d:.1f}% pullback")
    elif chg_7d > 20:
        bear += 2; reasons.append(f"7d +{chg_7d:.1f}% extended")
    elif chg_7d > 10:
        bear += 1; reasons.append(f"7d +{chg_7d:.1f}% overbought")

    # BTC funding rate (only for BTC signal)
    if funding_rate is not None:
        if funding_rate < -0.0005:
            bull += 1; reasons.append(f"funding {funding_rate*100:.3f}% negative (shorts paying)")
        elif funding_rate > 0.001:
            bear += 1; reasons.append(f"funding {funding_rate*100:.3f}% high (longs paying)")

    reason = " | ".join(reasons) if reasons else "No clear signal"

    if bull >= 5:   return "STRONG BULLISH", reason
    if bull >= 3 and bull > bear: return "BULLISH", reason
    if bear >= 5:   return "STRONG BEARISH", reason
    if bear >= 3 and bear > bull: return "BEARISH", reason
    return "NEUTRAL", reason


# ── State I/O ─────────────────────────────────────────────────

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"paper_trades": [], "last_run": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ── Main cycle ────────────────────────────────────────────────

def run_cycle() -> None:
    log.info("=== Weekend Crypto Paper Trading Cycle ===")
    start = time.time()

    # Fetch Fear & Greed first (one request, shared across all coins)
    fg = fetch_fear_greed()
    log.info("Fear & Greed: %d (%s)", fg["value"], fg["label"])

    # Optional: BTC funding rate
    funding = fetch_funding_rates()
    btc_funding = funding.get("BTC", {}).get("funding_rate")

    # Fetch all prices in one API call
    prices = fetch_prices()
    if not prices:
        log.error("Price fetch failed — aborting cycle")
        return

    # Collect per-coin data (OHLC fetched individually due to CoinGecko API shape)
    coin_data: dict = {}
    race_signals: list = []

    for sym, coin_id in COINS.items():
        p = prices.get(sym)
        if not p:
            continue

        time.sleep(1.5)   # CoinGecko free tier: ~10 req/min
        ohlc  = fetch_ohlc(coin_id, days=14)
        wr    = williams_r(ohlc)
        fr    = btc_funding if sym == "BTC" else None
        sig, reason = lw_signal(wr, fg["value"], p["chg_7d"], fr)

        log.info(
            "%-5s $%-14s  24h %+6.1f%%  7d %+6.1f%%  %%R %-8s  %s",
            sym, f"{p['price']:,.2f}", p["chg_24h"], p["chg_7d"],
            f"{wr:.0f}" if wr is not None else "-", sig,
        )

        coin_data[sym] = {
            "price":    p["price"],
            "chg_24h":  round(p["chg_24h"], 2),
            "chg_7d":   round(p["chg_7d"], 2),
            "vol_24h":  p["vol_24h"],
            "mkt_cap":  p["mkt_cap"],
            "williams_r": round(wr, 1) if wr is not None else None,
            "signal":   sig,
            "reason":   reason,
        }

        if "BULLISH" in sig:
            race_signals.append({
                "symbol":            f"{sym}/USD",
                "strategy":          "lw_williams_r",
                "direction":         "LONG",
                "entry_price":       p["price"],
                "stop_distance_pct": 4.0 if "STRONG" in sig else 5.5,
                "win_rate":          0.67 if "STRONG" in sig else 0.60,
                "reward_risk":       2.5,
                "confidence":        0.80 if "STRONG" in sig else 0.65,
                "reasoning":         reason,
                "asset_class":       "crypto",
                "weekend_session":   True,
            })

    # Submit to Race to $1B for position sizing evaluation
    approved_trades: list = []
    if race_signals:
        result = _http_post(f"{RACE_API}/api/race/evaluate", {"signals": race_signals})
        if result:
            approved_trades = result.get("signals", [])
            log.info(
                "Race API: %d submitted → %d approved / %d rejected",
                len(race_signals), len(approved_trades),
                result.get("rejected", 0),
            )
        else:
            log.warning("Race API unreachable — signals not evaluated (Race to $1B not running?)")

    # Persist state for Sierra Intelligence to read
    state = load_state()
    state.update({
        "last_run":    datetime.now().isoformat(),
        "mode":        "ACTIVE" if is_weekend() else "IDLE",
        "fear_greed":  fg,
        "coins":       coin_data,
        "btc_funding": btc_funding,
    })
    # Append new paper trades (keep last 200)
    for s in approved_trades:
        state["paper_trades"].append({
            "ts":         datetime.now().isoformat(),
            "symbol":     s["symbol"],
            "direction":  s.get("direction", "LONG"),
            "entry":      s.get("entry_price", 0),
            "size_usd":   round(s.get("position_size_usd", 0), 2),
            "risk_usd":   round(s.get("risk_usd", 0), 2),
            "reasoning":  s.get("reasoning", ""),
            "status":     "OPEN",
        })
    state["paper_trades"] = state["paper_trades"][-200:]

    save_state(state)
    log.info("Cycle complete in %.1fs — state saved to %s", time.time() - start, STATE_FILE)


def main() -> None:
    force = "--force" in sys.argv
    if not force and not is_weekend():
        log.info("Weekday — crypto daemon idle. Use --force to run anyway.")
        return
    run_cycle()


if __name__ == "__main__":
    main()
