#!/bin/bash
# LLM YouTube Tracker - start/restart script
# Usage: ./start.sh [port]

PORT=${1:-8080}
DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill any existing server on this port
pkill -f "python3 serve.py $PORT" 2>/dev/null
sleep 1

# Start the server
cd "$DIR"
nohup python3 serve.py "$PORT" > /tmp/llm-tracker.log 2>&1 &
echo "✅ LLM Tracker started on port $PORT (PID: $!)"
echo "🌐 Dashboard: http://$(curl -s http://icanhazip.com 2>/dev/null):$PORT"
