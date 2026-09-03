import json
import requests
from datetime import datetime


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学计算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 '2 + 3 * 4'"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网页信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


def execute_tool(name, arguments):
    args = json.loads(arguments) if isinstance(arguments, str) else arguments

    if name == "get_current_time":
        return json.dumps({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    if name == "calculate":
        try:
            result = eval(args["expression"], {"__builtins__": {}}, {})
            return json.dumps({"result": result})
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "web_search":
        return json.dumps({
            "results": f"关于「{args['query']}」的搜索结果（模拟数据，请接入实际搜索API）"
        })

    return json.dumps({"error": f"未知工具: {name}"})
