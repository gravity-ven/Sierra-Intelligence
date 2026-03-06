#!/usr/bin/env python3
"""
Sierra Scanner AI - Advanced Screenshot-Based Trading Intelligence System

ULTIMATE RULE: "Maximum Profits. Minimum Losses. Minimum Drawdown."

This system:
1. Auto-activates when Sierra Chart is detected running
2. Takes iterative screenshots of all open charts
3. Analyzes chart patterns using AI/ML
4. Recommends BUY, SELL, or HOLD for each symbol
5. Continuously learns and improves from outcomes

Author: AI Trading System
Version: 1.0
"""

import os
import sys
import time
import json
import signal
import threading
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import deque
from enum import Enum
import hashlib

# Third-party imports with graceful fallbacks
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not available. Install with: pip install psutil")

try:
    from PIL import Image, ImageGrab, ImageFilter, ImageEnhance
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: PIL/Pillow not available. Install with: pip install Pillow numpy")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("Warning: psycopg2 not available. Install with: pip install psycopg2-binary")

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("Warning: Flask not available. Install with: pip install flask flask-cors")


# ============================================================================
# CONFIGURATION
# ============================================================================

def _detect_wsl():
    """Detect if running in WSL (called before Config is defined)"""
    try:
        with open('/proc/version', 'r', encoding='utf-8') as f:
            content = f.read().lower()
            return 'microsoft' in content or 'wsl' in content
    except:
        return False

def _load_config_file():
    """Load configuration from JSON file if it exists"""
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
                print(f"Warning: Failed to load config from {config_path}: {e}")
    return {}


class Config:
    """Global configuration for Sierra Scanner AI"""

    # Load external config file
    _EXTERNAL_CONFIG = _load_config_file()

    # Detect WSL at class definition time
    _IS_WSL = _detect_wsl()
    _ON_MACOS = __import__('platform').system() == 'Darwin'

    # Sierra Chart paths - use WSL paths if in WSL; None on macOS (Sierra Chart is Windows-only)
    SIERRA_CHART_EXE = "SierraChart_64.exe"
    if _ON_MACOS:
        SIERRA_CHART_PATH = None  # Sierra Chart not available on macOS
    elif _IS_WSL:
        SIERRA_CHART_PATH = Path("/mnt/c/Users/Quantum/Downloads/SierraChart")
    else:
        SIERRA_CHART_PATH = Path(r"C:\Users\Quantum\Downloads\SierraChart")
    DATA_PATH = SIERRA_CHART_PATH / "Data" if SIERRA_CHART_PATH else None
    ACS_SOURCE_PATH = SIERRA_CHART_PATH / "ACS_Source" if SIERRA_CHART_PATH else None

    # Screenshot settings (can be overridden by config file)
    _scanner_cfg = _EXTERNAL_CONFIG.get('scanner', {})
    SCREENSHOT_INTERVAL = _scanner_cfg.get('screenshot_interval', 5)
    SCREENSHOT_DIR = ACS_SOURCE_PATH / "screenshots"
    MAX_SCREENSHOTS_PER_SYMBOL = _scanner_cfg.get('max_screenshots_per_symbol', 100)

    # AI Analysis settings
    CONFIDENCE_THRESHOLD = _scanner_cfg.get('confidence_threshold', 0.65)
    PATTERN_MEMORY_SIZE = 1000  # Patterns to remember per symbol
    LEARNING_RATE = 0.1

    # Database settings (PostgreSQL ONLY - NO SQLite!)
    DB_NAME = "sierra_scanner_db"
    DB_USER = "sierra_user"
    DB_PASSWORD = "sierra_secure_pass"
    DB_HOST = "localhost"
    DB_PORT = 5432

    # API settings (can be overridden by config file)
    _api_cfg = _EXTERNAL_CONFIG.get('api', {})
    API_HOST = _api_cfg.get('host', "0.0.0.0")
    API_PORT = _api_cfg.get('port', 5015)

    # Logging
    LOG_FILE = ACS_SOURCE_PATH / "logs" / "sierra_scanner_ai.log"
    LOG_LEVEL = logging.INFO

    # Windows Python path (for WSL screenshot capture)
    WINDOWS_PYTHON = "/mnt/c/Python313/pythonw.exe"
    SCREENSHOT_HELPER = Path(__file__).parent / "sierra_screenshot_helper.py"

    # Grid Configuration - LOADED FROM CONFIG FILE
    # Edit sierra_scanner_config.json to match your Sierra Chart layout
    _grid_cfg = _EXTERNAL_CONFIG.get('grid', {})
    GRID_COLS = _grid_cfg.get('cols', 8)
    GRID_ROWS = _grid_cfg.get('rows', 4)  # Default to 4 rows now
    GRID_SYMBOLS = _grid_cfg.get('symbols', ['M2K', 'MBT', 'MCL', 'MES', 'MET', 'MGC', 'MNQ', 'MYM'])
    GRID_TIMEFRAMES = _grid_cfg.get('timeframes', ['Daily', 'Weekly', 'Monthly', 'Yearly'])

    # Auto-detection settings
    _auto_cfg = _EXTERNAL_CONFIG.get('auto_detect', {})
    AUTO_DETECT_SYMBOLS = _auto_cfg.get('symbols_from_data', True)


# ============================================================================
# WSL DETECTION AND WINDOWS PYTHON HELPERS
# ============================================================================

def is_wsl() -> bool:
    """Detect if running in Windows Subsystem for Linux"""
    try:
        with open('/proc/version', 'r', encoding='utf-8') as f:
            return 'microsoft' in f.read().lower() or 'wsl' in f.read().lower()
    except:
        return False

def wsl_to_windows_path(wsl_path: str) -> str:
    """Convert WSL path to Windows path"""
    path_str = str(wsl_path)
    if path_str.startswith('/mnt/c/'):
        return path_str.replace('/mnt/c/', 'C:\\\\').replace('/', '\\\\')
    elif path_str.startswith('/mnt/'):
        # Handle other drive letters like /mnt/d/
        drive = path_str[5]
        return path_str.replace(f'/mnt/{drive}/', f'{drive.upper()}:\\\\').replace('/', '\\\\')
    return path_str

def run_windows_python(script_path: str, *args) -> dict:
    """Run a Python script using Windows Python from WSL"""
    try:
        # Convert WSL path to Windows path for the script
        win_script = wsl_to_windows_path(script_path)

        # Convert any path arguments as well
        converted_args = []
        for arg in args:
            if str(arg).startswith('/mnt/'):
                converted_args.append(wsl_to_windows_path(str(arg)))
            else:
                converted_args.append(str(arg))

        cmd = [Config.WINDOWS_PYTHON, win_script] + converted_args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

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


IS_WSL = is_wsl()


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure logging for the application"""
    log_dir = Config.LOG_FILE.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format='%(asctime)s | %(levelname)s | %(message)s',
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
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class ChartAnalysis:
    """Analysis result for a single chart"""
    symbol: str
    timestamp: datetime
    signal: Signal
    confidence: float

    # Pattern features
    trend_direction: float  # -1 to 1 (bearish to bullish)
    trend_strength: float   # 0 to 1
    support_proximity: float  # 0 to 1 (distance to support)
    resistance_proximity: float  # 0 to 1 (distance to resistance)
    momentum: float  # -1 to 1
    volatility: float  # 0 to 1
    volume_trend: float  # -1 to 1

    # AI learning data
    pattern_hash: str = ""
    similar_patterns_count: int = 0
    historical_accuracy: float = 0.5

    # Risk metrics (ULTIMATE RULE compliance)
    expected_profit: float = 0.0
    max_loss_estimate: float = 0.0
    drawdown_risk: float = 0.0
    risk_reward_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['signal'] = self.signal.value
        result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class SymbolState:
    """State tracking for each symbol"""
    symbol: str
    chartbook: str = ""
    chart_number: int = 0
    window_handle: int = 0

    # Analysis history
    analyses: deque = field(default_factory=lambda: deque(maxlen=100))
    last_screenshot: Optional[datetime] = None
    last_analysis: Optional[ChartAnalysis] = None

    # Learning data
    pattern_memory: Dict[str, Dict] = field(default_factory=dict)
    prediction_outcomes: List[Dict] = field(default_factory=list)

    # Performance tracking
    total_predictions: int = 0
    correct_predictions: int = 0
    total_profit: float = 0.0
    max_drawdown: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.5
        return self.correct_predictions / self.total_predictions


@dataclass
class ScannerState:
    """Global scanner state"""
    is_running: bool = False
    sierra_chart_detected: bool = False
    scan_count: int = 0
    last_scan: Optional[datetime] = None

    symbols: Dict[str, SymbolState] = field(default_factory=dict)

    # Global performance
    global_win_rate: float = 0.5
    global_profit: float = 0.0
    global_drawdown: float = 0.0


# ============================================================================
# SIERRA CHART DETECTION
# ============================================================================

class SierraChartDetector:
    """Detects and monitors Sierra Chart application"""

    @staticmethod
    def is_running() -> bool:
        """Check if Sierra Chart is currently running"""
        if IS_WSL:
            # Check via tasklist.exe command in WSL
            try:
                result = subprocess.run(
                    ['tasklist.exe', '/FI', f'IMAGENAME eq {Config.SIERRA_CHART_EXE}'],
                    capture_output=True, text=True
                )
                return Config.SIERRA_CHART_EXE.lower() in result.stdout.lower()
            except Exception:
                return False

        # Define CREATE_NO_WINDOW for Windows (0x08000000)
        CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

        if not PSUTIL_AVAILABLE:
            # Fallback: check via tasklist command
            try:
                result = subprocess.run(
                    ['tasklist', '/FI', f'IMAGENAME eq {Config.SIERRA_CHART_EXE}'],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW
                )
                return Config.SIERRA_CHART_EXE.lower() in result.stdout.lower()
            except Exception:
                return False

        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and Config.SIERRA_CHART_EXE.lower() in proc.info['name'].lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    @staticmethod
    def get_windows() -> List[Dict]:
        """Get all Sierra Chart windows with their titles"""
        windows = []

        # If running in WSL, use Windows Python helper
        if IS_WSL:
            try:
                result = run_windows_python(str(Config.SCREENSHOT_HELPER), 'enumerate')
                if 'error' not in result and 'windows' in result:
                    # Convert rect lists to tuples for consistency
                    for win in result['windows']:
                        win['rect'] = tuple(win['rect'])
                    return result['windows']
                else:
                    logger.warning(f"WSL window enumeration: {result.get('error', 'Unknown error')}")
                    return windows
            except Exception as e:
                logger.warning(f"WSL window enumeration failed: {e}")
                return windows

        if not PSUTIL_AVAILABLE:
            return windows

        try:
            # Use Windows API via ctypes for window enumeration (native Windows only)
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # Window enumeration callback
            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            def callback(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd) + 1
                    buffer = ctypes.create_unicode_buffer(length)
                    user32.GetWindowTextW(hwnd, buffer, length)
                    title = buffer.value

                    if 'SierraChart' in title or 'Sierra Chart' in title:
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        windows.append({
                            'hwnd': hwnd,
                            'title': title,
                            'rect': (rect.left, rect.top, rect.right, rect.bottom)
                        })
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)

        except Exception as e:
            logger.warning(f"Window enumeration failed: {e}")

        return windows

    @staticmethod
    def get_open_chartbooks() -> List[str]:
        """Get list of open chartbooks from Sierra Chart config"""
        chartbooks = []

        # Read from Sierra Chart config
        config_file = Config.SIERRA_CHART_PATH / "Sierra4.config"
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Parse chartbook references
                    import re
                    matches = re.findall(r'Chartbook.*?=\s*"?([^"\n]+)"?', content)
                    chartbooks.extend(matches)
            except Exception as e:
                logger.warning(f"Failed to read chartbooks: {e}")

        # Also check Data folder for .Chartbook files
        data_path = Config.DATA_PATH
        if data_path.exists():
            for cb_file in data_path.glob("*.Chartbook"):
                chartbooks.append(cb_file.stem)

        return list(set(chartbooks))

    @staticmethod
    def extract_symbol_from_title(title: str) -> Optional[str]:
        """Extract symbol name from Sierra Chart window title"""
        import re

        # Sierra Chart window title formats:
        # "Sierra Chart ... [#1 MET-202602-CME-USD-0.1 [C][M] Daily L:5 | Micro Ether Futures - CME (Feb26)]"
        # "Sierra Chart ... [#2 DA-202602-CME-USD-2000 [C][M] Daily | Class III Milk Futures...]"
        patterns = [
            # New format: [#N SYMBOL-YYYYMM-EXCHANGE...] - extract base symbol
            r'\[#\d+\s+([A-Z0-9]{1,5})-\d{6}',
            # Alternative: extract full contract symbol
            r'\[#\d+\s+([A-Z0-9]+-\d{6})-[A-Z]{2,4}',
            # Pattern from pipe: | Description - Exchange
            r'\|\s*(?:Micro\s+)?([A-Za-z]+)\s+(?:Futures|Options)',
            # Standard symbol at start
            r'^([A-Z0-9.]+(?:-[A-Z0-9]+)?)\s*[-–]',
            # "Chart #N - Symbol"
            r'Chart\s*#?\d*\s*[-–]\s*([A-Z0-9.]+)',
            # Symbol with timeframe
            r'([A-Z]{1,5}(?:\.[A-Z])?)\s+(?:Daily|Weekly|Monthly)',
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                symbol = match.group(1).strip()
                # Clean up the symbol
                if symbol:
                    return symbol.upper()

        return None

    @staticmethod
    def get_active_symbols_from_data() -> List[str]:
        """Get active symbols from recently modified data files"""
        import re
        from datetime import datetime, timedelta

        symbols = []
        data_path = Config.DATA_PATH

        if not data_path.exists():
            return symbols

        # Look for .dly files modified in the last 24 hours
        cutoff_time = datetime.now() - timedelta(hours=24)

        try:
            for dly_file in data_path.glob("*.dly"):
                try:
                    mtime = datetime.fromtimestamp(dly_file.stat().st_mtime)
                    if mtime > cutoff_time:
                        # Extract symbol from filename (e.g., M2K-202603-CME-USD.dly)
                        match = re.match(r'^([A-Z0-9]{2,5})-\d{6}', dly_file.stem)
                        if match:
                            symbol = match.group(1)
                            if symbol not in symbols:
                                symbols.append(symbol)
                                logger.info(f"Found active symbol: {symbol} from {dly_file.name}")
                except Exception:
                    continue
            logger.info(f"Total active symbols found: {len(symbols)}")
        except Exception as e:
            logger.warning(f"Failed to scan data files: {e}")

        return symbols


# ============================================================================
# SCREENSHOT CAPTURE
# ============================================================================

class ScreenshotCapture:
    """Captures screenshots of Sierra Chart windows"""

    def __init__(self):
        self.screenshot_dir = Config.SCREENSHOT_DIR
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def capture_full_screen(self) -> Optional[Image.Image]:
        """Capture the entire screen"""
        # If running in WSL, use Windows Python helper
        if IS_WSL:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = str(self.screenshot_dir / f"full_screen_{timestamp}.png")
                win_path = output_path.replace('/mnt/c/', 'C:/')

                result = run_windows_python(str(Config.SCREENSHOT_HELPER), 'capture', win_path)

                if 'error' not in result and result.get('success'):
                    # Load the saved image
                    return Image.open(output_path)
                else:
                    logger.error(f"WSL screenshot failed: {result.get('error', 'Unknown error')}")
                    return None
            except Exception as e:
                logger.error(f"WSL full screen capture failed: {e}")
                return None

        if not PIL_AVAILABLE:
            return None

        try:
            return ImageGrab.grab()
        except Exception as e:
            logger.error(f"Full screen capture failed: {e}")
            return None

    def capture_window(self, hwnd: int, rect: Tuple[int, int, int, int]) -> Optional[Image.Image]:
        """Capture a specific window by its handle"""
        # If running in WSL, use Windows Python helper
        if IS_WSL:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = str(self.screenshot_dir / f"window_{timestamp}.png")
                win_path = output_path.replace('/mnt/c/', 'C:/')

                left, top, right, bottom = rect
                result = run_windows_python(
                    str(Config.SCREENSHOT_HELPER),
                    'capture-region',
                    str(left), str(top), str(right), str(bottom),
                    win_path
                )

                if 'error' not in result and result.get('success'):
                    return Image.open(output_path)
                else:
                    logger.error(f"WSL window capture failed: {result.get('error', 'Unknown error')}")
                    return None
            except Exception as e:
                logger.error(f"WSL window capture failed: {e}")
                return None

        if not PIL_AVAILABLE:
            return None

        try:
            # Capture the window region
            left, top, right, bottom = rect
            image = ImageGrab.grab(bbox=(left, top, right, bottom))
            return image
        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            return None

    def capture_all_charts(self, num_charts: int = 5) -> List[Dict]:
        """Capture and split screenshot into individual chart images (WSL optimized)"""
        if IS_WSL:
            try:
                win_dir = str(self.screenshot_dir).replace('/mnt/c/', 'C:/')
                result = run_windows_python(
                    str(Config.SCREENSHOT_HELPER),
                    'capture-all',
                    win_dir,
                    str(num_charts)
                )

                if 'error' not in result and result.get('success'):
                    charts = []
                    for chart in result.get('charts', []):
                        # Convert Windows path back to WSL path (robust version)
                        win_path = str(chart['path'])
                        wsl_path = win_path.replace('C:\\', '/mnt/c/').replace('C:/', '/mnt/c/').replace('\\', '/')
                        # logger.info(f"DEBUG PATH: {win_path} -> {wsl_path}")
                        print(f"DEBUG PATH: {win_path} -> {wsl_path}")
                        try:
                            img = Image.open(wsl_path)
                            charts.append({
                                'index': chart['index'],
                                'image': img,
                                'path': wsl_path,
                                'region': chart['region']
                            })
                        except Exception as e:
                            logger.warning(f"Failed to load chart {chart['index']}: {e}")
                    return charts
                else:
                    logger.error(f"WSL capture-all failed: {result.get('error', 'Unknown error')}")
                    return []
            except Exception as e:
                logger.error(f"WSL capture_all_charts failed: {e}")
                return []

        # Native Windows fallback - capture and split manually
        full_img = self.capture_full_screen()
        if not full_img:
            return []

        width, height = full_img.size
        chart_width = width // num_charts
        charts = []

        for i in range(num_charts):
            left = i * chart_width
            right = (i + 1) * chart_width if i < num_charts - 1 else width

            chart_img = full_img.crop((left, 0, right, height))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chart_path = self.screenshot_dir / f"chart_{i+1}_{timestamp}.png"
            chart_img.save(chart_path, 'PNG')

            charts.append({
                'index': i + 1,
                'image': chart_img,
                'path': str(chart_path),
                'region': [left, 0, right, height]
            })

        return charts

    def capture_grid_charts(self, rows: int = 6, cols: int = 8) -> List[Dict]:
        """Capture and split screenshot into a grid of charts (WSL optimized)"""
        if IS_WSL:
            try:
                win_dir = str(self.screenshot_dir).replace('/mnt/c/', 'C:/')
                result = run_windows_python(
                    str(Config.SCREENSHOT_HELPER),
                    'capture-grid',
                    win_dir,
                    str(rows),
                    str(cols)
                )

                if 'error' not in result and result.get('success'):
                    charts = []
                    for chart in result.get('charts', []):
                        # Convert Windows path back to WSL path (robust version)
                        win_path = str(chart['path'])
                        wsl_path = win_path.replace('C:\\', '/mnt/c/').replace('C:/', '/mnt/c/').replace('\\', '/')
                        # logger.info(f"DEBUG PATH: {win_path} -> {wsl_path}")
                        print(f"DEBUG PATH: {win_path} -> {wsl_path}")
                        try:
                            img = Image.open(wsl_path)
                            charts.append({
                                'row': chart['row'],
                                'col': chart['col'],
                                'image': img,
                                'path': wsl_path,
                                'region': chart['region']
                            })
                        except Exception as e:
                            logger.warning(f"Failed to load chart r{chart['row']}c{chart['col']}: {e}")
                    return charts
                else:
                    logger.error(f"WSL capture-grid failed: {result.get('error', 'Unknown error')}")
                    return []
            except Exception as e:
                logger.error(f"WSL capture_grid_charts failed: {e}")
                return []
        
        # Fallback for non-WSL (not implemented for grid yet)
        return []

    def save_screenshot(self, image: Image.Image, symbol: str) -> Path:
        """Save screenshot with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{timestamp}.png"
        filepath = self.screenshot_dir / filename

        image.save(filepath, "PNG", optimize=True)

        # Cleanup old screenshots
        self._cleanup_old_screenshots(symbol)

        return filepath

    def _cleanup_old_screenshots(self, symbol: str):
        """Remove old screenshots to manage disk space"""
        pattern = f"{symbol}_*.png"
        files = sorted(
            self.screenshot_dir.glob(pattern),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )

        # Keep only the most recent N screenshots
        for old_file in files[Config.MAX_SCREENSHOTS_PER_SYMBOL:]:
            try:
                old_file.unlink()
            except Exception:
                pass


# ============================================================================
# AI ANALYSIS ENGINE
# ============================================================================

class ChartAnalyzer:
    """
    AI-powered chart analysis engine

    Uses image processing and pattern recognition to analyze charts
    and generate BUY/SELL/HOLD recommendations.

    ULTIMATE RULE: "Maximum Profits. Minimum Losses. Minimum Drawdown."
    """

    def __init__(self):
        self.pattern_memory: Dict[str, List[Dict]] = {}
        self.learning_enabled = True

    def analyze_screenshot(
        self,
        image: Image.Image,
        symbol: str,
        historical_state: Optional[SymbolState] = None
    ) -> ChartAnalysis:
        """
        Analyze a chart screenshot and generate trading recommendation
        """
        timestamp = datetime.now()

        if not PIL_AVAILABLE:
            return self._create_hold_analysis(symbol, timestamp, "PIL not available")

        try:
            # Convert to numpy array for analysis
            img_array = np.array(image.convert('RGB'))

            # Extract features from the chart
            features = self._extract_features(img_array)

            # Calculate pattern hash for memory lookup
            pattern_hash = self._calculate_pattern_hash(features)

            # Look up similar patterns in memory
            similar_patterns = self._find_similar_patterns(symbol, pattern_hash, features)

            # Calculate confidence based on historical accuracy
            historical_accuracy = self._calculate_historical_accuracy(
                symbol, similar_patterns, historical_state
            )

            # Generate signal using multi-factor analysis
            signal, confidence = self._generate_signal(
                features, similar_patterns, historical_accuracy, historical_state
            )

            # Calculate risk metrics (ULTIMATE RULE compliance)
            risk_metrics = self._calculate_risk_metrics(
                features, signal, confidence, historical_state
            )

            # Create analysis result
            analysis = ChartAnalysis(
                symbol=symbol,
                timestamp=timestamp,
                signal=signal,
                confidence=confidence,
                trend_direction=features['trend_direction'],
                trend_strength=features['trend_strength'],
                support_proximity=features['support_proximity'],
                resistance_proximity=features['resistance_proximity'],
                momentum=features['momentum'],
                volatility=features['volatility'],
                volume_trend=features['volume_trend'],
                pattern_hash=pattern_hash,
                similar_patterns_count=len(similar_patterns),
                historical_accuracy=historical_accuracy,
                expected_profit=risk_metrics['expected_profit'],
                max_loss_estimate=risk_metrics['max_loss'],
                drawdown_risk=risk_metrics['drawdown_risk'],
                risk_reward_ratio=risk_metrics['risk_reward_ratio']
            )

            # Store pattern for learning
            if self.learning_enabled:
                self._store_pattern(symbol, pattern_hash, features, analysis)

            return analysis

        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            return self._create_hold_analysis(symbol, timestamp, str(e))

    def _extract_features(self, img_array: np.ndarray) -> Dict[str, float]:
        """Extract trading-relevant features from chart image"""
        height, width, _ = img_array.shape

        # Color analysis for trend detection
        # Green typically indicates bullish, Red indicates bearish
        green_channel = img_array[:, :, 1].astype(float)
        red_channel = img_array[:, :, 0].astype(float)
        blue_channel = img_array[:, :, 2].astype(float)

        # Analyze the main chart area (exclude borders)
        margin = int(min(height, width) * 0.1)
        chart_area = img_array[margin:-margin, margin:-margin] if margin > 0 else img_array

        chart_green = chart_area[:, :, 1].astype(float)
        chart_red = chart_area[:, :, 0].astype(float)

        # Trend direction: ratio of green to red pixels (candlesticks)
        green_dominance = np.mean(chart_green > 150)
        red_dominance = np.mean(chart_red > 150)

        if green_dominance + red_dominance > 0:
            trend_direction = (green_dominance - red_dominance) / (green_dominance + red_dominance + 0.001)
        else:
            trend_direction = 0.0

        # Trend strength: consistency of direction
        # Analyze vertical distribution of colored pixels
        h, w, _ = chart_area.shape
        upper_half = chart_area[:h//2]
        lower_half = chart_area[h//2:]

        upper_green = np.mean(upper_half[:, :, 1] > 150)
        lower_green = np.mean(lower_half[:, :, 1] > 150)

        trend_strength = abs(upper_green - lower_green)

        # Support/Resistance proximity (based on edge detection)
        # Convert to grayscale for edge analysis
        gray = np.mean(chart_area, axis=2)

        # Simple edge detection using gradient
        gradient_y = np.abs(np.diff(gray, axis=0))
        gradient_x = np.abs(np.diff(gray, axis=1))

        # Horizontal lines indicate support/resistance
        horizontal_lines = np.sum(gradient_y > 30, axis=1)

        # Find strongest horizontal line positions
        if len(horizontal_lines) > 0:
            max_line_idx = np.argmax(horizontal_lines)
            support_proximity = 1.0 - (max_line_idx / len(horizontal_lines))
            resistance_proximity = max_line_idx / len(horizontal_lines)
        else:
            support_proximity = 0.5
            resistance_proximity = 0.5

        # Momentum: analyze recent price movement pattern
        # Look at right side of chart (recent data)
        recent_area = chart_area[:, -w//4:]
        recent_green = np.mean(recent_area[:, :, 1])
        recent_red = np.mean(recent_area[:, :, 0])

        momentum = (recent_green - recent_red) / 255.0

        # Volatility: variance in the chart
        volatility = np.std(gray) / 128.0  # Normalize to 0-1 range
        volatility = min(volatility, 1.0)

        # Volume trend: look for volume bars (usually at bottom)
        volume_area = chart_area[-h//5:] if h > 20 else chart_area
        volume_intensity = np.mean(volume_area)
        volume_trend = (volume_intensity - 100) / 155.0  # Normalize

        return {
            'trend_direction': float(np.clip(trend_direction, -1, 1)),
            'trend_strength': float(np.clip(trend_strength, 0, 1)),
            'support_proximity': float(np.clip(support_proximity, 0, 1)),
            'resistance_proximity': float(np.clip(resistance_proximity, 0, 1)),
            'momentum': float(np.clip(momentum, -1, 1)),
            'volatility': float(np.clip(volatility, 0, 1)),
            'volume_trend': float(np.clip(volume_trend, -1, 1))
        }

    def _calculate_pattern_hash(self, features: Dict[str, float]) -> str:
        """Generate a hash for pattern similarity matching"""
        # Quantize features to reduce noise
        quantized = {
            k: round(v * 10) / 10 for k, v in features.items()
        }
        feature_str = json.dumps(quantized, sort_keys=True)
        return hashlib.md5(feature_str.encode()).hexdigest()[:12]

    def _find_similar_patterns(
        self,
        symbol: str,
        pattern_hash: str,
        features: Dict[str, float]
    ) -> List[Dict]:
        """Find historically similar patterns"""
        if symbol not in self.pattern_memory:
            return []

        similar = []
        for stored_hash, stored_data in self.pattern_memory[symbol].items():
            # Calculate feature similarity
            similarity = self._calculate_similarity(features, stored_data['features'])
            if similarity > 0.8:  # 80% similar threshold
                similar.append({
                    'hash': stored_hash,
                    'similarity': similarity,
                    **stored_data
                })

        return sorted(similar, key=lambda x: x['similarity'], reverse=True)[:10]

    def _calculate_similarity(self, f1: Dict[str, float], f2: Dict[str, float]) -> float:
        """Calculate cosine similarity between feature sets"""
        if not f1 or not f2:
            return 0.0

        common_keys = set(f1.keys()) & set(f2.keys())
        if not common_keys:
            return 0.0

        v1 = np.array([f1[k] for k in common_keys])
        v2 = np.array([f2[k] for k in common_keys])

        dot = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot / (norm1 * norm2))

    def _calculate_historical_accuracy(
        self,
        symbol: str,
        similar_patterns: List[Dict],
        historical_state: Optional[SymbolState]
    ) -> float:
        """Calculate accuracy based on similar historical patterns"""
        if not similar_patterns:
            return 0.5  # Default to 50%

        weighted_accuracy = 0.0
        total_weight = 0.0

        for pattern in similar_patterns:
            if 'outcome_accuracy' in pattern:
                weight = pattern['similarity']
                weighted_accuracy += pattern['outcome_accuracy'] * weight
                total_weight += weight

        if total_weight > 0:
            base_accuracy = weighted_accuracy / total_weight
        else:
            base_accuracy = 0.5

        # Blend with symbol's overall win rate
        if historical_state and historical_state.total_predictions > 10:
            symbol_weight = min(historical_state.total_predictions / 100, 0.5)
            base_accuracy = (
                base_accuracy * (1 - symbol_weight) +
                historical_state.win_rate * symbol_weight
            )

        return base_accuracy

    def _generate_signal(
        self,
        features: Dict[str, float],
        similar_patterns: List[Dict],
        historical_accuracy: float,
        historical_state: Optional[SymbolState]
    ) -> Tuple[Signal, float]:
        """
        Generate trading signal using multi-factor analysis

        ULTIMATE RULE: "Maximum Profits. Minimum Losses. Minimum Drawdown."
        """
        # Base scores
        buy_score = 0.0
        sell_score = 0.0

        # Factor 1: Trend analysis (weight: 0.35)
        trend = features['trend_direction']
        strength = features['trend_strength']

        if trend > 0.2 and strength > 0.3:
            buy_score += 0.35 * (trend + strength) / 2
        elif trend < -0.2 and strength > 0.3:
            sell_score += 0.35 * abs(trend + strength) / 2

        # Factor 2: Momentum (weight: 0.25)
        momentum = features['momentum']
        if momentum > 0.15:
            buy_score += 0.25 * momentum
        elif momentum < -0.15:
            sell_score += 0.25 * abs(momentum)

        # Factor 3: Support/Resistance proximity (weight: 0.20)
        support_prox = features['support_proximity']
        resist_prox = features['resistance_proximity']

        # Near support = potential buy zone
        if support_prox > 0.7:
            buy_score += 0.20 * support_prox
        # Near resistance = potential sell zone
        if resist_prox > 0.7:
            sell_score += 0.20 * resist_prox

        # Factor 4: Historical pattern accuracy (weight: 0.20)
        if similar_patterns:
            pattern_signal = 0.0
            for pattern in similar_patterns[:5]:
                if 'outcome_signal' in pattern:
                    weight = pattern['similarity']
                    if pattern['outcome_signal'] == 'BUY':
                        pattern_signal += weight
                    elif pattern['outcome_signal'] == 'SELL':
                        pattern_signal -= weight

            if pattern_signal > 0:
                buy_score += 0.20 * min(pattern_signal, 1.0)
            else:
                sell_score += 0.20 * min(abs(pattern_signal), 1.0)

        # Apply historical accuracy modifier
        accuracy_factor = (historical_accuracy - 0.5) * 2  # -1 to 1
        if accuracy_factor > 0:
            buy_score *= (1 + accuracy_factor * 0.2)
            sell_score *= (1 - accuracy_factor * 0.1)
        else:
            buy_score *= (1 + accuracy_factor * 0.1)
            sell_score *= (1 - accuracy_factor * 0.2)

        # ULTIMATE RULE: Risk adjustment
        volatility = features['volatility']

        # High volatility = higher confidence threshold needed
        volatility_penalty = volatility * 0.15
        buy_score -= volatility_penalty
        sell_score -= volatility_penalty

        # Determine signal
        confidence_threshold = Config.CONFIDENCE_THRESHOLD

        if buy_score > sell_score and buy_score > confidence_threshold:
            return Signal.BUY, min(max(buy_score, 0.0), 0.95)
        elif sell_score > buy_score and sell_score > confidence_threshold:
            return Signal.SELL, min(max(sell_score, 0.0), 0.95)
        else:
            # HOLD when uncertain - protect capital
            hold_conf = 1.0 - abs(buy_score) - abs(sell_score)
            return Signal.HOLD, min(max(hold_conf, 0.5), 0.95)

    def _calculate_risk_metrics(
        self,
        features: Dict[str, float],
        signal: Signal,
        confidence: float,
        historical_state: Optional[SymbolState]
    ) -> Dict[str, float]:
        """
        Calculate risk metrics for the ULTIMATE RULE

        Minimum Losses. Minimum Drawdown. Maximum Profits.
        """
        volatility = features['volatility']
        trend_strength = features['trend_strength']

        # Expected profit (normalized estimate)
        if signal == Signal.HOLD:
            expected_profit = 0.0
        else:
            expected_profit = confidence * trend_strength * (1 - volatility)

        # Max loss estimate based on volatility
        max_loss = volatility * (1 - confidence) * 2.0

        # Drawdown risk
        if historical_state and historical_state.max_drawdown > 0:
            recent_drawdown_factor = min(historical_state.max_drawdown / 10.0, 1.0)
        else:
            recent_drawdown_factor = 0.0

        drawdown_risk = (volatility + recent_drawdown_factor) / 2

        # Risk/Reward ratio
        if max_loss > 0:
            risk_reward_ratio = expected_profit / max_loss
        else:
            risk_reward_ratio = expected_profit * 10 if expected_profit > 0 else 0

        return {
            'expected_profit': round(expected_profit, 4),
            'max_loss': round(max_loss, 4),
            'drawdown_risk': round(drawdown_risk, 4),
            'risk_reward_ratio': round(risk_reward_ratio, 2)
        }

    def _store_pattern(
        self,
        symbol: str,
        pattern_hash: str,
        features: Dict[str, float],
        analysis: ChartAnalysis
    ):
        """Store pattern for future learning"""
        if symbol not in self.pattern_memory:
            self.pattern_memory[symbol] = {}

        if len(self.pattern_memory[symbol]) >= Config.PATTERN_MEMORY_SIZE:
            # Remove oldest pattern
            oldest_key = next(iter(self.pattern_memory[symbol]))
            del self.pattern_memory[symbol][oldest_key]

        self.pattern_memory[symbol][pattern_hash] = {
            'features': features,
            'signal': analysis.signal.value,
            'confidence': analysis.confidence,
            'timestamp': analysis.timestamp.isoformat(),
            'outcome_accuracy': 0.5,  # Will be updated with actual outcome
            'outcome_signal': None
        }

    def update_pattern_outcome(
        self,
        symbol: str,
        pattern_hash: str,
        actual_outcome: str,
        profit_loss: float
    ):
        """Update pattern with actual outcome for learning"""
        if symbol not in self.pattern_memory:
            return

        if pattern_hash not in self.pattern_memory[symbol]:
            return

        pattern = self.pattern_memory[symbol][pattern_hash]
        predicted = pattern['signal']

        # Determine if prediction was correct
        is_correct = (
            (predicted == 'BUY' and actual_outcome == 'UP') or
            (predicted == 'SELL' and actual_outcome == 'DOWN') or
            (predicted == 'HOLD' and abs(profit_loss) < 0.01)
        )

        # Update accuracy with exponential moving average
        current_accuracy = pattern['outcome_accuracy']
        learning_rate = Config.LEARNING_RATE

        new_accuracy = current_accuracy * (1 - learning_rate)
        if is_correct:
            new_accuracy += learning_rate * 1.0

        pattern['outcome_accuracy'] = new_accuracy
        pattern['outcome_signal'] = actual_outcome

        logger.info(f"Pattern {pattern_hash} updated: predicted={predicted}, "
                   f"actual={actual_outcome}, accuracy={new_accuracy:.2%}")

    def _create_hold_analysis(
        self,
        symbol: str,
        timestamp: datetime,
        reason: str
    ) -> ChartAnalysis:
        """Create a default HOLD analysis when normal analysis fails"""
        logger.warning(f"Creating default HOLD for {symbol}: {reason}")

        return ChartAnalysis(
            symbol=symbol,
            timestamp=timestamp,
            signal=Signal.HOLD,
            confidence=0.5,
            trend_direction=0.0,
            trend_strength=0.0,
            support_proximity=0.5,
            resistance_proximity=0.5,
            momentum=0.0,
            volatility=0.5,
            volume_trend=0.0,
            pattern_hash="default",
            similar_patterns_count=0,
            historical_accuracy=0.5,
            expected_profit=0.0,
            max_loss_estimate=0.0,
            drawdown_risk=0.5,
            risk_reward_ratio=0.0
        )


# ============================================================================
# DATABASE MANAGER (PostgreSQL ONLY!)
# ============================================================================

class DatabaseManager:
    """
    PostgreSQL database manager for persistent storage

    NO SQLite! PostgreSQL ONLY as per CLAUDE.md requirements.
    """

    def __init__(self):
        self.conn = None
        self._setup_database()

    def _get_connection(self):
        """Get database connection"""
        if not POSTGRES_AVAILABLE:
            logger.warning("PostgreSQL not available")
            return None

        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg2.connect(
                    dbname=Config.DB_NAME,
                    user=Config.DB_USER,
                    password=Config.DB_PASSWORD,
                    host=Config.DB_HOST,
                    port=Config.DB_PORT
                )
            return self.conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return None

    def _setup_database(self):
        """Initialize database tables"""
        conn = self._get_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                # Chart analyses table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS chart_analyses (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        signal VARCHAR(10) NOT NULL,
                        confidence FLOAT NOT NULL,
                        trend_direction FLOAT,
                        trend_strength FLOAT,
                        support_proximity FLOAT,
                        resistance_proximity FLOAT,
                        momentum FLOAT,
                        volatility FLOAT,
                        volume_trend FLOAT,
                        pattern_hash VARCHAR(32),
                        similar_patterns_count INT,
                        historical_accuracy FLOAT,
                        expected_profit FLOAT,
                        max_loss_estimate FLOAT,
                        drawdown_risk FLOAT,
                        risk_reward_ratio FLOAT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_analyses_symbol
                        ON chart_analyses(symbol);
                    CREATE INDEX IF NOT EXISTS idx_analyses_timestamp
                        ON chart_analyses(timestamp);
                """)

                # Pattern memory table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pattern_memory (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        pattern_hash VARCHAR(32) NOT NULL,
                        features JSONB NOT NULL,
                        predicted_signal VARCHAR(10),
                        actual_outcome VARCHAR(10),
                        profit_loss FLOAT,
                        accuracy FLOAT DEFAULT 0.5,
                        timestamp TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, pattern_hash)
                    );

                    CREATE INDEX IF NOT EXISTS idx_patterns_symbol
                        ON pattern_memory(symbol);
                """)

                # Performance tracking table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS performance_tracking (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        date DATE NOT NULL,
                        total_predictions INT DEFAULT 0,
                        correct_predictions INT DEFAULT 0,
                        total_profit FLOAT DEFAULT 0,
                        max_drawdown FLOAT DEFAULT 0,
                        win_rate FLOAT DEFAULT 0.5,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, date)
                    );
                """)

                conn.commit()
                logger.info("Database tables initialized")

        except Exception as e:
            logger.error(f"Database setup failed: {e}")
            conn.rollback()

    def save_analysis(self, analysis: ChartAnalysis):
        """Save analysis to database"""
        conn = self._get_connection()
        if not conn:
            return

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chart_analyses (
                        symbol, timestamp, signal, confidence,
                        trend_direction, trend_strength, support_proximity,
                        resistance_proximity, momentum, volatility, volume_trend,
                        pattern_hash, similar_patterns_count, historical_accuracy,
                        expected_profit, max_loss_estimate, drawdown_risk, risk_reward_ratio
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    analysis.symbol, analysis.timestamp, analysis.signal.value,
                    analysis.confidence, analysis.trend_direction, analysis.trend_strength,
                    analysis.support_proximity, analysis.resistance_proximity,
                    analysis.momentum, analysis.volatility, analysis.volume_trend,
                    analysis.pattern_hash, analysis.similar_patterns_count,
                    analysis.historical_accuracy, analysis.expected_profit,
                    analysis.max_loss_estimate, analysis.drawdown_risk, analysis.risk_reward_ratio
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save analysis: {e}")
            conn.rollback()

    def get_recent_analyses(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """Get recent analyses from database"""
        conn = self._get_connection()
        if not conn:
            return []

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if symbol:
                    cur.execute("""
                        SELECT * FROM chart_analyses
                        WHERE symbol = %s
                        ORDER BY timestamp DESC
                        LIMIT %s
                    """, (symbol, limit))
                else:
                    cur.execute("""
                        SELECT * FROM chart_analyses
                        ORDER BY timestamp DESC
                        LIMIT %s
                    """, (limit,))

                return cur.fetchall()
        except Exception as e:
            logger.error(f"Failed to get analyses: {e}")
            return []

    def close(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()


# ============================================================================
# MAIN SCANNER ENGINE
# ============================================================================

class SierraScannerAI:
    """
    Main Sierra Scanner AI Engine

    Coordinates screenshot capture, AI analysis, and recommendations
    in a continuous loop that auto-activates when Sierra Chart is detected.
    """

    def __init__(self):
        self.state = ScannerState()
        self.detector = SierraChartDetector()
        self.capture = ScreenshotCapture()
        self.analyzer = ChartAnalyzer()
        self.db = DatabaseManager() if POSTGRES_AVAILABLE else None

        self._stop_event = threading.Event()
        self._scan_thread = None

    def start(self):
        """Start the scanner engine"""
        if self.state.is_running:
            logger.warning("Scanner already running")
            return

        logger.info("=" * 60)
        logger.info("SIERRA SCANNER AI - Starting")
        logger.info("ULTIMATE RULE: Maximum Profits. Minimum Losses. Minimum Drawdown.")
        logger.info("=" * 60)

        self.state.is_running = True
        self._stop_event.clear()

        # Start the main scanning thread
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()

        logger.info("Scanner engine started - waiting for Sierra Chart...")

    def stop(self):
        """Stop the scanner engine"""
        logger.info("Stopping scanner engine...")
        self._stop_event.set()
        self.state.is_running = False

        if self._scan_thread:
            self._scan_thread.join(timeout=5)

        if self.db:
            self.db.close()

        logger.info("Scanner engine stopped")

    def _scan_loop(self):
        """Main scanning loop"""
        while not self._stop_event.is_set():
            try:
                # Check if Sierra Chart is running
                sierra_running = self.detector.is_running()

                if sierra_running and not self.state.sierra_chart_detected:
                    logger.info("Sierra Chart DETECTED - Activating scanner!")
                    self.state.sierra_chart_detected = True
                elif not sierra_running and self.state.sierra_chart_detected:
                    logger.info("Sierra Chart CLOSED - Scanner on standby")
                    self.state.sierra_chart_detected = False

                # Only scan if Sierra Chart is running
                if self.state.sierra_chart_detected:
                    self._perform_scan()

                # Wait before next iteration
                self._stop_event.wait(Config.SCREENSHOT_INTERVAL)

            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                time.sleep(1)

    def _perform_scan(self):
        """Perform a single scan iteration using Grid Strategy with Content Validation"""
        self.state.scan_count += 1
        self.state.last_scan = datetime.now()
        
        # Track which symbols/timeframes we actually see in THIS scan
        current_scan_keys = set()

        # Get all Sierra Chart windows (just to verify it's open)
        windows = self.detector.get_windows()
        if not windows:
            logger.debug("No Sierra Chart windows found")
            return

        logger.info(f"Scan #{self.state.scan_count} - Executing Grid Scan ({Config.GRID_ROWS}x{Config.GRID_COLS}) with Validation")
        logger.info(f"  Timeframes: {Config.GRID_TIMEFRAMES}")
        logger.info(f"  Symbols: {Config.GRID_SYMBOLS}")

        # Capture Grid Charts
        grid_charts = self.capture.capture_grid_charts(
            rows=Config.GRID_ROWS,
            cols=Config.GRID_COLS
        )

        if not grid_charts:
            logger.warning("Failed to capture grid charts")
            return

        for chart in grid_charts:
            row, col = chart['row'], chart['col']
            
            # Map grid position to Symbol and Timeframe
            if col < len(Config.GRID_SYMBOLS):
                base_symbol = Config.GRID_SYMBOLS[col]
            else:
                continue # Skip extra columns

            if row < len(Config.GRID_TIMEFRAMES):
                timeframe = Config.GRID_TIMEFRAMES[row]
            else:
                continue # Skip extra rows

            # Create unique identifier: SYMBOL_TIMEFRAME
            symbol_key = f"{base_symbol}_{timeframe}"
            
            try:
                img = chart['image']
                
                # --- CONTENT VALIDATION ---
                # Check if the chart segment actually contains data
                # Calculate standard deviation of pixels (0 = solid color)
                img_gray = img.convert('L')
                stat = np.std(np.array(img_gray))
                
                if stat < 5.0:  # Very low variance = empty/black/background
                    continue
                
                # Check if it's mostly one color (e.g. Sierra background)
                # (Simple check: if more than 95% of pixels are identical)
                
                # If we pass validation, process the chart
                if symbol_key not in self.state.symbols:
                    self.state.symbols[symbol_key] = SymbolState(
                        symbol=symbol_key,
                        window_handle=0
                    )

                symbol_state = self.state.symbols[symbol_key]
                current_scan_keys.add(symbol_key)

                # Analyze the screenshot segment
                analysis = self.analyzer.analyze_screenshot(
                    img,
                    symbol_key,
                    symbol_state
                )

                # Store analysis
                symbol_state.last_analysis = analysis
                symbol_state.analyses.append(analysis)
                symbol_state.last_screenshot = datetime.now()

                # Save to database
                if self.db:
                    self.db.save_analysis(analysis)

                # Log Daily charts that are active
                if row == 0:
                    logger.info(f"  Detected: {symbol_key} (Stat: {stat:.1f})")

            except Exception as e:
                logger.error(f"Error processing chart {symbol_key}: {e}")

        # --- CLEANUP ---
        # Remove symbols from the state that were NOT seen in this scan
        # This ensures the "list" only contains what is currently shown
        all_keys = list(self.state.symbols.keys())
        for key in all_keys:
            if key not in current_scan_keys:
                del self.state.symbols[key]
        
        logger.info(f"Scan complete. {len(current_scan_keys)} charts active.")



    def get_recommendations(self) -> Dict[str, Dict]:
        """Get current recommendations for all symbols"""
        recommendations = {}

        for symbol, state in self.state.symbols.items():
            if state.last_analysis:
                recommendations[symbol] = {
                    'symbol': symbol,
                    'signal': state.last_analysis.signal.value,
                    'confidence': state.last_analysis.confidence,
                    'risk_reward': state.last_analysis.risk_reward_ratio,
                    'trend': state.last_analysis.trend_direction,
                    'momentum': state.last_analysis.momentum,
                    'win_rate': state.win_rate,
                    'timestamp': state.last_analysis.timestamp.isoformat(),
                    'analysis': state.last_analysis.to_dict()
                }

        return recommendations

    def get_status(self) -> Dict:
        """Get scanner status"""
        return {
            'is_running': self.state.is_running,
            'sierra_chart_detected': self.state.sierra_chart_detected,
            'scan_count': self.state.scan_count,
            'last_scan': self.state.last_scan.isoformat() if self.state.last_scan else None,
            'symbols_tracked': len(self.state.symbols),
            'symbols': list(self.state.symbols.keys())
        }


# ============================================================================
# FLASK API SERVER
# ============================================================================

def create_api(scanner: SierraScannerAI) -> Optional[Flask]:
    """Create Flask API for the scanner"""
    if not FLASK_AVAILABLE:
        return None

    app = Flask(__name__)
    CORS(app)

    @app.route('/api/sierra-scanner/health', methods=['GET'])
    def health():
        return jsonify({
            'status': 'healthy',
            'service': 'Sierra Scanner AI',
            'timestamp': datetime.now().isoformat()
        })

    @app.route('/api/sierra-scanner/status', methods=['GET'])
    def status():
        return jsonify(scanner.get_status())

    @app.route('/api/sierra-scanner/recommendations', methods=['GET'])
    def recommendations():
        return jsonify({
            'recommendations': scanner.get_recommendations(),
            'timestamp': datetime.now().isoformat()
        })

    @app.route('/api/sierra-scanner/symbol/<symbol>', methods=['GET'])
    def symbol_detail(symbol):
        if symbol not in scanner.state.symbols:
            return jsonify({'error': 'Symbol not found'}), 404

        state = scanner.state.symbols[symbol]
        return jsonify({
            'symbol': symbol,
            'current_recommendation': state.last_analysis.to_dict() if state.last_analysis else None,
            'win_rate': state.win_rate,
            'total_predictions': state.total_predictions,
            'correct_predictions': state.correct_predictions,
            'analyses_count': len(state.analyses)
        })

    @app.route('/api/sierra-scanner/start', methods=['POST'])
    def start_scanner():
        scanner.start()
        return jsonify({'status': 'started'})

    @app.route('/api/sierra-scanner/stop', methods=['POST'])
    def stop_scanner():
        scanner.stop()
        return jsonify({'status': 'stopped'})

    return app


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for Sierra Scanner AI"""
    print("=" * 70)
    print("  SIERRA SCANNER AI")
    print("  Advanced Screenshot-Based Trading Intelligence System")
    print("  ")
    print("  ULTIMATE RULE: Maximum Profits. Minimum Losses. Minimum Drawdown.")
    print("=" * 70)
    print()

    # Display loaded configuration
    print("Configuration loaded:")
    print(f"  Grid: {Config.GRID_ROWS} rows x {Config.GRID_COLS} cols")
    print(f"  Timeframes: {Config.GRID_TIMEFRAMES}")
    print(f"  Symbols: {Config.GRID_SYMBOLS}")
    print(f"  Screenshot Interval: {Config.SCREENSHOT_INTERVAL}s")
    print()
    print("  To customize, edit: sierra_scanner_config.json")
    print()

    # Create scanner instance
    scanner = SierraScannerAI()

    # Create API
    app = create_api(scanner)

    # Handle shutdown gracefully
    def signal_handler(signum, frame):
        print("\nShutdown signal received...")
        scanner.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start scanner
    scanner.start()

    # Start API server
    if app:
        print(f"\nStarting API server on http://{Config.API_HOST}:{Config.API_PORT}")
        app.run(
            host=Config.API_HOST,
            port=Config.API_PORT,
            debug=False,
            threaded=True
        )
    else:
        # No Flask, just run the scanner
        print("\nFlask not available - running scanner only")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scanner.stop()


if __name__ == "__main__":
    main()
