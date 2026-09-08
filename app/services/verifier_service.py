from openai import OpenAI
from flask import current_app
from langsmith import traceable


class VerifierService:
    """验证服务：用另一个 agent 验证 AI 回答的正确性"""

    def __init__(self, model=None):
        self.client = OpenAI(
            api_key=current_app.config["OPENAI_API_KEY"],
            base_url=current_app.config["OPENAI_BASE_URL"],
        )
        # 可以使用专门的验证模型，默认使用同一个模型
        self.model = model or current_app.config.get("VERIFY_MODEL") or current_app.config["OPENAI_MODEL"]

    @traceable(name="verify_answer", run_type="llm")
    def verify_answer(self, question, answer, context=None):
        """
        验证 AI 回答的正确性

        Args:
            question: 用户的问题
            answer: AI 的回答
            context: 额外的上下文信息（如 RAG 检索结果）

        Returns:
            dict: 包含 is_correct(bool), confidence(float), explanation(str), issues(list)
        """
        verify_prompt = f"""你是一个专业的回答验证助手。请仔细验证以下回答是否正确、准确、完整。

用户问题：
{question}

AI 回答：
{answer}
"""

        if context:
            verify_prompt += f"""
参考上下文：
{context}
"""

        verify_prompt += """
请从以下几个维度验证回答：
1. 事实准确性：回答中的事实是否正确？
2. 逻辑一致性：回答的逻辑是否自洽？
3. 完整性：是否遗漏了关键信息？
4. 清晰度：表达是否清晰易懂？

请以 JSON 格式返回验证结果：
{
  "is_correct": true/false,
  "confidence": 0.0-1.0,
  "explanation": "总体评价",
  "issues": ["问题1", "问题2", ...]
}

只返回 JSON，不要有其他内容。
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的回答验证助手，只返回 JSON 格式的结果。"},
                    {"role": "user", "content": verify_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            import json
            result = json.loads(content)

            # 确保返回格式正确
            return {
                "is_correct": result.get("is_correct", False),
                "confidence": float(result.get("confidence", 0)),
                "explanation": result.get("explanation", ""),
                "issues": result.get("issues", [])
            }

        except Exception as e:
            return {
                "is_correct": None,
                "confidence": 0,
                "explanation": f"验证失败: {str(e)}",
                "issues": []
            }
