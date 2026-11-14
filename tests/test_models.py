"""
Tests for database models
"""
import pytest
from datetime import datetime, timezone
from app.models import Conversation, Message


class TestConversation:
    """Test suite for Conversation model"""
    
    def test_create_conversation(self, db):
        """Test creating a new conversation"""
        conv = Conversation(title="Test Conversation")
        db.session.add(conv)
        db.session.commit()
        
        assert conv.id is not None
        assert conv.title == "Test Conversation"
        assert conv.created_at is not None
        assert conv.updated_at is not None
    
    def test_conversation_defaults(self, db):
        """Test conversation default values"""
        conv = Conversation()
        db.session.add(conv)
        db.session.commit()
        
        assert conv.title == "新对话"
        assert conv.summary == ""
        assert conv.memory == ""
    
    def test_conversation_to_share_dict(self, db):
        """Test conversation serialization for sharing.

        注意：Conversation 没有 to_dict()，实际序列化方法是 to_share_dict()。
        它刻意保留 created_at 为 datetime 对象（而非 ISO 字符串），
        因为 shared.html 模板会调用 .strftime() 格式化。
        """
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        # 附带一条消息，验证嵌套序列化
        msg = Message(conversation_id=conv.id, role="user", content="Hi")
        db.session.add(msg)
        db.session.commit()
        
        data = conv.to_share_dict()
        
        assert data['id'] == conv.id
        assert data['title'] == "Test"
        # created_at 必须保持 datetime，不能是字符串
        assert isinstance(data['created_at'], datetime)
        assert len(data['messages']) == 1
        assert data['messages'][0]['content'] == "Hi"
        assert data['messages'][0]['role'] == "user"
        assert 'image_urls' in data['messages'][0]


class TestMessage:
    """Test suite for Message model"""
    
    def test_create_message(self, db):
        """Test creating a new message"""
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        
        msg = Message(
            conversation_id=conv.id,
            role="user",
            content="Hello, world!"
        )
        db.session.add(msg)
        db.session.commit()
        
        assert msg.id is not None
        assert msg.conversation_id == conv.id
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.created_at is not None
    
    def test_message_defaults(self, db):
        """Test message default values"""
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        
        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content="Response"
        )
        db.session.add(msg)
        db.session.commit()
        
        assert msg.token_count == 0
        assert msg.status == "completed"
        assert msg.interrupted is False
        assert msg.tool_calls == []
    
    def test_message_relationship(self, db):
        """Test message-conversation relationship"""
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        
        msg1 = Message(conversation_id=conv.id, role="user", content="Hi")
        msg2 = Message(conversation_id=conv.id, role="assistant", content="Hello")
        db.session.add_all([msg1, msg2])
        db.session.commit()
        
        # Test relationship
        assert len(conv.messages.all()) == 2
        assert msg1.conversation.id == conv.id
        assert msg2.conversation.id == conv.id
    
    def test_message_cascade_delete(self, db):
        """Test that messages are deleted when conversation is deleted"""
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        
        msg = Message(conversation_id=conv.id, role="user", content="Test")
        db.session.add(msg)
        db.session.commit()
        
        conv_id = conv.id
        msg_id = msg.id
        
        db.session.delete(conv)
        db.session.commit()
        
        # Message should be deleted
        assert Message.query.get(msg_id) is None
