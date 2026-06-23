#!/usr/bin/env bash
# taxi_gps 前端演示启动脚本
# 启动 HTTP 服务器后浏览器访问 http://localhost:8080/frontend/index.html

set -e

PORT="${1:-4399}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  深圳出租车GPS数据分析系统 · 前端演示"
echo "============================================"
echo ""
echo "  启动 HTTP 服务器: 端口 $PORT"
echo "  浏览器打开: http://localhost:$PORT/frontend/index.html"
echo ""
echo "  按 Ctrl+C 停止"
echo "============================================"
echo ""

cd "$DIR"
python3 -m http.server "$PORT"
