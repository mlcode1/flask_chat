import os
from functools import wraps
from flask import request


def _build_disclaimer():
    """构建免责声明片段。

    使用 HTML 分隔线 + 纯文本，避免 markdown 语法（*...*、---）
    被前端 marked 渲染成斜体/强调或失效的分隔线。
    """
    text = os.getenv("AI_DISCLAIMER_TEXT", "").strip()
    if not text:
        return ""
    return f'\n<hr class="disclaimer-divider" />\n<div class="disclaimer-text">{_escape_html(text)}</div>'


def _escape_html(s):
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def get_disclaimer():
    """动态获取免责声明（每次调用时读取最新配置）。"""
    return _build_disclaimer()


def ai_disclaimer_middleware(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated
