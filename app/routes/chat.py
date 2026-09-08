import json
import threading
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context, current_app
from app.extensions import db
from app.models import Conversation, Message
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.verifier_service import VerifierService
from app.middleware import AI_DISCLAIMER

chat_bp = Blueprint("chat", __name__)

_interrupt_events = {}


@chat_bp.route("/")
def index():
    conversations = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    return render_template("index.html", conversations=conversations)


@chat_bp.route("/api/models")
def get_models():
    return jsonify({
        "models": current_app.config["AVAILABLE_MODELS"],
        "default": current_app.config["OPENAI_MODEL"],
    })


@chat_bp.route("/api/config/verify")
def get_verify_config():
    """获取验证功能配置"""
    return jsonify({
        "enabled": current_app.config["VERIFY_ENABLED"],
        "model": current_app.config.get("VERIFY_MODEL", ""),
    })


@chat_bp.route("/api/config/verify", methods=["POST"])
def update_verify_config():
    """动态更新验证功能开关"""
    data = request.get_json()
    enabled = data.get("enabled")
    if enabled is not None:
        current_app.config["VERIFY_ENABLED"] = bool(enabled)
    return jsonify({
        "enabled": current_app.config["VERIFY_ENABLED"],
        "model": current_app.config.get("VERIFY_MODEL", ""),
    })


@chat_bp.route("/api/conversations", methods=["POST"])
def create_conversation():
    conv = Conversation(title="新对话")
    db.session.add(conv)
    db.session.commit()
    return jsonify({"id": conv.id, "title": conv.title})


@chat_bp.route("/api/conversations/<int:cid>/messages")
def get_messages(cid):
    messages = Message.query.filter_by(conversation_id=cid).order_by(Message.created_at).all()
    return jsonify([{
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "interrupted": m.interrupted,
        "verification": m.verification,
        "created_at": m.created_at.isoformat(),
    } for m in messages])


@chat_bp.route("/api/conversations/<int:cid>/chat", methods=["POST"])
def chat(cid):
    data = request.get_json()
    user_content = data.get("content", "").strip()
    model = data.get("model", "").strip() or current_app.config["OPENAI_MODEL"]
    if not user_content:
        return jsonify({"error": "消息不能为空"}), 400

    user_msg = Message(conversation_id=cid, role="user", content=user_content)
    db.session.add(user_msg)
    db.session.commit()

    ctx = ContextService(current_app.config["MAX_CONTEXT_TOKENS"])
    if ctx.should_compress(cid):
        ai = AIService(model=model)
        ctx.compress_context(cid, ai)

    messages = ctx.build_context(cid)

    stop_event = threading.Event()
    _interrupt_events[cid] = stop_event

    assistant_msg = Message(conversation_id=cid, role="assistant", content="")
    db.session.add(assistant_msg)
    db.session.commit()
    msg_id = assistant_msg.id

    def generate():
        full = ""
        try:
            ai = AIService(model=model)

            def on_chunk(text):
                nonlocal full
                full += text

            for token in ai.stream_response(messages, on_chunk=on_chunk, stop_event=stop_event):
                if stop_event.is_set():
                    break
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

            # 避免重复添加 disclaimer：如果 AI 输出已包含「消息来源于大模型返回」则不再附加
            if "消息来源于大模型返回" in full:
                final_content = full
            else:
                final_content = full + AI_DISCLAIMER
            msg = db.session.get(Message, msg_id)
            msg.content = final_content
            if stop_event.is_set():
                msg.interrupted = True
            db.session.commit()

            conv = db.session.get(Conversation, cid)
            conv.updated_at = db.func.now()
            db.session.commit()

            yield f"data: {json.dumps({'done': True, 'content': final_content, 'message_id': msg_id}, ensure_ascii=False)}\n\n"

            # 如果验证开关打开且消息未被中断，自动触发验证
            if current_app.config["VERIFY_ENABLED"] and not stop_event.is_set():
                yield f"data: {json.dumps({'verifying': True}, ensure_ascii=False)}\n\n"
                try:
                    verifier = VerifierService()
                    verify_result = verifier.verify_answer(
                        question=user_content,
                        answer=final_content,
                    )
                    msg = db.session.get(Message, msg_id)
                    msg.verification = verify_result
                    db.session.commit()
                    yield f"data: {json.dumps({'verified': verify_result}, ensure_ascii=False)}\n\n"
                except Exception as verify_err:
                    yield f"data: {json.dumps({'verified': {'error': str(verify_err)}}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            _interrupt_events.pop(cid, None)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@chat_bp.route("/api/conversations/<int:cid>/interrupt", methods=["POST"])
def interrupt(cid):
    event = _interrupt_events.get(cid)
    if event:
        event.set()
        return jsonify({"status": "interrupted"})
    return jsonify({"status": "no_active_stream"}), 404


@chat_bp.route("/api/conversations/<int:cid>/messages/<int:mid>/verify", methods=["POST"])
def verify_message(cid, mid):
    """手动触发验证某条消息"""
    msg = db.session.get(Message, mid)
    if not msg or msg.conversation_id != cid:
        return jsonify({"error": "消息不存在"}), 404
    if msg.role != "assistant":
        return jsonify({"error": "只能验证助手消息"}), 400

    # 找到对应的用户问题
    prev_msg = Message.query.filter_by(
        conversation_id=cid, role="user"
    ).filter(Message.id < mid).order_by(Message.id.desc()).first()
    question = prev_msg.content if prev_msg else ""

    try:
        verifier = VerifierService()
        result = verifier.verify_answer(question=question, answer=msg.content)
        msg.verification = result
        db.session.commit()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/api/conversations/<int:cid>", methods=["DELETE"])
def delete_conversation(cid):
    Message.query.filter_by(conversation_id=cid).delete()
    conv = db.session.get(Conversation, cid)
    if conv:
        db.session.delete(conv)
    db.session.commit()
    return jsonify({"status": "deleted"})
