from flask import Flask
from flask_cors import CORS
from app.config import Config
from app.extensions import db
from app.routes.chat import chat_bp


def create_app():
    app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
    app.config.from_object(Config)

    CORS(app)
    db.init_app(app)

    app.register_blueprint(chat_bp)

    with app.app_context():
        db.create_all()

    return app
