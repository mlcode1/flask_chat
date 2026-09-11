# Flask Chat

---

## 中文

### 项目简介

Flask Chat 是一个基于 Flask 构建的 AI 智能对话应用，支持多模型切换、流式输出、工具调用、上下文压缩与长期记忆、RAG（检索增强生成）知识库系统、LangSmith 全链路监控以及 AI 回答结果验证。数据存储在 PostgreSQL（含 pgvector 向量扩展）中，前端采用原生 JavaScript 实现单页应用。

### 功能特性

- **多模型切换** — 支持配置多个大语言模型，用户可在对话中自由切换；兼容 OpenAI API 协议的任意服务（包括 Ollama 本地模型）
- **流式输出** — 基于 Server-Sent Events（SSE）实现逐字流式响应
- **流式打断** — 支持在 AI 回复过程中随时打断生成
- **工具调用** — 支持 Function Calling，内置获取时间、数学计算、代码执行、数据库查询、文件读取、知识库检索、网页搜索等工具；`web_search` 支持 Tavily / Bing / DuckDuckGo 多源自动切换
- **RAG 知识检索** — 上传文档后，AI 可通过工具调用自动检索知识库回答问题；支持 BM25 + 向量混合检索、多查询重写、结果重排序
- **本地模型支持** — 通过 Ollama 可直接使用本地部署的大语言模型和 Embedding 模型，无需任何云服务；Embedding 也可接入第三方服务
- **多轮记忆与上下文压缩** — 结构化摘要 + 长期记忆，跨轮次保留关键信息；对话过长时自动压缩历史消息，节省 Token 用量
- **结果验证（Result Verification）** — 可选开关，开启后由另一个 Agent 对 AI 回答进行事实、逻辑、完整性与清晰度的多维度验证，支持自动验证与手动验证
- **协作与分享** — 一键生成分享链接（`/share/<token>` 公开查看页）、对话导出（Markdown / JSON / TXT）
- **响应缓存** — 相同问题 + 相同上下文命中缓存时直接返回，提升响应速度
- **错误恢复** — 自动重试（指数退避）、主模型失败降级到备用模型、健康检查接口
- **交互体验** — Markdown 渲染（含代码高亮、一键复制）、消息点赞/点踩反馈
- **可视化与调试** — Token 统计面板 + 工具调用可视化，调试面板展示系统/缓存/模型状态
- **LangSmith 监控** — 通过 LangSmith 实现 LLM 调用、RAG 检索、上下文构建等关键流程的全链路可观测
- **安全防护** — 可选 API Key 鉴权、Prompt Injection 输入过滤、审计日志

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask |
| ORM | Flask-SQLAlchemy |
| 数据库 | PostgreSQL + pgvector |
| LLM 接口 | OpenAI SDK（兼容任意 OpenAI 协议的服务） |
| Embedding 模型 | Ollama（qwen3-embedding:8b）或第三方 Embedding 服务 |
| 向量检索 | pgvector（余弦相似度 + BM25 混合检索） |
| 文件解析 | pypdf、python-docx |
| 可观测性 | LangSmith（`@traceable` 装饰器 + 环境变量） |
| 前端 | 原生 HTML / CSS / JavaScript（marked.js 渲染 Markdown） |

### 项目结构

```
flask_chat/
├── run.py                        # 启动入口
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量模板
└── app/
    ├── __init__.py               # 应用工厂（create_app）
    ├── config.py                 # 配置类
    ├── extensions.py             # Flask 扩展（SQLAlchemy）
    ├── models.py                 # 数据模型
    ├── middleware.py             # 中间件（免责声明等）
    ├── routes/
    │   ├── chat.py               # 对话、验证、分享、导出、反馈、审计路由
    │   └── rag.py                # RAG 知识库路由
    ├── services/
    │   ├── ai_service.py         # AI 服务（流式输出 + 工具调用循环 + 模型降级）
    │   ├── context_service.py    # 上下文管理（窗口裁剪 + 压缩 + 长期记忆）
    │   ├── rag_service.py        # RAG 服务（解析/分块/嵌入/存储/混合检索）
    │   ├── verifier_service.py   # 结果验证服务（独立 Agent 验证）
    │   ├── tool_service.py       # 工具定义与执行（多源 web_search 等）
    │   ├── cache_service.py      # 响应缓存
    │   ├── retry_service.py      # 重试与降级（指数退避 + fallback）
    │   └── security_service.py   # 安全（API Key 认证 / 注入过滤 / 审计日志）
    ├── static/
    │   ├── css/style.css
    │   └── js/chat.js
    └── templates/
        ├── index.html            # 主对话页
        └── shared.html           # 分享对话查看页
```

### 数据模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `Conversation` | `conversations` | 对话（含 `summary` 摘要、`memory` 长期记忆） |
| `Message` | `messages` | 消息（含 `tool_calls`、`verification`、`token_count`、`feedback`、`image_urls` 等） |
| `Document` | `documents` | 知识库文档 |
| `DocumentChunk` | `document_chunks` | 文档分块（含向量 `embedding`） |
| `SharedConversation` | `shared_conversations` | 分享链接 |
| `ConversationTemplate` | `conversation_templates` | 对话模板 |
| `AuditLog` | `audit_logs` | 审计日志 |

### 环境要求

- Python 3.10+
- PostgreSQL 15+（需安装 pgvector 扩展）
- Ollama（用于本地 Embedding 模型，也可选用于本地大语言模型）

### 快速开始

**1. 克隆项目并安装依赖**

```bash
git clone <repo-url>
cd flask_chat
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. 安装 pgvector 扩展**

确保 PostgreSQL 安装了 pgvector 扩展，然后执行：

```bash
psql -U <username> -d flask_chat -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> 应用启动时也会自动执行 `CREATE EXTENSION IF NOT EXISTS vector`。

**3. 安装并启动 Ollama**

Ollama 用于本地 Embedding 模型，也可作为大语言模型使用（无需任何云服务）：

```bash
# 拉取 Embedding 模型（必选）
ollama pull qwen3-embedding:8b

# （可选）拉取本地大语言模型，用于对话
ollama pull qwen2.5:7b

ollama serve
```

> **提示：** 如果只想用 Ollama 做 Embedding，主 LLM 仍用云端 API（如 OpenAI、火山引擎等），可跳过拉取对话模型这一步。

**4. 配置环境变量**

复制 `.env.example` 为 `.env`，并根据实际情况修改：

```bash
cp .env.example .env
```

关键配置项说明：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | - |
| `OPENAI_API_KEY` | LLM API 密钥 | - |
| `OPENAI_BASE_URL` | LLM API 地址 | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 默认模型 | `gpt-4o` |
| `AVAILABLE_MODELS` | 可用模型列表（逗号分隔） | `Qwen3.7-Max` |
| `MAX_CONTEXT_TOKENS` | 上下文窗口大小 | `4000` |
| `OLLAMA_BASE_URL` | Ollama API 地址 | `http://localhost:11434/v1` |
| `EMBEDDING_BASE_URL` | Embedding 服务 API 地址（默认同 `OLLAMA_BASE_URL`） | `http://localhost:11434/v1` |
| `EMBEDDING_API_KEY` | Embedding 服务 API Key（Ollama 填 `ollama`，第三方填真实 Key） | `ollama` |
| `EMBEDDING_MODEL` | Embedding 模型名称 | `qwen3-embedding:8b` |
| `EMBEDDING_DIM` | 向量维度 | `4096` |
| `CHUNK_SIZE` | 文档分块大小（字符数） | `500` |
| `CHUNK_OVERLAP` | 分块重叠大小 | `50` |
| `RAG_TOP_K` | 检索返回的文档块数量 | `5` |
| `RAG_HYBRID_ENABLED` | 是否启用 BM25 + 向量混合检索 | `true` |
| `RAG_BM25_WEIGHT` | 混合检索中 BM25 权重 | `0.3` |
| `RAG_VECTOR_WEIGHT` | 混合检索中向量权重 | `0.7` |
| `RAG_QUERY_REWRITE_ENABLED` | 是否启用多查询重写 | `false` |
| `RAG_RERANK_ENABLED` | 是否启用结果重排序 | `false` |
| `WEB_SEARCH_ENABLED` | 是否启用网页搜索工具 | `false` |
| `WEB_SEARCH_PROVIDER` | 网页搜索提供商（tavily / bing / duckduckgo） | `duckduckgo` |
| `TAVILY_API_KEY` | Tavily API Key（可选，最稳定） | 空 |
| `CODE_EXEC_ENABLED` | 是否启用代码执行工具 | `true` |
| `API_KEY` | API 鉴权密钥（留空则跳过鉴权） | 空 |
| `INPUT_FILTER_ENABLED` | 是否启用 Prompt Injection 输入过滤 | `true` |
| `CACHE_ENABLED` | 是否启用响应缓存 | `true` |
| `CACHE_TTL_HOURS` | 缓存有效期（小时） | `1` |
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `FALLBACK_MODEL` | 备用模型（主模型失败时降级） | 空 |
| `VERIFY_ENABLED` | 是否启用结果验证 | `false` |
| `VERIFY_MODEL` | 验证 Agent 使用的模型（留空则与主模型一致） | 空 |
| `AI_DISCLAIMER_TEXT` | AI 免责声明文字（留空则不追加） | 空 |
| `LANGCHAIN_TRACING_V2` | 是否启用 LangSmith 追踪 | `false` |
| `LANGCHAIN_PROJECT` | LangSmith 项目名 | `flask_chat` |
| `LANGCHAIN_API_KEY` | LangSmith API Key | - |
| `LANGCHAIN_ENDPOINT` | LangSmith 服务端点 | `https://api.smith.langchain.com` |

**5. 数据库初始化**

首次启动时 `db.create_all()` 会自动创建所有表，无需手动建表。

**6. 数据库迁移**

当 `models.py` 中的模型发生变化（新增字段、新表等），已有数据库不会自动更新，需要手动执行迁移脚本。本项目采用**手写 SQL 脚本**的方式进行迁移（脚本统一放在 `migrations/` 目录，按日期命名，如 `2026-09-11_add_xxx.sql`）。

**执行已有迁移脚本：**

```bash
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_advanced_features.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_memory_fields.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_feedback_field.sql
```

**新增迁移脚本的约定：**

1. 修改 `app/models.py`，添加新字段或新表
2. 在 `migrations/` 目录新建脚本，命名格式 `YYYY-MM-DD_描述.sql`
3. 脚本内容使用 `IF NOT EXISTS`，保证可重复执行，例如：

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS new_field VARCHAR(100) DEFAULT NULL;
```

4. 按日期顺序依次执行新脚本即可。建议在脚本头部用注释说明本次变更内容。

**7. 启动应用**

```bash
python run.py
```

访问 `http://localhost:8080` 即可使用。

生产环境可使用 Gunicorn：

```bash
gunicorn run:app -w 4 -b 0.0.0.0:8080
```

### 使用 Ollama 本地大语言模型

本项目基于 OpenAI SDK 调用 LLM，而 Ollama 原生提供 OpenAI 兼容 API，因此**无需改动代码**，只需调整 `.env` 配置即可切换到本地模型。

**步骤：**

1. 在 Ollama 拉取支持工具调用（Function Calling）的模型：

```bash
# 推荐：中文场景首选
ollama pull qwen2.5:7b

# 备选：英文场景
ollama pull llama3.1:8b
ollama pull mistral:7b

# 小显存（8GB）可用
ollama pull qwen2.5:3b
```

> ⚠️ **注意：** 必须拉取支持 tool calling 的模型（如 `qwen2.5`、`llama3.1`、`mistral`、`command-r`）。旧版 `llama2:7b`、`qwen:7b` 等不支持，调用会返回 400 错误。

2. 修改 `.env` 中的 LLM 配置：

```bash
# 将 LLM 指向本地 Ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama                # Ollama 不校验 key，但 SDK 要求非空
OPENAI_MODEL=qwen2.5:7b              # 默认模型（必须带 tag 如 :7b）
AVAILABLE_MODELS=qwen2.5:7b,qwen2.5:14b,llama3.1:8b
```

3. （可选）关闭外部服务，实现完全离线：

```bash
LANGCHAIN_TRACING_V2=false           # 关闭 LangSmith 上报
```

4. 重启 Flask 应用即可：

```bash
python run.py
```

**常见问题：**

- **首次对话卡顿**：Ollama 首次加载模型到显存/内存需 10–30 秒，后续请求正常。可用 `ollama run <model> "hi"` 提前预热。
- **模型 tag 必须精确**：`AVAILABLE_MODELS` 中要写完整 tag（如 `qwen2.5:7b`），不能只写 `qwen2.5`。
- **Embedding 模型切换**：如果更换 Embedding 模型（如从 `qwen3-embedding:8b` 换到 `nomic-embed-text`），需同步更新 `EMBEDDING_DIM`（前者 4096，后者 768），并重建 `document_chunks` 表。
- **混合模式**：可以同时配置云端 LLM（如 OpenAI）和本地 Ollama，通过 `AVAILABLE_MODELS` 列出多个模型，在前端下拉框自由切换。

### 使用第三方 Embedding 服务

Embedding 与大语言模型相互独立，可分别配置。若 Embedding 使用第三方服务（而非 Ollama），只需调整 `.env`：

```bash
EMBEDDING_BASE_URL=https://api.example.com/v1   # 第三方 Embedding 服务地址
EMBEDDING_API_KEY=your-real-api-key             # 第三方真实 Key
EMBEDDING_MODEL=text-embedding-3-large          # 第三方模型名
EMBEDDING_DIM=3072                              # 对应向量维度
```

RAG 相关业务（文档解析、分块、嵌入、混合检索）不依赖 LLM，因此 Embedding 换第三方后知识库功能可正常运行。只需确保 `EMBEDDING_DIM` 与所选模型的实际输出维度一致。

### 使用说明

- **对话** — 在输入框输入消息，按 Enter 发送，Shift+Enter 换行
- **切换模型** — 在顶部下拉框选择不同的大语言模型
- **打断生成** — AI 回复时点击「打断」按钮停止生成
- **知识库** — 在左侧栏点击「+」上传文档（支持 `.txt`、`.md`、`.pdf`、`.docx`），上传后 AI 会在需要时自动检索知识库
- **删除文档** — 在左侧栏文档列表中点击 `×` 删除已上传的文档
- **结果验证** — 顶部打开「结果验证」开关后，AI 回答完成后会自动触发验证；也可点击消息下方的「🔍 结果验证」按钮对历史回答手动验证。验证结果以卡片形式展示，包括通过/未通过、置信度、问题点等
- **分享对话** — 点击顶部「分享」按钮生成公开链接，其他人可通过 `/share/<token>` 查看（只读）
- **导出对话** — 点击顶部「导出」按钮，选择 Markdown / JSON / TXT 格式下载
- **反馈** — 点击消息下方的 👍 / 👎 对回答进行评价
- **调试面板** — 点击右下角 🐛 按钮查看系统状态、缓存状态、可用模型与 Token 统计
- **LangSmith 监控** — 启动应用后，在 [LangSmith](https://smith.langchain.com) 对应项目下查看 LLM 调用、RAG 检索、上下文构建的全链路追踪

### API 接口

#### 对话与管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页 |
| `GET` | `/api/models` | 获取可用模型列表 |
| `POST` | `/api/conversations` | 创建新对话 |
| `GET` | `/api/conversations/<id>/messages` | 获取对话消息（含 `tool_calls`、`token_count` 等） |
| `POST` | `/api/conversations/<id>/chat` | 发送消息并流式获取回复（SSE） |
| `POST` | `/api/conversations/<id>/interrupt` | 打断当前对话生成 |
| `DELETE` | `/api/conversations/<id>` | 删除对话 |
| `GET` | `/api/conversations/<id>/stats` | 获取对话 Token 统计 |

#### 结果验证

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config/verify` | 获取结果验证配置 |
| `POST` | `/api/config/verify` | 更新结果验证开关（请求体：`{"enabled": true/false}`） |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | 手动触发对某条回答的验证 |

#### 分享与导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/conversations/<id>/share` | 生成分享链接（返回 `share_token`） |
| `GET` | `/share/<token>` | 查看分享的对话（公开只读页） |
| `GET` | `/api/conversations/<id>/export` | 导出对话（`?format=markdown/json/txt`） |

#### 知识库（RAG）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/documents/upload` | 上传文档到知识库 |
| `GET` | `/api/documents` | 获取知识库文档列表 |
| `DELETE` | `/api/documents/<id>` | 删除知识库文档 |
| `POST` | `/api/documents/search` | 搜索知识库 |

#### 图片上传与反馈

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/upload/image` | 上传图片（多模态） |
| `POST` | `/api/messages/<msg_id>/feedback` | 提交消息反馈（`{"feedback": "like"/"dislike"}`） |

#### 系统与运维

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查（数据库/缓存状态） |
| `POST` | `/api/cache/clear` | 清空响应缓存 |
| `GET` | `/api/audit-logs` | 获取审计日志 |
| `GET` | `/api/config/disclaimer` | 获取免责声明配置 |
| `POST` | `/api/config/disclaimer` | 更新免责声明配置 |

#### 聊天流式事件（SSE）

`/api/conversations/<id>/chat` 通过 SSE 推送以下事件类型：

| 事件字段 | 说明 |
|----------|------|
| `token` | 增量文本片段 |
| `tool_calls` | 工具调用记录（含工具名、参数、结果） |
| `done` | 回答完成，附带 `content`、`message_id`、`token_count` |
| `verifying` | 验证开关开启时，回答完成后触发验证 |
| `verified` | 验证完成，附带 `is_correct`、`confidence`、`explanation`、`issues` 等结构化结果 |
| `error` | 错误信息 |

---

## English

### Introduction

Flask Chat is an AI-powered chat application built with Flask. It supports multi-model switching, streaming responses, tool calling, context compression with long-term memory, a RAG (Retrieval-Augmented Generation) knowledge base, LangSmith observability, and an optional AI answer verification feature. Data is stored in PostgreSQL (with the pgvector extension), and the frontend is a vanilla JavaScript single-page application.

### Features

- **Multi-Model Support** — Configure multiple LLMs and switch between them during conversations; compatible with any OpenAI-protocol service (including Ollama local models)
- **Streaming Output** — Token-by-token streaming responses via Server-Sent Events (SSE)
- **Stream Interruption** — Stop AI generation at any time
- **Tool Calling** — Function Calling with built-in tools: current time, math calculation, code execution, database query, file reading, knowledge-base search, web search; `web_search` supports Tavily / Bing / DuckDuckGo with automatic fallback
- **RAG Knowledge Base** — Upload documents and let the AI automatically search the knowledge base when answering questions; supports BM25 + vector hybrid search, multi-query rewriting, and result reranking
- **Local Model Support** — Run both LLM and Embedding models locally via Ollama, no cloud service required; embedding can also use a third-party service
- **Multi-turn Memory & Context Compression** — Structured summarization + long-term memory across turns; automatically compresses older messages when conversations get too long
- **Result Verification** — Optional toggle that runs a second agent to validate every AI answer for accuracy, logic, completeness, and clarity. Supports both auto-verification and manual on-demand verification
- **Sharing & Export** — One-click share links (`/share/<token>` public view) and conversation export (Markdown / JSON / TXT)
- **Response Cache** — Returns cached results when the same question + context is repeated, improving response speed
- **Error Recovery** — Automatic retry with exponential backoff, fallback to a backup model, and a health check endpoint
- **Interaction** — Markdown rendering (syntax highlighting, one-click copy) and message like/dislike feedback
- **Visualization & Debugging** — Token statistics panel + tool-call visualization; a debug panel shows system/cache/model status
- **LangSmith Observability** — End-to-end tracing for LLM calls, RAG retrieval, and context building
- **Security** — Optional API key auth, Prompt Injection input filtering, and audit logging

### Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask |
| ORM | Flask-SQLAlchemy |
| Database | PostgreSQL + pgvector |
| LLM Interface | OpenAI SDK (compatible with any OpenAI-protocol service) |
| Embedding Model | Ollama (qwen3-embedding:8b) or third-party embedding service |
| Vector Search | pgvector (cosine similarity + BM25 hybrid search) |
| File Parsing | pypdf, python-docx |
| Observability | LangSmith (`@traceable` decorator + env vars) |
| Frontend | Vanilla HTML / CSS / JavaScript (marked.js for Markdown) |

### Project Structure

```
flask_chat/
├── run.py                        # Entry point
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
└── app/
    ├── __init__.py               # App factory (create_app)
    ├── config.py                 # Configuration class
    ├── extensions.py             # Flask extensions (SQLAlchemy)
    ├── models.py                 # Database models
    ├── middleware.py             # Middleware (disclaimer, etc.)
    ├── routes/
    │   ├── chat.py               # Chat, verification, sharing, export, feedback, audit routes
    │   └── rag.py                # RAG knowledge base routes
    ├── services/
    │   ├── ai_service.py         # AI service (streaming + tool call loop + model fallback)
    │   ├── context_service.py    # Context management (window + compression + long-term memory)
    │   ├── rag_service.py        # RAG service (parse/chunk/embed/store/hybrid search)
    │   ├── verifier_service.py   # Result verification service (second-agent validation)
    │   ├── tool_service.py       # Tool definitions and execution (multi-source web_search)
    │   ├── cache_service.py      # Response cache
    │   ├── retry_service.py      # Retry & fallback (exponential backoff)
    │   └── security_service.py   # Security (API key auth / injection filter / audit log)
    ├── static/
    │   ├── css/style.css
    │   └── js/chat.js
    └── templates/
        ├── index.html            # Main chat page
        └── shared.html           # Shared conversation view page
```

### Data Models

| Model | Table | Description |
|-------|-------|-------------|
| `Conversation` | `conversations` | Conversation (with `summary` and `memory` fields) |
| `Message` | `messages` | Message (with `tool_calls`, `verification`, `token_count`, `feedback`, `image_urls`, etc.) |
| `Document` | `documents` | Knowledge base document |
| `DocumentChunk` | `document_chunks` | Document chunk (with `embedding` vector) |
| `SharedConversation` | `shared_conversations` | Share link |
| `ConversationTemplate` | `conversation_templates` | Conversation template |
| `AuditLog` | `audit_logs` | Audit log |

### Prerequisites

- Python 3.10+
- PostgreSQL 15+ (with pgvector extension installed)
- Ollama (for local embedding model, and optionally for local LLM)

### Quick Start

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd flask_chat
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Install pgvector extension**

Make sure pgvector is installed on your PostgreSQL server, then run:

```bash
psql -U <username> -d flask_chat -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> The app also runs `CREATE EXTENSION IF NOT EXISTS vector` automatically on startup.

**3. Install and start Ollama**

Ollama is used for local embedding models, and can also serve as the main LLM (no cloud service required):

```bash
# Pull embedding model (required)
ollama pull qwen3-embedding:8b

# (Optional) Pull a local LLM for chat
ollama pull qwen2.5:7b

ollama serve
```

> **Tip:** If you only want to use Ollama for embeddings and keep the main LLM on a cloud API (e.g., OpenAI), you can skip pulling the chat model.

**4. Configure environment variables**

Copy `.env.example` to `.env` and modify as needed:

```bash
cp .env.example .env
```

Key configuration options:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | - |
| `OPENAI_API_KEY` | LLM API key | - |
| `OPENAI_BASE_URL` | LLM API endpoint | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | Default model | `gpt-4o` |
| `AVAILABLE_MODELS` | Available models (comma-separated) | `Qwen3.7-Max` |
| `MAX_CONTEXT_TOKENS` | Context window size | `4000` |
| `OLLAMA_BASE_URL` | Ollama API endpoint | `http://localhost:11434/v1` |
| `EMBEDDING_BASE_URL` | Embedding service API endpoint (defaults to `OLLAMA_BASE_URL`) | `http://localhost:11434/v1` |
| `EMBEDDING_API_KEY` | Embedding service API key (`ollama` for Ollama, real key for third-party) | `ollama` |
| `EMBEDDING_MODEL` | Embedding model name | `qwen3-embedding:8b` |
| `EMBEDDING_DIM` | Embedding vector dimension | `4096` |
| `CHUNK_SIZE` | Document chunk size (characters) | `500` |
| `CHUNK_OVERLAP` | Chunk overlap size | `50` |
| `RAG_TOP_K` | Number of chunks to retrieve | `5` |
| `RAG_HYBRID_ENABLED` | Enable BM25 + vector hybrid search | `true` |
| `RAG_BM25_WEIGHT` | BM25 weight in hybrid search | `0.3` |
| `RAG_VECTOR_WEIGHT` | Vector weight in hybrid search | `0.7` |
| `RAG_QUERY_REWRITE_ENABLED` | Enable multi-query rewriting | `false` |
| `RAG_RERANK_ENABLED` | Enable result reranking | `false` |
| `WEB_SEARCH_ENABLED` | Enable web search tool | `false` |
| `WEB_SEARCH_PROVIDER` | Web search provider (tavily / bing / duckduckgo) | `duckduckgo` |
| `TAVILY_API_KEY` | Tavily API key (optional, most stable) | empty |
| `CODE_EXEC_ENABLED` | Enable code execution tool | `true` |
| `API_KEY` | API authentication key (empty = skip auth) | empty |
| `INPUT_FILTER_ENABLED` | Enable Prompt Injection input filtering | `true` |
| `CACHE_ENABLED` | Enable response caching | `true` |
| `CACHE_TTL_HOURS` | Cache TTL (hours) | `1` |
| `MAX_RETRIES` | Maximum retry count | `3` |
| `FALLBACK_MODEL` | Fallback model (used when primary fails) | empty |
| `VERIFY_ENABLED` | Enable result verification | `false` |
| `VERIFY_MODEL` | Model used by the verification agent (empty = same as main) | empty |
| `AI_DISCLAIMER_TEXT` | AI disclaimer text (empty = no disclaimer) | empty |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | `false` |
| `LANGCHAIN_PROJECT` | LangSmith project name | `flask_chat` |
| `LANGCHAIN_API_KEY` | LangSmith API key | - |
| `LANGCHAIN_ENDPOINT` | LangSmith endpoint | `https://api.smith.langchain.com` |

**5. Database initialization**

`db.create_all()` creates all tables automatically on first run — no manual table creation needed.

**6. Database migration**

When `models.py` changes (new fields, new tables, etc.), existing databases are not updated automatically — you must run migration scripts manually. This project uses **hand-written SQL scripts** for migrations (stored in the `migrations/` directory, named by date, e.g., `2026-09-11_add_xxx.sql`).

**Running existing migration scripts:**

```bash
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_advanced_features.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_memory_fields.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_feedback_field.sql
```

**Convention for adding a new migration:**

1. Modify `app/models.py` to add the new field or table
2. Create a new script in `migrations/` named `YYYY-MM-DD_description.sql`
3. Use `IF NOT EXISTS` in the script so it is safe to re-run, for example:

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS new_field VARCHAR(100) DEFAULT NULL;
```

4. Run new scripts in date order. It's recommended to add a comment at the top of each script describing the change.

**7. Run the application**

```bash
python run.py
```

Open `http://localhost:8080` in your browser.

For production, use Gunicorn:

```bash
gunicorn run:app -w 4 -b 0.0.0.0:8080
```

### Using Ollama as Local LLM

This project uses the OpenAI SDK to call LLMs, and Ollama natively provides an OpenAI-compatible API, so **no code changes are needed** — just adjust the `.env` configuration to switch to local models.

**Steps:**

1. Pull a model that supports tool calling (Function Calling) in Ollama:

```bash
# Recommended: best for Chinese
ollama pull qwen2.5:7b

# Alternatives: better for English
ollama pull llama3.1:8b
ollama pull mistral:7b

# Low VRAM (8GB)
ollama pull qwen2.5:3b
```

> ⚠️ **Note:** You must pull a model that supports tool calling (e.g., `qwen2.5`, `llama3.1`, `mistral`, `command-r`). Older models like `llama2:7b` or `qwen:7b` do not support it and will return 400 errors.

2. Update the LLM configuration in `.env`:

```bash
# Point the LLM to local Ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama                # Ollama doesn't verify keys, but the SDK requires a non-empty value
OPENAI_MODEL=qwen2.5:7b              # Default model (must include tag like :7b)
AVAILABLE_MODELS=qwen2.5:7b,qwen2.5:14b,llama3.1:8b
```

3. (Optional) Disable external services for fully offline operation:

```bash
LANGCHAIN_TRACING_V2=false           # Disable LangSmith reporting
```

4. Restart the Flask application:

```bash
python run.py
```

**Common issues:**

- **First request is slow**: Ollama loads the model into VRAM/RAM on first use (10–30 seconds). Subsequent requests are normal. You can warm up with `ollama run <model> "hi"`.
- **Model tags must be exact**: `AVAILABLE_MODELS` requires full tags (e.g., `qwen2.5:7b`), not just `qwen2.5`.
- **Switching embedding models**: If you change the embedding model (e.g., from `qwen3-embedding:8b` to `nomic-embed-text`), you must update `EMBEDDING_DIM` accordingly (4096 → 768) and rebuild the `document_chunks` table.
- **Hybrid mode**: You can configure both cloud LLMs (e.g., OpenAI) and local Ollama models together — list multiple models in `AVAILABLE_MODELS` and switch freely from the frontend dropdown.

### Using a Third-Party Embedding Service

Embedding and LLM are independent and can be configured separately. To use a third-party embedding service (instead of Ollama), just adjust `.env`:

```bash
EMBEDDING_BASE_URL=https://api.example.com/v1   # Third-party embedding endpoint
EMBEDDING_API_KEY=your-real-api-key             # Third-party API key
EMBEDDING_MODEL=text-embedding-3-large          # Third-party model name
EMBEDDING_DIM=3072                              # Matching vector dimension
```

RAG functionality (document parsing, chunking, embedding, hybrid search) does not depend on the LLM, so the knowledge base keeps working after switching to a third-party embedding provider. Just make sure `EMBEDDING_DIM` matches the actual output dimension of the chosen model.

### Usage

- **Chat** — Type a message in the input box, press Enter to send, Shift+Enter for new line
- **Switch Models** — Select a different LLM from the dropdown at the top
- **Interrupt** — Click the "Interrupt" button during AI generation to stop it
- **Knowledge Base** — Click "+" in the sidebar to upload documents (supports `.txt`, `.md`, `.pdf`, `.docx`). The AI will automatically search the knowledge base when needed
- **Delete Documents** — Click "×" next to a document in the sidebar to remove it
- **Result Verification** — Toggle the "Result Verification" switch in the header to auto-verify every AI answer. You can also click the "🔍 Verify" button on any message for manual on-demand verification. Results are shown as a card with pass/fail, confidence, and issues
- **Share Conversation** — Click the "Share" button to generate a public link viewable via `/share/<token>` (read-only)
- **Export Conversation** — Click the "Export" button and choose Markdown / JSON / TXT format to download
- **Feedback** — Click 👍 / 👎 below a message to rate the answer
- **Debug Panel** — Click the 🐛 button in the bottom-right corner to view system status, cache status, available models, and token statistics
- **LangSmith Monitoring** — After launching, visit [LangSmith](https://smith.langchain.com) to inspect end-to-end traces for LLM calls, RAG retrieval, and context building

### API Endpoints

#### Chat & Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main page |
| `GET` | `/api/models` | List available models |
| `POST` | `/api/conversations` | Create a new conversation |
| `GET` | `/api/conversations/<id>/messages` | Get messages (with `tool_calls`, `token_count`, etc.) |
| `POST` | `/api/conversations/<id>/chat` | Send message and stream response (SSE) |
| `POST` | `/api/conversations/<id>/interrupt` | Interrupt active generation |
| `DELETE` | `/api/conversations/<id>` | Delete a conversation |
| `GET` | `/api/conversations/<id>/stats` | Get conversation token statistics |

#### Result Verification

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config/verify` | Get result verification configuration |
| `POST` | `/api/config/verify` | Toggle result verification (`{"enabled": true/false}`) |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | Manually trigger verification for a message |

#### Sharing & Export

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/conversations/<id>/share` | Generate share link (returns `share_token`) |
| `GET` | `/share/<token>` | View a shared conversation (public read-only page) |
| `GET` | `/api/conversations/<id>/export` | Export conversation (`?format=markdown/json/txt`) |

#### Knowledge Base (RAG)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/documents/upload` | Upload a document to the knowledge base |
| `GET` | `/api/documents` | List knowledge base documents |
| `DELETE` | `/api/documents/<id>` | Delete a knowledge base document |
| `POST` | `/api/documents/search` | Search the knowledge base |

#### Image Upload & Feedback

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload/image` | Upload an image (multimodal) |
| `POST` | `/api/messages/<msg_id>/feedback` | Submit message feedback (`{"feedback": "like"/"dislike"}`) |

#### System & Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check (database/cache status) |
| `POST` | `/api/cache/clear` | Clear response cache |
| `GET` | `/api/audit-logs` | Get audit logs |
| `GET` | `/api/config/disclaimer` | Get disclaimer configuration |
| `POST` | `/api/config/disclaimer` | Update disclaimer configuration |

#### Chat SSE Event Types

`/api/conversations/<id>/chat` emits the following event types over SSE:

| Event Field | Description |
|-------------|-------------|
| `token` | Incremental text fragment |
| `tool_calls` | Tool call records (tool name, arguments, result) |
| `done` | Response complete, with `content`, `message_id`, `token_count` |
| `verifying` | Verification started (when verify toggle is on) |
| `verified` | Verification complete, with `is_correct`, `confidence`, `explanation`, `issues` |
| `error` | Error message |
