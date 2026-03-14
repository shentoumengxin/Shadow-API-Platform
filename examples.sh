#!/bin/bash
# LLM Research Proxy - cURL 测试示例

BASE_URL="http://localhost:8765"

echo "=========================================="
echo "LLM Research Proxy - cURL 测试示例"
echo "=========================================="

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}提示：请先确保服务正在运行：python -m app.main${NC}"
echo ""

# =============================================
# 1. 健康检查
# =============================================
echo -e "${YELLOW}1. 健康检查${NC}"
echo "----------------------------------------"
curl -s "$BASE_URL/health" | python3 -m json.tool
echo ""

# =============================================
# 2. OpenAI 兼容接口
# =============================================
echo -e "${YELLOW}2. OpenAI 兼容接口测试${NC}"
echo "----------------------------------------"
curl -s -X POST "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY:-test}" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "system", "content": "You are a helpful research assistant."},
      {"role": "user", "content": "Hello, tell me about API security research."}
    ],
    "temperature": 0.7,
    "max_tokens": 200
  }' | python3 -m json.tool
echo ""
echo -e "${GREEN}提示：响应头中包含 X-Research-Trace-Id${NC}"
echo ""

# =============================================
# 3. Anthropic 兼容接口
# =============================================
echo -e "${YELLOW}3. Anthropic 兼容接口测试${NC}"
echo "----------------------------------------"
curl -s -X POST "$BASE_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${ANTHROPIC_API_KEY:-test}" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [
      {"role": "user", "content": "Hello, tell me about API security research."}
    ],
    "max_tokens": 200
  }' | python3 -m json.tool
echo ""

# =============================================
# 4. 统一调试入口
# =============================================
echo -e "${YELLOW}4. 统一调试入口 (OpenAI)${NC}"
echo "----------------------------------------"
curl -s -X POST "$BASE_URL/proxy/openai/invoke" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Test message"}]
  }' | python3 -m json.tool
echo ""

# =============================================
# 5. 查看 Traces
# =============================================
echo -e "${YELLOW}5. 查看最近的 Traces${NC}"
echo "----------------------------------------"
curl -s "$BASE_URL/traces?limit=5" | python3 -m json.tool
echo ""

# =============================================
# 6. 查看规则
# =============================================
echo -e "${YELLOW}6. 查看所有规则${NC}"
echo "----------------------------------------"
curl -s "$BASE_URL/rules" | python3 -m json.tool
echo ""

# =============================================
# 7. 查看提供者配置
# =============================================
echo -e "${YELLOW}7. 查看配置提供者${NC}"
echo "----------------------------------------"
curl -s "$BASE_URL/debug/providers" | python3 -m json.tool
echo ""

# =============================================
# 8. 带有关键词测试 (触发规则)
# =============================================
echo -e "${YELLOW}8. 测试关键词替换规则 (包含'bypass')${NC}"
echo "----------------------------------------"
curl -s -X POST "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY:-test}" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "How to bypass security checks in API?"}
    ],
    "max_tokens": 100
  }' | python3 -m json.tool
echo ""
echo -e "${GREEN}提示：如果启用了替换规则，bypass 会被替换${NC}"
echo ""

# =============================================
# 9. 重放 Trace 示例
# =============================================
echo -e "${YELLOW}9. 重放 Trace (需要先有 trace_id)${NC}"
echo "----------------------------------------"
echo "获取最近的 trace_id 并重放:"
TRACE_ID=$(curl -s "$BASE_URL/traces?limit=1" | python3 -c "import sys,json; t=json.load(sys.stdin); print(t[0]['trace_id']) if t else print('')" 2>/dev/null)
if [ -n "$TRACE_ID" ]; then
    echo "Trace ID: $TRACE_ID"
    curl -s -X POST "$BASE_URL/replay/$TRACE_ID" | python3 -m json.tool
else
    echo "没有找到可重放的 traces"
fi
echo ""

# =============================================
# 10. 删除单个 Trace
# =============================================
echo -e "${YELLOW}10. 删除 Trace 示例${NC}"
echo "----------------------------------------"
if [ -n "$TRACE_ID" ]; then
    echo "删除 trace: $TRACE_ID"
    curl -s -X DELETE "$BASE_URL/traces/$TRACE_ID" | python3 -m json.tool
else
    echo "没有可删除的 trace"
fi
echo ""

# =============================================
# 11. 清空所有 Traces
# =============================================
echo -e "${YELLOW}11. 清空所有 Traces${NC}"
echo "----------------------------------------"
curl -s -X DELETE "$BASE_URL/traces" | python3 -m json.tool
echo ""

# =============================================
# 12. Web 界面
# =============================================
echo -e "${BLUE}=========================================="
echo "Web 界面访问:"
echo "  - UI: http://localhost:8765/ui"
echo "  - API Docs: http://localhost:8765/docs"
echo "  - Health: http://localhost:8765/health"
echo "==========================================${NC}"
