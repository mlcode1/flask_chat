from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv
import json
import logging
import atexit

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


def _start_mcp_init_background(app, sock):
    """在后台连接 MCP 服务器，不阻塞服务端口监听。

    背景：MCP 服务器（尤其 stdio 类型）要靠 npx/uvx 拉起子进程并解析依赖，
    正常也要几秒；网络不通时 npm/uv 会把重试预算烧满，单个服务器最坏卡到
    30s（client_manager.connect 的轮询上限）。原先这段在 create_app() 主流程
    里同步执行，端口 8080 要等它全部连完才开始监听，表现为"服务启动很慢"。

    改用 socketio.start_background_task（eventlet green thread）后台连接：
    端口立即可用，MCP 工具在各自连接完成后才逐步出现在工具列表里。
    get_tools() 本就只列已连接的服务器、绝不触发连接，所以这个时间窗是安全的。
    """
    def _init():
        # 后台任务没有请求上下文，需显式推 app context ——
        # build_effective_configs / update_runtime_state 都要读写数据库。
        with app.app_context():
            try:
                from app.services import mcp_service

                # 合并 .env 配置与数据库配置（数据库优先）。
                # .env 中的服务器会同步一份入库（source='env'），
                # 以便在管理界面统一查看与启停。
                effective = mcp_service.build_effective_configs(
                    app.config.get('MCP_SERVERS_CONFIG', {})
                )

                if not effective:
                    logger.info("MCP 已启用但无启用的服务器配置")
                    return

                mcp_manager = get_mcp_manager()
                results = mcp_manager.connect_all_sync(effective)
                connected = mcp_manager.get_connected_servers()
                failed = [n for n, ok in results.items() if not ok]

                # 回写运行时状态，供管理界面展示
                for name, ok in results.items():
                    tools_count = (
                        len(mcp_manager.servers[name].tools)
                        if ok and name in mcp_manager.servers else 0
                    )
                    mcp_service.update_runtime_state(
                        name,
                        status='connected' if ok else 'failed',
                        tools_count=tools_count,
                        error_message=None if ok else '启动时连接失败，可在界面点「重连」'
                    )

                if failed:
                    logger.warning(f"MCP 部分服务器连接失败: {failed}")
                if connected:
                    logger.info(f"MCP 系统已初始化，连接了 {len(connected)} 个服务器: {connected}")
                else:
                    logger.warning("MCP 已启用但所有服务器均连接失败（配置已保留，可稍后重连）")
            except Exception as e:
                logger.error(f"Failed to initialize MCP system: {e}", exc_info=True)

    sock.start_background_task(_init)
    logger.info("MCP 初始化已转入后台（端口立即可用，工具连接完成后陆续就绪）")


def create_app(config_override=None):
    """创建 Flask 应用。

    Args:
        config_override: 可选的配置类（如 TestingConfig）。
            必须在 db.init_app() 之前注入 —— SQLAlchemy 的 engine 在
            init_app 时即根据 SQLALCHEMY_DATABASE_URI 绑定，之后再修改
            app.config 不会重建 engine，会导致配置覆盖失效。
    """
    app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
    app.config.from_object(Config)

    # 关键：在 db.init_app 之前覆盖配置，否则 engine 已绑定默认库
    if config_override is not None:
        app.config.from_object(config_override)

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

        # MCP 客户端初始化不在此处执行 —— 见 _start_mcp_init_background()，
        # 在 socketio.init_app() 之后以 background task 启动，避免阻塞端口监听。

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

    # 注入 sse SSRF 白名单与超时配置到 client_manager（模块级变量）。
    # ⚠️ 必须在 _start_mcp_init_background 之前 —— 后台连接会对每个 sse URL
    #    做 SSRF 复检、并按这里的超时值建连，读取的正是这里注入的配置。
    # 为什么用注入而不是在 client_manager 里读 current_app：MCP 连接跑在专用
    # 事件循环线程上，那个线程没有 Flask app context，读 current_app 必然
    # RuntimeError（与 configure_sse_guard 同一个原因）。
    from app.mcp.client_manager import configure_sse_guard, configure_mcp_timeouts
    configure_sse_guard(app.config.get('MCP_SSE_ALLOWED_HOSTS'))
    configure_mcp_timeouts(
        connect=app.config.get('MCP_CONNECT_TIMEOUT'),
        sse_http=app.config.get('MCP_SSE_HTTP_TIMEOUT'),
        sse_read=app.config.get('MCP_SSE_READ_TIMEOUT'),
    )

    # 启动 MCP 后台初始化（不阻塞端口监听）
    if app.config.get('MCP_ENABLED', False):
        _start_mcp_init_background(app, socketio)

    # 注册退出清理钩子
    def cleanup():
        try:
            mcp_manager = get_mcp_manager()
            if mcp_manager:
                mcp_manager.disconnect_all_sync()
                logger.info("MCP 客户端已清理")
        except Exception as e:
            logger.warning(f"退出清理时 MCP 清理失败: {e}")
    
    atexit.register(cleanup)

    return app
