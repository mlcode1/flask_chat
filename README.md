# Flask Chat

---

## 中文

### 项目简介

Flask Chat 是一个基于 Flask 构建的 AI 智能对话应用，支持多模型切换、WebSocket 流式输出、工具调用、上下文压缩与长期记忆、RAG（检索增强生成）知识库系统、LangSmith 全链路监控、AI 回答结果验证以及**代码库索引管理**。数据存储在 PostgreSQL（含 pgvector 向量扩展）中，前端采用原生 JavaScript 单页应用。

### 功能特性

- **多模型切换** — 支持配置多个大语言模型，用户可在对话中自由切换；兼容 OpenAI API 协议的任意服务（包括 Ollama 本地模型）
- **WebSocket 流式输出** — 基于 Flask-SocketIO + eventlet 实现实时双向通信，逐字流式响应
- **流式打断** — 支持在 AI 回复过程中随时打断生成
- **工具调用** — 支持 Function Calling，内置获取时间、数学计算、代码执行、数据库查询、文件读取、知识库检索等工具
- **工具开关控制** — 知识库查询和代码库查询工具可通过页面顶部开关实时启用/禁用，无需重启服务
- **RAG 知识检索** — 上传文档后，AI 可通过工具调用自动检索知识库回答问题；支持 BM25 + 向量混合检索（BM25 索引缓存，避免重复构建）、多查询重写、结果重排序
- **代码库索引管理** — 通过 Web UI 管理代码仓库配置（名称 + 本地路径），支持全量构建与增量构建（混合方案：文件修改时间 + SHA256 哈希双重过滤），构建过程实时进度条，支持取消任务；AI 在对话中通过 `search_code` 工具自动检索相关代码片段，自动选择已索引仓库
- **本地模型支持** — 通过 Ollama 可直接使用本地部署的大语言模型和 Embedding 模型，无需任何云服务；Embedding 也可接入第三方服务
- **多轮记忆与上下文压缩** — 结构化摘要 + 长期记忆，跨轮次保留关键信息；对话过长时自动压缩历史消息，节省 Token 用量
- **结果验证（Result Verification）** — 可选开关，开启后由另一个 Agent 对 AI 回答进行事实、逻辑、完整性与清晰度的多维度验证，支持自动验证与手动验证
- **对话命名与重命名** — 新建对话时弹窗输入标题（留空则默认）；侧边栏对话项点击编辑按钮（✎）即可随时重命名
- **协作与分享** — 一键生成分享链接（`/share/<token>` 公开查看页）、对话导出（Markdown / JSON / TXT）
- **消息分页** — 支持游标分页加载历史消息，避免长对话一次性加载所有消息
- **响应缓存** — 支持内存缓存和 Redis 缓存双模式，相同问题 + 相同上下文命中缓存时直接返回
- **错误恢复** — 自动重试（指数退避）、主模型失败降级到备用模型、健康检查接口
- **交互体验** — Markdown 渲染（含代码高亮、一键复制）、消息点赞/点踩反馈
- **可视化与调试** — Token 统计面板 + 工具调用可视化，调试面板展示系统/缓存/模型状态
- **LangSmith 监控** — 通过 LangSmith 实现 LLM 调用、RAG 检索、上下文构建等关键流程的全链路可观测
- **统一错误处理** — 基于 APIError 基类的统一异常体系，全局错误处理器保证一致的响应格式
- **结构化日志** — 支持 JSON 格式和人类可读格式，请求级追踪（request_id）
- **性能监控** — 内置请求耗时、模型调用、工具执行等关键指标的监控
- **安全防护** — 可选 API Key 鉴权、Prompt Injection 输入过滤、审计日志、数据库查询表级访问控制
- **Docker 容器化** — 提供 Dockerfile 和 docker-compose.yml，支持一键容器化部署

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask |
| 实时通信 | Flask-SocketIO + eventlet（WebSocket） |
| ORM | Flask-SQLAlchemy |
| 数据库 | PostgreSQL + pgvector |
| 缓存 | 内存缓存 / Redis（双模式，可切换） |
| LLM 接口 | OpenAI SDK（兼容任意 OpenAI 协议的服务） |
| Embedding 模型 | Ollama（qwen3-embedding:8b）或第三方 Embedding 服务 |
| 向量检索 | pgvector（余弦相似度 + BM25 混合检索） |
| 代码索引构建 | LlamaIndex + CodeSplitter（tree-sitter）+ PGVectorStore |
| 文件解析 | pypdf、python-docx |
| 可观测性 | LangSmith（`@traceable` 装饰器 + 环境变量） |
| 安全 | API Key 认证、Prompt Injection 过滤、输入校验、审计日志 |
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
├── docs/
│   └── api.md                         # API 文档
├── tests/                             # 单元测试 & 集成测试
│   ├── conftest.py                    # pytest 配置和 fixtures
│   ├── test_utils.py                  # 工具函数测试
│   ├── test_models.py                 # 数据模型测试
│   └── test_chat_api.py              # API 集成测试
├── scripts/
│   └── diagnose_index.py             # 索引诊断脚本
├── migrations/                        # 数据库迁移脚本（按日期命名）
│   ├── 2026-09-11_add_advanced_features.sql
│   ├── 2026-09-11_add_memory_fields.sql
│   ├── 2026-09-11_add_feedback_field.sql
│   ├── 2026-09-17_add_code_repositories.sql
│   ├── 2026-09-17_add_progress_fields.sql
│   └── 2026-09-18_incremental_index.sql
└── app/
    ├── __init__.py                    # 应用工厂（create_app + 启动清理 + 扩展初始化）
    ├── config.py                      # 配置类
    ├── errors.py                      # 统一错误处理（APIError 基类 + 全局处理器）
    ├── extensions.py                  # Flask 扩展（SQLAlchemy）
    ├── logging_config.py              # 结构化日志配置
    ├── middleware.py                  # 中间件（免责声明等）
    ├── models.py                      # 数据模型
    ├── monitoring.py                  # 性能监控（请求耗时、指标收集）
    ├── utils.py                       # 共享工具函数（token 估算等）
    ├── websocket.py                   # WebSocket 事件处理器（实时通信核心）
    ├── routes/
    │   ├── chat.py                    # 对话、验证、分享、导出、反馈、审计、页面路由
    │   ├── rag.py                     # RAG 知识库路由
    │   └── code_index.py             # 代码库索引管理 API
    ├── services/
    │   ├── ai_service.py             # AI 服务（流式输出 + 工具调用循环 + 模型降级）
    │   ├── context_service.py        # 上下文管理（窗口裁剪 + 压缩 + 长期记忆）
    │   ├── rag_service.py            # RAG 服务（解析/分块/嵌入/存储/混合检索/BM25缓存）
    │   ├── verifier_service.py       # 结果验证服务（独立 Agent 验证）
    │   ├── tool_service.py           # 工具定义与执行（search_code、knowledge_search 等）
    │   ├── cache_service.py          # 响应缓存（内存/Redis 双模式）
    │   ├── retry_service.py          # 重试与降级（指数退避 + fallback）
    │   ├── security_service.py       # 安全（API Key 认证 / 注入过滤 / 审计日志）
    │   ├── code_index_service.py     # 代码索引查询服务（pgvector 向量搜索）
    │   └── code_index_builder.py     # 代码索引构建服务（LlamaIndex + 全量/增量 + 混合摘要）
    ├── static/
    │   ├── css/style.css
    │   └── js/
    │       ├── chat.js               # 主对话页交互逻辑（IIFE，~1666 行）
    │       ├── knowledge.js          # 知识库管理页独立逻辑
    │       ├── code_repos.js         # 代码库管理页独立逻辑
    │       ├── marked.min.js         # Markdown 渲染（本地）
    │       └── socket.io.min.js      # Socket.IO 客户端（本地）
    └── templates/
        ├── index.html                # 主对话页
        ├── knowledge.html            # 知识库管理页（独立）
        ├── code_repos.html           # 代码库管理页（独立）
        └── shared.html               # 分享对话查看页
```

### 数据模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `Conversation` | `conversations` | 对话（含 `summary` 摘要、`memory` 长期记忆） |
| `Message` | `messages` | 消息（含 `tool_calls`、`verification`、`token_count`、`feedback`、`image_urls`、`status` 等，复合索引 `conversation_id + created_at`） |
| `Document` | `documents` | 知识库文档 |
| `DocumentChunk` | `document_chunks` | 文档分块（含向量 `embedding`） |
| `SharedConversation` | `shared_conversations` | 分享链接 |
| `ConversationTemplate` | `conversation_templates` | 对话模板（预留） |
| `AuditLog` | `audit_logs` | 审计日志 |
| `CodeRepository` | `code_repositories` | 代码仓库配置（名称、路径、索引状态、进度、模式等） |
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
| `CODE_INDEX_DEFAULT_REPO` | 默认代码仓库名称（工具描述中提示 LLM） | `flask_chat` |
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

**执行已有迁移脚本：**

```bash
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_advanced_features.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_memory_fields.sql
psql -U <username> -d flask_chat -f migrations/2026-09-11_add_feedback_field.sql
psql -U <username> -d flask_chat -f migrations/2026-09-17_add_code_repositories.sql
psql -U <username> -d flask_chat -f migrations/2026-09-17_add_progress_fields.sql
psql -U <username> -d flask_chat -f migrations/2026-09-18_incremental_index.sql
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

访问 `http://localhost:8080` 即可使用。

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
- **跨仓库搜索**：支持同时搜索多个已索引仓库，按相关度排序返回结果；工具描述中动态列出所有可选仓库，引导 LLM 正确选择目标仓库
- **数据访问控制**：开关关闭时，不仅隐藏工具定义，还在数据库查询层面禁止访问相关表，防止通过 `query_database` 等替代路径绕过

**索引原理：**

- 使用 LlamaIndex 的 `CodeSplitter`（基于 tree-sitter）进行语法感知的代码分割
- 使用 `OllamaEmbedding`（qwen3-embedding:8b，4096 维）生成代码向量
- 存储到 PostgreSQL 的 `data_code_summaries_{repo_name}`（摘要层）和 `data_code_chunks_{repo_name}`（代码块层）表
- 增量索引时，通过 `indexed_files` 表记录每个文件的路径和哈希值，对比变化后只处理差异文件

**搜索时的仓库选择逻辑：**

- 指定了仓库名：直接搜索该仓库（LLM 从工具描述的可选列表中选择）
- 未指定仓库名：自动搜索所有已索引的仓库，按相关度排序返回结果
- 工具描述中动态列出所有已索引仓库名称，引导 LLM 正确选择目标仓库

### 使用说明

- **对话** — 在输入框输入消息，按 Enter 发送，Shift+Enter 换行
- **新建对话** — 点击左侧「+ 新对话」会弹出标题输入框，可直接命名（留空则用默认标题，发消息后由 AI 自动生成标题）
- **重命名对话** — 鼠标悬停在左侧某条对话上，点击出现的编辑按钮（✎）即可原地重命名
- **切换模型** — 在顶部下拉框选择不同的大语言模型
- **打断生成** — AI 回复时点击「打断」按钮停止生成
- **知识库管理** — 侧边栏点击「知识库管理」进入独立页面，支持上传文档（`.txt`、`.md`、`.pdf`、`.docx`）、删除文档、查看统计信息
- **代码库管理** — 侧边栏点击「代码库管理」进入独立页面，支持添加代码仓库、全量/增量构建索引、查看进度、取消任务、搜索测试、删除仓库
- **结果验证** — 顶部打开「结果验证」开关后，AI 回答完成后会自动触发验证；也可点击消息下方的「🔍 结果验证」按钮对历史回答手动验证
- **分享对话** — 点击顶部「分享」按钮生成公开链接，其他人可通过 `/share/<token>` 查看（只读）
- **导出对话** — 点击顶部「导出」按钮，选择 Markdown / JSON / TXT 格式下载
- **反馈** — 点击消息下方的 👍 / 👎 对回答进行评价
- **调试面板** — 点击右下角 🐛 按钮查看系统状态、缓存状态、可用模型与 Token 统计

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

#### 对话与管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 主页 |
| `GET` | `/knowledge` | 知识库管理页 |
| `GET` | `/code-repos` | 代码库管理页 |
| `GET` | `/api/models` | 获取可用模型列表 |
| `POST` | `/api/conversations` | 创建新对话（请求体可选 `{"title": "..."}`） |
| `PATCH` | `/api/conversations/<id>` | 重命名对话（请求体：`{"title": "..."}`） |
| `GET` | `/api/conversations/<id>/messages` | 获取对话消息（支持分页 `?limit=50&before=<msg_id>`） |
| `DELETE` | `/api/conversations/<id>` | 删除对话 |
| `GET` | `/api/conversations/<id>/stats` | 获取对话 Token 统计 |

#### 结果验证

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config/verify` | 获取结果验证配置 |
| `POST` | `/api/config/verify` | 更新结果验证开关（请求体：`{"enabled": true/false}`） |
| `POST` | `/api/conversations/<id>/messages/<mid>/verify` | 手动触发对某条回答的验证 |

#### 工具配置

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config/tools` | 获取工具开关状态（知识库查询、代码库查询） |
| `POST` | `/api/config/tools` | 更新工具开关（请求体：`{"knowledge_search": true/false, "code_index": true/false}`） |

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

#### 代码库索引管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/code-repos` | 获取所有代码仓库列表 |
| `POST` | `/api/code-repos` | 创建代码仓库配置（`{"name": "...", "path": "..."}`） |
| `GET` | `/api/code-repos/<id>` | 获取单个仓库配置 |
| `DELETE` | `/api/code-repos/<id>` | 删除仓库配置及其索引 |
| `POST` | `/api/code-repos/<id>/index` | 触发索引构建（异步，`{"mode": "full"/"incremental", "reindex": true}`） |
| `GET` | `/api/code-repos/<id>/progress` | 获取索引构建进度 |
| `POST` | `/api/code-repos/<id>/cancel` | 取消正在进行的索引任务 |
| `GET` | `/api/code-repos/<id>/status` | 获取仓库索引状态 |
| `GET` | `/api/code-repos/<id>/stats` | 获取索引统计信息 |

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

#### WebSocket 事件

聊天消息通过 WebSocket（Socket.IO）实时通信，客户端连接后通过以下事件交互：

| 事件 | 方向 | 说明 |
|------|------|------|
| `chat_message` | → 服务端 | 发送消息（`conversation_id`, `content`, `model`） |
| `token` | ← 客户端 | 接收增量文本片段 |
| `tool_calls` | ← 客户端 | 接收工具调用记录 |
| `generation_completed` | ← 客户端 | AI 回复完成 |
| `generation_error` | ← 客户端 | 生成失败 |
| `stop_generation` | → 服务端 | 打断生成 |
| `join` | → 服务端 | 加入对话房间 |
| `leave` | → 服务端 | 离开对话房间 |

详细 API 文档见 `docs/api.md`。

---

## English

### Introduction

Flask Chat is an AI-powered chat application built with Flask. It supports multi-model switching, WebSocket streaming responses, tool calling, context compression with long-term memory, a RAG (Retrieval-Augmented Generation) knowledge base, LangSmith observability, an optional AI answer verification feature, and **code repository index management**. Data is stored in PostgreSQL (with the pgvector extension), and the frontend is a vanilla JavaScript single-page application.

### Features

- **Multi-Model Support** — Configure multiple LLMs and switch between them during conversations; compatible with any OpenAI-protocol service (including Ollama local models)
- **WebSocket Streaming** — Real-time bidirectional communication via Flask-SocketIO + eventlet, token-by-token streaming responses
- **Stream Interruption** — Stop AI generation at any time
- **Tool Calling** — Function Calling with built-in tools: current time, math calculation, code execution, database query, file reading, knowledge-base search; `search_code` supports cross-repository search with dynamic repository listing
- **Tool Toggle Control** — Knowledge base search and code repository search tools can be enabled/disabled in real-time via header toggles
- **RAG Knowledge Base** — Upload documents and let the AI automatically search the knowledge base when answering questions; supports BM25 + vector hybrid search (with BM25 index caching), multi-query rewriting, and result reranking
- **Code Index Management** — Manage code repository configurations via Web UI, supports full and incremental indexing with real-time progress bar and task cancellation; hybrid summary approach (structural extraction for code files, LLM for non-code files)
- **Local Model Support** — Run both LLM and Embedding models locally via Ollama
- **Multi-turn Memory & Context Compression** — Structured summarization + long-term memory across turns
- **Result Verification** — Optional toggle that runs a second agent to validate every AI answer
- **Message Pagination** — Cursor-based pagination for loading historical messages
- **Response Cache** — Dual-mode caching: in-memory (development) or Redis (production)
- **Error Recovery** — Automatic retry with exponential backoff, fallback to a backup model
- **Unified Error Handling** — APIError base class with global error handlers for consistent response format
- **Structured Logging** — JSON and human-readable formats with request-level tracing
- **Performance Monitoring** — Built-in request timing, model call metrics, and tool execution tracking
- **Docker Containerization** — Dockerfile and docker-compose.yml for one-command deployment
- **Security** — Optional API key auth, Prompt Injection filtering, audit logging, table-level access control

### Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask |
| Real-time | Flask-SocketIO + eventlet (WebSocket) |
| ORM | Flask-SQLAlchemy |
| Database | PostgreSQL + pgvector |
| Cache | In-memory / Redis (dual-mode, switchable) |
| LLM Interface | OpenAI SDK (compatible with any OpenAI-protocol service) |
| Embedding Model | Ollama (qwen3-embedding:8b) or third-party embedding service |
| Vector Search | pgvector (cosine similarity + BM25 hybrid search) |
| Code Index Builder | LlamaIndex + CodeSplitter (tree-sitter) + PGVectorStore |
| File Parsing | pypdf, python-docx |
| Observability | LangSmith (`@traceable` decorator + env vars) |
| Security | API key auth, Prompt Injection filtering, input validation, audit logging |
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

### API Documentation

See `docs/api.md` for complete API documentation.
