"""
上下文服务：对话历史管理、摘要压缩、长期记忆
增强：结构化摘要、记忆提取、渐进式压缩
"""
import json
import logging
from datetime import datetime, timezone
from langsmith import traceable
from app.extensions import db
from app.models import Conversation, Message

logger = logging.getLogger(__name__)


class ContextService:

    def __init__(self, max_tokens=4000):
        self.max_tokens = max_tokens

    def count_tokens(self, text):
        """粗略估算 token 数（中文约 1.5 token/字，英文约 0.25 token/字）"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    @traceable(name="build_chat_context")
    def build_context(self, conversation_id):
        """构建对话上下文：系统提示 + 记忆 + 摘要 + 最近消息"""
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return []

        messages = conversation.messages.filter_by(compressed=False).all()
        all_messages = conversation.messages.all()
        if not all_messages:
            return []

        context = []

        # 1. 加入系统提示（如果有长期记忆）
        system_content = self._build_system_context(conversation)
        if system_content:
            context.append({
                "role": "system",
                "content": system_content
            })

        # 2. 加入未压缩的最近消息（从后往前，直到 token 超限）
        recent_messages = []
        total_tokens = 0
        for msg in reversed(messages):
            msg_tokens = self.count_tokens(msg.content or "")
            if total_tokens + msg_tokens > self.max_tokens:
                break
            total_tokens += msg_tokens
            entry = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                # 转换为 OpenAI 标准格式（去除 _result 等自定义字段）
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                        },
                    }
                    for tc in msg.tool_calls
                    if isinstance(tc, dict) and tc.get("function")
                ] or None
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            # 多模态：如果有图片，加入 image_url
            if msg.image_urls:
                entry["content"] = [
                    {"type": "text", "text": msg.content or ""},
                    *[{"type": "image_url", "image_url": {"url": url}} for url in msg.image_urls]
                ]
            recent_messages.insert(0, entry)

        context.extend(recent_messages)
        return context

    def _build_system_context(self, conversation):
        """构建系统上下文：摘要 + 长期记忆"""
        parts = []
        
        if conversation.memory:
            parts.append(f"## 用户信息（长期记忆）\n{conversation.memory}")
        
        if conversation.summary:
            parts.append(f"## 对话历史摘要\n{conversation.summary}")
        
        if not parts:
            return None
        
        return "\n\n".join(parts)

    def should_compress(self, conversation_id):
        """判断是否需要压缩上下文"""
        messages = Message.query.filter_by(
            conversation_id=conversation_id,
            compressed=False
        ).all()
        total_tokens = sum(self.count_tokens(m.content or "") for m in messages)
        return total_tokens > self.max_tokens * 1.5

    @traceable(name="compress_context")
    def compress_context(self, conversation_id, ai_service):
        """压缩上下文：生成结构化摘要 + 提取记忆，保留最近消息"""
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return

        messages = Message.query.filter_by(
            conversation_id=conversation_id,
            compressed=False
        ).order_by(Message.created_at).all()
        
        if len(messages) < 6:
            return

        # 保留最近 4 条消息，其余压缩
        older = messages[:-4]
        older_text = "\n".join(f"{m.role}: {m.content}" for m in older if m.content)

        # 1. 生成结构化摘要
        summary_prompt = f"""请将以下对话历史压缩为结构化摘要。要求：
1. 用简洁的中文总结对话主题和关键结论
2. 保留用户提出的重要问题和 AI 给出的关键回答
3. 如果涉及具体数据、决策或计划，务必保留
4. 控制在 200 字以内

对话历史：
{older_text}

结构化摘要："""

        try:
            new_summary = ai_service.sync_complete(summary_prompt)
        except Exception as e:
            logger.warning("生成摘要失败: %s", e)
            return

        # 2. 提取长期记忆（用户偏好、重要事实）
        memory_prompt = f"""从以下对话中提取需要长期记住的信息（如果有的话）。
提取类型：
- 用户偏好（如语言、风格、喜欢的回答方式）
- 重要事实（如姓名、职业、项目信息）
- 关键决策或结论

如果没有值得记住的信息，返回"无"。

对话：
{older_text}

提取的信息（JSON 格式）：
{{
  "preferences": "用户偏好（如有）",
  "facts": "重要事实（如有）",
  "decisions": "关键决策（如有）"
}}

只输出 JSON，不要其他内容："""

        try:
            memory_json = ai_service.sync_complete(memory_prompt)
            if memory_json and memory_json.strip() != "无":
                # 解析并合并到现有记忆
                try:
                    new_memory = json.loads(memory_json)
                    existing_memory = json.loads(conversation.memory) if conversation.memory else {}
                    
                    # 合并记忆
                    for key in ["preferences", "facts", "decisions"]:
                        if new_memory.get(key) and new_memory[key] != "无":
                            existing = existing_memory.get(key, "")
                            if existing:
                                existing_memory[key] = f"{existing}\n{new_memory[key]}"
                            else:
                                existing_memory[key] = new_memory[key]
                    
                    conversation.memory = json.dumps(existing_memory, ensure_ascii=False)
                except json.JSONDecodeError:
                    # 如果不是 JSON，作为文本追加
                    if conversation.memory:
                        conversation.memory = f"{conversation.memory}\n{memory_json}"
                    else:
                        conversation.memory = memory_json
        except Exception as e:
            logger.warning("提取记忆失败: %s", e)

        # 3. 更新摘要
        if conversation.summary:
            conversation.summary = f"{conversation.summary}\n\n{new_summary}"
        else:
            conversation.summary = new_summary

        # 4. 标记旧消息为已压缩（不删除，保留审计记录）
        for msg in older:
            msg.compressed = True

        db.session.commit()

    def estimate_context_tokens(self, messages):
        """估算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态消息
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += self.count_tokens(part.get("text", ""))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        total += 85  # 图片大约 85 tokens
            else:
                total += self.count_tokens(str(content))
        return total
