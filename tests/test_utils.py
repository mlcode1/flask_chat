"""
Tests for utility functions
"""
import pytest
from app.utils import estimate_tokens


class TestEstimateTokens:
    """Test suite for estimate_tokens function"""
    
    def test_empty_string(self):
        """Test with empty string"""
        assert estimate_tokens("") == 0
    
    def test_none_input(self):
        """Test with None input"""
        assert estimate_tokens(None) == 0
    
    def test_english_text(self):
        """Test with pure English text"""
        text = "Hello world"
        tokens = estimate_tokens(text)
        # Rough estimate: ~4 tokens per 3 words
        assert tokens > 0
        assert tokens < len(text)
    
    def test_chinese_text(self):
        """Test with pure Chinese text"""
        text = "你好世界"
        tokens = estimate_tokens(text)
        # Chinese characters typically map to 1-2 tokens each
        assert tokens >= 4
        assert tokens <= 8
    
    def test_mixed_text(self):
        """Test with mixed English and Chinese"""
        text = "Hello 你好 World 世界"
        tokens = estimate_tokens(text)
        assert tokens > 0
    
    def test_long_text(self):
        """Test with longer text"""
        text = "This is a longer piece of text " * 10
        tokens = estimate_tokens(text)
        assert tokens > 50
    
    def test_code_snippet(self):
        """Test with code snippet"""
        code = """
def hello():
    print("Hello, World!")
    return True
"""
        tokens = estimate_tokens(code)
        assert tokens > 0
