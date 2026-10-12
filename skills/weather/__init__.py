"""
天气查询技能

提供天气查询功能，支持多个城市和温度单位
"""
from app.skills.base import BaseSkill
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class Skill(BaseSkill):
    """天气查询技能实现"""
    
    name = "weather"
    version = "1.0.0"
    description = "查询指定城市的天气信息"
    author = "System"
    
    def _register_tools(self):
        """注册天气查询工具"""
        
        # 工具 1: 获取当前天气
        self.register_tool(
            name="get_current_weather",
            handler=self._get_current_weather,
            schema={
                "type": "function",
                "description": "获取指定城市的当前天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，例如：北京、上海、纽约"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                            "description": "温度单位，默认为 celsius（摄氏度）"
                        }
                    },
                    "required": ["city"]
                }
            }
        )
        
        # 工具 2: 获取天气预报
        self.register_tool(
            name="get_weather_forecast",
            handler=self._get_weather_forecast,
            schema={
                "type": "function",
                "description": "获取指定城市未来几天的天气预报",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称"
                        },
                        "days": {
                            "type": "integer",
                            "description": "预报天数，默认 3 天",
                            "minimum": 1,
                            "maximum": 7
                        }
                    },
                    "required": ["city"]
                }
            }
        )
    
    def _get_current_weather(self, city: str, unit: str = None) -> Dict[str, Any]:
        """
        获取当前天气
        
        Args:
            city: 城市名称
            unit: 温度单位（celsius/fahrenheit）
        
        Returns:
            天气信息字典
        """
        if not unit:
            unit = self.config.get('default_unit', 'celsius')
        
        logger.info(f"Getting current weather for {city} in {unit}")
        
        # 这里使用模拟数据，实际项目中应调用真实天气 API
        mock_data = {
            "北京": {"temp": 22, "humidity": 45, "wind": "NE 3m/s", "condition": "晴"},
            "上海": {"temp": 25, "humidity": 65, "wind": "SE 2m/s", "condition": "多云"},
            "广州": {"temp": 28, "humidity": 75, "wind": "S 4m/s", "condition": "阴"},
            "深圳": {"temp": 27, "humidity": 70, "wind": "SE 3m/s", "condition": "小雨"},
            "纽约": {"temp": 18, "humidity": 55, "wind": "W 5m/s", "condition": "晴"},
        }
        
        if city not in mock_data:
            return {
                "error": f"无法找到城市 '{city}' 的天气信息",
                "suggestion": "请检查城市名称是否正确，或尝试使用英文名称"
            }
        
        weather = mock_data[city]
        temp = weather["temp"]
        
        # 温度单位转换
        if unit == "fahrenheit":
            temp = temp * 9 / 5 + 32
            unit_symbol = "°F"
        else:
            unit_symbol = "°C"
        
        return {
            "city": city,
            "temperature": f"{temp}{unit_symbol}",
            "humidity": f"{weather['humidity']}%",
            "wind": weather["wind"],
            "condition": weather["condition"],
            "update_time": "2026-10-11 09:23:00"
        }
    
    def _get_weather_forecast(self, city: str, days: int = 3) -> Dict[str, Any]:
        """
        获取天气预报
        
        Args:
            city: 城市名称
            days: 预报天数
        
        Returns:
            天气预报信息字典
        """
        logger.info(f"Getting {days}-day forecast for {city}")
        
        # 模拟预报数据
        mock_forecast = {
            "北京": [
                {"date": "2026-10-12", "high": 24, "low": 15, "condition": "晴"},
                {"date": "2026-10-13", "high": 23, "low": 14, "condition": "多云"},
                {"date": "2026-10-14", "high": 20, "low": 12, "condition": "小雨"},
                {"date": "2026-10-15", "high": 22, "low": 13, "condition": "晴"},
                {"date": "2026-10-16", "high": 25, "low": 16, "condition": "晴"},
                {"date": "2026-10-17", "high": 26, "low": 17, "condition": "多云"},
                {"date": "2026-10-18", "high": 24, "low": 15, "condition": "阴"},
            ]
        }
        
        if city not in mock_forecast:
            return {
                "error": f"无法找到城市 '{city}' 的天气预报",
                "suggestion": "请检查城市名称是否正确"
            }
        
        forecast_data = mock_forecast[city][:days]
        
        return {
            "city": city,
            "forecast_days": days,
            "forecast": forecast_data
        }
    
    def on_load(self):
        """技能加载时的回调"""
        logger.info(f"Weather skill v{self.version} loaded with config: {self.config}")
    
    def on_unload(self):
        """技能卸载时的回调"""
        logger.info(f"Weather skill unloaded")
