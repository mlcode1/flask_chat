# Flask Chat

---

## 中文

### 项目简介

Flask Chat 是一个基于 Flask 构建的 AI 智能对话应用，支持多模型切换、流式输出、工具调用、上下文压缩、RAG（检索增强生成）知识库系统、LangSmith 全链路监控以及 AI 回答结果验证。数据存储在 PostgreSQL 中，前端采用原生 JavaScript 实现单页应用。

### 功能特性

- **多模型切换** — 支持配置多个大语言模型，用户可在对话中自由切换
- **流式输出** — 基于 Server-Sent Events（SSE）实现逐字流式响应
- **工具调用** — 支持 Function Calling，内置获取时间、数学计算、网页搜索等工具
- **RAG 知识检索** — 上传文档后，AI 可通过工具调用自动检索知识库回答问题
- **上下文压缩** — 对话过长时自动压缩历史消息，节省 Token 用量
- **流式打断** — 支持在 AI 回复过程中随时打断生成
- **结果验证（Result Verification）** — 可选开关，开启后由另一个 Agent 对 AI 回答进行事实、逻辑、完整性与清晰度的多维度验证，支持自动验证与手动验证
- **LangSmith 监控** — 通过 LangSmith 实现 LLM 调用、RAG 检索、上下文构建等关键流程的全链路可观测

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask |
| ORM | Flask-SQLAlchemy |
| 数据库 | PostgreSQL + pgvector |
| LLM 接口 | OpenAI SDK（兼容任意 OpenAI 协议的服务） |
| Embedding 模型 | Ollama（qwen3-embedding:8b） |
| 向量检索 | pgvector（余弦相似度） |
| 文件解析 | pypdf、python-docx |
| 可观测性 | LangSmith（`@traceable` 装饰器 + 环境变量） |
| 前端 | 原生 HTML / CSS / JavaScript |

### 项目结构

```
flask_chat/
├── run.py                    # 启动入口
├── requirements.txt          # Python 依赖
├── .env                      # 环境变量配置
├── .env.example              # 环境变量模板
└── app/
    ├── __init__.py           # 应用工厂（create_app）
    ├── config.py             # 配置类
    ├── extensions.py         # Flask 扩展（SQLAlchemy）
    ├── models.py             # 数据模型
    ├── middleware.py          # 中间件
    ├── routes/
    │   ├── chat.py           # 对话、结果验证配置、手动验证路由
    │   └── rag.py            # RAG 知识库路由
    ├── services/
    │   ├── ai_service.py     # AI 服务（流式输出 + 工具调用循环）
    │   ├── context_service.py # 上下文管理（窗口裁剪 + 压缩）
    │   ├── rag_service.py    # RAG 服务（解析/分块/嵌入/存储/检索）
    │   ├── verifier_service.py # 结果验证服务（独立 Agent 验证）
    │   └── tool_service.py   # 工具定义与执行
    ├── static/
    │   ├── css/style.css
    │   └── js/chat.js
    └── templates/
        └── index.html
```

### 环境要求

- Python 3.10+
- PostgreSQL 15+（需安装 pgvector 扩展）
- Ollama（用于本地 Embedding 模型）

### 快速开始

**1. 克隆项目并安装依赖**

```bash
git clone <repo-url>
cd flask_chat
pip install -r requirements.txt
```

**2. 安装 pgvector 扩展**

确保 PostgreSQL 安装了 pgvector 扩展，然后执行：

```bash
psql -U <username> -d flask_chat -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**3. 安装并启动 Ollama**

```bash
ollama pull qwen3-embedding:8b
ollama serve
```

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
| `EMBEDDING_MODEL` | Embedding 模型名称 | `qwen3-embedding:8b` |
| `EMBEDDING_DIM` | 向量维度 | `4096` |
| `CHUNK_SIZE` | 文档分块大小（字符数） | `500` |
| `CHUNK_OVERLAP` | 分块重叠大小 | `50` |
| `RAG_TOP_K` | 检索返回的文档块数量 | `5` |
| `VERIFY_ENABLED` | 是否启用结果验证 | `false` |
| `VERIFY_MODEL` | 验证 Agent 使用的模型（留空则与主模型一致） | 空 |
| `LANGCHAIN_TRACING_V2` | 是否启用 LangSmith 追踪 | `true` |
| `LANGCHAIN_PROJECT` | LangSmith 项目名 | `flask_chat` |
| `LANGCHAIN_API_KEY` | LangSmith API Key | - |
| `LANGCHAIN_ENDPOINT` | LangSmith 服务端点 | `https://api.smith.langchain.com` |

**5. 数据库初始化**

如果是首次启动，`db.create_all()` 会自动建表。如果是从旧版本升级（新增了 `verification` 字段），需要手动执行：

```sql
ALTER TABLE messages ADD COLUMN verification JSON;
```

**6. 启动应用**

```bash
python run.py
```

访问 `http://localhost:8080` 即可使用。

生产环境可使用 Gunicorn：

```bash
gunicorn run:app -w 4 -b 0.0.0.0:8080
```

### 使用说明

- **对话** — 在输入框输入消息，按 Enter 发送，Shift+Enter 换行
- **切换模型** — 在顶部下拉框选择不同的大语言模型
- **打断生成** — AI 回复时点击「打断」按钮停止生成
- **知识库** — 在左侧栏点击「+」上传文档（支持 `.txt`、`.md`、`.pdf`、`.docx`），上传后 AI 会在需要时自动检索知识库
- **删除文档** — 在左侧栏文档列表中点击 `×` 删除已上传的文档
- **结果验证** — 顶部打开「结果验证」开关后，AI 回答完成后会自动触发验证；也可点击消息下方的「🔍 结果验证」按钮对历史回答手动验证。验证结果以卡片形式展示，包括通过/未通过、置信度、问题点等
- **LangSmith 监控** — 启动应用后，在 [LangSmith](https://smith.langchain.com) 对应项目下查看 LLM 调用、RAG 检索、上下文构建的全链路追踪

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页 |
| `GET` | `/api/models` | 获取可用模型列表 |
| `GET` | `/api/config/verify` | 获取结果验证配置 |
| `POST` | `/api/config/verify` | 更新结果验证开关（请求体：`{"enabled": true/false}`） |
| `POST` | `/api/conversations` | 创建新对话 |
| `GET` | `/api/conversations/<id>/messages` | 获取对话消息 |
| `POST` | `/api/conversations/<id>/chat` | 发送消息并流式获取回复（SSE） |
| `POST` | `/api/conversations/<id>/interrupt` | 打断当前对话生成 |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | 手动触发对某条回答的验证 |
| `DELETE` | `/api/conversations/<id>` | 删除对话 |
| `POST` | `/api/documents/upload` | 上传文档到知识库 |
| `GET` | `/api/documents` | 获取知识库文档列表 |
| `DELETE` | `/api/documents/<id>` | 删除知识库文档 |
| `POST` | `/api/documents/search` | 搜索知识库 |

#### 聊天流式事件（SSE）

`/api/conversations/<id>/chat` 通过 SSE 推送以下事件类型：

| 事件字段 | 说明 |
|----------|------|
| `token` | 增量文本片段 |
| `done` | 回答完成，附带 `content` 和 `message_id` |
| `verifying` | 验证开关开启时，回答完成后触发验证 |
| `verified` | 验证完成，附带 `is_correct`、`confidence`、`explanation`、`issues` 等结构化结果 |
| `error` | 错误信息 |

---

## English

### Introduction

Flask Chat is an AI-powered chat application built with Flask. It supports multi-model switching, streaming responses, tool calling, context compression, a RAG (Retrieval-Augmented Generation) knowledge base, LangSmith observability, and an optional AI answer verification feature. Data is stored in PostgreSQL, and the frontend is a vanilla JavaScript single-page application.

### Features

- **Multi-Model Support** — Configure multiple LLMs and switch between them during conversations
- **Streaming Output** — Token-by-token streaming responses via Server-Sent Events (SSE)
- **Tool Calling** — Function Calling with built-in tools: current time, math calculator, web search
- **RAG Knowledge Base** — Upload documents and let the AI automatically search the knowledge base when answering questions
- **Context Compression** — Automatically compresses older messages when conversations get too long, saving token usage
- **Stream Interruption** — Stop AI generation at any time
- **Result Verification** — Optional toggle that runs a second agent to validate every AI answer for accuracy, logic, completeness, and clarity. Supports both auto-verification and manual on-demand verification
- **LangSmith Observability** — End-to-end tracing for LLM calls, RAG retrieval, and context building via LangSmith

### Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask |
| ORM | Flask-SQLAlchemy |
| Database | PostgreSQL + pgvector |
| LLM Interface | OpenAI SDK (compatible with any OpenAI-protocol service) |
| Embedding Model | Ollama (qwen3-embedding:8b) |
| Vector Search | pgvector (cosine similarity) |
| File Parsing | pypdf, python-docx |
| Observability | LangSmith (`@traceable` decorator + env vars) |
| Frontend | Vanilla HTML / CSS / JavaScript |

### Project Structure

```
flask_chat/
├── run.py                    # Entry point
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables
├── .env.example              # Environment template
└── app/
    ├── __init__.py           # App factory (create_app)
    ├── config.py             # Configuration class
    ├── extensions.py         # Flask extensions (SQLAlchemy)
    ├── models.py             # Database models
    ├── middleware.py          # Middleware
    ├── routes/
    │   ├── chat.py           # Chat, result-verify config, and manual verify routes
    │   └── rag.py            # RAG knowledge base routes
    ├── services/
    │   ├── ai_service.py     # AI service (streaming + tool call loop)
    │   ├── context_service.py # Context management (window + compression)
    │   ├── rag_service.py    # RAG service (parse/chunk/embed/store/retrieve)
    │   ├── verifier_service.py # Result verification service (second-agent validation)
    │   └── tool_service.py   # Tool definitions and execution
    ├── static/
    │   ├── css/style.css
    │   └── js/chat.js
    └── templates/
        └── index.html
```

### Prerequisites

- Python 3.10+
- PostgreSQL 15+ (with pgvector extension installed)
- Ollama (for local embedding model)

### Quick Start

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd flask_chat
pip install -r requirements.txt
```

**2. Install pgvector extension**

Make sure pgvector is installed on your PostgreSQL server, then run:

```bash
psql -U <username> -d flask_chat -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**3. Install and start Ollama**

```bash
ollama pull qwen3-embedding:8b
ollama serve
```

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
| `EMBEDDING_MODEL` | Embedding model name | `qwen3-embedding:8b` |
| `EMBEDDING_DIM` | Embedding vector dimension | `4096` |
| `CHUNK_SIZE` | Document chunk size (characters) | `500` |
| `CHUNK_OVERLAP` | Chunk overlap size | `50` |
| `RAG_TOP_K` | Number of chunks to retrieve | `5` |
| `VERIFY_ENABLED` | Enable result verification | `false` |
| `VERIFY_MODEL` | Model used by the verification agent (empty = same as main) | empty |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | `true` |
| `LANGCHAIN_PROJECT` | LangSmith project name | `flask_chat` |
| `LANGCHAIN_API_KEY` | LangSmith API key | - |
| `LANGCHAIN_ENDPOINT` | LangSmith endpoint | `https://api.smith.langchain.com` |

**5. Database initialization**

`db.create_all()` will create missing tables on first run. If you are upgrading from a previous version (new `verification` field on `messages`), run this manually:

```sql
ALTER TABLE messages ADD COLUMN verification JSON;
```

**6. Run the application**

```bash
python run.py
```

Open `http://localhost:8080` in your browser.

For production, use Gunicorn:

```bash
gunicorn run:app -w 4 -b 0.0.0.0:8080
```

### Usage

- **Chat** — Type a message in the input box, press Enter to send, Shift+Enter for new line
- **Switch Models** — Select a different LLM from the dropdown at the top
- **Interrupt** — Click the "Interrupt" button during AI generation to stop it
- **Knowledge Base** — Click "+" in the sidebar to upload documents (supports `.txt`, `.md`, `.pdf`, `.docx`). The AI will automatically search the knowledge base when needed
- **Delete Documents** — Click "×" next to a document in the sidebar to remove it
- **Result Verification** — Toggle the "Result Verification" switch in the header to auto-verify every AI answer. You can also click the "🔍 Verify" button on any message for manual on-demand verification. Results are shown as a card with pass/fail, confidence, and issues
- **LangSmith Monitoring** — After launching, visit [LangSmith](https://smith.langchain.com) to inspect end-to-end traces for LLM calls, RAG retrieval, and context building

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main page |
| `GET` | `/api/models` | List available models |
| `GET` | `/api/config/verify` | Get result verification configuration |
| `POST` | `/api/config/verify` | Toggle result verification (`{"enabled": true/false}`) |
| `POST` | `/api/conversations` | Create a new conversation |
| `GET` | `/api/conversations/<id>/messages` | Get messages for a conversation |
| `POST` | `/api/conversations/<id>/chat` | Send message and stream response (SSE) |
| `POST` | `/api/conversations/<id>/interrupt` | Interrupt active generation |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | Manually trigger verification for a message |
| `DELETE` | `/api/conversations/<id>` | Delete a conversation |
| `POST` | `/api/documents/upload` | Upload a document to the knowledge base |
| `GET` | `/api/documents` | List knowledge base documents |
| `DELETE` | `/api/documents/<id>` | Delete a knowledge base document |
| `POST` | `/api/documents/search` | Search the knowledge base |

#### Chat SSE Event Types

`/api/conversations/<id>/chat` emits the following event types over SSE:

| Event Field | Description |
|-------------|-------------|
| `token` | Incremental text fragment |
| `done` | Response complete, with `content` and `message_id` |
| `verifying` | Verification started (when verify toggle is on) |
| `verified` | Verification complete, with `is_correct`, `confidence`, `explanation`, `issues` |
| `error` | Error message |
