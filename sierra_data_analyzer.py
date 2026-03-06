#!/usr/bin/env python3
"""
Sierra Data Analyzer — Screenshot-first AI Vision + OHLCV Technical Analysis
=============================================================================
Primary: Takes a screenshot of Sierra Chart every 60 s, sends to Claude vision
         API to read the actual indicators the user has set up.
Fallback: Reads .dly OHLCV files and calculates standard technical indicators
          when Sierra Chart is not on screen or API is unavailable.

Signals reflect the user's real Sierra Chart indicator setup.
Output: /tmp/sierra_analysis.json — read by sierra_screenshot_server.py dashboard
"""

import json
import time
import math
import os
import re
import base64
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Optional

SIERRA_DATA_DIR    = Path("/mnt/c/Users/Quantum/Downloads/SierraChart/Data")
OUTPUT_FILE        = Path("/tmp/sierra_analysis.json")
UPDATE_INTERVAL    = 60   # seconds — take screenshot every minute

# Load .env so ANTHROPIC_API_KEY is available even when launched without sourcing .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(errors="ignore").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip('"').strip("'")
            if _k:
                os.environ[_k] = _v

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
# Windows temp path (accessible from WSL via /mnt/c/...)
_WIN_CAPTURE       = r"C:\Users\Quantum\AppData\Local\Temp\sierra_sc.png"
SCREEN_CAPTURE     = Path("/mnt/c/Users/Quantum/AppData/Local/Temp/sierra_sc.png")

# The primary symbols to track (from chartbook structure)
TRACKED_SYMBOLS = {
    "M2KH26-CME":     {"name": "Micro Russell 2000", "category": "Equity"},
    "MESH26-CME":     {"name": "Micro S&P 500",      "category": "Equity"},
    "MNQH26-CME":     {"name": "Micro NASDAQ 100",   "category": "Equity"},
    "MYMH26-CBOT":    {"name": "Micro Dow",          "category": "Equity"},
    "MBTG26-CME":     {"name": "Micro Bitcoin",      "category": "Crypto"},
    "METG26-CME":     {"name": "Micro Ether",        "category": "Crypto"},
    "MGCJ26-COMEX":   {"name": "Micro Gold",         "category": "Commodity"},
    "MHGH26-COMEX":   {"name": "Micro Copper",       "category": "Commodity"},
    "MCLJ26-NYMEX":   {"name": "Micro Crude Oil",    "category": "Energy"},
    "MSLG26-CME":     {"name": "Micro Silver",       "category": "Commodity"},
    "MZLK26-CBOT":    {"name": "Micro Corn",         "category": "Grain"},
    "AAPL":           {"name": "Apple",               "category": "Stock"},
    "TSLA-NQTV":      {"name": "Tesla",               "category": "Stock"},
    "NVDA-NQTV":      {"name": "NVIDIA",              "category": "Stock"},
    "GOOGL-NQTV":     {"name": "Alphabet",            "category": "Stock"},
    "MSFT-NQTV":      {"name": "Microsoft",           "category": "Stock"},
}


def _read_dly(symbol_key: str) -> list:
    """Read Sierra Chart .dly file and return list of OHLCV dicts (newest last)."""
    path = SIERRA_DATA_DIR / f"{symbol_key}.dly"
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("Date"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 5:
                    continue
                try:
                    rows.append({
                        "date": parts[0],
                        "open":   float(parts[1]),
                        "high":   float(parts[2]),
                        "low":    float(parts[3]),
                        "close":  float(parts[4]),
                        "volume": float(parts[5]) if len(parts) > 5 else 0,
                    })
                except (ValueError, IndexError):
                    continue
    except Exception:
        pass
    return rows


def _ema(values: list, period: int) -> list:
    """Exponential Moving Average."""
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    result.append(ema)
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
        result.append(ema)
    return result


def _sma(values: list, period: int) -> list:
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def _rsi(closes: list, period: int = 14) -> list:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    result = [None] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100 - 100 / (1 + rs))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    return result


def _macd(closes: list, fast=12, slow=26, signal=9):
    """MACD line, signal line, histogram."""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid_macd = [v for v in macd_line if v is not None]
    sig_raw = _ema(valid_macd, signal)
    # Pad signal to full length
    sig_padded = [None] * (len(macd_line) - len(sig_raw)) + sig_raw
    histogram = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, sig_padded)
    ]
    return macd_line, sig_padded, histogram


def _bollinger(closes: list, period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands: upper, middle (SMA), lower."""
    sma = _sma(closes, period)
    upper, lower = [], []
    for i, mid in enumerate(sma):
        if mid is None:
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            sigma = math.sqrt(variance)
            upper.append(mid + std_dev * sigma)
            lower.append(mid - std_dev * sigma)
    return upper, sma, lower


def _atr(rows: list, period: int = 14) -> list:
    """Average True Range."""
    if len(rows) < 2:
        return [None] * len(rows)
    trs = [None]
    for i in range(1, len(rows)):
        high = rows[i]["high"]
        low = rows[i]["low"]
        prev_close = rows[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    result = [None] * period
    valid_trs = [t for t in trs if t is not None]
    if len(valid_trs) < period:
        return [None] * len(rows)
    atr = sum(valid_trs[:period]) / period
    result.append(atr)
    for tr in valid_trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        result.append(atr)
    return result


def analyze_symbol(symbol_key: str, meta: dict, ai_override: dict = None) -> Optional[dict]:
    """
    Full technical analysis for a single symbol using real price data.
    Returns a structured analysis dict or None if insufficient data.
    """
    rows = _read_dly(symbol_key)
    if len(rows) < 50:
        return None

    # Use last 500 bars (or all if fewer)
    rows = rows[-500:]
    closes = [r["close"] for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    vols   = [r["volume"] for r in rows]

    n = len(rows)
    last_close = closes[-1]
    last_date  = rows[-1]["date"]

    # ── Technical Indicators ──────────────────────────────────────────────────

    # Moving Averages
    ema9   = _ema(closes, 9)
    ema21  = _ema(closes, 21)
    sma50  = _sma(closes, 50)
    sma200 = _sma(closes, 200) if n >= 200 else [None] * n

    # RSI
    rsi = _rsi(closes, 14)

    # MACD
    macd_line, macd_signal, macd_hist = _macd(closes)

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = _bollinger(closes, 20, 2.0)

    # ATR (for volatility / stop estimation)
    atr = _atr(rows, 14)

    # Volume trend (10-bar vs 50-bar average volume)
    def vol_avg(n_bars):
        vslice = [v for v in vols[-n_bars:] if v > 0]
        return sum(vslice) / len(vslice) if vslice else 0

    vol_10 = vol_avg(10)
    vol_50 = vol_avg(50)
    vol_ratio = vol_10 / vol_50 if vol_50 > 0 else 1.0

    # ── Current Values ────────────────────────────────────────────────────────
    cur_rsi     = rsi[-1]
    cur_ema9    = ema9[-1]
    cur_ema21   = ema21[-1]
    cur_sma50   = sma50[-1]
    cur_sma200  = sma200[-1]
    cur_macd    = macd_line[-1]
    cur_signal  = macd_signal[-1]
    cur_hist    = macd_hist[-1]
    prev_hist   = macd_hist[-2] if len(macd_hist) >= 2 else None
    cur_bb_u    = bb_upper[-1]
    cur_bb_l    = bb_lower[-1]
    cur_bb_m    = bb_mid[-1]
    cur_atr     = atr[-1]

    if any(v is None for v in [cur_rsi, cur_ema9, cur_ema21, cur_sma50, cur_macd, cur_signal]):
        return None

    # ── Signal Scoring System ─────────────────────────────────────────────────
    # Each factor contributes +1 (bullish), -1 (bearish), or 0 (neutral)
    # Final score determines BUY/SELL/HOLD

    scores = []
    reasons = []

    # 1. RSI zone
    if cur_rsi < 35:
        scores.append(1)
        reasons.append(f"RSI oversold ({cur_rsi:.1f})")
    elif cur_rsi > 65:
        scores.append(-1)
        reasons.append(f"RSI overbought ({cur_rsi:.1f})")
    else:
        scores.append(0)

    # 2. RSI momentum direction (rising vs falling)
    rsi_5ago = rsi[-6] if len(rsi) >= 6 and rsi[-6] is not None else cur_rsi
    rsi_delta = cur_rsi - rsi_5ago
    if rsi_delta > 3:
        scores.append(1)
        reasons.append(f"RSI rising +{rsi_delta:.1f}")
    elif rsi_delta < -3:
        scores.append(-1)
        reasons.append(f"RSI falling {rsi_delta:.1f}")
    else:
        scores.append(0)

    # 3. MACD crossover (histogram sign change)
    if prev_hist is not None:
        if cur_hist > 0 and prev_hist <= 0:
            scores.append(2)
            reasons.append("MACD bullish crossover")
        elif cur_hist < 0 and prev_hist >= 0:
            scores.append(-2)
            reasons.append("MACD bearish crossover")
        elif cur_hist > 0:
            scores.append(1)
            reasons.append(f"MACD above signal ({cur_hist:+.4f})")
        elif cur_hist < 0:
            scores.append(-1)
            reasons.append(f"MACD below signal ({cur_hist:+.4f})")
        else:
            scores.append(0)
    else:
        scores.append(0)

    # 4. Price vs 50 SMA
    if last_close > cur_sma50 * 1.005:
        scores.append(1)
        reasons.append(f"Price above 50SMA")
    elif last_close < cur_sma50 * 0.995:
        scores.append(-1)
        reasons.append(f"Price below 50SMA")
    else:
        scores.append(0)

    # 5. EMA 9 vs EMA 21 (short-term trend)
    if cur_ema9 > cur_ema21 * 1.002:
        scores.append(1)
        reasons.append("EMA9 > EMA21 (uptrend)")
    elif cur_ema9 < cur_ema21 * 0.998:
        scores.append(-1)
        reasons.append("EMA9 < EMA21 (downtrend)")
    else:
        scores.append(0)

    # 6. 200 SMA (only if available)
    if cur_sma200 is not None:
        if last_close > cur_sma200:
            scores.append(1)
            reasons.append("Price above 200SMA (bull market)")
        else:
            scores.append(-1)
            reasons.append("Price below 200SMA (bear market)")

    # 7. Bollinger Band position
    bb_range = cur_bb_u - cur_bb_l if cur_bb_u and cur_bb_l and cur_bb_u != cur_bb_l else 1
    bb_pct = (last_close - cur_bb_l) / bb_range if bb_range > 0 else 0.5
    if bb_pct < 0.2:
        scores.append(1)
        reasons.append(f"Price near BB lower ({bb_pct:.0%})")
    elif bb_pct > 0.8:
        scores.append(-1)
        reasons.append(f"Price near BB upper ({bb_pct:.0%})")
    else:
        scores.append(0)

    # 8. Volume confirmation
    if vol_ratio > 1.3:
        # High volume — amplifies current direction
        price_chg = last_close - closes[-6] if len(closes) >= 6 else 0
        if price_chg > 0:
            scores.append(1)
            reasons.append(f"High volume {vol_ratio:.1f}x upward")
        else:
            scores.append(-1)
            reasons.append(f"High volume {vol_ratio:.1f}x downward")
    else:
        scores.append(0)

    # ── Final Signal ──────────────────────────────────────────────────────────
    total = sum(scores)
    max_score = len(scores) * 2  # If all were ±2

    # Normalize confidence: |total| / max_possible
    confidence = min(abs(total) / max(max_score, 1), 0.95)
    # Minimum confidence floor
    confidence = max(confidence, 0.45)

    if total >= 5:
        signal = "Strong Bullish"
    elif total >= 3:
        signal = "Bullish"
    elif total <= -5:
        signal = "Strong Bearish"
    elif total <= -3:
        signal = "Bearish"
    else:
        signal = "Neutral"
        confidence = max(0.5 - abs(total) * 0.05, 0.4)

    # ── Risk Metrics ──────────────────────────────────────────────────────────
    atr_val = cur_atr if cur_atr else (last_close * 0.01)
    # Typical stop = 2× ATR below entry (buy) or above entry (sell)
    if signal in ("Strong Bullish", "Bullish"):
        stop_loss = last_close - 2 * atr_val
        target    = last_close + 3 * atr_val
    elif signal in ("Strong Bearish", "Bearish"):
        stop_loss = last_close + 2 * atr_val
        target    = last_close - 3 * atr_val
    else:
        stop_loss = last_close - atr_val
        target    = last_close + atr_val

    risk  = abs(last_close - stop_loss)
    reward = abs(target - last_close)
    rr_ratio = reward / risk if risk > 0 else 0

    # Price change (5-bar)
    price_5ago = closes[-6] if len(closes) >= 6 else closes[0]
    pct_chg_5 = (last_close - price_5ago) / price_5ago * 100 if price_5ago > 0 else 0

    # ── Multi-Timeframe Predictions ───────────────────────────────────────────
    # Each timeframe uses a subset of indicators weighted for that horizon

    def _signal_label(sc, max_sc):
        c = min(abs(sc) / max(max_sc, 1), 0.95)
        c = max(c, 0.45)
        if sc >= 4:
            return "Strong Bullish", round(c, 3)
        elif sc >= 2:
            return "Bullish", round(c, 3)
        elif sc <= -4:
            return "Strong Bearish", round(c, 3)
        elif sc <= -2:
            return "Bearish", round(c, 3)
        else:
            return "Neutral", round(max(0.5 - abs(sc) * 0.05, 0.4), 3)

    # 24h: Short-term momentum (RSI direction, MACD histogram, price vs EMA9)
    s24 = []
    s24.append(1 if cur_rsi < 40 else (-1 if cur_rsi > 60 else 0))
    s24.append(2 if (cur_hist > 0 and prev_hist is not None and prev_hist <= 0)
               else (-2 if (cur_hist < 0 and prev_hist is not None and prev_hist >= 0)
               else (1 if cur_hist > 0 else (-1 if cur_hist < 0 else 0))))
    s24.append(1 if last_close > cur_ema9 * 1.001 else (-1 if last_close < cur_ema9 * 0.999 else 0))
    s24.append(1 if rsi_delta > 2 else (-1 if rsi_delta < -2 else 0))
    sig_24h, conf_24h = _signal_label(sum(s24), len(s24) * 2)

    # 5-day: Medium-term trend (MACD direction, EMA9 vs EMA21, volume)
    s5d = []
    s5d.append(1 if cur_hist > 0 else (-1 if cur_hist < 0 else 0))
    s5d.append(1 if cur_ema9 > cur_ema21 else -1)
    s5d.append(1 if last_close > cur_sma50 else -1)
    vol_dir = 1 if (vol_ratio > 1.2 and pct_chg_5 > 0) else (-1 if (vol_ratio > 1.2 and pct_chg_5 < 0) else 0)
    s5d.append(vol_dir)
    s5d.append(1 if cur_rsi > 50 else -1)
    sig_5d, conf_5d = _signal_label(sum(s5d), len(s5d) * 2)

    # 1-month: Longer-term structure (SMA200, 50SMA position, Bollinger bandwidth)
    s1m = []
    s1m.append(1 if (cur_sma200 and last_close > cur_sma200) else (-1 if cur_sma200 else 0))
    s1m.append(1 if last_close > cur_sma50 else -1)
    s1m.append(1 if cur_ema9 > cur_ema21 * 1.01 else (-1 if cur_ema9 < cur_ema21 * 0.99 else 0))
    # Bollinger squeeze trend
    bb_width = (cur_bb_u - cur_bb_l) / cur_bb_m if cur_bb_m and cur_bb_u and cur_bb_l else 0
    s1m.append(1 if bb_pct > 0.5 and bb_width > 0.05 else (-1 if bb_pct < 0.5 and bb_width > 0.05 else 0))
    s1m.append(1 if cur_macd > 0 else -1)
    sig_1m, conf_1m = _signal_label(sum(s1m), len(s1m) * 2)

    # ── AI vision override: use Claude's reading of the actual Sierra Chart ──
    ai_source = "technical"
    if ai_override:
        ai_sig  = ai_override.get("signal", signal)
        ai_conf = ai_override.get("confidence", confidence)
        ai_why  = ai_override.get("reasoning", "")
        ai_ind  = ai_override.get("indicators", {})
        _valid_signals = ("Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish",
                          "BUY", "SELL", "HOLD")  # accept legacy labels from AI
        if ai_sig in _valid_signals:
            # Normalize legacy labels
            _legacy = {"BUY": "Bullish", "SELL": "Bearish", "HOLD": "Neutral"}
            signal     = _legacy.get(ai_sig, ai_sig)
            confidence = float(ai_conf)
            # Prepend the AI chart reading to reasons
            if ai_why:
                reasons = [f"[Sierra Chart] {ai_why}"] + reasons[:2]
            # Merge any indicator values Claude read from the chart
            for k, v in ai_ind.items():
                if k not in ("description",):
                    reasons.append(f"{k}: {v}")
            ai_source = "ai_vision"
        # Update multi-timeframe predictions from AI if provided
        if ai_sig in _valid_signals:
            sig_24h, conf_24h = ai_sig, round(min(float(ai_conf) * 0.9, 0.95), 3)
            sig_5d,  conf_5d  = ai_sig, round(min(float(ai_conf) * 0.8, 0.95), 3)
            sig_1m,  conf_1m  = ai_sig, round(min(float(ai_conf) * 0.7, 0.95), 3)

    return {
        "symbol": symbol_key,
        "name": meta["name"],
        "category": meta["category"],
        "signal": signal,
        "confidence": round(confidence, 3),
        "score": total,
        "signal_source": ai_source,
        "last_close": round(last_close, 6),
        "last_date": last_date,
        "predictions": {
            "current": {"signal": signal, "confidence": round(confidence, 3)},
            "24h":     {"signal": sig_24h, "confidence": conf_24h},
            "5d":      {"signal": sig_5d,  "confidence": conf_5d},
            "1m":      {"signal": sig_1m,  "confidence": conf_1m},
        },
        "indicators": {
            "rsi_14":       round(cur_rsi, 2),
            "ema_9":        round(cur_ema9, 6),
            "ema_21":       round(cur_ema21, 6),
            "sma_50":       round(cur_sma50, 6),
            "sma_200":      round(cur_sma200, 6) if cur_sma200 else None,
            "macd":         round(cur_macd, 6),
            "macd_signal":  round(cur_signal, 6),
            "macd_hist":    round(cur_hist, 6),
            "bb_upper":     round(cur_bb_u, 6) if cur_bb_u else None,
            "bb_lower":     round(cur_bb_l, 6) if cur_bb_l else None,
            "bb_pct":       round(bb_pct, 3),
            "atr_14":       round(atr_val, 6),
            "vol_ratio":    round(vol_ratio, 2),
        },
        "risk": {
            "stop_loss":      round(stop_loss, 6),
            "target":         round(target, 6),
            "risk_reward":    round(rr_ratio, 2),
            "atr":            round(atr_val, 6),
            "pct_change_5d":  round(pct_chg_5, 2),
        },
        "reasons": reasons,
        "bars_analyzed": len(rows),
        "analyzed_at": datetime.now().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Screenshot capture + Claude vision analysis
# ──────────────────────────────────────────────────────────────────────────────

def _take_screenshot() -> bool:
    """Capture the primary Windows monitor via powershell.exe. Returns True if OK."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$s=[System.Windows.Forms.Screen]::PrimaryScreen;"
        "$b=New-Object System.Drawing.Bitmap($s.Bounds.Width,$s.Bounds.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen($s.Bounds.Location,[System.Drawing.Point]::Empty,$s.Bounds.Size);"
        f"$b.Save('{_WIN_CAPTURE}');"
        "$g.Dispose();$b.Dispose()"
    )
    try:
        # Write PS to temp file; use win_hidden.exe (CREATE_NO_WINDOW) to avoid flash
        _tmp_ps = '/mnt/c/Users/Quantum/AppData/Local/Temp/sierra_screenshot.ps1'
        _win_ps = r'C:\Users\Quantum\AppData\Local\Temp\sierra_screenshot.ps1'
        with open(_tmp_ps, 'w', encoding='utf-8') as _f:
            _f.write(ps)
        subprocess.run(
            ['/mnt/c/Users/Quantum/win_hidden.exe',
             f'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File {_win_ps}'],
            capture_output=True, timeout=20
        )
        try:
            import os as _os
            _os.unlink(_tmp_ps)
        except Exception:
            pass
        return SCREEN_CAPTURE.exists() and SCREEN_CAPTURE.stat().st_size > 30_000
    except Exception:
        return False


def _analyze_with_claude(img_path: Path) -> dict:
    """Send screenshot to Claude Haiku vision API. Returns per-symbol AI signals."""
    if not ANTHROPIC_API_KEY:
        return {}
    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

        syms_list = ", ".join(
            sym.split("-")[0] for sym in TRACKED_SYMBOLS.keys()
        )

        prompt = (
            "This is a screenshot of the Sierra Chart trading platform. "
            "The user has their own custom indicator setup on each chart "
            "(moving averages, RSI, MACD, VWAP, volume, custom studies, etc.).\n\n"
            "Analyze EVERY chart panel visible on screen:\n"
            "1. Identify the ticker/contract symbol (look at chart title)\n"
            "2. Read ALL visible indicators and their current state\n"
            "3. Determine the signal based on what those indicators show\n\n"
            f"Known symbols (may be visible): {syms_list}\n\n"
            "Return ONLY this JSON — no markdown, no explanation:\n"
            '{"sierra_visible":true/false,"charts_found":N,'
            '"symbols":{"SYMBOL":{"signal":"Strong Bullish"/"Bullish"/"Neutral"/"Bearish"/"Strong Bearish",'
            '"confidence":0.0-1.0,"timeframe":"Daily/4H/1H/etc",'
            '"indicators":{"name":"state"},'
            '"reasoning":"what the chart indicators show",'
            '"price":N_or_null}}}'
        )

        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 2048,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            # Strip markdown fences if Claude wrapped it
            text = re.sub(r"^```\w*\s*", "", text)
            text = re.sub(r"\s*```$", "", text.strip())
            result = json.loads(text)
            if result.get("sierra_visible") and result.get("symbols"):
                return result["symbols"]  # {SYM: {...}, ...}
            return {}
    except urllib.error.HTTPError as exc:
        body = ""
        try: body = exc.read().decode()
        except Exception: pass
        if "credit balance" in body or exc.code == 402:
            print("  [claude-vision] API credits depleted — using OHLCV math", flush=True)
        else:
            print(f"  [claude-vision] HTTP {exc.code}: {body[:120]}", flush=True)
        return {}
    except Exception as exc:
        print(f"  [claude-vision] {type(exc).__name__}: {exc}", flush=True)
        return {}


def run_analysis() -> dict:
    """Analyze all tracked symbols and return full results dict."""
    results = {}
    errors  = []

    # ── Step 1: Screenshot + AI vision (reads actual Sierra Chart indicators) ──
    ai_signals: dict = {}
    if ANTHROPIC_API_KEY:
        if _take_screenshot():
            ai_signals = _analyze_with_claude(SCREEN_CAPTURE)
            if ai_signals:
                print(f"  AI vision: {len(ai_signals)} charts read from screen", flush=True)
        else:
            print("  Screenshot: Sierra Chart not captured (minimised/off)", flush=True)
    else:
        print("  Screenshot: ANTHROPIC_API_KEY not set — using OHLCV math only", flush=True)

    for sym, meta in TRACKED_SYMBOLS.items():
        try:
            # Try to match AI result for this symbol (base name match)
            base = sym.split("-")[0]
            ai_override = ai_signals.get(sym) or ai_signals.get(base)
            result = analyze_symbol(sym, meta, ai_override=ai_override)
            if result:
                results[sym] = result
        except Exception as e:
            errors.append(f"{sym}: {e}")

    # Summary counts
    strong_bull = sum(1 for r in results.values() if r["signal"] == "Strong Bullish")
    bull_count  = sum(1 for r in results.values() if r["signal"] == "Bullish")
    neutral_n   = sum(1 for r in results.values() if r["signal"] == "Neutral")
    bear_count  = sum(1 for r in results.values() if r["signal"] == "Bearish")
    strong_bear = sum(1 for r in results.values() if r["signal"] == "Strong Bearish")

    return {
        "timestamp": datetime.now().isoformat(),
        "symbols_analyzed": len(results),
        "summary": {
            "Strong Bullish": strong_bull,
            "Bullish": bull_count,
            "Neutral": neutral_n,
            "Bearish": bear_count,
            "Strong Bearish": strong_bear,
        },
        "symbols": results,
        "errors": errors,
    }


def main():
    print(f"Sierra Data Analyzer — reading from {SIERRA_DATA_DIR}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Tracking {len(TRACKED_SYMBOLS)} symbols\n")

    while True:
        print(f"[{datetime.now():%H:%M:%S}] Running analysis...", end=" ", flush=True)
        data = run_analysis()

        # Write atomically
        tmp = OUTPUT_FILE.with_suffix(".json.tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        tmp.rename(OUTPUT_FILE)

        n = data["symbols_analyzed"]
        s = data["summary"]
        print(f"{n} symbols → ▲▲{s['Strong Bullish']} ▲{s['Bullish']} ●{s['Neutral']} ▼{s['Bearish']} ▼▼{s['Strong Bearish']}")
        if data["errors"]:
            print(f"  Errors: {data['errors']}")

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
