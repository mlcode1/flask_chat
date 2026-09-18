from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# 加载环境变量（确保 LangSmith 等配置在任何其他导入前加载）
load_dotenv()

from app.config import Config
from app.extensions import db
from app.models import CodeRepository, IndexedFile  # 导入新模型
from app.routes.chat import chat_bp
from app.routes.rag import rag_bp
from app.routes.code_index import code_index_bp


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

    return app
