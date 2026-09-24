# Flask Chat

---

## 中文

### 项目简介

Flask Chat 是一个基于 Flask 构建的 AI 智能对话应用，支持多用户认证、多模型切换、WebSocket 流式输出、工具调用、上下文压缩与长期记忆、RAG（检索增强生成）知识库系统、代码库索引管理、对话模板、Agent 工作流、语音输入、Webhook 集成、LangSmith 全链路监控、AI 回答结果验证。数据存储在 PostgreSQL（含 pgvector 向量扩展）中，前端采用原生 JavaScript 单页应用。

### 功能特性

- **多用户支持** — JWT 认证（注册/登录/登出），用户数据隔离（对话、知识库、代码库按用户隔离），管理员权限分级
- **对话模板** — 预设模板（代码审查、知识库问答、技术架构师、SQL 分析师、学习导师），新建对话时选择模板自动应用 system_prompt
- **Agent 工作流** — 多步骤推理与工具链调用，支持任务分解、自动规划、执行步骤可视化展示
- **语音输入** — 基于浏览器 Web Speech API 的语音识别，支持中文，录音状态实时反馈
- **Webhook 集成** — 出站回调（对话完成后触发通知）和入站 API（外部系统触发对话）-> 还未实现
- **多模型切换** — 支持配置多个大语言模型，用户可在对话中自由切换；兼容 OpenAI API 协议的任意服务（包括 Ollama 本地模型）
- **WebSocket 流式输出** — 基于 Flask-SocketIO + eventlet 实现实时双向通信，逐字流式响应
- **流式打断** — 支持在 AI 回复过程中随时打断生成
- **工具调用** — 支持 Function Calling，内置获取时间、数学计算、代码执行、知识库检索、代码库检索等工具
- **工具开关控制** — 知识库查询和代码库查询工具可通过页面顶部开关实时启用/禁用，无需重启服务
- **RAG 知识检索** — 上传文档后，AI 可通过工具调用自动检索知识库回答问题；支持 BM25 + 向量混合检索（BM25 索引缓存，避免重复构建）、多查询重写、结果重排序
- **代码库索引管理** — 通过 Web UI 管理代码仓库配置（名称 + 本地路径），支持全量构建与增量构建（混合方案：文件修改时间 + SHA256 哈希双重过滤），构建过程 WebSocket 实时进度推送，支持取消任务；AI 在对话中通过 `search_code` 工具自动检索相关代码片段
- **本地模型支持** — 通过 Ollama 可直接使用本地部署的大语言模型和 Embedding 模型，无需任何云服务；Embedding 也可接入第三方服务
- **多轮记忆与上下文压缩** — 结构化摘要 + 长期记忆，跨轮次保留关键信息；对话过长时自动压缩历史消息，节省 Token 用量
- **结果验证（Result Verification）** — 可选开关，开启后由另一个 Agent 对 AI 回答进行事实、逻辑、完整性与清晰度的多维度验证
- **协作与分享** — 一键生成分享链接（`/share/<token>` 公开查看页）、对话导出（Markdown / JSON / TXT）
- **消息分页** — 支持游标分页加载历史消息，避免长对话一次性加载所有消息
- **响应缓存** — 支持内存缓存和 Redis 缓存双模式，相同问题 + 相同上下文命中缓存时直接返回
- **错误恢复** — 自动重试（指数退避）、主模型失败降级到备用模型、健康检查接口
- **交互体验** — Markdown 渲染（含代码高亮、一键复制）、消息点赞/点踩反馈、中文输入法兼容（IME composing 检测）
- **LangSmith 监控** — 通过 LangSmith 实现 LLM 调用、RAG 检索、上下文构建等关键流程的全链路可观测
- **结构化日志** — 支持 JSON 格式和人类可读格式，请求级追踪（request_id）
- **安全防护** — 可选 API Key 鉴权、JWT 认证、Prompt Injection 输入过滤、审计日志、用户级数据隔离
- **Docker 容器化** — 提供 Dockerfile 和 docker-compose.yml，支持一键容器化部署

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask |
| 实时通信 | Flask-SocketIO + eventlet（WebSocket） |
| ORM | Flask-SQLAlchemy |
| 数据库 | PostgreSQL + pgvector |
| 认证 | PyJWT（JWT Token） |
| 缓存 | 内存缓存 / Redis（双模式，可切换） |
| LLM 接口 | OpenAI SDK（兼容任意 OpenAI 协议的服务） |
| Embedding 模型 | Ollama（qwen3-embedding:8b）或第三方 Embedding 服务 |
| 向量检索 | pgvector（余弦相似度 + BM25 混合检索） |
| 代码索引构建 | LlamaIndex + CodeSplitter（tree-sitter）+ PGVectorStore |
| 文件解析 | pypdf、python-docx |
| 可观测性 | LangSmith（`@traceable` 装饰器 + 环境变量） |
| 安全 | JWT 认证、API Key 认证、Prompt Injection 过滤、用户级数据隔离 |
| 代码索引查询 | psycopg2（直连 pgvector 索引） |
| 容器化 | Docker + docker-compose |
| 前端 | 原生 HTML / CSS / JavaScript（IIFE + marked.js 渲染 Markdown） |

### 项目结构

```
flask_chat/
├── run.py                             # 启动入口（eventlet.monkey_patch）
├── requirements.txt                   # Python 依赖
├── .env.example                       # 环境变量模板
├── Dockerfile                         # Docker 镜像构建
├── docker-compose.yml                 # Docker Compose 编排
├── tests/                             # 单元测试 & 集成测试
│   ├── conftest.py                    # pytest 配置和 fixtures
│   ├── test_utils.py                  # 工具函数测试
│   ├── test_models.py                 # 数据模型测试
│   └── test_chat_api.py              # API 集成测试
├── scripts/
│   └── diagnose_index.py             # 索引诊断脚本
└── app/
    ├── __init__.py                    # 应用工厂（create_app + 蓝图注册 + 扩展初始化）
    ├── config.py                      # 配置类
    ├── errors.py                      # 统一错误处理（APIError 基类 + 全局处理器）
    ├── extensions.py                  # Flask 扩展（SQLAlchemy）
    ├── logging_config.py              # 结构化日志配置
    ├── middleware.py                  # 中间件（免责声明等）
    ├── models.py                      # 数据模型（User, Conversation, Message 等）
    ├── monitoring.py                  # 性能监控（请求耗时、指标收集）
    ├── utils.py                       # 共享工具函数（token 估算等）
    ├── websocket.py                   # WebSocket 事件处理器（实时通信核心 + 用户追踪）
    ├── routes/
    │   ├── auth.py                    # 认证路由（注册/登录/登出/验证）
    │   ├── chat.py                    # 对话、验证、分享、导出、反馈、页面路由
    │   ├── rag.py                     # RAG 知识库路由
    │   ├── code_index.py             # 代码库索引管理 API
    │   ├── template.py               # 对话模板管理 API
    │   ├── agent.py                   # Agent 工作流 API
    │   ├── webhook.py                 # Webhook 管理 API
    │   └── speech.py                  # 语音 I/O API
    ├── services/
    │   ├── ai_service.py             # AI 服务（流式输出 + 工具调用循环 + 模型降级）
    │   ├── auth_service.py           # JWT 认证服务（Token 生成/验证/登录/注册）
    │   ├── context_service.py        # 上下文管理（窗口裁剪 + 压缩 + 长期记忆 + system_prompt）
    │   ├── rag_service.py            # RAG 服务（解析/分块/嵌入/存储/混合检索/BM25缓存）
    │   ├── verifier_service.py       # 结果验证服务（独立 Agent 验证）
    │   ├── tool_service.py           # 工具定义与执行（用户权限传递）
    │   ├── cache_service.py          # 响应缓存（内存/Redis 双模式）
    │   ├── retry_service.py          # 重试与降级（指数退避 + fallback）
    │   ├── security_service.py       # 安全（API Key 认证 / 注入过滤 / 审计日志）
    │   ├── code_index_service.py     # 代码索引查询服务（pgvector 向量搜索 + 用户隔离）
    │   ├── code_index_builder.py     # 代码索引构建服务（LlamaIndex + 全量/增量 + 混合摘要）
    │   ├── template_service.py       # 对话模板 CRUD + 默认模板初始化
    │   ├── agent_service.py          # Agent 工作流（多步骤推理 + 工具链调用）
    │   ├── webhook_service.py        # Webhook 服务（出站回调 + 入站触发）
    │   └── speech_service.py         # 语音服务（STT/TTS，OpenAI Whisper + Edge TTS）
    ├── static/
    │   ├── css/style.css
    │   └── js/
    │       ├── chat.js               # 主对话页交互逻辑（IIFE，含 Agent/语音/模板选择）
    │       ├── knowledge.js          # 知识库管理页独立逻辑
    │       ├── code_repos.js         # 代码库管理页独立逻辑
    │       ├── marked.min.js         # Markdown 渲染（本地）
    │       └── socket.io.min.js      # Socket.IO 客户端（本地）
    └── templates/
        ├── login.html                # 登录/注册页
        ├── index.html                # 主对话页
        ├── knowledge.html            # 知识库管理页
        ├── code_repos.html           # 代码库管理页
        └── shared.html               # 分享对话查看页
```

### 数据模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `User` | `users` | 用户（用户名、邮箱、密码哈希、is_admin、last_login） |
| `Conversation` | `conversations` | 对话（含 `user_id`、`summary` 摘要、`memory` 长期记忆、`system_prompt` 模板提示词） |
| `Message` | `messages` | 消息（含 `tool_calls`、`verification`、`token_count`、`feedback`、`image_urls`、`status` 等） |
| `Document` | `documents` | 知识库文档（含 `user_id` 用户隔离） |
| `DocumentChunk` | `document_chunks` | 文档分块（含向量 `embedding`） |
| `SharedConversation` | `shared_conversations` | 分享链接 |
| `ConversationTemplate` | `conversation_templates` | 对话模板（名称、描述、system_prompt、分类） |
| `AuditLog` | `audit_logs` | 审计日志 |
| `CodeRepository` | `code_repositories` | 代码仓库配置（含 `user_id` 用户隔离，名称、路径、索引状态、进度等） |
| `IndexedFile` | `indexed_files` | 文件索引记录（路径、SHA256 哈希、修改时间，用于增量索引） |

### 环境要求

- Python 3.10+
- PostgreSQL 15+（需安装 pgvector 扩展）
- Ollama（用于本地 Embedding 模型，也可选用于本地大语言模型）
- Redis（可选，生产环境缓存加速）
- Docker & Docker Compose（可选，容器化部署）

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
| `FLASK_SECRET_KEY` | Flask 密钥（JWT 签名也使用此密钥） | `dev-secret` |
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
| `CODE_EXEC_ENABLED` | 是否启用代码执行工具 | `true` |
| `KNOWLEDGE_SEARCH_ENABLED` | 是否启用知识库检索工具（可在页面切换） | `false` |
| `API_KEY` | API 鉴权密钥（留空则跳过鉴权） | 空 |
| `INPUT_FILTER_ENABLED` | 是否启用 Prompt Injection 输入过滤 | `true` |
| **缓存配置** | | |
| `CACHE_ENABLED` | 是否启用响应缓存 | `true` |
| `CACHE_TTL_HOURS` | 缓存有效期（小时） | `1` |
| `CACHE_MAX_SIZE` | 内存缓存最大条目数 | `1000` |
| `REDIS_ENABLED` | 是否启用 Redis 缓存（`false` 时使用内存缓存） | `false` |
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` |
| **日志配置** | | |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_FORMAT` | 日志格式（`human` 人类可读 / `json` 结构化） | `human` |
| **重试与降级** | | |
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `RETRY_DELAY_SECONDS` | 重试间隔（秒） | `2` |
| `FALLBACK_MODEL` | 备用模型（主模型失败时降级） | 空 |
| `VERIFY_ENABLED` | 是否启用结果验证 | `false` |
| `VERIFY_MODEL` | 验证 Agent 使用的模型（留空则与主模型一致） | 空 |
| `AI_DISCLAIMER_TEXT` | AI 免责声明文字（留空则不追加） | 空 |
| `LANGCHAIN_TRACING_V2` | 是否启用 LangSmith 追踪 | `false` |
| `LANGCHAIN_PROJECT` | LangSmith 项目名 | `flask_chat` |
| `LANGCHAIN_API_KEY` | LangSmith API Key | - |
| `LANGCHAIN_ENDPOINT` | LangSmith 服务端点 | `https://api.smith.langchain.com` |
| **代码索引配置** | | |
| `CODE_INDEX_ENABLED` | 是否启用代码索引功能 | `false` |
| `CODE_INDEX_DB_HOST` | 代码索引数据库主机 | `localhost` |
| `CODE_INDEX_DB_PORT` | 代码索引数据库端口 | `5432` |
| `CODE_INDEX_DB_USER` | 代码索引数据库用户 | `postgres` |
| `CODE_INDEX_DB_PASSWORD` | 代码索引数据库密码 | - |
| `CODE_INDEX_DB_NAME` | 代码索引数据库名称 | `flask_chat` |
| `CODE_INDEX_TOP_K` | 代码搜索返回结果数量 | `5` |
| **索引构建配置** | | |
| `CODE_INDEX_CHUNK_LINES` | 代码分块行数 | `100` |
| `CODE_INDEX_CHUNK_LINES_OVERLAP` | 代码分块重叠行数 | `10` |
| `CODE_INDEX_MAX_CHARS` | 代码分块最大字符数 | `1500` |
| `CODE_INDEX_SUPPORTED_EXTS` | 支持索引的文件扩展名 | `.py,.js,.ts,.tsx,...` |
| `CODE_INDEX_EXCLUDE_PATTERNS` | 排除的目录/文件名模式 | `.git,__pycache__,...` |

**5. 数据库初始化**

首次启动时 `db.create_all()` 会自动创建所有表，无需手动建表。

**6. 数据库迁移**

当 `models.py` 中的模型发生变化（新增字段、新表等），已有数据库不会自动更新，需要手动执行迁移脚本。本项目采用**手写 SQL 脚本**的方式进行迁移（脚本统一放在 `migrations/` 目录，按日期命名）。

**执行迁移脚本：**

```bash
psql -U <username> -d flask_chat -f migrations/<迁移脚本>.sql
```

**新增迁移脚本的约定：**

1. 修改 `app/models.py`，添加新字段或新表
2. 在 `migrations/` 目录新建脚本，命名格式 `YYYY-MM-DD_描述.sql`
3. 脚本内容使用 `IF NOT EXISTS`，保证可重复执行
4. 按日期顺序依次执行新脚本

**7. 启动应用**

```bash
python run.py
```

> `run.py` 在入口处自动执行 `eventlet.monkey_patch()`，确保 WebSocket 正常工作。

访问 `http://localhost:8080` 即可使用。首次访问会跳转到登录页面，注册账户后即可使用。

### Docker 部署

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 停止
docker-compose down
```

### 缓存配置

系统支持两种缓存后端，通过 `REDIS_ENABLED` 环境变量切换：

| 模式 | 配置 | 适用场景 |
|------|------|----------|
| 内存缓存 | `REDIS_ENABLED=false` | 开发/测试环境，单进程部署 |
| Redis 缓存 | `REDIS_ENABLED=true` | 生产环境，多进程/多实例部署 |

Redis 模式下，缓存在多个 worker 进程间共享，重启不丢失。

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
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama                # Ollama 不校验 key，但 SDK 要求非空
OPENAI_MODEL=qwen2.5:7b              # 默认模型（必须带 tag 如 :7b）
AVAILABLE_MODELS=qwen2.5:7b,qwen2.5:14b,llama3.1:8b
```

3. （可选）关闭外部服务，实现完全离线：

```bash
LANGCHAIN_TRACING_V2=false
```

4. 重启 Flask 应用即可。

**常见问题：**

- **首次对话卡顿**：Ollama 首次加载模型到显存/内存需 10–30 秒，后续请求正常。可用 `ollama run <model> "hi"` 提前预热。
- **模型 tag 必须精确**：`AVAILABLE_MODELS` 中要写完整 tag（如 `qwen2.5:7b`），不能只写 `qwen2.5`。
- **Embedding 模型切换**：如果更换 Embedding 模型（如从 `qwen3-embedding:8b` 换到 `nomic-embed-text`），需同步更新 `EMBEDDING_DIM`（前者 4096，后者 768），并重建 `document_chunks` 表。
- **混合模式**：可以同时配置云端 LLM（如 OpenAI）和本地 Ollama，通过 `AVAILABLE_MODELS` 列出多个模型，在前端下拉框自由切换。

### 使用第三方 Embedding 服务

Embedding 与大语言模型相互独立，可分别配置。若 Embedding 使用第三方服务（而非 Ollama），只需调整 `.env`：

```bash
EMBEDDING_BASE_URL=https://api.example.com/v1
EMBEDDING_API_KEY=your-real-api-key
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIM=3072
```

### 多用户与权限隔离

系统支持多用户注册/登录，所有用户数据通过 JWT 认证，数据按用户隔离：

- **对话隔离**：每个用户只能看到和操作自己的对话
- **知识库隔离**：每个用户只能搜索到自己上传的文档
- **代码库隔离**：每个用户只能搜索到自己导入的代码仓库
- **向后兼容**：已有数据（`user_id` 为空）对所有用户可见，可绑定到管理员账户

权限控制贯穿完整调用链：WebSocket 连接 → AI 服务 → 工具执行 → 搜索服务，确保 B 用户无法访问 A 用户的知识库和代码库数据。

### 代码库索引管理

代码库索引管理功能允许用户通过 Web UI 配置本地代码仓库，并构建向量索引。AI 在对话中通过 `search_code` 工具自动检索相关代码片段。

**页面入口：**

- **主页面**（`/`）：侧边栏显示知识库和代码库的数量徽章及导航链接
- **代码库管理页**（`/code-repos`）：独立的代码库管理页面
- **知识库管理页**（`/knowledge`）：独立的知识库管理页面

**支持的功能：**

- 添加/删除代码仓库配置（仓库名称 + 本地路径）
- 全量构建索引（清空重建）
- 增量构建索引（混合方案：文件修改时间初筛 + SHA256 哈希验证，只索引新增/修改的文件，自动清理已删除文件的索引）
- 构建过程 WebSocket 实时进度推送（索引状态实时更新，页面切换后返回可查看当前进度）
- 取消正在进行的索引任务
- 搜索测试
- 敏感内容自动过滤（API Key、密码、Token 等）
- **混合摘要方案**：代码文件使用零 token 的结构化元数据提取（函数签名、类定义、导入声明），非代码文件使用 LLM 摘要
- **跨仓库搜索**：支持同时搜索多个已索引仓库，按相关度排序返回结果
- **用户隔离**：工具描述中动态列出当前用户有权限的仓库，搜索时按用户过滤

**索引原理：**

- 使用 LlamaIndex 的 `CodeSplitter`（基于 tree-sitter）进行语法感知的代码分割
- 使用 `OllamaEmbedding`（qwen3-embedding:8b，4096 维）生成代码向量
- 存储到 PostgreSQL 的 `data_code_summaries_{repo_name}`（摘要层）和 `data_code_chunks_{repo_name}`（代码块层）表
- 增量索引时，通过 `indexed_files` 表记录每个文件的路径和哈希值，对比变化后只处理差异文件

**搜索时的仓库选择逻辑：**

- 指定了仓库名：校验用户权限后直接搜索该仓库
- 未指定仓库名：自动搜索当前用户有权限的所有已索引仓库，按相关度排序返回结果
- 工具描述中动态列出当前用户可选的仓库名称，引导 LLM 正确选择目标仓库

### 使用说明

- **登录/注册** — 首次访问自动跳转到登录页面，注册账户后进入主页面
- **对话** — 在输入框输入消息，按 Enter 发送，Shift+Enter 换行
- **新建对话** — 点击左侧「+ 新对话」，选择对话模板（或空白对话），输入标题后创建
- **重命名对话** — 鼠标悬停在左侧某条对话上，点击出现的编辑按钮（✎）即可原地重命名
- **切换模型** — 在顶部下拉框选择不同的大语言模型
- **打断生成** — AI 回复时点击「打断」按钮停止生成
- **Agent 模式** — 点击「Agent」按钮开启多步骤推理模式，Agent 会自动规划、调用工具、展示执行步骤
- **语音输入** — 点击麦克风按钮开始录音，识别结果自动填入输入框（需浏览器支持 Web Speech API）
- **知识库管理** — 侧边栏点击「知识库管理」进入独立页面，支持上传文档（`.txt`、`.md`、`.pdf`、`.docx`）、删除文档、查看统计信息
- **代码库管理** — 侧边栏点击「代码库管理」进入独立页面，支持添加代码仓库、全量/增量构建索引、查看进度、取消任务、搜索测试、删除仓库
- **结果验证** — 顶部打开「结果验证」开关后，AI 回答完成后会自动触发验证
- **分享对话** — 点击顶部「分享」按钮生成公开链接
- **导出对话** — 点击顶部「导出」按钮，选择 Markdown / JSON / TXT 格式下载
- **反馈** — 点击消息下方的 👍 / 👎 对回答进行评价
- **登出** — 点击顶部「退出」按钮清除登录状态

### 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_utils.py
pytest tests/test_models.py
pytest tests/test_chat_api.py

# 查看详细输出
pytest tests/ -v -s
```

### API 接口

#### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/register` | 注册（`{"username": "...", "email": "...", "password": "..."}` ） |
| `POST` | `/api/auth/login` | 登录（`{"username": "...", "password": "..."}` ），返回 JWT Token |
| `GET` | `/api/auth/me` | 获取当前用户信息（需 Bearer Token） |
| `GET` | `/api/auth/verify` | 验证 Token 有效性 |

#### 对话与管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页（需登录） |
| `GET` | `/knowledge` | 知识库管理页 |
| `GET` | `/code-repos` | 代码库管理页 |
| `GET` | `/login` | 登录/注册页 |
| `GET` | `/api/models` | 获取可用模型列表 |
| `GET` | `/api/conversations` | 获取当前用户的对话列表 |
| `POST` | `/api/conversations` | 创建新对话（可选 `{"title": "...", "template_id": 1}`） |
| `PATCH` | `/api/conversations/<id>` | 重命名对话（请求体：`{"title": "..."}`） |
| `GET` | `/api/conversations/<id>/messages` | 获取对话消息（支持分页 `?limit=50&before=<msg_id>`） |
| `DELETE` | `/api/conversations/<id>` | 删除对话 |
| `GET` | `/api/conversations/<id>/stats` | 获取对话 Token 统计 |

#### 对话模板

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/templates` | 获取所有对话模板 |
| `GET` | `/api/templates/<id>` | 获取单个模板 |
| `POST` | `/api/templates` | 创建模板 |
| `PUT` | `/api/templates/<id>` | 更新模板 |
| `DELETE` | `/api/templates/<id>` | 删除模板 |

#### Agent 工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/agent/run` | 执行 Agent 任务（`{"task": "...", "conversation_id": 1}`） |
| `POST` | `/api/agent/save-response` | 保存 Agent 回复到数据库 |
| `POST` | `/api/agent/plan` | 任务分解（`{"task": "..."}`) |

#### 语音 I/O

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/speech/stt` | 语音转文字（上传音频文件） |
| `POST` | `/api/speech/tts` | 文字转语音 |
| `GET` | `/api/speech/voices` | 获取可用语音列表 |

#### Webhook

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/webhooks` | 获取所有 Webhook 配置 |
| `POST` | `/api/webhooks` | 注册 Webhook |
| `DELETE` | `/api/webhooks/<id>` | 删除 Webhook |
| `POST` | `/api/webhooks/trigger` | 入站触发对话 |

#### 结果验证

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config/verify` | 获取结果验证配置 |
| `POST` | `/api/config/verify` | 更新结果验证开关 |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | 手动触发验证 |

#### 工具配置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config/tools` | 获取工具开关状态 |
| `POST` | `/api/config/tools` | 更新工具开关 |

#### 分享与导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/conversations/<id>/share` | 生成分享链接 |
| `GET` | `/share/<token>` | 查看分享的对话（公开只读页） |
| `GET` | `/api/conversations/<id>/export` | 导出对话（`?format=markdown/json/txt`） |

#### 知识库（RAG）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/documents/upload` | 上传文档到知识库 |
| `GET` | `/api/documents` | 获取知识库文档列表 |
| `DELETE` | `/api/documents/<id>` | 删除知识库文档 |
| `POST` | `/api/documents/search` | 搜索知识库 |

#### 代码库索引管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/code-repos` | 获取当前用户的代码仓库列表 |
| `POST` | `/api/code-repos` | 创建代码仓库配置 |
| `GET` | `/api/code-repos/<id>` | 获取单个仓库配置 |
| `DELETE` | `/api/code-repos/<id>` | 删除仓库配置及其索引 |
| `POST` | `/api/code-repos/<id>/index` | 触发索引构建 |
| `GET` | `/api/code-repos/<id>/progress` | 获取索引构建进度 |
| `POST` | `/api/code-repos/<id>/cancel` | 取消正在进行的索引任务 |
| `GET` | `/api/code-repos/<id>/status` | 获取仓库索引状态 |
| `GET` | `/api/code-repos/<id>/stats` | 获取索引统计信息 |

#### 图片上传与反馈

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/upload/image` | 上传图片（多模态） |
| `POST` | `/api/messages/<msg_id>/feedback` | 提交消息反馈 |

#### 系统与运维

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查（数据库/缓存状态） |
| `POST` | `/api/cache/clear` | 清空响应缓存 |
| `GET` | `/api/audit-logs` | 获取审计日志 |
| `GET` | `/api/config/disclaimer` | 获取免责声明配置 |
| `POST` | `/api/config/disclaimer` | 更新免责声明配置 |

#### WebSocket 事件

聊天消息通过 WebSocket（Socket.IO）实时通信：

| 事件 | 方向 | 说明 |
|------|------|------|
| `connect` | → 服务端 | 连接（可传 `auth.token` 进行 JWT 认证） |
| `chat_message` | → 服务端 | 发送消息（`conversation_id`, `content`, `model`） |
| `token` | ← 客户端 | 接收增量文本片段 |
| `tool_calls` | ← 客户端 | 接收工具调用记录 |
| `generation_completed` | ← 客户端 | AI 回复完成 |
| `generation_error` | ← 客户端 | 生成失败 |
| `stop_generation` | → 服务端 | 打断生成 |
| `join` | → 服务端 | 加入对话房间 |
| `leave` | → 服务端 | 离开对话房间 |
| `index_progress` | ← 客户端 | 接收代码索引构建进度 |

---

## English

### Introduction

Flask Chat is an AI-powered chat application built with Flask. It supports multi-user authentication, multi-model switching, WebSocket streaming responses, tool calling, context compression with long-term memory, a RAG (Retrieval-Augmented Generation) knowledge base, code repository index management, conversation templates, Agent workflow, voice input, Webhook integration, LangSmith observability, and AI answer verification. Data is stored in PostgreSQL (with the pgvector extension), and the frontend is a vanilla JavaScript single-page application.

### Features

- **Multi-User Support** — JWT authentication (register/login/logout), user data isolation (conversations, knowledge base, code repos), admin privileges
- **Conversation Templates** — Preset templates with system_prompt (code review, knowledge Q&A, tech architect, SQL analyst, learning tutor)
- **Agent Workflow** — Multi-step reasoning with tool chaining, task decomposition, execution step visualization
- **Voice Input** — Browser-native Web Speech API for speech recognition, Chinese language support
- **Webhook Integration** — Outbound callbacks (conversation completed) and inbound API (external triggers)
- **Multi-Model Support** — Configure multiple LLMs and switch between them; compatible with any OpenAI-protocol service (including Ollama local models)
- **WebSocket Streaming** — Real-time bidirectional communication via Flask-SocketIO + eventlet, token-by-token streaming
- **Tool Calling** — Function Calling with built-in tools: time, math, code execution, knowledge-base search, code search with user-level isolation
- **RAG Knowledge Base** — Upload documents, AI auto-searches knowledge base; supports BM25 + vector hybrid search, multi-query rewriting, result reranking
- **Code Index Management** — Manage code repositories via Web UI, full and incremental indexing with WebSocket real-time progress, cross-repository search with user isolation
- **Local Model Support** — Run both LLM and Embedding models locally via Ollama
- **Multi-turn Memory & Context Compression** — Structured summarization + long-term memory across turns
- **Result Verification** — Optional toggle that runs a second agent to validate AI answers
- **Response Cache** — Dual-mode caching: in-memory (development) or Redis (production)
- **Error Recovery** — Automatic retry with exponential backoff, fallback to a backup model
- **Docker Containerization** — Dockerfile and docker-compose.yml for one-command deployment
- **Security** — JWT auth, API key auth, Prompt Injection filtering, audit logging, user-level data isolation

### Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask |
| Real-time | Flask-SocketIO + eventlet (WebSocket) |
| ORM | Flask-SQLAlchemy |
| Database | PostgreSQL + pgvector |
| Auth | PyJWT (JWT Token) |
| Cache | In-memory / Redis (dual-mode, switchable) |
| LLM Interface | OpenAI SDK (compatible with any OpenAI-protocol service) |
| Embedding Model | Ollama (qwen3-embedding:8b) or third-party embedding service |
| Vector Search | pgvector (cosine similarity + BM25 hybrid search) |
| Code Index Builder | LlamaIndex + CodeSplitter (tree-sitter) + PGVectorStore |
| File Parsing | pypdf, python-docx |
| Observability | LangSmith (`@traceable` decorator + env vars) |
| Security | JWT auth, API key auth, Prompt Injection filtering, user-level isolation |
| Containerization | Docker + docker-compose |
| Frontend | Vanilla HTML / CSS / JavaScript (IIFE + marked.js) |

### Quick Start

```bash
git clone <repo-url>
cd flask_chat
pip install -r requirements.txt
cp .env.example .env    # Edit as needed
python run.py           # Visit http://localhost:8080
```

Or with Docker:

```bash
docker-compose up -d
```

See the Chinese section above for full configuration details.

### Testing

```bash
pytest tests/ -v
```

### WebSocket Events

Chat messages use WebSocket (Socket.IO) for real-time communication. See the Chinese section for the full event table.
