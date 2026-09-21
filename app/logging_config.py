"""
结构化日志配置
支持 JSON 格式输出、请求追踪、上下文信息
"""
import logging
import logging.config
import json
import sys
import uuid
from datetime import datetime
from flask import request, has_request_context, g


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器"""
    
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # 添加请求上下文（如果在请求上下文中）
        if has_request_context():
            log_data['request_id'] = getattr(g, 'request_id', None)
            log_data['method'] = request.method
            log_data['path'] = request.path
            log_data['remote_addr'] = request.remote_addr
            
            # 添加用户 ID（如果有）
            user_id = getattr(g, 'user_id', None)
            if user_id:
                log_data['user_id'] = user_id
            
            # 添加会话 ID（如果有）
            session_id = getattr(g, 'session_id', None)
            if session_id:
                log_data['session_id'] = session_id
        
        # 添加额外的上下文信息
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        
        return json.dumps(log_data, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """人类可读的日志格式化器（开发环境使用）"""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def format(self, record):
        # 基础格式化
        base = super().format(record)
        
        # 添加请求上下文
        if has_request_context():
            request_id = getattr(g, 'request_id', None)
            if request_id:
                base = f"{base} | request_id={request_id}"
        
        return base


def setup_logging(app):
    """配置应用日志"""
    
    # 从配置中获取日志级别和格式
    log_level = app.config.get('LOG_LEVEL', 'INFO').upper()
    log_format = app.config.get('LOG_FORMAT', 'human')  # 'json' or 'human'
    
    # 创建根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    
    # 清除现有的处理器
    root_logger.handlers = []
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level))
    
    # 根据配置选择格式化器
    if log_format == 'json':
        formatter = StructuredFormatter()
    else:
        formatter = HumanReadableFormatter()
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 降低第三方库的日志级别
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # 设置应用日志级别
    app.logger.setLevel(getattr(logging, log_level))
    
    app.logger.info(f"日志系统已初始化: level={log_level}, format={log_format}")


def generate_request_id():
    """生成唯一的请求 ID"""
    return str(uuid.uuid4())[:8]


def log_request_start():
    """记录请求开始"""
    if not has_request_context():
        return
    
    # 生成请求 ID
    g.request_id = generate_request_id()
    
    # 记录请求开始
    logger = logging.getLogger('request')
    logger.info(
        f"请求开始: {request.method} {request.path}",
        extra={'extra_data': {
            'event': 'request_start',
            'query_string': request.query_string.decode('utf-8') if request.query_string else None,
            'user_agent': request.headers.get('User-Agent')
        }}
    )


def log_request_end(response):
    """记录请求结束"""
    if not has_request_context():
        return response
    
    logger = logging.getLogger('request')
    
    # 计算请求耗时（如果有开始时间）
    duration_ms = None
    start_time = getattr(g, 'request_start_time', None)
    if start_time:
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    logger.info(
        f"请求完成: {request.method} {request.path} - {response.status_code}",
        extra={'extra_data': {
            'event': 'request_end',
            'status_code': response.status_code,
            'duration_ms': duration_ms,
            'content_length': response.content_length
        }}
    )
    
    return response


class ContextLogger:
    """带上下文的日志记录器"""
    
    def __init__(self, name):
        self.logger = logging.getLogger(name)
    
    def _add_context(self, extra=None):
        """添加上下文信息到日志记录"""
        extra_data = extra or {}
        
        if has_request_context():
            extra_data['request_id'] = getattr(g, 'request_id', None)
            extra_data['user_id'] = getattr(g, 'user_id', None)
            extra_data['session_id'] = getattr(g, 'session_id', None)
        
        return extra_data
    
    def debug(self, msg, extra=None):
        self.logger.debug(msg, extra={'extra_data': self._add_context(extra)})
    
    def info(self, msg, extra=None):
        self.logger.info(msg, extra={'extra_data': self._add_context(extra)})
    
    def warning(self, msg, extra=None):
        self.logger.warning(msg, extra={'extra_data': self._add_context(extra)})
    
    def error(self, msg, extra=None):
        self.logger.error(msg, extra={'extra_data': self._add_context(extra)})
    
    def exception(self, msg, extra=None):
        self.logger.exception(msg, extra={'extra_data': self._add_context(extra)})


def get_logger(name):
    """获取带上下文的日志记录器"""
    return ContextLogger(name)
