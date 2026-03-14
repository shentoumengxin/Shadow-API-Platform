# LLM Research Proxy - 快速启动指南

## 📦 一、安装依赖

### 方法 1: 使用 requirements.txt (推荐)
```bash
cd /home/XXBAi/HKUST/router
pip install -r requirements.txt
```

### 方法 2: 使用 pyproject.toml
```bash
pip install -e ".[dev]"
```

### 方法 3: 手动安装
```bash
pip install fastapi uvicorn httpx pydantic pyyaml python-dotenv pytest pytest-asyncio
```

---

## 🔑 二、配置 API 密钥 (重要!)

### 在哪里填写上游 API 密钥？

**步骤 1:** 复制环境变量模板
```bash
cp .env.example .env
```

**步骤 2:** 编辑 `.env` 文件，填入你的 API 密钥：

```bash
# 服务器配置
HOST=0.0.0.0
PORT=8765

# ============ 在这里填写你的 API 密钥 ============

# OpenAI API 配置
OPENAI_API_KEY=sk-your-actual-openai-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1

# Anthropic API 配置
ANTHROPIC_API_KEY=sk-ant-your-actual-anthropic-api-key-here
ANTHROPIC_BASE_URL=https://api.anthropic.com

# ================================================

# 日志配置
LOG_LEVEL=INFO
TRACE_ENABLED=true
DRY_RUN=false

# 规则目录
RULES_DIR=rules
```

### 支持的 Provider

| Provider | 环境变量 | 默认 Base URL |
|----------|----------|---------------|
| OpenAI | `OPENAI_API_KEY` | https://api.openai.com/v1 |
| Anthropic | `ANTHROPIC_API_KEY` | https://api.anthropic.com |

**注意:** 你也可以使用兼容 OpenAI 接口的其他服务 (如 vLLM、LocalAI 等)，只需修改 `OPENAI_BASE_URL` 即可。

---

## 🚀 三、启动服务

### 方法 1: 使用 Python 直接运行
```bash
python -m app.main
```

### 方法 2: 使用 Uvicorn
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8765 --reload
```

### 方法 3: 后台运行
```bash
nohup uvicorn app.main:app --host 0.0.0.0 --port 8765 > proxy.log 2>&1 &
```

启动后，你会看到类似输出:
```
2024-01-01 12:00:00 - INFO - ==================================================
2024-01-01 12:00:00 - INFO - LLM Research Proxy starting...
2024-01-01 12:00:00 - INFO - Host: 0.0.0.0:8765
2024-01-01 12:00:00 - INFO - Trace enabled: True
2024-01-01 12:00:00 - INFO - Dry run: False
2024-01-01 12:00:00 - INFO - Rules directory: rules
2024-01-01 12:00:00 - INFO - Providers configured: ['openai', 'anthropic']
2024-01-01 12:00:00 - INFO - ==================================================
```

---

## 🌐 四、访问界面

服务启动后，可以通过以下地址访问：

| 界面 | 地址 | 说明 |
|------|------|------|
| **Web 监控面板** | http://localhost:8765/ui | 内置监控界面 |
| **独立监控面板** | 打开 `dashboard.html` | 独立 HTML 文件 |
| **API 文档** | http://localhost:8765/docs | Swagger UI |
| **健康检查** | http://localhost:8765/health | 健康状态 |

### 跨端口访问配置

如果你想在**不同端口**访问监控面板：

**步骤 1:** 启动代理服务 (端口 8765)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

**步骤 2:** 在另一台机器或浏览器打开 `dashboard.html`

**步骤 3:** 在监控面板的配置中填入代理地址：
- Proxy API 地址：`http://your-server-ip:8765`
- 点击"保存配置"

**注意:** 如需远程访问，启动时请确保：
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8765
```
(`--host 0.0.0.0` 允许外部访问)

---

## 🧪 五、测试请求

### 使用内置测试界面

1. 访问 http://localhost:8765/ui
2. 点击"测试请求"标签
3. 填写模型和消息
4. 点击"发送请求"

### 使用 cURL

**OpenAI 兼容接口:**
```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "system", "content": "You are helpful."},
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

**Anthropic 兼容接口:**
```bash
curl -X POST http://localhost:8765/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 1024
  }'
```

**运行测试脚本:**
```bash
bash examples.sh
```

---

## ⚙️ 六、配置拦截规则

规则文件位于 `rules/` 目录：

| 文件 | 用途 |
|------|------|
| `request.yaml` | 请求拦截规则 |
| `response.yaml` | 响应拦截规则 |
| `passive.yaml` | 被动监控规则 (不修改) |

### 启用/禁用规则

编辑规则文件，修改 `enabled` 字段：

```yaml
rules:
  - id: "tag_system"
    enabled: true   # ← 改为 true 启用，false 禁用
    priority: 100
    scope: request
    description: "对 System Prompt 追加标签"
    match:
      role: system
    action:
      type: append_text
      text: "\n\n[RESEARCH_MODE: active]"
```

### 热重载规则

修改规则后无需重启服务：

**方法 1:** 访问 API
```bash
curl -X POST http://localhost:8765/rules/reload
```

**方法 2:** 在 Web 界面点击"刷新规则"

### 查看当前规则

```bash
curl http://localhost:8765/rules
```

---

## 📊 七、查看 Traces

### Web 界面查看

访问 http://localhost:8765/ui 或打开 `dashboard.html`

### API 查看

**列出最近的 Traces:**
```bash
curl http://localhost:8765/traces?limit=10
```

**查看单个 Trace:**
```bash
curl http://localhost:8765/traces/<trace_id>
```

**重放 Trace:**
```bash
curl -X POST http://localhost:8765/replay/<trace_id>
```

**使用修改后的请求重放:**
```bash
curl -X POST http://localhost:8765/replay/<trace_id> \
  -H "Content-Type: application/json" \
  -d '{"use_modified_request": true}'
```

**清空所有 Traces:**
```bash
curl -X DELETE http://localhost:8765/traces
```

### Trace 文件位置

- 索引文件：`logs/index.jsonl`
- 独立 Trace: `logs/traces/<trace_id>.json`

---

## 🔧 八、常见配置场景

### 场景 1: 仅记录，不修改 (Dry Run 模式)

在 `.env` 中设置：
```bash
DRY_RUN=true
```

此模式下，规则会匹配但不会实际修改请求/响应，仅记录"将会如何修改"。

### 场景 2: 只使用 OpenAI

在 `.env` 中只配置 OpenAI：
```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
# ANTHROPIC_API_KEY 留空或不设置
```

### 场景 3: 使用本地模型 (vLLM/LocalAI)

```bash
OPENAI_API_KEY=not-needed
OPENAI_BASE_URL=http://localhost:8000/v1
```

### 场景 4: 调试模式

```bash
LOG_LEVEL=DEBUG
DRY_RUN=true
TRACE_ENABLED=true
```

---

## 🏗️ 九、项目结构

```
router/
├── app/
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 配置管理
│   ├── adapters/            # Provider 适配器
│   │   ├── base.py
│   │   ├── openai_adapter.py
│   │   └── anthropic_adapter.py
│   ├── rules/               # 规则引擎
│   │   ├── engine.py
│   │   ├── loader.py
│   │   ├── matchers.py
│   │   └── actions.py
│   ├── schemas/             # 数据模型
│   │   ├── models.py
│   │   ├── rules.py
│   │   └── traces.py
│   ├── services/            # 核心服务
│   │   ├── proxy.py
│   │   ├── trace_store.py
│   │   └── replay.py
│   └── utils/               # 工具函数
│       ├── ids.py
│       └── logging.py
├── rules/                   # 规则配置
│   ├── request.yaml
│   ├── response.yaml
│   └── passive.yaml
├── logs/                    # 日志和 Traces
│   ├── index.jsonl
│   └── traces/
├── tests/                   # 测试
├── .env.example             # 环境变量模板
├── .env                     # 实际配置 (需创建)
├── requirements.txt         # Python 依赖
├── pyproject.toml
├── README.md
├── dashboard.html           # 独立监控面板
└── examples.sh              # cURL 示例
```

---

## 🧪 十、运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 带覆盖率报告
pytest tests/ -v --cov=app --cov-report=html

# 运行特定测试
pytest tests/test_rules.py -v
```

---

## 🔍 十一、监控面板功能

### 独立监控面板 (dashboard.html)

用浏览器直接打开 `dashboard.html` 文件即可使用。

**功能:**
- 📊 Traces 列表和详情
- 🎯 实时拦截监控 (每 3 秒自动刷新)
- 🧪 测试请求发送
- ⚙️ 规则查看

**配置:**
1. 在"API 配置"栏输入代理地址
2. 如跨端口访问，填入监控端口
3. 点击"保存配置"

### 内置 Web 界面 (/ui)

访问 `http://localhost:8765/ui`

功能与独立面板类似，但集成在代理服务中。

---

## 📝 十二、Claude Code / OpenClaw 接入

### Claude Code 接入

设置环境变量：
```bash
export ANTHROPIC_BASE_URL=http://localhost:8765
```

或在配置文件中：
```yaml
anthropic:
  base_url: http://localhost:8765
  api_key: your-key
```

### OpenAI 客户端接入

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

### 通用 HTTP 客户端

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
```

---

## 🔮 十三、扩展到 Streaming

当前版本仅支持非流式请求。如需支持 streaming：

1. 在请求中添加 `stream: true`
2. 修改 `app/adapters/*.py` 中的 `invoke` 方法
3. 使用 httpx 的流式 API: `async with client.stream(...)`
4. 以 SSE 格式转发响应

由于涉及较复杂的流式处理，MVP 版本暂未实现。

---

## ⚠️ 重要提示

1. **本工具仅限授权实验环境使用**
2. **不要在生产环境使用默认配置**
3. **日志包含 API 交互内容，请妥善保管**
4. **默认 CORS 配置允许所有来源 (便于调试)，生产环境请限制**
5. **规则文件可能包含敏感模式，已加入 `.gitignore`**

---

## 🆘 故障排除

### 问题 1: 启动失败，提示导入错误
```bash
pip install -r requirements.txt --upgrade
```

### 问题 2: API 密钥错误
检查 `.env` 文件是否正确配置，确认没有多余空格。

### 问题 3: 端口被占用
修改 `.env` 中的 `PORT` 值，或启动时指定：
```bash
uvicorn app.main:app --port 8766
```

### 问题 4: 远程无法访问
确保启动时使用 `--host 0.0.0.0`，并检查防火墙设置。

### 问题 5: 规则不生效
- 检查规则的 `enabled` 是否为 `true`
- 检查 `scope` 是否正确 (request/response/passive)
- 运行 `curl -X POST http://localhost:8765/rules/reload` 重载规则
