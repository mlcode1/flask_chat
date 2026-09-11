"""
安全服务：API Key 认证、输入过滤、审计日志
"""
import re
import logging
from functools import wraps
from flask import request, jsonify, current_app
from app.extensions import db
from app.models import AuditLog

logger = logging.getLogger(__name__)

# ============================================================
# API Key 认证
# ============================================================

def require_api_key(f):
    """装饰器：校验 API Key（如果配置了 API_KEY）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = current_app.config.get("API_KEY", "")
        if not api_key:
            # 未配置 API Key 则跳过认证
            return f(*args, **kwargs)

        provided_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").replace("Bearer ", "")
            or request.args.get("api_key")
        )
        if provided_key != api_key:
            log_audit("auth_failed", detail=f"Invalid API Key from {request.remote_addr}")
            return jsonify({"error": "Unauthorized: invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated


# ============================================================
# 输入过滤 (Prompt Injection 防护)
# ============================================================

# 常见的 Prompt Injection 模式
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+the\s+above", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?your\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a\s+new\s+AI", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"print\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
]


def check_injection(text):
    """检测文本中是否包含 Prompt Injection 攻击"""
    if not text:
        return False, ""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            matched = pattern.pattern
            logger.warning("检测到 Prompt Injection: %s (pattern: %s)", text[:100], matched)
            return True, f"输入可能包含注入指令，已过滤"
    return False, ""


def filter_input(text):
    """
    过滤用户输入：
    - 检测 Prompt Injection
    - 返回 (is_safe, filtered_text, warning)
    """
    if not current_app.config.get("INPUT_FILTER_ENABLED", True):
        return True, text, ""

    is_injection, warning = check_injection(text)
    if is_injection:
        return False, text, warning

    return True, text, ""


# ============================================================
# 审计日志
# ============================================================

def log_audit(action, conversation_id=None, detail=""):
    """记录审计日志"""
    try:
        entry = AuditLog(
            action=action,
            conversation_id=conversation_id,
            detail=str(detail)[:2000],
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        logger.warning("审计日志写入失败: %s", e)
        db.session.rollback()


def get_audit_logs(limit=100, action=None):
    """获取审计日志"""
    query = AuditLog.query
    if action:
        query = query.filter_by(action=action)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "conversation_id": log.conversation_id,
            "detail": log.detail,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
