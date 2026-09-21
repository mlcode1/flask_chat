"""
通用工具函数：被多个模块共享的辅助逻辑
"""


def estimate_tokens(text):
    """粗略估算 token 数（中文约 1.5 token/字，英文约 0.25 token/字）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.25)
