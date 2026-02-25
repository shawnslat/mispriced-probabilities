#!/bin/bash

# Seer Dashboard Launcher
# Quick start script for the web dashboard

echo "🔮 Starting Seer Dashboard..."
echo ""

# Check if streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "❌ Streamlit not found. Installing..."
    pip install streamlit pandas
    echo "✅ Streamlit installed!"
    echo ""
fi

# Navigate to dashboard directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if database exists
DB_PATH="../seer.db"
if [ ! -f "$DB_PATH" ]; then
    echo "⚠️  Warning: Database not found at $DB_PATH"
    echo "   Make sure the scanner has run at least once."
    echo ""
fi

# Launch dashboard
echo "📊 Launching dashboard at http://localhost:8501"
echo "   Press Ctrl+C to stop"
echo ""

streamlit run app.py --server.headless false --server.port 8501

