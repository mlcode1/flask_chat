import json
import threading
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context, current_app
from app.extensions import db
from app.models import Conversation, Message
from app.services.ai_service import AIService
from app.services.context_service import ContextService
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

            final_content = full + AI_DISCLAIMER
            msg = db.session.get(Message, msg_id)
            msg.content = final_content
            if stop_event.is_set():
                msg.interrupted = True
            db.session.commit()

            conv = db.session.get(Conversation, cid)
            conv.updated_at = db.func.now()
            db.session.commit()

            yield f"data: {json.dumps({'done': True, 'content': final_content}, ensure_ascii=False)}\n\n"
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


@chat_bp.route("/api/conversations/<int:cid>", methods=["DELETE"])
def delete_conversation(cid):
    Message.query.filter_by(conversation_id=cid).delete()
    conv = db.session.get(Conversation, cid)
    if conv:
        db.session.delete(conv)
    db.session.commit()
    return jsonify({"status": "deleted"})
