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
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "从知识库中检索与用户问题相关的文档内容。当用户的问题可能涉及已上传的文档资料时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用于在知识库中检索的查询内容，应该是用户问题的核心关键词或摘要"
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

    if name == "knowledge_search":
        from app.services.rag_service import search
        results = search(args["query"])
        if not results:
            return json.dumps({"message": "知识库中未找到相关内容", "results": []})
        formatted = [
            {
                "source": r["filename"],
                "content": r["content"],
            }
            for r in results
        ]
        return json.dumps({"results": formatted}, ensure_ascii=False)

    return json.dumps({"error": f"未知工具: {name}"})
