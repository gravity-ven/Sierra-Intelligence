#!/usr/bin/env python3
"""
Sierra Intelligence Dashboard — port 5050
Multi-timeframe technical analysis from real Sierra Chart price data.
Spartan theme. No broken images.
"""

import re
import json
import time
import threading
import urllib.request
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CHARTS_DIR             = Path(__file__).parent / "sierra_screenshots" / "data" / "charts"
CHARTBOOK_JSON         = Path("/mnt/c/Users/Quantum/Desktop/projects/CV-Sierra/chartbook_structure.json")
SCANNER_API            = "http://127.0.0.1:5015"
TECHNICAL_ANALYSIS_FILE = Path("/tmp/sierra_analysis.json")
PORT = 5050

# Dashboard HTML cache — avoids slow /mnt/c/ filesystem scans on every request
_DASHBOARD_CACHE: dict = {"html": None, "ts": 0.0, "lock": threading.Lock()}
_DASHBOARD_TTL = 30  # seconds


def _get_cached_dashboard() -> str:
    """Return cached dashboard HTML, rebuilding if stale (>30s)."""
    with _DASHBOARD_CACHE["lock"]:
        if _DASHBOARD_CACHE["html"] and (time.time() - _DASHBOARD_CACHE["ts"]) < _DASHBOARD_TTL:
            return _DASHBOARD_CACHE["html"]
    html = _build_dashboard()
    with _DASHBOARD_CACHE["lock"]:
        _DASHBOARD_CACHE["html"] = html
        _DASHBOARD_CACHE["ts"]   = time.time()
    return html


# ──────────────────────────────────────────────────────────────────────────────
# Data helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_filename(fname: str) -> dict:
    info = {"timeframe": "Unknown", "timestamp": None, "contract": None}
    for tf in ["Daily", "Weekly", "Monthly", "Yearly", "Intraday"]:
        if tf.lower() in fname.lower():
            info["timeframe"] = tf
            break
    m = re.search(r'([A-Z]{2,5}[A-Z]\d{2})-', fname)
    if m:
        info["contract"] = m.group(1)
    m = re.search(r'_(\d{6})\.png$', fname, re.IGNORECASE)
    if m:
        ts = m.group(1)
        try:
            info["timestamp"] = f"{ts[:2]}:{ts[2:4]}:{ts[4:6]}"
        except Exception:
            pass
    m = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{6})', fname)
    if m:
        ts = m.group(2)
        try:
            info["timestamp"] = f"{m.group(1)} {ts[:2]}:{ts[2:4]}:{ts[4:6]}"
        except Exception:
            pass
    return info


def _collect_symbol_data() -> list:
    symbols = []
    if not CHARTS_DIR.exists():
        return symbols
    for symbol_dir in sorted(CHARTS_DIR.iterdir()):
        if not symbol_dir.is_dir():
            continue
        files = sorted(
            list(symbol_dir.glob("*.png")) + list(symbol_dir.glob("*.jpg")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            continue
        latest = files[0]
        parsed = _parse_filename(latest.name)
        mtime  = datetime.fromtimestamp(latest.stat().st_mtime)
        timeframes = {_parse_filename(f.name)["timeframe"] for f in files}
        contracts  = {_parse_filename(f.name)["contract"]  for f in files
                      if _parse_filename(f.name)["contract"]}
        symbols.append({
            "symbol":      symbol_dir.name,
            "file_count":  len(files),
            "latest_mtime": mtime.strftime("%Y-%m-%d %H:%M"),
            "timeframes":  sorted(t for t in timeframes if t != "Unknown"),
            "contracts":   sorted(contracts),
            "latest_timestamp": parsed.get("timestamp"),
        })
    return symbols


def _load_chartbook_structure() -> dict:
    if CHARTBOOK_JSON.exists():
        try:
            with open(CHARTBOOK_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _trend_from_ind(ind: dict) -> float:
    ema9 = ind.get("ema_9"); sma50 = ind.get("sma_50")
    if ema9 and sma50 and sma50 > 0:
        return max(-1.0, min(1.0, (ema9 - sma50) / sma50 * 20))
    return 0.0


def _momentum_from_ind(ind: dict) -> float:
    rsi  = ind.get("rsi_14", 50)
    hist = ind.get("macd_hist", 0) or 0
    return max(-1.0, min(1.0, (rsi - 50) / 50 * 0.6 + (1.0 if hist > 0 else -1.0 if hist < 0 else 0.0) * 0.4))


def _fetch_analysis() -> dict:
    """Load technical analysis: prefer /tmp/sierra_analysis.json, fallback to port 5015 CV."""
    result = {"available": False, "status": None, "recommendations": {}, "source": None, "raw": {}}

    if TECHNICAL_ANALYSIS_FILE.exists():
        try:
            data = json.loads(TECHNICAL_ANALYSIS_FILE.read_text())
            syms = data.get("symbols", {})
            if syms:
                result["available"] = True
                result["source"]    = "technical"
                result["raw"]       = data
                result["status"] = {
                    "scan_count":  data.get("symbols_analyzed", 0),
                    "last_scan":   data.get("timestamp", "")[:19],
                    "summary":     data.get("summary", {}),
                }
                for sym, a in syms.items():
                    ind  = a.get("indicators", {})
                    risk = a.get("risk", {})
                    preds = a.get("predictions", {})
                    result["recommendations"][sym] = {
                        "symbol":      sym,
                        "name":        a.get("name", sym),
                        "category":    a.get("category", ""),
                        "signal":      a.get("signal", "HOLD"),
                        "confidence":  a.get("confidence", 0.5),
                        "score":       a.get("score", 0),
                        "risk_reward": risk.get("risk_reward", 0),
                        "trend":       _trend_from_ind(ind),
                        "momentum":    _momentum_from_ind(ind),
                        "last_close":  a.get("last_close"),
                        "last_date":   a.get("last_date", ""),
                        "pct_chg_5d":  risk.get("pct_change_5d", 0),
                        "indicators":  ind,
                        "risk":        risk,
                        "reasons":     a.get("reasons", []),
                        "predictions": preds,
                    }
        except Exception:
            pass

    if not result["available"]:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(f"{SCANNER_API}/api/sierra-scanner/recommendations",
                                           headers={"Accept": "application/json"}), timeout=2) as r:
                d = json.loads(r.read())
                if d.get("recommendations"):
                    result.update(available=True, source="cv_scanner",
                                  recommendations=d["recommendations"])
        except Exception:
            pass

    return result


# ──────────────────────────────────────────────────────────────────────────────
# HTML builders
# ──────────────────────────────────────────────────────────────────────────────

_SIG_COLORS = {
    "Strong Bullish": ("#00e676", "rgba(0,230,118,.15)",  "rgba(0,230,118,.50)"),
    "Bullish":        ("#00c853", "rgba(0,200,83,.10)",   "rgba(0,200,83,.35)"),
    "Neutral":        ("#8899aa", "rgba(136,153,170,.06)", "rgba(136,153,170,.20)"),
    "Bearish":        ("#ff7043", "rgba(255,112,67,.10)",  "rgba(255,112,67,.35)"),
    "Strong Bearish": ("#ff5252", "rgba(255,82,82,.15)",   "rgba(255,82,82,.50)"),
    # Legacy fallbacks
    "BUY":  ("#00c853", "rgba(0,200,83,.10)",   "rgba(0,200,83,.35)"),
    "SELL": ("#ff5252", "rgba(255,82,82,.10)",   "rgba(255,82,82,.35)"),
    "HOLD": ("#8899aa", "rgba(136,153,170,.06)", "rgba(136,153,170,.20)"),
}

def _sig_td(sig, conf=None):
    """Return a full <td> with flat text, coloured background and left-border accent."""
    c, bg, brd = _SIG_COLORS.get(sig, _SIG_COLORS["Neutral"])
    pct = f"<br><span style='font-size:10px;opacity:.65'>{int(conf*100)}%</span>" if conf is not None else ""
    return (
        f'<td style="background:{bg};border-left:2px solid {brd};'
        f'text-align:center;padding:6px 10px;white-space:nowrap">'
        f'<span style="font-weight:700;font-size:13px;letter-spacing:.5px;color:{c}">{sig}</span>'
        f'{pct}</td>'
    )

def _sig_badge(sig, conf=None):
    """Legacy helper — delegates to _sig_td content (used inline)."""
    c, bg, brd = _SIG_COLORS.get(sig, _SIG_COLORS["Neutral"])
    pct = f"<br><span style='font-size:10px;opacity:.65'>{int(conf*100)}%</span>" if conf is not None else ""
    return (
        f'<span style="font-weight:700;font-size:13px;letter-spacing:.5px;color:{c}">{sig}</span>'
        f'{pct}'
    )


def _tier(score: int, signal: str) -> int:
    """Return sort tier: 0=Strong Bullish … 4=Strong Bearish."""
    if score >= 4:   return 0  # Strong Bullish
    if score >= 1:   return 1  # Bullish
    if score == 0:   return 2  # Neutral
    if score >= -3:  return 3  # Bearish
    return 4                   # Strong Bearish

_TIER_META = {
    0: ("STRONG BULLISH",  "#00e676", "rgba(0,230,118,.08)",  "rgba(0,230,118,.5)"),
    4: ("STRONG BEARISH",  "#ff5252", "rgba(255,82,82,.08)",  "rgba(255,82,82,.5)"),
    1: ("BULLISH",         "#00c853", "rgba(0,200,83,.06)",   "rgba(0,200,83,.4)"),
    2: ("NEUTRAL",         "#5a7090", "rgba(90,112,144,.06)", "rgba(90,112,144,.3)"),
    3: ("BEARISH",         "#ff7043", "rgba(255,112,67,.06)", "rgba(255,112,67,.4)"),
}
# Display order: Strong Bullish, Strong Bearish, Bullish, Neutral, Bearish
_DISPLAY_ORDER = {0: 0, 4: 1, 1: 2, 2: 3, 3: 4}


def _build_predictions_table(scanner: dict) -> str:
    recs = scanner.get("recommendations", {})
    if not recs:
        return ""

    # Sort: Strong Bullish, Strong Bearish, Bullish, Neutral, Bearish — then score desc within tier
    items = sorted(
        recs.values(),
        key=lambda x: (_DISPLAY_ORDER[_tier(x.get("score", 0), x.get("signal", "HOLD"))], -x.get("score", 0))
    )

    rows = []
    current_tier = -1
    for r in items:
        score = r.get("score", 0)
        tier  = _tier(score, r.get("signal", "HOLD"))

        # Insert group divider when tier changes
        if tier != current_tier:
            current_tier = tier
            label, col, bg, border = _TIER_META[tier]
            icon = "▲▲" if tier == 0 else "▲" if tier == 1 else "●" if tier == 2 else "▼" if tier == 3 else "▼▼"
            rows.append(
                f'<tr><td colspan="13" style="background:{bg};border-left:3px solid {border};'
                f'color:{col};font-size:11px;font-weight:700;letter-spacing:2px;'
                f'padding:6px 14px;white-space:nowrap">'
                f'{icon}&nbsp;&nbsp;{label}</td></tr>'
            )

        sym   = r.get("symbol", "")
        cat   = r.get("category", "")
        price = r.get("last_close")
        date  = r.get("last_date", "")[:10]
        pct   = r.get("pct_chg_5d", 0) or 0
        rr    = r.get("risk_reward", 0) or 0
        ind   = r.get("indicators", {})
        rsk   = r.get("risk", {})
        preds = r.get("predictions", {})

        # Tier row accent
        _, row_col, row_bg, _ = _TIER_META[tier]
        row_style = f'style="border-left:3px solid {row_col}33"'

        # Current + multi-timeframe signals
        cur = preds.get("current", {"signal": r.get("signal","Neutral"), "confidence": r.get("confidence",0.5)})
        p24 = preds.get("24h",  {"signal": "—", "confidence": 0})
        p5d = preds.get("5d",   {"signal": "—", "confidence": 0})
        p1m = preds.get("1m",   {"signal": "—", "confidence": 0})

        rsi_val = ind.get("rsi_14")
        rsi_str = f"{rsi_val:.1f}" if rsi_val else "—"
        rsi_col = ("#ff5252" if rsi_val and rsi_val > 65
                   else "#00e676" if rsi_val and rsi_val < 35 else "#c8d8f0")

        macd_h = ind.get("macd_hist", 0) or 0
        macd_str = f"{'▲' if macd_h > 0 else '▼'} {abs(macd_h):.4f}" if macd_h != 0 else "—"
        macd_col = "#00e676" if macd_h > 0 else "#ff5252" if macd_h < 0 else "#5a7090"

        bb_pct = ind.get("bb_pct", 0.5) or 0.5
        bb_str = f"{bb_pct:.0%}"
        bb_col = ("#ff5252" if bb_pct > 0.85 else "#00e676" if bb_pct < 0.15 else "#c8d8f0")

        price_str = f"{price:.4f}" if price else "—"
        pct_col = "#00e676" if pct > 0 else "#ff5252" if pct < 0 else "#c8d8f0"
        pct_str = f"{'▲' if pct > 0 else '▼'}{abs(pct):.2f}%" if pct != 0 else "—"

        stop   = rsk.get("stop_loss")
        target = rsk.get("target")
        stop_str   = f"{stop:.4f}"   if stop   else "—"
        target_str = f"{target:.4f}" if target else "—"

        reasons = r.get("reasons", [])[:3]
        reason_str = " · ".join(reasons) if reasons else ""

        # Score bar: 8 dots, filled relative to |score|/8
        score_abs = min(abs(score), 8)
        filled = "●" * score_abs + "○" * (8 - score_abs)
        score_col = row_col

        sig_src = r.get("signal_source", "technical")
        src_badge = ('<span style="font-size:9px;background:rgba(0,212,255,.12);'
                     'border:1px solid rgba(0,212,255,.3);color:#00d4ff;border-radius:8px;'
                     'padding:1px 5px;margin-left:4px">AI</span>'
                     if sig_src == "ai_vision" else "")

        rows.append(f"""<tr {row_style}>
  <td><div style="font-weight:700;color:#a0d0ff;font-size:15px">{sym.split('-')[0]}{src_badge}</div>
      <div style="font-size:11px;color:#5a7090">{cat}</div>
      <div style="font-size:10px;color:{score_col};letter-spacing:0;margin-top:3px">{filled}</div>
      <div style="font-size:10px;color:#3a5070;margin-top:1px">{date}</div></td>
  <td style="color:{pct_col};font-weight:600">{price_str}<br><span style="font-size:11px">{pct_str}</span></td>
  {_sig_td(cur['signal'], cur.get('confidence'))}
  {_sig_td(p24['signal'], p24.get('confidence')) if p24['signal'] != '—' else '<td style="text-align:center;color:#3a5070">—</td>'}
  {_sig_td(p5d['signal'], p5d.get('confidence')) if p5d['signal'] != '—' else '<td style="text-align:center;color:#3a5070">—</td>'}
  {_sig_td(p1m['signal'], p1m.get('confidence')) if p1m['signal'] != '—' else '<td style="text-align:center;color:#3a5070">—</td>'}
  <td style="color:{rsi_col};font-weight:600">{rsi_str}</td>
  <td style="color:{macd_col};font-size:11px">{macd_str}</td>
  <td style="color:{bb_col};font-size:11px">{bb_str}</td>
  <td style="color:#FFD700;font-weight:600">{rr:.1f}x</td>
  <td style="font-size:10px;color:#3a5070;max-width:150px">{stop_str}<br><span style="color:#00e676">{target_str}</span></td>
  <td style="font-size:10px;color:#5a7090;max-width:200px">{reason_str}</td>
</tr>""")

    source_label = scanner.get("source", "")
    status = scanner.get("status", {})
    summary = status.get("summary", {}) if status else {}
    last_scan = status.get("last_scan", "—") if status else "—"
    n_syms  = len(recs)
    strong_bull_n = summary.get("Strong Bullish", summary.get("BUY", 0))
    bull_n        = summary.get("Bullish", 0)
    neutral_n     = summary.get("Neutral", summary.get("HOLD", 0))
    bear_n        = summary.get("Bearish", 0)
    strong_bear_n = summary.get("Strong Bearish", summary.get("SELL", 0))

    src_label = "Real Technical Analysis (OHLCV)" if source_label == "technical" else "CV Scanner (screenshot-based)"

    return f"""
<section>
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px">
    <h2>MULTI-TIMEFRAME PREDICTIONS — {n_syms} Instruments</h2>
    <div style="font-size:11px;color:#3a5070">Source: {src_label} · Updated: {last_scan}</div>
  </div>
  <div style="display:flex;gap:16px;margin-bottom:12px">
    <div class="stat-chip" style="color:#00e676;border-color:#00e67644">{strong_bull_n} Strong Bullish</div>
    <div class="stat-chip" style="color:#00c853;border-color:#00c85344">{bull_n} Bullish</div>
    <div class="stat-chip" style="color:#8899aa;border-color:#8899aa44">{neutral_n} Neutral</div>
    <div class="stat-chip" style="color:#ff7043;border-color:#ff704344">{bear_n} Bearish</div>
    <div class="stat-chip" style="color:#ff5252;border-color:#ff525244">{strong_bear_n} Strong Bearish</div>
  </div>
  <div style="overflow-x:auto">
    <table class="data-table">
      <thead>
        <tr>
          <th>Symbol · Strength</th>
          <th>Price · 5d Δ</th>
          <th>NOW</th>
          <th>24 Hours</th>
          <th>5 Days</th>
          <th>1 Month</th>
          <th>RSI</th>
          <th>MACD</th>
          <th>BB%</th>
          <th>R/R</th>
          <th>Stop / Target</th>
          <th>Key Signals</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>"""


def _build_chartbook_section(cb_data: dict) -> str:
    if not cb_data or "chartbooks" not in cb_data:
        return ""
    rows = []
    for cb_num, charts in sorted(cb_data["chartbooks"].items(), key=lambda x: int(x[0])):
        for chart in charts:
            if not chart.get("visible", True):
                continue
            title = chart.get("title", "")
            clean = re.sub(r'^#\d+\s+\S+\s+', '', title)
            clean = re.sub(r'\[C\]\[M\]\s*', '', clean)
            rows.append(f"""<tr>
  <td style="color:#FFD700;font-weight:700">CB{cb_num}</td>
  <td style="color:#FFD700">#{chart.get('position','')}</td>
  <td style="color:#a0d0ff;font-weight:600">{chart.get('symbol','')}</td>
  <td style="color:#5a7090;font-size:11px">{chart.get('timeframe','')}</td>
  <td style="color:#7a90a8;font-size:11px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{title}">{clean[:80]}</td>
</tr>""")
    ts = cb_data.get("timestamp", "")
    total = cb_data.get("total_charts", 0)
    return f"""
<section>
  <h2>SIERRA CHART STRUCTURE — {total} Charts</h2>
  <div style="font-size:11px;color:#3a5070;margin-bottom:8px">Snapshot: {ts}</div>
  <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr><th>Book</th><th>Chart</th><th>Symbol</th><th>Timeframe</th><th>Description</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>"""


def _build_files_section(symbols: list) -> str:
    if not symbols:
        return ""
    total = sum(s["file_count"] for s in symbols)
    rows = []
    for s in symbols:
        tfs  = ", ".join(s["timeframes"][:4]) or "—"
        cons = ", ".join(s["contracts"][:3]) or "—"
        ts   = s.get("latest_timestamp") or s.get("latest_mtime", "—")
        rows.append(f"""<tr>
  <td style="color:#a0d0ff;font-weight:700">{s['symbol']}</td>
  <td style="color:#7ab0d0;font-size:11px">{cons}</td>
  <td style="color:#5a7090;font-size:11px">{tfs}</td>
  <td style="color:#FFD700">{s['file_count']}</td>
  <td style="color:#3a5070;font-size:11px">{ts}</td>
</tr>""")
    return f"""
<section>
  <h2>SCREENSHOT LIBRARY — {len(symbols)} Symbols · {total} Files</h2>
  <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr><th>Symbol</th><th>Contracts</th><th>Timeframes</th><th>Count</th><th>Latest</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>"""


def _build_dashboard() -> str:
    scanner = _fetch_analysis()
    cb_data = _load_chartbook_structure()
    syms    = _collect_symbol_data()

    if scanner["available"]:
        status = scanner.get("status", {}) or {}
        sc_class  = "badge-on"
        sc_label  = f"● LIVE — {len(scanner['recommendations'])} instruments"
        scan_count = str(status.get("scan_count", "—"))
        last_scan  = (status.get("last_scan", "") or "")[:19]
        src        = scanner.get("source", "")
        src_str    = "Technical" if src == "technical" else "CV Scanner"
    else:
        sc_class = "badge-off"
        sc_label = "○ OFFLINE — run: python3 sierra_data_analyzer.py"
        scan_count = "—"
        last_scan  = "—"
        src_str    = "—"

    total_screenshots = sum(s["file_count"] for s in syms)

    # Pre-compute signal counts (avoid {{{} }} in f-string)
    _summary         = (scanner.get("status") or {}).get("summary") or {}
    strong_bull_cnt  = _summary.get("Strong Bullish", _summary.get("BUY",  0))
    bull_cnt         = _summary.get("Bullish",  0)
    neutral_cnt      = _summary.get("Neutral",  _summary.get("HOLD", 0))
    bear_cnt         = _summary.get("Bearish",  0)
    strong_bear_cnt  = _summary.get("Strong Bearish", _summary.get("SELL", 0))

    predictions_section = _build_predictions_table(scanner)
    chartbook_section   = _build_chartbook_section(cb_data)
    files_section       = _build_files_section(syms)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>Sierra Intelligence · Spartan</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  :root {{
    --bg:        #060c18;
    --bg2:       #0a1220;
    --bg3:       #0d1930;
    --card:      #091528;
    --border:    #1a3050;
    --gold:      #FFD700;
    --gold2:     #e6c200;
    --cyan:      #00d4ff;
    --green:     #00e676;
    --red:       #ff4444;
    --text:      #c8d8f0;
    --text2:     #7a90b0;
    --text3:     #3a5070;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', monospace;
    font-size: 13px;
    line-height: 1.5;
  }}

  /* ── Header ── */
  header {{
    background: var(--bg2);
    border-bottom: 2px solid rgba(255,215,0,.4);
    padding: 0 28px;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
    box-shadow: 0 2px 20px rgba(0,0,0,.6);
  }}
  .brand {{ display: flex; align-items: center; gap: 16px; }}
  .logo-text {{
    font-size: 20px; font-weight: 700; letter-spacing: 4px;
    color: var(--gold); text-shadow: 0 0 20px rgba(255,215,0,.4);
  }}
  .logo-sep {{ color: var(--text3); }}
  .logo-sub {{ font-size: 12px; font-weight: 500; letter-spacing: 2px; color: var(--text2); }}
  .header-right {{ display: flex; align-items: center; gap: 12px; }}
  .badge-on  {{
    padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;
    background: rgba(0,230,118,.12); border: 1px solid rgba(0,230,118,.35); color: var(--green);
  }}
  .badge-off {{
    padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;
    background: rgba(255,68,68,.10); border: 1px solid rgba(255,68,68,.3); color: var(--red);
  }}
  .ts-badge {{ font-size: 11px; color: var(--text3); }}

  /* ── Stats bar ── */
  .stats-bar {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 10px 28px;
    display: flex; gap: 24px; align-items: center; flex-wrap: wrap;
  }}
  .stat {{ display: flex; align-items: baseline; gap: 6px; }}
  .stat-n {{ font-size: 20px; font-weight: 700; color: var(--gold); }}
  .stat-l {{ font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; }}
  .stat-div {{ width: 1px; height: 28px; background: var(--border); }}

  /* ── Sections ── */
  section {{
    padding: 20px 28px;
    border-bottom: 1px solid var(--border);
  }}
  h2 {{
    font-size: 11px; font-weight: 600; color: var(--gold);
    text-transform: uppercase; letter-spacing: 3px;
    margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
  }}
  h2::before {{
    content: ''; display: inline-block; width: 3px; height: 14px;
    background: var(--gold); border-radius: 2px;
  }}

  /* ── Data Table ── */
  .data-table {{
    width: 100%; border-collapse: collapse;
    background: var(--card);
    border-radius: 8px; overflow: hidden;
  }}
  .data-table thead tr {{
    background: rgba(255,215,0,.06);
    border-bottom: 1px solid rgba(255,215,0,.15);
  }}
  .data-table th {{
    padding: 8px 10px;
    text-align: left;
    font-size: 10px; font-weight: 600; color: var(--text3);
    text-transform: uppercase; letter-spacing: 1px;
    white-space: nowrap;
    border-right: 1px solid rgba(255,255,255,.06);
    border-bottom: 1px solid rgba(255,255,255,.08);
  }}
  .data-table th:last-child {{ border-right: none; }}
  .data-table td {{
    padding: 10px 10px;
    border-bottom: 1px solid rgba(255,255,255,.05);
    border-right: 1px solid rgba(255,255,255,.04);
    vertical-align: middle;
  }}
  .data-table td:last-child {{ border-right: none; }}
  .data-table tbody tr:hover td {{
    background: rgba(0,212,255,.04);
  }}
  .data-table tbody tr:last-child td {{ border-bottom: none; }}

  .stat-chip {{
    display: inline-block; padding: 3px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 700; letter-spacing: 1px;
    background: rgba(255,255,255,.04); border: 1px solid;
  }}
</style>
</head>
<body>

<header>
  <div class="brand">
    <img src="/Spartan_logo.png" alt="Spartan" style="height:38px;width:auto;object-fit:contain;filter:drop-shadow(0 0 6px rgba(255,215,0,.35))">
    <div class="logo-sep">|</div>
    <div class="logo-sub">SIERRA INTELLIGENCE</div>
  </div>
  <div class="header-right">
    <div class="ts-badge">Source: {src_str}</div>
    <div class="{sc_class}">{sc_label}</div>
    <div class="ts-badge" id="ts">{datetime.now().strftime('%H:%M:%S')}</div>
  </div>
</header>

<div class="stats-bar">
  <div class="stat"><div class="stat-n">{len(scanner.get('recommendations', {}))}</div><div class="stat-l">Instruments</div></div>
  <div class="stat-div"></div>
  <div class="stat"><div class="stat-n" style="color:#00e676">{strong_bull_cnt}</div><div class="stat-l">Strong Bullish</div></div>
  <div class="stat"><div class="stat-n" style="color:#00c853">{bull_cnt}</div><div class="stat-l">Bullish</div></div>
  <div class="stat"><div class="stat-n" style="color:#8899aa">{neutral_cnt}</div><div class="stat-l">Neutral</div></div>
  <div class="stat"><div class="stat-n" style="color:#ff7043">{bear_cnt}</div><div class="stat-l">Bearish</div></div>
  <div class="stat"><div class="stat-n" style="color:#ff5252">{strong_bear_cnt}</div><div class="stat-l">Strong Bearish</div></div>
  <div class="stat-div"></div>
  <div class="stat"><div class="stat-n">{total_screenshots}</div><div class="stat-l">Screenshots</div></div>
  <div class="stat-div"></div>
  <div class="stat"><div class="stat-n" style="font-size:14px">{last_scan or '—'}</div><div class="stat-l">Last Update</div></div>
</div>

{predictions_section}

{chartbook_section}

{files_section}

<script>
(function() {{
  var fmt = new Intl.DateTimeFormat('en-US', {{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}});
  setInterval(function() {{
    var el = document.getElementById('ts');
    if (el) el.textContent = fmt.format(new Date());
  }}, 1000);
}})();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# HTTP Server
# ──────────────────────────────────────────────────────────────────────────────

class SierraHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = _get_cached_dashboard().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/status":
            scanner = _fetch_analysis()
            syms    = _collect_symbol_data()
            self._json({
                "service":    "sierra-intelligence",
                "port":       PORT,
                "available":  scanner["available"],
                "source":     scanner.get("source"),
                "symbols":    len(scanner.get("recommendations", {})),
                "screenshots": sum(s["file_count"] for s in syms),
                "timestamp":  datetime.now().isoformat(),
            })

        elif path == "/api/analysis":
            scanner = _fetch_analysis()
            self._json(scanner.get("recommendations", {}))

        elif path == "/health":
            self._json({"status": "ok", "service": "sierra-intelligence", "port": PORT})

        elif path == "/Spartan_logo.png":
            logo = Path(__file__).parent / "Spartan_logo.png"
            if logo.exists():
                data = logo.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)

        else:
            self.send_error(404)

    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Sierra Intelligence Dashboard  →  http://localhost:{PORT}")
    print(f"  Analysis file : {TECHNICAL_ANALYSIS_FILE}")
    print(f"  Charts dir    : {CHARTS_DIR}")
    print(f"  Chartbook     : {CHARTBOOK_JSON}")
    server = ThreadingHTTPServer(("", PORT), SierraHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
