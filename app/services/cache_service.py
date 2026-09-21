"""
缓存服务：提升响应速度
- 对话响应缓存（相同问题+上下文返回缓存结果）
- 查询缓存（RAG 检索结果缓存）
- 支持内存缓存和 Redis 缓存两种后端
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from flask import current_app

logger = logging.getLogger(__name__)


class MemoryCacheService:
    """内存缓存服务（开发/测试环境使用）"""
    
    def __init__(self, max_size=1000):
        self._cache = {}
        self._max_size = max_size
    
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
                logger.debug(f"Cache hit (memory): {query[:50]}")
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
        logger.debug(f"Cache set (memory): {query[:50]}")
    
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
        logger.info("Memory cache cleared")
    
    def stats(self):
        """获取缓存统计"""
        return {
            'backend': 'memory',
            'total_entries': len(self._cache),
            'max_size': self._max_size,
        }


class RedisCacheService:
    """Redis 缓存服务（生产环境使用）"""
    
    def __init__(self, redis_url, default_ttl_hours=1):
        import redis
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._default_ttl = default_ttl_hours * 3600  # 转换为秒
        self._prefix = "flask_chat:cache:"
        logger.info(f"Redis cache initialized: {redis_url}")
    
    def _generate_key(self, query, context_hash=None):
        """生成缓存键"""
        key_data = f"{query}|{context_hash or ''}"
        hash_key = hashlib.md5(key_data.encode('utf-8')).hexdigest()
        return f"{self._prefix}{hash_key}"
    
    def get(self, query, context_hash=None):
        """获取缓存"""
        key = self._generate_key(query, context_hash)
        try:
            value = self._redis.get(key)
            if value:
                logger.debug(f"Cache hit (redis): {query[:50]}")
                return json.loads(value)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
        return None
    
    def set(self, query, data, context_hash=None, ttl_hours=None):
        """设置缓存"""
        key = self._generate_key(query, context_hash)
        ttl = (ttl_hours or self._default_ttl / 3600) * 3600
        
        try:
            self._redis.setex(key, int(ttl), json.dumps(data, ensure_ascii=False))
            logger.debug(f"Cache set (redis): {query[:50]}")
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
    
    def clear(self):
        """清空所有缓存"""
        try:
            keys = self._redis.keys(f"{self._prefix}*")
            if keys:
                self._redis.delete(*keys)
            logger.info(f"Redis cache cleared: {len(keys)} keys")
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")
    
    def stats(self):
        """获取缓存统计"""
        try:
            keys = self._redis.keys(f"{self._prefix}*")
            info = self._redis.info('memory')
            return {
                'backend': 'redis',
                'total_entries': len(keys),
                'used_memory': info.get('used_memory_human', 'unknown'),
            }
        except Exception as e:
            logger.warning(f"Redis stats error: {e}")
            return {
                'backend': 'redis',
                'error': str(e)
            }


def create_cache_service():
    """工厂函数：根据配置创建缓存服务实例"""
    try:
        redis_enabled = current_app.config.get("REDIS_ENABLED", False)
        redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379/0")
        
        if redis_enabled:
            return RedisCacheService(
                redis_url=redis_url,
                default_ttl_hours=current_app.config.get("CACHE_TTL_HOURS", 1)
            )
        else:
            max_size = current_app.config.get("CACHE_MAX_SIZE", 1000)
            return MemoryCacheService(max_size=max_size)
    except Exception as e:
        logger.warning(f"Failed to create cache service, falling back to memory: {e}")
        return MemoryCacheService()


# 全局缓存实例（在应用初始化时创建）
cache_service = None


def init_cache_service():
    """初始化缓存服务（在 Flask 应用上下文中调用）"""
    global cache_service
    cache_service = create_cache_service()
    logger.info(f"Cache service initialized: {type(cache_service).__name__}")


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
