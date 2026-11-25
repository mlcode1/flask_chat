"""AI 免责声明的数据源一致性测试

覆盖的缺陷：Config 类此前**未定义** AI_DISCLAIMER_TEXT，而
  - routes/chat.py 的 GET/POST 接口读写 current_app.config
  - middleware._build_disclaimer() 读 os.getenv
两边不是同一份数据。后果是：管理员在界面改免责声明，POST 返回成功、
GET 也显示新值，但实际拼进 AI 回复的文案纹丝不动 —— 一个界面上完全
看不出来的静默失效。

修复后 config 是唯一数据源，middleware 通过 has_app_context() 读 config，
无上下文时才退回 env（避免后台线程 RuntimeError）。
"""
import os

import pytest

from app.middleware import _build_disclaimer, get_disclaimer


class TestDisclaimerSingleSource:
    """middleware 必须与 config 同源，改 config 要立刻生效。"""

    def test_config_defines_the_key(self, app):
        """回归防护：Config 类必须定义 AI_DISCLAIMER_TEXT。

        此前正是因为这里没定义，config.get() 恒返回默认值，
        而 middleware 走 os.getenv，两边彻底脱节。
        """
        from app.config import Config

        assert hasattr(Config, 'AI_DISCLAIMER_TEXT'), (
            "Config 未定义 AI_DISCLAIMER_TEXT —— 三源不一致的根因又回来了"
        )

    def test_middleware_reflects_config_change(self, app):
        """核心断言：改 config 后 middleware 立刻产出新文案。

        这正是原来坏掉的行为 —— 改 config 对 middleware 毫无影响。
        """
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = '来自配置的声明文本'
            out = _build_disclaimer()

        assert '来自配置的声明文本' in out

    def test_middleware_reflects_runtime_update(self, app):
        """模拟管理界面 POST 的写入方式，验证端到端一致。"""
        with app.app_context():
            # routes/chat.py:170 就是这么写的
            app.config['AI_DISCLAIMER_TEXT'] = '第一次设置'
            assert '第一次设置' in get_disclaimer()

            app.config['AI_DISCLAIMER_TEXT'] = '第二次修改'
            out = get_disclaimer()
            assert '第二次修改' in out
            assert '第一次设置' not in out, "旧文案未被替换 —— 存在缓存或读了陈旧数据源"

    def test_empty_config_yields_empty_disclaimer(self, app):
        """未配置时不产生任何片段（不能输出空的 hr/div 结构）。"""
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = ''
            assert _build_disclaimer() == ''

        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = None
            assert _build_disclaimer() == ''

    def test_whitespace_only_is_treated_as_empty(self, app):
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = '   \n  '
            assert _build_disclaimer() == ''

    def test_env_does_not_override_config(self, app, monkeypatch):
        """有 app context 时 config 优先，env 不得盖过运行时修改。

        原来 middleware 只读 env，所以管理员的运行时修改永远无效。
        """
        monkeypatch.setenv('AI_DISCLAIMER_TEXT', '环境变量里的旧文案')
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = '运行时改过的新文案'
            out = _build_disclaimer()

        assert '运行时改过的新文案' in out
        assert '环境变量里的旧文案' not in out


class TestDisclaimerEscaping:
    """免责声明会拼进所有用户的回复，必须转义。"""

    def test_html_is_escaped(self, app):
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = '<script>alert(1)</script>'
            out = _build_disclaimer()

        assert '<script>' not in out
        assert '&lt;script&gt;' in out

    def test_ampersand_is_escaped(self, app):
        with app.app_context():
            app.config['AI_DISCLAIMER_TEXT'] = 'A & B'
            out = _build_disclaimer()

        assert 'A &amp; B' in out


class TestDisclaimerWithoutAppContext:
    """无 app context 时必须降级到 env，而不是抛 RuntimeError。

    middleware 可能被后台线程调用，直接读 current_app 会炸 ——
    这是 MCP 那次踩过的同类坑（跨线程无 Flask 上下文）。
    """

    def test_falls_back_to_env_without_context(self, monkeypatch):
        monkeypatch.setenv('AI_DISCLAIMER_TEXT', '无上下文时的降级文案')
        # 不进入 app_context
        out = _build_disclaimer()
        assert '无上下文时的降级文案' in out

    def test_no_exception_without_context(self, monkeypatch):
        """即便 env 也没设，也只能返回空串，不得抛异常。"""
        monkeypatch.delenv('AI_DISCLAIMER_TEXT', raising=False)
        assert _build_disclaimer() == ''


class TestDisclaimerApiRoundTrip:
    """接口层：POST 写入后 GET 读到的必须一致。"""

    def test_post_then_get_returns_same_text(self, admin_client):
        new_text = '接口写入的免责声明'
        post = admin_client.post(
            '/api/config/disclaimer', json={'text': new_text}
        )
        assert post.status_code == 200, post.get_json()
        assert post.get_json()['text'] == new_text

        got = admin_client.get('/api/config/disclaimer')
        assert got.status_code == 200
        assert got.get_json()['text'] == new_text

    def test_posted_text_reaches_middleware(self, admin_client, app):
        """端到端：接口写入 → middleware 实际使用。

        这条是原缺陷的完整复现路径 —— 以前这一步必然失败。
        """
        admin_client.post(
            '/api/config/disclaimer', json={'text': '端到端验证文案'}
        )
        with app.app_context():
            out = _build_disclaimer()

        assert '端到端验证文案' in out

    def test_post_requires_admin(self, auth_client):
        """免责声明会拼进所有用户的回复，必须限管理员。"""
        resp = auth_client.post(
            '/api/config/disclaimer', json={'text': '普通用户想改'}
        )
        assert resp.status_code == 403

    def test_post_rejects_non_string(self, admin_client):
        resp = admin_client.post(
            '/api/config/disclaimer', json={'text': 123}
        )
        assert resp.status_code == 400

    def test_post_strips_whitespace(self, admin_client):
        resp = admin_client.post(
            '/api/config/disclaimer', json={'text': '  带空白的文案  '}
        )
        assert resp.get_json()['text'] == '带空白的文案'
