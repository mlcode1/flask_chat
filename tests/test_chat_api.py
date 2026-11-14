"""
Integration tests for chat API endpoints
"""
import pytest
import json


class TestChatAPI:
    """Integration tests for chat endpoints"""
    
    def test_create_conversation(self, client):
        """Test creating a new conversation"""
        response = client.post('/api/conversations', 
                              json={'title': 'Test Chat'})
        # 注意：实现返回 200 而非 REST 规范的 201，此处断言真实行为。
        # 若后续将 create_conversation 改为返回 201，需同步更新此断言。
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'id' in data
        assert data['title'] == 'Test Chat'
    
    def test_create_conversation_default_title(self, client):
        """Test creating conversation with default title"""
        response = client.post('/api/conversations', json={})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'id' in data
        # 默认标题已中文化
        assert data['title'] == '新对话'
    
    def test_list_conversations(self, auth_client, db):
        """Test listing conversations.

        GET /api/conversations 需要 JWT 认证（无 user 时返回 401），
        因此使用 auth_client 而非匿名 client。
        """
        # Create some conversations
        for i in range(3):
            auth_client.post('/api/conversations', json={'title': f'Chat {i}'})
        
        response = auth_client.get('/api/conversations')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) >= 3
    
    def test_get_conversation_messages_empty(self, client, db):
        """Test getting messages from empty conversation"""
        # Create conversation
        create_resp = client.post('/api/conversations', json={'title': 'Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Get messages
        response = client.get(f'/api/conversations/{conv_id}/messages')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['messages'] == []
        assert data['has_more'] is False
    
    def test_delete_conversation(self, auth_client, db):
        """Test deleting a conversation"""
        # Create conversation
        create_resp = auth_client.post('/api/conversations', json={'title': 'To Delete'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Delete it
        response = auth_client.delete(f'/api/conversations/{conv_id}')
        assert response.status_code == 200
        
        # Verify it's gone
        get_resp = auth_client.get('/api/conversations')
        conversations = json.loads(get_resp.data)
        assert isinstance(conversations, list)
        assert not any(c['id'] == conv_id for c in conversations)
    
    def test_rename_conversation(self, client, db):
        """Test renaming a conversation"""
        # Create conversation
        create_resp = client.post('/api/conversations', json={'title': 'Old Title'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Rename it
        response = client.patch(f'/api/conversations/{conv_id}',
                               json={'title': 'New Title'})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['title'] == 'New Title'
    
    def test_rename_conversation_not_found(self, client):
        """Test renaming non-existent conversation"""
        response = client.patch('/api/conversations/99999',
                               json={'title': 'New Title'})
        assert response.status_code == 404
    
    def test_get_conversation_stats(self, client, db):
        """Test getting conversation statistics"""
        # Create conversation with messages
        create_resp = client.post('/api/conversations', json={'title': 'Stats Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Add some messages
        from app.models import Message
        msg1 = Message(conversation_id=conv_id, role='user', content='Hello', token_count=10)
        msg2 = Message(conversation_id=conv_id, role='assistant', content='Hi there', token_count=15)
        db.session.add_all([msg1, msg2])
        db.session.commit()
        
        # Get stats
        response = client.get(f'/api/conversations/{conv_id}/stats')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['total_messages'] == 2
        assert data['user_tokens'] == 10
        assert data['assistant_tokens'] == 15
        assert data['total_tokens'] == 25
    
    def test_share_conversation(self, client, db):
        """Test sharing a conversation"""
        # Create conversation
        create_resp = client.post('/api/conversations', json={'title': 'Share Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Share it
        response = client.post(f'/api/conversations/{conv_id}/share')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'share_token' in data
        assert len(data['share_token']) > 0
    
    def test_export_conversation_markdown(self, client, db):
        """Test exporting conversation as markdown"""
        # Create conversation with messages
        create_resp = client.post('/api/conversations', json={'title': 'Export Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        from app.models import Message
        msg = Message(conversation_id=conv_id, role='user', content='Test message')
        db.session.add(msg)
        db.session.commit()
        
        # Export as markdown
        response = client.get(f'/api/conversations/{conv_id}/export?format=markdown')
        assert response.status_code == 200
        assert response.mimetype == 'text/markdown'
        assert b'Export Test' in response.data
    
    def test_export_conversation_json(self, client, db):
        """Test exporting conversation as JSON"""
        # Create conversation
        create_resp = client.post('/api/conversations', json={'title': 'JSON Export'})
        conv_id = json.loads(create_resp.data)['id']
        
        # Export as JSON
        response = client.get(f'/api/conversations/{conv_id}/export?format=json')
        assert response.status_code == 200
        assert response.mimetype == 'application/json'
        
        data = json.loads(response.data)
        assert data['title'] == 'JSON Export'
        assert 'messages' in data
    
    def test_submit_feedback_like(self, client, db):
        """Test submitting positive feedback"""
        # Create conversation and message
        create_resp = client.post('/api/conversations', json={'title': 'Feedback Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        from app.models import Message
        msg = Message(conversation_id=conv_id, role='assistant', content='Test')
        db.session.add(msg)
        db.session.commit()
        
        # Submit feedback
        response = client.post(f'/api/messages/{msg.id}/feedback',
                              json={'feedback': 'like'})
        assert response.status_code == 200
        
        # Verify feedback was saved
        db.session.refresh(msg)
        assert msg.feedback == 'like'
    
    def test_submit_feedback_dislike(self, client, db):
        """Test submitting negative feedback"""
        # Create conversation and message
        create_resp = client.post('/api/conversations', json={'title': 'Feedback Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        from app.models import Message
        msg = Message(conversation_id=conv_id, role='assistant', content='Test')
        db.session.add(msg)
        db.session.commit()
        
        # Submit feedback
        response = client.post(f'/api/messages/{msg.id}/feedback',
                              json={'feedback': 'dislike'})
        assert response.status_code == 200
        
        # Verify feedback was saved
        db.session.refresh(msg)
        assert msg.feedback == 'dislike'
    
    def test_submit_feedback_invalid_type(self, client, db):
        """Test submitting invalid feedback type"""
        # Create conversation and message
        create_resp = client.post('/api/conversations', json={'title': 'Feedback Test'})
        conv_id = json.loads(create_resp.data)['id']
        
        from app.models import Message
        msg = Message(conversation_id=conv_id, role='assistant', content='Test')
        db.session.add(msg)
        db.session.commit()
        
        # Submit invalid feedback
        response = client.post(f'/api/messages/{msg.id}/feedback',
                              json={'feedback': 'invalid'})
        assert response.status_code == 400
    
    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get('/api/health')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'status' in data
        assert 'database' in data
        assert 'cache' in data
    
    def test_get_models(self, client):
        """Test getting available models"""
        response = client.get('/api/models')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'models' in data
        assert 'default' in data
        assert isinstance(data['models'], list)
    
    def test_get_tools_config(self, client):
        """Test getting tools configuration"""
        response = client.get('/api/config/tools')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'knowledge_search' in data
        assert 'code_index' in data
    
    def test_update_tools_config(self, admin_client):
        """Test updating tools configuration (admin only)"""
        response = admin_client.post('/api/config/tools',
                              json={'knowledge_search': True, 'code_index': False})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['knowledge_search'] is True
        assert data['code_index'] is False
    
    def test_get_verify_config(self, client):
        """Test getting verification configuration"""
        response = client.get('/api/config/verify')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'enabled' in data
    
    def test_update_verify_config(self, admin_client):
        """Test updating verification configuration (admin only)"""
        response = admin_client.post('/api/config/verify',
                              json={'enabled': True})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['enabled'] is True
    
    def test_get_disclaimer_config(self, client):
        """Test getting disclaimer configuration"""
        response = client.get('/api/config/disclaimer')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'text' in data
    
    def test_update_disclaimer_config(self, admin_client):
        """Test updating disclaimer configuration (admin only)"""
        response = admin_client.post('/api/config/disclaimer',
                              json={'text': 'Test disclaimer'})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['text'] == 'Test disclaimer'
    
    def test_update_disclaimer_config_invalid(self, admin_client):
        """Test updating disclaimer with invalid data.

        需以管理员身份通过权限校验后，才会走到参数校验分支（400）。
        """
        response = admin_client.post('/api/config/disclaimer',
                              json={'text': 123})
        assert response.status_code == 400
    
    def test_clear_cache(self, admin_client):
        """Test clearing cache (admin only)"""
        response = admin_client.post('/api/cache/clear')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'cleared'
    
    def test_get_audit_logs(self, admin_client, db):
        """Test getting audit logs (admin only)"""
        # Create some audit logs by performing actions
        admin_client.post('/api/conversations', json={'title': 'Audit Test'})
        
        response = admin_client.get('/api/audit-logs')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert isinstance(data, list)


class TestAdminAuthorization:
    """管理员权限校验测试。

    覆盖三类身份对受保护接口的访问结果：
      - 匿名（无 JWT）        → 401
      - 普通已登录用户        → 403
      - 管理员                → 200
    """

    # 受 admin_required 保护的写接口
    PROTECTED_POSTS = [
        ('/api/config/verify', {'enabled': True}),
        ('/api/config/tools', {'knowledge_search': True}),
        ('/api/config/disclaimer', {'text': 'x'}),
        ('/api/cache/clear', None),
    ]

    def test_anonymous_rejected(self, client):
        """匿名请求应被拒绝（401），而非放行"""
        for path, payload in self.PROTECTED_POSTS:
            kwargs = {'json': payload} if payload is not None else {}
            resp = client.post(path, **kwargs)
            assert resp.status_code == 401, f"{path} 匿名访问应返回 401，实际 {resp.status_code}"

        # GET 类审计日志同样需认证
        assert client.get('/api/audit-logs').status_code == 401

    def test_normal_user_forbidden(self, auth_client):
        """已登录但非管理员应被拒绝（403）"""
        for path, payload in self.PROTECTED_POSTS:
            kwargs = {'json': payload} if payload is not None else {}
            resp = auth_client.post(path, **kwargs)
            assert resp.status_code == 403, f"{path} 普通用户应返回 403，实际 {resp.status_code}"

        assert auth_client.get('/api/audit-logs').status_code == 403

    def test_admin_allowed(self, admin_client):
        """管理员应被放行（非 401/403）"""
        for path, payload in self.PROTECTED_POSTS:
            kwargs = {'json': payload} if payload is not None else {}
            resp = admin_client.post(path, **kwargs)
            assert resp.status_code not in (401, 403), \
                f"{path} 管理员不应被拒，实际 {resp.status_code}"

        assert admin_client.get('/api/audit-logs').status_code == 200

    def test_mcp_add_requires_admin(self, client, auth_client, admin_client):
        """MCP 添加接口可执行任意命令（RCE 风险），必须限管理员"""
        payload = {'name': 'evil', 'transport': 'stdio', 'command': 'echo', 'args': ['hi']}

        assert client.post('/api/skills/mcp/servers/add', json=payload).status_code == 401
        assert auth_client.post('/api/skills/mcp/servers/add', json=payload).status_code == 403

    def test_skill_reload_requires_admin(self, client, auth_client):
        """Skill 热重载接口必须限管理员"""
        assert client.post('/api/skills/reload').status_code == 401
        assert auth_client.post('/api/skills/reload').status_code == 403

    def test_config_change_not_leaked_between_tests(self, admin_client):
        """验证 autouse fixture 生效：改完配置后不应影响后续断言。

        此处先把 disclaimer 改成非默认值，确认接口生效即可；
        还原由 _restore_global_config 保证（若失效，其它测试会顺序相关地失败）。
        """
        resp = admin_client.post('/api/config/disclaimer', json={'text': 'LEAKED'})
        assert resp.status_code == 200
        assert json.loads(resp.data)['text'] == 'LEAKED'

