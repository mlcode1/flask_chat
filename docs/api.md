# Flask Chat API 文档

## 概述

Flask Chat 是一个基于 Flask 的 AI 聊天应用，支持 WebSocket 实时通信、RAG 知识检索、代码索引等功能。

**Base URL**: `http://localhost:5000`

**认证**: 大部分 API 需要 API Key，通过 `X-API-Key` 请求头传递。

---

## 目录

1. [聊天相关 API](#聊天相关-api)
2. [RAG 知识库 API](#rag-知识库-api)
3. [代码索引 API](#代码索引-api)

---

## 聊天相关 API

### 页面路由

#### GET /
主页

#### GET /knowledge
知识库管理页面

#### GET /code-repos
代码库管理页面

---

### 配置接口

#### GET /api/models
获取可用模型列表

**Response**:
```json
{
  "models": ["gpt-4o", "gpt-3.5-turbo"],
  "default": "gpt-4o"
}
```

---

#### GET /api/config/verify
获取验证配置

**Response**:
```json
{
  "enabled": true,
  "model": "gpt-4o"
}
```

---

#### POST /api/config/verify
更新验证配置

**Request Body**:
```json
{
  "enabled": true
}
```

**Response**:
```json
{
  "enabled": true,
  "model": "gpt-4o"
}
```

---

#### GET /api/config/tools
获取工具配置

**Response**:
```json
{
  "knowledge_search": true,
  "code_index": false
}
```

---

#### POST /api/config/tools
更新工具配置

**Request Body**:
```json
{
  "knowledge_search": true,
  "code_index": false
}
```

**Response**:
```json
{
  "knowledge_search": true,
  "code_index": false
}
```

---

#### GET /api/config/disclaimer
获取免责声明文本

**Response**:
```json
{
  "text": "此内容由 AI 生成，仅供参考"
}
```

---

#### POST /api/config/disclaimer
更新免责声明文本

**Request Body**:
```json
{
  "text": "新的免责声明文本"
}
```

**Response**:
```json
{
  "text": "新的免责声明文本"
}
```

**Errors**:
- `400`: text 必须是字符串

---

### 健康检查

#### GET /api/health
健康检查端点

**Response**:
```json
{
  "status": "healthy",
  "database": "ok",
  "cache": "enabled",
  "cache_stats": {
    "backend": "memory",
    "total_entries": 42,
    "max_size": 1000
  },
  "models": {
    "default": "gpt-4o",
    "available": ["gpt-4o", "gpt-3.5-turbo"],
    "fallback": "gpt-3.5-turbo"
  },
  "timestamp": "2026-09-21T08:50:00.000Z"
}
```

---

#### POST /api/cache/clear
清空缓存

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "cleared",
  "message": "缓存已清空"
}
```

---

### 对话管理

#### POST /api/conversations
创建新对话

**Headers**: `X-API-Key: your-api-key`

**Request Body**:
```json
{
  "title": "新对话"
}
```

**Response**:
```json
{
  "id": 1,
  "title": "新对话"
}
```

---

#### GET /api/conversations/{cid}/messages
获取对话消息（分页）

**Headers**: `X-API-Key: your-api-key`

**Query Parameters**:
- `limit` (int, optional): 每页消息数量，默认 50，范围 1-100
- `cursor` (int, optional): 游标分页，返回该 ID 之前的消息

**Response**:
```json
{
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "你好",
      "interrupted": false,
      "verification": null,
      "image_urls": [],
      "token_count": 2,
      "tool_calls": [],
      "status": "completed",
      "created_at": "2026-09-21T08:50:00.000Z"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "你好！有什么可以帮助你的吗？",
      "interrupted": false,
      "verification": null,
      "image_urls": [],
      "token_count": 15,
      "tool_calls": [],
      "status": "completed",
      "created_at": "2026-09-21T08:50:05.000Z"
    }
  ],
  "has_more": false,
  "oldest_id": 1
}
```

---

#### DELETE /api/conversations/{cid}
删除对话

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "deleted"
}
```

---

#### PATCH /api/conversations/{cid}
重命名对话标题

**Headers**: `X-API-Key: your-api-key`

**Request Body**:
```json
{
  "title": "新的标题"
}
```

**Response**:
```json
{
  "id": 1,
  "title": "新的标题"
}
```

**Errors**:
- `400`: 标题不能为空
- `404`: 对话不存在

---

### 图片上传

#### POST /api/upload/image
上传图片

**Headers**: `X-API-Key: your-api-key`

**Request**: `multipart/form-data`
- `file`: 图片文件（png, jpg, jpeg, gif, webp），最大 10MB

**Response**:
```json
{
  "url": "data:image/png;base64,iVBORw0KGgo...",
  "filename": "image.png"
}
```

**Errors**:
- `400`: 未选择文件 / 不支持的图片格式 / 图片大小超过 10MB 限制

---

### 消息验证

#### POST /api/conversations/{cid}/messages/{mid}/verify
验证消息

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "verified",
  "explanation": "回答正确",
  "issues": []
}
```

**Errors**:
- `400`: 只能验证助手消息
- `404`: 消息不存在

---

### Token 统计

#### GET /api/conversations/{cid}/stats
获取对话 Token 统计

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "conversation_id": 1,
  "total_messages": 10,
  "total_tokens": 1500,
  "user_tokens": 500,
  "assistant_tokens": 1000
}
```

---

### 对话分享

#### POST /api/conversations/{cid}/share
生成分享链接

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "share_token": "abc123def456"
}
```

**Errors**:
- `404`: 对话不存在

---

#### GET /share/{token}
查看分享的对话

**Response**: HTML 页面

**Errors**:
- `404`: 分享链接不存在或已失效

---

### 对话导出

#### GET /api/conversations/{cid}/export
导出对话

**Headers**: `X-API-Key: your-api-key`

**Query Parameters**:
- `format` (string, optional): 导出格式，可选 `json`, `txt`, `markdown`（默认）

**Response**: 文件下载

**Errors**:
- `404`: 对话不存在

---

### 审计日志

#### GET /api/audit-logs
获取审计日志

**Headers**: `X-API-Key: your-api-key`

**Query Parameters**:
- `limit` (int, optional): 返回数量，默认 100
- `action` (string, optional): 按操作类型过滤

**Response**:
```json
[
  {
    "id": 1,
    "action": "create_conversation",
    "conversation_id": 1,
    "detail": "新对话",
    "created_at": "2026-09-21T08:50:00.000Z"
  }
]
```

---

### 消息反馈

#### POST /api/messages/{msg_id}/feedback
提交消息反馈

**Headers**: `X-API-Key: your-api-key`

**Request Body**:
```json
{
  "feedback": "like"
}
```

**Response**:
```json
{
  "status": "success",
  "message_id": 1,
  "feedback": "like"
}
```

**Errors**:
- `400`: 反馈类型必须是 like 或 dislike

---

## RAG 知识库 API

### 文档管理

#### POST /api/documents/upload
上传文档

**Request**: `multipart/form-data`
- `file`: 文档文件（txt, md, pdf, docx）

**Response**:
```json
{
  "id": 1,
  "filename": "document.pdf",
  "file_type": "pdf",
  "chunk_count": 42
}
```

**Errors**:
- `400`: 未选择文件 / 不支持的文件类型
- `500`: 处理文件失败

---

#### GET /api/documents
获取文档列表

**Response**:
```json
[
  {
    "id": 1,
    "filename": "document.pdf",
    "file_type": "pdf",
    "chunk_count": 42,
    "created_at": "2026-09-21T08:50:00.000Z"
  }
]
```

---

#### DELETE /api/documents/{doc_id}
删除文档

**Response**:
```json
{
  "status": "deleted"
}
```

**Errors**:
- `404`: 文档不存在

---

### 文档搜索

#### POST /api/documents/search
搜索文档

**Request Body**:
```json
{
  "query": "搜索关键词",
  "top_k": 5
}
```

**Response**:
```json
[
  {
    "content": "文档内容片段",
    "document_id": 1,
    "filename": "document.pdf",
    "chunk_index": 5,
    "score": 0.85
  }
]
```

**Errors**:
- `400`: 搜索内容不能为空

---

## 代码索引 API

**Base URL**: `/api/code-repos`

### 仓库管理

#### GET /api/code-repos
获取所有代码仓库配置

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "repos": [
    {
      "id": 1,
      "name": "flask-chat",
      "path": "/path/to/flask-chat",
      "status": "indexed",
      "chunk_count": 150,
      "file_count": 30,
      "error_message": null,
      "last_indexed_at": "2026-09-21T08:50:00.000Z",
      "last_full_index_time": "2026-09-21T08:50:00.000Z",
      "index_mode": "full",
      "created_at": "2026-09-20T10:00:00.000Z",
      "updated_at": "2026-09-21T08:50:00.000Z"
    }
  ]
}
```

---

#### POST /api/code-repos
创建新的代码仓库配置

**Headers**: `X-API-Key: your-api-key`

**Request Body**:
```json
{
  "name": "flask-chat",
  "path": "/path/to/flask-chat"
}
```

**Response** (201):
```json
{
  "status": "success",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    "path": "/path/to/flask-chat",
    "status": "pending",
    ...
  }
}
```

**Errors**:
- `400`: 请求体不能为空 / 仓库名称不能为空 / 仓库路径不能为空 / 路径不存在 / 路径不是目录 / 仓库名称已存在

---

#### GET /api/code-repos/{repo_id}
获取单个代码仓库配置

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    ...
  }
}
```

**Errors**:
- `404`: 仓库不存在

---

#### DELETE /api/code-repos/{repo_id}
删除代码仓库配置及其索引

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "message": "已删除仓库配置: flask-chat"
}
```

**Errors**:
- `404`: 仓库不存在

---

### 索引构建

#### POST /api/code-repos/{repo_id}/index
触发索引构建（异步）

**Headers**: `X-API-Key: your-api-key`

**Request Body**:
```json
{
  "reindex": true,
  "mode": "full"
}
```

**Parameters**:
- `reindex` (bool, optional): 是否重新索引，默认 true
- `mode` (string, optional): 索引模式，可选 `full`（全量）或 `incremental`（增量），默认 `full`

**Response**:
```json
{
  "status": "success",
  "message": "索引任务已启动（full模式）",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    "status": "indexing",
    ...
  }
}
```

**Errors**:
- `400`: 无效的索引模式，必须是 full 或 incremental
- `404`: 仓库不存在
- `409`: 索引任务正在运行中

---

#### GET /api/code-repos/{repo_id}/progress
获取索引进度

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "progress": 75,
  "message": "正在索引文件 30/40",
  "repo_status": "indexing",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    ...
  }
}
```

**Errors**:
- `404`: 仓库不存在

---

#### POST /api/code-repos/{repo_id}/cancel
取消索引任务

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "message": "已取消索引任务",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    "status": "failed",
    ...
  }
}
```

**Errors**:
- `400`: 没有正在运行的索引任务
- `404`: 仓库不存在

---

#### GET /api/code-repos/{repo_id}/status
获取仓库索引状态

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "repo": {
    "id": 1,
    "name": "flask-chat",
    "status": "indexed",
    ...
  }
}
```

**Errors**:
- `404`: 仓库不存在

---

#### GET /api/code-repos/{repo_id}/stats
获取仓库索引统计信息

**Headers**: `X-API-Key: your-api-key`

**Response**:
```json
{
  "status": "success",
  "stats": {
    "total_files": 40,
    "chunk_count": 150,
    "last_indexed_at": "2026-09-21T08:50:00.000Z",
    "last_full_index_time": "2026-09-21T08:50:00.000Z",
    "index_mode": "full",
    "status": "indexed"
  }
}
```

**Errors**:
- `404`: 仓库不存在

---

## WebSocket API

### 连接

**URL**: `ws://localhost:5000/socket.io/`

### 事件

#### connect
客户端连接时触发

**Server → Client**:
```json
{
  "status": "connected",
  "sid": "abc123"
}
```

---

#### join
加入对话房间

**Client → Server**:
```json
{
  "conversation_id": 1
}
```

---

#### leave
离开对话房间

**Client → Server**:
```json
{
  "conversation_id": 1
}
```

---

#### chat_message
发送聊天消息

**Client → Server**:
```json
{
  "conversation_id": 1,
  "content": "你好",
  "model": "gpt-4o",
  "image_urls": []
}
```

**Server → Client**:
```json
{
  "message_id": 1,
  "user_message_id": 2,
  "status": "generating"
}
```

---

#### token
流式返回生成的 token

**Server → Client**:
```json
{
  "message_id": 1,
  "token": "你好"
}
```

---

#### tool_calls
工具调用信息

**Server → Client**:
```json
{
  "message_id": 1,
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "search",
        "arguments": "{\"query\": \"test\"}"
      },
      "_result": "搜索结果..."
    }
  ]
}
```

---

#### generation_completed
生成完成

**Server → Client**:
```json
{
  "message_id": 1,
  "content": "完整的回复内容"
}
```

---

#### generation_stopped
生成被停止

**Server → Client**:
```json
{
  "message_id": 1,
  "content": "已生成的部分内容"
}
```

---

#### generation_resume
恢复生成（客户端重新连接时）

**Server → Client**:
```json
{
  "message_id": 1,
  "content": "已生成的部分内容"
}
```

---

#### stop_generation
停止生成

**Client → Server**:
```json
{
  "message_id": 1
}
```

---

#### verifying
开始验证

**Server → Client**:
```json
{
  "message_id": 1
}
```

---

#### verified
验证完成

**Server → Client**:
```json
{
  "message_id": 1,
  "verification": {
    "status": "verified",
    "explanation": "回答正确",
    "issues": []
  }
}
```

---

#### generation_error
生成错误

**Server → Client**:
```json
{
  "message_id": 1,
  "error": "回复失败，请重试"
}
```

---

## 错误响应格式

所有 API 错误使用统一格式：

```json
{
  "error": {
    "code": "bad_request",
    "message": "错误描述信息"
  }
}
```

**常见错误码**:
- `bad_request` (400): 请求参数错误
- `unauthorized` (401): 未授权
- `forbidden` (403): 禁止访问
- `not_found` (404): 资源不存在
- `conflict` (409): 资源冲突
- `internal_error` (500): 服务器内部错误
- `service_unavailable` (503): 服务不可用

---

## 配置说明

### 环境变量

```bash
# Flask
FLASK_SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:pass@localhost/dbname

# OpenAI
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Embedding
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL=qwen3-embedding:8b
EMBEDDING_DIM=4096

# Cache
CACHE_ENABLED=true
CACHE_TTL_HOURS=1
CACHE_MAX_SIZE=1000

# Redis (可选)
REDIS_ENABLED=false
REDIS_URL=redis://localhost:6379/0

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=human  # 或 json
```

---

## 版本

**API 版本**: 1.0  
**最后更新**: 2026-09-21
