from app.extensions import db
from app.models import Conversation, Message


class ContextService:

    def __init__(self, max_tokens=4000):
        self.max_tokens = max_tokens

    def count_tokens(self, text):
        return len(text)

    def build_context(self, conversation_id):
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return []

        messages = conversation.messages.all()
        if not messages:
            return []

        context = []
        if conversation.summary:
            context.append({
                "role": "system",
                "content": f"以下是之前对话的总结：{conversation.summary}"
            })

        recent_messages = []
        total_tokens = 0
        for msg in reversed(messages):
            msg_tokens = self.count_tokens(msg.content or "")
            if total_tokens + msg_tokens > self.max_tokens:
                break
            total_tokens += msg_tokens
            entry = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            recent_messages.insert(0, entry)

        context.extend(recent_messages)
        return context

    def should_compress(self, conversation_id):
        messages = Message.query.filter_by(conversation_id=conversation_id).all()
        total_tokens = sum(self.count_tokens(m.content or "") for m in messages)
        return total_tokens > self.max_tokens * 1.5

    def compress_context(self, conversation_id, ai_service):
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return

        messages = conversation.messages.all()
        if len(messages) < 6:
            return

        older = messages[:-4]
        older_text = "\n".join(f"{m.role}: {m.content}" for m in older if m.content)

        summary_prompt = (
            f"请将以下对话历史压缩为简洁的总结，保留关键信息和上下文：\n\n{older_text}"
        )
        summary = ai_service.sync_complete(summary_prompt)

        if conversation.summary:
            conversation.summary = f"{conversation.summary}\n\n{summary}"
        else:
            conversation.summary = summary

        for msg in older:
            db.session.delete(msg)

        db.session.commit()
