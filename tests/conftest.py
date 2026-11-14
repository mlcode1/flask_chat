"""
Pytest configuration and shared fixtures

⚠️ 安全须知：本文件所有 fixture 均带多重防护，确保测试绝不触碰生产数据库。

历史事故：旧版 conftest 在 `create_app()` 之后才修改 app.config['SQLALCHEMY_DATABASE_URI']，
但 SQLAlchemy 的 engine 在 create_app 内部的 db.init_app() 时就已绑定生产库，
配置覆盖成为死代码 —— 测试直连生产库并执行 drop_all()，清空了全部业务数据。

修复要点：
  1. 使用 TestingConfig 并通过 create_app(config_override=...) 在 init_app 之前注入
  2. 测试库必须是 PostgreSQL（pgvector 的 Vector 类型 SQLite 无法建表）
  3. 三处 URI 校验，drop_all() 前再验一次

以下防护机制不可随意删改。
"""
import pytest
import tempfile

# 注意：此处只 import 配置类，不 import create_app。
# app.config 在 import 时读取环境变量并固化类属性，
# 必须靠 TestingConfig 显式注入，而非依赖环境变量时序。
from app.config import TestingConfig
from app.extensions import db as _db


class DatabaseSafetyError(RuntimeError):
    """测试即将触碰生产数据库时抛出。"""


def _assert_not_production(uri: str, stage: str) -> None:
    """断言连接串不是生产库。任一规则命中即拒绝执行。

    Args:
        uri: 待校验的数据库连接串
        stage: 当前所处阶段，用于错误信息定位
    """
    prod_name = TestingConfig.PRODUCTION_DATABASE_NAME
    db_name = uri.rpartition("/")[2].partition("?")[0]

    if prod_name and db_name == prod_name:
        raise DatabaseSafetyError(
            f"[{stage}] 拒绝执行：测试连接串指向生产库 '{prod_name}'。\n"
            f"  当前 URI: {uri}\n"
            f"  请检查 TestingConfig.SQLALCHEMY_DATABASE_URI 或 .env 中的 TEST_DATABASE_URL。"
        )

    if not db_name.endswith("_test"):
        raise DatabaseSafetyError(
            f"[{stage}] 拒绝执行：测试库名 '{db_name}' 不含 '_test' 后缀。\n"
            f"  当前 URI: {uri}\n"
            f"  为防止误删生产数据，测试库名必须以 '_test' 结尾。"
        )

    if "sqlite" in uri.lower():
        raise DatabaseSafetyError(
            f"[{stage}] 拒绝执行：测试库不能是 SQLite。\n"
            f"  当前 URI: {uri}\n"
            f"  models.DocumentChunk.embedding 使用 pgvector 的 Vector(4096)，"
            f"SQLite 无法创建该列。"
        )


@pytest.fixture(scope="session")
def app():
    """Create application for testing.

    通过 config_override 在 db.init_app() 之前注入 TestingConfig，
    确保 engine 从一开始就绑定测试库。
    """
    from app import create_app

    _assert_not_production(TestingConfig.SQLALCHEMY_DATABASE_URI, "app fixture")

    application = create_app(config_override=TestingConfig)
    application.config["TESTING"] = True

    # 校验 Flask app 实际生效的 URI（防止 config_override 未生效）
    _assert_not_production(application.config["SQLALCHEMY_DATABASE_URI"], "app fixture (effective)")

    yield application


@pytest.fixture(scope="function")
def db(app):
    """Create database schema for a single test, drop it afterwards.

    drop_all() 前再次校验 URI —— 防止生产数据被删的最后防线。
    """
    with app.app_context():
        _assert_not_production(app.config["SQLALCHEMY_DATABASE_URI"], "db.create_all")

        _db.create_all()
        try:
            yield _db
        finally:
            _db.session.rollback()
            # 关键：释放 scoped_session，避免残留状态污染下一个测试。
            # 缺少这一步会导致后续测试复用已关闭/已回滚的 session，
            # 表现为诡异的 NotNullViolation（外键字段变 null）等错误。
            _db.session.remove()
            # 删除前再验一次：配置若在测试期间被篡改则拒绝执行
            _assert_not_production(app.config["SQLALCHEMY_DATABASE_URI"], "db.drop_all")
            _db.drop_all()


@pytest.fixture(autouse=True)
def _restore_global_config(app):
    """恢复被 /api/config/* 接口篡改的进程级配置。

    app fixture 是 session 级，而 update_verify_config / update_tools_config /
    update_disclaimer_config 修改的是 current_app.config（进程级全局），
    不还原会导致配置修改跨测试泄漏、产生顺序依赖。
    """
    watched = (
        "VERIFY_ENABLED",
        "KNOWLEDGE_SEARCH_ENABLED",
        "CODE_INDEX_ENABLED",
        "AI_DISCLAIMER_TEXT",
    )
    with app.app_context():
        snapshot = {k: app.config.get(k) for k in watched}

    yield

    with app.app_context():
        for k, v in snapshot.items():
            app.config[k] = v


@pytest.fixture(scope="function")
def client(app, db):
    """Create test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def test_user(app, db):
    """Create a **non-admin** test user and return (user, token).

    多数 API 走 login_required / get_current_user()，无 JWT 时返回 401，
    因此需要此 fixture 提供已认证用户。
    is_admin 保持默认 False，用于验证普通用户会被 admin_required 拒绝（403）。
    """
    from app.models import User
    from app.services.auth_service import generate_token

    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        user.set_password("testpass123")
        db.session.add(user)
        db.session.commit()

        token = generate_token(user.id)
        yield user, token

        db.session.remove()


@pytest.fixture(scope="function")
def admin_user(app, db):
    """Create an **admin** test user and return (user, token).

    用于验证 admin_required 放行的正向路径。
    """
    from app.models import User
    from app.services.auth_service import generate_token

    with app.app_context():
        user = User(
            username="adminuser",
            email="admin@example.com",
            is_admin=True,          # 关键区别
        )
        user.set_password("adminpass123")
        db.session.add(user)
        db.session.commit()

        token = generate_token(user.id)
        yield user, token

        db.session.remove()


def _make_authed_client(client, token):
    """构造自动注入 Authorization 头的客户端薄封装。

    auth_client / admin_client 共用，避免重复实现。
    """

    class AuthedClient:
        def _headers(self, kwargs):
            headers = dict(kwargs.pop("headers", None) or {})
            headers["Authorization"] = f"Bearer {token}"
            kwargs["headers"] = headers
            return kwargs

        def get(self, *a, **kw):
            return client.get(*a, **self._headers(kw))

        def post(self, *a, **kw):
            return client.post(*a, **self._headers(kw))

        def patch(self, *a, **kw):
            return client.patch(*a, **self._headers(kw))

        def put(self, *a, **kw):
            return client.put(*a, **self._headers(kw))

        def delete(self, *a, **kw):
            return client.delete(*a, **self._headers(kw))

    return AuthedClient()


@pytest.fixture(scope="function")
def auth_client(app, db, test_user):
    """普通（非管理员）已登录客户端。

    用法：auth_client.get('/api/conversations')
    访问 admin_required 接口应得 403。
    """
    user, token = test_user
    yield _make_authed_client(app.test_client(), token)


@pytest.fixture(scope="function")
def admin_client(app, db, admin_user):
    """管理员已登录客户端。

    用法：admin_client.post('/api/cache/clear')
    访问 admin_required 接口应得 200。
    """
    user, token = admin_user
    yield _make_authed_client(app.test_client(), token)


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
