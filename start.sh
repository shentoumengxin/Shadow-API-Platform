#!/bin/bash
# LLM Research Proxy 启动脚本

cd /home/XXBAi/HKUST/router

# 激活虚拟环境（如果有）
if [ -d "venv/bin" ]; then
    source venv/bin/activate
fi

# 启动服务，绑定到 0.0.0.0 允许所有网络接口访问
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8765 \
    --workers 1
