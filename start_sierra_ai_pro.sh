#!/bin/bash
# Quick start script for Sierra Scanner AI Pro

echo "Sierra Scanner AI Pro v2.0 - Quick Start"
echo "==========================================="
echo ""

if [ ! -f "sierra_scanner_ai_pro.py" ]; then
    echo "Error: Not in correct directory. Navigate to Sierra Intelligence."
    exit 1
fi

echo "Checking dependencies..."
pip list | grep -q scikit-learn && echo "  scikit-learn OK" || echo "  MISSING: pip install scikit-learn"
pip list | grep -q scipy && echo "  scipy OK" || echo "  MISSING: pip install scipy"
pip list | grep -q opencv-python && echo "  opencv OK" || echo "  MISSING: pip install opencv-python"
pip list | grep -q Pillow && echo "  Pillow OK" || echo "  MISSING: pip install Pillow"
pip list | grep -q numpy && echo "  numpy OK" || echo "  MISSING: pip install numpy"

echo ""
echo "Copying v2 config..."
cp sierra_scanner_config_v2.json sierra_scanner_config.json

echo ""
echo "Starting Sierra Scanner AI Pro..."
echo "  Features: Ensemble ML | Bayesian Calibration | Kelly Criterion | Regime Detection"
echo ""

python3 sierra_scanner_ai.py --ai-engine pro --config sierra_scanner_config.json "$@"
