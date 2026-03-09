#!/bin/bash

# 获取脚本所在目录的绝对路径
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT"

# 初始化 shell 以便使用 conda activate
# 这里假设 conda 安装在默认路径，或者已经在 PATH 中
eval "$(conda shell.bash hook)"
conda activate qwen3-asr

echo "🚀 Starting Mac Over Speak (Conda: qwen3-asr)..."

# 1. 启动 API 服务 (后台运行)
echo "--- Starting API Service ---"
python3 "$PROJECT_ROOT/api/main.py" &
API_PID=$!

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
        kill $API_PID
        exit 1
    fi
done

echo "✅ API Service is ready."

# 3. 启动 Client
echo "--- Starting Client Bridge ---"
python3 "$PROJECT_ROOT/client/qwen_bridge.py"

# 4. 当 Client 退出时，清理 API 进程
echo "Cleaning up..."
kill $API_PID
echo "Done."
