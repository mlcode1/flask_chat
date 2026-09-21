from datetime import datetime, timezone
from app.extensions import db
from app.config import Config
from pgvector.sqlalchemy import Vector


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), default="新对话")
    summary = db.Column(db.Text, default="")
    memory = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages = db.relationship("Message", backref="conversation", lazy="dynamic", order_by="Message.created_at")

    def to_share_dict(self):
        """用于分享展示的序列化。

        注意：created_at 保持 datetime 对象，供 shared.html 模板调用
        .strftime() 格式化（若转成字符串会触发 strftime 报错）。
        """
        msgs = self.messages.order_by(Message.created_at).all()
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content or "",
                    "image_urls": m.image_urls or [],
                    "created_at": m.created_at,
                }
                for m in msgs
            ],
        }


class Message(db.Model):
    __tablename__ = "messages"
    __table_args__ = (
        db.Index('idx_message_conversation_created', 'conversation_id', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, default="")
    tool_calls = db.Column(db.JSON, default=list)
    tool_call_id = db.Column(db.String(100), nullable=True)
    interrupted = db.Column(db.Boolean, default=False)
    verification = db.Column(db.JSON, nullable=True)
    image_urls = db.Column(db.JSON, default=list)        # 多模态：图片 URL 列表
    token_count = db.Column(db.Integer, default=0)       # Token 计数统计
    compressed = db.Column(db.Boolean, default=False)    # 是否已压缩到摘要中
    feedback = db.Column(db.String(20), nullable=True)   # like/dislike/null
    status = db.Column(db.String(20), default='completed')  # generating/completed/stopped/error
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    chunk_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    chunks = db.relationship("DocumentChunk", backref="document", lazy="dynamic", cascade="all, delete-orphan")


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    embedding = db.Column(Vector(Config.EMBEDDING_DIM))


class SharedConversation(db.Model):
    """分享对话的公开链接"""
    __tablename__ = "shared_conversations"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    share_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = db.relationship("Conversation", backref="shares")


class ConversationTemplate(db.Model):
    """对话模板"""
    __tablename__ = "conversation_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    system_prompt = db.Column(db.Text, default="")
    category = db.Column(db.String(50), default="general")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    """审计日志"""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(50), nullable=False)           # chat / upload / share / delete 等
    conversation_id = db.Column(db.Integer, nullable=True)
    detail = db.Column(db.Text, default="")                      # JSON 或描述文本
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class CodeRepository(db.Model):
    """代码仓库配置"""
    __tablename__ = "code_repositories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)  # 仓库别名（如 flask_chat）
    path = db.Column(db.String(500), nullable=False)            # 本地路径（绝对路径）
    status = db.Column(db.String(20), default="pending")        # pending/indexing/indexed/failed
    chunk_count = db.Column(db.Integer, default=0)              # 分块数量
    file_count = db.Column(db.Integer, default=0)               # 文件数量
    error_message = db.Column(db.Text, nullable=True)           # 错误信息
    last_indexed_at = db.Column(db.DateTime, nullable=True)     # 最后索引时间
    progress = db.Column(db.Integer, default=0)                 # 索引进度（0-100）
    progress_message = db.Column(db.Text, nullable=True)        # 进度消息
    # 增量索引相关字段
    last_full_index_time = db.Column(db.DateTime, nullable=True)  # 最后全量索引时间
    index_mode = db.Column(db.String(20), default='full')         # 最后索引模式: full/incremental
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # 关系：文件索引记录
    indexed_files = db.relationship("IndexedFile", backref="repository", lazy="dynamic", cascade="all, delete-orphan")

    def to_dict(self):
        """序列化为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "chunk_count": self.chunk_count,
            "file_count": self.file_count,
            "error_message": self.error_message,
            "last_indexed_at": self.last_indexed_at.isoformat() if self.last_indexed_at else None,
            "last_full_index_time": self.last_full_index_time.isoformat() if self.last_full_index_time else None,
            "index_mode": self.index_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IndexedFile(db.Model):
    """文件索引记录 - 支持增量索引"""
    __tablename__ = "indexed_files"

    id = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, db.ForeignKey("code_repositories.id"), nullable=False)
    file_path = db.Column(db.Text, nullable=False)                # 文件路径（相对于仓库根目录）
    content_hash = db.Column(db.String(64), nullable=False)       # 文件内容的SHA256哈希值
    file_size = db.Column(db.BigInteger, default=0)               # 文件大小（字节）
    last_modified_time = db.Column(db.DateTime, nullable=True)    # 文件最后修改时间
    last_indexed_time = db.Column(db.DateTime, nullable=True)     # 最后索引时间
    chunk_count = db.Column(db.Integer, default=0)                # 该文件产生的分块数量
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # 唯一约束：同一个仓库中文件路径唯一
    __table_args__ = (
        db.UniqueConstraint('repo_id', 'file_path', name='uq_indexed_files_path'),
    )

    def to_dict(self):
        """序列化为字典"""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "file_size": self.file_size,
            "last_modified_time": self.last_modified_time.isoformat() if self.last_modified_time else None,
            "last_indexed_time": self.last_indexed_time.isoformat() if self.last_indexed_time else None,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
