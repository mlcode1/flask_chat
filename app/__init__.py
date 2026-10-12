from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv
import json
import logging

# 加载环境变量（确保 LangSmith 等配置在任何其他导入前加载）
load_dotenv()

from app.config import Config
from app.extensions import db
from app.models import CodeRepository, IndexedFile, Message, User, ConversationTemplate
from app.routes.chat import chat_bp
from app.routes.rag import rag_bp
from app.routes.code_index import code_index_bp
from app.routes.auth import auth_bp
from app.routes.template import template_bp
from app.routes.webhook import webhook_bp
from app.routes.agent import agent_bp
from app.routes.speech import speech_bp
from app.routes.skills import skills_bp
from app.errors import register_error_handlers
from app.services.cache_service import init_cache_service
from app.logging_config import setup_logging, log_request_start, log_request_end
from app import monitoring
from app.services.tool_service import get_skill_loader, get_mcp_manager

logger = logging.getLogger(__name__)

# 全局 SocketIO 实例
socketio = SocketIO()


def create_app():
    app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
    app.config.from_object(Config)

    CORS(app)
    db.init_app(app)
    
    # 初始化结构化日志
    setup_logging(app)
    
    # Register global error handlers
    register_error_handlers(app)

    app.register_blueprint(chat_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(code_index_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(template_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(speech_bp)
    app.register_blueprint(skills_bp)
    
    # 注册请求追踪钩子
    @app.before_request
    def before_request():
        log_request_start()
    
    @app.after_request
    def after_request(response):
        return log_request_end(response)

    # 初始化性能监控
    monitoring.init_app(app)

    with app.app_context():
        db.session.execute(db.text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.create_all()

        # 迁移：给 messages 表添加 status 列（如果不存在）
        try:
            result = db.session.execute(db.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='messages' AND column_name='status'"
            )).fetchone()
            if not result:
                db.session.execute(db.text(
                    "ALTER TABLE messages ADD COLUMN status VARCHAR(20) DEFAULT 'completed'"
                ))
                db.session.commit()
                print("✅ 已为 messages 表添加 status 列")
        except Exception as e:
            print(f"⚠️ messages 表 status 列迁移检查失败: {e}")
            db.session.rollback()

        # 程序启动时，将所有残留的 indexing 状态重置为 pending
        # 防止上次异常退出导致前端无限轮询
        try:
            stale_repos = CodeRepository.query.filter_by(status='indexing').all()
            if stale_repos:
                for repo in stale_repos:
                    repo.status = 'pending'
                    repo.progress = 0
                    repo.progress_message = None
                db.session.commit()
                print(f"✅ 已重置 {len(stale_repos)} 个残留的索引任务状态为 pending")
        except Exception as e:
            print(f"⚠️ 清理残留索引状态失败: {e}")
            db.session.rollback()

        # 程序启动时，将所有残留的 generating 消息标记为 error
        try:
            stale_msgs = Message.query.filter_by(status='generating').all()
            if stale_msgs:
                for m in stale_msgs:
                    m.status = 'error'
                    if not m.content or not m.content.strip():
                        m.content = '[服务重启，生成中断]'
                db.session.commit()
                print(f"✅ 已重置 {len(stale_msgs)} 条残留的 generating 消息状态")
        except Exception as e:
            print(f"⚠️ 清理残留消息状态失败: {e}")
            db.session.rollback()

        # 初始化缓存服务
        init_cache_service()

        # 初始化 Skill 系统
        if app.config.get('SKILLS_ENABLED', True):
            try:
                skill_loader = get_skill_loader()
                skill_loader.load_all_skills()
                print(f"✅ Skill 系统已初始化，加载了 {len(skill_loader.skills)} 个技能")
            except Exception as e:
                print(f"⚠️ Skill 系统初始化失败: {e}")
                logger.error(f"Failed to initialize skill system: {e}", exc_info=True)

        # 初始化 MCP 客户端
        if app.config.get('MCP_ENABLED', False):
            try:
                mcp_servers_config = app.config.get('MCP_SERVERS_CONFIG', {})
                if mcp_servers_config:
                    mcp_manager = get_mcp_manager()
                    # 在应用上下文中连接 MCP 服务器
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(mcp_manager.connect_all(mcp_servers_config))
                        connected = mcp_manager.get_connected_servers()
                        print(f"✅ MCP 系统已初始化，连接了 {len(connected)} 个服务器")
                    finally:
                        loop.close()
                else:
                    print("ℹ️ MCP 已启用但未配置服务器")
            except Exception as e:
                print(f"⚠️ MCP 系统初始化失败: {e}")
                logger.error(f"Failed to initialize MCP system: {e}", exc_info=True)

        # 创建默认对话模板
        from app.services.template_service import create_default_templates
        create_default_templates()

    # 初始化 SocketIO
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode='eventlet',  # 使用 eventlet 支持真正的 WebSocket
        logger=False,
        engineio_logger=False
    )

    # 注册 WebSocket 事件处理器
    from app import websocket
    websocket.register_handlers(socketio, app)

    return app
