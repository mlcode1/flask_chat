from functools import wraps
from flask import request

AI_DISCLAIMER = "\n\n---\n*消息来源于大模型返回*"


def ai_disclaimer_middleware(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated
