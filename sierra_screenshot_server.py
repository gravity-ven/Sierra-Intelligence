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
POLYGON_DATA_FILE       = Path("/tmp/sierra_polygon_data.json")
CRYPTO_STATE_FILE       = Path.home() / ".spartan_crypto_state.json"
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
    result = {"available": False, "analyzer_running": False, "status": None, "recommendations": {}, "source": None, "raw": {}}

    if TECHNICAL_ANALYSIS_FILE.exists():
        result["analyzer_running"] = True  # file written by analyzer → it's alive
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


_MICRO_TO_COT = {"MES": "ES", "MNQ": "NQ", "MCL": "CL", "MGC": "GC", "MSI": "SI",
                  "M2K": "RTY", "MYM": "YM"}

def _cot_root(sym: str) -> str:
    """Strip month-code + 2-digit year suffix to get COT root symbol."""
    import re
    m = re.match(r'^(.+?)[FGHJKMNQUVXZ]\d{2}$', sym)
    root = m.group(1) if m else sym
    return _MICRO_TO_COT.get(root, root)


def _build_predictions_table(scanner: dict, cot_lookup: dict | None = None) -> str:
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
                f'<tr><td colspan="14" style="background:{bg};border-left:3px solid {border};'
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

        # LW COT lookup
        cot_root = _cot_root(sym.split('-')[0])
        cot = (cot_lookup or {}).get(cot_root)
        if cot:
            lw_sig    = cot.get("signal", "")
            lw_cidx   = cot.get("comm_idx")
            lw_sidx   = cot.get("spec_idx")
            lw_wr     = cot.get("williams_r")
            lw_reason = cot.get("reason", "")
            _lw_colors = {
                "Strong Bullish": "#00e676", "Bullish": "#00c853",
                "Neutral": "#8899aa", "Bearish": "#ff7043", "Strong Bearish": "#ff5252",
            }
            lw_col = _lw_colors.get(lw_sig, "#5a7090")
            lw_icon = {"Strong Bullish": "▲▲", "Bullish": "▲", "Neutral": "●",
                       "Bearish": "▼", "Strong Bearish": "▼▼"}.get(lw_sig, "")
            cidx_bar = (f'<div style="background:rgba(255,255,255,.08);border-radius:3px;height:4px;'
                        f'width:50px;display:inline-block;vertical-align:middle;margin-left:4px">'
                        f'<div style="background:{lw_col};width:{lw_cidx:.0f}%;height:100%;'
                        f'border-radius:3px"></div></div>' if lw_cidx is not None else "")
            cidx_str = f"{lw_cidx:.0f}%{cidx_bar}" if lw_cidx is not None else "—"
            wr_str   = f"{lw_wr:.0f}" if lw_wr is not None else "—"
            wr_col   = "#00e676" if lw_wr is not None and lw_wr < -80 else "#ff5252" if lw_wr is not None and lw_wr > -20 else "#c8d8f0"
            lw_cell = (
                f'<td style="white-space:nowrap;min-width:130px">'
                f'<div style="color:{lw_col};font-weight:700;font-size:12px">{lw_icon} {lw_sig}</div>'
                f'<div style="font-size:10px;color:#8899aa;margin-top:1px">Comm:{cidx_str}</div>'
                f'<div style="font-size:10px;color:{wr_col}">%R:{wr_str}</div>'
                f'<div style="font-size:9px;color:#3a5070;max-width:150px;white-space:normal;margin-top:2px">{lw_reason}</div>'
                f'</td>'
            )
        else:
            lw_cell = '<td style="text-align:center;color:#3a5070;font-size:11px">—<br><span style="font-size:9px">no COT</span></td>'

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
  {lw_cell}
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
          <th>LW COT</th>
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


def _fetch_polygon_data() -> dict:
    """Load latest Polygon.io scan results."""
    if not POLYGON_DATA_FILE.exists():
        return {}
    try:
        return json.loads(POLYGON_DATA_FILE.read_text())
    except Exception:
        return {}


# ── SRS scanner integrations ──────────────────────────────────────────────────

def _fetch_barometers() -> dict:
    """Pull live intermarket barometer data from SRS port 9001."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:9001/api/barometers/latest",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return {}


_YF_FUTURES = {
    "ES": "ES=F", "NQ": "NQ=F", "GC": "GC=F", "SI": "SI=F",
    "CL": "CL=F", "NG": "NG=F", "ZB":  "ZB=F", "ZN":  "ZN=F",
    "EUR": "6E=F", "JPY": "6J=F", "GBP": "6B=F", "AUD": "6A=F",
    "ZC": "ZC=F", "ZS": "ZS=F", "ZW": "ZW=F",
}

def _williams_r(highs, lows, closes, period=14) -> float | None:
    """Williams %R — ranges -100 to 0. <-80 oversold, >-20 overbought."""
    if len(closes) < period:
        return None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    c  = closes[-1]
    if hh == ll:
        return -50.0
    return round(-100.0 * (hh - c) / (hh - ll), 1)


def _fetch_price_indicators(symbols: list[str]) -> dict:
    """Fetch Williams %R for futures via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    yf_tickers = [_YF_FUTURES[s] for s in symbols if s in _YF_FUTURES]
    if not yf_tickers:
        return {}

    result = {}
    try:
        data = yf.download(yf_tickers, period="60d", interval="1d",
                           auto_adjust=True, progress=False)
        for sym in symbols:
            tick = _YF_FUTURES.get(sym)
            if not tick:
                continue
            try:
                if len(yf_tickers) == 1:
                    highs  = data["High"].dropna().tolist()
                    lows   = data["Low"].dropna().tolist()
                    closes = data["Close"].dropna().tolist()
                else:
                    highs  = data["High"][tick].dropna().tolist()
                    lows   = data["Low"][tick].dropna().tolist()
                    closes = data["Close"][tick].dropna().tolist()
                wr = _williams_r(highs, lows, closes, 14)
                result[sym] = {"williams_r": wr}
            except Exception:
                pass
    except Exception:
        pass
    return result


def _lw_signal(comm_idx: float | None, spec_idx: float | None,
               comm_net: int, wr: float | None) -> tuple[str, str]:
    """
    Larry Williams COT signal combining:
    - Commercial Index (smart money positioning)
    - Large Spec Index (contrarian — fade when extreme)
    - Williams %R (price momentum confirmation)
    Returns (signal, reason).
    """
    if comm_idx is None:
        return "No Data", ""

    # Core LW rule: commercials are the benchmark
    if comm_idx >= 90:
        if spec_idx is not None and spec_idx <= 25:
            sig = "Strong Bullish"
            why = f"Comm {comm_idx:.0f}% · Spec {spec_idx:.0f}% (divergence)"
        elif wr is not None and wr < -60:
            sig = "Bullish"
            why = f"Comm {comm_idx:.0f}% · %R oversold {wr:.0f}"
        else:
            sig = "Bullish"
            why = f"Comm {comm_idx:.0f}% — commercials at extreme long"
    elif comm_idx >= 70:
        sig = "Bullish"
        why = f"Comm {comm_idx:.0f}% — smart money net long"
    elif comm_idx <= 10:
        if spec_idx is not None and spec_idx >= 75:
            sig = "Strong Bearish"
            why = f"Comm {comm_idx:.0f}% · Spec {spec_idx:.0f}% (divergence)"
        elif wr is not None and wr > -40:
            sig = "Bearish"
            why = f"Comm {comm_idx:.0f}% · %R overbought {wr:.0f}"
        else:
            sig = "Bearish"
            why = f"Comm {comm_idx:.0f}% — commercials at extreme short"
    elif comm_idx <= 30:
        sig = "Bearish"
        why = f"Comm {comm_idx:.0f}% — smart money net short"
    else:
        sig = "Neutral"
        why = f"Comm {comm_idx:.0f}% — no extreme"

    return sig, why


def _fetch_cot_data() -> list:
    """Pull COT + LW indicators for key futures markets."""
    import sys
    sys.path.insert(0, "/Users/spartan")

    markets = [
        ("ES", "E-mini S&P 500"), ("NQ", "E-mini NASDAQ"), ("GC", "Gold"),
        ("SI", "Silver"),         ("CL", "Crude Oil"),      ("NG", "Nat Gas"),
        ("ZB", "T-Bond 30Y"),     ("ZN", "T-Note 10Y"),    ("EUR", "Euro FX"),
        ("JPY", "Japanese Yen"),  ("GBP", "British Pound"), ("AUD", "Aussie"),
        ("ZC", "Corn"),           ("ZS", "Soybeans"),       ("ZW", "Wheat"),
    ]
    rows = []
    syms = [m[0] for m in markets]

    # Fetch Williams %R prices in one batch call
    price_ind = _fetch_price_indicators(syms)

    try:
        from cot_central_engine import get_latest_cot, get_cot_index, get_spec_index
        for sym, name in markets:
            cot      = get_latest_cot(sym)
            comm_idx = get_cot_index(sym, lookback=156)   # LW uses 3-year (156 weeks)
            spec_idx = get_spec_index(sym, lookback=156)
            if not cot:
                continue
            comm_net  = int(cot.get("comm_net", 0) or 0)
            spec_net  = int(cot.get("spec_net", 0) or 0)
            small_net = int(cot.get("small_net", 0) or 0)
            oi        = int(cot.get("open_interest", 0) or 0)
            date      = cot.get("date", "")
            wr        = price_ind.get(sym, {}).get("williams_r")
            signal, reason = _lw_signal(comm_idx, spec_idx, comm_net, wr)
            rows.append({
                "symbol":    sym,
                "name":      name,
                "comm_net":  comm_net,
                "spec_net":  spec_net,
                "small_net": small_net,
                "oi":        oi,
                "comm_idx":  comm_idx,
                "spec_idx":  spec_idx,
                "williams_r": wr,
                "signal":    signal,
                "reason":    reason,
                "date":      date,
            })
    except Exception:
        pass

    # Sort: Strong Bullish → Bullish → Neutral → Bearish → Strong Bearish
    order = {"Strong Bullish": 0, "Bullish": 1, "Neutral": 2, "Bearish": 3, "Strong Bearish": 4, "No Data": 5}
    rows.sort(key=lambda r: order.get(r["signal"], 5))
    return rows


def _build_barometers_section(baro: dict) -> str:
    if not baro or "barometers" not in baro:
        return ""
    composite = baro.get("composite_score", 0)
    risk_label = baro.get("risk_label", "—")
    bars = baro.get("barometers", [])

    # composite colour
    if composite >= 65:
        comp_col, comp_label = "#00e676", "RISK-ON"
    elif composite <= 35:
        comp_col, comp_label = "#ff4444", "RISK-OFF"
    else:
        comp_col, comp_label = "#FFD700", "NEUTRAL"

    rows = []
    tier_order = ["Tier 1 (6-18mo)", "Tier 2 (3-6mo)", "Tier 3 (1-3mo)"]
    by_tier: dict = {}
    for b in bars:
        t = b.get("tier", "Other")
        by_tier.setdefault(t, []).append(b)

    for tier in tier_order:
        items = by_tier.get(tier, [])
        if not items:
            continue
        rows.append(f'<tr><td colspan="4" style="background:rgba(255,215,0,.04);'
                    f'color:#FFD700;font-size:10px;font-weight:700;letter-spacing:2px;'
                    f'padding:6px 10px;border-left:3px solid rgba(255,215,0,.4)">'
                    f'{tier}</td></tr>')
        for b in items:
            name = b.get("name", "")
            val  = b.get("value", "")
            sig  = b.get("signal", "")
            val_str = f"{val:.4g}" if isinstance(val, float) else str(val)
            sig_col = ("#00e676" if "bull" in sig.lower() or sig == "Risk-On"
                       else "#ff4444" if "bear" in sig.lower() or sig == "Risk-Off"
                       else "#7a90b0")
            rows.append(
                f'<tr>'
                f'<td style="color:#a0d0ff;font-weight:600">{name}</td>'
                f'<td style="color:#c8d8f0">{val_str}</td>'
                f'<td style="color:{sig_col};font-weight:600">{sig or "—"}</td>'
                f'<td style="color:#3a5070;font-size:11px">{tier.split("(")[1].rstrip(")")}</td>'
                f'</tr>'
            )

    # Gauge bar for composite score
    bar_w = max(0, min(100, composite))
    gauge = (
        f'<div style="background:rgba(255,255,255,.08);border-radius:6px;height:8px;width:200px;display:inline-block;vertical-align:middle;margin-left:12px">'
        f'<div style="background:{comp_col};width:{bar_w}%;height:100%;border-radius:6px"></div></div>'
    )

    return f"""
<section>
  <h2>INTERMARKET BAROMETERS — SRS RISK ENGINE</h2>
  <div style="display:flex;align-items:center;gap:20px;margin-bottom:16px;flex-wrap:wrap">
    <div class="stat"><div class="stat-n" style="color:{comp_col};font-size:28px">{composite}</div><div class="stat-l">Composite Score</div></div>
    <div class="stat"><div class="stat-n" style="color:{comp_col}">{comp_label}</div><div class="stat-l">Regime</div></div>
    <div style="flex:1">{gauge}</div>
    <div class="stat"><div class="stat-n" style="color:{comp_col}">{risk_label}</div><div class="stat-l">SRS Label</div></div>
  </div>
  <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr><th>Indicator</th><th>Value</th><th>Signal</th><th>Lead Time</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>"""


def _idx_bar(pct: float | None, color: str, width: int = 80) -> str:
    if pct is None:
        return ""
    bar_w = max(0, min(100, pct))
    return (f'<div style="background:rgba(255,255,255,.08);border-radius:3px;height:5px;'
            f'width:{width}px;display:inline-block;vertical-align:middle;margin-left:5px">'
            f'<div style="background:{color};width:{bar_w}%;height:100%;border-radius:3px"></div></div>')


def _build_cot_section(cot_rows: list) -> str:
    if not cot_rows:
        return ""

    sig_meta = {
        "Strong Bullish": ("#00e676", "rgba(0,230,118,.08)", "rgba(0,230,118,.5)"),
        "Bullish":        ("#00c853", "rgba(0,200,83,.06)",  "rgba(0,200,83,.4)"),
        "Neutral":        ("#5a7090", "rgba(90,112,144,.04)","rgba(90,112,144,.3)"),
        "Bearish":        ("#ff7043", "rgba(255,112,67,.06)","rgba(255,112,67,.4)"),
        "Strong Bearish": ("#ff5252", "rgba(255,82,82,.08)", "rgba(255,82,82,.5)"),
        "No Data":        ("#3a5070", "rgba(0,0,0,0)",       "rgba(58,80,112,.3)"),
    }

    # Summary counts
    counts = {k: 0 for k in sig_meta}
    for r in cot_rows:
        counts[r.get("signal", "No Data")] = counts.get(r.get("signal", "No Data"), 0) + 1

    rows = []
    prev_sig = None
    for r in cot_rows:
        sym       = r["symbol"]
        name      = r["name"]
        comm_net  = r["comm_net"]
        spec_net  = r["spec_net"]
        small_net = r["small_net"]
        oi        = r["oi"]
        comm_idx  = r.get("comm_idx")
        spec_idx  = r.get("spec_idx")
        wr        = r.get("williams_r")
        signal    = r.get("signal", "Neutral")
        reason    = r.get("reason", "")
        date      = r["date"]

        col, bg, brd = sig_meta.get(signal, sig_meta["Neutral"])

        # Group header when signal changes
        if signal != prev_sig:
            prev_sig = signal
            icon = {"Strong Bullish": "▲▲", "Bullish": "▲", "Neutral": "●",
                    "Bearish": "▼", "Strong Bearish": "▼▼", "No Data": "—"}.get(signal, "")
            rows.append(
                f'<tr><td colspan="9" style="background:{bg};border-left:3px solid {brd};'
                f'color:{col};font-size:10px;font-weight:700;letter-spacing:2px;'
                f'padding:5px 12px">{icon}&nbsp;&nbsp;{signal.upper()}</td></tr>'
            )

        # Commercial Index bar
        if comm_idx is not None:
            cidx_col = "#00e676" if comm_idx >= 70 else "#ff4444" if comm_idx <= 30 else "#FFD700"
            cidx_str = f"{comm_idx:.0f}%"
            cidx_bar = _idx_bar(comm_idx, cidx_col, 60)
        else:
            cidx_col, cidx_str, cidx_bar = "#3a5070", "—", ""

        # Spec Index bar
        if spec_idx is not None:
            # Spec index is CONTRARIAN: high = specs maxed long = bearish signal
            sidx_col = "#ff4444" if spec_idx >= 70 else "#00e676" if spec_idx <= 30 else "#FFD700"
            sidx_str = f"{spec_idx:.0f}%"
            sidx_bar = _idx_bar(spec_idx, sidx_col, 60)
        else:
            sidx_col, sidx_str, sidx_bar = "#3a5070", "—", ""

        # Williams %R
        if wr is not None:
            wr_col = "#00e676" if wr < -80 else "#ff4444" if wr > -20 else "#c8d8f0"
            wr_str = f"{wr:.0f}"
        else:
            wr_col, wr_str = "#3a5070", "—"

        comm_col  = "#00e676" if comm_net > 0 else "#ff4444"
        spec_col  = "#00e676" if spec_net > 0 else "#ff4444"

        rows.append(
            f'<tr style="border-left:2px solid {brd}">'
            f'<td><span style="color:#FFD700;font-weight:700;font-size:14px">{sym}</span>'
            f'<br><span style="color:#3a5070;font-size:10px">{name}</span></td>'
            f'<td style="color:{col};font-weight:700;white-space:nowrap">'
            f'<span style="font-size:12px">{signal}</span></td>'
            f'<td style="color:{cidx_col};font-weight:700;white-space:nowrap">'
            f'{cidx_str}{cidx_bar}'
            f'<br><span style="font-size:9px;color:#3a5070">LW Comm Idx</span></td>'
            f'<td style="color:{sidx_col};white-space:nowrap">'
            f'{sidx_str}{sidx_bar}'
            f'<br><span style="font-size:9px;color:#3a5070">Spec Idx (contra)</span></td>'
            f'<td style="color:{wr_col};font-weight:600">{wr_str}'
            f'<br><span style="font-size:9px;color:#3a5070">%R</span></td>'
            f'<td style="color:{comm_col};font-weight:600">{comm_net:+,}</td>'
            f'<td style="color:{spec_col};color:#7a90b0">{spec_net:+,}</td>'
            f'<td style="color:#7a90b0">{oi:,}</td>'
            f'<td style="color:#3a5070;font-size:10px;max-width:180px">'
            f'{reason}<br><span style="color:#2a3850">{date}</span></td>'
            f'</tr>'
        )

    sb  = counts.get("Strong Bullish", 0)
    b   = counts.get("Bullish", 0)
    n   = counts.get("Neutral", 0)
    be  = counts.get("Bearish", 0)
    sb2 = counts.get("Strong Bearish", 0)

    # Derive overall BIAS
    total_bull = sb + b
    total_bear = sb2 + be
    if sb >= 3 or (sb > 0 and total_bull >= total_bear * 2):
        bias_label, bias_icon = "STRONG BULLISH BIAS", "▲▲"
        bias_color, bias_bg, bias_border = "#00e676", "rgba(0,230,118,.09)", "rgba(0,230,118,.45)"
    elif total_bull > total_bear:
        bias_label, bias_icon = "BULLISH BIAS", "▲"
        bias_color, bias_bg, bias_border = "#00c853", "rgba(0,200,83,.07)", "rgba(0,200,83,.35)"
    elif sb2 >= 3 or (sb2 > 0 and total_bear >= total_bull * 2):
        bias_label, bias_icon = "STRONG BEARISH BIAS", "▼▼"
        bias_color, bias_bg, bias_border = "#ff5252", "rgba(255,82,82,.09)", "rgba(255,82,82,.45)"
    elif total_bear > total_bull:
        bias_label, bias_icon = "BEARISH BIAS", "▼"
        bias_color, bias_bg, bias_border = "#ff7043", "rgba(255,112,67,.07)", "rgba(255,112,67,.35)"
    else:
        bias_label, bias_icon = "NEUTRAL BIAS", "●"
        bias_color, bias_bg, bias_border = "#8899aa", "rgba(136,153,170,.06)", "rgba(136,153,170,.25)"

    return f"""
<section>
  <h2>COT — LARRY WILLIAMS COMMERCIAL INDEX · {len(cot_rows)} MARKETS</h2>
  <div style="font-size:11px;color:#5a7090;margin-bottom:12px">
    Comm Idx = 3-year Commercial percentile (smart money).  Spec Idx = contrarian (fade extremes).
    %R = Williams %%R 14-period.  &gt;70%% commercial = bullish setup.  &lt;30%% = bearish setup.
  </div>

  <!-- OVERALL BIAS BANNER -->
  <div style="display:flex;align-items:center;gap:24px;background:{bias_bg};border:1px solid {bias_border};border-radius:8px;padding:14px 20px;margin-bottom:14px">
    <div style="font-size:20px;font-weight:900;color:{bias_color};letter-spacing:2px;white-space:nowrap">
      {bias_icon}&nbsp;&nbsp;{bias_label}
    </div>
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-left:auto;align-items:center">
      <div style="text-align:center">
        <div style="font-size:22px;font-weight:800;color:#00e676;line-height:1">{sb}</div>
        <div style="font-size:9px;color:#5a7090;letter-spacing:1px;margin-top:2px">STR BULL</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:22px;font-weight:800;color:#00c853;line-height:1">{b}</div>
        <div style="font-size:9px;color:#5a7090;letter-spacing:1px;margin-top:2px">BULL</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:22px;font-weight:800;color:#8899aa;line-height:1">{n}</div>
        <div style="font-size:9px;color:#5a7090;letter-spacing:1px;margin-top:2px">NEUTRAL</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:22px;font-weight:800;color:#ff7043;line-height:1">{be}</div>
        <div style="font-size:9px;color:#5a7090;letter-spacing:1px;margin-top:2px">BEAR</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:22px;font-weight:800;color:#ff5252;line-height:1">{sb2}</div>
        <div style="font-size:9px;color:#5a7090;letter-spacing:1px;margin-top:2px">STR BEAR</div>
      </div>
    </div>
  </div>

  <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr>
        <th>Contract</th><th>LW Signal</th><th>Comm Index</th>
        <th>Spec Index</th><th>%R</th>
        <th>Comm Net</th><th>Spec Net</th><th>Open Int</th><th>Reason · Date</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>"""


FOREX_PAIRS = [
    # Major pairs
    ("EURUSD=X", "EUR/USD", "Euro / US Dollar"),
    ("GBPUSD=X", "GBP/USD", "British Pound / US Dollar"),
    ("USDJPY=X", "USD/JPY", "US Dollar / Japanese Yen"),
    ("USDCHF=X", "USD/CHF", "US Dollar / Swiss Franc"),
    ("AUDUSD=X", "AUD/USD", "Australian Dollar / US Dollar"),
    ("NZDUSD=X", "NZD/USD", "New Zealand Dollar / US Dollar"),
    ("USDCAD=X", "USD/CAD", "US Dollar / Canadian Dollar"),
    # Cross pairs
    ("EURJPY=X", "EUR/JPY", "Euro / Japanese Yen"),
    ("GBPJPY=X", "GBP/JPY", "British Pound / Japanese Yen"),
    ("EURGBP=X", "EUR/GBP", "Euro / British Pound"),
    ("AUDJPY=X", "AUD/JPY", "Aussie / Japanese Yen"),
    ("EURAUD=X", "EUR/AUD", "Euro / Aussie"),
    ("GBPAUD=X", "GBP/AUD", "British Pound / Aussie"),
    # Dollar index
    ("DX-Y.NYB", "DXY",     "US Dollar Index"),
]


def _fetch_forex_data() -> list:
    """Fetch live forex rates from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return []

    results = []
    tickers = [p[0] for p in FOREX_PAIRS]
    name_map = {p[0]: (p[1], p[2]) for p in FOREX_PAIRS}

    try:
        data = yf.download(tickers, period="5d", interval="1d",
                           auto_adjust=True, progress=False)
        closes = data["Close"]

        for ticker in tickers:
            pair, desc = name_map[ticker]
            try:
                series = closes[ticker].dropna()
                if len(series) < 2:
                    continue
                price    = float(series.iloc[-1])
                prev     = float(series.iloc[-2])
                day_pct  = (price - prev) / prev * 100
                week_pct = (price - float(series.iloc[0])) / float(series.iloc[0]) * 100 if len(series) >= 5 else day_pct
                signal = ("Strong Bullish" if day_pct >= 1.0 else
                          "Bullish"        if day_pct >= 0.2 else
                          "Strong Bearish" if day_pct <= -1.0 else
                          "Bearish"        if day_pct <= -0.2 else "Neutral")
                results.append({
                    "ticker":   ticker,
                    "pair":     pair,
                    "desc":     desc,
                    "price":    round(price, 5),
                    "day_pct":  round(day_pct, 3),
                    "week_pct": round(week_pct, 3),
                    "signal":   signal,
                })
            except Exception:
                continue
    except Exception:
        pass

    results.sort(key=lambda x: x["day_pct"], reverse=True)
    return results


def _build_forex_section(forex: list) -> str:
    if not forex:
        return '<section><h2>FOREX — Loading...</h2><p style="color:#3a5070;padding:20px">yfinance data not available</p></section>'

    now = datetime.now().strftime("%H:%M:%S")
    bullish  = [f for f in forex if "Bullish" in f["signal"]]
    bearish  = [f for f in forex if "Bearish" in f["signal"]]
    neutral  = [f for f in forex if f["signal"] == "Neutral"]

    rows = []
    for f in forex:
        sig      = f["signal"]
        day_pct  = f["day_pct"]
        week_pct = f["week_pct"]
        price    = f["price"]
        arrow    = "▲" if day_pct >= 0 else "▼"
        warrow   = "▲" if week_pct >= 0 else "▼"
        sig_col  = ("#00e676" if "Bullish" in sig else "#ff4444" if "Bearish" in sig else "#7a90b0")
        day_col  = "#00e676" if day_pct >= 0 else "#ff4444"
        week_col = "#00e676" if week_pct >= 0 else "#ff4444"

        rows.append(
            f'<tr>'
            f'<td><span style="color:#FFD700;font-weight:700;font-size:15px">{f["pair"]}</span>'
            f'<br><span style="color:#3a5070;font-size:10px">{f["desc"]}</span></td>'
            f'<td style="color:#c8d8f0;font-weight:600;font-size:14px">{price:.5f}</td>'
            f'<td style="color:{day_col};font-weight:700">{arrow}{abs(day_pct):.3f}%</td>'
            f'<td style="color:{week_col}">{warrow}{abs(week_pct):.3f}%</td>'
            f'<td style="color:{sig_col};font-weight:700">{sig}</td>'
            f'</tr>'
        )

    return f"""
<section>
  <h2>FOREX — {len(forex)} CURRENCY PAIRS · <span style="font-weight:400;color:#7a90b0">{now}</span></h2>
  <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
    <div class="stat"><div class="stat-n" style="color:#00e676">{len(bullish)}</div><div class="stat-l">Bullish</div></div>
    <div class="stat-div"></div>
    <div class="stat"><div class="stat-n" style="color:#ff4444">{len(bearish)}</div><div class="stat-l">Bearish</div></div>
    <div class="stat-div"></div>
    <div class="stat"><div class="stat-n" style="color:#7a90b0">{len(neutral)}</div><div class="stat-l">Neutral</div></div>
  </div>
  <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr>
        <th>Pair</th><th>Price</th><th>Day Change</th><th>5-Day Change</th><th>Signal</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
  <div style="font-size:10px;color:#3a5070;margin-top:8px">Source: Yahoo Finance (yfinance) · EOD data</div>
</section>"""


def _signal_color(signal: str) -> str:
    return {
        "Strong Bullish": "#00e676",
        "Bullish":        "#69f0ae",
        "Neutral":        "#7a90b0",
        "Bearish":        "#ff7043",
        "Strong Bearish": "#ff4444",
    }.get(signal, "#7a90b0")


def _build_polygon_section(poly: dict) -> str:
    if not poly:
        return ""

    ts       = poly.get("timestamp", "")[:19]
    summary  = poly.get("summary", {})
    bullish  = poly.get("bullish", [])
    bearish  = poly.get("bearish", [])
    gainers  = poly.get("gainers", [])[:8]
    losers   = poly.get("losers", [])[:8]

    def stock_rows(items: list, max_rows: int = 10) -> str:
        rows = []
        for s in items[:max_rows]:
            pct   = s.get("change_pct", 0)
            col   = _signal_color(s.get("signal", "Neutral"))
            arrow = "▲" if pct >= 0 else "▼"
            rows.append(
                f'<tr>'
                f'<td style="color:#FFD700;font-weight:600">{s["symbol"]}</td>'
                f'<td>${s["price"]:,.2f}</td>'
                f'<td style="color:{col};font-weight:600">{arrow}{abs(pct):.2f}%</td>'
                f'<td style="color:{col}">{s.get("signal","")}</td>'
                f'<td style="color:#7a90b0">{s["volume"]:,}</td>'
                f'</tr>'
            )
        return "".join(rows) if rows else '<tr><td colspan="5" style="color:#3a5070">No data</td></tr>'

    bull_rows = stock_rows(bullish)
    bear_rows = stock_rows(bearish)
    gain_rows = stock_rows(gainers)
    loss_rows = stock_rows(losers)

    b_cnt = summary.get("bullish_count", len(bullish))
    s_cnt = summary.get("bearish_count", len(bearish))
    n_cnt = summary.get("neutral_count", 0)
    total = summary.get("total_scanned", 0)

    return f"""
<section>
  <h2>POLYGON.IO — MARKET SENTIMENT · <span style="font-weight:400;color:#7a90b0">{ts}</span></h2>
  <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
    <div class="stat"><div class="stat-n" style="color:#00e676">{b_cnt}</div><div class="stat-l">Bullish</div></div>
    <div class="stat-div"></div>
    <div class="stat"><div class="stat-n" style="color:#ff4444">{s_cnt}</div><div class="stat-l">Bearish</div></div>
    <div class="stat-div"></div>
    <div class="stat"><div class="stat-n" style="color:#7a90b0">{n_cnt}</div><div class="stat-l">Neutral</div></div>
    <div class="stat-div"></div>
    <div class="stat"><div class="stat-n">{total}</div><div class="stat-l">Scanned</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
    <div>
      <div style="font-size:11px;font-weight:600;color:#00e676;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">▲ Bullish Watchlist</div>
      <table class="data-table">
        <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th>Signal</th><th>Volume</th></tr></thead>
        <tbody>{bull_rows}</tbody>
      </table>
    </div>
    <div>
      <div style="font-size:11px;font-weight:600;color:#ff4444;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">▼ Bearish Watchlist</div>
      <table class="data-table">
        <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th>Signal</th><th>Volume</th></tr></thead>
        <tbody>{bear_rows}</tbody>
      </table>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    <div>
      <div style="font-size:11px;font-weight:600;color:#69f0ae;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">🏆 Market Gainers</div>
      <table class="data-table">
        <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th>Signal</th><th>Volume</th></tr></thead>
        <tbody>{gain_rows}</tbody>
      </table>
    </div>
    <div>
      <div style="font-size:11px;font-weight:600;color:#ff7043;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">💔 Market Losers</div>
      <table class="data-table">
        <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th>Signal</th><th>Volume</th></tr></thead>
        <tbody>{loss_rows}</tbody>
      </table>
    </div>
  </div>
</section>"""


def _fetch_crypto_data() -> dict:
    """Read crypto state written by weekend_crypto_daemon.py."""
    try:
        return json.loads(CRYPTO_STATE_FILE.read_text())
    except Exception:
        return {}


def _build_crypto_section(crypto: dict) -> str:
    if not crypto:
        return """<section style="padding:24px 28px">
  <h2 style="color:#FFD700;font-size:16px;letter-spacing:3px;margin-bottom:16px">CRYPTO MARKETS</h2>
  <div style="color:#7a90b0;padding:20px;text-align:center">
    Crypto data not yet available.<br>
    Run: <code style="color:#00d4ff">python3 ~/sierra_intelligence/weekend_crypto_daemon.py --force</code>
  </div>
</section>"""

    mode       = crypto.get("mode", "IDLE")
    fg         = crypto.get("fear_greed", {})
    fg_val     = fg.get("value", 50)
    fg_label   = fg.get("label", "—")
    last_run   = (crypto.get("last_run") or "")[:19]
    coins      = crypto.get("coins", {})
    trades     = crypto.get("paper_trades", [])

    # Fear & Greed colour
    if fg_val <= 25:   fg_color = "#00e676"
    elif fg_val <= 45: fg_color = "#69f0ae"
    elif fg_val >= 75: fg_color = "#ff4444"
    elif fg_val >= 55: fg_color = "#ff7043"
    else:              fg_color = "#8899aa"

    # Weekend mode banner
    if mode == "ACTIVE":
        mode_banner = f"""<div style="background:rgba(0,230,118,.08);border:1px solid rgba(0,230,118,.4);
  border-radius:8px;padding:12px 20px;margin-bottom:20px;display:flex;align-items:center;gap:20px">
  <span style="color:#00e676;font-size:18px;font-weight:700;letter-spacing:2px">● WEEKEND MODE ACTIVE</span>
  <span style="color:#7a90b0;font-size:12px">Paper trading running · Last update: {last_run}</span>
</div>"""
    else:
        mode_banner = f"""<div style="background:rgba(122,144,176,.06);border:1px solid rgba(122,144,176,.2);
  border-radius:8px;padding:12px 20px;margin-bottom:20px;display:flex;align-items:center;gap:20px">
  <span style="color:#7a90b0;font-size:14px;font-weight:600;letter-spacing:2px">○ WEEKDAY — IDLE</span>
  <span style="color:#3a5070;font-size:12px">Crypto paper trading activates on weekends · Last run: {last_run or 'never'}</span>
</div>"""

    # Coin rows
    rows = ""
    sig_colors = {
        "STRONG BULLISH": ("#00e676", "rgba(0,230,118,.12)"),
        "BULLISH":        ("#69f0ae", "rgba(105,240,174,.08)"),
        "NEUTRAL":        ("#8899aa", "transparent"),
        "BEARISH":        ("#ff7043", "rgba(255,112,67,.08)"),
        "STRONG BEARISH": ("#ff4444", "rgba(255,68,68,.12)"),
    }
    for sym, d in coins.items():
        sig   = d.get("signal", "NEUTRAL")
        sc, sb = sig_colors.get(sig, ("#8899aa", "transparent"))
        wr    = d.get("williams_r")
        wr_str = f"{wr:.0f}" if wr is not None else "—"
        wr_color = "#00e676" if wr is not None and wr < -60 else ("#ff4444" if wr is not None and wr > -30 else "#8899aa")
        c24   = d.get("chg_24h", 0)
        c7    = d.get("chg_7d", 0)
        c24c  = "#00e676" if c24 >= 0 else "#ff4444"
        c7c   = "#00e676" if c7  >= 0 else "#ff4444"
        price = d.get("price", 0)
        price_str = f"${price:,.2f}" if price >= 1 else f"${price:.5f}"
        rows += f"""<tr style="background:{sb}">
  <td style="font-weight:700;color:#c8d8f0">{sym}</td>
  <td style="font-weight:600;color:#FFD700">{price_str}</td>
  <td style="color:{c24c}">{c24:+.1f}%</td>
  <td style="color:{c7c}">{c7:+.1f}%</td>
  <td style="color:{wr_color};font-weight:600">{wr_str}</td>
  <td><span style="color:{sc};font-weight:700;font-size:11px;letter-spacing:1px">{sig}</span></td>
  <td style="color:#7a90b0;font-size:11px">{d.get('reason','—')[:60]}</td>
</tr>"""

    # Recent paper trades (last 10)
    trade_rows = ""
    for t in reversed(trades[-10:]):
        ts  = (t.get("ts") or "")[:16]
        sym = t.get("symbol", "")
        sz  = t.get("size_usd", 0)
        risk = t.get("risk_usd", 0)
        trade_rows += f"""<tr>
  <td style="color:#7a90b0;font-size:11px">{ts}</td>
  <td style="color:#FFD700;font-weight:600">{sym}</td>
  <td style="color:#00e676">LONG</td>
  <td style="color:#c8d8f0">${sz:,.0f}</td>
  <td style="color:#ff7043">${risk:,.0f}</td>
  <td style="color:#7a90b0;font-size:11px">{t.get('reasoning','')[:50]}</td>
</tr>"""

    trade_section = ""
    if trade_rows:
        trade_section = f"""
<section style="padding:0 28px 24px">
  <h2 style="color:#FFD700;font-size:14px;letter-spacing:3px;margin-bottom:12px">
    RECENT PAPER TRADES ({len(trades)} total)
  </h2>
  <table class="data-table">
    <thead><tr>
      <th>Time</th><th>Symbol</th><th>Dir</th>
      <th>Size USD</th><th>Risk USD</th><th>Reason</th>
    </tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
</section>"""

    return f"""<section style="padding:24px 28px 8px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
    <h2 style="color:#FFD700;font-size:16px;letter-spacing:3px">CRYPTO MARKETS</h2>
    <div style="display:flex;gap:24px;align-items:center">
      <div style="text-align:center">
        <div style="color:{fg_color};font-size:24px;font-weight:700">{fg_val}</div>
        <div style="color:#7a90b0;font-size:11px;letter-spacing:1px">FEAR &amp; GREED</div>
        <div style="color:{fg_color};font-size:11px">{fg_label}</div>
      </div>
    </div>
  </div>
  {mode_banner}
  <table class="data-table">
    <thead><tr>
      <th>Symbol</th><th>Price</th><th>24h %</th><th>7d %</th>
      <th>Williams %R</th><th>Signal</th><th>Reason</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
{trade_section}"""


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
        if scanner.get("analyzer_running"):
            sc_class = "badge-standby"
            sc_label = "● STANDBY — Open Sierra Chart to activate"
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

    poly_data           = _fetch_polygon_data()
    baro_data           = _fetch_barometers()
    cot_rows            = _fetch_cot_data()
    cot_lookup          = {r["symbol"]: r for r in cot_rows}
    forex_data          = _fetch_forex_data()
    crypto_data         = _fetch_crypto_data()
    predictions_section = _build_predictions_table(scanner, cot_lookup)
    barometers_section  = _build_barometers_section(baro_data)
    cot_section         = _build_cot_section(cot_rows)
    polygon_section     = _build_polygon_section(poly_data)
    forex_section       = _build_forex_section(forex_data)
    crypto_section      = _build_crypto_section(crypto_data)
    chartbook_section   = _build_chartbook_section(cb_data)
    files_section       = _build_files_section(syms)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
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
  .badge-standby {{
    padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;
    background: rgba(255,165,0,.12); border: 1px solid rgba(255,165,0,.4); color: #ffaa33;
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
    user-select: none;
    transition: background .15s;
  }}
  .data-table th:hover {{
    background: rgba(255,215,0,.08);
    color: #FFD700;
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

<!-- ── Tab Bar ── -->
<div style="background:var(--bg2);border-bottom:1px solid var(--border);padding:0 28px;display:flex;gap:0">
  <button class="tab-btn active" onclick="switchTab('futures',this)"
    style="padding:12px 28px;background:none;border:none;border-bottom:3px solid #FFD700;
           color:#FFD700;font-weight:700;font-size:13px;letter-spacing:2px;cursor:pointer;text-transform:uppercase">
    FUTURES
  </button>
  <button class="tab-btn" onclick="switchTab('stocks',this)"
    style="padding:12px 28px;background:none;border:none;border-bottom:3px solid transparent;
           color:#7a90b0;font-weight:600;font-size:13px;letter-spacing:2px;cursor:pointer;text-transform:uppercase">
    STOCKS
  </button>
  <button class="tab-btn" onclick="switchTab('forex',this)"
    style="padding:12px 28px;background:none;border:none;border-bottom:3px solid transparent;
           color:#7a90b0;font-weight:600;font-size:13px;letter-spacing:2px;cursor:pointer;text-transform:uppercase">
    FOREX
  </button>
  <button class="tab-btn" onclick="switchTab('crypto',this)"
    style="padding:12px 28px;background:none;border:none;border-bottom:3px solid transparent;
           color:#7a90b0;font-weight:600;font-size:13px;letter-spacing:2px;cursor:pointer;text-transform:uppercase">
    CRYPTO
  </button>
</div>

<!-- ── Futures Tab ── -->
<div id="tab-futures" class="tab-panel">
{predictions_section}
{barometers_section}
{cot_section}
{chartbook_section}
{files_section}
</div>

<!-- ── Stocks Tab ── -->
<div id="tab-stocks" class="tab-panel" style="display:none">
{polygon_section}
</div>

<!-- ── Forex Tab ── -->
<div id="tab-forex" class="tab-panel" style="display:none">
{forex_section}
</div>

<!-- ── Crypto Tab ── -->
<div id="tab-crypto" class="tab-panel" style="display:none">
{crypto_section}
</div>

<script>
/* ── Clock ── */
(function() {{
  var fmt = new Intl.DateTimeFormat('en-US',{{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}});
  setInterval(function(){{var el=document.getElementById('ts');if(el)el.textContent=fmt.format(new Date());}},1000);
}})();

/* ── Tab switching ── */
function switchTab(name, btn) {{
  document.querySelectorAll('.tab-panel').forEach(function(p){{p.style.display='none';}});
  document.querySelectorAll('.tab-btn').forEach(function(b){{
    b.style.color='#7a90b0';b.style.borderBottom='3px solid transparent';b.style.fontWeight='600';
  }});
  var panel=document.getElementById('tab-'+name);
  if(panel) panel.style.display='block';
  if(btn){{btn.style.color='#FFD700';btn.style.borderBottom='3px solid #FFD700';btn.style.fontWeight='700';}}
  localStorage.setItem('si_active_tab',name);
}}

/* ── Column drag-reorder + sort — persisted to localStorage ── */
(function() {{

  /* Unique stable ID for each table based on its section heading */
  function tableKey(table) {{
    var sec = table.closest('section');
    var h2  = sec && sec.querySelector('h2');
    var txt = h2 ? h2.textContent.trim().replace(/[^A-Za-z0-9]+/g,'_').slice(0,40) : '';
    if (!txt) {{
      var all = Array.from(document.querySelectorAll('.data-table'));
      txt = 'tbl_'+all.indexOf(table);
    }}
    return 'si_col_'+txt;
  }}

  /* Read column header texts (stable keys) */
  function headerTexts(table) {{
    return Array.from(table.querySelectorAll('thead th')).map(function(th){{
      return th.dataset.colKey || th.textContent.trim();
    }});
  }}

  /* Reorder all rows so column srcIdx moves to tgtIdx */
  function moveColumn(table, srcIdx, tgtIdx) {{
    if (srcIdx===tgtIdx) return;
    table.querySelectorAll('tr').forEach(function(row) {{
      var cells = Array.from(row.children);
      if (Math.max(srcIdx,tgtIdx) >= cells.length) return;
      var moving = cells[srcIdx];
      if (srcIdx < tgtIdx) row.insertBefore(moving, cells[tgtIdx].nextSibling);
      else                  row.insertBefore(moving, cells[tgtIdx]);
    }});
  }}

  /* Save current visual column order (as header key array) */
  function saveOrder(table) {{
    try {{ localStorage.setItem(tableKey(table), JSON.stringify(headerTexts(table))); }} catch(e) {{}}
  }}

  /* Restore saved order on page load */
  function restoreOrder(table) {{
    var saved;
    try {{ saved = JSON.parse(localStorage.getItem(tableKey(table))); }} catch(e) {{ return; }}
    if (!saved || !Array.isArray(saved)) return;
    var ths = Array.from(table.querySelectorAll('thead th'));
    if (saved.length !== ths.length) return;  /* schema changed — skip */
    /* Build map: key → current index */
    var keyToIdx = {{}};
    ths.forEach(function(th,i){{ keyToIdx[th.dataset.colKey||th.textContent.trim()] = i; }});
    saved.forEach(function(key, displayPos) {{
      var curIdx = keyToIdx[key];
      if (curIdx === undefined || curIdx === displayPos) return;
      moveColumn(table, curIdx, displayPos);
      /* After move, update keyToIdx */
      var entries = Object.entries(keyToIdx);
      var moved = entries.find(function(e){{return e[0]===key;}});
      entries.forEach(function(e) {{
        var k=e[0], v=e[1];
        if (curIdx < displayPos) {{
          if (v>curIdx && v<=displayPos) keyToIdx[k]=v-1;
        }} else {{
          if (v>=displayPos && v<curIdx) keyToIdx[k]=v+1;
        }}
      }});
      keyToIdx[key]=displayPos;
    }});
  }}

  /* Sort table by column index — numeric or text, toggle asc/desc */
  function sortByColumn(table, colIdx, th) {{
    var asc = th.dataset.sortDir !== 'asc';
    th.dataset.sortDir = asc ? 'asc' : 'desc';
    /* Update sort indicator on all ths */
    Array.from(table.querySelectorAll('thead th')).forEach(function(h) {{
      var base = h.dataset.colKey || h.textContent.replace(/[\u25b2\u25bc]\s*/g,'').trim();
      h.textContent = base + (h===th ? (asc?' ▲':' ▼') : '');
      h.dataset.colKey = base;
    }});
    /* Sort tbody rows */
    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll('tr')).filter(function(r){{
      /* Skip group-header rows (colspan rows) */
      return !r.querySelector('td[colspan]');
    }});
    rows.sort(function(a,b) {{
      var ca = a.children[colIdx], cb = b.children[colIdx];
      if (!ca||!cb) return 0;
      var ta = ca.textContent.trim(), tb = cb.textContent.trim();
      /* Strip arrows/symbols for numeric check */
      var na = parseFloat(ta.replace(/[^0-9.\-+]/g,''));
      var nb = parseFloat(tb.replace(/[^0-9.\-+]/g,''));
      var cmp = (!isNaN(na)&&!isNaN(nb)) ? na-nb : ta.localeCompare(tb);
      return asc ? cmp : -cmp;
    }});
    rows.forEach(function(r){{tbody.appendChild(r);}});
    /* Persist sort state */
    try {{ localStorage.setItem(tableKey(table)+'_sort', JSON.stringify({{col:colIdx,asc:asc}})); }} catch(e) {{}}
  }}

  /* Restore saved sort */
  function restoreSort(table) {{
    var s;
    try {{ s = JSON.parse(localStorage.getItem(tableKey(table)+'_sort')); }} catch(e) {{ return; }}
    if (!s) return;
    var ths = table.querySelectorAll('thead th');
    var th = ths[s.col];
    if (!th) return;
    th.dataset.sortDir = s.asc ? 'desc' : 'asc'; /* will be toggled */
    sortByColumn(table, s.col, th);
  }}

  /* Drag-and-drop column reorder */
  function addDragHandlers(table) {{
    var thead = table.querySelector('thead');
    if (!thead) return;
    var dragSrc = null;

    function getThIdx(th) {{
      return Array.from(thead.querySelectorAll('th')).indexOf(th);
    }}

    thead.querySelectorAll('th').forEach(function(th) {{
      /* Store stable col key BEFORE any reorder */
      if (!th.dataset.colKey) th.dataset.colKey = th.textContent.trim();

      th.draggable = true;
      th.style.cursor = 'grab';
      th.title = 'Drag to reorder · Click to sort';

      th.addEventListener('dragstart', function(e) {{
        dragSrc = th;
        th.style.opacity = '0.45';
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain','');
      }});
      th.addEventListener('dragend', function() {{
        th.style.opacity = '';
        thead.querySelectorAll('th').forEach(function(h){{
          h.style.background=''; h.style.outline='';
        }});
      }});
      th.addEventListener('dragover', function(e) {{
        e.preventDefault(); e.dataTransfer.dropEffect='move';
        thead.querySelectorAll('th').forEach(function(h){{h.style.outline='';}});
        if (th!==dragSrc) th.style.outline='2px solid #FFD700';
      }});
      th.addEventListener('dragleave', function() {{ th.style.outline=''; }});
      th.addEventListener('drop', function(e) {{
        e.preventDefault();
        th.style.outline='';
        if (!dragSrc || dragSrc===th) return;
        var si = getThIdx(dragSrc), ti = getThIdx(th);
        moveColumn(table, si, ti);
        saveOrder(table);
        /* Re-init drag on all ths after DOM reorder */
        initTable(table);
      }});

      /* Click to sort */
      th.addEventListener('click', function() {{
        if (dragSrc) return; /* was a drag, not a click */
        var idx = getThIdx(th);
        sortByColumn(table, idx, th);
      }});
    }});
  }}

  function initTable(table) {{
    addDragHandlers(table);
  }}

  /* Init all tables after DOM ready */
  document.addEventListener('DOMContentLoaded', function() {{
    document.querySelectorAll('.data-table').forEach(function(table) {{
      /* Tag all th with stable colKey before any reorder */
      table.querySelectorAll('thead th').forEach(function(th) {{
        if (!th.dataset.colKey) th.dataset.colKey = th.textContent.trim();
      }});
      restoreOrder(table);
      restoreSort(table);
      initTable(table);
    }});
  }});

  /* Restore active tab */
  document.addEventListener('DOMContentLoaded', function() {{
    var tab = localStorage.getItem('si_active_tab') || 'futures';
    var btn = document.querySelector('[onclick*="switchTab(\\''+tab+'\'"]') ||
              document.querySelector('[onclick*="\''+tab+'\'"]');
    if (btn) switchTab(tab, btn);
  }});

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
