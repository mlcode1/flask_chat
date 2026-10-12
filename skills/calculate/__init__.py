"""
数学计算技能

提供安全的数学计算功能，支持基础运算和常用数学函数
"""
from app.skills.base import BaseSkill
from typing import Dict, Any
import logging
import math

logger = logging.getLogger(__name__)


class Skill(BaseSkill):
    """数学计算技能实现"""
    
    name = "calculate"
    version = "1.0.0"
    description = "执行数学计算，支持基础运算和常用数学函数"
    author = "System"
    
    def _register_tools(self):
        """注册计算工具"""
        
        # 工具 1: 执行数学表达式
        self.register_tool(
            name="evaluate",
            handler=self._evaluate,
            schema={
                "type": "function",
                "description": "执行数学表达式计算，支持加减乘除、幂运算、取余等",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "数学表达式，例如：'2 + 3 * 4', 'sqrt(16)', 'pow(2, 10)'"
                        }
                    },
                    "required": ["expression"]
                }
            }
        )
        
        # 工具 2: 单位转换
        self.register_tool(
            name="convert_unit",
            handler=self._convert_unit,
            schema={
                "type": "function",
                "description": "单位转换，支持长度、重量、温度等常用单位",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "number",
                            "description": "要转换的数值"
                        },
                        "from_unit": {
                            "type": "string",
                            "description": "原单位（km, m, cm, mm, kg, g, mg, celsius, fahrenheit）"
                        },
                        "to_unit": {
                            "type": "string",
                            "description": "目标单位"
                        }
                    },
                    "required": ["value", "from_unit", "to_unit"]
                }
            }
        )
        
        # 工具 3: 数学函数计算
        self.register_tool(
            name="math_function",
            handler=self._math_function,
            schema={
                "type": "function",
                "description": "执行数学函数计算，如三角函数、对数、指数等",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "function": {
                            "type": "string",
                            "enum": ["sin", "cos", "tan", "log", "log10", "exp", "sqrt", "abs", "ceil", "floor"],
                            "description": "数学函数名称"
                        },
                        "value": {
                            "type": "number",
                            "description": "输入值"
                        }
                    },
                    "required": ["function", "value"]
                }
            }
        )
    
    def _evaluate(self, expression: str) -> Dict[str, Any]:
        """
        执行数学表达式
        
        Args:
            expression: 数学表达式
        
        Returns:
            计算结果字典
        """
        logger.info(f"Evaluating expression: {expression}")
        
        # 安全检查：只允许数学相关的字符和函数
        allowed_chars = set("0123456789+-*/().%e ")
        allowed_functions = {
            "sqrt", "pow", "abs", "round", "floor", "ceil",
            "sin", "cos", "tan", "log", "log10", "exp"
        }
        
        # 简单的安全检查（实际生产环境应使用更严格的沙箱）
        for char in expression:
            if char not in allowed_chars and not char.isalpha():
                return {
                    "error": f"表达式包含不允许的字符: {char}",
                    "suggestion": "只允许数字、运算符和数学函数"
                }
        
        try:
            # 构建安全的计算环境
            safe_dict = {
                "sqrt": math.sqrt,
                "pow": pow,
                "abs": abs,
                "round": round,
                "floor": math.floor,
                "ceil": math.ceil,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log,
                "log10": math.log10,
                "exp": math.exp,
            }
            
            # 执行计算
            result = eval(expression, {"__builtins__": {}}, safe_dict)
            
            # 格式化结果
            precision = self.config.get("precision", 2)
            if isinstance(result, float):
                result = round(result, precision)
            
            return {
                "expression": expression,
                "result": result,
                "type": type(result).__name__
            }
            
        except Exception as e:
            return {
                "error": f"计算失败: {str(e)}",
                "expression": expression,
                "suggestion": "请检查表达式语法是否正确"
            }
    
    def _convert_unit(self, value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
        """
        单位转换
        
        Args:
            value: 数值
            from_unit: 原单位
            to_unit: 目标单位
        
        Returns:
            转换结果字典
        """
        logger.info(f"Converting {value} {from_unit} to {to_unit}")
        
        # 单位转换表
        conversions = {
            # 长度转换（以米为基准）
            "km_to_m": 1000,
            "m_to_km": 0.001,
            "cm_to_m": 0.01,
            "m_to_cm": 100,
            "mm_to_m": 0.001,
            "m_to_mm": 1000,
            
            # 重量转换（以千克为基准）
            "kg_to_g": 1000,
            "g_to_kg": 0.001,
            "mg_to_g": 0.001,
            "g_to_mg": 1000,
        }
        
        # 温度转换（特殊处理）
        if from_unit == "celsius" and to_unit == "fahrenheit":
            result = value * 9/5 + 32
            return {
                "original": f"{value}°C",
                "converted": f"{round(result, 2)}°F",
                "formula": "°F = °C × 9/5 + 32"
            }
        
        if from_unit == "fahrenheit" and to_unit == "celsius":
            result = (value - 32) * 5/9
            return {
                "original": f"{value}°F",
                "converted": f"{round(result, 2)}°C",
                "formula": "°C = (°F - 32) × 5/9"
            }
        
        # 查找转换因子
        key = f"{from_unit}_to_{to_unit}"
        if key not in conversions:
            return {
                "error": f"不支持从 {from_unit} 转换到 {to_unit}",
                "suggestion": "请检查单位名称是否正确"
            }
        
        result = value * conversions[key]
        
        return {
            "original": f"{value} {from_unit}",
            "converted": f"{round(result, 2)} {to_unit}",
            "factor": conversions[key]
        }
    
    def _math_function(self, function: str, value: float) -> Dict[str, Any]:
        """
        执行数学函数
        
        Args:
            function: 函数名称
            value: 输入值
        
        Returns:
            计算结果字典
        """
        logger.info(f"Calculating {function}({value})")
        
        math_functions = {
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "sqrt": math.sqrt,
            "abs": abs,
            "ceil": math.ceil,
            "floor": math.floor,
        }
        
        if function not in math_functions:
            return {
                "error": f"不支持的数学函数: {function}",
                "supported": list(math_functions.keys())
            }
        
        try:
            func = math_functions[function]
            result = func(value)
            
            precision = self.config.get("precision", 2)
            if isinstance(result, float):
                result = round(result, precision)
            
            return {
                "function": function,
                "input": value,
                "result": result
            }
            
        except Exception as e:
            return {
                "error": f"计算失败: {str(e)}",
                "function": function,
                "input": value
            }
    
    def on_load(self):
        """技能加载时的回调"""
        logger.info(f"Calculate skill v{self.version} loaded with precision={self.config.get('precision')}")
    
    def on_unload(self):
        """技能卸载时的回调"""
        logger.info(f"Calculate skill unloaded")
