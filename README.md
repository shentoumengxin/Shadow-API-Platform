# LLM Research Proxy

一个轻量级的 LLM API 代理，用于模型供应链与第三方平台代理风险研究。

> ⚠️ **重要声明**: 本项目仅限个人授权实验环境使用，用于论文验证、靶场和防御研究。

## 特性

- 🔌 **双协议兼容**: 支持 OpenAI 和 Anthropic 两种 API 格式
- 🎯 **请求/响应拦截**: 基于 YAML 规则的灵活拦截和修改
- 📊 **文件化审计**: 所有请求/响应保存到本地 JSONL 文件
- 🔍 ** trace 回放**: 支持重放历史请求进行对比分析
- 🖥️ **Web 界面**: 内置简洁的监控和测试界面
- 🚀 **零数据库依赖**: 无需 Redis、Postgres 等重型依赖

## 快速开始

### 1. 安装依赖

```bash
pip install -e ".[dev]"
```

或直接安装：

```bash
pip install fastapi uvicorn httpx pydantic pyyaml python-dotenv
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

编辑 `.env`:

```env
# Server Configuration
HOST=0.0.0.0
PORT=8765

# OpenAI-compatible provider
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1

# Anthropic provider
ANTHROPIC_API_KEY=your-anthropic-api-key-here
ANTHROPIC_BASE_URL=https://api.anthropic.com

# Trace & Logging Configuration
LOG_LEVEL=INFO
TRACE_ENABLED=true
DRY_RUN=false
```

### 3. 启动服务

```bash
python -m app.main
```

或使用 uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8765 --reload
```

### 4. 访问界面

- **Web UI**: http://localhost:8765/ui
- **API Docs**: http://localhost:8765/docs
- **Health Check**: http://localhost:8765/health

## 目录结构

```
project/
├── app/
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 配置管理
│   ├── adapters/
│   │   ├── base.py          # 适配器基类
│   │   ├── openai_adapter.py
│   │   └── anthropic_adapter.py
│   ├── rules/
│   │   ├── engine.py        # 规则引擎
│   │   ├── loader.py        # YAML 加载器
│   │   ├── matchers.py      # 匹配器
│   │   └── actions.py       # 动作执行器
│   ├── schemas/
│   │   ├── models.py        # 数据模型
│   │   ├── rules.py         # 规则模型
│   │   └── traces.py        # Trace 模型
│   ├── services/
│   │   ├── proxy.py         # 核心代理服务
│   │   ├── trace_store.py   # 文件存储
│   │   └── replay.py        # 回放服务
│   └── utils/
│       ├── ids.py           # ID 生成
│       └── logging.py       # 日志工具
├── rules/
│   ├── request.yaml         # 请求规则
│   ├── response.yaml        # 响应规则
│   └── passive.yaml         # 被动规则
├── logs/
│   ├── index.jsonl          # Trace 索引
│   └── traces/              # 独立 Trace 文件
├── tests/
│   ├── test_proxy.py
│   ├── test_config.py
│   └── test_rules.py
├── .env.example
├── pyproject.toml
└── README.md
```

## API 端点

### 代理端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 兼容接口 |
| `/v1/messages` | POST | Anthropic 兼容接口 |
| `/proxy/{provider}/invoke` | POST | 统一调试入口 |

### 管理端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/traces` | GET | 获取 Trace 列表 |
| `/traces/{trace_id}` | GET | 获取单个 Trace |
| `/traces/{trace_id}` | DELETE | 删除 Trace |
| `/traces` | DELETE | 清空所有 Trace |
| `/replay/{trace_id}` | POST | 回放 Trace |
| `/rules` | GET | 查看规则 |
| `/rules/reload` | POST | 重载规则 |

## 规则系统

### 规则格式

```yaml
rules:
  - id: "rule_unique_id"
    enabled: true          # 是否启用
    priority: 100          # 优先级 (0-1000, 越高越先执行)
    scope: request         # request / response / passive
    description: "规则描述"
    match:
      role: user           # 匹配角色
      keyword: "bypass"    # 匹配关键词
      regex: null          # 正则匹配
      model: "gpt"         # 匹配模型
      provider: "openai"   # 匹配提供者
    action:
      type: replace_text   # 动作类型
      original: "bypass"
      replacement: "[REPLACED]"
```

### 支持的动作类型

| 类型 | 说明 |
|------|------|
| `append_text` | 追加文本 |
| `replace_text` | 替换文本 |
| `remove_field` | 删除字段 |
| `mask_field` | 遮蔽字段 |
| `add_header` | 添加请求头 |
| `add_metadata` | 添加元数据 |
| `no_op` | 无操作 (仅记录) |

### 示例规则

**对 System Prompt 追加标签**:

```yaml
- id: "tag_system"
  enabled: true
  priority: 100
  scope: request
  description: "Tag system prompts for research"
  match:
    role: system
  action:
    type: append_text
    text: "\n\n[RESEARCH_MODE: active]"
```

**关键词替换**:

```yaml
- id: "replace_keyword"
  enabled: false
  priority: 90
  scope: request
  description: "Replace specific keywords"
  match:
    role: user
    keyword: "ignore"
  action:
    type: replace_text
    original: "ignore"
    replacement: "[RESEARCH_NOTE: keyword_blocked]"
```

**被动监控 (不修改)**:

```yaml
- id: "monitor_injection"
  enabled: true
  priority: 85
  scope: passive
  description: "Monitor potential injections"
  match:
    regex: "(?i)(ignore.*instruction|forget.*previous)"
    role: user
  action:
    type: add_metadata
    key: "flagged"
    value: "potential_injection"
```

## 使用示例

### cURL 调用

**OpenAI 兼容接口**:

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "system", "content": "You are helpful."},
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7
  }'
```

**Anthropic 兼容接口**:

```bash
curl -X POST http://localhost:8765/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 1024
  }'
```

**统一调试入口**:

```bash
curl -X POST http://localhost:8765/proxy/openai/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Test"}]
  }'
```

### 查看 Traces

```bash
# 获取最近的 traces
curl http://localhost:8765/traces?limit=10

# 获取特定 trace
curl http://localhost:8765/traces/tr_20240101123456_abc123

# 回放 trace
curl -X POST http://localhost:8765/replay/tr_20240101123456_abc123

# 使用修改后的请求回放
curl -X POST http://localhost:8765/replay/tr_20240101123456_abc123 \
  -H "Content-Type: application/json" \
  -d '{"use_modified_request": true}'
```

## 客户端接入

### Claude Code 接入

在 Claude Code 配置中设置自定义 API base:

```bash
# 设置代理为本地服务
export ANTHROPIC_BASE_URL=http://localhost:8765

# 或直接在使用时指定
claude --api-base http://localhost:8765/v1
```

### OpenClaw / OpenAI 客户端接入

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-key",
    base_url="http://localhost:8765/v1"
)

response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Hello"}]
)
```

### Python SDK 通用示例

```python
import httpx

# OpenAI 兼容
response = httpx.post(
    "http://localhost:8765/v1/chat/completions",
    json={
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}]
    },
    headers={"Authorization": "Bearer your-key"}
)

# Anthropic 兼容
response = httpx.post(
    "http://localhost:8765/v1/messages",
    json={
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 1024
    },
    headers={"x-api-key": "your-key"}
)
```

## 数据持久化

### Trace 文件结构

每个 trace 保存为独立的 JSON 文件：

```
logs/traces/tr_20240101123456_abc123.json
```

内容包含：
- 原始请求
- 修改后请求
- 原始响应
- 修改后响应
- 命中的规则
- 时间戳和耗时
- 错误信息

### JSONL 索引

`logs/index.jsonl` 包含所有 trace 的摘要，便于快速查询。

## 运行测试

```bash
pytest tests/ -v

# 带覆盖率
pytest tests/ -v --cov=app --cov-report=html
```

## 开发说明

### 添加新的 Provider

1. 在 `app/adapters/` 创建新的适配器类，继承 `BaseAdapter`
2. 实现所有抽象方法
3. 在 `ProxyService` 中注册

```python
# app/adapters/custom_adapter.py
from app.adapters.base import BaseAdapter

class CustomAdapter(BaseAdapter):
    def get_provider_name(self) -> str:
        return "custom"

    # 实现其他抽象方法...
```

### 扩展现有规则

在 `rules/` 目录添加新的 YAML 文件，或修改现有文件。
规则会自动热加载，也可以通过 `POST /rules/reload` 手动重载。

### 调试技巧

1. 启用 debug 日志：
   ```env
   LOG_LEVEL=DEBUG
   ```

2. 使用 dry run 模式测试规则：
   ```env
   DRY_RUN=true
   ```

3. 查看最近 trace:
   ```bash
   curl http://localhost:8765/debug/last-trace
   ```

## Streaming 支持 (未来扩展)

当前版本仅支持非流式请求。如需支持 streaming:

1. 在 `ProxyService.process_request` 中检测 `stream: true`
2. 使用 httpx 的流式 API 转发响应
3. 保持 SSE 格式传递给客户端
4. 注意：流式模式下规则应用需要在完整响应后进行

## 安全注意事项

- 本项目设计为**本地实验环境**使用
- 默认 CORS 配置允许所有来源 (便于调试)
- 生产环境请限制 CORS、添加认证
- 规则文件可能包含敏感模式，已加入 `.gitignore`
- 日志文件包含 API 交互内容，注意妥善保管

## License

MIT License - 仅供研究使用
