"""
工具服务：定义 AI 可调用的工具，并提供执行逻辑
新增：代码执行、数据库查询、文件操作工具
"""
import json
import logging
import subprocess
import sys
import os
import re
import tempfile
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)


def _build_tools_list():
    """根据配置动态构建工具列表"""
    tools = [
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

    # 网络搜索（按配置决定是否启用）
    if current_app.config.get("WEB_SEARCH_ENABLED", False):
        tools.append({
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "搜索网页信息，获取最新数据和资讯",
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
        })

    # 代码执行（按配置决定是否启用）
    if current_app.config.get("CODE_EXEC_ENABLED", True):
        tools.append({
            "type": "function",
            "function": {
                "name": "execute_code",
                "description": "执行 Python 代码并返回输出结果。可用于数据分析、文本处理、计算等任务。代码会在安全沙箱中运行，超时时间为10秒。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "要执行的 Python 代码"
                        }
                    },
                    "required": ["code"]
                }
            }
        })

    # 数据库查询（始终可用，但内部做了安全检查）
    tools.append({
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "执行 SQL 查询（只读 SELECT）。可用于查询项目数据库中的数据。仅允许 SELECT 语句。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL 查询语句（仅支持 SELECT）"
                    }
                },
                "required": ["sql"]
            }
        }
    })

    # 文件操作（始终可用）
    tools.append({
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取知识库中的文件内容。需要提供文件名（不是路径）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "知识库中的文件名"
                    }
                },
                "required": ["filename"]
            }
        }
    })

    return tools


# 工具列表（延迟初始化，避免 Flask 应用上下文问题）
_TOOLS_CACHE = None

def get_tools():
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = _build_tools_list()
    return _TOOLS_CACHE


def execute_tool(name, arguments):
    """执行工具调用"""
    args = json.loads(arguments) if isinstance(arguments, str) else arguments

    if name == "get_current_time":
        return json.dumps({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    if name == "calculate":
        return _exec_calculate(args)

    if name == "web_search":
        return _exec_web_search(args)

    if name == "knowledge_search":
        return _exec_knowledge_search(args)

    if name == "execute_code":
        return _exec_code(args)

    if name == "query_database":
        return _exec_query_database(args)

    if name == "read_file":
        return _exec_read_file(args)

    return json.dumps({"error": f"未知工具: {name}"})


# ============================================================
# 工具实现
# ============================================================

def _exec_calculate(args):
    """数学计算（安全的 eval）"""
    try:
        expression = args["expression"]
        # 安全白名单：只允许数字和基本运算符
        allowed = re.compile(r'^[\d\s\+\-\*\/\(\)\.\%\*]+$')
        if not allowed.match(expression):
            return json.dumps({"error": "表达式包含不允许的字符"})
        result = eval(expression, {"__builtins__": {}}, {})
        return json.dumps({"result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _exec_web_search(args):
    """网络搜索（多源支持：Tavily/Bing/DuckDuckGo，自动降级）"""
    if not current_app.config.get("WEB_SEARCH_ENABLED", False):
        return json.dumps({"message": "网络搜索未启用", "results": []})

    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "搜索关键词不能为空"})

    max_results = current_app.config.get("SEARCH_MAX_RESULTS", 5)
    provider = current_app.config.get("WEB_SEARCH_PROVIDER", "duckduckgo")
    tavily_api_key = current_app.config.get("TAVILY_API_KEY", "")

    # 优先级：Tavily（配了 key）→ Bing（国内默认）→ DuckDuckGo（兜底）
    if tavily_api_key:
        result = _tavily_search(query, tavily_api_key, max_results)
        if "失败" not in result and "未找到" not in result:
            return result

    # 国内默认用 Bing（DuckDuckGo 被墙）
    result = _bing_search(query, max_results)
    if "失败" not in result and "未找到" not in result:
        return result

    # Bing 失败兜底试 DuckDuckGo
    return _ddg_search(query, max_results)


def _tavily_search(query: str, api_key: str, max_results: int) -> str:
    """Tavily 搜索（最稳定，需要 API key，免费 1000 次/月）"""
    try:
        from tavily import TavilyClient
    except ImportError:
        return "错误：未安装 tavily-python，请执行：pip install tavily-python"

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=max_results)
    except Exception as e:
        logger.warning(f"Tavily 搜索失败：{e}")
        return f"Tavily 搜索失败：{e}"

    results = response.get("results", [])
    if not results:
        return "未找到相关结果，建议换关键词重试。"

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append({
            "title": r.get("title", ""),
            "snippet": r.get("content", ""),
            "url": r.get("url", ""),
        })

    return json.dumps({"results": formatted}, ensure_ascii=False)


def _bing_search(query: str, max_results: int) -> str:
    """Bing 中国搜索（免费，无需 key，国内可用）"""
    try:
        import requests
        from lxml import html
    except ImportError:
        return "错误：未安装 requests 或 lxml，请执行：pip install requests lxml"

    try:
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": max_results * 2},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=10,
        )
        resp.raise_for_status()
        tree = html.fromstring(resp.text)
        results = []
        for li in tree.xpath('//li[@class="b_algo"]')[:max_results]:
            title_a = li.xpath(".//h2/a")
            if not title_a:
                continue
            title = title_a[0].text_content().strip()
            link = title_a[0].get("href", "")
            snippet_nodes = li.xpath(
                './/div[contains(@class,"b_caption")]//p//text()'
            )
            body = " ".join(
                s.strip() for s in snippet_nodes if s.strip()
            )
            results.append({
                "title": title,
                "snippet": body,
                "url": link,
            })

        if not results:
            return "未找到相关结果，建议换关键词重试。"

        return json.dumps({"results": results}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Bing 搜索失败：{e}")
        return f"Bing 搜索失败：{e}"


def _ddg_search(query: str, max_results: int) -> str:
    """DuckDuckGo 免费搜索（国内通常不可用，仅作兜底）"""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "错误：未安装 duckduckgo-search，请执行：pip install duckduckgo-search"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败（国内通常被墙）：{e}")
        return f"DuckDuckGo 搜索失败（国内通常被墙）：{e}\n建议配置 TAVILY_API_KEY 使用更稳定的搜索。"

    if not results:
        return "未找到相关结果，建议换关键词重试。"

    formatted = []
    for r in results:
        formatted.append({
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "url": r.get("href", ""),
        })

    return json.dumps({"results": formatted}, ensure_ascii=False)


def _exec_knowledge_search(args):
    """知识库检索"""
    from app.services.rag_service import search
    results = search(args["query"])
    if not results:
        return json.dumps({"message": "知识库中未找到相关内容", "results": []})
    formatted = [
        {"source": r["filename"], "content": r["content"]}
        for r in results
    ]
    return json.dumps({"results": formatted}, ensure_ascii=False)


def _exec_code(args):
    """Python 代码执行（沙箱）"""
    if not current_app.config.get("CODE_EXEC_ENABLED", True):
        return json.dumps({"error": "代码执行未启用"})

    code = args.get("code", "")
    if not code.strip():
        return json.dumps({"error": "代码不能为空"})

    timeout = current_app.config.get("CODE_EXEC_TIMEOUT", 10)

    # 安全检查：禁止危险操作
    forbidden = [
        "os.system", "subprocess", "__import__", "eval(", "exec(",
        "open(", "shutil", "socket", "requests", "urllib",
        "ctypes", "multiprocessing", "threading",
    ]
    for f in forbidden:
        if f in code:
            return json.dumps({"error": f"代码包含禁止的操作: {f}"})

    # 在子进程中执行
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        os.unlink(tmp_path)

        output = {
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:1000] if result.stderr else "",
            "returncode": result.returncode,
        }
        return json.dumps(output, ensure_ascii=False)

    except subprocess.TimeoutExpired:
        os.unlink(tmp_path) if os.path.exists(tmp_path) else None
        return json.dumps({"error": f"代码执行超时（{timeout}秒）"})
    except Exception as e:
        return json.dumps({"error": f"代码执行失败: {str(e)}"})


def _exec_query_database(args):
    """数据库查询（只读 SELECT）"""
    sql = args.get("sql", "").strip()
    if not sql:
        return json.dumps({"error": "SQL 语句不能为空"})

    # 安全检查：只允许 SELECT
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return json.dumps({"error": "仅允许 SELECT 查询"})

    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "GRANT", "REVOKE"]
    for kw in forbidden_keywords:
        if kw in sql_upper.split():
            return json.dumps({"error": f"SQL 包含禁止操作: {kw}"})

    try:
        from app.extensions import db
        result = db.session.execute(db.text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return json.dumps({
            "columns": columns,
            "rows": rows[:50],  # 最多返回 50 行
            "total": len(rows),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"查询失败: {str(e)}"})


def _exec_read_file(args):
    """读取知识库中的文件"""
    filename = args.get("filename", "")
    if not filename:
        return json.dumps({"error": "文件名不能为空"})

    # 安全检查：防止路径遍历
    if ".." in filename or "/" in filename or "\\" in filename:
        return json.dumps({"error": "无效的文件名"})

    # 在知识库文档中查找
    from app.models import Document, DocumentChunk
    doc = Document.query.filter_by(filename=filename).first()
    if not doc:
        return json.dumps({"error": f"文件 {filename} 不在知识库中"})

    chunks = DocumentChunk.query.filter_by(document_id=doc.id).order_by(DocumentChunk.chunk_index).all()
    content = "\n".join(c.content for c in chunks)
    return json.dumps({
        "filename": filename,
        "content": content[:5000],  # 限制返回长度
        "truncated": len(content) > 5000,
    }, ensure_ascii=False)
