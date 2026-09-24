"""
Webhook 服务：对话完成后的出站回调 + 入站 API 触发对话
支持飞书/钉钉/企业微信等外部系统集成
"""
import json
import logging
import requests
import threading
from datetime import datetime, timezone
from app.extensions import db

logger = logging.getLogger(__name__)


class WebhookService:
    """Webhook 服务：管理出站 Webhook 和入站对话触发"""
    
    @staticmethod
    def send_completion_webhook(conversation_id, webhook_url, secret=None):
        """对话完成后发送 Webhook 通知"""
        from app.models import Conversation, Message
        
        conv = db.session.get(Conversation, conversation_id)
        if not conv:
            logger.warning(f"Webhook: 对话 {conversation_id} 不存在")
            return False
        
        messages = Message.query.filter_by(
            conversation_id=conversation_id
        ).order_by(Message.created_at.desc()).limit(2).all()
        
        if not messages:
            return False
        
        last_ai_msg = None
        last_user_msg = None
        for m in messages:
            if m.role == 'assistant' and not last_ai_msg:
                last_ai_msg = m
            elif m.role == 'user' and not last_user_msg:
                last_user_msg = m
        
        if not last_ai_msg:
            return False
        
        payload = {
            "event": "conversation.completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "title": conv.title,
            "user_message": last_user_msg.content[:500] if last_user_msg else "",
            "ai_response": last_ai_msg.content[:2000],
            "message_id": last_ai_msg.id,
        }
        
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Webhook-Secret"] = secret
        
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=10
            )
            if response.status_code in (200, 201, 202, 204):
                logger.info(f"Webhook 发送成功: {conversation_id} -> {webhook_url}")
                return True
            else:
                logger.warning(f"Webhook 返回异常状态: {response.status_code}")
                return False
        except requests.exceptions.Timeout:
            logger.warning(f"Webhook 超时: {webhook_url}")
            return False
        except Exception as e:
            logger.error(f"Webhook 发送失败: {e}")
            return False
    
    @staticmethod
    def trigger_conversation(user_content, model=None, webhook_url=None):
        """入站 API：外部系统触发新对话"""
        from app.models import Conversation, Message
        
        conv = Conversation(title="外部触发对话")
        db.session.add(conv)
        db.session.commit()
        
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=user_content,
            status="completed"
        )
        db.session.add(user_msg)
        db.session.commit()
        
        return {
            "conversation_id": conv.id,
            "user_message_id": user_msg.id,
            "status": "created"
        }


# Webhook 配置存储（内存，生产环境可用 Redis/DB）
_webhook_configs = {}


def register_webhook(conversation_id, url, secret=None, events=None):
    """注册 Webhook 配置"""
    if events is None:
        events = ["conversation.completed"]
    
    _webhook_configs[conversation_id] = {
        "url": url,
        "secret": secret,
        "events": events,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    logger.info(f"注册 Webhook: conversation={conversation_id}, url={url}")


def get_webhook_config(conversation_id):
    """获取 Webhook 配置"""
    return _webhook_configs.get(conversation_id)


def list_webhooks():
    """列出所有 Webhook 配置"""
    return {k: v for k, v in _webhook_configs.items()}


def delete_webhook(conversation_id):
    """删除 Webhook 配置"""
    return _webhook_configs.pop(conversation_id, None)


def fire_webhook(event, conversation_id):
    """触发 Webhook（异步）"""
    config = get_webhook_config(conversation_id)
    if not config:
        return
    
    if event not in config.get("events", []):
        return
    
    # 异步发送，不阻塞主流程
    def _send():
        from app import create_app
        app = create_app()
        with app.app_context():
            WebhookService.send_completion_webhook(
                conversation_id,
                config["url"],
                config.get("secret")
            )
    
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
