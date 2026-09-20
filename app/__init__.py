from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv

# 加载环境变量（确保 LangSmith 等配置在任何其他导入前加载）
load_dotenv()

from app.config import Config
from app.extensions import db
from app.models import CodeRepository, IndexedFile, Message  # 导入新模型
from app.routes.chat import chat_bp
from app.routes.rag import rag_bp
from app.routes.code_index import code_index_bp

# 全局 SocketIO 实例
socketio = SocketIO()


def create_app():
    app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
    app.config.from_object(Config)

    CORS(app)
    db.init_app(app)

    app.register_blueprint(chat_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(code_index_bp)

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
