"""
聊天路由：对话、验证配置、分享、导出、图片上传、审计日志
"""
import json
import re
import uuid
import io
import base64
import logging
from datetime import datetime
from flask import (
    Blueprint, render_template, request, jsonify, current_app, send_file
)
from app.extensions import db
from app.models import Conversation, Message, SharedConversation
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.verifier_service import VerifierService
from app.services.security_service import (
    require_api_key, filter_input, log_audit
)
from app.middleware import get_disclaimer
from app.services import cache_service as cache_service_module
from app.services.cache_service import hash_context
from app.errors import BadRequestError, NotFoundError


logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


# ============================================================
# 页面 & 配置接口
# ============================================================

@chat_bp.route("/")
def index():
    conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(50).all()
    return render_template("index.html", conversations=conversations)


@chat_bp.route("/knowledge")
def knowledge_page():
    """知识库管理页面"""
    conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(50).all()
    return render_template("knowledge.html", conversations=conversations)


@chat_bp.route("/code-repos")
def code_repos_page():
    """代码库管理页面"""
    conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(50).all()
    return render_template("code_repos.html", conversations=conversations)


@chat_bp.route("/api/models")
@require_api_key
def get_models():
    return jsonify({
        "models": current_app.config["AVAILABLE_MODELS"],
        "default": current_app.config["OPENAI_MODEL"],
    })


@chat_bp.route("/api/config/verify")
def get_verify_config():
    return jsonify({
        "enabled": current_app.config["VERIFY_ENABLED"],
        "model": current_app.config.get("VERIFY_MODEL", ""),
    })


@chat_bp.route("/api/config/verify", methods=["POST"])
def update_verify_config():
    data = request.get_json()
    enabled = data.get("enabled")
    if enabled is not None:
        current_app.config["VERIFY_ENABLED"] = bool(enabled)
    return jsonify({
        "enabled": current_app.config["VERIFY_ENABLED"],
        "model": current_app.config.get("VERIFY_MODEL", ""),
    })


@chat_bp.route("/api/config/tools")
def get_tools_config():
    return jsonify({
        "knowledge_search": current_app.config.get("KNOWLEDGE_SEARCH_ENABLED", False),
        "code_index": current_app.config.get("CODE_INDEX_ENABLED", False),
    })


@chat_bp.route("/api/config/tools", methods=["POST"])
def update_tools_config():
    data = request.get_json()
    if "knowledge_search" in data:
        current_app.config["KNOWLEDGE_SEARCH_ENABLED"] = bool(data["knowledge_search"])
    if "code_index" in data:
        current_app.config["CODE_INDEX_ENABLED"] = bool(data["code_index"])
    return jsonify({
        "knowledge_search": current_app.config.get("KNOWLEDGE_SEARCH_ENABLED", False),
        "code_index": current_app.config.get("CODE_INDEX_ENABLED", False),
    })


@chat_bp.route("/api/config/disclaimer")
def get_disclaimer_config():
    return jsonify({"text": current_app.config.get("AI_DISCLAIMER_TEXT", "")})


@chat_bp.route("/api/config/disclaimer", methods=["POST"])
def update_disclaimer_config():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not isinstance(text, str):
        raise BadRequestError("text 必须是字符串")
    decoded = text.strip()
    current_app.config["AI_DISCLAIMER_TEXT"] = decoded
    return jsonify({"text": decoded})


# ============================================================
# 健康检查 & 缓存统计
# ============================================================

@chat_bp.route("/api/health")
def health_check():
    """健康检查端点"""
    try:
        # 检查数据库连接
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    # 检查缓存状态
    cache_status = "enabled" if current_app.config.get("CACHE_ENABLED") else "disabled"
    
    return jsonify({
        "status": "healthy" if db_status == "ok" else "degraded",
        "database": db_status,
        "cache": cache_status,
        "cache_stats": cache_service_module.cache_service.stats() if cache_service_module.cache_service and current_app.config.get("CACHE_ENABLED") else None,
        "models": {
            "default": current_app.config["OPENAI_MODEL"],
            "available": current_app.config["AVAILABLE_MODELS"],
            "fallback": current_app.config.get("FALLBACK_MODEL", ""),
        },
        "timestamp": datetime.now().isoformat()
    })


@chat_bp.route("/api/cache/clear", methods=["POST"])
@require_api_key
def clear_cache():
    """清空缓存"""
    if cache_service_module.cache_service:
        cache_service_module.cache_service.clear()
        return jsonify({"status": "cleared", "message": "缓存已清空"})
    return jsonify({"status": "error", "message": "缓存服务未初始化"}), 500


# ============================================================
# 对话 CRUD
# ============================================================

@chat_bp.route("/api/conversations", methods=["POST"])
@require_api_key
def create_conversation():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "新对话")
    conv = Conversation(title=title)
    db.session.add(conv)
    db.session.commit()
    log_audit("create_conversation", conversation_id=conv.id, detail=title)
    return jsonify({"id": conv.id, "title": conv.title})


@chat_bp.route("/api/conversations/<int:cid>/messages")
@require_api_key
def get_messages(cid):
    # 分页参数
    limit = request.args.get("limit", 50, type=int)
    limit = min(max(limit, 1), 100)  # 限制范围 1-100
    
    # 游标分页：cursor 是消息 ID，返回该 ID 之前的消息
    cursor = request.args.get("cursor", type=int)
    
    query = Message.query.filter_by(conversation_id=cid)
    
    # 如果有游标，查询该 ID 之前的消息
    if cursor:
        query = query.filter(Message.id < cursor)
    
    # 按 ID 降序获取最新的 limit 条消息
    messages = query.order_by(Message.id.desc()).limit(limit).all()
    
    # 反转为正序（从旧到新）
    messages = list(reversed(messages))
    
    # 判断是否还有更多消息
    has_more = False
    if messages:
        oldest_id = messages[0].id
        has_more = Message.query.filter_by(conversation_id=cid).filter(Message.id < oldest_id).first() is not None
    
    return jsonify({
        "messages": [{
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "interrupted": m.interrupted,
            "verification": m.verification,
            "image_urls": m.image_urls or [],
            "token_count": m.token_count or 0,
            "tool_calls": m.tool_calls or [],
            "status": m.status or "completed",
            "created_at": m.created_at.isoformat(),
        } for m in messages],
        "has_more": has_more,
        "oldest_id": messages[0].id if messages else None
    })


@chat_bp.route("/api/conversations/<int:cid>", methods=["DELETE"])
@require_api_key
def delete_conversation(cid):
    Message.query.filter_by(conversation_id=cid).delete()
    SharedConversation.query.filter_by(conversation_id=cid).delete()
    conv = db.session.get(Conversation, cid)
    if conv:
        db.session.delete(conv)
    db.session.commit()
    log_audit("delete_conversation", conversation_id=cid)
    return jsonify({"status": "deleted"})


@chat_bp.route("/api/conversations/<int:cid>", methods=["PATCH"])
@require_api_key
def rename_conversation(cid):
    """重命名对话标题"""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        raise BadRequestError("标题不能为空")
    conv = db.session.get(Conversation, cid)
    if not conv:
        raise NotFoundError("对话不存在")
    conv.title = title[:50]
    db.session.commit()
    log_audit("rename_conversation", conversation_id=cid, detail=title)
    return jsonify({"id": cid, "title": conv.title})


# ============================================================
# 对话标题更新（自动生成标题）
# ============================================================

def _auto_title(conv_id, first_message):
    """用 LLM 自动生成对话标题"""
    try:
        ai = AIService()
        title = ai.sync_complete(
            f"请用不超过15个字概括以下用户消息的主题，作为对话标题。只返回标题文字：\n\n{first_message}"
        )
        if title and len(title) > 1:
            conv = db.session.get(Conversation, conv_id)
            if conv and conv.title == "新对话":
                conv.title = title.strip()[:50]
                db.session.commit()
    except Exception as e:
        logger.warning("自动生成标题失败: %s", e)


# ============================================================
# 图片上传
# ============================================================

@chat_bp.route("/api/upload/image", methods=["POST"])
@require_api_key
def upload_image():
    """上传图片，返回 base64 data URL"""
    if "file" not in request.files:
        raise BadRequestError("未选择文件")

    file = request.files["file"]
    if file.filename == "":
        raise BadRequestError("未选择文件")

    allowed_ext = {"png", "jpg", "jpeg", "gif", "webp"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed_ext:
        raise BadRequestError(f"不支持的图片格式，支持: {', '.join(allowed_ext)}")

    # 读取并转 base64
    data = file.read()
    if len(data) > 10 * 1024 * 1024:  # 10MB limit
        raise BadRequestError("图片大小超过 10MB 限制")

    b64 = base64.b64encode(data).decode("utf-8")
    mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    return jsonify({"url": data_url, "filename": file.filename})


# ============================================================
# 消息验证
# ============================================================

@chat_bp.route("/api/conversations/<int:cid>/messages/<int:mid>/verify", methods=["POST"])
@require_api_key
def verify_message(cid, mid):
    if not current_app.config["VERIFY_ENABLED"]:
        return jsonify({"status": "skipped", "explanation": "无需校验", "issues": []})

    msg = db.session.get(Message, mid)
    if not msg or msg.conversation_id != cid:
        raise NotFoundError("消息不存在")
    if msg.role != "assistant":
        raise BadRequestError("只能验证助手消息")

    prev_msg = Message.query.filter_by(
        conversation_id=cid, role="user"
    ).filter(Message.id < mid).order_by(Message.id.desc()).first()
    question = prev_msg.content if prev_msg else ""

    try:
        verifier = VerifierService()
        result = verifier.verify_answer(question=question, answer=msg.content)
        if result.get("status") != "skipped":
            msg.verification = result
            db.session.commit()
        return jsonify(result)
    except Exception as e:
        logger.warning("手动验证异常: %s", e)
        return jsonify({"status": "skipped", "explanation": "无需校验", "issues": []})


# ============================================================
# Token 统计
# ============================================================

@chat_bp.route("/api/conversations/<int:cid>/stats")
@require_api_key
def get_conversation_stats(cid):
    """获取对话的 Token 统计"""
    messages = Message.query.filter_by(conversation_id=cid).all()
    total_tokens = sum(m.token_count or 0 for m in messages)
    user_tokens = sum(m.token_count or 0 for m in messages if m.role == "user")
    assistant_tokens = sum(m.token_count or 0 for m in messages if m.role == "assistant")

    return jsonify({
        "conversation_id": cid,
        "total_messages": len(messages),
        "total_tokens": total_tokens,
        "user_tokens": user_tokens,
        "assistant_tokens": assistant_tokens,
    })


# ============================================================
# 对话分享
# ============================================================

@chat_bp.route("/api/conversations/<int:cid>/share", methods=["POST"])
@require_api_key
def share_conversation(cid):
    """生成分享链接"""
    conv = db.session.get(Conversation, cid)
    if not conv:
        raise NotFoundError("对话不存在")

    # 检查是否已有分享记录
    existing = SharedConversation.query.filter_by(conversation_id=cid).first()
    if existing:
        return jsonify({"share_token": existing.share_token})

    token = uuid.uuid4().hex[:16]
    share = SharedConversation(conversation_id=cid, share_token=token)
    db.session.add(share)
    db.session.commit()

    log_audit("share", conversation_id=cid, detail=token)
    return jsonify({"share_token": token})


@chat_bp.route("/share/<token>")
def view_shared(token):
    """查看分享的对话"""
    share = SharedConversation.query.filter_by(share_token=token).first()
    if not share:
        return "分享链接不存在或已失效", 404

    conv = share.conversation
    return render_template("shared.html", conversation=conv.to_share_dict())


# ============================================================
# 对话导出
# ============================================================

@chat_bp.route("/api/conversations/<int:cid>/export")
@require_api_key
def export_conversation(cid):
    """导出对话为 Markdown / JSON / TXT"""
    conv = db.session.get(Conversation, cid)
    if not conv:
        raise NotFoundError("对话不存在")

    fmt = request.args.get("format", "markdown")
    messages = Message.query.filter_by(conversation_id=cid).order_by(Message.created_at).all()

    if fmt == "json":
        data = {
            "title": conv.title,
            "exported_at": datetime.now().isoformat(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content or "",
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }
        content = json.dumps(data, ensure_ascii=False, indent=2)
        mime = "application/json"
        ext = "json"

    elif fmt == "txt":
        lines = [f"# {conv.title}\n"]
        for m in messages:
            role_label = "用户" if m.role == "user" else "AI"
            lines.append(f"[{role_label}] {m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else ''}")
            lines.append(m.content or "")
            lines.append("")
        content = "\n".join(lines)
        mime = "text/plain"
        ext = "txt"

    else:  # markdown (default)
        lines = [f"# {conv.title}\n\n"]
        for m in messages:
            role_label = "👤 用户" if m.role == "user" else "🤖 AI"
            ts = m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else ''
            lines.append(f"## {role_label} ({ts})\n\n")
            lines.append(m.content or "")
            lines.append("\n\n---\n\n")
        content = "".join(lines)
        mime = "text/markdown"
        ext = "md"

    log_audit("export", conversation_id=cid, detail=f"format={fmt}")

    buf = io.BytesIO(content.encode("utf-8"))
    safe_title = re.sub(r'[^\w\u4e00-\u9fff]', '_', conv.title)[:50]
    return send_file(
        buf,
        mimetype=mime,
        as_attachment=True,
        download_name=f"{safe_title}.{ext}",
    )


# ============================================================
# 审计日志
# ============================================================

@chat_bp.route("/api/audit-logs")
@require_api_key
def get_audit_logs():
    """获取审计日志"""
    from app.services.security_service import get_audit_logs
    limit = request.args.get("limit", 100, type=int)
    action = request.args.get("action")
    logs = get_audit_logs(limit=limit, action=action)
    return jsonify(logs)


@chat_bp.route("/api/messages/<int:msg_id>/feedback", methods=["POST"])
@require_api_key
def submit_feedback(msg_id):
    """提交消息反馈（like/dislike）"""
    msg = Message.query.get_or_404(msg_id)
    data = request.get_json()
    feedback = data.get("feedback")
    
    if feedback not in ["like", "dislike"]:
        raise BadRequestError("反馈类型必须是 like 或 dislike")
    
    msg.feedback = feedback
    db.session.commit()
    
    # 记录审计日志
    log_audit("feedback", msg.conversation_id, f"Message {msg_id}: {feedback}")
    
    return jsonify({
        "status": "success",
        "message_id": msg_id,
        "feedback": feedback
    })
