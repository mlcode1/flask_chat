"""
AI 服务：流式响应、工具调用循环、Token 统计、多模态支持、重试与降级
"""
import json
import logging
from openai import OpenAI
from flask import current_app
from langsmith import traceable
from app.services.tool_service import get_tools, execute_tool

logger = logging.getLogger(__name__)


class AIService:

    def __init__(self, model=None):
        self.client = OpenAI(
            api_key=current_app.config["OPENAI_API_KEY"],
            base_url=current_app.config["OPENAI_BASE_URL"],
        )
        self.model = model or current_app.config["OPENAI_MODEL"]
        self.fallback_model = current_app.config.get("FALLBACK_MODEL", "")

    def _call_with_retry(self, call_func, max_retries=None):
        """带重试和降级的 API 调用"""
        if max_retries is None:
            max_retries = current_app.config.get("MAX_RETRIES", 3)
        
        delay = current_app.config.get("RETRY_DELAY_SECONDS", 2)
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return call_func()
            except Exception as e:
                last_exception = e
                
                if attempt == max_retries:
                    logger.error(f"API 调用失败，已达到最大重试次数: {e}")
                    raise
                
                # 指数退避
                import time
                wait_time = delay * (2 ** attempt)
                logger.warning(
                    f"API 调用失败 (尝试 {attempt + 1}/{max_retries + 1})，"
                    f"{wait_time}秒后重试: {e}"
                )
                time.sleep(wait_time)
        
        raise last_exception

    @traceable(name="chat_stream_response", run_type="llm")
    def stream_response(self, messages, on_chunk=None, on_tool_call=None, stop_event=None):
        full_content = ""
        tool_calls_accumulator = {}

        while True:
            if stop_event and stop_event.is_set():
                yield "[已打断]"
                return

            has_tool_calls = False
            tools = get_tools()
            
            # 带重试的 API 调用
            def call_api():
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    stream=True,
                )
            
            try:
                response = self._call_with_retry(call_api)
            except Exception as e:
                # 主模型失败，尝试降级模型
                if self.fallback_model and self.model != self.fallback_model:
                    logger.warning(f"主模型 {self.model} 失败，降级到 {self.fallback_model}")
                    original_model = self.model
                    self.model = self.fallback_model
                    try:
                        response = self._call_with_retry(call_api)
                        self.model = original_model  # 恢复
                    except Exception as fallback_error:
                        self.model = original_model
                        raise fallback_error
                else:
                    raise

            for chunk in response:
                if stop_event and stop_event.is_set():
                    yield "[已打断]"
                    return

                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if delta.tool_calls:
                    has_tool_calls = True
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""}
                            }
                        if tc.id:
                            tool_calls_accumulator[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_accumulator[idx]["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_accumulator[idx]["function"]["arguments"] += tc.function.arguments

                if delta.content:
                    full_content += delta.content
                    if on_chunk:
                        on_chunk(delta.content)
                    yield delta.content

            if not has_tool_calls:
                break

            tool_calls_list = list(tool_calls_accumulator.values())
            messages = list(messages) + [
                {
                    "role": "assistant",
                    "content": full_content or None,
                    "tool_calls": tool_calls_list
                }
            ]

            for tc in tool_calls_list:
                result = execute_tool(tc["function"]["name"], tc["function"]["arguments"])
                if on_tool_call:
                    on_tool_call(tc, result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            full_content = ""
            tool_calls_accumulator = {}

    @traceable(name="chat_sync_complete", run_type="llm")
    def sync_complete(self, prompt, system_prompt=None):
        """同步调用（用于摘要、验证等内部场景）"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        def call_api():
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
        
        try:
            response = self._call_with_retry(call_api)
        except Exception as e:
            # 主模型失败，尝试降级模型
            if self.fallback_model and self.model != self.fallback_model:
                logger.warning(f"主模型 {self.model} 失败，降级到 {self.fallback_model}")
                original_model = self.model
                self.model = self.fallback_model
                try:
                    response = self._call_with_retry(call_api)
                    self.model = original_model
                except Exception as fallback_error:
                    self.model = original_model
                    raise fallback_error
            else:
                raise
        
        return response.choices[0].message.content

    def estimate_tokens(self, text):
        """粗略估算 token 数"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)
