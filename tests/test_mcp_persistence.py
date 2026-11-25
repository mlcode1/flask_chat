"""
MCP 服务器配置持久化与归属隔离测试

覆盖此前"仅存内存、重启即丢"缺陷的修复，以及多用户归属隔离：
  1. 配置写入 mcp_servers 表（而非只存 manager.servers 内存字典）
  2. 重启后能从数据库恢复配置
  3. 用户定制服务器仅归属者可见可用（列表 + 工具层双重过滤）
  4. 工具执行时的权限校验（防止构造工具名绕过 UI 直连他人服务器）
  5. transport 分级授权（stdio 仅管理员，sse 可开放）
  6. 敏感字段（env / headers）脱敏

所有连接操作由 conftest 的 mcp_enabled fixture mock，不会真的 spawn 子进程。
"""
import pytest

from app.extensions import db
from app.models import MCPServer, User
from app.services import mcp_service


SSE_PAYLOAD = {
    'name': 'remote-sse',
    'transport': 'sse',
    'url': 'https://example.com/sse',
    'headers': {'Authorization': 'Bearer super-secret-token'},
}

STDIO_PAYLOAD = {
    'name': 'local-stdio',
    'transport': 'stdio',
    'command': 'echo',
    'args': ['hello'],
    'env': {'API_KEY': 'sk-secret-value'},
}


class TestPersistence:
    """配置必须落库，而不是只留在内存。"""

    def test_add_writes_to_database(self, admin_client, mcp_enabled):
        """添加后 mcp_servers 表应有记录 —— 这是本次修复的核心。"""
        resp = admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert resp.status_code == 200, resp.get_json()

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record is not None, '配置未写入数据库，仍只存在内存'
        assert record.transport == 'sse'
        assert record.config['url'] == 'https://example.com/sse'
        assert record.source == 'user'
        assert record.enabled is True

    def test_admin_add_creates_global_server(self, admin_client, mcp_enabled):
        """管理员添加的服务器归属为全局（user_id 为 NULL），所有用户可用。"""
        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.user_id is None, '管理员添加的服务器应为全局，而非归属个人'

    def test_connection_failure_still_persists_config(self, admin_client, mcp_enabled):
        """连接失败时配置仍应保存 —— 用户不必重填，重启后可自动重试。"""
        mcp_enabled.set_connect_result(False)

        resp = admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        assert resp.status_code == 200, '连接失败不应返回 5xx，持久化本身是成功的'
        data = resp.get_json()
        assert data['success'] is True
        assert data['connected'] is False

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record is not None, '连接失败也必须保留配置'
        assert record.status == 'failed'
        assert record.error_message

    def test_config_survives_manager_reset(self, admin_client, mcp_enabled):
        """模拟进程重启：内存连接全部清空后，配置仍能从数据库恢复。

        这正是旧实现丢失数据的场景 —— manager.servers 是纯内存字典。
        """
        from app.services.tool_service import get_mcp_manager

        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert 'remote-sse' in mcp_service.visible_server_names(None)

        # 模拟重启：清空内存态（数据库记录不动）
        get_mcp_manager().servers.clear()

        # 重启后从数据库读取，配置依然存在
        configs = mcp_service.build_effective_configs({})
        assert 'remote-sse' in configs, '重启后配置丢失，持久化未生效'
        assert configs['remote-sse']['url'] == 'https://example.com/sse'
        assert configs['remote-sse']['transport'] == 'sse'

    def test_remove_deletes_database_record(self, admin_client, mcp_enabled):
        """移除必须同时删掉数据库记录，否则重启后服务器会复活。"""
        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert MCPServer.query.filter_by(name='remote-sse').first() is not None

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/remove')
        assert resp.status_code == 200, resp.get_json()

        assert MCPServer.query.filter_by(name='remote-sse').first() is None, \
            '仅断开了连接，数据库配置未删除 → 重启后服务器会复活'

    def test_duplicate_name_rejected(self, admin_client, mcp_enabled):
        """服务器名必须全局唯一：它是工具名前缀，重名会导致路由错乱。"""
        first = admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert first.status_code == 200

        second = admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert second.status_code == 409
        assert MCPServer.query.filter_by(name='remote-sse').count() == 1

    def test_invalid_name_rejected(self, admin_client, mcp_enabled):
        """含 '__' 的名字必须拒绝 —— 那是工具名分隔符，会导致路由解析错乱。"""
        for bad_name in ['has__double', '-leading-dash', 'a' * 65, '']:
            payload = dict(SSE_PAYLOAD, name=bad_name)
            resp = admin_client.post('/api/skills/mcp/servers/add', json=payload)
            assert resp.status_code == 400, f'非法名 {bad_name!r} 应被拒绝'

        assert MCPServer.query.count() == 0

    def test_name_conflicting_with_skill_rejected(self, admin_client, mcp_enabled, app):
        """与已加载 Skill 重名必须拒绝：三层分发里 MCP 优先，会静默遮蔽同名 Skill。"""
        app.config['SKILLS_ENABLED'] = True
        from app.services.tool_service import get_skill_loader

        loader = get_skill_loader()
        loader.load_all_skills()

        if not loader.skills:
            pytest.skip('无已加载 Skill，跳过重名冲突测试')

        skill_name = next(iter(loader.skills))
        resp = admin_client.post('/api/skills/mcp/servers/add',
                                 json=dict(SSE_PAYLOAD, name=skill_name))

        assert resp.status_code == 400, f'与 Skill {skill_name!r} 重名应被拒绝'
        assert MCPServer.query.filter_by(name=skill_name).first() is None

    def test_stdio_requires_command(self, admin_client, mcp_enabled):
        """stdio 缺 command 应被拒绝（否则会尝试启动空命令）。"""
        resp = admin_client.post('/api/skills/mcp/servers/add',
                                 json={'name': 'broken', 'transport': 'stdio'})
        assert resp.status_code == 400
        assert MCPServer.query.filter_by(name='broken').first() is None

    def test_sse_requires_url(self, admin_client, mcp_enabled):
        """sse 缺 url 应被拒绝。"""
        resp = admin_client.post('/api/skills/mcp/servers/add',
                                 json={'name': 'broken', 'transport': 'sse'})
        assert resp.status_code == 400
        assert MCPServer.query.filter_by(name='broken').first() is None


class TestOwnershipIsolation:
    """用户定制服务器必须只对归属者可见可用。"""

    @pytest.fixture
    def open_user_custom(self, app):
        """开启用户自助添加（默认关闭），用于测试普通用户路径。"""
        original = app.config.get('MCP_ALLOW_USER_CUSTOM', False)
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        yield
        app.config['MCP_ALLOW_USER_CUSTOM'] = original

    def test_user_added_server_is_scoped_to_self(self, auth_client, test_user,
                                                 mcp_enabled, open_user_custom):
        """普通用户添加 sse 服务器后，归属应为自己而非全局。"""
        resp = auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert resp.status_code == 200, resp.get_json()

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.user_id == test_user.id, '用户定制服务器不应变成全局'

    def test_custom_server_invisible_to_others(self, auth_client, second_client,
                                              test_user, second_user,
                                              mcp_enabled, open_user_custom):
        """用户 A 的定制服务器不应出现在用户 B 的列表里。"""
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        mine = auth_client.get('/api/skills/mcp/servers').get_json()
        assert any(s['name'] == 'remote-sse' for s in mine['servers'])

        theirs = second_client.get('/api/skills/mcp/servers').get_json()
        assert not any(s['name'] == 'remote-sse' for s in theirs['servers']), \
            '用户 B 看到了用户 A 的定制服务器'

    def test_tool_layer_filters_by_ownership(self, auth_client, test_user,
                                             second_user, mcp_enabled,
                                             open_user_custom):
        """工具层过滤：get_tools 的可见名单必须按用户区分。

        这是防止用户 A 的定制工具暴露给用户 B 的关键 ——
        MCPClientManager.servers 以 name 为全局键，不含归属信息。
        """
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        assert 'remote-sse' in mcp_service.visible_server_names(test_user.id)
        assert 'remote-sse' not in mcp_service.visible_server_names(second_user.id), \
            '用户 B 的可见名单里出现了用户 A 的服务器'
        # 全局视角（user_id=None）也不应包含用户定制服务器
        assert 'remote-sse' not in mcp_service.visible_server_names(None)

    def test_execute_tool_rejects_cross_user_access(self, auth_client, test_user,
                                                   second_user, mcp_enabled,
                                                   open_user_custom):
        """执行层必须独立校验归属。

        仅靠 get_tools() 隐藏列表不够 —— 用户可以直接构造工具名
        （如 remote-sse__some_tool）绕过 UI 调用他人的服务器。
        """
        from app.services.tool_service import execute_tool, get_mcp_manager

        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        manager = get_mcp_manager()
        # 伪装成已连接并挂一个工具，模拟真实运行时状态
        fake = type('FakeConn', (), {
            'is_connected': True,
            'tools': [{'type': 'function',
                       'function': {'name': 'remote-sse__steal', 'parameters': {}}}],
            'transport': 'sse',
        })()
        manager.servers['remote-sse'] = fake

        # 归属者可以调用
        assert mcp_service.is_visible_to('remote-sse', test_user.id)

        # 他人调用必须被拒
        result = execute_tool('remote-sse__steal', '{}', user_id=second_user.id)
        assert '无权访问' in result, f'用户 B 成功调用了用户 A 的服务器: {result}'

    def test_unknown_server_denied_fail_closed(self, mcp_enabled, test_user):
        """数据库查不到的服务器名一律拒绝（fail-closed）。"""
        assert mcp_service.is_visible_to('never-existed', test_user.id) is False
        assert mcp_service.is_visible_to('never-existed', None) is False

    def test_user_cannot_remove_others_server(self, auth_client, second_client,
                                             test_user, mcp_enabled,
                                             open_user_custom):
        """用户 B 不能删除用户 A 的服务器。"""
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = second_client.post('/api/skills/mcp/servers/remote-sse/remove')
        assert resp.status_code == 403
        assert MCPServer.query.filter_by(name='remote-sse').first() is not None

    def test_user_cannot_reconnect_others_server(self, auth_client, second_client,
                                                test_user, mcp_enabled,
                                                open_user_custom):
        """用户 B 不能重连用户 A 的服务器。"""
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = second_client.post('/api/skills/mcp/servers/remote-sse/reconnect')
        assert resp.status_code == 403

    def test_admin_can_manage_any_server(self, auth_client, admin_client,
                                        test_user, mcp_enabled, open_user_custom):
        """管理员可管理任意用户的服务器（运维需要）。"""
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/remove')
        assert resp.status_code == 200, resp.get_json()
        assert MCPServer.query.filter_by(name='remote-sse').first() is None


class TestTransportAuthorization:
    """stdio 会 spawn 任意本地进程（等价 RCE），必须仅管理员可添加。"""

    def test_normal_user_cannot_add_stdio(self, auth_client, mcp_enabled, app):
        """即使用户自助开关打开，普通用户也不能添加 stdio。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True

        resp = auth_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)

        assert resp.status_code == 403, '普通用户竟能添加 stdio 服务器（RCE 风险）'
        assert MCPServer.query.filter_by(name='local-stdio').first() is None

    def test_admin_can_add_stdio(self, admin_client, mcp_enabled):
        resp = admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)
        assert resp.status_code == 200, resp.get_json()
        assert MCPServer.query.filter_by(name='local-stdio').first() is not None

    def test_user_custom_disabled_by_default(self, auth_client, mcp_enabled):
        """默认 MCP_ALLOW_USER_CUSTOM=false，普通用户连 sse 也不能加。"""
        resp = auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        assert resp.status_code == 403
        assert MCPServer.query.filter_by(name='remote-sse').first() is None

    def test_anonymous_cannot_add(self, client, mcp_enabled):
        """匿名请求必须 401，且不泄露任何命名规则信息。"""
        resp = client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)
        assert resp.status_code == 401
        assert MCPServer.query.count() == 0

    def test_anonymous_gets_401_not_400_when_mcp_disabled(self, client, app, db):
        """MCP 未启用时，匿名请求也必须是 401 而非 400。

        认证检查必须先于功能开关检查，否则未认证用户能探测出
        "本部署未开启 MCP" 这类信息。
        """
        app.config['MCP_ENABLED'] = False

        resp = client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)
        assert resp.status_code == 401, '功能开关检查跑到了认证之前'

    def test_cannot_escalate_sse_to_stdio(self, auth_client, admin_client,
                                         test_user, mcp_enabled, app):
        """提权防护：非管理员不得把 sse 服务器改成 stdio。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = auth_client.put('/api/skills/mcp/servers/remote-sse',
                              json={'transport': 'stdio', 'command': 'rm'})

        assert resp.status_code == 403, '普通用户成功把服务器提权为 stdio'
        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.transport == 'sse', 'transport 被篡改'

    def test_user_cannot_promote_to_global(self, auth_client, test_user,
                                          mcp_enabled, app):
        """普通用户不能把自己的服务器改成全局（等于开放给所有人）。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = auth_client.put('/api/skills/mcp/servers/remote-sse',
                              json={'scope': 'global'})

        assert resp.status_code == 403
        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.user_id == test_user.id, '归属被篡改为全局'


class TestSecretRedaction:
    """env / headers 常含 API Key 与代理凭据，列表接口必须脱敏。"""

    def test_list_redacts_env_and_headers(self, admin_client, mcp_enabled):
        admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)
        admin_client.post('/api/skills/mcp/servers/add',
                          json=dict(SSE_PAYLOAD, name='other-sse'))

        resp = admin_client.get('/api/skills/mcp/servers')
        assert resp.status_code == 200

        servers = {s['name']: s for s in resp.get_json()['servers']}

        stdio_cfg = servers['local-stdio']['config']
        assert 'sk-secret-value' not in str(stdio_cfg), 'env 中的 API Key 被泄露到列表接口'
        assert set(stdio_cfg['env'].keys()) == {'API_KEY'}, '应保留键名便于排查配置'
        assert stdio_cfg['env']['API_KEY'] == '***'

        sse_cfg = servers['other-sse']['config']
        assert 'super-secret-token' not in str(sse_cfg), 'headers 中的凭据被泄露'
        assert sse_cfg['headers']['Authorization'] == '***'

    def test_raw_secret_stored_in_database(self, admin_client, mcp_enabled):
        """数据库里必须是原值 —— 否则连接时拿不到真实凭据。"""
        admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)

        record = MCPServer.query.filter_by(name='local-stdio').first()
        assert record.config['env']['API_KEY'] == 'sk-secret-value', \
            '脱敏不应影响存储，否则无法用于实际连接'

    def test_detail_redacts_by_default(self, admin_client, mcp_enabled):
        admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)

        resp = admin_client.get('/api/skills/mcp/servers/local-stdio/info')
        assert resp.status_code == 200
        assert 'sk-secret-value' not in resp.get_data(as_text=True)

    def test_detail_reveals_secret_only_when_requested(self, admin_client, mcp_enabled):
        """只有归属者/管理员显式请求 include_secrets 才返回原值。"""
        admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)

        resp = admin_client.get('/api/skills/mcp/servers/local-stdio/info?include_secrets=true')
        assert resp.status_code == 200
        assert resp.get_json()['server']['config']['env']['API_KEY'] == 'sk-secret-value'

    def test_non_owner_cannot_read_secrets(self, admin_client, second_client,
                                          test_user, mcp_enabled, app, db):
        """用户 B 连用户 A 的服务器详情都无权查看（更谈不上读密钥）。"""
        # stdio 只有管理员能建，建好后把归属改为用户 A，
        # 模拟"管理员代用户配置"或"用户 A 的定制服务器"场景
        resp = admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)
        assert resp.status_code == 200, resp.get_json()

        record = MCPServer.query.filter_by(name='local-stdio').first()
        record.user_id = test_user.id
        db.session.commit()

        denied = second_client.get(
            '/api/skills/mcp/servers/local-stdio/info?include_secrets=true')
        assert denied.status_code == 403, '用户 B 竟能查看用户 A 的服务器详情'

    def test_owner_can_read_own_secrets(self, auth_client, admin_client, test_user,
                                       mcp_enabled, app, db):
        """归属者显式请求时应能读到自己服务器的密钥。"""
        admin_client.post('/api/skills/mcp/servers/add', json=STDIO_PAYLOAD)

        record = MCPServer.query.filter_by(name='local-stdio').first()
        record.user_id = test_user.id
        db.session.commit()

        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        resp = auth_client.get(
            '/api/skills/mcp/servers/local-stdio/info?include_secrets=true')

        assert resp.status_code == 200, resp.get_json()
        cfg = resp.get_json()['server']['config']
        assert cfg['env']['API_KEY'] == 'sk-secret-value', '归属者应能读到自己的密钥'


class TestToggleAndReconnect:
    """启用/禁用与重连都应基于数据库配置。"""

    def test_disable_keeps_config_but_removes_tools(self, admin_client, mcp_enabled):
        """禁用后配置保留（区别于删除），但工具不再暴露。"""
        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/toggle',
                                json={'enabled': False})
        assert resp.status_code == 200

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record is not None, '禁用不应删除配置'
        assert record.enabled is False
        assert record.status == 'disabled'

        # 禁用的服务器不出现在任何用户的有效配置里
        assert 'remote-sse' not in mcp_service.build_effective_configs({})

    def test_enable_reconnects(self, admin_client, mcp_enabled):
        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        admin_client.post('/api/skills/mcp/servers/remote-sse/toggle', json={'enabled': False})

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/toggle',
                                json={'enabled': True})
        assert resp.status_code == 200

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.enabled is True
        assert record.status == 'connected'

    def test_reconnect_uses_database_config(self, admin_client, mcp_enabled):
        """重连必须从数据库读配置，而非依赖内存 —— 否则重启后无法重连。"""
        from app.services.tool_service import get_mcp_manager

        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)

        # 模拟重启：内存清空
        get_mcp_manager().servers.clear()
        mcp_enabled.connect_calls.clear()

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/reconnect')
        assert resp.status_code == 200, resp.get_json()

        assert len(mcp_enabled.connect_calls) == 1, '重连未使用数据库配置'
        name, cfg = mcp_enabled.connect_calls[0]
        assert name == 'remote-sse'
        assert cfg['url'] == 'https://example.com/sse', '配置与数据库中保存的不一致'

    def test_reconnect_disabled_server_rejected(self, admin_client, mcp_enabled):
        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        admin_client.post('/api/skills/mcp/servers/remote-sse/toggle', json={'enabled': False})

        resp = admin_client.post('/api/skills/mcp/servers/remote-sse/reconnect')
        assert resp.status_code == 400

    def test_update_config_persists_and_reconnects(self, admin_client, mcp_enabled):
        """更新配置必须落库，且用新配置重连（否则运行时仍用旧配置）。"""
        from app.services.tool_service import get_mcp_manager

        admin_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        get_mcp_manager().servers.clear()
        mcp_enabled.connect_calls.clear()

        resp = admin_client.put('/api/skills/mcp/servers/remote-sse',
                               json={'url': 'https://new-endpoint.com/sse'})
        assert resp.status_code == 200, resp.get_json()

        record = MCPServer.query.filter_by(name='remote-sse').first()
        assert record.config['url'] == 'https://new-endpoint.com/sse', '更新未落库'

        assert len(mcp_enabled.connect_calls) == 1
        assert mcp_enabled.connect_calls[0][1]['url'] == 'https://new-endpoint.com/sse'

    def test_update_nonexistent_returns_404(self, admin_client, mcp_enabled):
        resp = admin_client.put('/api/skills/mcp/servers/ghost', json={'url': 'https://x'})
        assert resp.status_code == 404


class TestCascade:
    """用户删除时其定制服务器应级联删除（避免孤儿配置）。"""

    def test_deleting_user_removes_custom_servers(self, app, db, mcp_enabled):
        user = User(username='tempuser', email='temp@example.com')
        user.set_password('pass12345')
        db.session.add(user)
        db.session.commit()

        mcp_service.upsert_server('temp-server', 'sse', {'url': 'https://t.com'},
                                  user_id=user.id)
        mcp_service.upsert_server('global-server', 'sse', {'url': 'https://g.com'},
                                  user_id=None)

        assert MCPServer.query.count() == 2

        db.session.delete(user)
        db.session.commit()

        assert MCPServer.query.filter_by(name='temp-server').first() is None, \
            '用户定制服务器未级联删除，留下孤儿配置'
        assert MCPServer.query.filter_by(name='global-server').first() is not None, \
            '全局服务器被误删'


class TestLazyConnectOnLogin:
    """用户上线时懒连接其定制服务器（修复重启后不自动重连的缺陷）。

    背景：启动时只连接全局服务器（build_effective_configs 过滤 user_id IS NULL），
    否则要为每个用户 spawn 子进程。用户定制服务器改为在 WebSocket 上线时补连。
    """

    @pytest.fixture
    def user_server(self, db, test_user):
        """直接入库一个归属 test_user 的定制服务器（模拟用户此前已添加）。"""
        mcp_service.upsert_server(
            'my-sse', 'sse', {'url': 'https://my.example/sse'}, user_id=test_user.id)
        return MCPServer.query.filter_by(name='my-sse').first()

    def test_restart_then_login_reconnects(self, user_server, test_user, mcp_enabled):
        """核心场景：重启后内存为空，用户上线应把定制服务器连回来。"""
        from app.services.tool_service import get_mcp_manager

        # 模拟重启：配置在库里，但内存连接态归零
        get_mcp_manager().servers.clear()
        mcp_enabled.connect_calls.clear()

        results = mcp_service.ensure_user_servers_connected(test_user.id)

        assert results == {'my-sse': True}, f'上线未连接定制服务器: {results}'
        assert len(mcp_enabled.connect_calls) == 1
        name, cfg = mcp_enabled.connect_calls[0]
        assert name == 'my-sse'
        assert cfg['url'] == 'https://my.example/sse', '未按数据库配置连接'

    def test_tools_available_after_login(self, user_server, test_user, mcp_enabled):
        """连接后工具必须真的出现在 get_tools 结果里（否则模型仍看不到）。"""
        from app.services.tool_service import get_mcp_manager, get_tools
        from flask import current_app

        current_app.config['MCP_ENABLED'] = True
        get_mcp_manager().servers.clear()

        # 上线前：没有工具
        assert [t for t in get_tools(user_id=test_user.id)
                if t['function']['name'].startswith('my-sse__')] == []

        mcp_service.ensure_user_servers_connected(test_user.id)

        # 模拟连接成功后 manager 里的真实状态（mock 不会填充 tools）
        conn = get_mcp_manager().servers.get('my-sse')
        assert conn is not None, '连接后 manager 里应有该服务器'
        conn.tools = [{'type': 'function',
                       'function': {'name': 'my-sse__do_thing', 'parameters': {}}}]

        names = [t['function']['name'] for t in get_tools(user_id=test_user.id)]
        assert 'my-sse__do_thing' in names, f'工具未暴露给模型: {names}'

    def test_only_connects_own_servers(self, user_server, db, second_user, mcp_enabled):
        """懒连接只处理该用户自己的服务器，不能把别人的也连上。"""
        mcp_service.upsert_server('other-sse', 'sse', {'url': 'https://o.example/sse'},
                                  user_id=second_user.id)

        results = mcp_service.ensure_user_servers_connected(second_user.id)

        assert 'other-sse' in results
        assert 'my-sse' not in results, '连上了不属于该用户的服务器'

    def test_skips_global_servers(self, user_server, db, test_user, mcp_enabled):
        """全局服务器已在启动时连接，懒连接不应重复处理。"""
        mcp_service.upsert_server('global-sse', 'sse', {'url': 'https://g.example/sse'},
                                  user_id=None)

        results = mcp_service.ensure_user_servers_connected(test_user.id)

        assert 'global-sse' not in results, '懒连接不该处理全局服务器'
        assert list(results.keys()) == ['my-sse']

    def test_skips_disabled_servers(self, user_server, test_user, mcp_enabled):
        """已禁用的服务器不应被连上（否则禁用开关形同虚设）。"""
        mcp_service.set_enabled('my-sse', False)

        results = mcp_service.ensure_user_servers_connected(test_user.id)

        assert results == {}, f'禁用的服务器仍被连接: {results}'
        assert mcp_enabled.connect_calls == []

    def test_second_login_within_cooldown_skipped(self, user_server, test_user, mcp_enabled):
        """冷却期内重复上线不重连 —— 防止多标签页反复 spawn 子进程。"""
        first = mcp_service.ensure_user_servers_connected(test_user.id)
        assert first == {'my-sse': True}
        assert len(mcp_enabled.connect_calls) == 1

        mcp_enabled.connect_calls.clear()
        second = mcp_service.ensure_user_servers_connected(test_user.id)

        assert second == {}, '冷却期内应跳过，返回空 dict'
        assert mcp_enabled.connect_calls == [], '冷却期内不应重复发起连接'

    def test_cooldown_gate_and_invalidate(self, user_server, test_user, mcp_enabled):
        """精确验证冷却闸门：冷却期内跳过，清簿记后放行。

        注意「已连接则跳过」的短路是正确行为 —— 要观察重连动作，
        必须先让服务器处于未连接状态（模拟掉线），否则无从判断
        究竟是冷却期拦住了还是短路跳过了。
        """
        from app.services.tool_service import get_mcp_manager

        # 第一次上线：连接成功，进入冷却期
        assert mcp_service.ensure_user_servers_connected(test_user.id) == {'my-sse': True}
        assert len(mcp_enabled.connect_calls) == 1

        # 模拟掉线：连接没了，但冷却期仍生效
        get_mcp_manager().servers.clear()
        mcp_enabled.connect_calls.clear()

        # 冷却期内再次上线 → 被闸门拦住，不发起连接
        assert mcp_service.ensure_user_servers_connected(test_user.id) == {}
        assert mcp_enabled.connect_calls == [], '冷却期内不应发起连接'

        # 清簿记后 → 闸门放行，立即重连
        mcp_service.invalidate_user_load(test_user.id)
        results = mcp_service.ensure_user_servers_connected(test_user.id)

        assert results == {'my-sse': True}, '清簿记后应重新连接'
        assert len(mcp_enabled.connect_calls) == 1

    def test_already_connected_short_circuits(self, user_server, test_user, mcp_enabled):
        """已连接的服务器不该重复连接（避免无谓的断连/重连抖动）。"""
        from app.services.tool_service import get_mcp_manager

        mcp_service.ensure_user_servers_connected(test_user.id)
        assert len(mcp_enabled.connect_calls) == 1
        assert 'my-sse' in get_mcp_manager().servers

        # 清冷却期但保持已连接状态 → 应走短路，不再发起连接
        mcp_service.invalidate_user_load(test_user.id)
        mcp_enabled.connect_calls.clear()

        results = mcp_service.ensure_user_servers_connected(test_user.id)

        assert results == {'my-sse': True}, '短路也应报告为已连接'
        assert mcp_enabled.connect_calls == [], '已连接的服务器被重复连接'

    def test_add_custom_server_invalidates_cooldown(self, auth_client, test_user,
                                                   mcp_enabled, app):
        """用户添加服务器后必须清簿记，否则冷却期内改了配置不生效。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True

        # 先触发一次懒连接，让该用户进入冷却期
        mcp_service.ensure_user_servers_connected(test_user.id)

        mcp_enabled.connect_calls.clear()
        resp = auth_client.post('/api/skills/mcp/servers/add', json=SSE_PAYLOAD)
        assert resp.status_code == 200, resp.get_json()

        # add 接口应当已连接该服务器
        assert any(n == 'remote-sse' for n, _ in mcp_enabled.connect_calls), \
            'add 未触发连接'

    def test_failure_recorded_and_retryable(self, user_server, test_user, mcp_enabled):
        """连接失败要回写 status=failed，且清簿记后可重试。"""
        mcp_enabled.set_connect_result(False)

        results = mcp_service.ensure_user_servers_connected(test_user.id)
        assert results == {'my-sse': False}

        record = MCPServer.query.filter_by(name='my-sse').first()
        assert record.status == 'failed'
        assert record.error_message, '失败原因应写入，供界面展示'

        # 恢复可用后清簿记应能重连成功
        mcp_enabled.set_connect_result(True)
        mcp_service.invalidate_user_load(test_user.id)

        results = mcp_service.ensure_user_servers_connected(test_user.id)
        assert results == {'my-sse': True}
        assert MCPServer.query.filter_by(name='my-sse').first().status == 'connected'

    def test_anonymous_user_returns_empty(self, mcp_enabled):
        """user_id 为空时直接返回，不查库不连接。"""
        assert mcp_service.ensure_user_servers_connected(None) == {}
        assert mcp_service.ensure_user_servers_connected(0) == {}
        assert mcp_enabled.connect_calls == []

    def test_user_without_servers_returns_empty(self, test_user, mcp_enabled):
        """没有任何定制服务器的用户，上线时不应产生连接动作。"""
        results = mcp_service.ensure_user_servers_connected(test_user.id)
        assert results == {}
        assert mcp_enabled.connect_calls == []


class TestSsrfGuard:
    """sse URL 的 SSRF 校验。

    为什么需要：sse 的 url 由**服务端**发起请求。不校验则用户可填
    http://169.254.169.254/latest/meta-data/ 读云厂商实例元数据（含临时凭证），
    或填 http://127.0.0.1:5432/ 探测本机数据库端口，且响应会回流到工具列表 /
    调用结果，构成有读回通道的 SSRF。

    校验分三层，都要覆盖：
      1. ssrf_guard.validate_sse_url —— 纯函数规则（协议 / IP 段 / host 混淆）
      2. add / update 路由 —— 非管理员被拦，管理员豁免
      3. _connect_sse 连接前复检 —— 挡住绕过路由直接写库的配置

    DNS 由 conftest 的 mcp_enabled fixture 桩化，测试不依赖网络。
    """

    # ---------- 1. 纯函数规则 ----------

    @pytest.mark.parametrize("url", [
        # 云厂商元数据 —— SSRF 最高价值目标
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/v2/credentials",
        "http://[fd00:ec2::254]/",
        # 环回
        "http://127.0.0.1:9111/sse",
        "http://127.1/x",                       # 127/8 的简写形式
        "http://[::1]/mcp",
        # 内网段
        "http://10.0.0.5/mcp",
        "http://192.168.1.1/mcp",
        "http://172.16.5.4/mcp",
        "http://172.31.255.255/mcp",
        "http://[fc00::1]/mcp",                 # IPv6 ULA
        # Python 3.14 的 ipaddress 对该段 is_private=False，
        # 只有 is_global=False 能抓住 —— 这是最容易被漏掉的一段
        "http://100.64.0.1/mcp",
        "http://100.127.255.255/mcp",
        # 未指定 / 组播 / 保留
        "http://0.0.0.0/mcp",
        "http://[::]/mcp",
        "http://224.0.0.1/mcp",
        "http://239.255.255.250/mcp",           # SSDP
        "http://240.0.0.1/mcp",
        # 链路本地（IPv6）
        "http://[fe80::1]/mcp",
        "http://[fe80::1%25en0]/mcp",           # 带 scope id
    ])
    def test_rejects_private_and_special_addresses(self, url):
        """内网 / 元数据 / 特殊段一律拒绝。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url(url, None)

    @pytest.mark.parametrize("url", [
        # IPv4-mapped IPv6：::ffff:127.0.0.1 的 is_loopback 为 False，
        # 不先还原成 IPv4 就判断会被绕过
        "http://[::ffff:127.0.0.1]/mcp",
        "http://[::ffff:169.254.169.254]/",
        # IPv4-in-IPv6（非标准写法，部分解析器接受）
        "http://[::127.0.0.1]/mcp",
        "http://[::a9fe:a9fe]/",                # ::169.254.169.254 的十六进制形式
    ])
    def test_rejects_ipv6_wrapped_ipv4_bypass(self, url):
        """IPv6 包裹的 IPv4 写法不能绕过校验。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url(url, None)

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_x",
        "dict://x/y",
        "ftp://8.8.8.8/",
        "http+unix:///var/run/docker.sock",
    ])
    def test_rejects_non_http_schemes(self, url):
        """只允许 http / https。用白名单而非黑名单，未知协议默认拒绝。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url(url, None)

    @pytest.mark.parametrize("url", [
        # http://expected.com@evil.com/ 的真实 host 是 evil.com。
        # 我们以 parsed.hostname 为准，所以这类混淆天然无效；
        # 但仍显式拒绝，避免用户误以为自己在连前面那个域名。
        "http://expected.com@127.0.0.1/mcp",
        "http://trusted.example@internal.example/mcp",
    ])
    def test_rejects_credential_host_confusion(self, url):
        """url 中不得含 '@'（防 host 混淆）。凭据应放 headers。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError) as exc:
            validate_sse_url(url, None)
        assert "@" in str(exc.value)

    @pytest.mark.parametrize("url", [
        "https://api.github.com/mcp",
        "https://example.com/sse",
        "http://8.8.8.8/mcp",
        "http://1.1.1.1/mcp",
        "http://93.184.216.34:8080/sse",
        "http://[2606:2800:220:1:248:1893:25c8:1946]/mcp",
    ])
    def test_allows_public_urls(self, url):
        """正常公网地址必须放行，否则功能不可用。"""
        from app.services.ssrf_guard import validate_sse_url
        assert validate_sse_url(url, None) == url

    @pytest.mark.parametrize("url", ["", None, "   ", "not-a-url", "http://", "http:///sse"])
    def test_rejects_malformed_urls(self, url):
        """空值 / 无 host 的畸形 URL 必须拒绝（fail-closed）。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url(url, None)

    def test_rejects_domain_resolving_to_internal_ip(self, stub_dns):
        """域名解析到内网也要拦 —— 只看 host 字面量是不够的。

        这是 SSRF 最常见的绕过手法：用一个公网可解析的域名指向内网 IP。
        stub_dns 把 internal.example 桩化为 10.0.0.7。
        """
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError) as exc:
            validate_sse_url("http://internal.example/mcp", None)
        assert "10.0.0.7" in str(exc.value), "错误信息应包含实际解析到的 IP，便于排查"

    def test_rejects_domain_resolving_to_metadata_service(self, stub_dns):
        """域名指向云元数据服务（169.254.169.254）必须拦。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError) as exc:
            validate_sse_url("http://metadata.example/mcp", None)
        assert "元数据" in str(exc.value)

    def test_checks_all_resolved_addresses_not_just_first(self, stub_dns):
        """多 A 记录场景：只要有一条落在内网就拒绝。

        攻击者可让权威 DNS 返回「公网 IP + 127.0.0.1」，客户端可能挑后者连接。
        stub_dns 把 mixed.example 桩化为 ["93.184.216.34", "192.168.1.5"]。
        """
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError) as exc:
            validate_sse_url("http://mixed.example/mcp", None)
        assert "192.168.1.5" in str(exc.value), "必须检查到第二条内网记录，而不是只看第一条"

    def test_unresolvable_domain_is_rejected(self, stub_dns):
        """解析不出地址的域名拒绝（fail-closed，不放行未知目标）。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError) as exc:
            validate_sse_url("http://definitely-not-registered.invalid/mcp", None)
        assert "解析" in str(exc.value)

    # ---------- 2. 白名单 ----------

    def test_allowlist_bypasses_check_for_loopback(self):
        """白名单命中的主机跳过校验 —— 本地开发连 127.0.0.1 测试服务器要用。"""
        from app.services.ssrf_guard import validate_sse_url
        url = "http://127.0.0.1:9111/sse"
        assert validate_sse_url(url, {"127.0.0.1"}) == url

    def test_allowlist_is_case_insensitive_and_strips_brackets(self):
        """白名单匹配应忽略大小写，并兼容 IPv6 的方括号写法。"""
        from app.services.ssrf_guard import validate_sse_url
        assert validate_sse_url("http://LOCALHOST:9111/sse", {"localhost"})
        assert validate_sse_url("http://[::1]:9111/sse", {"::1"})

    def test_allowlist_does_not_leak_to_other_hosts(self):
        """白名单只放行列出的主机，不能顺带放过其他内网地址。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url("http://169.254.169.254/", {"127.0.0.1"})

    def test_empty_allowlist_enforces_full_check(self):
        """白名单为空（代码默认值）= 全部主机都要过校验。"""
        from app.services.ssrf_guard import SSRFValidationError, validate_sse_url
        with pytest.raises(SSRFValidationError):
            validate_sse_url("http://127.0.0.1/sse", frozenset())
        with pytest.raises(SSRFValidationError):
            validate_sse_url("http://127.0.0.1/sse", None)

    # ---------- 3. 路由层集成 ----------

    def test_normal_user_cannot_add_internal_url(self, auth_client, mcp_enabled, app):
        """非管理员添加内网 URL 被拦，且不落库。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True

        resp = auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'evil-metadata',
            'transport': 'sse',
            'url': 'http://169.254.169.254/latest/meta-data/',
        })

        assert resp.status_code == 400, resp.get_json()
        assert MCPServer.query.filter_by(name='evil-metadata').first() is None, \
            '被 SSRF 拦下的配置不应落库'

    def test_normal_user_cannot_add_loopback_url(self, auth_client, mcp_enabled, app):
        """非管理员添加 127.0.0.1 被拦（TestingConfig 白名单为空）。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True

        resp = auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'loopback',
            'transport': 'sse',
            'url': 'http://127.0.0.1:9111/sse',
        })

        assert resp.status_code == 400, resp.get_json()
        assert MCPServer.query.filter_by(name='loopback').first() is None

    def test_normal_user_can_add_public_url(self, auth_client, mcp_enabled, app):
        """非管理员添加公网 URL 应放行 —— 不能把功能一起堵死。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True

        resp = auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'good-remote',
            'transport': 'sse',
            'url': 'https://example.com/sse',
        })

        assert resp.status_code == 200, resp.get_json()
        assert MCPServer.query.filter_by(name='good-remote').first() is not None

    def test_admin_exempt_from_ssrf_check(self, admin_client, mcp_enabled):
        """管理员豁免 SSRF 校验。

        理由：管理员本就能添加 stdio（等价 RCE），SSRF 对其不构成额外权限。
        强制校验只会让管理员连内网服务时被迫改白名单，无安全收益。
        """
        resp = admin_client.post('/api/skills/mcp/servers/add', json={
            'name': 'admin-internal',
            'transport': 'sse',
            'url': 'http://192.168.1.50:8080/mcp',
        })

        assert resp.status_code == 200, resp.get_json()
        assert MCPServer.query.filter_by(name='admin-internal').first() is not None

    def test_allowlist_lets_normal_user_add_loopback(self, auth_client, mcp_enabled, app):
        """白名单配置后，非管理员可添加对应主机（本地开发场景）。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        app.config['MCP_SSE_ALLOWED_HOSTS'] = {'127.0.0.1'}

        resp = auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'local-test',
            'transport': 'sse',
            'url': 'http://127.0.0.1:9111/sse',
        })

        assert resp.status_code == 200, resp.get_json()

    def test_normal_user_cannot_update_to_internal_url(self, auth_client, mcp_enabled, app):
        """update 也要校验 —— 否则可「先建合法 sse，再 update 成元数据地址」绕过 add。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        add = auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'mutable',
            'transport': 'sse',
            'url': 'https://example.com/sse',
        })
        assert add.status_code == 200, add.get_json()

        resp = auth_client.put('/api/skills/mcp/servers/mutable',
                               json={'url': 'http://169.254.169.254/latest/meta-data/'})

        assert resp.status_code == 400, resp.get_json()
        record = MCPServer.query.filter_by(name='mutable').first()
        assert record.config['url'] == 'https://example.com/sse', \
            '被拦下的 update 不应改动已存的 url'

    def test_normal_user_cannot_switch_transport_to_evade_check(
            self, auth_client, mcp_enabled, app):
        """从 stdio 改成 sse 时同样要校验新 url（transport 分支切换不能成为绕过口）。"""
        app.config['MCP_ALLOW_USER_CUSTOM'] = True
        # 普通用户建不了 stdio，先用管理员建一个全局的再验证 update 路径不现实；
        # 改为直接验证 sse→sse 的 url 变更已覆盖，且 stdio 提权仍被拦。
        auth_client.post('/api/skills/mcp/servers/add', json={
            'name': 'sse-only', 'transport': 'sse', 'url': 'https://example.com/sse'})

        resp = auth_client.put('/api/skills/mcp/servers/sse-only',
                               json={'transport': 'stdio', 'command': 'id'})
        assert resp.status_code == 403, '提权为 stdio 应被拦'

    def test_reconnect_does_not_revalidate_but_connect_layer_does(
            self, admin_client, mcp_enabled, app):
        """reconnect 只校验归属、不校验 url，所以连接层复检是必要的纵深防御。

        此处验证：管理员可入库一个内网地址（豁免），配置确实进了库 ——
        连接层复检的行为由 test_connect_sse_rejects_internal_url 单独覆盖。
        """
        admin_client.post('/api/skills/mcp/servers/add', json={
            'name': 'internal-by-admin',
            'transport': 'sse',
            'url': 'http://10.0.0.9/mcp',
        })
        record = MCPServer.query.filter_by(name='internal-by-admin').first()
        assert record is not None and record.config['url'] == 'http://10.0.0.9/mcp'

    # ---------- 4. 连接层复检 ----------

    def test_connect_sse_rejects_internal_url(self, app):
        """_connect_sse 连接前复检：内网 URL 抛错，不发起真实请求。

        这层挡住绕过路由的路径 —— .env 的 MCP_SERVERS_CONFIG、管理员直接改库、
        reconnect 接口（只校验归属不校验 url）。
        """
        import asyncio

        from app.mcp.client_manager import MCPServerConnection, configure_sse_guard

        # 显式设空白名单，确保复检对全部主机生效
        configure_sse_guard(frozenset())
        try:
            conn = MCPServerConnection(
                "probe",
                {"transport": "sse", "url": "http://169.254.169.254/latest/meta-data/"},
            )
            with pytest.raises(ValueError) as exc:
                asyncio.run(conn._connect_sse())
            assert "SSRF" in str(exc.value)
        finally:
            configure_sse_guard(app.config.get('MCP_SSE_ALLOWED_HOSTS'))

    def test_connect_sse_allows_whitelisted_host(self, app):
        """白名单主机在连接层同样放行（否则本地测试服务器连不上）。

        桩掉 sse_client：只要代码走到调用 sse_client 这一步，就证明 SSRF 复检
        已放行。sse_client 返回的是 async context manager，桩必须同构 ——
        进入 __aenter__ 时抛哨兵异常终止，避免真的建连。
        """
        import asyncio
        from contextlib import asynccontextmanager

        from app.mcp import client_manager
        from app.mcp.client_manager import MCPServerConnection, configure_sse_guard

        configure_sse_guard({"127.0.0.1"})
        reached = {"value": False}

        @asynccontextmanager
        async def fake_sse_client(url, headers=None, timeout=None, sse_read_timeout=None):
            reached["value"] = True
            raise RuntimeError("已越过 SSRF 复检，进入真实连接阶段（测试到此为止）")
            yield  # pragma: no cover  —— 永不执行，仅为满足 async CM 协议

        original = client_manager.sse_client
        client_manager.sse_client = fake_sse_client
        try:
            conn = MCPServerConnection(
                "local", {"transport": "sse", "url": "http://127.0.0.1:9111/sse"})
            with pytest.raises(RuntimeError, match="已越过 SSRF 复检"):
                asyncio.run(conn._connect_sse())
            assert reached["value"] is True, "白名单主机应放行到真实连接阶段"
        finally:
            client_manager.sse_client = original
            configure_sse_guard(app.config.get('MCP_SSE_ALLOWED_HOSTS'))

    # ---------- 5. 配置注入 ----------

    def test_configure_sse_guard_normalizes_hosts(self):
        """注入白名单时统一小写、去空白、剥方括号（IPv6）。"""
        from app.mcp import client_manager

        client_manager.configure_sse_guard([" LocalHost ", "[::1]", "Example.COM"])
        try:
            assert client_manager._sse_allowed_hosts == {"localhost", "::1", "example.com"}
        finally:
            client_manager.configure_sse_guard(frozenset())

    def test_configure_sse_guard_handles_empty(self):
        """空 / None / 空串都应得到空 frozenset，而不是残留上次的值。"""
        from app.mcp import client_manager

        client_manager.configure_sse_guard({"stale.example"})
        for value in (None, "", [], set(), frozenset()):
            client_manager.configure_sse_guard(value)
            assert client_manager._sse_allowed_hosts == frozenset(), f"{value!r} 应清空为 frozenset()"


class TestConnectTimeout:
    """连接超时与 sse 超时的回归防护。

    覆盖两个此前的缺陷：
      1. connect() 超时后只 return False，**不取消** connect_task。
         _connect_stdio 内部是 `async with stdio_client(...)`，该上下文持有
         npx/uvx 拉起的子进程；任务不取消 → 子进程变孤儿，反复重连会累积僵尸进程。
      2. _connect_sse 调 sse_client 时未传 timeout，落回 mcp 默认的 **5s**
         （已用 inspect.signature 实测确认），远端服务冷启动极易超时，
         且异常被 anyio 包成 ExceptionGroup，日志里看不出是超时。
    """

    def test_timeout_cancels_connect_task(self, monkeypatch):
        """核心断言：超时后 connect_task 必须被 cancel。"""
        import asyncio
        from app.mcp import client_manager
        from app.mcp.client_manager import MCPServerConnection

        entered = {"value": False}
        cancelled = {"value": False}

        async def slow_connect(self):
            entered["value"] = True
            try:
                await asyncio.sleep(30)      # 远超超时，模拟 npx 卡死
            except asyncio.CancelledError:
                cancelled["value"] = True
                raise                        # 必须重抛，否则 asyncio 认为任务未取消

        monkeypatch.setattr(MCPServerConnection, "_connect_stdio", slow_connect)
        monkeypatch.setattr(client_manager, "CONNECT_TIMEOUT_SECONDS", 0.3)
        monkeypatch.setattr(client_manager, "MCP_AVAILABLE", True)

        conn = MCPServerConnection("slow", {"transport": "stdio", "command": "echo"})
        result = asyncio.run(conn.connect())

        assert result is False, "超时应返回 False"
        assert entered["value"] is True, "连接协程根本没启动，测试无意义"
        assert cancelled["value"] is True, (
            "超时后未取消 connect_task —— npx/uvx 子进程会泄漏成孤儿进程"
        )
        assert conn._connected is False
        assert conn.session is None

    def test_timeout_uses_configurable_constant(self, monkeypatch):
        """超时上限来自 CONNECT_TIMEOUT_SECONDS，不再是硬编码的 range(300)。"""
        import asyncio
        import time
        from app.mcp import client_manager
        from app.mcp.client_manager import MCPServerConnection

        async def never_ready(self):
            await asyncio.sleep(30)

        monkeypatch.setattr(MCPServerConnection, "_connect_stdio", never_ready)
        monkeypatch.setattr(client_manager, "MCP_AVAILABLE", True)

        # 改成 0.4s：若代码仍按硬编码 30s 轮询，这里会耗时远超 1s
        monkeypatch.setattr(client_manager, "CONNECT_TIMEOUT_SECONDS", 0.4)
        conn = MCPServerConnection("t", {"transport": "stdio", "command": "echo"})
        t0 = time.time()
        asyncio.run(conn.connect())
        elapsed = time.time() - t0

        assert elapsed < 2.0, (
            f"耗时 {elapsed:.2f}s，说明超时上限没有读 CONNECT_TIMEOUT_SECONDS"
        )

    def test_sse_client_receives_explicit_timeouts(self, monkeypatch):
        """sse_client 必须收到显式 timeout / sse_read_timeout。"""
        import asyncio
        from contextlib import asynccontextmanager
        from app.mcp import client_manager
        from app.mcp.client_manager import MCPServerConnection

        captured = {}

        @asynccontextmanager
        async def fake_sse_client(url, headers=None, timeout=None, sse_read_timeout=None):
            captured.update(
                url=url, timeout=timeout, sse_read_timeout=sse_read_timeout,
                headers=headers,
            )
            raise RuntimeError("已拿到参数，测试到此为止")
            yield  # pragma: no cover

        monkeypatch.setattr(client_manager, "sse_client", fake_sse_client)
        client_manager.configure_sse_guard({"127.0.0.1"})   # 放行本地地址以走到建连
        try:
            conn = MCPServerConnection(
                "t", {"transport": "sse", "url": "http://127.0.0.1:9111/sse"})
            with pytest.raises(RuntimeError, match="已拿到参数"):
                asyncio.run(conn._connect_sse())
        finally:
            client_manager.configure_sse_guard(frozenset())

        assert captured["timeout"] is not None, (
            "未传 timeout → 落回 mcp 默认 5s，远端冷启动会莫名超时"
        )
        assert captured["timeout"] == client_manager.SSE_HTTP_TIMEOUT_SECONDS
        assert captured["sse_read_timeout"] == client_manager.SSE_READ_TIMEOUT_SECONDS
        # 回归防护：绝不能把 HTTP 超时误设成 5s
        assert captured["timeout"] > 5.0

    def test_configure_mcp_timeouts_partial_update(self):
        """注入函数：传 None 的参数必须保持原值，不能被清零。"""
        from app.mcp import client_manager

        original = (
            client_manager.CONNECT_TIMEOUT_SECONDS,
            client_manager.SSE_HTTP_TIMEOUT_SECONDS,
            client_manager.SSE_READ_TIMEOUT_SECONDS,
        )
        try:
            client_manager.configure_mcp_timeouts(connect=11, sse_http=22, sse_read=33)
            assert client_manager.CONNECT_TIMEOUT_SECONDS == 11.0
            assert client_manager.SSE_HTTP_TIMEOUT_SECONDS == 22.0
            assert client_manager.SSE_READ_TIMEOUT_SECONDS == 33.0

            # 只改一项，其余两项必须原样保留
            client_manager.configure_mcp_timeouts(connect=44)
            assert client_manager.CONNECT_TIMEOUT_SECONDS == 44.0
            assert client_manager.SSE_HTTP_TIMEOUT_SECONDS == 22.0, "部分注入污染了 sse_http"
            assert client_manager.SSE_READ_TIMEOUT_SECONDS == 33.0, "部分注入污染了 sse_read"

            # 字符串也要能转成 float（config 可能来自 env）
            client_manager.configure_mcp_timeouts(connect="7")
            assert client_manager.CONNECT_TIMEOUT_SECONDS == 7.0
        finally:
            client_manager.configure_mcp_timeouts(*original)

