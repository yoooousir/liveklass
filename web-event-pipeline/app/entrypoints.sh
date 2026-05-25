#!/bin/sh
set -e

echo "=== [1/2] Running event generator ==="
python generator.py

echo ""
echo "=== [2/2] Running analytics & visualization ==="
python analytics.py

echo ""
echo "=== Pipeline complete. Charts saved to /charts/ ==="
