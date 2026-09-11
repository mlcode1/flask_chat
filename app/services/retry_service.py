"""
重试服务：自动重试失败的操作
"""
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def retry(max_retries=3, delay_seconds=2, exceptions=(Exception,)):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay_seconds: 重试间隔（秒），会指数增长
        exceptions: 需要重试的异常类型
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"{func.__name__} 失败，已达到最大重试次数: {e}")
                        raise
                    
                    # 指数退避
                    wait_time = delay_seconds * (2 ** attempt)
                    logger.warning(
                        f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries + 1})，"
                        f"{wait_time}秒后重试: {e}"
                    )
                    time.sleep(wait_time)
            
            raise last_exception
        
        return wrapper
    return decorator


def retry_with_fallback(primary_func, fallback_func, max_retries=3, delay_seconds=2):
    """
    带降级的重试
    
    Args:
        primary_func: 主函数
        fallback_func: 降级函数（主函数失败时调用）
        max_retries: 最大重试次数
        delay_seconds: 重试间隔
    """
    for attempt in range(max_retries + 1):
        try:
            return primary_func()
        except Exception as e:
            if attempt == max_retries:
                logger.warning(f"主函数失败，使用降级函数: {e}")
                return fallback_func()
            
            wait_time = delay_seconds * (2 ** attempt)
            logger.warning(
                f"主函数失败 (尝试 {attempt + 1}/{max_retries + 1})，"
                f"{wait_time}秒后重试: {e}"
            )
            time.sleep(wait_time)
