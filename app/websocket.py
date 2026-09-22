"""
WebSocket 事件处理器
实现实时双向通信，支持后台生成 AI 回复（前端断开不丢失数据）
"""
import threading
import logging
from flask import current_app, request
from flask_socketio import emit, join_room, leave_room
from app.extensions import db
from app.models import Message, Conversation
from app.services.ai_service import AIService
from app.services.context_service import ContextService
from app.services.cache_service import cache_service
from app.services.security_service import filter_input
from app.services.verifier_service import VerifierService
from app.middleware import get_disclaimer

logger = logging.getLogger(__name__)

# 全局存储正在进行的生成任务
_active_generations = {}  # {message_id: {thread, content, stop_event, status}}


def register_handlers(socketio, app):
    """注册 WebSocket 事件处理器"""

    @socketio.on('connect')
    def handle_connect():
        """客户端连接"""
        logger.info(f"WebSocket 客户端已连接: {request.sid}")
        emit('connected', {'status': 'connected', 'sid': request.sid})

    @socketio.on('disconnect')
    def handle_disconnect():
        """客户端断开连接（后台生成继续）"""
        logger.info(f"WebSocket 客户端已断开: {request.sid}")

    @socketio.on('join')
    def handle_join(data):
        """加入对话房间"""
        conv_id = data.get('conversation_id')
        if conv_id:
            room = f"conv_{conv_id}"
            join_room(room)
            logger.info(f"客户端 {request.sid} 加入房间: {room}")

            # 检查是否有正在进行的生成任务，如果有则恢复
            with app.app_context():
                last_msg = Message.query.filter_by(
                    conversation_id=int(conv_id),
                    role='assistant',
                    status='generating'
                ).order_by(Message.id.desc()).first()

                if last_msg and last_msg.id in _active_generations:
                    gen_info = _active_generations[last_msg.id]
                    if gen_info['status'] == 'generating':
                        emit('generation_resume', {
                            'message_id': last_msg.id,
                            'content': gen_info['content']
                        })

    @socketio.on('leave')
    def handle_leave(data):
        """离开对话房间"""
        conv_id = data.get('conversation_id')
        if conv_id:
            room = f"conv_{conv_id}"
            leave_room(room)
            logger.info(f"客户端 {request.sid} 离开房间: {room}")

    @socketio.on('chat_message')
    def handle_chat_message(data):
        """处理聊天消息：创建消息记录 + 启动后台生成线程"""
        conv_id = data.get('conversation_id')
        content = data.get('content', '').strip()
        model = data.get('model')
        image_urls = data.get('image_urls', [])

        if not conv_id or not content:
            emit('error', {'message': '缺少必要参数'})
            return

        with app.app_context():
            # 输入安全过滤
            is_safe, filtered_text, warning = filter_input(content)
            if not is_safe:
                user_msg = Message(
                    conversation_id=int(conv_id), role='user',
                    content=content, image_urls=image_urls, status='completed'
                )
                db.session.add(user_msg)
                assistant_msg = Message(
                    conversation_id=int(conv_id), role='assistant',
                    content=f"⚠️ {warning}\n\n为了安全起见，我无法处理包含潜在注入指令的输入。请重新描述你的问题。",
                    status='completed'
                )
                db.session.add(assistant_msg)
                db.session.commit()
                emit('message_created', {
                    'message_id': assistant_msg.id,
                    'user_message_id': user_msg.id,
                    'status': 'completed'
                })
                emit('generation_completed', {
                    'message_id': assistant_msg.id,
                    'content': assistant_msg.content
                })
                return

            # 创建用户消息
            user_msg = Message(
                conversation_id=int(conv_id),
                role='user',
                content=content,
                image_urls=image_urls,
                status='completed'
            )
            db.session.add(user_msg)

            # 创建助手消息（空内容，状态为 generating）
            assistant_msg = Message(
                conversation_id=int(conv_id),
                role='assistant',
                content='',
                status='generating'
            )
            db.session.add(assistant_msg)
            db.session.commit()

            msg_id = assistant_msg.id

            # 更新对话时间
            conv = db.session.get(Conversation, int(conv_id))
            if conv:
                conv.updated_at = db.func.now()
                db.session.commit()

            # 自动生成标题（第一条消息）
            user_msg_count = Message.query.filter_by(
                conversation_id=int(conv_id), role='user'
            ).count()
            if user_msg_count == 1:
                try:
                    from app.routes.chat import _auto_title
                    _auto_title(int(conv_id), content)
                except Exception as e:
                    logger.warning(f"自动生成标题失败: {e}")

            # 通知客户端消息已创建
            emit('message_created', {
                'message_id': msg_id,
                'user_message_id': user_msg.id,
                'status': 'generating'
            })

            # 启动后台生成任务（使用 socketio.start_background_task 确保 WebSocket 事件能正常推送）
            room = f"conv_{conv_id}"
            stop_event = threading.Event()
            
            # 使用 socketio.start_background_task 启动后台任务
            from app import socketio
            socketio.start_background_task(
                generate_ai_response,
                app, int(conv_id), msg_id, content, model, image_urls, room, stop_event
            )

            # 记录生成任务
            _active_generations[msg_id] = {
                'content': '',
                'stop_event': stop_event,
                'status': 'generating'
            }

            logger.info(f"启动生成任务: message_id={msg_id}, conversation_id={conv_id}")

    @socketio.on('stop_generation')
    def handle_stop_generation(data):
        """停止生成 — 只设置 stop_event，不直接操作数据库。
        数据库保存和事件通知由 generate_ai_response 线程统一处理，
        避免双重写入和双重事件。"""
        msg_id = data.get('message_id')
        if msg_id and msg_id in _active_generations:
            gen_info = _active_generations[msg_id]
            gen_info['stop_event'].set()
            logger.info(f"已请求停止生成: message_id={msg_id}")


def generate_ai_response(app, conv_id, msg_id, user_content, model, image_urls, room, stop_event):
    """后台生成 AI 回复（独立线程，前端断开不影响）"""
    with app.app_context():
        try:
            # 1. 构建上下文
            max_tokens = current_app.config.get("MAX_CONTEXT_TOKENS", 4000)
            ctx_service = ContextService(max_tokens=max_tokens)

            # 上下文压缩检查
            ai_svc = AIService(model=model)
            if ctx_service.should_compress(conv_id):
                ctx_service.compress_context(conv_id, ai_svc)

            messages = ctx_service.build_context(conv_id)
            if not messages:
                messages = [{"role": "user", "content": user_content}]

            # 2. 检查缓存
            cache_enabled = current_app.config.get("CACHE_ENABLED", False)
            context_hash = None
            if cache_enabled:
                from app.services.cache_service import hash_context
                context_hash = hash_context(messages)
                cached = cache_service.get(user_content, context_hash)
                if cached:
                    _send_token(room, msg_id, cached)
                    _finish_generation(msg_id, cached, room, [], user_content=user_content)
                    return

            # 3. 流式生成 AI 回复
            full_content = ''
            last_save_len = 0
            tool_calls_log = []

            def on_chunk(text):
                nonlocal full_content, last_save_len
                full_content += text
                if msg_id in _active_generations:
                    _active_generations[msg_id]['content'] = full_content
                # 实时保存到数据库（每 2000 字符保存一次）
                if len(full_content) - last_save_len >= 2000:
                    _save_progress(msg_id, full_content)
                    last_save_len = len(full_content)

            def on_tool_call(tc, result):
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
                _send_tool_calls(room, msg_id, [tool_info])

            # 使用 AIService 生成
            ai = AIService(model=model)
            for token in ai.stream_response(
                messages,
                on_chunk=on_chunk,
                on_tool_call=on_tool_call,
                stop_event=stop_event,
                conversation_id=conv_id
            ):
                if stop_event.is_set():
                    break
                _send_token(room, msg_id, token)

            # 4. 统一处理完成/停止（所有数据库操作和事件通知都在这里）
            if stop_event.is_set():
                final_content = full_content or '[已停止]'
                _finish_generation(msg_id, final_content, room, tool_calls_log,
                                   interrupted=True, user_content=user_content)
            else:
                # 添加免责声明
                disclaimer = get_disclaimer()
                if disclaimer and disclaimer.strip() not in full_content:
                    full_content += f"\n\n{disclaimer}"
                    _send_token(room, msg_id, f"\n\n{disclaimer}")

                # 正常完成（含结果验证）
                _finish_generation(msg_id, full_content, room, tool_calls_log,
                                   interrupted=False, user_content=user_content,
                                   context_hash=context_hash, cache_enabled=cache_enabled)

            logger.info(f"生成完成: message_id={msg_id}, 内容长度={len(full_content)}")

        except Exception as e:
            logger.error(f"生成失败: {e}", exc_info=True)
            _error_generation(msg_id, str(e), room)


def _finish_generation(msg_id, content, room, tool_calls_log, interrupted=False,
                       user_content=None, context_hash=None, cache_enabled=False):
    """统一的生成完成处理：保存数据库 + 结果验证 + 通知客户端。
    无论是正常完成、被中断、还是出错，都只调用此函数一次。"""
    from app import socketio

    # 更新全局状态
    status = 'stopped' if interrupted else 'completed'
    if msg_id in _active_generations:
        _active_generations[msg_id]['status'] = status

    # 保存到数据库
    try:
        msg = db.session.get(Message, msg_id)
        if msg:
            msg.content = content
            msg.status = status
            msg.interrupted = interrupted
            msg.tool_calls = tool_calls_log or []
            ai = AIService()
            msg.token_count = ai.estimate_tokens(content)
            db.session.commit()

            conv = db.session.get(Conversation, msg.conversation_id)
            if conv:
                conv.updated_at = db.func.now()
                db.session.commit()
    except Exception as e:
        logger.error(f"保存生成结果失败: {e}")
        db.session.rollback()

    # 结果验证（仅正常完成时）
    if not interrupted and current_app.config.get("VERIFY_ENABLED", False):
        try:
            socketio.emit('verifying', {
                'message_id': msg_id
            }, room=room)

            verifier = VerifierService()
            verify_result = verifier.verify_answer(
                question=user_content or "",
                answer=content,
            )
            if verify_result.get("status") != "skipped":
                msg = db.session.get(Message, msg_id)
                if msg:
                    msg.verification = verify_result
                    db.session.commit()

            socketio.emit('verified', {
                'message_id': msg_id,
                'verification': verify_result
            }, room=room)
        except Exception as verify_err:
            logger.warning(f"结果验证异常: {verify_err}")
            socketio.emit('verified', {
                'message_id': msg_id,
                'verification': {'status': 'skipped'}
            }, room=room)

    # 写入缓存（仅正常完成、无工具调用时）
    if not interrupted and cache_enabled and not tool_calls_log:
        try:
            cache_service.set(user_content, content, context_hash, ttl_hours=1)
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    # 通知客户端最终状态
    if interrupted:
        socketio.emit('generation_stopped', {
            'message_id': msg_id,
            'content': content
        }, room=room)
    else:
        socketio.emit('generation_completed', {
            'message_id': msg_id,
            'content': content
        }, room=room)

    # 延迟清理全局状态（给客户端时间接收事件）
    def cleanup():
        import eventlet
        eventlet.sleep(10)
        _active_generations.pop(msg_id, None)

    from app import socketio
    socketio.start_background_task(cleanup)


# ========== 辅助函数 ==========

def _send_token(room, msg_id, token):
    """发送 token 给房间内的所有客户端"""
    from app import socketio
    socketio.emit('token', {
        'message_id': msg_id,
        'token': token
    }, room=room)
    # 让出控制权给 eventlet 事件循环，确保事件被发送
    import eventlet
    eventlet.sleep(0)


def _send_tool_calls(room, msg_id, tool_calls):
    """发送工具调用信息给客户端"""
    from app import socketio
    socketio.emit('tool_calls', {
        'message_id': msg_id,
        'tool_calls': tool_calls
    }, room=room)


def _save_progress(msg_id, content):
    """保存生成进度到数据库"""
    try:
        msg = db.session.get(Message, msg_id)
        if msg:
            msg.content = content
            msg.status = 'generating'
            db.session.commit()
    except Exception as e:
        logger.error(f"保存进度失败: {e}")
        db.session.rollback()


def _error_generation(msg_id, error, room):
    """生成失败"""
    from app import socketio

    if msg_id in _active_generations:
        _active_generations[msg_id]['status'] = 'error'

    try:
        msg = db.session.get(Message, msg_id)
        if msg:
            msg.status = 'error'
            msg.content = f"[生成失败: {error}]"
            db.session.commit()
    except Exception as e:
        logger.error(f"保存错误状态失败: {e}")
        db.session.rollback()

    socketio.emit('generation_error', {
        'message_id': msg_id,
        'error': '回复失败，请重试'
    }, room=room)

    def cleanup():
        import time
        time.sleep(10)
        _active_generations.pop(msg_id, None)

    cleanup_thread = threading.Thread(target=cleanup)
    cleanup_thread.daemon = True
    cleanup_thread.start()
