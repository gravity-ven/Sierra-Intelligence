#!/usr/bin/env python3
"""
Sierra Screenshot Helper - Windows-side screenshot capture
This script MUST be run with Windows Python (not WSL) to capture Windows screenshots.

Usage:
    python sierra_screenshot_helper.py enumerate   # List Sierra Chart windows
    python sierra_screenshot_helper.py capture     # Capture full screenshot
    python sierra_screenshot_helper.py capture-all # Capture and split into charts

Output: JSON to stdout for parsing by WSL-side code
"""

import sys
import json
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import base64
import io

try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def enumerate_windows():
    """Enumerate all Sierra Chart windows"""
    windows = []
    try:
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buffer = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buffer, length)
                title = buffer.value
                if 'SierraChart' in title or 'Sierra Chart' in title:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    windows.append({'hwnd': hwnd, 'title': title,
                                    'rect': [rect.left, rect.top, rect.right, rect.bottom]})
            return True
        user32.EnumWindows(EnumWindowsProc(callback), 0)
    except Exception as e:
        return {'error': str(e), 'windows': []}
    return {'windows': windows, 'count': len(windows)}


def capture_screenshot(output_path=None):
    """Capture full screen screenshot"""
    if not PIL_AVAILABLE:
        return {'error': 'PIL not available'}
    try:
        img = ImageGrab.grab()
        if output_path:
            img.save(output_path, 'PNG')
            return {'success': True, 'path': str(output_path), 'size': [img.width, img.height]}
        else:
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return {'success': True, 'size': [img.width, img.height],
                    'image_base64': base64.b64encode(buffer.getvalue()).decode('utf-8')}
    except Exception as e:
        return {'error': str(e)}


def capture_and_split(output_dir, num_charts=5):
    """Capture full screenshot and split into chart regions"""
    if not PIL_AVAILABLE:
        return {'error': 'PIL not available'}
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        full_path = output_path / f"sierra_full_{timestamp}.png"
        img.save(full_path, 'PNG')
        width, height = img.size
        chart_width = width // num_charts
        charts = []
        for i in range(num_charts):
            left = i * chart_width
            right = (i + 1) * chart_width if i < num_charts - 1 else width
            chart_img = img.crop((left, 0, right, height))
            chart_path = output_path / f"chart_{i+1}_{timestamp}.png"
            chart_img.save(chart_path, 'PNG')
            charts.append({'index': i+1, 'path': str(chart_path), 'region': [left, 0, right, height]})
        return {'success': True, 'full_screenshot': str(full_path), 'size': [width, height], 'charts': charts}
    except Exception as e:
        return {'error': str(e)}


def capture_grid(output_dir, rows=6, cols=8):
    """Capture full screenshot and split into a grid of charts"""
    if not PIL_AVAILABLE:
        return {'error': 'PIL not available'}
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        full_path = output_path / f"sierra_full_{timestamp}.png"
        img.save(full_path, 'PNG')
        width, height = img.size
        cell_width = width // cols
        cell_height = height // rows
        charts = []
        for r in range(rows):
            for c in range(cols):
                left = c * cell_width
                top = r * cell_height
                right = (c+1)*cell_width if c < cols-1 else width
                bottom = (r+1)*cell_height if r < rows-1 else height
                chart_img = img.crop((left, top, right, bottom))
                chart_path = output_path / f"chart_r{r}_c{c}_{timestamp}.png"
                chart_img.save(chart_path, 'PNG')
                charts.append({'row': r, 'col': c, 'path': str(chart_path), 'region': [left, top, right, bottom]})
        return {'success': True, 'full_screenshot': str(full_path), 'grid': {'rows': rows, 'cols': cols}, 'charts': charts}
    except Exception as e:
        return {'error': str(e)}


def capture_window_region(rect, output_path=None):
    """Capture a specific screen region"""
    if not PIL_AVAILABLE:
        return {'error': 'PIL not available'}
    try:
        left, top, right, bottom = rect
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        if output_path:
            img.save(output_path, 'PNG')
            return {'success': True, 'path': str(output_path), 'size': [img.width, img.height]}
        else:
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return {'success': True, 'size': [img.width, img.height],
                    'image_base64': base64.b64encode(buffer.getvalue()).decode('utf-8')}
    except Exception as e:
        return {'error': str(e)}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: sierra_screenshot_helper.py <command> [args]'}))
        sys.exit(1)
    command = sys.argv[1].lower()
    if command == 'enumerate':
        result = enumerate_windows()
    elif command == 'capture':
        result = capture_screenshot(sys.argv[2] if len(sys.argv) > 2 else None)
    elif command == 'capture-all':
        output_dir = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Quantum/Downloads/SierraChart/ACS_Source/screenshots'
        result = capture_and_split(output_dir, int(sys.argv[3]) if len(sys.argv) > 3 else 5)
    elif command == 'capture-grid':
        output_dir = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Quantum/Downloads/SierraChart/ACS_Source/screenshots'
        result = capture_grid(output_dir, int(sys.argv[3]) if len(sys.argv) > 3 else 6, int(sys.argv[4]) if len(sys.argv) > 4 else 8)
    elif command == 'capture-region':
        if len(sys.argv) < 6:
            result = {'error': 'Usage: capture-region left top right bottom [output_path]'}
        else:
            rect = [int(sys.argv[i]) for i in range(2, 6)]
            result = capture_window_region(rect, sys.argv[6] if len(sys.argv) > 6 else None)
    else:
        result = {'error': f'Unknown command: {command}'}
    print(json.dumps(result))
