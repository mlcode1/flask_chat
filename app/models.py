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
