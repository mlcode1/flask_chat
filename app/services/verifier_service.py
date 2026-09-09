import json
import logging
from openai import OpenAI
from flask import current_app
from langsmith import traceable

logger = logging.getLogger(__name__)


# 验证状态常量
STATUS_VERIFIED = "verified"   # 校验通过
STATUS_FAILED = "failed"        # 校验不通过
STATUS_SKIPPED = "skipped"      # 无需校验（问候/闲聊/创意等）或异常

# 异常 / 跳过时返回的占位结果
_SKIPPED_RESULT = {
    "status": STATUS_SKIPPED,
    "is_correct": None,
    "confidence": 0,
    "explanation": "",
    "issues": [],
}


class VerifierService:
    """验证服务：用另一个 agent 验证 AI 回答的正确性"""

    def __init__(self, model=None):
        self.client = OpenAI(
            api_key=current_app.config["OPENAI_API_KEY"],
            base_url=current_app.config["OPENAI_BASE_URL"],
        )
        self.model = (
            model
            or current_app.config.get("VERIFY_MODEL")
            or current_app.config["OPENAI_MODEL"]
        )

    @traceable(name="verify_answer", run_type="llm")
    def verify_answer(self, question, answer, context=None):
        """
        验证 AI 回答的正确性。
        流程：先判断是否需要校验 → 需要则校验 → 不需要或异常则静默跳过。

        Args:
            question: 用户的问题
            answer:   AI 的回答
            context:  额外的上下文信息（如 RAG 检索结果）

        Returns:
            dict:
              - status:      "verified" | "failed" | "skipped"
              - is_correct:  bool | None
              - confidence:  float  (0.0-1.0)
              - explanation: str
              - issues:      list[str]
        """
        prompt = self._build_prompt(question, answer, context)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个严谨的回答验证助手，只返回 JSON 格式的结果。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            result = json.loads(content)
        except Exception as e:
            # 任何异常都当作"无需校验"静默跳过，不抛错给用户
            logger.warning("验证过程异常，已跳过: %s", e)
            return dict(_SKIPPED_RESULT)

        return self._normalize(result)

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _build_prompt(self, question, answer, context):
        ctx_block = f"\n参考上下文：\n{context}\n" if context else ""
        return f"""你是一个专业的回答验证助手。请先判断"用户问题 + AI 回答"这一组内容是否需要做事实/逻辑校验，再按要求返回结果。

## 用户问题
{question}

## AI 回答
{answer}
{ctx_block}
## 判断是否需要校验

以下情况属于「无需校验」(needs_verification = false)：
- 简单问候 / 寒暄（你好、谢谢、再见等）
- 闲聊 / 主观感受 / 情感回应
- 创意类内容（写诗、写故事、起名字、生成营销文案等）
- 代码 / 命令 / 配置片段（仅检查格式，由人类 review）
- 工具调用 / 角色扮演 / 翻译改写等
- 内容太短、无法构成可校验的事实陈述

其余包含事实性陈述、推理结论、操作建议、引用数据等的情况，按以下维度严格校验：
1. 事实准确性：回答中的事实是否正确？
2. 逻辑一致性：回答的逻辑是否自洽？
3. 完整性：是否遗漏了关键信息？
4. 清晰度：表达是否清晰易懂？

## 输出格式（严格 JSON，不要其他内容）

{{
  "needs_verification": true/false,
  "skip_reason": "无需校验时的简短原因，可空",
  "is_correct": true/false/null,    // 无需校验时填 null
  "confidence": 0.0-1.0,           // 无需校验时填 0
  "explanation": "总体评价或跳过原因",
  "issues": ["问题1", "问题2"]      // 无问题时为空数组
}}
"""

    @staticmethod
    def _normalize(result):
        """将 LLM 返回的结果规整为统一结构。"""
        if not isinstance(result, dict):
            return dict(_SKIPPED_RESULT)

        # 1. 判断是否需要校验
        if not result.get("needs_verification", False):
            return {
                "status": STATUS_SKIPPED,
                "is_correct": None,
                "confidence": 0,
                "explanation": result.get("skip_reason") or result.get("explanation") or "无需校验",
                "issues": [],
            }

        # 2. 需要校验 → 根据 is_correct 区分通过/不通过
        is_correct = result.get("is_correct", False)
        try:
            confidence = float(result.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return {
            "status": STATUS_VERIFIED if is_correct else STATUS_FAILED,
            "is_correct": bool(is_correct),
            "confidence": confidence,
            "explanation": result.get("explanation", ""),
            "issues": result.get("issues") or [],
        }
