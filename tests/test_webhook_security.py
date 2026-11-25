"""Webhook 路由的安全测试

覆盖两个此前存在的缺陷：
  1. /api/webhooks/trigger 漏加 @require_api_key —— 同文件其余 4 个路由都有，
     唯独这个入站接口裸奔。它会创建对话并消耗 LLM 额度，未认证暴露等于免费算力入口。
  2. register_webhook 的 url 无 SSRF 校验 —— 该 url 会入库，对话完成时由
     webhook_service.send_completion_webhook 发起 requests.post，
     构成有服务端出口通道的 SSRF（可读云元数据 / 探本机端口）。

⚠️ require_api_key 在 API_KEY 为空时**直接放行**（security_service.py:22-24），
   所以认证类用例必须显式设置 app.config['API_KEY']，否则测的是"空转放行"路径，
   断言会假通过。API_KEY 已加入 conftest._restore_global_config 的 watched 列表，
   用例结束后自动还原，不会跨用例泄漏。

不真正发起 HTTP 回调：只验证路由层的准入与校验，send_completion_webhook
不在这些用例的执行路径上。
"""
import pytest

from app.services import webhook_service


TRIGGER_URL = '/api/webhooks/trigger'
REGISTER_URL = '/api/webhooks'

# 内网 / 特殊地址：必须被 SSRF 校验拒绝
INTERNAL_URLS = [
    'http://127.0.0.1:6379/probe',        # 本机 Redis
    'http://169.254.169.254/latest/meta-data/',  # 云厂商元数据（最高价值目标）
    'http://10.0.0.5/hook',               # 内网 A 类
    'http://192.168.1.1/hook',            # 内网 C 类
    'http://[::1]/hook',                  # IPv6 环回
    'http://[::ffff:127.0.0.1]/hook',     # IPv4-mapped IPv6 绕过手法
    'file:///etc/passwd',                 # 非 http 协议
    'http://metadata.example/hook',       # 域名解析到 169.254.169.254
    'http://internal.example/hook',       # 域名解析到 10.0.0.7
    'http://rebind.example/hook',         # 域名解析到 127.0.0.1
]

# 用 conftest.stub_dns 登记过的公网域名，不走真实 DNS
PUBLIC_URL = 'https://example.com/notify'


@pytest.fixture
def api_key_enabled(app):
    """显式启用 API Key 认证。

    不设这个 fixture 的话 require_api_key 走"API_KEY 为空则跳过"分支，
    认证测试形同虚设。
    """
    app.config['API_KEY'] = 'test-secret-key'
    yield 'test-secret-key'


def _auth_headers(key):
    return {'X-API-Key': key}


class TestTriggerAuthentication:
    """/trigger 必须受 API Key 保护。"""

    def test_trigger_requires_api_key(self, client, api_key_enabled):
        """未带 key 的入站触发必须被拒，且不得创建任何数据。"""
        resp = client.post(TRIGGER_URL, json={'content': '白嫖一次生成'})
        assert resp.status_code == 401, (
            f"未认证请求应返回 401，实际 {resp.status_code} —— "
            "说明 @require_api_key 又丢了"
        )

    def test_trigger_rejects_wrong_api_key(self, client, api_key_enabled):
        resp = client.post(
            TRIGGER_URL,
            json={'content': 'hi'},
            headers={'X-API-Key': 'wrong-key'},
        )
        assert resp.status_code == 401

    def test_trigger_accepts_valid_api_key(self, client, api_key_enabled, db):
        """带正确 key 应放行（201），证明装饰器没把正常调用也挡死。"""
        from app.models import Conversation

        before = Conversation.query.count()
        resp = client.post(
            TRIGGER_URL,
            json={'content': '正常触发'},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 201, resp.get_json()
        assert Conversation.query.count() == before + 1

    def test_trigger_still_validates_content(self, client, api_key_enabled):
        """认证通过后，参数校验依然生效（顺序：先认证再校验参数）。"""
        resp = client.post(
            TRIGGER_URL,
            json={},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 400


class TestWebhookSsrf:
    """注册 webhook 时必须拦截内网 / 元数据地址。"""

    @pytest.mark.parametrize('url', INTERNAL_URLS)
    def test_register_rejects_internal_url(self, client, api_key_enabled, url):
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 1, 'url': url},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 400, (
            f"{url} 应被 SSRF 校验拒绝，实际 {resp.status_code}"
        )
        # 恶意地址绝不能落库，否则会被反复触发
        assert webhook_service.get_webhook_config(1) is None

    def test_register_accepts_public_url(self, client, api_key_enabled):
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 2, 'url': PUBLIC_URL},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 201, resp.get_json()
        assert webhook_service.get_webhook_config(2)['url'] == PUBLIC_URL

    def test_error_message_mentions_webhook_not_sse(self, client, api_key_enabled):
        """label 参数生效：错误信息说的是 webhook 场景，不是照搬 sse 文案。"""
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 3, 'url': 'gopher://127.0.0.1/x'},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 400
        msg = resp.get_json()['error']
        assert 'webhook' in msg, f"错误信息应标注 webhook 场景，实际: {msg}"

    def test_allowlist_permits_loopback(self, client, api_key_enabled, app):
        """WEBHOOK_ALLOWED_HOSTS 命中时放行 —— 本地调试需要这个口子。"""
        app.config['WEBHOOK_ALLOWED_HOSTS'] = frozenset({'127.0.0.1'})
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 4, 'url': 'http://127.0.0.1:9999/hook'},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 201, resp.get_json()

    def test_allowlist_does_not_leak_to_other_hosts(
        self, client, api_key_enabled, app
    ):
        """白名单只放行列出的主机，不能顺带放过别的内网地址。"""
        app.config['WEBHOOK_ALLOWED_HOSTS'] = frozenset({'127.0.0.1'})
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 5, 'url': 'http://10.0.0.5/hook'},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 400

    def test_webhook_allowlist_independent_from_mcp(
        self, client, api_key_enabled, app
    ):
        """两个白名单刻意分开：放开 MCP 的不得顺带放开 webhook。

        这是把 MCP_SSE_ALLOWED_HOSTS 和 WEBHOOK_ALLOWED_HOSTS 拆成两个配置项
        的全部理由 —— 否则"为本地跑 sse_test_server 放开 127.0.0.1"
        会同时让 webhook 回调也能打本机端口。
        """
        app.config['MCP_SSE_ALLOWED_HOSTS'] = frozenset({'127.0.0.1'})
        app.config['WEBHOOK_ALLOWED_HOSTS'] = frozenset()   # webhook 保持严格
        resp = client.post(
            REGISTER_URL,
            json={'conversation_id': 6, 'url': 'http://127.0.0.1:6379/probe'},
            headers=_auth_headers(api_key_enabled),
        )
        assert resp.status_code == 400, (
            "MCP 白名单泄漏到了 webhook —— 两个开关没真正隔离"
        )


@pytest.fixture(autouse=True)
def _use_stub_dns(stub_dns):
    """让本文件所有用例都走桩化的 DNS，不依赖真实网络。

    INTERNAL_URLS 里的 metadata.example / internal.example / rebind.example
    以及 PUBLIC_URL 的 example.com 都只在 stub_dns 的表里登记过；
    不挂这个 fixture 就会走真实解析 —— 轻则离线失败，重则域名不存在导致
    "应放行"的用例因 DNS 解析失败而被拒，断言假失败。
    """
    return stub_dns


@pytest.fixture(autouse=True)
def _clear_webhook_configs():
    """清空进程级 webhook 配置表，避免用例间互相污染。

    webhook_service._webhook_configs 是模块级 dict，跨测试存活；
    不清空的话前一个用例注册的 conversation_id=1 会让后一个
    "恶意地址不得落库"的断言假失败。
    """
    webhook_service._webhook_configs.clear()
    yield
    webhook_service._webhook_configs.clear()
