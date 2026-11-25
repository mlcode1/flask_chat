import os
from functools import wraps
from flask import request, current_app, has_app_context


def _build_disclaimer():
    """构建免责声明片段。

    使用 HTML 分隔线 + 纯文本，避免 markdown 语法（*...*、---）
    被前端 marked 渲染成斜体/强调或失效的分隔线。
    """
    # 数据源必须是 current_app.config，不是 os.getenv：
    # 管理界面 POST /api/config/disclaimer 写的是 config（见 routes/chat.py:170），
    # 读 os.getenv 会拿到进程启动时的旧值，导致"界面改了但实际没生效"。
    #
    # 用 has_app_context() 兜底而非直接读 current_app —— 本模块可能被
    # 无 app context 的线程调用（如后台任务），那种情况下 current_app 会抛
    # RuntimeError。退回 env 至少能给出启动时的配置，不至于让回复生成整个失败。
    if has_app_context():
        text = (current_app.config.get("AI_DISCLAIMER_TEXT") or "").strip()
    else:
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
