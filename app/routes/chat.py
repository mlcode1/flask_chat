"""
聊天路由：对话、验证配置、分享、导出、图片上传、审计日志
"""
import json
import re
import logging
import threading
import uuid
import os
import io
import base64
from datetime import datetime
from flask import (
    Blueprint, render_template, request, jsonify, Response,
    stream_with_context, current_app, send_file
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
from app.services.cache_service import cache_service, hash_context


logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)

_interrupt_events = {}


# ============================================================
# 页面 & 配置接口
# ============================================================

@chat_bp.route("/")
def index():
    conversations = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    return render_template("index.html", conversations=conversations)


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


@chat_bp.route("/api/config/disclaimer")
def get_disclaimer_config():
    return jsonify({"text": current_app.config.get("AI_DISCLAIMER_TEXT", "")})


@chat_bp.route("/api/config/disclaimer", methods=["POST"])
def update_disclaimer_config():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not isinstance(text, str):
        return jsonify({"error": "text 必须是字符串"}), 400
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
        "cache_stats": cache_service.stats() if current_app.config.get("CACHE_ENABLED") else None,
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
    cache_service.clear()
    return jsonify({"status": "cleared", "message": "缓存已清空"})


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
    messages = Message.query.filter_by(conversation_id=cid).order_by(Message.created_at).all()
    return jsonify([{
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "interrupted": m.interrupted,
        "verification": m.verification,
        "image_urls": m.image_urls or [],
        "token_count": m.token_count or 0,
        "tool_calls": m.tool_calls or [],
        "created_at": m.created_at.isoformat(),
    } for m in messages])


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
        return jsonify({"error": "标题不能为空"}), 400
    conv = db.session.get(Conversation, cid)
    if not conv:
        return jsonify({"error": "对话不存在"}), 404
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
        return jsonify({"error": "未选择文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "未选择文件"}), 400

    allowed_ext = {"png", "jpg", "jpeg", "gif", "webp"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed_ext:
        return jsonify({"error": f"不支持的图片格式，支持: {', '.join(allowed_ext)}"}), 400

    # 读取并转 base64
    data = file.read()
    if len(data) > 10 * 1024 * 1024:  # 10MB limit
        return jsonify({"error": "图片大小超过 10MB 限制"}), 400

    b64 = base64.b64encode(data).decode("utf-8")
    mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    return jsonify({"url": data_url, "filename": file.filename})


# ============================================================
# 聊天主流程
# ============================================================

@chat_bp.route("/api/conversations/<int:cid>/chat", methods=["POST"])
@require_api_key
def chat(cid):
    data = request.get_json() or {}
    user_content = data.get("content", "").strip()
    model = data.get("model", "").strip() or current_app.config["OPENAI_MODEL"]
    image_urls = data.get("image_urls", [])

    if not user_content and not image_urls:
        return jsonify({"error": "消息不能为空"}), 400

    # 输入过滤
    is_safe, filtered_text, warning = filter_input(user_content)
    if not is_safe:
        user_msg = Message(conversation_id=cid, role="user", content=user_content, image_urls=image_urls or [])
        db.session.add(user_msg)
        db.session.commit()

        assistant_msg = Message(
            conversation_id=cid, role="assistant",
            content=f"⚠️ {warning}\n\n为了安全起见，我无法处理包含潜在注入指令的输入。请重新描述你的问题。",
        )
        db.session.add(assistant_msg)
        db.session.commit()
        log_audit("input_filtered", conversation_id=cid, detail=user_content[:200])
        return jsonify({"error": warning, "message_id": assistant_msg.id}), 400

    # 创建用户消息
    user_msg = Message(
        conversation_id=cid, role="user",
        content=user_content, image_urls=image_urls or [],
    )
    db.session.add(user_msg)
    db.session.commit()

    # 统计用户消息 token
    ai_svc = AIService(model=model)
    user_msg.token_count = ai_svc.estimate_tokens(user_content)
    if image_urls:
        user_msg.token_count += len(image_urls) * 85  # 图片约 85 tokens each
    db.session.commit()

    # 自动生成标题（第一条消息）
    msg_count = Message.query.filter_by(conversation_id=cid, role="user").count()
    if msg_count == 1:
        _auto_title(cid, user_content)

    # 上下文压缩
    ctx = ContextService(current_app.config["MAX_CONTEXT_TOKENS"])
    if ctx.should_compress(cid):
        ctx.compress_context(cid, ai_svc)

    messages = ctx.build_context(cid)

    # 响应缓存：检查是否有缓存结果
    cache_enabled = current_app.config.get("CACHE_ENABLED", False)
    context_hash = hash_context(messages) if cache_enabled else None
    cached_response = cache_service.get(user_content, context_hash) if cache_enabled else None

    stop_event = threading.Event()
    _interrupt_events[cid] = stop_event

    assistant_msg = Message(conversation_id=cid, role="assistant", content="")
    db.session.add(assistant_msg)
    db.session.commit()
    msg_id = assistant_msg.id

    log_audit("chat", conversation_id=cid, detail=f"model={model}")

    def generate():
        full = ""

        # 缓存命中：直接返回缓存结果
        if cached_response:
            try:
                yield f"data: {json.dumps({'token': cached_response}, ensure_ascii=False)}\n\n"
                msg = db.session.get(Message, msg_id)
                msg.content = cached_response
                msg.token_count = ai_svc.estimate_tokens(cached_response)
                db.session.commit()
                conv = db.session.get(Conversation, cid)
                conv.updated_at = db.func.now()
                db.session.commit()
                yield f"data: {json.dumps({'done': True, 'content': cached_response, 'message_id': msg_id, 'token_count': msg.token_count, 'cached': True}, ensure_ascii=False)}\n\n"
                return
            except Exception as e:
                logger.warning(f"Cache response failed: {e}")
                return

        try:
            ai = AIService(model=model)

            def on_chunk(text):
                nonlocal full
                full += text

            def on_tool_call(tc, result):
                """工具调用时通过 SSE 发送事件"""
                nonlocal tool_calls_log
                # 保存为 OpenAI 标准格式（带 _result 用于前端展示）
                tool_info = {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                    "_result": result[:500] if result else "",
                }
                tool_calls_log.append(tool_info)

            tool_calls_log = []

            for token in ai.stream_response(messages, on_chunk=on_chunk, on_tool_call=on_tool_call, stop_event=stop_event):
                if stop_event.is_set():
                    break
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

            # 发送工具调用信息（如果有的话）
            if tool_calls_log:
                yield f"data: {json.dumps({'tool_calls': tool_calls_log}, ensure_ascii=False)}\n\n"

            # Disclaimer 处理
            disclaimer = get_disclaimer()
            if not disclaimer:
                # 未配置免责声明，直接返回 AI 结果
                final_content = full
            elif disclaimer.strip() in full or os.getenv("AI_DISCLAIMER_TEXT", "").strip() in full:
                # AI 已自带免责声明，避免重复
                final_content = full
            else:
                final_content = full + disclaimer

            # 保存消息（含工具调用记录）
            msg = db.session.get(Message, msg_id)
            msg.content = final_content
            msg.token_count = ai.estimate_tokens(final_content)
            msg.tool_calls = tool_calls_log if tool_calls_log else []
            if stop_event.is_set():
                msg.interrupted = True
            db.session.commit()

            conv = db.session.get(Conversation, cid)
            conv.updated_at = db.func.now()
            db.session.commit()

            # 写入缓存（仅在无工具调用时缓存）
            if cache_enabled and not tool_calls_log and not stop_event.is_set():
                try:
                    cache_service.set(user_content, final_content, context_hash, ttl_hours=1)
                except Exception as e:
                    logger.warning(f"Cache write failed: {e}")

            yield f"data: {json.dumps({'done': True, 'content': final_content, 'message_id': msg_id, 'token_count': msg.token_count}, ensure_ascii=False)}\n\n"

            # 结果验证
            if current_app.config["VERIFY_ENABLED"] and not stop_event.is_set():
                yield f"data: {json.dumps({'verifying': True}, ensure_ascii=False)}\n\n"
                try:
                    verifier = VerifierService()
                    verify_result = verifier.verify_answer(
                        question=user_content,
                        answer=final_content,
                    )
                    if verify_result.get("status") != "skipped":
                        msg = db.session.get(Message, msg_id)
                        msg.verification = verify_result
                        db.session.commit()
                    yield f"data: {json.dumps({'verified': verify_result}, ensure_ascii=False)}\n\n"
                except Exception as verify_err:
                    logger.warning("自动验证异常: %s", verify_err)
                    yield f"data: {json.dumps({'verified': {'status': 'skipped'}}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error("聊天流异常: %s", e)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            _interrupt_events.pop(cid, None)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@chat_bp.route("/api/conversations/<int:cid>/interrupt", methods=["POST"])
@require_api_key
def interrupt(cid):
    event = _interrupt_events.get(cid)
    if event:
        event.set()
        return jsonify({"status": "interrupted"})
    return jsonify({"status": "no_active_stream"}), 404


@chat_bp.route("/api/conversations/<int:cid>/messages/<int:mid>/verify", methods=["POST"])
@require_api_key
def verify_message(cid, mid):
    if not current_app.config["VERIFY_ENABLED"]:
        return jsonify({"status": "skipped", "explanation": "无需校验", "issues": []})

    msg = db.session.get(Message, mid)
    if not msg or msg.conversation_id != cid:
        return jsonify({"error": "消息不存在"}), 404
    if msg.role != "assistant":
        return jsonify({"error": "只能验证助手消息"}), 400

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
        return jsonify({"error": "对话不存在"}), 404

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
        return jsonify({"error": "对话不存在"}), 404

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
        return jsonify({"error": "反馈类型必须是 like 或 dislike"}), 400
    
    msg.feedback = feedback
    db.session.commit()
    
    # 记录审计日志
    log_audit("feedback", msg.conversation_id, f"Message {msg_id}: {feedback}")
    
    return jsonify({
        "status": "success",
        "message_id": msg_id,
        "feedback": feedback
    })
