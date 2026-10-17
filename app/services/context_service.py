"""
上下文服务：对话历史管理、摘要压缩、长期记忆
增强：自适应上下文窗口、结构化摘要、记忆提取、渐进式压缩
"""
import json
import logging
from datetime import datetime, timezone
from langsmith import traceable
from flask import current_app
from app.extensions import db
from app.models import Conversation, Message
from app.utils import estimate_tokens

logger = logging.getLogger(__name__)


# 模型上下文窗口大小映射（token数）
MODEL_CONTEXT_WINDOWS = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    # 火山引擎 / 智谱
    "Qwen3.7-Max": 32768,
    "Qwen3.7": 32768,
    "Qwen3": 32768,
    "glm-5.2": 128000,
    "glm-4": 128000,
    # Ollama 本地模型
    "qwen2.5:7b": 32768,
    "qwen2.5:14b": 32768,
    "qwen2.5:3b": 32768,
    "llama3.1:8b": 128000,
    "llama3.1:70b": 128000,
    "mistral:7b": 32768,
    "deepseek-r1:7b": 65536,
    "deepseek-r1:14b": 65536,
}

# 默认上下文窗口（未知模型）
DEFAULT_CONTEXT_WINDOW = 8192

# 输出预留比例（给模型回复留空间）
OUTPUT_RESERVE_RATIO = 0.25

# 压缩触发比例（上下文使用率超过此比例时触发压缩）
COMPRESS_TRIGGER_RATIO = 0.7

# 压缩后保留比例（压缩后上下文占窗口的比例）
COMPRESS_RETAIN_RATIO = 0.5

# 最少保留消息数
MIN_RECENT_MESSAGES = 4


class ContextService:

    def __init__(self, max_tokens=None, model=None):
        """
        初始化上下文服务
        
        Args:
            max_tokens: 最大上下文 token 数（如果为 None，根据模型自动计算）
            model: 当前使用的模型名称（用于自动计算上下文窗口）
        """
        self.model = model or current_app.config.get("OPENAI_MODEL", "gpt-4o")
        
        if max_tokens is not None:
            self.max_tokens = max_tokens
        else:
            # 根据模型自动计算上下文窗口
            context_window = self._get_model_context_window(self.model)
            # 预留输出空间
            self.max_tokens = int(context_window * (1 - OUTPUT_RESERVE_RATIO))
            logger.debug(f"模型 {self.model}: 上下文窗口={context_window}, 输入上限={self.max_tokens}")
    
    @staticmethod
    def _get_model_context_window(model_name):
        """获取模型的上下文窗口大小"""
        # 精确匹配
        if model_name in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[model_name]
        
        # 模糊匹配（去掉版本号等后缀）
        for key, value in MODEL_CONTEXT_WINDOWS.items():
            if key.lower() in model_name.lower() or model_name.lower() in key.lower():
                return value
        
        return DEFAULT_CONTEXT_WINDOW

    def count_tokens(self, text):
        """粗略估算 token 数（中文约 1.5 token/字，英文约 0.25 token/字）"""
        return estimate_tokens(text)

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

        # 1. 加入系统提示
        system_content = self._build_system_context(conversation)
        system_tokens = self.count_tokens(system_content) if system_content else 0
        if system_content:
            context.append({
                "role": "system",
                "content": system_content
            })

        # 2. 计算可用于历史消息的 token 预算
        available_tokens = self.max_tokens - system_tokens

        # 3. 加入未压缩的最近消息（从后往前，直到 token 超限）
        recent_messages = []
        total_tokens = 0
        for msg in reversed(messages):
            msg_tokens = self.count_tokens(msg.content or "")
            # 工具调用也占 token
            if msg.tool_calls:
                msg_tokens += sum(
                    self.count_tokens(json.dumps(tc, ensure_ascii=False))
                    for tc in msg.tool_calls if isinstance(tc, dict)
                ) * 0.3  # 工具调用大约占 30% 的额外 token
            
            if total_tokens + msg_tokens > available_tokens:
                break
            total_tokens += msg_tokens
            entry = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
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
        
        usage_ratio = (system_tokens + total_tokens) / self.max_tokens if self.max_tokens > 0 else 0
        logger.debug(
            f"构建上下文: {len(recent_messages)}条消息, "
            f"系统提示{system_tokens}token, 历史{total_tokens}token, "
            f"使用率{usage_ratio:.1%}"
        )
        
        return context

    def _build_system_context(self, conversation):
        """构建系统上下文：对话模板系统提示 + 工具状态 + 摘要 + 长期记忆"""
        parts = []
        
        # 0. 默认系统提示（当没有模板系统提示时，提供基础指引）
        default_prompt = """你是一个智能助手，具备以下工具能力：
- **calculate__evaluate**: 执行数学表达式计算（如 "2 + 3 * 4"）。当用户提出计算问题时，请始终使用此工具而非自行计算。
- **calculate__convert_unit**: 执行单位转换（如温度、长度、重量等）。
- **calculate__math_function**: 执行数学函数计算（如 sin, cos, tan, log, sqrt 等）。
- **get_current_time**: 获取当前日期和时间。
- **execute_code**: 执行 Python 代码。当用户需要数据分析、文本处理或复杂计算时，请使用此工具。
- **query_database**: 执行只读 SQL 查询。
- **read_file**: 读取知识库中的文件。
- **list_dir**: 列出目录内容，查看项目结构（仅当用户有已索引代码库时可用）。
- **read_code_file**: 读取代码文件的完整内容（仅当用户有已索引代码库时可用）。
- **write_file**: 创建或覆盖写入文件（仅当用户有已索引代码库时可用）。
- **edit_file**: 局部编辑文件中的指定文本片段（仅当用户有已索引代码库时可用）。
- **run_shell**: 执行 shell 命令，用于 git 操作、编译构建等（仅当用户有已索引代码库时可用）。

重要原则：
1. 当有对应工具可用时，始终优先使用工具而非自行处理。
2. 数学计算务必使用 calculate__* 工具，不要自行计算。
3. 回复使用中文，除非用户要求其他语言。
4. 如果用户要求修改代码文件，先使用 read_code_file 查看当前内容，再使用 edit_file 或 write_file 修改。"""

        # 1. 优先使用对话模板的系统提示词
        if conversation.system_prompt:
            parts.append(conversation.system_prompt)
        else:
            parts.append(default_prompt)
        
        # 1.5 动态添加 MCP 工具说明（如果有已连接的 MCP 服务器）
        mcp_enabled = current_app.config.get("MCP_ENABLED", False)
        if mcp_enabled:
            try:
                from app.services.tool_service import get_mcp_manager
                mcp_manager = get_mcp_manager()
                mcp_tools = mcp_manager.get_all_tools()
                if mcp_tools:
                    mcp_tool_desc = "\n\n此外，你还接入了以下外部工具（MCP），请优先使用这些专用工具：\n"
                    for tool in mcp_tools:
                        func_name = tool['function']['name']
                        desc = tool['function']['description']
                        mcp_tool_desc += f"- **{func_name}**: {desc}\n"
                    mcp_tool_desc += "\n**重要**：当 MCP 工具与通用工具（如 execute_code）功能重叠时，优先使用 MCP 工具。例如，抓取网页内容应使用 fetch__fetch 而非 execute_code。"
                    parts.append(mcp_tool_desc)
            except Exception as e:
                logger.warning(f"Failed to add MCP tools to system prompt: {e}")
        
        # 2. 添加工具状态提示（动态告知 LLM 当前可用的功能）
        knowledge_enabled = current_app.config.get("KNOWLEDGE_SEARCH_ENABLED", False)
        code_index_enabled = current_app.config.get("CODE_INDEX_ENABLED", False)
        
        tool_status = []
        if not knowledge_enabled:
            tool_status.append("- 知识库查询功能已关闭，不要提及或使用 knowledge_search 工具")
        if not code_index_enabled:
            tool_status.append("- 代码库查询功能已关闭，不要提及或使用 search_code 工具")
        
        if tool_status:
            parts.append(f"## 当前工具状态\n" + "\n".join(tool_status))
        
        # 3. 加入长期记忆
        if conversation.memory:
            parts.append(f"## 用户信息（长期记忆）\n{conversation.memory}")
        
        # 4. 加入对话摘要
        if conversation.summary:
            parts.append(f"## 对话历史摘要\n{conversation.summary}")
        
        if not parts:
            return None
        
        return "\n\n".join(parts)

    def should_compress(self, conversation_id):
        """判断是否需要压缩上下文（自适应：基于模型实际上下文窗口）"""
        messages = Message.query.filter_by(
            conversation_id=conversation_id,
            compressed=False
        ).all()
        total_tokens = sum(self.count_tokens(m.content or "") for m in messages)
        
        # 压缩阈值 = 上下文窗口 * 压缩触发比例
        compress_threshold = int(self.max_tokens * COMPRESS_TRIGGER_RATIO)
        
        if total_tokens > compress_threshold:
            logger.info(
                f"触发压缩: 当前{total_tokens}token > 阈值{compress_threshold}token "
                f"(使用率{total_tokens / self.max_tokens:.1%})"
            )
            return True
        return False

    @traceable(name="compress_context")
    def compress_context(self, conversation_id, ai_service):
        """压缩上下文：智能决定保留消息数，生成结构化摘要 + 提取记忆"""
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return

        messages = Message.query.filter_by(
            conversation_id=conversation_id,
            compressed=False
        ).order_by(Message.created_at).all()
        
        if len(messages) < MIN_RECENT_MESSAGES + 2:
            return

        # 智能决定保留多少条消息（根据 token 预算）
        retain_count = self._calculate_retain_count(messages)
        
        older = messages[:-retain_count]
        older_text = "\n".join(f"{m.role}: {m.content}" for m in older if m.content)
        
        if not older_text.strip():
            return

        logger.info(f"压缩上下文: 保留最近{retain_count}条, 压缩{len(older)}条消息")

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
                try:
                    new_memory = json.loads(memory_json)
                    existing_memory = json.loads(conversation.memory) if conversation.memory else {}
                    
                    for key in ["preferences", "facts", "decisions"]:
                        if new_memory.get(key) and new_memory[key] != "无":
                            existing = existing_memory.get(key, "")
                            if existing:
                                existing_memory[key] = f"{existing}\n{new_memory[key]}"
                            else:
                                existing_memory[key] = new_memory[key]
                    
                    conversation.memory = json.dumps(existing_memory, ensure_ascii=False)
                except json.JSONDecodeError:
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
        logger.info(f"压缩完成: 压缩了{len(older)}条消息")

    def _calculate_retain_count(self, messages):
        """智能计算应该保留多少条未压缩消息"""
        # 从最近的消息往前累加 token，直到达到保留预算
        retain_budget = int(self.max_tokens * COMPRESS_RETAIN_RATIO)
        total = 0
        count = 0
        
        for msg in reversed(messages):
            msg_tokens = self.count_tokens(msg.content or "")
            if msg.tool_calls:
                msg_tokens += sum(
                    self.count_tokens(json.dumps(tc, ensure_ascii=False))
                    for tc in msg.tool_calls if isinstance(tc, dict)
                ) * 0.3
            
            if total + msg_tokens > retain_budget and count >= MIN_RECENT_MESSAGES:
                break
            
            total += msg_tokens
            count += 1
        
        # 至少保留 MIN_RECENT_MESSAGES 条
        return max(count, MIN_RECENT_MESSAGES)

    def estimate_context_tokens(self, messages):
        """估算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += self.count_tokens(part.get("text", ""))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        total += 85
            else:
                total += self.count_tokens(str(content))
        return total
    
    def get_context_usage_info(self, conversation_id):
        """获取当前上下文使用率信息（供前端展示）"""
        conversation = db.session.get(Conversation, conversation_id)
        if not conversation:
            return None
        
        messages = conversation.messages.filter_by(compressed=False).all()
        total_tokens = sum(self.count_tokens(m.content or "") for m in messages)
        
        return {
            "model": self.model,
            "context_window": self._get_model_context_window(self.model),
            "max_input_tokens": self.max_tokens,
            "used_tokens": total_tokens,
            "usage_ratio": round(total_tokens / self.max_tokens, 3) if self.max_tokens > 0 else 0,
            "message_count": len(messages),
            "compressed_count": conversation.messages.filter_by(compressed=True).count(),
            "will_compress": self.should_compress(conversation_id),
        }
