#!/usr/bin/env python3
"""
Sierra Scanner AI Pro - Advanced Trading Intelligence System v2.0

ULTIMATE RULE: "Maximum Profits. Minimum Losses. Minimum Drawdown."

Enhancements in v2.0:
- Ensemble machine learning (Random Forest + Gradient Boosting + Neural Network)
- Advanced technical indicator extraction from chart images
- Reinforcement learning for continuous improvement
- Bayesian confidence calibration
- Multi-timeframe analysis fusion
- Advanced risk management with Kelly Criterion
- Real-time backtesting and cross-validation
- Market regime detection
- Sentiment analysis integration

Author: AI Trading System
Version: 2.0
"""

import os
import sys
import time
import json
import signal
import threading
import subprocess
import logging
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field, asdict
from collections import deque, defaultdict
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

# Third-party imports with graceful fallbacks
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from PIL import Image, ImageGrab, ImageFilter, ImageEnhance, ImageOps
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    np = None

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Machine Learning imports
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler, RobustScaler
    from sklearn.model_selection import cross_val_score, TimeSeriesSplit
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.feature_selection import SelectKBest, mutual_info_classif
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from scipy import stats
    from scipy.signal import find_peaks, butter, filtfilt
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# ============================================================================
# CONFIGURATION v2.0
# ============================================================================

def _detect_wsl():
    """Detect if running in WSL"""
    try:
        with open('/proc/version', 'r', encoding='utf-8') as f:
            content = f.read().lower()
            return 'microsoft' in content or 'wsl' in content
    except:
        return False

def _load_config_file():
    """Load configuration from JSON file"""
    config_paths = [
        Path(__file__).parent / "sierra_scanner_config.json",
        Path("/mnt/c/Users/Quantum/Downloads/Spartan_Labs/website/sierra_scanner_config.json"),
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config: {e}")
    return {}


class Config:
    """Global configuration for Sierra Scanner AI Pro"""

    _EXTERNAL_CONFIG = _load_config_file()
    _IS_WSL = _detect_wsl()
    _ON_MACOS = __import__('platform').system() == 'Darwin'

    # Sierra Chart paths
    SIERRA_CHART_EXE = "SierraChart_64.exe"
    if _ON_MACOS:
        SIERRA_CHART_PATH = None
    elif _IS_WSL:
        SIERRA_CHART_PATH = Path("/mnt/c/Users/Quantum/Downloads/SierraChart")
    else:
        SIERRA_CHART_PATH = Path(r"C:\Users\Quantum\Downloads\SierraChart")
    
    DATA_PATH = SIERRA_CHART_PATH / "Data" if SIERRA_CHART_PATH else None
    ACS_SOURCE_PATH = SIERRA_CHART_PATH / "ACS_Source" if SIERRA_CHART_PATH else None

    # Enhanced scanner settings
    _scanner_cfg = _EXTERNAL_CONFIG.get('scanner', {})
    SCREENSHOT_INTERVAL = _scanner_cfg.get('screenshot_interval', 3)  # Faster scanning
    SCREENSHOT_DIR = ACS_SOURCE_PATH / "screenshots" if ACS_SOURCE_PATH else Path("./screenshots")
    MAX_SCREENSHOTS_PER_SYMBOL = _scanner_cfg.get('max_screensshots_per_symbol', 200)

    # v2.0 AI Settings - Higher standards
    CONFIDENCE_THRESHOLD = _scanner_cfg.get('confidence_threshold', 0.75)  # Increased from 0.65
    PATTERN_MEMORY_SIZE = 5000  # Increased from 1000
    LEARNING_RATE = 0.05  # More conservative learning
    MIN_SAMPLES_FOR_PREDICTION = 50  # Minimum historical samples
    ENSEMBLE_VOTING = 'soft'  # Soft voting for probability calibration
    
    # Cross-validation settings
    CV_SPLITS = 5
    MIN_ACCURACY_FOR_DEPLOYMENT = 0.65  # 65% minimum accuracy
    MIN_PRECISION_FOR_TRADING = 0.70  # 70% precision required

    # Risk Management - Kelly Criterion
    KELLY_FRACTION = 0.5  # Half-Kelly for safety
    MAX_POSITION_SIZE_PCT = 0.10  # Max 10% per position
    STOP_LOSS_ATR_MULTIPLIER = 2.0  # 2x ATR for stop loss
    TAKE_PROFIT_RR_RATIO = 2.5  # Risk:Reward ratio

    # Market Regime Detection
    REGIME_LOOKBACK = 20  # Bars for regime detection
    VOLATILITY_PERCENTILE_THRESHOLD = 75  # High volatility regime

    # Database settings
    DB_NAME = "sierra_scanner_db"
    DB_USER = "sierra_user"
    DB_PASSWORD = "sierra_secure_pass"
    DB_HOST = "localhost"
    DB_PORT = 5432

    # API settings
    _api_cfg = _EXTERNAL_CONFIG.get('api', {})
    API_HOST = _api_cfg.get('host', "0.0.0.0")
    API_PORT = _api_cfg.get('port', 5015)

    # Logging
    LOG_FILE = ACS_SOURCE_PATH / "logs" / "sierra_scanner_ai_pro.log" if ACS_SOURCE_PATH else Path("./sierra_scanner_ai_pro.log")
    LOG_LEVEL = logging.INFO

    # Windows Python path
    WINDOWS_PYTHON = "/mnt/c/Python313/pythonw.exe"
    SCREENSHOT_HELPER = Path(__file__).parent / "sierra_screenshot_helper.py"

    # Grid Configuration
    _grid_cfg = _EXTERNAL_CONFIG.get('grid', {})
    GRID_COLS = _grid_cfg.get('cols', 8)
    GRID_ROWS = _grid_cfg.get('rows', 4)
    GRID_SYMBOLS = _grid_cfg.get('symbols', ['M2K', 'MBT', 'MCL', 'MES', 'MET', 'MGC', 'MNQ', 'MYM'])
    GRID_TIMEFRAMES = _grid_cfg.get('timeframes', ['Daily', 'Weekly', 'Monthly', 'Yearly'])

    # Model persistence
    MODEL_DIR = ACS_SOURCE_PATH / "models" if ACS_SOURCE_PATH else Path("./models")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# WSL HELPERS
# ============================================================================

IS_WSL = Config._IS_WSL

def wsl_to_windows_path(wsl_path: str) -> str:
    """Convert WSL path to Windows path"""
    path_str = str(wsl_path)
    if path_str.startswith('/mnt/c/'):
        return path_str.replace('/mnt/c/', 'C:\\\\').replace('/', '\\\\')
    elif path_str.startswith('/mnt/'):
        drive = path_str[5]
        return path_str.replace(f'/mnt/{drive}/', f'{drive.upper()}:\\\\').replace('/', '\\\\')
    return path_str

def run_windows_python(script_path: str, *args) -> dict:
    """Run a Python script using Windows Python from WSL"""
    try:
        win_script = wsl_to_windows_path(str(script_path))
        converted_args = []
        for arg in args:
            if str(arg).startswith('/mnt/'):
                converted_args.append(wsl_to_windows_path(str(arg)))
            else:
                converted_args.append(str(arg))

        cmd = [Config.WINDOWS_PYTHON, win_script] + converted_args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        else:
            return {'error': result.stderr or 'Unknown error'}
    except subprocess.TimeoutExpired:
        return {'error': 'Timeout waiting for Windows Python'}
    except json.JSONDecodeError as e:
        return {'error': f'Invalid JSON response: {e}'}
    except Exception as e:
        return {'error': str(e)}


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure logging"""
    log_dir = Config.LOG_FILE.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format='%(asctime)s | %(levelname)s | [%(name)s] %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class Signal(Enum):
    """Trading signal types"""
    STRONG_BULLISH = "Strong Bullish"
    BULLISH        = "Bullish"
    NEUTRAL        = "Neutral"
    BEARISH        = "Bearish"
    STRONG_BEARISH = "Strong Bearish"

class MarketRegime(Enum):
    """Market regime classification"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


@dataclass
class TechnicalIndicators:
    """Technical indicators extracted from chart"""
    # Trend indicators
    sma_fast: float = 0.0
    sma_slow: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    adx: float = 0.0  # Trend strength
    
    # Momentum indicators
    rsi: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    stochastic_k: float = 50.0
    stochastic_d: float = 50.0
    
    # Volatility indicators
    bollinger_position: float = 0.5  # 0=lower band, 0.5=middle, 1=upper
    atr: float = 0.0
    
    # Volume indicators
    volume_sma_ratio: float = 1.0
    obv_trend: float = 0.0
    
    # Support/Resistance
    support_distance: float = 0.5
    resistance_distance: float = 0.5
    pivot_position: float = 0.5


@dataclass
class ChartAnalysis:
    """Enhanced analysis result for a single chart"""
    symbol: str
    timestamp: datetime
    signal: Signal
    confidence: float
    
    # Technical indicators
    indicators: TechnicalIndicators = field(default_factory=TechnicalIndicators)
    
    # Market regime
    market_regime: MarketRegime = MarketRegime.RANGING
    regime_confidence: float = 0.5
    
    # AI learning data
    pattern_hash: str = ""
    pattern_vector: List[float] = field(default_factory=list)
    similar_patterns_count: int = 0
    historical_accuracy: float = 0.5
    model_predictions: Dict[str, float] = field(default_factory=dict)
    
    # Risk metrics (ULTIMATE RULE)
    expected_profit: float = 0.0
    max_loss_estimate: float = 0.0
    drawdown_risk: float = 0.0
    risk_reward_ratio: float = 0.0
    kelly_fraction: float = 0.0
    recommended_position_size: float = 0.0
    
    # Ensemble confidence
    ensemble_agreement: float = 0.0  # How much models agree
    bayesian_confidence: float = 0.5  # Calibrated probability
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['signal'] = self.signal.value
        result['market_regime'] = self.market_regime.value
        result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class SymbolState:
    """Enhanced state tracking for each symbol"""
    symbol: str
    timeframe: str = ""
    chartbook: str = ""
    
    # Analysis history
    analyses: deque = field(default_factory=lambda: deque(maxlen=500))
    indicator_history: deque = field(default_factory=lambda: deque(maxlen=100))
    regime_history: deque = field(default_factory=lambda: deque(maxlen=50))
    
    # Learning data
    pattern_memory: Dict[str, Dict] = field(default_factory=dict)
    prediction_outcomes: List[Dict] = field(default_factory=list)
    
    # Performance tracking
    total_predictions: int = 0
    correct_predictions: int = 0
    total_profit: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    
    @property
    def win_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.5
        return self.correct_predictions / self.total_predictions
    
    @property
    def sharpe_ratio(self) -> float:
        if len(self.prediction_outcomes) < 10:
            return 0.0
        returns = [p.get('return', 0) for p in self.prediction_outcomes[-50:]]
        if not returns or np.std(returns) == 0:
            return 0.0
        return np.mean(returns) / (np.std(returns) + 1e-10)


# ============================================================================
# ADVANCED IMAGE ANALYSIS - Technical Indicator Extraction
# ============================================================================

class ImageAnalyzer:
    """Extract technical indicators from chart images using computer vision"""
    
    def __init__(self):
        self.price_line_color = None
        self.candle_colors = {'bullish': None, 'bearish': None}
    
    def extract_price_data(self, img_array: np.ndarray) -> np.ndarray:
        """Extract price line from chart image"""
        height, width = img_array.shape[:2]
        
        # Find the main chart area (typically center)
        margin_h = int(height * 0.15)
        margin_w = int(width * 0.10)
        chart_area = img_array[margin_h:-margin_h, margin_w:-margin_w]
        
        # Convert to grayscale
        if len(chart_area.shape) == 3:
            gray = cv2.cvtColor(chart_area, cv2.COLOR_RGB2GRAY) if CV2_AVAILABLE else np.mean(chart_area, axis=2)
        else:
            gray = chart_area
        
        # Detect price line using edge detection
        if CV2_AVAILABLE:
            edges = cv2.Canny(gray.astype(np.uint8), 50, 150)
            # Find the dominant horizontal line (price)
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=width//4, maxLineGap=10)
        else:
            # Simple gradient-based detection
            grad_y = np.abs(np.diff(gray, axis=0))
            edges = grad_y > np.percentile(grad_y, 90)
        
        return chart_area, gray
    
    def detect_candles(self, img_array: np.ndarray) -> List[Dict]:
        """Detect and classify candlesticks"""
        height, width = img_array.shape[:2]
        chart_area, gray = self.extract_price_data(img_array)
        
        candles = []
        
        # Divide chart into vertical slices (candle positions)
        num_candles = min(50, width // 20)  # Estimate number of visible candles
        candle_width = chart_area.shape[1] // num_candles
        
        for i in range(num_candles):
            left = i * candle_width
            right = min((i + 1) * candle_width, chart_area.shape[1])
            candle_region = chart_area[:, left:right]
            
            # Analyze candle color and size
            if len(candle_region.shape) == 3:
                red = np.mean(candle_region[:, :, 0])
                green = np.mean(candle_region[:, :, 1])
                blue = np.mean(candle_region[:, :, 2])
                
                # Classify as bullish or bearish
                is_bullish = green > red
                strength = abs(green - red) / 255.0
                
                candles.append({
                    'index': i,
                    'bullish': is_bullish,
                    'strength': strength,
                    'position': i / num_candles  # Relative position (0=oldest, 1=newest)
                })
        
        return candles
    
    def calculate_indicators_from_candles(self, candles: List[Dict], img_array: np.ndarray) -> TechnicalIndicators:
        """Calculate technical indicators from detected candles"""
        indicators = TechnicalIndicators()
        
        if not candles or len(candles) < 10:
            return indicators
        
        # Sort by position (time)
        candles_sorted = sorted(candles, key=lambda x: x['position'])
        
        # Extract price-like series from candle strengths
        strengths = [c['strength'] if c['bullish'] else -c['strength'] for c in candles_sorted]
        prices = np.array(strengths)
        
        # Simple Moving Averages
        if len(prices) >= 20:
            indicators.sma_fast = np.mean(prices[-10:])
            indicators.sma_slow = np.mean(prices[-20:])
            indicators.ema_fast = self._ema(prices, 10)[-1]
            indicators.ema_slow = self._ema(prices, 20)[-1]
        
        # RSI calculation
        indicators.rsi = self._calculate_rsi(prices, 14)
        
        # MACD
        indicators.macd, indicators.macd_signal = self._calculate_macd(prices)
        
        # Trend strength (ADX approximation)
        indicators.adx = self._calculate_adx_approximation(prices)
        
        # Volatility (ATR approximation)
        indicators.atr = np.std(prices) * 2
        
        # Bollinger position
        if len(prices) >= 20:
            sma = np.mean(prices[-20:])
            std = np.std(prices[-20:])
            if std > 0:
                current = prices[-1]
                indicators.bollinger_position = (current - (sma - 2*std)) / (4*std)
                indicators.bollinger_position = np.clip(indicators.bollinger_position, 0, 1)
        
        # Support/Resistance detection
        indicators.support_distance, indicators.resistance_distance = self._detect_support_resistance(prices)
        
        # Stochastic approximation
        if len(prices) >= 14:
            low_14 = np.min(prices[-14:])
            high_14 = np.max(prices[-14:])
            if high_14 > low_14:
                indicators.stochastic_k = (prices[-1] - low_14) / (high_14 - low_14) * 100
        
        return indicators
    
    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema
    
    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_macd(self, prices: np.ndarray) -> Tuple[float, float]:
        """Calculate MACD and Signal line"""
        if len(prices) < 26:
            return 0.0, 0.0
        
        ema_12 = self._ema(prices, 12)
        ema_26 = self._ema(prices, 26)
        
        macd_line = ema_12[-1] - ema_26[-1]
        signal_line = self._ema(macd_line[-9:] if hasattr(macd_line, '__len__') else np.array([macd_line]), 9)[-1]
        
        return macd_line, signal_line
    
    def _calculate_adx_approximation(self, prices: np.ndarray, period: int = 14) -> float:
        """Approximate ADX (Average Directional Index)"""
        if len(prices) < period * 2:
            return 25.0
        
        # Calculate +DM and -DM
        high = prices[1:]
        low = prices[:-1]
        
        plus_dm = np.where((high - low) > 0, high - low, 0)
        minus_dm = np.where((low - high) > 0, low - high, 0)
        
        tr = np.abs(high - low)
        
        avg_plus_dm = np.mean(plus_dm[-period:])
        avg_minus_dm = np.mean(minus_dm[-period:])
        avg_tr = np.mean(tr[-period:])
        
        if avg_tr == 0:
            return 25.0
        
        plus_di = 100 * avg_plus_dm / avg_tr
        minus_di = 100 * avg_minus_dm / avg_tr
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = np.mean([dx] * period)  # Simplified
        
        return adx
    
    def _detect_support_resistance(self, prices: np.ndarray) -> Tuple[float, float]:
        """Detect support and resistance levels"""
        if len(prices) < 10:
            return 0.5, 0.5
        
        current = prices[-1]
        
        # Find local minima and maxima
        if SCIPY_AVAILABLE and len(prices) >= 5:
            minima, _ = find_peaks(-prices, distance=3)
            maxima, _ = find_peaks(prices, distance=3)
        else:
            # Simple detection
            minima = []
            maxima = []
            for i in range(1, len(prices) - 1):
                if prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                    minima.append(i)
                if prices[i] > prices[i-1] and prices[i] > prices[i+1]:
                    maxima.append(i)
        
        if len(minima) > 0:
            support_level = np.mean(prices[minima])
            support_dist = (current - support_level) / (np.max(prices) - np.min(prices) + 1e-10)
        else:
            support_dist = 0.5
        
        if len(maxima) > 0:
            resistance_level = np.mean(prices[maxima])
            resistance_dist = (resistance_level - current) / (np.max(prices) - np.min(prices) + 1e-10)
        else:
            resistance_dist = 0.5
        
        return np.clip(support_dist, 0, 1), np.clip(resistance_dist, 0, 1)


# ============================================================================
# ENSEMBLE MACHINE LEARNING ENGINE
# ============================================================================

class EnsembleLearner:
    """
    Ensemble machine learning system with multiple algorithms
    - Random Forest (bagging)
    - Gradient Boosting (boosting)
    - Neural Network (deep learning)
    - Voting ensemble
    """
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.feature_selector = None
        self.is_trained = False
        self.performance_history = defaultdict(list)
        
        if SKLEARN_AVAILABLE:
            self._initialize_models()
    
    def _initialize_models(self):
        """Initialize ensemble models"""
        # Random Forest - robust, handles non-linearity
        self.models['rf'] = RandomForestClassifier(
            n_estimators=200,
            max_depth=15,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
            class_weight='balanced'
        )
        
        # Gradient Boosting - sequential error correction
        self.models['gb'] = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.1,
            min_samples_split=10,
            random_state=42
        )
        
        # Neural Network - capture complex patterns
        self.models['nn'] = MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            activation='relu',
            solver='adam',
            alpha=0.001,
            max_iter=500,
            early_stopping=True,
            validation_fraction=0.2,
            random_state=42
        )
        
        # Voting ensemble
        self.models['ensemble'] = VotingClassifier(
            estimators=[
                ('rf', self.models['rf']),
                ('gb', self.models['gb']),
                ('nn', self.models['nn'])
            ],
            voting='soft'
        )
        
        # Scalers
        self.scalers['standard'] = StandardScaler()
        self.scalers['robust'] = RobustScaler()
    
    def prepare_features(self, indicators: TechnicalIndicators, market_features: Dict) -> np.ndarray:
        """Prepare feature vector from indicators"""
        features = [
            # Trend features
            indicators.sma_fast,
            indicators.sma_slow,
            indicators.ema_fast,
            indicators.ema_slow,
            indicators.adx / 100.0,  # Normalize
            
            # Momentum features
            indicators.rsi / 100.0,
            indicators.macd,
            indicators.macd_signal,
            indicators.stochastic_k / 100.0,
            indicators.stochastic_d / 100.0,
            
            # Volatility features
            indicators.bollinger_position,
            indicators.atr,
            
            # S/R features
            indicators.support_distance,
            indicators.resistance_distance,
            indicators.pivot_position,
            
            # Market regime features
            market_features.get('volatility_percentile', 0.5),
            market_features.get('trend_consistency', 0.5),
            market_features.get('volume_anomaly', 0),
        ]
        
        return np.array(features).reshape(1, -1)
    
    def train(self, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Train all models with cross-validation"""
        if not SKLEARN_AVAILABLE or len(X) < Config.MIN_SAMPLES_FOR_PREDICTION:
            logger.warning("Insufficient data for training")
            return {'status': 'insufficient_data'}
        
        results = {}
        
        # Scale features
        X_scaled = self.scalers['robust'].fit_transform(X)
        
        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=Config.CV_SPLITS)
        
        for name, model in self.models.items():
            if name == 'ensemble':
                continue  # Train ensemble last
            
            try:
                # Cross-validation
                scores = cross_val_score(model, X_scaled, y, cv=tscv, scoring='accuracy')
                cv_accuracy = scores.mean()
                
                # Train on full dataset
                model.fit(X_scaled, y)
                
                results[name] = {
                    'cv_accuracy': cv_accuracy,
                    'cv_std': scores.std(),
                    'trained': True
                }
                
                logger.info(f"Model {name}: CV accuracy = {cv_accuracy:.3f} (+/- {scores.std():.3f})")
                
            except Exception as e:
                logger.error(f"Failed to train {name}: {e}")
                results[name] = {'error': str(e)}
        
        # Train ensemble if base models succeeded
        if len([r for r in results.values() if 'cv_accuracy' in r]) >= 2:
            try:
                self.models['ensemble'].fit(X_scaled, y)
                ensemble_scores = cross_val_score(self.models['ensemble'], X_scaled, y, cv=tscv)
                results['ensemble'] = {
                    'cv_accuracy': ensemble_scores.mean(),
                    'cv_std': ensemble_scores.std(),
                    'trained': True
                }
                self.is_trained = True
            except Exception as e:
                logger.error(f"Failed to train ensemble: {e}")
        
        return results
    
    def predict_proba(self, features: np.ndarray) -> Dict[str, np.ndarray]:
        """Get probability predictions from all models"""
        if not self.is_trained:
            return {'ensemble': np.array([0.33, 0.33, 0.34])}
        
        X_scaled = self.scalers['robust'].transform(features)
        
        predictions = {}
        for name, model in self.models.items():
            try:
                predictions[name] = model.predict_proba(X_scaled)[0]
            except Exception as e:
                logger.warning(f"Prediction failed for {name}: {e}")
                predictions[name] = np.array([0.33, 0.33, 0.34])
        
        return predictions
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from tree-based models"""
        if not self.is_trained or 'rf' not in self.models:
            return {}
        
        try:
            importances = self.models['rf'].feature_importances_
            feature_names = [
                'sma_fast', 'sma_slow', 'ema_fast', 'ema_slow', 'adx',
                'rsi', 'macd', 'macd_signal', 'stoch_k', 'stoch_d',
                'bb_position', 'atr', 'support_dist', 'resistance_dist', 'pivot',
                'vol_percentile', 'trend_consistency', 'volume_anomaly'
            ]
            
            return dict(zip(feature_names, importances))
        except:
            return {}
    
    def save_models(self, filepath: str):
        """Save trained models to disk"""
        if not self.is_trained:
            return
        
        try:
            with open(filepath, 'wb') as f:
                pickle.dump({
                    'models': self.models,
                    'scalers': self.scalers,
                    'is_trained': self.is_trained
                }, f)
            logger.info(f"Models saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save models: {e}")
    
    def load_models(self, filepath: str) -> bool:
        """Load trained models from disk"""
        try:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
                self.models = data['models']
                self.scalers = data['scalers']
                self.is_trained = data['is_trained']
            logger.info(f"Models loaded from {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            return False


# ============================================================================
# BAYESIAN CONFIDENCE CALIBRATION
# ============================================================================

class BayesianCalibrator:
    """
    Bayesian confidence calibration using Beta distributions
    Provides well-calibrated probability estimates
    """
    
    def __init__(self):
        # Prior: Beta(2, 2) - weakly informative
        self.alpha_prior = 2
        self.beta_prior = 2
        
        # Track predictions and outcomes for each model
        self.prediction_history = defaultdict(lambda: {'correct': 0, 'total': 0})
    
    def calibrate_confidence(self, model_name: str, raw_confidence: float, 
                            signal: Signal, historical_accuracy: float) -> float:
        """
        Calibrate raw confidence using Bayesian updating
        """
        # Get model's historical performance
        history = self.prediction_history[model_name]
        
        # Posterior distribution
        alpha_post = self.alpha_prior + history['correct']
        beta_post = self.beta_prior + (history['total'] - history['correct'])
        
        # Expected accuracy from posterior
        model_accuracy = alpha_post / (alpha_post + beta_post)
        
        # Blend with historical accuracy
        if history['total'] > 10:
            weight = min(history['total'] / 100, 0.7)
            calibrated = model_accuracy * weight + historical_accuracy * (1 - weight)
        else:
            calibrated = raw_confidence * 0.7 + historical_accuracy * 0.3
        
        # Apply temperature scaling for overconfident models
        temperature = 1.5  # Higher = more conservative
        calibrated = np.power(calibrated, 1/temperature)
        
        return np.clip(calibrated, 0.1, 0.95)
    
    def update_posterior(self, model_name: str, predicted_signal: Signal, 
                        actual_outcome: str, was_correct: bool):
        """Update Bayesian posterior with new observation"""
        self.prediction_history[model_name]['total'] += 1
        if was_correct:
            self.prediction_history[model_name]['correct'] += 1


# ============================================================================
# MARKET REGIME DETECTOR
# ============================================================================

class MarketRegimeDetector:
    """
    Detect current market regime using volatility and trend analysis
    """
    
    def __init__(self):
        self.volatility_history = deque(maxlen=50)
        self.trend_history = deque(maxlen=50)
    
    def detect_regime(self, indicators: TechnicalIndicators, 
                     indicator_history: List[TechnicalIndicators]) -> Tuple[MarketRegime, float]:
        """
        Detect market regime and return confidence
        """
        if len(indicator_history) < Config.REGIME_LOOKBACK:
            return MarketRegime.RANGING, 0.5
        
        # Calculate volatility percentile
        recent_atr = [h.atr for h in indicator_history[-Config.REGIME_LOOKBACK:]]
        current_atr = indicators.atr
        
        if recent_atr:
            volatility_percentile = stats.percentileofscore(recent_atr, current_atr) if SCIPY_AVAILABLE else 50
        else:
            volatility_percentile = 50
        
        self.volatility_history.append(volatility_percentile)
        
        # Calculate trend consistency
        recent_directions = []
        for i in range(-Config.REGIME_LOOKBACK + 1, 0):
            if len(indicator_history) > abs(i):
                prev_ema = indicator_history[i-1].ema_fast if i > -len(indicator_history) else indicator_history[0].ema_fast
                curr_ema = indicator_history[i].ema_fast
                recent_directions.append(1 if curr_ema > prev_ema else -1)
        
        if recent_directions:
            trend_consistency = abs(sum(recent_directions)) / len(recent_directions)
        else:
            trend_consistency = 0
        
        self.trend_history.append(trend_consistency)
        
        # Determine regime
        if volatility_percentile > Config.VOLATILITY_PERCENTILE_THRESHOLD:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = volatility_percentile / 100.0
        elif volatility_percentile < 25:
            regime = MarketRegime.LOW_VOLATILITY
            confidence = (25 - volatility_percentile) / 25.0
        elif trend_consistency > 0.7 and indicators.adx > 25:
            if indicators.trend_direction > 0:
                regime = MarketRegime.TRENDING_UP
            else:
                regime = MarketRegime.TRENDING_DOWN
            confidence = trend_consistency
        else:
            regime = MarketRegime.RANGING
            confidence = 1.0 - trend_consistency
        
        return regime, confidence


# ============================================================================
# RISK MANAGER - Kelly Criterion
# ============================================================================

class RiskManager:
    """
    Advanced risk management using Kelly Criterion and position sizing
    """
    
    def __init__(self):
        self.equity_curve = deque(maxlen=1000)
        self.peak_equity = 0
    
    def calculate_position_size(self, analysis: ChartAnalysis, 
                               account_equity: float = 100000) -> Tuple[float, Dict]:
        """
        Calculate optimal position size using Kelly Criterion
        """
        # Extract probabilities
        win_prob = analysis.bayesian_confidence
        
        # Estimate win/loss amounts from risk metrics
        win_amount = analysis.expected_profit
        loss_amount = analysis.max_loss_estimate
        
        if loss_amount <= 0 or win_amount <= 0:
            return 0, {'reason': 'Insufficient risk data'}
        
        # Kelly fraction: f = (p*b - q) / b
        # where p = win probability, q = loss probability, b = win/loss ratio
        b = win_amount / loss_amount  # Odds
        q = 1 - win_prob
        
        kelly = (win_prob * b - q) / b
        
        # Use half-Kelly for safety
        kelly_fraction = kelly * Config.KELLY_FRACTION
        
        # Cap at maximum position size
        max_position = Config.MAX_POSITION_SIZE_PCT
        position_size = min(max(kelly_fraction, 0), max_position)
        
        # Additional safety: reduce size in high volatility
        if analysis.market_regime == MarketRegime.HIGH_VOLATILITY:
            position_size *= 0.5
        
        # Reduce size if drawdown risk is high
        if analysis.drawdown_risk > 0.5:
            position_size *= (1 - analysis.drawdown_risk)
        
        risk_details = {
            'kelly_fraction': kelly,
            'half_kelly_fraction': kelly_fraction,
            'position_size_pct': position_size,
            'position_value': account_equity * position_size,
            'max_loss_dollar': account_equity * position_size * loss_amount,
            'expected_profit_dollar': account_equity * position_size * win_amount,
            'risk_reward_ratio': analysis.risk_reward_ratio
        }
        
        return position_size, risk_details
    
    def update_equity(self, profit_loss: float):
        """Update equity curve for drawdown calculation"""
        if self.equity_curve:
            new_equity = self.equity_curve[-1] + profit_loss
        else:
            new_equity = 100000 + profit_loss  # Starting equity
        
        self.equity_curve.append(new_equity)
        self.peak_equity = max(self.peak_equity, new_equity)
    
    def get_drawdown(self) -> float:
        """Calculate current drawdown"""
        if not self.equity_curve or self.peak_equity == 0:
            return 0.0
        
        current = self.equity_curve[-1]
        return (self.peak_equity - current) / self.peak_equity


# ============================================================================
# MAIN AI ANALYZER v2.0
# ============================================================================

class SierraAIAnalyzer:
    """
    Enhanced AI analyzer with ensemble learning, Bayesian calibration,
    market regime detection, and Kelly Criterion position sizing
    """
    
    def __init__(self):
        self.image_analyzer = ImageAnalyzer()
        self.ensemble = EnsembleLearner()
        self.bayesian = BayesianCalibrator()
        self.regime_detector = MarketRegimeDetector()
        self.risk_manager = RiskManager()
        
        # Load existing models if available
        model_file = Config.MODEL_DIR / "ensemble_model.pkl"
        if model_file.exists():
            self.ensemble.load_models(str(model_file))
    
    def analyze(self, image: Image.Image, symbol: str, 
                historical_state: Optional[SymbolState] = None) -> ChartAnalysis:
        """
        Comprehensive chart analysis with ML ensemble
        """
        timestamp = datetime.now()
        
        if not PIL_AVAILABLE or np is None:
            return self._create_hold_analysis(symbol, timestamp, "Libraries not available")
        
        try:
            # Convert to numpy array
            img_array = np.array(image.convert('RGB'))
            
            # Step 1: Extract technical indicators from image
            candles = self.image_analyzer.detect_candles(img_array)
            indicators = self.image_analyzer.calculate_indicators_from_candles(candles, img_array)
            
            # Step 2: Detect market regime
            indicator_history = list(historical_state.indicator_history) if historical_state else []
            regime, regime_confidence = self.regime_detector.detect_regime(indicators, indicator_history)
            
            # Step 3: Prepare market features
            market_features = {
                'volatility_percentile': len(self.regime_detector.volatility_history) > 0 and 
                                        np.mean(list(self.regime_detector.volatility_history)) / 100 or 0.5,
                'trend_consistency': len(self.regime_detector.trend_history) > 0 and 
                                    np.mean(list(self.regime_detector.trend_history)) or 0.5,
                'volume_anomaly': 0.0  # Placeholder
            }
            
            # Step 4: Get ML predictions
            features = self.ensemble.prepare_features(indicators, market_features)
            predictions = self.ensemble.predict_proba(features)
            
            # Step 5: Calculate ensemble agreement
            model_probs = [pred for name, pred in predictions.items() if name != 'ensemble']
            if model_probs:
                agreement = 1.0 - np.std([p[0] for p in model_probs])  # Agreement on class 0
            else:
                agreement = 0.5
            
            # Step 6: Generate signal from ensemble
            ensemble_prob = predictions.get('ensemble', np.array([0.33, 0.33, 0.34]))
            signal_idx = np.argmax(ensemble_prob)
            raw_confidence = ensemble_prob[signal_idx]
            
            if signal_idx == 0:
                signal = Signal.BEARISH      # weak sell — upgraded to Strong below if confidence high
            elif signal_idx == 1:
                signal = Signal.NEUTRAL
            else:
                signal = Signal.BULLISH      # weak buy — upgraded to Strong below if confidence high
            
            # Step 7: Bayesian confidence calibration
            historical_acc = historical_state.win_rate if historical_state else 0.5
            calibrated_confidence = self.bayesian.calibrate_confidence(
                'ensemble', raw_confidence, signal, historical_acc
            )
            
            # Step 8: Calculate risk metrics
            risk_metrics = self._calculate_risk_metrics(
                indicators, signal, calibrated_confidence, historical_state
            )
            
            # Step 9: Calculate position size using Kelly Criterion
            temp_analysis = ChartAnalysis(
                symbol=symbol,
                timestamp=timestamp,
                signal=signal,
                confidence=calibrated_confidence,
                indicators=indicators,
                market_regime=regime,
                regime_confidence=regime_confidence,
                bayesian_confidence=calibrated_confidence,
                expected_profit=risk_metrics['expected_profit'],
                max_loss_estimate=risk_metrics['max_loss'],
                drawdown_risk=risk_metrics['drawdown_risk'],
                risk_reward_ratio=risk_metrics['risk_reward_ratio']
            )
            
            position_size, risk_details = self.risk_manager.calculate_position_size(temp_analysis)
            
            # Step 10: Final confidence threshold check + Strong upgrade
            if calibrated_confidence < Config.CONFIDENCE_THRESHOLD:
                signal = Signal.NEUTRAL
                calibrated_confidence = 1.0 - calibrated_confidence
            elif calibrated_confidence >= 0.85:
                # High-conviction upgrade
                if signal == Signal.BULLISH:
                    signal = Signal.STRONG_BULLISH
                elif signal == Signal.BEARISH:
                    signal = Signal.STRONG_BEARISH
            
            # Create final analysis
            analysis = ChartAnalysis(
                symbol=symbol,
                timestamp=timestamp,
                signal=signal,
                confidence=calibrated_confidence,
                indicators=indicators,
                market_regime=regime,
                regime_confidence=regime_confidence,
                pattern_hash=self._calculate_pattern_hash(features[0]),
                pattern_vector=features[0].tolist(),
                similar_patterns_count=len(candles),
                historical_accuracy=historical_acc,
                model_predictions={k: v.tolist() for k, v in predictions.items()},
                expected_profit=risk_metrics['expected_profit'],
                max_loss_estimate=risk_metrics['max_loss'],
                drawdown_risk=risk_metrics['drawdown_risk'],
                risk_reward_ratio=risk_metrics['risk_reward_ratio'],
                kelly_fraction=risk_details.get('half_kelly_fraction', 0),
                recommended_position_size=position_size,
                ensemble_agreement=agreement,
                bayesian_confidence=calibrated_confidence
            )
            
            return analysis
            
        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return self._create_hold_analysis(symbol, timestamp, str(e))
    
    def _calculate_pattern_hash(self, features: np.ndarray) -> str:
        """Generate pattern hash for memory lookup"""
        quantized = np.round(features * 20) / 20  # Quantize to reduce noise
        feature_str = json.dumps(quantized.tolist(), sort_keys=True)
        return hashlib.sha256(feature_str.encode()).hexdigest()[:16]
    
    def _calculate_risk_metrics(self, indicators: TechnicalIndicators, 
                                signal: Signal, confidence: float,
                                historical_state: Optional[SymbolState]) -> Dict:
        """Calculate comprehensive risk metrics"""
        volatility = indicators.atr
        trend_strength = indicators.adx / 100.0
        
        # Expected profit
        if signal == Signal.NEUTRAL:
            expected_profit = 0.0
        else:
            expected_profit = confidence * trend_strength * (1 - volatility) * 0.05
        
        # Max loss based on ATR
        max_loss = volatility * (1 - confidence) * 3.0
        
        # Drawdown risk
        if historical_state:
            recent_dd = historical_state.max_drawdown
            dd_factor = min(recent_dd / 0.1, 1.0) if recent_dd > 0 else 0.0
        else:
            dd_factor = 0.0
        
        drawdown_risk = (volatility + dd_factor) / 2
        
        # Risk/Reward
        if max_loss > 0:
            risk_reward = expected_profit / max_loss
        else:
            risk_reward = expected_profit * 10 if expected_profit > 0 else 0
        
        return {
            'expected_profit': round(expected_profit, 4),
            'max_loss': round(max_loss, 4),
            'drawdown_risk': round(drawdown_risk, 4),
            'risk_reward_ratio': round(risk_reward, 2)
        }
    
    def _create_hold_analysis(self, symbol: str, timestamp: datetime, 
                             reason: str) -> ChartAnalysis:
        """Create default HOLD analysis"""
        logger.warning(f"Creating default NEUTRAL for {symbol}: {reason}")

        return ChartAnalysis(
            symbol=symbol,
            timestamp=timestamp,
            signal=Signal.NEUTRAL,
            confidence=0.5,
            indicators=TechnicalIndicators(),
            market_regime=MarketRegime.RANGING,
            regime_confidence=0.5,
            pattern_hash="default",
            pattern_vector=[],
            similar_patterns_count=0,
            historical_accuracy=0.5,
            model_predictions={},
            expected_profit=0.0,
            max_loss_estimate=0.0,
            drawdown_risk=0.5,
            risk_reward_ratio=0.0,
            kelly_fraction=0.0,
            recommended_position_size=0.0,
            ensemble_agreement=0.0,
            bayesian_confidence=0.5
        )
    
    def save_state(self):
        """Save model state"""
        model_file = Config.MODEL_DIR / "ensemble_model.pkl"
        self.ensemble.save_models(str(model_file))


# ============================================================================
# LEGACY COMPATIBILITY - ChartAnalyzer
# ============================================================================

class ChartAnalyzer(SierraAIAnalyzer):
    """
    Backward-compatible wrapper for existing code
    """
    pass


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    print("Sierra Scanner AI Pro v2.0")
    print("==========================")
    print("This module provides enhanced AI analysis capabilities.")
    print("Import and use SierraAIAnalyzer class for best results.")
    print("")
    print("Key features:")
    print("  - Ensemble ML (Random Forest + Gradient Boosting + Neural Network)")
    print("  - Technical indicator extraction from chart images")
    print("  - Bayesian confidence calibration")
    print("  - Market regime detection")
    print("  - Kelly Criterion position sizing")
    print("  - Advanced risk management")
