"""
Skill 基类 - 所有技能必须继承此类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable
import json
import logging

logger = logging.getLogger(__name__)


class BaseSkill(ABC):
    """Skill 基类，定义技能的接口和通用行为"""
    
    # 子类必须定义这些类属性
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化 Skill
        
        Args:
            config: Skill 配置（从 skill.json 或数据库读取）
        """
        self.config = config or {}
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._register_tools()
    
    @abstractmethod
    def _register_tools(self):
        """
        注册所有工具，子类必须实现此方法
        
        在此方法中调用 register_tool() 注册每个工具
        """
        pass
    
    def register_tool(
        self,
        name: str,
        handler: Callable,
        schema: Dict[str, Any]
    ):
        """
        注册单个工具
        
        Args:
            name: 工具名称（不含命名空间前缀）
            handler: 工具执行函数
            schema: 工具参数定义（OpenAI Function Calling 格式）
                {
                    "description": "工具描述",
                    "parameters": {
                        "type": "object",
                        "properties": {...},
                        "required": [...]
                    }
                }
        """
        if not name or not handler or not schema:
            raise ValueError("name, handler, and schema are required")
        
        self._tools[name] = {
            'handler': handler,
            'schema': schema
        }
        logger.debug(f"Registered tool: {self.name}__{name}")
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的定义（OpenAI Function Calling 格式）
        
        Returns:
            List[Dict]: 工具定义列表，每个工具包含 type 和 function
        """
        tools = []
        for tool_name, tool_info in self._tools.items():
            full_name = f"{self.name}__{tool_name}"  # 添加命名空间前缀
            
            tool_def = {
                "type": "function",
                "function": {
                    "name": full_name,
                    "description": tool_info['schema'].get('description', ''),
                    "parameters": tool_info['schema'].get('parameters', {
                        "type": "object",
                        "properties": {}
                    })
                }
            }
            tools.append(tool_def)
        
        return tools
    
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具
        
        Args:
            tool_name: 工具名称（不含命名空间前缀）
            arguments: 工具参数
        
        Returns:
            str: 工具执行结果（JSON 字符串）
        """
        if tool_name not in self._tools:
            error_msg = f"Tool '{tool_name}' not found in skill '{self.name}'"
            logger.error(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        
        try:
            handler = self._tools[tool_name]['handler']
            result = handler(**arguments)
            
            # 确保返回 JSON 字符串
            if isinstance(result, str):
                return result
            else:
                return json.dumps(result, ensure_ascii=False)
                
        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
    
    def on_load(self):
        """
        Skill 加载时的回调（可选）
        
        子类可以重写此方法来执行初始化操作
        """
        logger.debug(f"Skill '{self.name}' v{self.version} loaded")
    
    def on_unload(self):
        """
        Skill 卸载时的回调（可选）
        
        子类可以重写此方法来执行清理操作
        """
        logger.debug(f"Skill '{self.name}' unloaded")
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取 Skill 信息
        
        Returns:
            Dict: Skill 元数据
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tools": list(self._tools.keys()),
            "config": self.config
        }
