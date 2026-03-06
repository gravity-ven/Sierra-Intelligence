# Sierra Intelligence

**Sierra Intelligence** is an advanced AI-powered trading intelligence system for Sierra Chart. It combines computer vision, Claude Vision API, ensemble machine learning, and real-time technical analysis to deliver multi-timeframe trading signals across futures, crypto, commodities, and equities.

---

## Architecture

```
Sierra Intelligence
├── sierra_data_analyzer.py        — Primary engine: screenshot → Claude Vision → OHLCV fallback
├── sierra_screenshot_server.py    — Dashboard (port 5050): live multi-timeframe signals
├── sierra_scanner_ai.py           — v1.0 Screenshot-based AI scanner
├── sierra_scanner_ai_pro.py       — v2.0 Ensemble ML (RF + GB + NN) + Kelly Criterion
├── sierra_screenshot_helper.py    — Windows-side screenshot capture (run with Windows Python)
├── sierra_gpu_monitor.py          — NVIDIA GPU cache auto-cleaner
├── sierra_scanner_config.json     — Base configuration
├── sierra_scanner_config_v2.json  — Enhanced AI Pro configuration
├── SierraChartAutonomousMonitor.ps1 — Autonomous window position manager
└── start_sierra_ai_pro.sh         — Quick start for AI Pro scanner
```

---

## Dashboard

The **Sierra Intelligence Dashboard** runs at `http://localhost:5050`:

- Real-time multi-timeframe signals: **NOW / 24H / 5D / 1M**
- RSI, MACD, Bollinger Bands, ATR, Risk/Reward ratio
- Stop-loss and target price levels
- AI vision vs technical analysis signal source badge
- 16 tracked instruments grouped by signal strength

---

## Quick Start

```bash
# 1. Install dependencies
pip install psutil Pillow numpy psycopg2-binary flask flask-cors scikit-learn scipy

# 2. Set your Anthropic API key (for Claude Vision)
export ANTHROPIC_API_KEY=your_key_here
# Or add to .env file in the project directory

# 3. Start the analysis engine
python3 sierra_data_analyzer.py

# 4. Start the dashboard (separate terminal)
python3 sierra_screenshot_server.py

# 5. Open http://localhost:5050
```

### AI Pro Scanner (Ensemble ML)

```bash
./start_sierra_ai_pro.sh
```

---

## Tracked Instruments

| Symbol | Name | Category |
|--------|------|----------|
| M2KH26-CME | Micro Russell 2000 | Equity |
| MESH26-CME | Micro S&P 500 | Equity |
| MNQH26-CME | Micro NASDAQ 100 | Equity |
| MYMH26-CBOT | Micro Dow | Equity |
| MBTG26-CME | Micro Bitcoin | Crypto |
| METG26-CME | Micro Ether | Crypto |
| MGCJ26-COMEX | Micro Gold | Commodity |
| MHGH26-COMEX | Micro Copper | Commodity |
| MCLJ26-NYMEX | Micro Crude Oil | Energy |
| MSLG26-CME | Micro Silver | Commodity |
| MZLK26-CBOT | Micro Corn | Grain |
| AAPL | Apple | Stock |
| TSLA-NQTV | Tesla | Stock |
| NVDA-NQTV | NVIDIA | Stock |
| GOOGL-NQTV | Alphabet | Stock |
| MSFT-NQTV | Microsoft | Stock |

---

## Signal System

Each instrument is scored across 8 factors:

| Factor | Bullish | Bearish |
|--------|---------|---------|
| RSI 14 | < 35 oversold | > 65 overbought |
| RSI momentum | Rising +3 | Falling -3 |
| MACD histogram | Bullish crossover | Bearish crossover |
| Price vs SMA 50 | Price > 50SMA | Price < 50SMA |
| EMA 9 vs EMA 21 | EMA9 > EMA21 | EMA9 < EMA21 |
| SMA 200 | Price > 200SMA | Price < 200SMA |
| Bollinger position | Near lower band | Near upper band |
| Volume | High vol + price up | High vol + price down |

**Signals**: `Strong Bullish` | `Bullish` | `Neutral` | `Bearish` | `Strong Bearish`

---

## AI Vision Mode

When `ANTHROPIC_API_KEY` is set, `sierra_data_analyzer.py` will:
1. Capture a screenshot of Sierra Chart every 60 seconds
2. Send it to Claude Haiku vision API
3. Read the actual indicators configured in Sierra Chart
4. Override the technical signal with what Claude sees on screen
5. Fall back to pure OHLCV math if the screenshot fails

---

## AI Pro Features (v2.0)

- **Ensemble ML**: Random Forest + Gradient Boosting + Neural Network (soft voting)
- **Bayesian confidence calibration** with temperature scaling
- **Kelly Criterion** position sizing (half-Kelly default)
- **Market regime detection**: trending / ranging / volatile
- **Reinforcement learning** for continuous improvement
- **Multi-timeframe analysis fusion**
- **Auto-retraining** every 24 hours

---

## GPU Cache Monitor

```bash
python3 sierra_gpu_monitor.py --status   # Check current sizes
python3 sierra_gpu_monitor.py --clear    # Force clear now
python3 sierra_gpu_monitor.py            # Continuous monitor (5min interval)
```

---

*Part of the Spartan Research Station — "Maximum Profits. Minimum Losses. Minimum Drawdown."*
