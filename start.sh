#!/bin/bash

# 获取脚本所在目录的绝对路径
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT"

# 初始化 shell 以便使用 conda activate
# 这里假设 conda 安装在默认路径，或者已经在 PATH 中
eval "$(conda shell.bash hook)"
conda activate qwen3-asr
export PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "🚀 Starting Mac Over Speak (Conda: qwen3-asr)..."

# Default to the working local backend on Apple Silicon.
# ASR_BACKEND=mlx is reserved for a future MLX backend implementation.
export ASR_BACKEND="${ASR_BACKEND:-transformers}"
export ASR_DEVICE="${ASR_DEVICE:-mps}"
export ASR_DTYPE="${ASR_DTYPE:-bfloat16}"
# Keep automatic model resets disabled by default to avoid adding
# multi-second reload pauses to normal back-to-back dictation.
export ASR_RESET_EVERY_N_REQUESTS="${ASR_RESET_EVERY_N_REQUESTS:-20}"

cleanup() {
    if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" 2>/dev/null; then
        echo "Cleaning up API service (PID: $API_PID)..."
        kill "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM HUP

# 1. 启动 API 服务 (后台运行)
echo "--- Starting API Service ---"
python3 "$PROJECT_ROOT/api/main.py" &
API_PID=$!
export MAC_OVER_SPEAK_API_PID="$API_PID"

# 2. 等待 API 服务启动 (检查端口 8333 是否就绪)
echo "Waiting for API to be ready..."
MAX_RETRIES=300
COUNT=0
URL="http://127.0.0.1:8333/status/"

while ! curl -s "$URL" > /dev/null; do
    sleep 1
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "❌ API Service failed to start in time."
        exit 1
    fi
done

echo "✅ API Service is ready."

# 3. 启动 Client
echo "--- Starting Client Bridge ---"
python3 "$PROJECT_ROOT/client/qwen_bridge.py"
