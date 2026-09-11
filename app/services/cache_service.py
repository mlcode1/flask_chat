"""
缓存服务：提升响应速度
- 对话响应缓存（相同问题+上下文返回缓存结果）
- 查询缓存（RAG 检索结果缓存）
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from app.extensions import db
from app.models import Conversation

logger = logging.getLogger(__name__)


class CacheService:
    """简单的内存缓存服务"""
    
    def __init__(self):
        # 内存缓存（实际生产环境应使用 Redis）
        self._cache = {}
        self._max_size = 1000  # 最多缓存 1000 个条目
    
    def _generate_key(self, query, context_hash=None):
        """生成缓存键"""
        key_data = f"{query}|{context_hash or ''}"
        return hashlib.md5(key_data.encode('utf-8')).hexdigest()
    
    def get(self, query, context_hash=None):
        """获取缓存"""
        key = self._generate_key(query, context_hash)
        if key in self._cache:
            entry = self._cache[key]
            # 检查是否过期（默认 1 小时）
            if entry['expires_at'] > datetime.now():
                logger.debug(f"Cache hit: {query[:50]}")
                return entry['data']
            else:
                # 过期删除
                del self._cache[key]
        return None
    
    def set(self, query, data, context_hash=None, ttl_hours=1):
        """设置缓存"""
        key = self._generate_key(query, context_hash)
        
        # 清理过期缓存
        if len(self._cache) >= self._max_size:
            self._cleanup()
        
        self._cache[key] = {
            'data': data,
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=ttl_hours),
            'query': query[:100]  # 用于调试
        }
        logger.debug(f"Cache set: {query[:50]}")
    
    def _cleanup(self):
        """清理过期缓存"""
        now = datetime.now()
        expired_keys = [k for k, v in self._cache.items() if v['expires_at'] <= now]
        for key in expired_keys:
            del self._cache[key]
        logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
    
    def clear(self):
        """清空所有缓存"""
        self._cache.clear()
        logger.info("Cache cleared")
    
    def stats(self):
        """获取缓存统计"""
        return {
            'total_entries': len(self._cache),
            'max_size': self._max_size,
        }


# 全局缓存实例
cache_service = CacheService()


def hash_context(messages):
    """对上下文进行哈希，用于缓存键"""
    if not messages:
        return None
    # 只取最后 5 条消息的内容作为上下文哈希
    recent = messages[-5:] if len(messages) > 5 else messages
    context_str = "|".join([
        f"{m.get('role', '')}:{m.get('content', '')[:200]}"
        for m in recent
    ])
    return hashlib.md5(context_str.encode('utf-8')).hexdigest()
