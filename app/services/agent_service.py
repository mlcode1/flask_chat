"""
Agent 工作流服务
支持多步骤推理、工具链调用、复杂任务分解
"""
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from app.services.ai_service import AIService
from app.services.tool_service import execute_tool

logger = logging.getLogger(__name__)


@dataclass
class AgentStep:
    """Agent 执行步骤"""
    step_type: str  # 'thinking', 'tool_call', 'response'
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict] = None
    tool_result: Optional[str] = None


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    final_answer: str
    steps: List[AgentStep]
    error: Optional[str] = None


class AgentWorkflow:
    """Agent 工作流引擎"""
    
    def __init__(self, model: str = None, max_steps: int = 5):
        """
        初始化 Agent
        
        Args:
            model: 使用的 LLM 模型
            max_steps: 最大执行步骤数
        """
        self.ai_service = AIService(model=model)
        self.max_steps = max_steps
    
    def run(self, task: str, context: str = "", on_step=None) -> AgentResult:
        """
        执行 Agent 任务
        
        Args:
            task: 用户任务描述
            context: 上下文信息
            on_step: 步骤回调函数，接收 AgentStep 对象
            
        Returns:
            AgentResult: 执行结果
        """
        steps = []
        conversation_history = []  # 存储完整对话历史
        
        system_prompt = """你是一个智能助手，能够使用工具解决复杂问题。

你的工作流程：
1. 分析用户任务，制定解决计划
2. 逐步执行计划，必要时调用工具获取信息
3. 综合所有信息，给出最终答案

可用工具：
- get_current_time: 获取当前时间
- calculate: 执行数学计算
- knowledge_search: 搜索知识库
- search_code: 搜索代码库
- query_database: 查询数据库
- execute_code: 执行 Python 代码

输出格式：
每次回复使用以下 JSON 格式：
{
  "thinking": "你的思考过程",
  "action": "next_step" | "use_tool" | "final_answer",
  "tool_name": "工具名称（仅当 action=use_tool 时）",
  "tool_args": {工具参数},
  "final_answer": "最终答案（仅当 action=final_answer 时）"
}

重要规则：
- 如果信息充足，直接给出 final_answer
- 如果需要更多信息，使用合适的工具
- 每个步骤都要有清晰的思考说明
"""
        
        # 初始用户提示
        initial_prompt = f"任务：{task}"
        if context:
            initial_prompt += f"\n\n上下文：{context}"
        
        conversation_history.append({"role": "user", "content": initial_prompt})
        
        for step_num in range(self.max_steps):
            logger.info(f"Agent step {step_num + 1}/{self.max_steps}")
            
            # 构建包含完整历史的提示
            current_prompt = self._build_prompt_with_history(conversation_history)
            
            # 调用 LLM
            response = self.ai_service.sync_complete(current_prompt, system_prompt=system_prompt)
            
            try:
                # 解析响应
                response_json = json.loads(response)
                thinking = response_json.get("thinking", "")
                action = response_json.get("action", "final_answer")
                
                # 记录思考步骤并触发回调
                step = AgentStep(
                    step_type="thinking",
                    content=thinking
                )
                steps.append(step)
                if on_step:
                    on_step(step)
                
                # 处理不同动作
                if action == "final_answer":
                    final_answer = response_json.get("final_answer", "")
                    step = AgentStep(
                        step_type="response",
                        content=final_answer
                    )
                    steps.append(step)
                    if on_step:
                        on_step(step)
                    return AgentResult(
                        success=True,
                        final_answer=final_answer,
                        steps=steps
                    )
                
                elif action == "use_tool":
                    tool_name = response_json.get("tool_name")
                    tool_args = response_json.get("tool_args", {})
                    
                    step = AgentStep(
                        step_type="tool_call",
                        content=f"调用工具: {tool_name}",
                        tool_name=tool_name,
                        tool_args=tool_args
                    )
                    steps.append(step)
                    if on_step:
                        on_step(step)
                    
                    # 执行工具
                    tool_result = execute_tool(tool_name, tool_args)
                    
                    steps[-1].tool_result = tool_result
                    # 再次触发回调以更新工具结果
                    if on_step:
                        on_step(steps[-1])
                    
                    # 将助手响应和工具结果加入历史
                    conversation_history.append({
                        "role": "assistant",
                        "content": response
                    })
                    conversation_history.append({
                        "role": "user",
                        "content": f"工具 {tool_name} 返回结果：\n{tool_result}\n\n请继续执行下一步。"
                    })
                
                else:
                    # 未知动作，继续下一步
                    conversation_history.append({
                        "role": "assistant",
                        "content": response
                    })
                    
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse agent response: {response}")
                steps.append(AgentStep(
                    step_type="response",
                    content=response
                ))
                return AgentResult(
                    success=True,
                    final_answer=response,
                    steps=steps
                )
            except Exception as e:
                logger.error(f"Agent step error: {e}")
                return AgentResult(
                    success=False,
                    final_answer="",
                    steps=steps,
                    error=str(e)
                )
        
        # 超过最大步骤数
        return AgentResult(
            success=False,
            final_answer="任务过于复杂，超过最大执行步骤",
            steps=steps,
            error="Max steps exceeded"
        )
    
    def _build_prompt_with_history(self, history: list) -> str:
        """
        将对话历史构建为单个提示字符串
        
        Args:
            history: 对话历史列表，每项包含 role 和 content
            
        Returns:
            str: 格式化后的提示字符串
        """
        parts = []
        for msg in history:
            role = msg["role"].capitalize()
            content = msg["content"]
            parts.append(f"{role}: {content}")
        
        return "\n\n".join(parts)


class TaskPlanner:
    """任务规划器：将复杂任务分解为子任务"""
    
    def __init__(self, model: str = None):
        self.ai_service = AIService(model=model)
    
    def plan(self, task: str) -> List[str]:
        """
        生成任务计划
        
        Args:
            task: 复杂任务描述
            
        Returns:
            List[str]: 子任务列表
        """
        prompt = f"""将以下任务分解为 3-5 个具体的子任务：

任务：{task}

要求：
1. 每个子任务应该是具体、可执行的
2. 子任务之间应有逻辑顺序
3. 每个子任务用一句话描述

输出格式：
1. 子任务1
2. 子任务2
3. 子任务3
"""
        
        response = self.ai_service.sync_complete([
            {"role": "user", "content": prompt}
        ])
        
        # 解析子任务列表
        lines = response.strip().split('\n')
        subtasks = []
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-')):
                # 移除序号和符号
                task_text = line.split('.', 1)[-1].strip()
                task_text = task_text.split('-', 1)[-1].strip()
                if task_text:
                    subtasks.append(task_text)
        
        return subtasks
