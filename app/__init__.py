from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# 加载环境变量（确保 LangSmith 等配置在任何其他导入前加载）
load_dotenv()

from app.config import Config
from app.extensions import db
from app.routes.chat import chat_bp
from app.routes.rag import rag_bp


def create_app():
    app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
    app.config.from_object(Config)

    CORS(app)
    db.init_app(app)

    app.register_blueprint(chat_bp)
    app.register_blueprint(rag_bp)

    with app.app_context():
        db.session.execute(db.text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.create_all()

    return app
