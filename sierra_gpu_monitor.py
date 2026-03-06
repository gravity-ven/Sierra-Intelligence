"""
sierra_gpu_monitor.py — Spartan GPU Cache Superwatch
=====================================================
Monitors NVIDIA GPU cache size for Sierra Chart.
Auto-clears when cache exceeds threshold (default: 50MB).
Runs from WSL2 via PowerShell.exe bridging.

Integrated into spartan_autonomous_monitor.py's check cycle.
Can also run standalone:
    python3 sierra_gpu_monitor.py [--once] [--clear] [--status]
"""

import os
import sys
import json
import time
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────
DX_CACHE_WIN   = r"C:\Users\Quantum\AppData\Local\NVIDIA\DXCache"
GL_CACHE_WIN   = r"C:\Users\Quantum\AppData\Local\NVIDIA\GLCache"
STATE_FILE_WIN = r"C:\Users\Quantum\AppData\Local\spartan\gpu_cache_state.json"
CLEAR_SCRIPT   = r"C:\Users\Quantum\Downloads\Spartan_Labs\website\clear_nvidia_gpu_cache.ps1"

# WSL paths for direct reading (no PowerShell needed)
DX_CACHE_WSL   = Path("/mnt/c/Users/Quantum/AppData/Local/NVIDIA/DXCache")
GL_CACHE_WSL   = Path("/mnt/c/Users/Quantum/AppData/Local/NVIDIA/GLCache")
STATE_FILE_WSL = Path("/mnt/c/Users/Quantum/AppData/Local/spartan/gpu_cache_state.json")
LOG_FILE       = Path("/tmp/sierra_gpu_monitor.log")

AUTO_CLEAR_MB       = 50     # Clear DXCache when it exceeds this (MB)
GL_AUTO_CLEAR_MB    = 10     # Clear GLCache when it exceeds this (MB)
CHECK_INTERVAL_S    = 300    # Check every 5 minutes
SC_PROCESS_NAME     = "SierraChart"


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}][{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_dir_size_mb(path: Path) -> float:
    """Get directory size in MB via WSL path."""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def get_dir_file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def is_sierra_chart_running() -> bool:
    """Check if Sierra Chart is running on Windows via tasklist."""
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"IMAGENAME eq {SC_PROCESS_NAME}*", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        return SC_PROCESS_NAME.lower() in result.stdout.lower()
    except Exception:
        return False  # Assume not running if we can't check


_WIN_HIDDEN_EXE = '/mnt/c/Users/Quantum/win_hidden.exe'

def run_powershell_clear(force: bool = False) -> dict:
    """Invoke the PowerShell GPU cache cleaner via win_hidden.exe (no console flash)."""
    extra = " -Force" if force else ""
    cmd = (f'powershell.exe -NoProfile -ExecutionPolicy Bypass'
           f' -File {CLEAR_SCRIPT} -Quiet{extra}')
    try:
        result = subprocess.run(
            [_WIN_HIDDEN_EXE, cmd],
            capture_output=True, text=True, timeout=120
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "Timeout after 120s", "returncode": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}


def read_state_file() -> dict:
    """Read last clear state from the state JSON file."""
    try:
        if STATE_FILE_WSL.exists():
            return json.loads(STATE_FILE_WSL.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def write_monitor_status(data: dict):
    """Write current monitor status for the autonomous monitor to read."""
    status_path = Path("/tmp/sierra_gpu_status.json")
    try:
        status_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def check_and_maybe_clear() -> dict:
    """Core check: measure cache sizes, auto-clear if over threshold."""
    dx_mb    = get_dir_size_mb(DX_CACHE_WSL)
    dx_files = get_dir_file_count(DX_CACHE_WSL)
    gl_mb    = get_dir_size_mb(GL_CACHE_WSL)
    gl_files = get_dir_file_count(GL_CACHE_WSL)
    sc_running = is_sierra_chart_running()

    status = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "dx_mb":       dx_mb,
        "dx_files":    dx_files,
        "gl_mb":       gl_mb,
        "gl_files":    gl_files,
        "sc_running":  sc_running,
        "action":      "none",
        "freed_mb":    0,
        "alert":       None,
    }

    log(f"DXCache: {dx_files} files ({dx_mb} MB) | GLCache: {gl_files} files ({gl_mb} MB) | SC running: {sc_running}")

    dx_over = dx_mb > AUTO_CLEAR_MB
    gl_over = gl_mb > GL_AUTO_CLEAR_MB

    if not dx_over and not gl_over:
        log(f"Cache sizes OK (dx={dx_mb}MB < {AUTO_CLEAR_MB}MB, gl={gl_mb}MB < {GL_AUTO_CLEAR_MB}MB)")
        status["action"] = "none_needed"
        write_monitor_status(status)
        return status

    # Cache exceeds threshold — need to clear
    alert_msg = (
        f"NVIDIA GPU cache overgrown: DXCache={dx_mb}MB ({dx_files} files), "
        f"GLCache={gl_mb}MB ({gl_files} files). Threshold: {AUTO_CLEAR_MB}MB/{GL_AUTO_CLEAR_MB}MB."
    )
    log(alert_msg, "WARN")
    status["alert"] = alert_msg

    if sc_running:
        log("Sierra Chart is RUNNING — cannot clear cache safely. Will retry when SC exits.", "WARN")
        status["action"] = "deferred_sc_running"
        write_monitor_status(status)
        return status

    # SC not running — safe to clear
    log(f"Triggering GPU cache clear (dx={dx_mb}MB, gl={gl_mb}MB > thresholds)...")
    result = run_powershell_clear(force=True)

    if result["ok"]:
        # Re-measure after clear
        dx_mb_after = get_dir_size_mb(DX_CACHE_WSL)
        gl_mb_after = get_dir_size_mb(GL_CACHE_WSL)
        freed = round((dx_mb + gl_mb) - (dx_mb_after + gl_mb_after), 2)
        log(f"Cache cleared successfully. Freed {freed} MB. "
            f"After: DXCache={dx_mb_after}MB, GLCache={gl_mb_after}MB", "SUCCESS")
        status["action"]   = "cleared"
        status["freed_mb"] = freed
        status["dx_mb_after"] = dx_mb_after
        status["gl_mb_after"] = gl_mb_after
    else:
        log(f"Cache clear FAILED: {result['stderr']}", "ERROR")
        status["action"] = "clear_failed"
        status["error"]  = result["stderr"]

    write_monitor_status(status)
    return status


def force_clear_now() -> dict:
    """Immediately clear the GPU cache (for manual/superfix invocation)."""
    sc_running = is_sierra_chart_running()
    if sc_running:
        log("Sierra Chart is running. Using -Force flag to clear anyway...", "WARN")

    dx_mb    = get_dir_size_mb(DX_CACHE_WSL)
    dx_files = get_dir_file_count(DX_CACHE_WSL)
    gl_mb    = get_dir_size_mb(GL_CACHE_WSL)
    gl_files = get_dir_file_count(GL_CACHE_WSL)
    log(f"Force clear: DXCache={dx_files} files ({dx_mb}MB), GLCache={gl_files} files ({gl_mb}MB)")

    result = run_powershell_clear(force=True)
    if result["ok"]:
        dx_after = get_dir_size_mb(DX_CACHE_WSL)
        gl_after = get_dir_size_mb(GL_CACHE_WSL)
        freed = round((dx_mb + gl_mb) - (dx_after + gl_after), 2)
        log(f"Force clear complete. Freed {freed} MB.", "SUCCESS")
        return {"ok": True, "freed_mb": freed, "dx_before": dx_mb, "gl_before": gl_mb,
                "dx_after": dx_after, "gl_after": gl_after}
    else:
        log(f"Force clear failed: {result['stderr']}", "ERROR")
        return {"ok": False, "error": result["stderr"]}


def print_status():
    """Print current GPU cache status."""
    dx_mb    = get_dir_size_mb(DX_CACHE_WSL)
    dx_files = get_dir_file_count(DX_CACHE_WSL)
    gl_mb    = get_dir_size_mb(GL_CACHE_WSL)
    gl_files = get_dir_file_count(GL_CACHE_WSL)
    sc_running = is_sierra_chart_running()
    state = read_state_file()

    print(f"""
  ╔══════════════════════════════════════════════════╗
  ║    Spartan GPU Cache Monitor — Current Status    ║
  ╠══════════════════════════════════════════════════╣
  ║  Sierra Chart: {'RUNNING' if sc_running else 'NOT running':<34} ║
  ╠══════════════════════════════════════════════════╣
  ║  DXCache:  {dx_files:>4} files  {dx_mb:>7.2f} MB  (threshold: {AUTO_CLEAR_MB} MB) ║
  ║  GLCache:  {gl_files:>4} files  {gl_mb:>7.2f} MB  (threshold: {GL_AUTO_CLEAR_MB} MB) ║
  ╠══════════════════════════════════════════════════╣
  ║  DX {'OVER THRESHOLD - clear needed' if dx_mb > AUTO_CLEAR_MB else 'OK':<44} ║
  ║  GL {'OVER THRESHOLD - clear needed' if gl_mb > GL_AUTO_CLEAR_MB else 'OK':<44} ║
  ╠══════════════════════════════════════════════════╣
  ║  Last clear: {state.get('timestamp', 'never')[:19]:<36} ║
  ║  Freed:      {state.get('freed_mb', 0):>7.2f} MB                               ║
  ╚══════════════════════════════════════════════════╝
""")


def run_monitor_loop():
    """Continuous monitoring loop (superwatch mode)."""
    log(f"Sierra Chart GPU Cache Superwatch started. Check interval: {CHECK_INTERVAL_S}s")
    log(f"Auto-clear thresholds: DXCache>{AUTO_CLEAR_MB}MB, GLCache>{GL_AUTO_CLEAR_MB}MB")
    while True:
        try:
            check_and_maybe_clear()
        except Exception as e:
            log(f"Monitor cycle error: {e}", "ERROR")
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spartan Sierra Chart GPU Cache Monitor")
    parser.add_argument("--once",   action="store_true", help="Run one check and exit")
    parser.add_argument("--clear",  action="store_true", help="Force clear now and exit")
    parser.add_argument("--status", action="store_true", help="Show current status and exit")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.clear:
        result = force_clear_now()
        sys.exit(0 if result["ok"] else 1)
    elif args.once:
        status = check_and_maybe_clear()
        sys.exit(0 if status.get("action") != "clear_failed" else 1)
    else:
        run_monitor_loop()
