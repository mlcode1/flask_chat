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
        
        assert conv.title == "New Conversation"
        assert conv.summary == ""
        assert conv.memory == ""
    
    def test_conversation_to_dict(self, db):
        """Test conversation serialization"""
        conv = Conversation(title="Test")
        db.session.add(conv)
        db.session.commit()
        
        data = conv.to_dict()
        
        assert data['id'] == conv.id
        assert data['title'] == "Test"
        assert 'created_at' in data
        assert 'updated_at' in data


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
