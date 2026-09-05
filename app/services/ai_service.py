import json
from openai import OpenAI
from flask import current_app
from langsmith import traceable
from app.services.tool_service import TOOLS, execute_tool


class AIService:

    def __init__(self, model=None):
        self.client = OpenAI(
            api_key=current_app.config["OPENAI_API_KEY"],
            base_url=current_app.config["OPENAI_BASE_URL"],
        )
        self.model = model or current_app.config["OPENAI_MODEL"]

    @traceable(name="chat_stream_response", run_type="llm")
    def stream_response(self, messages, on_chunk=None, on_tool_call=None, stop_event=None):
        full_content = ""
        tool_calls_accumulator = {}

        while True:
            if stop_event and stop_event.is_set():
                yield "[已打断]"
                return

            has_tool_calls = False
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                stream=True,
            )

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
    def sync_complete(self, prompt):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
